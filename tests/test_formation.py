"""Test del motore di formazione."""

from __future__ import annotations

import pytest

from jarvis.fanta.formation import (
    MatchContext,
    best_formation,
    build_formation,
    compare_players,
    expected_score,
)
from jarvis.fanta.models import Player


def p(name, role, fm=6.0, prob=1.0, status="ok", rigorista=False) -> Player:
    return Player(
        name=name, team="XXX", role=role, fantamedia=fm,
        starter_probability=prob, status=status, penalty_taker=rigorista,
    )


@pytest.fixture
def rosa() -> list[Player]:
    """Rosa completa da 25: 3 portieri, 8 difensori, 8 centrocampisti, 6 attaccanti."""
    players = [p(f"Por{i}", "P", 6.0 + i * 0.1) for i in range(3)]
    players += [p(f"Dif{i}", "D", 5.8 + i * 0.1) for i in range(8)]
    players += [p(f"Cen{i}", "C", 6.0 + i * 0.1) for i in range(8)]
    players += [p(f"Att{i}", "A", 6.5 + i * 0.2) for i in range(6)]
    return players


# --------------------------------------------------------- punteggio atteso

def test_indisponibile_vale_zero():
    score = expected_score(p("Rotto", "A", 9.0, status="infortunato"))
    assert score.expected == 0.0
    assert score.excluded == "infortunato"


def test_la_titolarita_domina_sul_talento():
    """Un fuoriclasse in panchina vale meno di un titolare mediocre."""
    fenomeno = expected_score(p("Fenomeno", "A", 8.0, prob=0.2))
    onesto = expected_score(p("Onesto", "A", 6.3, prob=1.0))
    assert onesto.expected > fenomeno.expected


def test_il_rigorista_prende_un_premio():
    con = expected_score(p("Rigorista", "A", 6.5, rigorista=True))
    senza = expected_score(p("Normale", "A", 6.5))
    assert con.expected > senza.expected


def test_avversario_e_campo_spostano_il_punteggio():
    facile = expected_score(p("X", "A", 6.5), MatchContext(opponent_strength=1.0, home=True))
    difficile = expected_score(p("X", "A", 6.5), MatchContext(opponent_strength=5.0, home=False))
    assert facile.expected > difficile.expected


def test_il_dettaglio_spiega_il_punteggio():
    score = expected_score(p("X", "C", 6.4, prob=0.7, rigorista=True))
    assert set(score.breakdown) == {"base", "avversario", "campo", "rigorista", "titolarita"}
    assert score.breakdown["titolarita"] < 0


# ------------------------------------------------------------- formazione

def test_il_modulo_determina_i_reparti(rosa):
    formazione = build_formation(rosa, "3-4-3")
    ruoli = [s.player.role for s in formazione.starters]
    assert ruoli.count("P") == 1
    assert ruoli.count("D") == 3
    assert ruoli.count("C") == 4
    assert ruoli.count("A") == 3
    assert len(formazione.starters) == 11


def test_modulo_inesistente(rosa):
    with pytest.raises(ValueError, match="modulo non riconosciuto"):
        build_formation(rosa, "2-2-6")


def test_gli_indisponibili_non_scendono_in_campo(rosa):
    rosa[11].status = "squalificato"     # Cen0
    rosa[12].status = "infortunato"      # Cen1
    formazione = build_formation(rosa, "3-5-2")
    schierati = {s.player.name for s in formazione.starters}
    assert "Cen0" not in schierati and "Cen1" not in schierati
    assert any("squalificato" in w for w in formazione.warnings)


def test_avverte_se_mancano_giocatori_per_il_modulo():
    corta = [p("Por", "P")] + [p(f"D{i}", "D") for i in range(2)] + [p(f"C{i}", "C") for i in range(5)]
    formazione = build_formation(corta, "5-3-2")
    assert any("servono" in w for w in formazione.warnings)


def test_avverte_sui_titolari_incerti(rosa):
    for giocatore in rosa:
        giocatore.starter_probability = 0.4
    formazione = build_formation(rosa, "4-4-2")
    assert any("titolarita' e' incerta" in w for w in formazione.warnings)


def test_la_panchina_e_ordinata_per_valore(rosa):
    formazione = build_formation(rosa, "3-4-3")
    valori = [s.expected for s in formazione.bench]
    assert valori == sorted(valori, reverse=True)


# --------------------------------------------------- scelta del modulo

def test_il_modulo_migliore_segue_i_giocatori_forti(rosa):
    """Con un attacco fortissimo e una difesa scarsa deve uscire un modulo offensivo."""
    for giocatore in rosa:
        if giocatore.role == "A":
            giocatore.fantamedia = 9.0
        elif giocatore.role == "D":
            giocatore.fantamedia = 5.0
    assert best_formation(rosa).module.endswith("-3")


def test_il_modulo_migliore_batte_sempre_uno_a_caso(rosa):
    migliore = best_formation(rosa)
    for modulo in ("3-5-2", "4-4-2", "5-3-2"):
        assert migliore.total >= build_formation(rosa, modulo).total - 1e-9


def test_rosa_incompleta_nessun_modulo_copribile():
    with pytest.raises(ValueError, match="nessun modulo copribile"):
        best_formation([p("Por", "P"), p("Att", "A")])


# ------------------------------------------------------------- confronto

def test_confronto_sceglie_il_titolare_certo():
    esito = compare_players(p("Panchinaro", "A", 8.0, prob=0.2), p("Titolare", "A", 6.5, prob=1.0))
    assert esito["scelta"] == "Titolare"
    assert "campo" in esito["motivo"]


def test_confronto_scarta_l_indisponibile():
    esito = compare_players(p("Sano", "C", 6.0), p("Rotto", "C", 9.0, status="infortunato"))
    assert esito["scelta"] == "Sano"
    assert "infortunato" in esito["motivo"]


def test_confronto_dichiara_la_parita():
    esito = compare_players(p("Uno", "C", 6.2), p("Due", "C", 6.2))
    assert "equivalenti" in esito["motivo"]


# --------------------------------------- stima quando manca la fantamedia

def test_senza_storico_la_quotazione_fa_da_stima():
    """Un giocatore da 40 crediti deve valere piu' di uno da 5, non uguale."""
    from jarvis.fanta.formation import base_expectation

    caro = Player(name="Top", team="X", role="A", quotation=40.0)
    economico = Player(name="Riserva", team="X", role="A", quotation=5.0)

    base_caro, origine = base_expectation(caro)
    base_economico, _ = base_expectation(economico)
    assert base_caro > base_economico
    assert origine == "stimata dalla quotazione"


def test_lo_storico_batte_la_stima():
    from jarvis.fanta.formation import base_expectation

    con_storico = Player(name="X", team="X", role="A", quotation=40.0, fantamedia=6.1)
    base, origine = base_expectation(con_storico)
    assert base == 6.1
    assert origine == "storica"


def test_la_stima_e_dichiarata_nel_risultato():
    """Chi legge deve sapere che quel numero e' una stima, non un dato."""
    score = expected_score(Player(name="X", team="X", role="C", quotation=20.0))
    assert score.to_dict()["origine_base"] == "stimata dalla quotazione"
