"""Rilevamento di voce (VAD) e segmentazione dei turni.

Il VAD dice soltanto "qui c'e' voce umana": NON dice di chi. La distinzione fra
me e gli altri e' compito di `speaker/`. Qui serve solo a non far girare la
biometria e la trascrizione sul silenzio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..utils.logging import get_logger
from .dsp import NoiseFloor, dbfs, to_float32

log = get_logger(__name__)


class VoiceActivityDetector:
    """Interfaccia comune ai VAD."""

    def is_speech(self, frame: np.ndarray) -> bool:  # pragma: no cover - astratto
        raise NotImplementedError

    def reset(self) -> None:
        return None


class EnergyVAD(VoiceActivityDetector):
    """VAD di riserva basato sull'energia: nessuna dipendenza, qualita' modesta.

    Utile come fallback e nei test; in produzione usa Silero.
    """

    def __init__(self, sample_rate: int = 16000, margin_db: float = 10.0):
        self.sample_rate = sample_rate
        self.margin_db = margin_db
        self.noise = NoiseFloor()

    def is_speech(self, frame: np.ndarray) -> bool:
        level = dbfs(frame)
        speech = level >= self.noise.value_db + self.margin_db
        if not speech:
            self.noise.update(frame)
        return bool(speech)

    def reset(self) -> None:
        self.noise = NoiseFloor()


class SileroVAD(VoiceActivityDetector):
    """VAD neurale Silero: robusto sul brusio di sottofondo, ~1 ms per frame su CPU."""

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.55):
        import torch  # import pigro: pesante
        from silero_vad import load_silero_vad

        self.torch = torch
        self.sample_rate = int(sample_rate)
        self.threshold = float(threshold)
        self.model = load_silero_vad()
        # Silero vuole blocchi di 512 campioni a 16 kHz (32 ms).
        self.window = 512 if self.sample_rate == 16000 else 256
        self._buffer = np.zeros(0, dtype=np.float32)
        self._last_prob = 0.0

    def is_speech(self, frame: np.ndarray) -> bool:  # pragma: no cover - richiede torch
        self._buffer = np.concatenate([self._buffer, to_float32(frame).ravel()])
        speech = False
        while self._buffer.size >= self.window:
            chunk = self._buffer[: self.window]
            self._buffer = self._buffer[self.window :]
            with self.torch.no_grad():
                prob = float(self.model(self.torch.from_numpy(chunk), self.sample_rate).item())
            self._last_prob = prob
            speech = speech or prob >= self.threshold
        return speech

    @property
    def last_probability(self) -> float:
        return self._last_prob

    def reset(self) -> None:  # pragma: no cover - richiede torch
        self._buffer = np.zeros(0, dtype=np.float32)
        if hasattr(self.model, "reset_states"):
            self.model.reset_states()


class WebRTCVAD(VoiceActivityDetector):
    """VAD di WebRTC: leggerissimo, richiede frame di 10/20/30 ms."""

    def __init__(self, sample_rate: int = 16000, aggressiveness: int = 2):
        import webrtcvad

        self.sample_rate = int(sample_rate)
        self.vad = webrtcvad.Vad(int(aggressiveness))

    def is_speech(self, frame: np.ndarray) -> bool:  # pragma: no cover - dipendenza esterna
        from .dsp import to_int16

        return self.vad.is_speech(to_int16(frame).tobytes(), self.sample_rate)


def build_vad(provider: str, sample_rate: int, threshold: float = 0.55) -> VoiceActivityDetector:
    """Costruisce il VAD richiesto, con ripiego su quello a energia."""
    provider = (provider or "silero").lower()
    try:
        if provider == "silero":
            return SileroVAD(sample_rate, threshold)
        if provider == "webrtc":
            return WebRTCVAD(sample_rate)
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        log.warning("VAD '%s' non disponibile (%s): uso il VAD a energia", provider, exc)
    return EnergyVAD(sample_rate)


class TurnState(Enum):
    SILENCE = "silence"
    SPEAKING = "speaking"
    ENDED = "ended"


@dataclass
class Segment:
    """Un turno di parlato grezzo, prima di sapere di chi sia la voce."""

    audio: np.ndarray
    sample_rate: int
    truncated: bool = False

    @property
    def duration(self) -> float:
        return self.audio.size / float(self.sample_rate)


@dataclass
class TurnSegmenter:
    """Macchina a stati che trasforma un flusso di frame in turni di parlato.

    Tiene un `pre_roll` di audio precedente all'inizio del parlato: senza, la
    prima sillaba viene mangiata e sia la biometria sia la trascrizione ne
    soffrono.
    """

    sample_rate: int = 16000
    frame_ms: int = 20
    min_speech_ms: int = 250
    min_silence_ms: int = 600
    pre_roll_ms: int = 300
    max_utterance_s: float = 30.0

    state: TurnState = field(default=TurnState.SILENCE, init=False)
    _speech: list[np.ndarray] = field(default_factory=list, init=False)
    _pre_roll: list[np.ndarray] = field(default_factory=list, init=False)
    _speech_ms: int = field(default=0, init=False)
    _silence_ms: int = field(default=0, init=False)

    @property
    def _pre_roll_frames(self) -> int:
        return max(1, self.pre_roll_ms // max(1, self.frame_ms))

    @property
    def active_audio(self) -> np.ndarray:
        """Audio del turno in corso (per la verifica incrementale del parlante)."""
        return np.concatenate(self._speech) if self._speech else np.zeros(0, dtype=np.float32)

    def push(self, frame: np.ndarray, is_speech: bool) -> Segment | None:
        """Aggiunge un frame; restituisce il segmento quando il turno si chiude."""
        frame = to_float32(frame).ravel()

        if self.state is TurnState.SILENCE:
            self._pre_roll.append(frame)
            if len(self._pre_roll) > self._pre_roll_frames:
                self._pre_roll.pop(0)
            if is_speech:
                self._speech_ms += self.frame_ms
                if self._speech_ms >= self.min_speech_ms:
                    # Turno confermato: parto dal pre-roll, non dal frame corrente.
                    self.state = TurnState.SPEAKING
                    self._speech = list(self._pre_roll)
                    self._pre_roll = []
                    self._silence_ms = 0
            else:
                self._speech_ms = 0
            return None

        # --- stato SPEAKING ---
        self._speech.append(frame)
        self._silence_ms = 0 if is_speech else self._silence_ms + self.frame_ms

        duration_s = sum(f.size for f in self._speech) / float(self.sample_rate)
        if duration_s >= self.max_utterance_s:
            return self._close(truncated=True)
        if self._silence_ms >= self.min_silence_ms:
            return self._close(truncated=False)
        return None

    def _close(self, *, truncated: bool) -> Segment:
        audio = np.concatenate(self._speech) if self._speech else np.zeros(0, dtype=np.float32)
        self.reset()
        return Segment(audio=audio, sample_rate=self.sample_rate, truncated=truncated)

    def abort(self) -> None:
        """Scarta il turno in corso (es. parlante rifiutato: non ci interessa piu')."""
        self.reset()

    def reset(self) -> None:
        self.state = TurnState.SILENCE
        self._speech = []
        self._pre_roll = []
        self._speech_ms = 0
        self._silence_ms = 0
