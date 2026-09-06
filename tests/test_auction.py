"""Test del motore d'asta. Il vincolo che non deve mai saltare: poter
completare la rosa."""

from __future__ import annotations

import pytest

from jarvis.fanta.auction import AuctionState
from jarvis.fanta.models import Player


def player(name="Tizio", role="A", quotation=30.0, fvm=200.0) -> Player:
    return Player(name=name, team="MIL", role=role, quotation=quotation, fvm=fvm)


@pytest.fixture
def asta() -> AuctionState:
    return AuctionState(budget=500, slots={"P": 3, "D": 8, "C": 8, "A": 6})


# ------------------------------------------------------------------- budget

def test_ripartizione_iniziale_copre_il_budget(asta):
    totale = sum(asta.role_budget(r) for r in asta.slots)
    assert 0.98 * asta.budget <= totale <= asta.budget


def test_massimo_offribile_lascia_un_credito_per_slot(asta):
    # 25 slot, 500 crediti: posso arrivare a 500 - 24 = 476.
    assert asta.max_affordable() == 476


def test_il_massimo_offribile_scende_dopo_ogni_acquisto(asta):
    asta.buy(player("Lautaro", "A"), 200)
    assert asta.credits_left == 300
    assert asta.slots_left == 24
    assert asta.max_affordable() == 300 - 23


def test_non_posso_spendere_tutto_e_restare_con_slot_vuoti(asta):
    with pytest.raises(ValueError, match="completare la rosa"):
        asta.buy(player("Fenomeno", "A"), 500)


def test_acquisto_oltre_i_crediti_rifiutato(asta):
    asta.buy(player("Uno", "A"), 400)
    with pytest.raises(ValueError, match="crediti"):
        asta.buy(player("Due", "A"), 200)


def test_annullare_un_acquisto_sbagliato(asta):
    asta.buy(player("Errore", "C"), 90)
    assert asta.credits_left == 410
    asta.undo("errore")
    assert asta.credits_left == 500
    assert asta.roster.count("C") == 0


def test_annullare_un_giocatore_mai_preso(asta):
    with pytest.raises(ValueError, match="non risulta in rosa"):
        asta.undo("Nessuno")


# ------------------------------------------------------------------ consigli

def test_non_consiglia_di_comprare_un_reparto_completo(asta):
    for i in range(3):
        asta.buy(player(f"Portiere{i}", "P", 10.0), 5)
    advice = asta.advise(player("Portiere4", "P"))
    assert advice.verdetto == "lascia"
    assert advice.offerta_massima == 0
    assert "completi" in advice.motivo


def test_il_tetto_non_supera_mai_il_limite_assoluto(asta):
    for i in range(16):  # riempio difesa e centrocampo spendendo quasi tutto
        asta.buy(player(f"Tizio{i}", "D" if i < 8 else "C", 5.0), 28)
    advice = asta.advise(player("Costoso", "A", quotation=200.0))
    assert advice.offerta_massima <= advice.limite_assoluto
    assert advice.offerta_massima <= asta.credits_left


def test_offerta_gia_oltre_il_tetto_si_lascia(asta):
    advice = asta.advise(player("Caro", "A", quotation=40.0), current_bid=400)
    assert advice.verdetto == "lascia"


def test_offerta_bassa_e_un_affare(asta):
    advice = asta.advise(player("Occasione", "A", quotation=60.0), current_bid=5)
    assert advice.verdetto == "affare"


def test_aggressivita_alza_il_tetto(asta):
    calmo = asta.advise(player("Obiettivo", "A", quotation=50.0), aggressiveness=0.8)
    deciso = asta.advise(player("Obiettivo", "A", quotation=50.0), aggressiveness=1.3)
    assert deciso.offerta_massima >= calmo.offerta_massima


# -------------------------------------------------------------- scala budget

def test_le_quotazioni_si_riscalano_sul_mio_budget():
    """Con 250 crediti un giocatore da 60 sul listone (tarato 500) ne vale ~30."""
    piccola = AuctionState(budget=250)
    grande = AuctionState(budget=1000)
    p = player(quotation=60.0)
    assert piccola.player_value(p) == 30
    assert grande.player_value(p) == 120


def test_piano_a_fasce_decrescente(asta):
    prezzi = asta.plan()["A"]["prezzi_obiettivo"]
    assert prezzi == sorted(prezzi, reverse=True)
    assert sum(prezzi) <= asta.role_budget("A") * 1.02


def test_il_prezzo_obiettivo_scende_man_mano_che_riempio_il_reparto(asta):
    primo = asta.slot_target_price("A")
    asta.buy(player("Top", "A"), primo)
    assert asta.slot_target_price("A") < primo


def test_strategia_modificatore_sposta_crediti_in_difesa(asta):
    difesa_prima = asta.role_budget("D")
    asta.apply_strategy("modificatore")
    assert asta.role_budget("D") > difesa_prima


def test_strategia_sconosciuta(asta):
    with pytest.raises(ValueError, match="strategia sconosciuta"):
        asta.apply_strategy("fantasia")


# -------------------------------------------------------------------- report

def test_report_completo(asta):
    asta.buy(player("Bomber", "A"), 150)
    report = asta.report()
    assert report["crediti_residui"] == 350
    assert report["slot_mancanti"] == 24
    assert report["reparti"]["A"]["presi"] == 1
    assert report["rosa"][0]["nome"] == "Bomber"


def test_niente_doppioni_in_rosa(asta):
    asta.buy(player("Unico", "C"), 30)
    with pytest.raises(ValueError, match="gia' in rosa"):
        asta.buy(player("Unico", "C"), 20)


def test_slot_di_ruolo_non_sforabili(asta):
    for i in range(6):
        asta.buy(player(f"Att{i}", "A", 5.0), 3)
    with pytest.raises(ValueError, match="slot A"):
        asta.buy(player("Att7", "A"), 3)
