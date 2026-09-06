"""Motore d'asta: quanto posso offrire, adesso, senza rovinarmi la rosa.

La domanda che si fa mille volte durante un'asta e' sempre la stessa:
"posso arrivare a X?". La risposta dipende da tre vincoli che si intrecciano:

    vincolo duro     crediti residui meno gli slot ancora da riempire.
                     Superarlo significa non poter completare la rosa: e' un
                     limite invalicabile, non un consiglio;
    piano di reparto quanto avevo destinato a quel ruolo e quanto ne resta;
    valore           quanto vale il giocatore, riscalato sul MIO budget.

Il motore restituisce sempre i tre numeri separati, perche' in asta serve
sapere non solo il tetto ma anche perche' e' quello.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .knowledge import BUDGET_SPLIT_DEFAULT, BUDGET_SPLIT_STRATEGIE, PIANO_FASCE, ROSA_STANDARD
from .models import Player, Roster


@dataclass
class BidAdvice:
    """Consiglio su una singola offerta."""

    player: str
    role: str
    valore_stimato: int      # quanto vale sul mio budget
    offerta_massima: int     # il tetto che consiglio
    limite_assoluto: int     # oltre questo non completo la rosa
    budget_reparto_residuo: int
    verdetto: str
    motivo: str

    def to_dict(self) -> dict:
        return {
            "giocatore": self.player,
            "ruolo": self.role,
            "valore_stimato": self.valore_stimato,
            "offerta_massima": self.offerta_massima,
            "limite_assoluto": self.limite_assoluto,
            "budget_reparto_residuo": self.budget_reparto_residuo,
            "verdetto": self.verdetto,
            "motivo": self.motivo,
        }


@dataclass
class AuctionState:
    """Stato vivo dell'asta: budget, rosa, piano per reparto.

    Aggiornabile a voce durante l'asta ("preso Lautaro a 180") tramite gli
    strumenti dell'agente.
    """

    budget: int = 500
    slots: dict[str, int] = field(default_factory=lambda: dict(ROSA_STANDARD))
    budget_split: dict[str, float] = field(default_factory=lambda: dict(BUDGET_SPLIT_DEFAULT))
    roster: Roster = field(init=False)
    listone_budget_reference: int = 500  # budget su cui sono tarate le quotazioni

    def __post_init__(self) -> None:
        self.roster = Roster(slots_target=dict(self.slots))

    # ------------------------------------------------------------- strategia
    def apply_strategy(self, name: str) -> dict[str, float]:
        """Cambia la ripartizione del budget (es. 'modificatore')."""
        split = BUDGET_SPLIT_STRATEGIE.get(name.strip().lower())
        if not split:
            raise ValueError(
                f"strategia sconosciuta: {name}. Disponibili: {', '.join(BUDGET_SPLIT_STRATEGIE)}"
            )
        self.budget_split = dict(split)
        return self.budget_split

    # --------------------------------------------------------------- budget
    @property
    def credits_left(self) -> int:
        return self.budget - self.roster.total_spent

    @property
    def slots_left(self) -> int:
        return self.roster.total_missing

    def max_affordable(self) -> int:
        """Vincolo duro: il massimo offribile lasciando 1 credito per ogni altro slot."""
        if self.slots_left <= 0:
            return 0
        return max(1, self.credits_left - (self.slots_left - 1))

    def role_budget(self, role: str) -> int:
        """Crediti destinati al reparto secondo la ripartizione scelta."""
        return int(round(self.budget * self.budget_split.get(role, 0.0)))

    def role_budget_left(self, role: str) -> int:
        return self.role_budget(role) - self.roster.spent_on(role)

    def slot_target_price(self, role: str) -> int:
        """Prezzo di riferimento del PROSSIMO slot di quel reparto.

        Il piano a fasce dice che il primo attaccante prende il 38% del budget
        d'attacco, il secondo il 26% e cosi' via: chiedendo il target dello slot
        successivo si sa subito se si sta pagando dentro o fuori piano.
        """
        tiers = PIANO_FASCE.get(role, [])
        taken = self.roster.count(role)
        if not tiers or taken >= len(tiers):
            return max(1, self.role_budget_left(role) // max(1, self.roster.missing(role) or 1))
        return max(1, int(round(self.role_budget(role) * tiers[taken])))

    # ---------------------------------------------------------------- valore
    def player_value(self, player: Player) -> int:
        """Valore del giocatore riscalato sul mio budget.

        Le quotazioni del listone sono tarate su un budget di riferimento
        (tipicamente 500): con 250 o 1000 crediti vanno riscalate, altrimenti
        ogni numero e' fuori scala.
        """
        scale = self.budget / max(1, self.listone_budget_reference)
        base = player.quotation if player.quotation > 1 else max(player.fvm / 10.0, 1.0)
        return max(1, int(round(base * scale)))

    # -------------------------------------------------------------- consigli
    def advise(self, player: Player, *, current_bid: int = 0, aggressiveness: float = 1.0) -> BidAdvice:
        """Tetto d'offerta e verdetto su un giocatore.

        `aggressiveness` 1.0 = piano; 1.2 = "questo lo voglio"; 0.8 = "solo se
        capita a poco".
        """
        role = player.role
        value = self.player_value(player)
        hard_cap = self.max_affordable()
        role_left = self.role_budget_left(role)
        target = self.slot_target_price(role)

        if self.roster.missing(role) == 0:
            return BidAdvice(
                player=player.name, role=role, valore_stimato=value, offerta_massima=0,
                limite_assoluto=hard_cap, budget_reparto_residuo=role_left,
                verdetto="lascia",
                motivo=f"gli slot {role} sono gia' completi: ogni credito qui e' sprecato",
            )

        # Il tetto nasce dal valore, corretto dal piano di reparto e dalla voglia.
        planned = max(value, target)
        ceiling = int(round(planned * aggressiveness))
        # Se il reparto ha ancora molto budget, posso spingere fin la'.
        ceiling = min(ceiling, max(role_left, target))
        ceiling = max(1, min(ceiling, hard_cap))

        if current_bid and current_bid >= ceiling:
            verdict = "lascia"
            motivo = (
                f"a {current_bid} sei oltre il tuo tetto di {ceiling}: "
                f"con {self.credits_left} crediti e {self.slots_left} slot non conviene"
            )
        elif current_bid and current_bid <= int(ceiling * 0.6):
            verdict = "affare"
            motivo = f"a {current_bid} paghi molto sotto il tetto di {ceiling}: rilancia"
        elif ceiling >= value * 1.15:
            verdict = "prendi"
            motivo = f"puoi arrivare a {ceiling} restando dentro il piano del reparto {role}"
        else:
            verdict = "prezzo giusto"
            motivo = f"il tetto sensato e' {ceiling}; oltre stai pagando la fretta, non il giocatore"

        return BidAdvice(
            player=player.name, role=role, valore_stimato=value, offerta_massima=ceiling,
            limite_assoluto=hard_cap, budget_reparto_residuo=role_left,
            verdetto=verdict, motivo=motivo,
        )

    # ------------------------------------------------------------- mutazioni
    def buy(self, player: Player, price: int) -> dict:
        """Registra un acquisto e restituisce la situazione aggiornata."""
        price = int(price)
        if price > self.credits_left:
            raise ValueError(
                f"{price} crediti ma ne hai {self.credits_left}: acquisto impossibile"
            )
        if price > self.max_affordable():
            raise ValueError(
                f"a {price} non riusciresti a completare la rosa "
                f"(massimo offribile ora: {self.max_affordable()})"
            )
        self.roster.add(player, price)
        return self.report()

    def undo(self, name: str) -> dict:
        """Annulla un acquisto (in asta si detta in fretta e si sbaglia)."""
        removed = self.roster.remove(name)
        if removed is None:
            raise ValueError(f"{name} non risulta in rosa")
        return self.report()

    # ---------------------------------------------------------------- report
    def report(self) -> dict:
        """Fotografia dell'asta: quello che l'assistente legge ad alta voce."""
        per_role = {}
        for role in self.slots:
            per_role[role] = {
                "presi": self.roster.count(role),
                "mancanti": self.roster.missing(role),
                "spesi": self.roster.spent_on(role),
                "budget_reparto": self.role_budget(role),
                "residuo_reparto": self.role_budget_left(role),
                "prezzo_prossimo_slot": self.slot_target_price(role),
            }
        return {
            "budget": self.budget,
            "crediti_residui": self.credits_left,
            "slot_mancanti": self.slots_left,
            "massimo_offribile_ora": self.max_affordable(),
            "media_per_slot_residuo": round(self.credits_left / self.slots_left, 1) if self.slots_left else 0.0,
            "reparti": per_role,
            "rosa": [s.to_dict() for s in self.roster.acquired],
        }

    def plan(self) -> dict:
        """Il piano d'asta iniziale: quanto spendere per ogni slot di ogni reparto."""
        return {
            role: {
                "budget_reparto": self.role_budget(role),
                "slot": self.slots[role],
                "prezzi_obiettivo": [
                    max(1, int(round(self.role_budget(role) * tier)))
                    for tier in PIANO_FASCE.get(role, [])[: self.slots[role]]
                ],
            }
            for role in self.slots
        }
