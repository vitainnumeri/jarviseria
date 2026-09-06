"""L'orchestratore full-duplex: e' qui che il sistema diventa "una telefonata".

Il ciclo audio non si ferma mai. Gira nel thread principale a 20 ms per giro e
non fa niente di lento: ascolta, segmenta, verifica chi parla. Trascrizione,
modello e sintesi vengono eseguiti in un thread separato, cosi' mentre
l'assistente parla il microfono resta vivo e l'utente puo' interromperlo.

Ordine dei controlli su ogni turno (dal piu' economico al piu' costoso):

    guardia d'eco  ->  VAD  ->  campo vicino  ->  biometria  ->  ASR  ->  LLM  ->  TTS

Un estraneo che parla nella stanza si ferma alla biometria, di solito dopo circa
un secondo e mezzo: non arriva mai alla trascrizione, quindi non costa nulla e
non produce nessuna reazione. E' esattamente il comportamento richiesto.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from ..audio.capture import MicrophoneStream
from ..audio.dsp import normalized_xcorr
from ..audio.playback import Speaker
from ..audio.vad import TurnSegmenter, VoiceActivityDetector
from ..speaker.verifier import Decision, SpeakerVerifier
from ..tts import stream_sentences
from ..utils.logging import TranscriptWriter, get_logger
from .wake import WakeWordGate

log = get_logger(__name__)


@dataclass
class SessionStats:
    turni_miei: int = 0
    turni_ignorati: int = 0
    turni_senza_attivazione: int = 0
    interruzioni: int = 0
    eco_bloccata: int = 0
    latenze: list[float] = field(default_factory=list)

    def summary(self) -> str:
        media = f"{sum(self.latenze) / len(self.latenze):.2f}s" if self.latenze else "n/d"
        return (
            f"turni miei: {self.turni_miei} | voci ignorate: {self.turni_ignorati} | "
            f"interruzioni: {self.interruzioni} | eco bloccata: {self.eco_bloccata} | "
            f"latenza media: {media}"
        )


class VoiceSession:
    """Sessione vocale continua con un solo interlocutore autorizzato."""

    def __init__(
        self,
        mic: MicrophoneStream,
        vad: VoiceActivityDetector,
        verifier: SpeakerVerifier,
        transcriber,
        agent,
        synthesizer,
        speaker: Speaker,
        cfg,
    ):
        self.mic = mic
        self.vad = vad
        self.verifier = verifier
        self.transcriber = transcriber
        self.agent = agent
        self.synthesizer = synthesizer
        self.speaker = speaker
        self.cfg = cfg

        self.segmenter = TurnSegmenter(
            sample_rate=mic.sample_rate,
            frame_ms=mic.frame_ms,
            min_speech_ms=int(cfg.get("vad.min_speech_ms", 250)),
            min_silence_ms=int(cfg.get("vad.min_silence_ms", 600)),
            pre_roll_ms=int(cfg.get("vad.pre_roll_ms", 300)),
            max_utterance_s=float(cfg.get("vad.max_utterance_s", 30)),
        )

        self.barge_in = bool(cfg.get("session.barge_in", True))
        self.duck_db = float(cfg.get("session.duck_db", -12.0))
        self.echo_guard = bool(cfg.get("session.echo_guard", True))
        self.echo_threshold = float(cfg.get("session.echo_corr_threshold", 0.45))

        self.wake = WakeWordGate(
            enabled=bool(cfg.get("speaker.wake_word.enabled", False)),
            phrases=cfg.get("speaker.wake_word.phrases"),
            timeout_s=float(cfg.get("speaker.wake_word.timeout_s", 30)),
        )
        self.transcript = TranscriptWriter(cfg.get("log.transcript"))
        self.stats = SessionStats()

        self._stop = threading.Event()
        # Ogni turno ha il proprio segnale di annullamento e il proprio numero:
        # un turno vecchio non deve poter azzerare il segnale di quello nuovo ne'
        # dichiarare finita una risposta che non e' la sua.
        self._lock = threading.Lock()
        self._generation = 0
        self._cancel: threading.Event = threading.Event()
        self._worker: threading.Thread | None = None
        self._window_scores: list = []
        self._last_checked_samples = 0

    # ------------------------------------------------------------ ciclo audio
    def run(self, greeting: str | None = None) -> SessionStats:  # pragma: no cover - I/O
        """Avvia la sessione. Termina con Ctrl-C."""
        self.mic.start()
        try:
            if greeting:
                self._speak(greeting)
            log.info("in ascolto: parlo solo con te")
            while not self._stop.is_set():
                frame = self.mic.read(timeout=0.5)
                if frame is not None:
                    self._process_frame(frame)
        except KeyboardInterrupt:
            log.info("chiusura richiesta")
        finally:
            self.stop()
        return self.stats

    def stop(self) -> None:
        self._stop.set()
        self._cancel_current_turn()
        self.mic.stop()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)

    def _process_frame(self, frame: np.ndarray) -> None:
        """Un frame da 20 ms: il giro piu' caldo del programma."""
        if self._is_echo(frame):
            self.stats.eco_bloccata += 1
            return

        speech = self.vad.is_speech(frame)
        if not speech and self.segmenter.state.name == "SILENCE":
            # Il silenzio serve: e' cosi' che stimiamo il rumore della stanza.
            self.verifier.observe_noise(frame)

        if speech and self.speaker.is_playing and self.barge_in:
            self.speaker.duck(self.duck_db)  # abbasso la voce per sentire meglio

        segment = self.segmenter.push(frame, speech)

        if self.segmenter.state.name == "SPEAKING":
            self._check_speaker_incrementally()
        if segment is not None:
            self._on_segment(segment)

    def _is_echo(self, frame: np.ndarray) -> bool:
        """Vero se il microfono sta riascoltando l'assistente.

        La biometria da sola gia' scarterebbe la voce sintetica (non e' quella
        del proprietario), ma fermarla qui evita di sprecare un'inferenza e,
        soprattutto, evita che l'eco tenga aperto un finto turno.
        """
        if not (self.echo_guard and self.speaker.is_playing):
            return False
        reference = self.speaker.reference_signal(frame.size * 8)
        if reference.size < frame.size:
            return False
        return normalized_xcorr(frame, reference, max_lag=frame.size * 4) >= self.echo_threshold

    # ------------------------------------------------ verifica incrementale
    def _check_speaker_incrementally(self) -> None:
        """Valuta chi sta parlando MENTRE parla, non dopo.

        Ogni `hop_sec` di nuovo audio produce una decisione parziale. Se le
        ultime finestre dicono "non e' lui", il turno viene buttato subito:
        l'assistente resta zitto e il collega accanto non se ne accorge nemmeno.
        """
        audio = self.segmenter.active_audio
        hop = int(self.verifier.cfg.hop_sec * self.verifier.cfg.sample_rate)
        window = int(self.verifier.cfg.window_sec * self.verifier.cfg.sample_rate)
        if audio.size < window or audio.size - self._last_checked_samples < hop:
            return
        self._last_checked_samples = audio.size

        score = self.verifier.score_window(audio[-window:], index=len(self._window_scores))
        self._window_scores.append(score)
        decision = self.verifier.stream_decision(self._window_scores)

        if decision is Decision.STRANGER:
            log.debug(
                "voce estranea scartata dopo %.1fs (punteggio %.2f)",
                audio.size / self.verifier.cfg.sample_rate, score.owner_score,
            )
            self.stats.turni_ignorati += 1
            self._reset_turn_state()
            self.segmenter.abort()
        elif decision is Decision.OWNER and self.speaker.is_playing and self.barge_in:
            # Sono io e l'assistente sta parlando: ha finito di parlare.
            log.info("interruzione: riprendo la parola")
            self.stats.interruzioni += 1
            self._cancel_current_turn()

    def _reset_turn_state(self) -> None:
        self._window_scores = []
        self._last_checked_samples = 0
        self.verifier.reset_turn()

    # -------------------------------------------------------------- turni
    def _on_segment(self, segment) -> None:
        """Turno chiuso: decide se e' mio e, in caso, lo manda in lavorazione."""
        self._reset_turn_state()
        if segment.audio.size == 0:
            return

        result = self.verifier.verify(segment.audio)
        if not result.is_owner:
            self.stats.turni_ignorati += 1
            log.debug("turno ignorato: %s", result.reason)
            return

        # Un turno nuovo sostituisce quello in corso: e' il comportamento giusto
        # quando l'utente riprende la parola invece di aspettare la risposta.
        with self._lock:
            self._cancel.set()
            self.speaker.stop()
            self._generation += 1
            generation = self._generation
            cancel = threading.Event()
            self._cancel = cancel

        audio = result.trimmed_audio if result.trimmed_audio is not None else segment.audio
        self._worker = threading.Thread(
            target=self._handle_turn, args=(audio, result.score, generation, cancel), daemon=True
        )
        self._worker.start()

    def _cancel_current_turn(self) -> None:
        """Ferma la risposta in corso, qualunque essa sia."""
        with self._lock:
            self._cancel.set()
        self.speaker.stop()

    def _handle_turn(self, audio: np.ndarray, score: float, generation: int,
                     cancel: threading.Event) -> None:
        """Trascrivi, ragiona, rispondi. Gira fuori dal ciclo audio.

        `generation` identifica il turno: se nel frattempo ne e' cominciato uno
        nuovo, questo si ferma senza toccare lo stato condiviso.
        """
        started = time.perf_counter()
        try:
            transcript = self.transcriber.transcribe(audio, self.mic.sample_rate)
            if cancel.is_set() or generation != self._generation:
                log.debug("turno %d superato da uno piu' recente", generation)
                return
            if transcript.is_empty:
                log.debug("trascrizione vuota: niente da rispondere")
                return

            passed, text = self.wake.check(transcript.text)
            if not passed:
                log.debug("parola di attivazione mancante: '%s'", transcript.text)
                self.stats.turni_senza_attivazione += 1
                return
            transcript.text = text

            self.stats.turni_miei += 1
            log.info("tu: %s", transcript.text)
            self.transcript.write("utente", transcript.text, punteggio_voce=round(score, 3))

            spoken: list[str] = []
            for sentence in stream_sentences(self.agent.respond(transcript.text)):
                if cancel.is_set():
                    log.debug("risposta troncata: ho ripreso la parola")
                    break
                if not spoken:
                    self.stats.latenze.append(time.perf_counter() - started)
                spoken.append(sentence)
                if not self._speak(sentence, cancel):
                    break  # interrotto durante la riproduzione

            if spoken:
                log.info("assistente: %s", " ".join(spoken))
                self.transcript.write("assistente", " ".join(spoken))
        except Exception:  # pragma: no cover - la telefonata non deve cadere
            log.exception("errore durante il turno")

    def _speak(self, text: str, cancel: threading.Event | None = None) -> bool:
        """Sintetizza e riproduce una frase. False se e' stata interrotta."""
        audio = self.synthesizer.synthesize(text)
        if audio.samples.size == 0:
            return not (cancel is not None and cancel.is_set())
        return self.speaker.play(audio.samples, audio.sample_rate)


class TextSession:
    """Stessa testa, nessun microfono: serve a provare l'agente da tastiera.

    Utile per mettere a punto prompt e strumenti senza combattere anche con
    audio e modelli vocali.
    """

    def __init__(self, agent, transcript_path=None):
        self.agent = agent
        self.transcript = TranscriptWriter(transcript_path)

    def ask(self, text: str) -> str:
        answer = self.agent.respond_text(text)
        self.transcript.write("utente", text)
        self.transcript.write("assistente", answer)
        return answer

    def run(self) -> None:  # pragma: no cover - interattivo
        print("Modalita' testuale. 'esci' per uscire, 'reset' per ripartire da zero.\n")
        while True:
            try:
                text = input("tu> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if text.lower() in {"esci", "exit", "quit"}:
                return
            if text.lower() == "reset":
                self.agent.reset()
                print("(conversazione azzerata)\n")
                continue
            if not text:
                continue
            print("jarvis> ", end="", flush=True)
            for chunk in self.agent.respond(text):
                print(chunk, end="", flush=True)
            print("\n")
