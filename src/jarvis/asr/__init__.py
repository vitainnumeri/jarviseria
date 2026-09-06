"""Trascrizione del parlato.

Girano solo i segmenti gia' riconosciuti come miei: e' la ragione per cui il
riconoscimento del parlante viene PRIMA della trascrizione e non dopo. Cosi'
nessuna frase di un estraneo consuma tempo, CPU o token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..audio.dsp import to_float32, to_int16
from ..utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Transcript:
    text: str
    language: str = "it"
    confidence: float | None = None
    duration: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> Transcript: ...


class FasterWhisperTranscriber:
    """Whisper in locale via faster-whisper (CTranslate2).

    Sul modello `medium` in int8 una frase di 3 secondi si trascrive in poche
    centinaia di millisecondi su CPU moderna: abbastanza per una conversazione.
    Scendi a `small` se la macchina fatica, sali a `large-v3` se hai una GPU.
    """

    def __init__(
        self,
        model: str = "medium",
        language: str = "it",
        device: str = "auto",
        compute_type: str = "int8",
        initial_prompt: str | None = None,
    ):
        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.initial_prompt = initial_prompt
        self._model = None

    def _ensure_model(self):  # pragma: no cover - scarica pesi
        if self._model is None:
            from faster_whisper import WhisperModel

            device = self.device
            if device == "auto":
                try:
                    import torch

                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"
            log.info("carico Whisper '%s' su %s (%s)", self.model_name, device, self.compute_type)
            self._model = WhisperModel(self.model_name, device=device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> Transcript:  # pragma: no cover
        from ..audio.dsp import resample_linear

        audio = to_float32(np.asarray(audio)).ravel()
        if sample_rate != 16000:
            audio = resample_linear(audio, sample_rate, 16000)
        if audio.size < 1600:
            return Transcript("", duration=audio.size / 16000)

        model = self._ensure_model()
        segments, info = model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=False,               # la segmentazione l'abbiamo gia' fatta noi
            initial_prompt=self.initial_prompt,
            condition_on_previous_text=False,  # evita che un errore si propaghi
        )
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
        confidence = (
            float(np.mean([np.exp(s.avg_logprob) for s in segments])) if segments else None
        )
        return Transcript(
            text=text,
            language=getattr(info, "language", self.language),
            confidence=confidence,
            duration=audio.size / 16000,
        )


class OpenAITranscriber:
    """Trascrizione via API OpenAI: nessun modello locale, serve rete."""

    def __init__(self, model: str = "whisper-1", language: str = "it", prompt: str | None = None):
        self.model = model
        self.language = language
        self.prompt = prompt
        self._client = None

    def _ensure_client(self):  # pragma: no cover - rete
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> Transcript:  # pragma: no cover
        import io
        import wave

        audio = to_float32(np.asarray(audio)).ravel()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(to_int16(audio).tobytes())
        buffer.name = "turno.wav"
        buffer.seek(0)

        response = self._ensure_client().audio.transcriptions.create(
            model=self.model, file=buffer, language=self.language, prompt=self.prompt
        )
        return Transcript(text=response.text.strip(), duration=audio.size / sample_rate)


class EchoTranscriber:
    """Trascrittore finto per i test: restituisce un testo preimpostato."""

    def __init__(self, text: str = ""):
        self.text = text
        self.calls = 0

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> Transcript:
        self.calls += 1
        return Transcript(text=self.text, duration=len(audio) / sample_rate)


def build_transcriber(cfg) -> Transcriber:
    """Costruisce il trascrittore dalla sezione `asr` della configurazione."""
    provider = str(cfg.get("asr.provider", "faster-whisper")).lower()
    prompt = cfg.get("asr.initial_prompt")
    if provider == "openai":
        return OpenAITranscriber(language=cfg.get("asr.language", "it"), prompt=prompt)
    return FasterWhisperTranscriber(
        model=cfg.get("asr.model", "medium"),
        language=cfg.get("asr.language", "it"),
        device=cfg.get("asr.device", "auto"),
        compute_type=cfg.get("asr.compute_type", "int8"),
        initial_prompt=prompt,
    )
