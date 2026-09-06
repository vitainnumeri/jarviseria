"""Caricamento del listone e ricerca dei giocatori.

Due problemi concreti risolti qui:

1. Il file ufficiale (Fantacalcio.it) ha intestazioni come `Qt.A`, `R`, `RM`.
   Il loader accetta quelle e diverse varianti, cosi' non serve rimaneggiare a
   mano l'export.
2. Cercare per voce: la trascrizione storpia i cognomi ("Dimarco" -> "di marco",
   "Vlahovic" -> "vlahovich"). La ricerca e' quindi tollerante: normalizza gli
   accenti, ignora la punteggiatura e usa una somiglianza fra stringhe.
"""

from __future__ import annotations

import csv
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from ..utils.logging import get_logger
from .models import Player

log = get_logger(__name__)

# Ogni campo interno con i nomi di colonna accettati (minuscoli, senza spazi).
COLUMN_ALIASES = {
    "name": ["nome", "name", "giocatore", "calciatore"],
    "team": ["squadra", "team", "club"],
    "role": ["r", "ruolo", "role", "ruoloclassic"],
    "mantra_roles": ["rm", "ruolim", "ruolomantra", "ruolimantra"],
    "quotation": ["qt.a", "qta", "quotazioneattuale", "quotazione", "qt.am", "prezzo"],
    "initial_quotation": ["qt.i", "qti", "quotazioneiniziale"],
    "fvm": ["fvm", "fantavalore", "fvmm"],
    "fantamedia": ["fm", "fantamedia", "fantamediatotale"],
    "media_voto": ["mv", "mediavoto", "media"],
    "presences": ["pv", "presenze", "partite"],
    "goals": ["gf", "gol", "goals", "reti"],
    "assists": ["ass", "assist", "assists"],
    "player_id": ["id", "idgiocatore"],
}

VALID_ROLES = {"P", "D", "C", "A"}


def normalize_text(text: str) -> str:
    """Minuscolo, senza accenti e senza punteggiatura: base del confronto."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in stripped)
    return " ".join(cleaned.split())


def _norm_header(header: str) -> str:
    return "".join(str(header or "").lower().split()).replace("_", "")


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    """Associa i campi interni alle colonne effettive del file."""
    mapping: dict[str, str] = {}
    normalized = {_norm_header(f): f for f in fieldnames if f}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field_name] = normalized[alias]
                break
    return mapping


def _to_float(value, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return default


def _to_int(value, default: int | None = None) -> int | None:
    result = _to_float(value, None)
    return int(result) if result is not None else default


class Listone:
    """Il listone caricato in memoria, con ricerca tollerante agli errori."""

    def __init__(self, players: list[Player] | None = None, source: str | None = None):
        self.players: list[Player] = players or []
        self.source = source
        self._index: dict[str, Player] = {}
        self._reindex()

    def _reindex(self) -> None:
        self._index = {normalize_text(p.name): p for p in self.players}

    # -------------------------------------------------------------- caricamento
    @classmethod
    def from_csv(cls, path: str | Path, *, delimiter: str | None = None) -> "Listone":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"listone non trovato: {path}\n"
                "Scarica le quotazioni ufficiali da fantacalcio.it, salvale in CSV "
                "e indica il percorso in config (fanta.listone_path)."
            )
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if delimiter is None:
            head = raw.split("\n", 1)[0]
            delimiter = ";" if head.count(";") > head.count(",") else ","

        reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
        mapping = _map_columns(list(reader.fieldnames or []))
        if "name" not in mapping:
            raise ValueError(
                f"il file {path.name} non ha una colonna con i nomi dei giocatori "
                f"(attese: {', '.join(COLUMN_ALIASES['name'])})"
            )

        players: list[Player] = []
        for row in reader:
            name = str(row.get(mapping["name"], "")).strip()
            if not name:
                continue
            role = str(row.get(mapping.get("role", ""), "") or "").strip().upper()[:1]
            mantra_raw = str(row.get(mapping.get("mantra_roles", ""), "") or "")
            quotation = _to_float(row.get(mapping.get("quotation", "")), 1.0) or 1.0
            players.append(
                Player(
                    name=name,
                    team=str(row.get(mapping.get("team", ""), "") or "").strip().upper(),
                    role=role if role in VALID_ROLES else "C",
                    mantra_roles=[r.strip() for r in mantra_raw.replace("/", ";").split(";") if r.strip()],
                    quotation=quotation,
                    initial_quotation=_to_float(row.get(mapping.get("initial_quotation", "")), quotation) or quotation,
                    fvm=_to_float(row.get(mapping.get("fvm", "")), 0.0) or 0.0,
                    fantamedia=_to_float(row.get(mapping.get("fantamedia", ""))),
                    media_voto=_to_float(row.get(mapping.get("media_voto", ""))),
                    presences=_to_int(row.get(mapping.get("presences", ""))),
                    goals=_to_int(row.get(mapping.get("goals", ""))),
                    assists=_to_int(row.get(mapping.get("assists", ""))),
                    player_id=str(row.get(mapping.get("player_id", ""), "") or "").strip(),
                )
            )
        log.info("listone caricato: %d giocatori da %s", len(players), path.name)
        return cls(players, source=str(path))

    # ------------------------------------------------------------------ query
    def get(self, name: str) -> Player | None:
        """Corrispondenza esatta sul nome normalizzato."""
        return self._index.get(normalize_text(name))

    def search(self, query: str, *, limit: int = 5, min_score: float = 0.55) -> list[tuple[Player, float]]:
        """Ricerca tollerante: restituisce (giocatore, somiglianza) ordinati.

        Combina prefisso, sottostringa e somiglianza fra sequenze: e' cio' che
        rende usabile la ricerca quando il nome arriva da una trascrizione.
        """
        needle = normalize_text(query)
        if not needle:
            return []
        results: list[tuple[Player, float]] = []
        for player in self.players:
            hay = normalize_text(player.name)
            if hay == needle:
                score = 1.0
            elif hay.startswith(needle) or needle.startswith(hay):
                score = 0.95
            elif needle in hay or hay in needle:
                score = 0.85
            else:
                score = SequenceMatcher(None, needle, hay).ratio()
            if score >= min_score:
                results.append((player, round(score, 3)))
        results.sort(key=lambda item: (-item[1], -item[0].fvm))
        return results[:limit]

    def by_role(self, role: str) -> list[Player]:
        role = str(role).strip().upper()[:1]
        return [p for p in self.players if p.role == role]

    def by_team(self, team: str) -> list[Player]:
        needle = normalize_text(team)
        return [p for p in self.players if normalize_text(p.team) == needle]

    def top(self, role: str | None = None, *, key: str = "fvm", limit: int = 10) -> list[Player]:
        """I migliori per FVM o quotazione, eventualmente filtrati per ruolo."""
        pool = self.by_role(role) if role else list(self.players)
        getter = (lambda p: p.fvm) if key == "fvm" else (lambda p: p.quotation)
        return sorted(pool, key=getter, reverse=True)[:limit]

    def __len__(self) -> int:
        return len(self.players)

    def __bool__(self) -> bool:
        return bool(self.players)


def load_listone(path: str | Path | None) -> Listone:
    """Carica il listone se configurato; altrimenti restituisce un listone vuoto.

    L'assistente resta usabile senza listone (sa parlare di strategia), ma
    dichiara di non avere le quotazioni invece di inventarle.
    """
    if not path:
        return Listone()
    try:
        return Listone.from_csv(path)
    except FileNotFoundError as exc:
        log.warning("%s", exc)
        return Listone()
