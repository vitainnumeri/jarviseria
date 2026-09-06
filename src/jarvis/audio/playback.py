"""Riproduzione con interruzione immediata (barge-in) e ducking.

Espone anche l'ultimo audio riprodotto come "segnale di riferimento": serve al
guardiano dell'eco per capire se il microfono sta riascoltando il bot.
"""

from __future__ import annotations

import threading
from collections import deque

import numpy as np

from ..utils.logging import get_logger
from .dsp import to_float32

log = get_logger(__name__)


class Speaker:
    """Uscita audio a blocchi, con stop istantaneo.

    L'unita' di riproduzione e' il blocco da ~20 ms: uno `stop()` interrompe
    entro un blocco, quindi l'utente non deve mai aspettare la fine della frase
    per riprendere la parola.
    """

    def __init__(
        self,
        sample_rate: int = 22050,
        device: int | str | None = None,
        block_ms: int = 20,
        reference_seconds: float = 1.0,
    ):
        self.sample_rate = int(sample_rate)
        self.device = device
        self.block_len = max(1, int(self.sample_rate * block_ms / 1000))
        self._stop = threading.Event()
        self._playing = threading.Event()
        self._gain = 1.0
        self._lock = threading.Lock()
        # Anello del segnale riprodotto, per la correlazione d'eco.
        self._reference = deque(maxlen=int(self.sample_rate * reference_seconds))
        self._stream = None

    # ---------------------------------------------------------------- stato
    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    def duck(self, gain_db: float) -> None:
        """Abbassa il volume (dB negativi) per sentire meglio la barge-in."""
        with self._lock:
            self._gain = float(10.0 ** (gain_db / 20.0))

    def unduck(self) -> None:
        with self._lock:
            self._gain = 1.0

    def stop(self) -> None:
        """Interrompe subito la riproduzione in corso."""
        self._stop.set()

    def reference_signal(self, samples: int) -> np.ndarray:
        """Ultimi campioni inviati all'altoparlante (riferimento anti-eco)."""
        if not self._reference:
            return np.zeros(0, dtype=np.float32)
        buf = np.fromiter(self._reference, dtype=np.float32)
        return buf[-samples:] if samples > 0 else buf

    # ------------------------------------------------------------ playback
    def _ensure_stream(self, sample_rate: int):  # pragma: no cover - I/O
        import sounddevice as sd

        if self._stream is not None and self.sample_rate == sample_rate:
            return self._stream
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        self.sample_rate = int(sample_rate)
        self.block_len = max(1, int(self.sample_rate * 0.02))
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate, device=self.device, channels=1, dtype="float32"
        )
        self._stream.start()
        return self._stream

    def play(self, audio: np.ndarray, sample_rate: int | None = None) -> bool:
        """Riproduce un blocco d'audio. Restituisce False se interrotto.

        La scrittura avviene un blocco alla volta proprio per poter uscire dal
        ciclo appena arriva uno `stop()`.
        """
        audio = to_float32(np.asarray(audio)).ravel()
        if audio.size == 0:
            return True
        stream = self._ensure_stream(sample_rate or self.sample_rate)  # pragma: no cover - I/O
        self._stop.clear()
        self._playing.set()
        try:
            for start in range(0, audio.size, self.block_len):
                if self._stop.is_set():
                    log.debug("riproduzione interrotta (barge-in)")
                    return False
                with self._lock:
                    gain = self._gain
                block = audio[start : start + self.block_len] * gain
                self._reference.extend(block.tolist())
                stream.write(np.ascontiguousarray(block, dtype=np.float32))  # pragma: no cover
            return True
        finally:
            self._playing.clear()
            self.unduck()

    def close(self) -> None:  # pragma: no cover - I/O
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class NullSpeaker(Speaker):
    """Uscita finta per test e modalita' testuale: consuma l'audio e basta."""

    def play(self, audio: np.ndarray, sample_rate: int | None = None) -> bool:
        audio = to_float32(np.asarray(audio)).ravel()
        self._reference.extend(audio[-self._reference.maxlen :].tolist())
        return not self._stop.is_set()

    def close(self) -> None:
        return None
