"""Parola di attivazione: un filtro in piu' per gli ambienti estremi.

Normalmente non serve — la voce e' gia' la chiave. Ma in una sala d'asta vera,
con il microfono lontano e venti persone che urlano, puo' capitare che qualche
finestra passi la biometria per caso. Esigere anche una parola chiave riduce
quei casi a zero, al prezzo di doverla dire.

Una volta attivata resta aperta per `timeout_s` secondi, cosi' la conversazione
prosegue naturale invece di diventare un elenco di "ehi jarvis".
"""

from __future__ import annotations

import time
import unicodedata


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in stripped)
    return " ".join(cleaned.split())


class WakeWordGate:
    """Filtro sul testo trascritto, non sull'audio.

    Lavora dopo l'ASR perche' e' li' che la parola e' piu' riconoscibile: un
    keyword spotter dedicato sull'audio grezzo sarebbe piu' veloce ma un'altra
    dipendenza da addestrare, e a questo punto della catena la trascrizione c'e'
    gia'.
    """

    def __init__(self, enabled: bool = False, phrases: list[str] | None = None,
                 timeout_s: float = 30.0):
        self.enabled = bool(enabled)
        self.phrases = sorted(
            (_normalize(p) for p in (phrases or ["jarvis"]) if p.strip()),
            key=len, reverse=True,   # la piu' lunga per prima: "ehi jarvis" batte "jarvis"
        )
        self.timeout_s = float(timeout_s)
        self._active_until = 0.0

    @property
    def is_open(self) -> bool:
        """Vero se la finestra di conversazione e' ancora aperta."""
        return time.monotonic() < self._active_until

    def check(self, text: str) -> tuple[bool, str]:
        """Decide se il turno passa e restituisce il testo ripulito.

        Se la finestra e' aperta il turno passa cosi' com'e'. Altrimenti serve
        la parola chiave, che viene tolta dal testo: al modello arriva la
        domanda, non l'invocazione.
        """
        if not self.enabled:
            return True, text
        if self.is_open:
            self._touch()
            return True, text

        normalized = _normalize(text)
        for phrase in self.phrases:
            if normalized.startswith(phrase):
                self._touch()
                return True, self._strip_prefix(text, phrase)
            if f" {phrase} " in f" {normalized} ":
                self._touch()
                return True, text
        return False, text

    def _touch(self) -> None:
        self._active_until = time.monotonic() + self.timeout_s

    @staticmethod
    def _strip_prefix(text: str, phrase: str) -> str:
        """Toglie la parola chiave dall'inizio conservando il testo originale."""
        words = text.split()
        remaining = words[len(phrase.split()) :]
        return " ".join(remaining).lstrip(" ,.:;-").strip() or text

    def close(self) -> None:
        self._active_until = 0.0
