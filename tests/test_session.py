"""Test dell'orchestratore: la prova che la catena completa ignora gli estranei.

Non serve microfono: i frame vengono spinti a mano nel ciclo audio, esattamente
come farebbe la scheda audio.
"""

from __future__ import annotations

import numpy as np
import pytest

from conftest import SR, speech
from jarvis.audio.capture import MicrophoneStream
from jarvis.audio.playback import NullSpeaker
from jarvis.config import Config
from jarvis.session.orchestrator import TextSession, VoiceSession

FRAME_MS = 20
FRAME_LEN = SR * FRAME_MS // 1000


class FakeVAD:
    """Considera parlato tutto cio' che supera una soglia di energia."""

    def __init__(self, threshold: float = 0.01):
        self.threshold = threshold

    def is_speech(self, frame: np.ndarray) -> bool:
        return float(np.sqrt(np.mean(np.square(frame)))) > self.threshold


class FakeTranscriber:
    def __init__(self, text: str = "quanto posso offrire per Lautaro"):
        self.text = text
        self.calls: list[np.ndarray] = []

    def transcribe(self, audio, sample_rate=SR):
        from jarvis.asr import Transcript

        self.calls.append(np.asarray(audio))
        return Transcript(text=self.text, duration=len(audio) / sample_rate)


class FakeAgent:
    """Agente finto: risponde a pezzi, come farebbe lo streaming vero."""

    def __init__(self, reply: str = "Fino a centottanta crediti. Oltre resti scoperto."):
        self.reply = reply
        self.asked: list[str] = []

    def respond(self, text: str):
        self.asked.append(text)
        for word in self.reply.split(" "):
            yield word + " "

    def respond_text(self, text: str) -> str:
        return "".join(self.respond(text))

    def reset(self) -> None:
        self.asked.clear()


class FakeTTS:
    def __init__(self):
        self.spoken: list[str] = []

    def synthesize(self, text: str):
        from jarvis.tts import Audio

        self.spoken.append(text)
        return Audio(np.zeros(0, dtype=np.float32), 22050)


def build_session(verifier, *, transcriber=None, agent=None, cfg_overrides=None):
    cfg = Config({
        "audio": {"sample_rate": SR, "frame_ms": FRAME_MS},
        "vad": {"min_speech_ms": 100, "min_silence_ms": 200, "pre_roll_ms": 100},
        "session": {"barge_in": True, "echo_guard": False},
        "log": {},
        **(cfg_overrides or {}),
    })
    mic = MicrophoneStream(SR, FRAME_MS)
    return VoiceSession(
        mic=mic,
        vad=FakeVAD(),
        verifier=verifier,
        transcriber=transcriber or FakeTranscriber(),
        agent=agent or FakeAgent(),
        synthesizer=FakeTTS(),
        speaker=NullSpeaker(),
        cfg=cfg,
    )


