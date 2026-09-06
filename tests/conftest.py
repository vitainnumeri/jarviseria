"""Fixture condivise dai test: voci sintetiche e embedder controllato.

Simulare "chi parla" in modo deterministico permette di collaudare tutta la
catena di decisione senza microfono, senza modelli e senza rete.
"""

from __future__ import annotations

import numpy as np
import pytest

from jarvis.speaker.embedder import EMBEDDING_DIM, l2_normalize
from jarvis.speaker.profile import Cohort, VoiceProfile
from jarvis.speaker.verifier import SpeakerVerifier, VerifierConfig

SR = 16000
BASE_HZ = 110.0   # fondamentale del "parlante 0" (il proprietario)
STEP_HZ = 53.0    # distanza fra parlanti


class FakeEmbedder:
    """Ogni "persona" e' un vettore fisso; ogni sua frase e' quel vettore piu'
    rumore, come nella realta' (stessa voce, condizioni diverse).

    L'identita' viaggia nell'audio come frequenza fondamentale, cosi' sopravvive
    al finestramento: qualunque finestra di 1 secondo identifica lo stesso
    parlante, esattamente come farebbe ECAPA.
    """

    dim = EMBEDDING_DIM

    def __init__(self, jitter: float = 0.45, n_people: int = 8):
        rng = np.random.default_rng(42)
        self.n_people = n_people
        self.people = {
            pid: l2_normalize(rng.standard_normal(EMBEDDING_DIM).astype(np.float32))
            for pid in range(n_people)
        }
        self.jitter = jitter

    def _identify(self, audio: np.ndarray) -> int:
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
        peak_hz = float(np.argmax(spectrum)) * SR / audio.size
        return int(np.clip(round((peak_hz - BASE_HZ) / STEP_HZ), 0, self.n_people - 1))

    def embed(self, audio: np.ndarray, sample_rate: int = SR) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32).ravel()
        if audio.size < 256:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        pid = self._identify(audio)
        seed = (pid * 1000 + audio.size + int(abs(float(np.sum(audio))) * 10)) % 100_000
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        noise *= self.jitter / np.sqrt(EMBEDDING_DIM)
        return l2_normalize(self.people[pid] + noise)


def speech(person: int, seconds: float = 3.0, level: float = 0.2) -> np.ndarray:
    """Audio sintetico attribuito a `person`, con livello (=distanza) controllato."""
    t = np.arange(int(seconds * SR), dtype=np.float64) / SR
    f0 = BASE_HZ + person * STEP_HZ
    wave = np.sin(2 * np.pi * f0 * t) + 0.35 * np.sin(2 * np.pi * 2 * f0 * t)
    wave /= np.max(np.abs(wave))
    rng = np.random.default_rng(person * 7 + int(seconds * 10))
    return (wave * level + rng.standard_normal(t.size) * level * 0.03).astype(np.float32)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def owner_profile(embedder: FakeEmbedder) -> VoiceProfile:
    """Profilo del proprietario, arruolato su sei frasi."""
    profile = VoiceProfile(name="david")
    for i in range(6):
        profile.add(embedder.embed(speech(0, 4.0 + i * 0.3)), seconds=4.0)
    return profile


@pytest.fixture
def verifier(embedder, owner_profile) -> SpeakerVerifier:
    cfg = VerifierConfig(accept_threshold=0.62, continue_threshold=0.50, near_field_enabled=False)
    return SpeakerVerifier(embedder, owner_profile, cfg, Cohort())
