"""Scelta della formazione: chi schierare, con quale modulo, e chi in panchina.

Il punteggio atteso di un giocatore non e' la sua fantamedia storica: e' quella
fantamedia corretta da cio' che sappiamo di QUESTA giornata. Il modello e'
volutamente trasparente e a pesi espliciti, cosi' l'assistente puo' spiegare a
voce perche' preferisce un giocatore a un altro invece di dire "me lo dice
l'algoritmo".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .knowledge import MODULI_CLASSIC
from .models import Player

# Pesi del modello di punteggio atteso.
W_STARTER = 2.2        # peso della probabilita' di scendere in campo
W_OPPONENT = 0.30      # peso della difficolta' dell'avversario (scala 1-5)
W_HOME = 0.15          # vantaggio del giocare in casa
W_PENALTY = 0.45       # premio al rigorista designato
BASE_FM = 6.0          # fantamedia di riferimento quando manca ogni dato
FM_MAX_STIMATA = 8.5   # tetto della stima ricavata dalla quotazione


@dataclass
class MatchContext:
    """Il contesto di giornata di un singolo giocatore."""

    opponent_strength: float = 3.0   # 1 = avversario materasso, 5 = corazzata
    home: bool = True
    note: str = ""


def base_expectation(player: Player) -> tuple[float, str]:
    """Fantamedia di partenza e da dove viene.

    Se il dato storico c'e', si usa quello. Altrimenti si stima dalla
    quotazione: il mercato non e' un oracolo, ma un giocatore da 40 crediti
    rende sistematicamente piu' di uno da 5, e ignorarlo significherebbe
    trattare tutti come identici. La stima e' volutamente compressa (curva
    logaritmica, tetto a 8.5) e viene sempre dichiarata come tale.
    """
    if player.fantamedia is not None:
        return float(player.fantamedia), "storica"
    quotation = max(float(player.quotation), float(player.fvm) / 10.0, 1.0)
    stimata = 5.6 + 0.95 * math.log1p(quotation / 10.0)
    return min(stimata, FM_MAX_STIMATA), "stimata dalla quotazione"


@dataclass
class PlayerScore:
    """Punteggio atteso con la sua spiegazione, voce per voce."""

    player: Player
    expected: float
    breakdown: dict[str, float] = field(default_factory=dict)
    excluded: str | None = None
    base_source: str = "storica"

    def to_dict(self) -> dict:
        data = {
            "nome": self.player.name,
            "ruolo": self.player.role,
            "squadra": self.player.team,
            "punteggio_atteso": round(self.expected, 2),
            "dettaglio": {k: round(v, 2) for k, v in self.breakdown.items()},
            "origine_base": self.base_source,
        }
        if self.excluded:
            data["escluso"] = self.excluded
        return data


def expected_score(player: Player, context: MatchContext | None = None) -> PlayerScore:
    """Fantamedia attesa di un giocatore per la giornata.

    Partiamo dalla fantamedia nota (o da 6.0 se manca), poi:
      - moltiplichiamo per la probabilita' di giocare, che e' il fattore che
        domina tutti gli altri: un fuoriclasse in panchina vale zero;
      - correggiamo per avversario e campo;
      - aggiungiamo il premio al rigorista.
    """
    context = context or MatchContext()
    base, base_source = base_expectation(player)

    if not player.available:
        return PlayerScore(player, 0.0, {"base": base}, excluded=player.status,
                           base_source=base_source)

    prob = player.starter_probability if player.starter_probability is not None else 0.8
    prob = float(min(max(prob, 0.0), 1.0))

    opponent = W_OPPONENT * (3.0 - float(context.opponent_strength))
    home = W_HOME if context.home else -W_HOME
    penalty = W_PENALTY if player.penalty_taker else 0.0
    # La probabilita' di giocare non scala solo il bonus: scala tutto il valore.
    starter_penalty = -W_STARTER * (1.0 - prob)

    total = base + opponent + home + penalty + starter_penalty
    return PlayerScore(
        player=player,
        expected=max(0.0, total),
        breakdown={
            "base": base,
            "avversario": opponent,
            "campo": home,
            "rigorista": penalty,
            "titolarita": starter_penalty,
        },
        base_source=base_source,
    )


@dataclass
class Formation:
    """Una formazione proposta."""

    module: str
    starters: list[PlayerScore]
    bench: list[PlayerScore]
    total: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "modulo": self.module,
            "totale_atteso": round(self.total, 2),
            "titolari": [s.to_dict() for s in self.starters],
            "panchina": [s.to_dict() for s in self.bench],
            "avvertenze": self.warnings,
        }


def _pick(pool: list[PlayerScore], count: int) -> tuple[list[PlayerScore], list[PlayerScore]]:
    ordered = sorted(pool, key=lambda s: s.expected, reverse=True)
    return ordered[:count], ordered[count:]


def build_formation(
    players: list[Player],
    module: str,
    contexts: dict[str, MatchContext] | None = None,
) -> Formation:
    """Costruisce la formazione migliore per un modulo dato."""
    if module not in MODULI_CLASSIC:
        raise ValueError(f"modulo non riconosciuto: {module}. Validi: {', '.join(MODULI_CLASSIC)}")
    n_def, n_mid, n_att = MODULI_CLASSIC[module]
    contexts = contexts or {}

    scored = [expected_score(p, contexts.get(p.name)) for p in players]
    available = [s for s in scored if s.excluded is None]
    unavailable = [s for s in scored if s.excluded is not None]

    by_role = {r: [s for s in available if s.player.role == r] for r in "PDCA"}
    warnings: list[str] = []

    starters: list[PlayerScore] = []
    bench: list[PlayerScore] = []
    for role, needed in (("P", 1), ("D", n_def), ("C", n_mid), ("A", n_att)):
        chosen, rest = _pick(by_role[role], needed)
        if len(chosen) < needed:
            warnings.append(
                f"servono {needed} giocatori di ruolo {role} ma ne hai {len(chosen)} disponibili"
            )
        starters.extend(chosen)
        bench.extend(rest)

    for score in starters:
        prob = score.player.starter_probability
        if prob is not None and prob < 0.6:
            warnings.append(
                f"{score.player.name} e' schierato ma la titolarita' e' incerta ({prob:.0%})"
            )
    for score in unavailable:
        warnings.append(f"{score.player.name} indisponibile ({score.excluded})")

    bench.sort(key=lambda s: s.expected, reverse=True)
    return Formation(
        module=module,
        starters=starters,
        bench=bench,
        total=sum(s.expected for s in starters),
        warnings=warnings,
    )


def best_formation(
    players: list[Player],
    modules: list[str] | None = None,
    contexts: dict[str, MatchContext] | None = None,
) -> Formation:
    """Prova tutti i moduli ammessi e tiene il migliore.

    Il modulo si sceglie dopo aver visto chi gioca, non prima: e' esattamente
    quello che fa questa funzione.
    """
    candidates = []
    for module in (modules or list(MODULI_CLASSIC)):
        try:
            formation = build_formation(players, module, contexts)
        except ValueError:
            continue
        # Un modulo che non riesco a coprire e' inutilizzabile, per quanto valga.
        if any("servono" in w for w in formation.warnings):
            continue
        candidates.append(formation)

    if not candidates:
        raise ValueError(
            "nessun modulo copribile con questi giocatori: controlla ruoli e indisponibili"
        )
    return max(candidates, key=lambda f: f.total)


def compare_players(a: Player, b: Player, ctx_a: MatchContext | None = None,
                    ctx_b: MatchContext | None = None) -> dict:
    """Confronto diretto fra due giocatori, con la ragione della scelta.

    E' la domanda piu' frequente della domenica mattina: "chi schiero fra i due?".
    """
    score_a, score_b = expected_score(a, ctx_a), expected_score(b, ctx_b)
    winner, loser = (score_a, score_b) if score_a.expected >= score_b.expected else (score_b, score_a)
    gap = winner.expected - loser.expected

    if winner.excluded is None and loser.excluded is not None:
        reason = f"{loser.player.name} e' {loser.excluded}: non e' una scelta"
    elif gap < 0.15:
        reason = "sostanzialmente equivalenti: decidi col fiuto o con l'avversario piu' morbido"
    else:
        deltas = {
            k: winner.breakdown.get(k, 0.0) - loser.breakdown.get(k, 0.0)
            for k in ("base", "titolarita", "avversario", "campo", "rigorista")
        }
        driver = max(deltas, key=lambda k: abs(deltas[k]))
        etichette = {
            "base": "rende di piu' sul lungo periodo",
            "titolarita": "e' piu' sicuro di scendere in campo",
            "avversario": "ha l'avversario piu' abbordabile",
            "campo": "gioca in casa",
            "rigorista": "tira i rigori",
        }
        reason = f"{winner.player.name} {etichette[driver]}"

    return {
        "scelta": winner.player.name,
        "distacco": round(gap, 2),
        "motivo": reason,
        "dettaglio": {a.name: score_a.to_dict(), b.name: score_b.to_dict()},
    }
