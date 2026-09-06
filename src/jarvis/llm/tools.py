"""Strumenti dell'agente: il ponte fra la conversazione e i motori di dominio.

Ogni strumento restituisce un dizionario JSON-serializzabile. Le funzioni non
parlano: producono numeri e fatti. Il tono della risposta lo mette il modello.
"""

from __future__ import annotations

from typing import Any, Callable

from ..fanta.auction import AuctionState
from ..fanta.formation import MatchContext, best_formation, build_formation, compare_players
from ..fanta.knowledge import BUDGET_SPLIT_STRATEGIE, GLOSSARIO, MODULI_CLASSIC, modificatore_difesa
from ..fanta.listone import Listone
from ..fanta.models import Player
from ..utils.logging import get_logger

log = get_logger(__name__)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "cerca_giocatore",
        "description": (
            "Cerca un giocatore nel listone per nome, tollerando storpiature della "
            "trascrizione vocale. Restituisce i candidati con quotazione, FVM e ruolo. "
            "Usalo ogni volta che serve un dato su un giocatore: non fidarti della memoria."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome come lo hai sentito"},
                "limite": {"type": "integer", "description": "Quanti candidati (default 3)"},
            },
            "required": ["nome"],
        },
    },
    {
        "name": "migliori_per_ruolo",
        "description": "I giocatori piu' quotati di un ruolo (P, D, C, A), ordinati per valore.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruolo": {"type": "string", "enum": ["P", "D", "C", "A"]},
                "limite": {"type": "integer"},
            },
            "required": ["ruolo"],
        },
    },
    {
        "name": "consiglio_offerta",
        "description": (
            "Quanto posso offrire per un giocatore, adesso. Tiene conto di crediti residui, "
            "slot mancanti e piano di reparto. USALO SEMPRE prima di dire un prezzo in asta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string"},
                "offerta_attuale": {"type": "integer", "description": "A quanto e' arrivata l'asta"},
                "quanto_lo_voglio": {
                    "type": "number",
                    "description": "0.8 = solo se capita a poco, 1.0 = a piano, 1.3 = lo voglio",
                },
            },
            "required": ["nome"],
        },
    },
    {
        "name": "registra_acquisto",
        "description": (
            "Registra un giocatore appena aggiudicato al prezzo pagato e aggiorna budget e slot. "
            "Chiamalo appena te lo dice: da quel momento tutti i conti cambiano."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string"}, "prezzo": {"type": "integer"}},
            "required": ["nome", "prezzo"],
        },
    },
    {
        "name": "annulla_acquisto",
        "description": "Toglie dalla rosa un giocatore registrato per errore.",
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string"}},
            "required": ["nome"],
        },
    },
    {
        "name": "stato_asta",
        "description": (
            "Fotografia dell'asta: crediti residui, slot mancanti, massimo offribile, "
            "spesa per reparto e rosa attuale."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "piano_asta",
        "description": (
            "Il piano di spesa: quanto destinare a ogni reparto e il prezzo obiettivo di "
            "ogni slot. Puoi cambiare strategia passando il suo nome."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategia": {
                    "type": "string",
                    "enum": list(BUDGET_SPLIT_STRATEGIE),
                    "description": "Se indicata, cambia la ripartizione del budget",
                }
            },
        },
    },
    {
        "name": "costruisci_formazione",
        "description": (
            "Sceglie la formazione migliore fra i giocatori indicati, provando tutti i moduli. "
            "Restituisce titolari, panchina ordinata e avvertenze."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "giocatori": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nomi dei giocatori disponibili. Vuoto = usa la rosa d'asta.",
                },
                "modulo": {
                    "type": "string",
                    "enum": list(MODULI_CLASSIC),
                    "description": "Se indicato usa solo questo modulo, altrimenti sceglie il migliore",
                },
                "indisponibili": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Infortunati o squalificati da escludere",
                },
            },
        },
    },
    {
        "name": "confronta_giocatori",
        "description": (
            "Chi schierare fra due giocatori, con la ragione della scelta. "
            "La domanda della domenica mattina."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "primo": {"type": "string"},
                "secondo": {"type": "string"},
                "avversario_primo": {"type": "number", "description": "Forza avversario 1-5"},
                "avversario_secondo": {"type": "number"},
                "in_casa_primo": {"type": "boolean"},
                "in_casa_secondo": {"type": "boolean"},
            },
            "required": ["primo", "secondo"],
        },
    },
    {
        "name": "regolamento",
        "description": (
            "Bonus, malus, modificatore di difesa e glossario del fantacalcio. "
            "Usalo per rispondere su punteggi e regole invece di andare a memoria."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "argomento": {
                    "type": "string",
                    "description": "es. 'bonus', 'modificatore', o un termine del glossario",
                },
                "media_reparto": {
                    "type": "number",
                    "description": "Per calcolare il modificatore di difesa da una media voto",
                },
            },
        },
    },
]


