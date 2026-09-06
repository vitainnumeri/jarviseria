"""Test degli strumenti dell'agente: e' il contratto fra la voce e i motori."""

from __future__ import annotations

import pytest

from jarvis.config import PROJECT_ROOT
from jarvis.fanta.auction import AuctionState
from jarvis.fanta.listone import Listone
from jarvis.llm.tools import TOOL_SCHEMAS, FantaTools

ESEMPIO = PROJECT_ROOT / "data" / "esempio_listone_PLACEHOLDER.csv"


@pytest.fixture
def tools() -> FantaTools:
    return FantaTools(Listone.from_csv(ESEMPIO), AuctionState(budget=500))


# ---------------------------------------------------------------- schemi

def test_ogni_schema_ha_un_metodo_corrispondente(tools):
    for schema in TOOL_SCHEMAS:
        assert callable(getattr(tools, schema["name"], None)), f"manca {schema['name']}"


def test_ogni_schema_e_descritto(tools):
    for schema in TOOL_SCHEMAS:
        assert len(schema["description"]) > 40
        assert schema["input_schema"]["type"] == "object"


# ---------------------------------------------------------------- ricerca

def test_cerca_giocatore_tollera_la_trascrizione(tools):
    result = tools.cerca_giocatore("vlahovich")
    assert result["trovato"]
    assert result["candidati"][0]["nome"] == "Vlahovic"


def test_cerca_giocatore_inesistente(tools):
    result = tools.cerca_giocatore("Pinco Pallino")
    assert result["trovato"] is False
    assert "trascritto male" in result["nota"]


def test_senza_listone_lo_dice_invece_di_inventare():
    vuoti = FantaTools(Listone(), AuctionState())
    assert "listone non caricato" in vuoti.cerca_giocatore("Lautaro")["errore"]


# ------------------------------------------------------------------ asta

def test_consiglio_offerta_usa_i_crediti_reali(tools):
    advice = tools.consiglio_offerta("Lautaro Martinez")
    assert advice["offerta_massima"] <= advice["limite_assoluto"]
    assert advice["crediti_residui"] == 500
    assert advice["slot_mancanti"] == 25


def test_il_consiglio_cambia_dopo_gli_acquisti(tools):
    prima = tools.consiglio_offerta("Lookman")["offerta_massima"]
    tools.registra_acquisto("Lautaro Martinez", 200)
    tools.registra_acquisto("Leao", 150)
    dopo = tools.consiglio_offerta("Lookman")["offerta_massima"]
    assert dopo < prima


def test_registra_e_annulla(tools):
    tools.registra_acquisto("Barella", 60)
    assert tools.stato_asta()["crediti_residui"] == 440
    tools.annulla_acquisto("Barella")
    assert tools.stato_asta()["crediti_residui"] == 500


def test_acquisto_impossibile_spiegato(tools):
    result = tools.registra_acquisto("Lautaro Martinez", 499)
    assert "errore" in result
    assert "rosa" in result["errore"]


def test_annullare_un_giocatore_mai_preso(tools):
    assert "errore" in tools.annulla_acquisto("Nessuno")


def test_giocatore_fuori_listone_registrabile(tools):
    """Un arrivo dell'ultimo minuto non deve bloccare l'asta."""
    result = tools.registra_acquisto("Nuovo Acquisto Sconosciuto", 25)
    assert result["crediti_residui"] == 475


def test_piano_asta_con_strategia(tools):
    difesa_prima = tools.piano_asta()["piano"]["D"]["budget_reparto"]
    dopo = tools.piano_asta(strategia="modificatore")
    assert dopo["piano"]["D"]["budget_reparto"] > difesa_prima


def test_strategia_sconosciuta_non_esplode(tools):
    assert "errore" in tools.piano_asta(strategia="a caso")


# ------------------------------------------------------------ formazione

def test_formazione_dai_nomi(tools):
    nomi = ["Maignan", "Bastoni", "Dimarco", "Bremer", "Barella", "Calhanoglu",
            "Pulisic", "Kvaratskhelia", "Lautaro Martinez", "Vlahovic", "Lookman"]
    result = tools.costruisci_formazione(giocatori=nomi)
    assert len(result["titolari"]) == 11


def test_gli_indisponibili_restano_fuori(tools):
    nomi = ["Maignan", "Bastoni", "Dimarco", "Bremer", "Gatti", "Barella", "Calhanoglu",
            "Pulisic", "Kvaratskhelia", "Lautaro Martinez", "Vlahovic", "Lookman", "Leao"]
    result = tools.costruisci_formazione(giocatori=nomi, indisponibili=["Lookman"])
    assert "Lookman" not in {t["nome"] for t in result["titolari"]}


def test_formazione_senza_giocatori(tools):
    assert "errore" in tools.costruisci_formazione(giocatori=[])


def test_la_formazione_non_sporca_il_listone(tools):
    """Marcare un infortunato per una giornata non deve alterare il listone."""
    tools.costruisci_formazione(giocatori=["Lautaro Martinez", "Leao"], indisponibili=["Leao"])
    assert tools.listone.get("Leao").status == "ok"


def test_confronto_fra_due_giocatori(tools):
    result = tools.confronta_giocatori("Lautaro Martinez", "Dovbyk")
    assert result["scelta"] in {"Lautaro Martinez", "Dovbyk"}
    assert result["motivo"]


# ---------------------------------------------------------- regolamento

def test_regolamento_bonus_malus(tools):
    result = tools.regolamento()
    assert result["bonus_malus"]["gol_segnato"] == 3.0
    assert "impostazioni standard" in result["nota"]


def test_modificatore_di_difesa_calcolato(tools):
    assert tools.regolamento(media_reparto=6.6)["bonus_modificatore"] == 3


def test_glossario(tools):
    assert "media voto" in tools.regolamento(argomento="fantamedia")["significato"]


# -------------------------------------------------------------- dispatch

def test_dispatch_strumento_sconosciuto(tools):
    assert "sconosciuto" in tools.dispatch("inventato", {})["errore"]


def test_dispatch_argomenti_sbagliati(tools):
    assert "non validi" in tools.dispatch("cerca_giocatore", {"sbagliato": 1})["errore"]


def test_dispatch_non_espone_i_metodi_privati(tools):
    assert "sconosciuto" in tools.dispatch("_resolve", {"nome": "x"})["errore"]
