"""Profilo vocale del proprietario e coorte degli "altri".

ATTENZIONE: il file del profilo e' un dato biometrico. Resta in locale, e' in
.gitignore, e non va mai caricato da nessuna parte.

Due oggetti:

`VoiceProfile`  le impronte del proprietario (piu' frasi + il loro centroide).
`Cohort`        le impronte di chiunque altro. Serve a due cose:
                1) normalizzare il punteggio (una soglia assoluta non regge il
                   cambio di stanza/microfono);
                2) applicare la regola che conta davvero in mezzo alla gente:
                   "devo somigliare a me molto piu' che a chiunque altro".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..utils.logging import get_logger
from .embedder import EMBEDDING_DIM, cosine_matrix, l2_normalize

log = get_logger(__name__)


@dataclass
class VoiceProfile:
    """Impronta vocale del proprietario.

    Conserva i singoli embedding di arruolamento e non solo la media: frasi
    pronunciate in condizioni diverse (piano, forte, di corsa) coprono meglio
    la variabilita' della voce reale. Il punteggio finale combina il centroide
    con la migliore corrispondenza singola.
    """

    embeddings: np.ndarray = field(default_factory=lambda: np.zeros((0, EMBEDDING_DIM), np.float32))
    name: str = "owner"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    sample_seconds: float = 0.0
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------- proprieta'
    @property
    def is_empty(self) -> bool:
        return self.embeddings.size == 0

    @property
    def centroid(self) -> np.ndarray:
        """Media normalizzata delle impronte: la "voce media" del proprietario."""
        if self.is_empty:
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)
        return l2_normalize(self.embeddings.mean(axis=0))

    # ---------------------------------------------------------------- scoring
    def score(self, embedding: np.ndarray, *, top_k: int = 3) -> float:
        """Somiglianza fra un'impronta e il profilo, in [-1, 1].

        Media fra la somiglianza col centroide e quella con le `top_k` frasi di
        arruolamento piu' vicine: il centroide da' stabilita', le singole frasi
        recuperano i casi in cui la voce del momento assomiglia a una specifica
        condizione di registrazione.
        """
        if self.is_empty:
            return 0.0
        emb = l2_normalize(embedding)
        centroid_score = float(np.dot(self.centroid, emb))
        sims = cosine_matrix(emb, self.embeddings)
        k = min(int(top_k), sims.size)
        best = float(np.mean(np.sort(sims)[-k:]))
        return 0.5 * centroid_score + 0.5 * best

    # ------------------------------------------------------------ mutazioni
    def add(self, embedding: np.ndarray, seconds: float = 0.0) -> None:
        emb = l2_normalize(embedding).reshape(1, -1)
        self.embeddings = emb if self.is_empty else np.vstack([self.embeddings, emb])
        self.sample_seconds += float(seconds)
        self.updated_at = time.time()

    def adapt(self, embedding: np.ndarray, rate: float = 0.05, max_embeddings: int = 64) -> None:
        """Adattamento lento del profilo a microfono, stanza e stato della voce.

        Sposta il centroide di un passo `rate` verso l'impronta nuova. Il
        chiamante deve invocarlo SOLO su turni ad altissima confidenza,
        altrimenti il profilo va alla deriva verso un'altra persona.
        """
        if self.is_empty:
            self.add(embedding)
            return
        emb = l2_normalize(embedding)
        blended = l2_normalize((1.0 - rate) * self.centroid + rate * emb)
        self.embeddings = np.vstack([self.embeddings, blended.reshape(1, -1)])
        if self.embeddings.shape[0] > max_embeddings:
            self.embeddings = self.embeddings[-max_embeddings:]
        self.updated_at = time.time()

    # -------------------------------------------------------------- I/O
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            embeddings=self.embeddings,
            meta=json.dumps(
                {
                    "name": self.name,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                    "sample_seconds": self.sample_seconds,
                    **self.meta,
                }
            ),
        )
        log.info("profilo salvato in %s (%d impronte, %.1fs)", path, len(self.embeddings), self.sample_seconds)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "VoiceProfile":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"profilo vocale non trovato: {path}\nEsegui prima:  jarvis enroll"
            )
        data = np.load(path, allow_pickle=False)
        meta = json.loads(str(data["meta"]))
        return cls(
            embeddings=np.asarray(data["embeddings"], dtype=np.float32),
            name=meta.pop("name", "owner"),
            created_at=meta.pop("created_at", time.time()),
            updated_at=meta.pop("updated_at", time.time()),
            sample_seconds=meta.pop("sample_seconds", 0.0),
            meta=meta,
        )


@dataclass
class Cohort:
    """Insieme di impronte NON del proprietario.

    `auto_learn` la riempie da sola con le voci rifiutate durante la sessione:
    dopo qualche minuto in una stanza il sistema conosce i presenti e diventa
    piu' severo proprio verso di loro.
    """

    embeddings: np.ndarray = field(default_factory=lambda: np.zeros((0, EMBEDDING_DIM), np.float32))
    max_size: int = 300

    @property
    def size(self) -> int:
        return int(self.embeddings.shape[0]) if self.embeddings.size else 0

    def add(self, embedding: np.ndarray, *, min_novelty: float = 0.03) -> bool:
        """Aggiunge un'impronta se porta informazione nuova.

        Scarta i quasi-duplicati: 300 registrazioni della stessa persona
        sbilancerebbero la normalizzazione.
        """
        emb = l2_normalize(embedding).reshape(1, -1)
        if self.size:
            if float(np.max(cosine_matrix(emb.ravel(), self.embeddings))) > 1.0 - min_novelty:
                return False
            self.embeddings = np.vstack([self.embeddings, emb])
        else:
            self.embeddings = emb
        if self.size > self.max_size:
            self.embeddings = self.embeddings[-self.max_size :]
        return True

    def similarities(self, embedding: np.ndarray) -> np.ndarray:
        return cosine_matrix(embedding, self.embeddings)

    def best_match(self, embedding: np.ndarray) -> float:
        """Quanto l'impronta somiglia all'estraneo piu' somigliante."""
        sims = self.similarities(embedding)
        return float(np.max(sims)) if sims.size else -1.0

    def top_k_stats(self, embedding: np.ndarray, k: int = 20) -> tuple[float, float]:
        """Media e deviazione standard delle `k` somiglianze piu' alte (AS-Norm)."""
        sims = self.similarities(embedding)
        if sims.size == 0:
            return 0.0, 1.0
        top = np.sort(sims)[-min(int(k), sims.size) :]
        return float(np.mean(top)), float(max(np.std(top), 1e-3))

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, embeddings=self.embeddings, max_size=self.max_size)
        return path

    @classmethod
    def load(cls, path: str | Path, max_size: int = 300) -> "Cohort":
        path = Path(path)
        if not path.exists():
            return cls(max_size=max_size)
        data = np.load(path, allow_pickle=False)
        return cls(embeddings=np.asarray(data["embeddings"], dtype=np.float32), max_size=max_size)
