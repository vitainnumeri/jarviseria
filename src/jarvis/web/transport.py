"""Sorgente e uscita audio che viaggiano su WebSocket invece che sulla scheda audio.

L'orchestratore non sa e non deve sapere da dove arrivano i frame: gli basta
qualcosa che risponda a `read()` e qualcosa su cui riprodurre. Qui ci sono le
due implementazioni di rete, con la stessa interfaccia del microfono e
dell'altoparlante locali, cosi' la pipeline (VAD, biometria, ASR, modello,
sintesi) resta identica byte per byte.

Formato sul filo, in entrambe le direzioni: PCM 16 bit little-endian, mono.
    verso il server   16 kHz (il browser ricampiona prima di spedire)
    verso il telefono 24 kHz (compromesso fra qualita' della voce e banda)
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time

import numpy as np

from ..audio.dsp import resample_linear, to_float32, to_int16
from ..audio.playback import Speaker
from ..utils.logging import get_logger

log = get_logger(__name__)

UPLINK_RATE = 16000
DOWNLINK_RATE = 24000
# Blocchi di invio da ~120 ms: abbastanza corti perche' una barge-in interrompa
# quasi subito, abbastanza lunghi da non inondare il socket di pacchetti.
SEND_CHUNK_MS = 120


class RemoteAudioSource:
    """Frame che arrivano dal telefono, presentati come un microfono.

    Il browser manda blocchi di dimensione variabile (dipende dal carico e dal
    sistema operativo); qui vengono ricuciti e riemessi in frame di durata
    esatta, che e' cio' che VAD e segmentatore si aspettano.
    """

    def __init__(self, sample_rate: int = UPLINK_RATE, frame_ms: int = 20,
                 max_queue_frames: int = 200):
        self.sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.frame_len = int(self.sample_rate * self.frame_ms / 1000)
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue_frames)
        self._pending = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._running = threading.Event()
        self.dropped_frames = 0
        self.received_seconds = 0.0

    # ------------------------------------------------------------ interfaccia
    def start(self) -> "RemoteAudioSource":
        self._running.set()
        return self

    def stop(self) -> None:
        self._running.clear()

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ---------------------------------------------------------------- ingresso
    def push_pcm(self, payload: bytes) -> int:
        """Accoda PCM 16 bit dal telefono. Restituisce i frame prodotti."""
        if not payload:
            return 0
        samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        return self.push_samples(samples)

    def push_samples(self, samples: np.ndarray) -> int:
        """Come `push_pcm`, ma partendo da campioni float gia' decodificati."""
        with self._lock:
            self._pending = np.concatenate([self._pending, np.asarray(samples, dtype=np.float32)])
            frames = []
            while self._pending.size >= self.frame_len:
                frames.append(self._pending[: self.frame_len].copy())
                self._pending = self._pending[self.frame_len :]

        self.received_seconds += len(frames) * self.frame_ms / 1000.0
        for frame in frames:
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                # Meglio perdere audio vecchio che accumulare ritardo: in una
                # conversazione il ritardo si sente, un buco di 20 ms no.
                self.dropped_frames += 1
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(frame)
                except queue.Empty:  # pragma: no cover - corsa improbabile
                    pass
        return len(frames)


class WebSocketSpeaker(Speaker):
    """Altoparlante remoto: invece di suonare, spedisce al telefono.

    L'invio e' ritmato quasi in tempo reale invece che in un colpo solo. Serve a
    due cose: `is_playing` resta veritiero (e la barge-in si basa su quello) e
    un'interruzione butta via solo il poco che era gia' partito.
    """

    def __init__(self, send_bytes, send_control, loop: asyncio.AbstractEventLoop,
                 reference_seconds: float = 1.0):
        super().__init__(sample_rate=DOWNLINK_RATE, reference_seconds=reference_seconds)
        self._send_bytes = send_bytes
        self._send_control = send_control
        self._loop = loop
        self.chunk_len = int(DOWNLINK_RATE * SEND_CHUNK_MS / 1000)
        self._ducked = False

    # ------------------------------------------------------------------ invio
    def _send_audio(self, payload: bytes) -> None:
        """Invio bloccante dei blocchi audio.

        Qui aspettare e' giusto: se il socket e' saturo, rallentare la sintesi e'
        meglio che accumulare secondi di ritardo sul telefono.
        """
        try:
            asyncio.run_coroutine_threadsafe(self._send_bytes(payload), self._loop).result(timeout=5.0)
        except Exception as exc:  # pragma: no cover - socket chiuso a meta'
            log.debug("invio audio al telefono fallito: %s", exc)
            self._stop.set()

    def _control(self, message: dict) -> None:
        """Invio dei messaggi di controllo, senza attendere.

        `duck` arriva dal ciclo audio, che gira ogni 20 ms e non deve fermarsi
        ad aspettare la rete nemmeno per un istante.
        """
        try:
            asyncio.run_coroutine_threadsafe(self._send_control(message), self._loop)
        except Exception as exc:  # pragma: no cover - loop gia' chiuso
            log.debug("controllo '%s' non inviato: %s", message.get("type"), exc)

    def play(self, audio: np.ndarray, sample_rate: int | None = None) -> bool:
        audio = to_float32(np.asarray(audio)).ravel()
        if audio.size == 0:
            return not self._stop.is_set()
        audio = resample_linear(audio, sample_rate or DOWNLINK_RATE, DOWNLINK_RATE)

        self._stop.clear()
        self._playing.set()
        try:
            for start in range(0, audio.size, self.chunk_len):
                if self._stop.is_set():
                    log.debug("riproduzione interrotta (barge-in dal telefono)")
                    return False
                with self._lock:
                    gain = self._gain
                chunk = audio[start : start + self.chunk_len] * gain
                self._reference.extend(chunk.tolist())
                self._send_audio(to_int16(chunk).tobytes())
                # Ritmo l'invio sulla durata reale del blocco, meno un margine
                # perche' il telefono abbia sempre un po' di scorta in coda.
                time.sleep(chunk.size / DOWNLINK_RATE * 0.75)
            return not self._stop.is_set()
        finally:
            self._playing.clear()
            self.unduck()

    # --------------------------------------------------------------- controlli
    def stop(self) -> None:
        already = self._stop.is_set()
        super().stop()
        if not already and self._playing.is_set():
            # Il telefono ha gia' dei blocchi in coda: deve buttarli via subito,
            # altrimenti continuerebbe a parlare sopra di me.
            self._control({"type": "flush"})

    def duck(self, gain_db: float) -> None:
        """Abbassa il volume sul telefono, una volta sola per abbassamento.

        Il ciclo audio la richiama a ogni frame di parlato: senza questa guardia
        manderebbe cinquanta messaggi al secondo per dire la stessa cosa.
        """
        super().duck(gain_db)
        if not self._ducked:
            self._ducked = True
            self._control({"type": "duck", "db": gain_db})

    def unduck(self) -> None:
        super().unduck()
        if self._ducked:
            self._ducked = False
            self._control({"type": "unduck"})

    def close(self) -> None:
        return None