class FantaTools:
    """Implementazione degli strumenti su listone e stato d'asta condivisi."""

    def __init__(self, listone: Listone, auction: AuctionState):
        self.listone = listone
        self.auction = auction

    # ------------------------------------------------------------ risoluzione
    def _resolve(self, nome: str) -> tuple[Player | None, list[dict]]:
        """Trova un giocatore, restituendo anche i candidati alternativi.

        Se la corrispondenza migliore non e' netta, l'agente e' istruito a
        chiedere conferma invece di procedere sull'ipotesi sbagliata: in asta
        un nome scambiato costa crediti veri.
        """
        results = self.listone.search(nome, limit=3)
        if not results:
            return None, []
        candidates = [
            {"nome": p.name, "squadra": p.team, "ruolo": p.role, "somiglianza": score}
            for p, score in results
        ]
        best, best_score = results[0]
        ambiguous = len(results) > 1 and (best_score - results[1][1]) < 0.08
        return (None if ambiguous else best), candidates

    # ---------------------------------------------------------------- ricerca
    def cerca_giocatore(self, nome: str, limite: int = 3) -> dict:
        if not self.listone:
            return {"errore": "listone non caricato: non ho quotazioni da consultare"}
        results = self.listone.search(nome, limit=int(limite))
        if not results:
            return {"trovato": False, "cercato": nome,
                    "nota": "nessun giocatore corrisponde: forse il nome e' stato trascritto male"}
        return {
            "trovato": True,
            "candidati": [{**p.to_dict(), "somiglianza": score} for p, score in results],
        }

    def migliori_per_ruolo(self, ruolo: str, limite: int = 10) -> dict:
        if not self.listone:
            return {"errore": "listone non caricato"}
        players = self.listone.top(ruolo, limit=int(limite))
        return {"ruolo": ruolo, "giocatori": [p.to_dict() for p in players]}

    # ------------------------------------------------------------------ asta
    def consiglio_offerta(self, nome: str, offerta_attuale: int = 0,
                          quanto_lo_voglio: float = 1.0) -> dict:
        player, candidates = self._resolve(nome)
        if player is None:
            return {
                "serve_conferma": True,
                "candidati": candidates,
                "nota": "chiedi conferma su quale giocatore intende prima di dare un prezzo",
            } if candidates else {"errore": f"'{nome}' non e' nel listone"}

        advice = self.auction.advise(
            player, current_bid=int(offerta_attuale), aggressiveness=float(quanto_lo_voglio)
        )
        return {
            **advice.to_dict(),
            "crediti_residui": self.auction.credits_left,
            "slot_mancanti": self.auction.slots_left,
            "slot_mancanti_nel_ruolo": self.auction.roster.missing(player.role),
        }

    def registra_acquisto(self, nome: str, prezzo: int) -> dict:
        player, candidates = self._resolve(nome)
        if player is None:
            if not candidates:
                # Fuori listone (giocatore appena arrivato): lo registro comunque.
                player = Player(name=nome, team="?", role="C", quotation=float(prezzo))
                log.info("giocatore fuori listone registrato: %s", nome)
            else:
                return {"serve_conferma": True, "candidati": candidates}
        try:
            report = self.auction.buy(player, int(prezzo))
        except ValueError as exc:
            return {"errore": str(exc)}
        return {"registrato": f"{player.name} a {prezzo}", **report}

    def annulla_acquisto(self, nome: str) -> dict:
        try:
            return {"annullato": nome, **self.auction.undo(nome)}
        except ValueError as exc:
            return {"errore": str(exc)}

    def stato_asta(self) -> dict:
        return self.auction.report()

    def piano_asta(self, strategia: str | None = None) -> dict:
        if strategia:
            try:
                self.auction.apply_strategy(strategia)
            except ValueError as exc:
                return {"errore": str(exc)}
        return {
            "strategia": strategia or "corrente",
            "ripartizione": self.auction.budget_split,
            "piano": self.auction.plan(),
            "crediti_residui": self.auction.credits_left,
        }

    # ------------------------------------------------------------ formazione
    def _players_from_names(self, names: list[str]) -> tuple[list[Player], list[str]]:
        found, missing = [], []
        for name in names:
            player = self.listone.get(name)
            if player is None:
                results = self.listone.search(name, limit=1)
                player = results[0][0] if results else None
            if player is None:
                missing.append(name)
            else:
                found.append(player)
        return found, missing

    def costruisci_formazione(self, giocatori: list[str] | None = None, modulo: str | None = None,
                              indisponibili: list[str] | None = None) -> dict:
        if giocatori:
            players, missing = self._players_from_names(giocatori)
        else:
            players = [s.player for s in self.auction.roster.acquired]
            missing = []
        if not players:
            return {"errore": "non ho giocatori: dimmi la rosa oppure registra gli acquisti d'asta"}

        # Copio i giocatori per non sporcare il listone con lo stato di giornata.
        pool = []
        blocked = {n.strip().lower() for n in (indisponibili or [])}
        for p in players:
            clone = Player(**{**p.__dict__, "mantra_roles": list(p.mantra_roles)})
            if clone.name.lower() in blocked:
                clone.status = "infortunato"
            pool.append(clone)

        try:
            formation = build_formation(pool, modulo) if modulo else best_formation(pool)
        except ValueError as exc:
            return {"errore": str(exc)}

        result = formation.to_dict()
        if missing:
            result["non_trovati"] = missing
        return result

    def confronta_giocatori(self, primo: str, secondo: str, avversario_primo: float = 3.0,
                            avversario_secondo: float = 3.0, in_casa_primo: bool = True,
                            in_casa_secondo: bool = True) -> dict:
        a, cand_a = self._resolve(primo)
        b, cand_b = self._resolve(secondo)
        if a is None or b is None:
            return {"serve_conferma": True, "candidati_primo": cand_a, "candidati_secondo": cand_b}
        return compare_players(
            a, b,
            MatchContext(opponent_strength=avversario_primo, home=in_casa_primo),
            MatchContext(opponent_strength=avversario_secondo, home=in_casa_secondo),
        )

    # ----------------------------------------------------------- regolamento
    def regolamento(self, argomento: str = "", media_reparto: float | None = None) -> dict:
        from ..fanta.knowledge import BONUS_MALUS, MODIFICATORE_DIFESA

        if media_reparto is not None:
            return {
                "media_reparto": media_reparto,
                "bonus_modificatore": modificatore_difesa(float(media_reparto)),
                "fasce": [{"da": lo, "a": hi, "bonus": b} for lo, hi, b in MODIFICATORE_DIFESA],
                "nota": "valori standard: verifica il regolamento della lega",
            }
        key = (argomento or "").strip().lower()
        if key in GLOSSARIO:
            return {"termine": key, "significato": GLOSSARIO[key]}
        if "modific" in key:
            return {"fasce": [{"da": lo, "a": hi, "bonus": b} for lo, hi, b in MODIFICATORE_DIFESA]}
        return {
            "bonus_malus": BONUS_MALUS,
            "glossario": GLOSSARIO,
            "nota": "impostazioni standard: assist, portiere imbattuto e modificatore "
                    "possono essere disattivati nella lega dell'utente",
        }

    # --------------------------------------------------------------- dispatch
    def dispatch(self, name: str, arguments: dict) -> dict:
        """Esegue lo strumento richiesto dal modello.

        Un'eccezione qui non deve mai far cadere la telefonata: viene
        trasformata in un errore che il modello puo' spiegare a voce.
        """
        handler: Callable[..., dict] | None = getattr(self, name, None)
        if handler is None or name.startswith("_"):
            return {"errore": f"strumento sconosciuto: {name}"}
        try:
            return handler(**(arguments or {}))
        except TypeError as exc:
            return {"errore": f"argomenti non validi per {name}: {exc}"}
        except Exception as exc:  # pragma: no cover - rete di sicurezza
            log.exception("strumento %s fallito", name)
            return {"errore": f"{type(exc).__name__}: {exc}"}
