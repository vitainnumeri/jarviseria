"""Estrazione dell'impronta vocale (speaker embedding).

Modello: ECAPA-TDNN addestrato su VoxCeleb (SpeechBrain). Produce un vettore di
192 dimensioni che descrive *chi* parla e non *cosa* dice: due frasi diverse
della stessa persona finiscono vicine, la stessa frase detta da due persone
finisce lontana.

Il confronto avviene per similarita' del coseno su vettori normalizzati.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from ..audio.dsp import to_float32
from ..utils.logging import get_logger

log = get_logger(__name__)

EMBEDDING_DIM = 192


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    """Normalizza a norma 1 (cosi' il prodotto scalare *e'* il coseno)."""
    vec = np.asarray(vec, dtype=np.float32)
    if vec.ndim == 1:
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 1e-10 else vec
    norms = np.linalg.norm(vec, axis=-1, keepdims=True)
    return vec / np.maximum(norms, 1e-10)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Similarita' del coseno fra due vettori, in [-1, 1]."""
    a, b = l2_normalize(a), l2_normalize(b)
    return float(np.dot(a, b))


def cosine_matrix(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Similarita' di un vettore contro una matrice (N, D) di embedding."""
    if matrix.size == 0:
        return np.zeros(0, dtype=np.float32)
    return l2_normalize(np.atleast_2d(matrix)) @ l2_normalize(vec)


class SpeakerEmbedder(Protocol):
    """Contratto minimo: audio a 16 kHz -> vettore normalizzato."""

    dim: int

    def embed(self, audio: np.ndarray, sample_rate: int) -> np.ndarray: ...


class ECAPAEmbedder:
    """Wrapper su SpeechBrain ECAPA-TDNN. Il modello si carica alla prima chiamata."""

    def __init__(
        self,
        model_name: str = "speechbrain/spkrec-ecapa-voxceleb",
        device: str = "auto",
        savedir: str = "models/ecapa",
    ):
        self.model_name = model_name
        self.savedir = savedir
        self.dim = EMBEDDING_DIM
        self._device = device
        self._model = None

    def _resolve_device(self) -> str:  # pragma: no cover - dipende dall'hardware
        if self._device != "auto":
            return self._device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def _ensure_model(self):  # pragma: no cover - scarica pesi
        if self._model is None:
            from speechbrain.inference.speaker import EncoderClassifier

            device = self._resolve_device()
            log.info("carico ECAPA-TDNN (%s) su %s", self.model_name, device)
            self._model = EncoderClassifier.from_hparams(
                source=self.model_name,
                savedir=self.savedir,
                run_opts={"device": device},
            )
        return self._model

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:  # pragma: no cover
        import torch

        from ..audio.dsp import resample_linear

        audio = to_float32(np.asarray(audio)).ravel()
        if sample_rate != 16000:
            audio = resample_linear(audio, sample_rate, 16000)
        if audio.size < 1600:  # meno di 100 ms: troppo poco per un'impronta
            return np.zeros(self.dim, dtype=np.float32)
        model = self._ensure_model()
        with torch.no_grad():
            tensor = torch.from_numpy(audio).unsqueeze(0)
            emb = model.encode_batch(tensor).squeeze().cpu().numpy()
        return l2_normalize(emb.astype(np.float32))


class DeterministicEmbedder:
    """Embedder finto e deterministico, per i test e per `--dry-run`.

    Non riconosce nessuno: mappa l'audio in un vettore stabile in modo che la
    logica di verifica sia collaudabile senza scaricare 80 MB di pesi.
    """

    def __init__(self, dim: int = EMBEDDING_DIM, seed: int = 0):
        self.dim = dim
        self.seed = seed

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        audio = to_float32(np.asarray(audio)).ravel()
        if audio.size == 0:
            return np.zeros(self.dim, dtype=np.float32)
        digest = int(abs(float(np.sum(audio[:4000]))) * 1e6) % (2**31)
        rng = np.random.default_rng(self.seed + digest)
        return l2_normalize(rng.standard_normal(self.dim).astype(np.float32))


def build_embedder(model_name: str = "speechbrain/spkrec-ecapa-voxceleb", device: str = "auto"):
    """Costruisce l'embedder reale; se le dipendenze mancano, lo dice chiaramente."""
    try:
        import speechbrain  # noqa: F401  (solo per verificare che ci sia)
    except ImportError as exc:  # pragma: no cover - dipende dall'ambiente
        raise RuntimeError(
            "speechbrain non installato: `pip install -e '.[audio]'` "
            "(serve per riconoscere la tua voce)."
        ) from exc
    return ECAPAEmbedder(model_name, device)
