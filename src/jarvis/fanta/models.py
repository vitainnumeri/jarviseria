"""Modelli di dominio: giocatore, rosa, stato d'asta."""

from __future__ import annotations

from dataclasses import dataclass, field

from .knowledge import ROSA_STANDARD


@dataclass
class Player:
    """Un giocatore del listone.

    I campi statistici sono opzionali: il listone ufficiale contiene quotazioni
    e FVM, mentre fantamedia e presenze arrivano solo se l'utente carica anche
    lo storico. Cio' che manca resta None e l'assistente lo dichiara, invece di
    inventarlo.
    """

    name: str
    team: str
    role: str                       # ruolo Classic: P/D/C/A
    mantra_roles: list[str] = field(default_factory=list)
    quotation: float = 1.0          # Qt.A: quotazione attuale
    initial_quotation: float = 1.0  # Qt.I
    fvm: float = 0.0                # Fanta Valore di Mercato
    fantamedia: float | None = None
    media_voto: float | None = None
    presences: int | None = None
    goals: int | None = None
    assists: int | None = None
    penalty_taker: bool = False
    starter_probability: float | None = None   # 0..1, dalle probabili formazioni
    status: str = "ok"              # ok | infortunato | squalificato | diffidato | in dubbio
    player_id: str = ""

    @property
    def available(self) -> bool:
        return self.status not in {"infortunato", "squalificato"}

    @property
    def display(self) -> str:
        return f"{self.name} ({self.team}, {self.role})"

    def to_dict(self) -> dict:
        data = {
            "nome": self.name,
            "squadra": self.team,
            "ruolo": self.role,
            "quotazione": self.quotation,
            "fvm": self.fvm,
        }
        if self.mantra_roles:
            data["ruoli_mantra"] = self.mantra_roles
        for key, value in (
            ("fantamedia", self.fantamedia),
            ("media_voto", self.media_voto),
            ("presenze", self.presences),
            ("gol", self.goals),
            ("assist", self.assists),
            ("probabilita_titolare", self.starter_probability),
        ):
            if value is not None:
                data[key] = value
        if self.penalty_taker:
            data["rigorista"] = True
        if self.status != "ok":
            data["stato"] = self.status
        return data


@dataclass
class RosterSlot:
    """Un giocatore acquistato e quanto e' costato."""

    player: Player
    price: int

    def to_dict(self) -> dict:
        return {"nome": self.player.name, "ruolo": self.player.role,
                "squadra": self.player.team, "prezzo": self.price}


@dataclass
class Roster:
    """La mia rosa durante e dopo l'asta."""

    slots_target: dict[str, int] = field(default_factory=lambda: dict(ROSA_STANDARD))
    acquired: list[RosterSlot] = field(default_factory=list)

    # ------------------------------------------------------------- conteggi
    def count(self, role: str) -> int:
        return sum(1 for s in self.acquired if s.player.role == role)

    def missing(self, role: str) -> int:
        return max(0, self.slots_target.get(role, 0) - self.count(role))

    @property
    def total_missing(self) -> int:
        return sum(self.missing(r) for r in self.slots_target)

    @property
    def total_spent(self) -> int:
        return sum(s.price for s in self.acquired)

    def spent_on(self, role: str) -> int:
        return sum(s.price for s in self.acquired if s.player.role == role)

    def by_role(self, role: str) -> list[RosterSlot]:
        return [s for s in self.acquired if s.player.role == role]

    def has(self, name: str) -> bool:
        needle = name.strip().lower()
        return any(s.player.name.lower() == needle for s in self.acquired)

    # ------------------------------------------------------------ mutazioni
    def add(self, player: Player, price: int) -> RosterSlot:
        if self.has(player.name):
            raise ValueError(f"{player.name} e' gia' in rosa")
        if self.missing(player.role) == 0:
            raise ValueError(f"slot {player.role} gia' completi ({self.slots_target.get(player.role, 0)})")
        slot = RosterSlot(player=player, price=int(price))
        self.acquired.append(slot)
        return slot

    def remove(self, name: str) -> RosterSlot | None:
        """Annulla un acquisto: serve quando in asta si sbaglia a dettare."""
        needle = name.strip().lower()
        for i, slot in enumerate(self.acquired):
            if slot.player.name.lower() == needle:
                return self.acquired.pop(i)
        return None

    def to_dict(self) -> dict:
        return {
            "giocatori": [s.to_dict() for s in self.acquired],
            "per_ruolo": {
                r: {"presi": self.count(r), "mancanti": self.missing(r), "spesi": self.spent_on(r)}
                for r in self.slots_target
            },
            "totale_speso": self.total_spent,
            "slot_mancanti": self.total_missing,
        }
