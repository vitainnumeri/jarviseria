"""Sintesi vocale con riproduzione a frasi.

Per la sensazione di "chiamata" conta soprattutto una cosa: non aspettare che
il modello finisca di scrivere prima di parlare. `stream_sentences` spezza il
testo in frasi mentre arriva e ognuna viene sintetizzata e detta subito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol

import numpy as np

from ..config import require_env
from ..utils.logging import get_logger

log = get_logger(__name__)

# Fine frase: punto/!/?/: seguiti da spazio, oppure a capo.
_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+|\n+")
MIN_SENTENCE_CHARS = 12


@dataclass
class Audio:
    samples: np.ndarray
    sample_rate: int


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> Audio: ...


def _split_sentence(buffer: str, min_chars: int) -> tuple[str, str] | None:
    """Primo confine di frase abbastanza lontano da valere una riproduzione.

    Un frammento troppo corto ("Si'.") viene tenuto in attesa e unito a quello
    che segue: da solo suonerebbe spezzato e non farebbe risparmiare latenza.
    """
    for match in _SENTENCE_END.finditer(buffer):
        if match.end() >= min_chars:
            return buffer[: match.end()].strip(), buffer[match.end() :]
    return None


def stream_sentences(chunks: Iterable[str], *, min_chars: int = MIN_SENTENCE_CHARS) -> Iterator[str]:
    """Accumula i pezzi di testo del modello e li rilascia una frase alla volta.

    E' cio' che rende la risposta "una telefonata": la prima frase parte verso
    l'altoparlante mentre il modello sta ancora scrivendo la seconda.
    """
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        while (split := _split_sentence(buffer, min_chars)) is not None:
            sentence, buffer = split
            if sentence:
                yield sentence
    if buffer.strip():
        yield buffer.strip()


class PiperTTS:
    """Piper: sintesi neurale offline, veloce e con buone voci italiane.

    Offline significa due cose utili qui: nessuna latenza di rete durante
    un'asta e nessuna frase che esce dal computer.
    """

    def __init__(self, voice: str = "it_IT-riccardo-x_low", model_dir: str = "models/piper",
                 speed: float = 1.0):
        self.voice = voice
        self.model_dir = model_dir
        self.speed = float(speed)
        self._voice = None

    def _ensure_voice(self):  # pragma: no cover - richiede i pesi
        if self._voice is None:
            from pathlib import Path

            from piper import PiperVoice

            path = Path(self.model_dir) / f"{self.voice}.onnx"
            if not path.exists():
                raise FileNotFoundError(
                    f"voce Piper non trovata: {path}\n"
                    "Scaricala da https://github.com/rhasspy/piper/releases "
                    f"(servono {self.voice}.onnx e {self.voice}.onnx.json)."
                )
            self._voice = PiperVoice.load(str(path))
        return self._voice

    def synthesize(self, text: str) -> Audio:  # pragma: no cover - richiede i pesi
        voice = self._ensure_voice()
        chunks = [
            np.frombuffer(c.audio_int16_bytes, dtype=np.int16)
            for c in voice.synthesize(text, length_scale=1.0 / max(0.1, self.speed))
        ]
        samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        return Audio(samples.astype(np.float32) / 32768.0, voice.config.sample_rate)


class ElevenLabsTTS:
    """ElevenLabs: la voce piu' naturale, al prezzo di una chiamata di rete."""

    def __init__(self, voice_id: str | None = None, model: str = "eleven_flash_v2_5",
                 speed: float = 1.0):
        self.voice_id = voice_id
        self.model = model  # "flash" = la variante a bassa latenza
        self.speed = float(speed)

    def synthesize(self, text: str) -> Audio:  # pragma: no cover - rete
        import io

        import requests
        import soundfile as sf

        api_key = require_env("ELEVENLABS_API_KEY")
        voice_id = self.voice_id or require_env("ELEVENLABS_VOICE_ID")
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": self.model,
                "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                                   "speed": self.speed},
            },
            timeout=30,
        )
        response.raise_for_status()
        samples, rate = sf.read(io.BytesIO(response.content), dtype="float32")
        return Audio(np.asarray(samples).ravel(), rate)


class OpenAITTS:
    """Sintesi via API OpenAI."""

    def __init__(self, voice: str = "alloy", model: str = "gpt-4o-mini-tts", speed: float = 1.0):
        self.voice = voice
        self.model = model
        self.speed = float(speed)

    def synthesize(self, text: str) -> Audio:  # pragma: no cover - rete
        import io

        import soundfile as sf
        from openai import OpenAI

        response = OpenAI().audio.speech.create(
            model=self.model, voice=self.voice, input=text, response_format="wav", speed=self.speed
        )
        samples, rate = sf.read(io.BytesIO(response.read()), dtype="float32")
        return Audio(np.asarray(samples).ravel(), rate)


class SilentTTS:
    """Sintesi finta: stampa e basta. Usata da `jarvis chat` e dai test."""

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> Audio:
        self.spoken.append(text)
        return Audio(np.zeros(0, dtype=np.float32), self.sample_rate)


def build_synthesizer(cfg) -> SpeechSynthesizer:
    """Costruisce il sintetizzatore dalla sezione `tts` della configurazione."""
    provider = str(cfg.get("tts.provider", "piper")).lower()
    speed = float(cfg.get("tts.speed", 1.0))
    if provider == "elevenlabs":
        return ElevenLabsTTS(voice_id=cfg.get("tts.voice") or None, speed=speed)
    if provider == "openai":
        return OpenAITTS(voice=cfg.get("tts.voice", "alloy"), speed=speed)
    if provider in {"none", "silent"}:
        return SilentTTS()
    return PiperTTS(
        voice=cfg.get("tts.voice", "it_IT-riccardo-x_low"),
        model_dir=str(cfg.resolve_path("tts.model_dir", "models/piper")),
        speed=speed,
    )
