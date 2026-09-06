"""Test del caricamento del listone e della ricerca per voce."""

from __future__ import annotations

import pytest

from jarvis.config import PROJECT_ROOT
from jarvis.fanta.listone import Listone, load_listone, normalize_text

ESEMPIO = PROJECT_ROOT / "data" / "esempio_listone_PLACEHOLDER.csv"


@pytest.fixture
def listone() -> Listone:
    return Listone.from_csv(ESEMPIO)


# ------------------------------------------------------------- caricamento

def test_carica_il_formato_ufficiale(listone):
    """Le intestazioni dell'export Fantacalcio.it vengono riconosciute cosi' come sono."""
    assert len(listone) == 32
    lautaro = listone.get("Lautaro Martinez")
    assert lautaro is not None
    assert lautaro.team == "INTER"
    assert lautaro.role == "A"
    assert lautaro.quotation == 42.0
    assert lautaro.mantra_roles == ["Pc"]


def test_separatore_riconosciuto_da_solo(tmp_path):
    csv = tmp_path / "virgole.csv"
    csv.write_text("Nome,Squadra,R,Qt.A\nTizio,MIL,A,30\n", encoding="utf-8")
    assert Listone.from_csv(csv).get("Tizio").quotation == 30.0


def test_file_mancante_spiega_cosa_fare(tmp_path):
    with pytest.raises(FileNotFoundError, match="fantacalcio.it"):
        Listone.from_csv(tmp_path / "assente.csv")


def test_senza_colonna_nomi(tmp_path):
    csv = tmp_path / "rotto.csv"
    csv.write_text("Squadra;R\nMIL;A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nomi dei giocatori"):
        Listone.from_csv(csv)


def test_listone_assente_non_blocca_l_assistente():
    """Senza listone l'assistente resta usabile: parla di strategia, non di prezzi."""
    vuoto = load_listone("/percorso/inesistente.csv")
    assert len(vuoto) == 0
    assert not vuoto


def test_virgola_decimale_accettata(tmp_path):
    csv = tmp_path / "decimali.csv"
    csv.write_text("Nome;R;Qt.A;Fm\nTizio;C;12,5;6,75\n", encoding="utf-8")
    giocatore = Listone.from_csv(csv).get("Tizio")
    assert giocatore.quotation == 12.5
    assert giocatore.fantamedia == 6.75


# ------------------------------------------------- ricerca tollerante (voce)

def test_normalizzazione_accenti_e_punteggiatura():
    assert normalize_text("Vlahović, D.") == "vlahovic d"
    assert normalize_text("  Di  Marco ") == "di marco"


@pytest.mark.parametrize(
    "trascrizione,atteso",
    [
        ("lautaro", "Lautaro Martinez"),
        ("lautaro martinez", "Lautaro Martinez"),
        ("vlahovich", "Vlahovic"),        # storpiatura tipica dell'ASR
        ("kvaratskelia", "Kvaratskhelia"),
        ("di marco", "Dimarco"),
        ("calhanoglou", "Calhanoglu"),
        ("maignan", "Maignan"),
    ],
)
def test_trova_il_giocatore_anche_se_il_nome_arriva_storpiato(listone, trascrizione, atteso):
    risultati = listone.search(trascrizione)
    assert risultati, f"nessun risultato per '{trascrizione}'"
    assert risultati[0][0].name == atteso


def test_la_ricerca_e_ordinata_per_somiglianza(listone):
    punteggi = [score for _, score in listone.search("lauta", limit=5)]
    assert punteggi == sorted(punteggi, reverse=True)


def test_nessun_risultato_per_una_parola_estranea(listone):
    assert listone.search("supercalifragilistico") == []


# ---------------------------------------------------------------- filtri

def test_filtro_per_ruolo(listone):
    assert all(p.role == "A" for p in listone.by_role("A"))
    assert len(listone.by_role("P")) == 4


def test_filtro_per_squadra(listone):
    inter = {p.name for p in listone.by_team("inter")}
    assert "Lautaro Martinez" in inter and "Barella" in inter


def test_i_migliori_per_valore(listone):
    top = listone.top("A", limit=3)
    assert top[0].name == "Lautaro Martinez"
    assert [p.fvm for p in top] == sorted([p.fvm for p in top], reverse=True)