def feed(session: VoiceSession, audio: np.ndarray, *, silence_ms: int = 400) -> None:
    """Spinge l'audio nel ciclo, poi il silenzio che chiude il turno."""
    for start in range(0, audio.size - FRAME_LEN + 1, FRAME_LEN):
        session._process_frame(audio[start : start + FRAME_LEN])
    for _ in range(silence_ms // FRAME_MS):
        session._process_frame(np.zeros(FRAME_LEN, dtype=np.float32))
    if session._worker is not None:
        session._worker.join(timeout=5.0)


# ------------------------------------------------------- il caso richiesto

def test_risponde_a_me(verifier):
    session = build_session(verifier)
    feed(session, speech(0, 3.0))

    assert session.stats.turni_miei == 1
    assert session.agent.asked == ["quanto posso offrire per Lautaro"]
    assert session.synthesizer.spoken, "l'assistente non ha detto niente"


@pytest.mark.parametrize("estraneo", [1, 2, 3, 5])
def test_non_risponde_agli_altri(verifier, estraneo):
    session = build_session(verifier)
    feed(session, speech(estraneo, 3.0))

    assert session.stats.turni_miei == 0
    assert session.agent.asked == []
    assert session.synthesizer.spoken == []


def test_stanza_affollata_una_sola_risposta(verifier):
    """Sette persone parlano, io una volta sola: una sola risposta."""
    session = build_session(verifier)
    for persona in (3, 1, 0, 5, 2, 7, 4):
        feed(session, speech(persona, 3.0))

    assert session.stats.turni_miei == 1
    assert len(session.agent.asked) == 1
    assert session.stats.turni_ignorati >= 6


def test_la_voce_estranea_non_arriva_mai_alla_trascrizione(verifier):
    """Il risparmio non e' solo di token: e' latenza che resta disponibile per me."""
    transcriber = FakeTranscriber()
    session = build_session(verifier, transcriber=transcriber)
    for persona in (1, 2, 4, 6):
        feed(session, speech(persona, 3.0))

    assert transcriber.calls == []


def test_l_estraneo_viene_scartato_prima_della_fine_della_frase(verifier):
    """Rifiuto precoce: dopo poche finestre il turno e' gia' chiuso."""
    session = build_session(verifier)
    lunga = speech(2, 6.0)
    for start in range(0, lunga.size - FRAME_LEN + 1, FRAME_LEN):
        session._process_frame(lunga[start : start + FRAME_LEN])
        if session.stats.turni_ignorati:
            break
    consumato = start / SR
    assert session.stats.turni_ignorati == 1
    assert consumato < 3.0, f"ci ha messo {consumato:.1f}s a capire che non ero io"


# ------------------------------------------------------------- interruzione

def test_posso_interrompere_l_assistente(verifier):
    session = build_session(verifier)
    session.speaker._playing.set()      # simulo la riproduzione in corso
    feed(session, speech(0, 3.0))

    assert session.stats.interruzioni >= 1


def test_un_estraneo_non_interrompe_l_assistente(verifier):
    session = build_session(verifier)
    session.speaker._playing.set()
    feed(session, speech(4, 3.0))

    assert session.stats.interruzioni == 0


# ---------------------------------------------------------------- robustezza

def test_trascrizione_vuota_non_produce_risposta(verifier):
    session = build_session(verifier, transcriber=FakeTranscriber(""))
    feed(session, speech(0, 3.0))
    assert session.agent.asked == []


def test_un_errore_dell_agente_non_fa_cadere_la_sessione(verifier):
    class AgenteRotto:
        def respond(self, text):
            raise RuntimeError("modello non raggiungibile")

    session = build_session(verifier, agent=AgenteRotto())
    feed(session, speech(0, 3.0))       # non deve sollevare
    assert session.stats.turni_miei == 1


def test_il_silenzio_alimenta_la_stima_del_rumore(verifier):
    session = build_session(verifier)
    prima = session.verifier.noise.value_db
    for _ in range(50):
        session._process_frame(np.full(FRAME_LEN, 0.002, dtype=np.float32))
    assert session.verifier.noise.value_db != prima


def test_riassunto_della_sessione(verifier):
    session = build_session(verifier)
    feed(session, speech(0, 3.0))
    feed(session, speech(1, 3.0))
    riassunto = session.stats.summary()
    assert "turni miei: 1" in riassunto
    assert "latenza media" in riassunto


# ------------------------------------------------------------ modo testuale

def test_sessione_testuale():
    agent = FakeAgent("Fino a centottanta.")
    assert TextSession(agent).ask("quanto offro?") == "Fino a centottanta. "
    assert agent.asked == ["quanto offro?"]


# ----------------------------------------- sostituzione di un turno in corso

def test_un_turno_nuovo_sostituisce_quello_in_corso(verifier):
    """Se riprendo la parola mentre risponde, la vecchia risposta viene annullata."""
    import threading

    partita = threading.Event()
    rilascia = threading.Event()

    class AgenteLento:
        """Il primo turno resta appeso: cosi' il secondo lo trova ancora in corso."""

        def __init__(self):
            self.asked = []

        def respond(self, text):
            self.asked.append(text)
            if len(self.asked) == 1:
                partita.set()
                rilascia.wait(timeout=5.0)
            for parola in "risposta. ".split(" "):
                yield parola + " "

    agent = AgenteLento()
    session = build_session(verifier, agent=agent)

    audio = speech(0, 3.0)
    for start in range(0, audio.size - FRAME_LEN + 1, FRAME_LEN):
        session._process_frame(audio[start : start + FRAME_LEN])
    for _ in range(20):
        session._process_frame(np.zeros(FRAME_LEN, dtype=np.float32))

    assert partita.wait(timeout=5.0), "il primo turno non e' partito"
    vecchia_generazione = session._generation
    vecchio_cancel = session._cancel

    feed(session, speech(0, 3.0))           # secondo turno: sostituisce il primo
    rilascia.set()

    assert session._generation > vecchia_generazione
    assert vecchio_cancel.is_set(), "il turno vecchio non e' stato annullato"
    assert session._cancel is not vecchio_cancel, "il turno nuovo ha ereditato il segnale del vecchio"


def test_stop_annulla_il_turno_in_corso(verifier):
    session = build_session(verifier)
    feed(session, speech(0, 3.0))
    session.mic.stop()
    session.stop()
    assert session._cancel.is_set()
