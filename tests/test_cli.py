"""Test della riga di comando: solo i comandi che non richiedono microfono, rete o modelli."""

from __future__ import annotations

import pytest

from jarvis.cli import build_parser, main


def test_serve_un_comando():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_ogni_comando_ha_una_funzione():
    parser = build_parser()
    for comando in ("enroll", "cohort", "calibrate", "diag", "run", "chat",
                    "devices", "plan", "lineup"):
        args = parser.parse_args([comando] + (["--files", "x.wav"] if comando == "cohort" else [])
                                 + (["Tizio"] if comando == "lineup" else []))
        assert callable(args.func)


def test_piano_asta(capsys):
    assert main(["plan"]) == 0
    output = capsys.readouterr().out
    assert "Budget 500 crediti" in output
    assert "A:" in output


def test_piano_con_strategia(capsys):
    assert main(["plan", "--strategy", "modificatore"]) == 0
    assert "modificatore" in capsys.readouterr().out


def test_strategia_sconosciuta_esce_con_errore(capsys):
    assert main(["plan", "--strategy", "inventata"]) == 1
    assert "strategia sconosciuta" in capsys.readouterr().err


def test_formazione_da_riga_di_comando(capsys, monkeypatch):
    monkeypatch.setenv("JARVIS_LISTONE", "data/esempio_listone_PLACEHOLDER.csv")
    assert main([
        "lineup", "Maignan", "Bastoni", "Dimarco", "Bremer", "Barella",
        "Calhanoglu", "Pulisic", "Kvaratskhelia", "Lautaro Martinez",
        "Vlahovic", "Lookman",
    ]) == 0
    output = capsys.readouterr().out
    assert "Modulo" in output
    assert "Lautaro Martinez" in output


def test_formazione_in_json(capsys, monkeypatch):
    import json

    monkeypatch.setenv("JARVIS_LISTONE", "data/esempio_listone_PLACEHOLDER.csv")
    main(["lineup", "--json", "--module", "3-4-3", "Maignan", "Bastoni", "Dimarco",
          "Bremer", "Barella", "Calhanoglu", "Pulisic", "Kvaratskhelia",
          "Lautaro Martinez", "Vlahovic", "Lookman"])
    dati = json.loads(capsys.readouterr().out)
    assert dati["modulo"] == "3-4-3"
    assert len(dati["titolari"]) == 11


def test_formazione_senza_listone(capsys, monkeypatch):
    monkeypatch.setenv("JARVIS_LISTONE", "/percorso/inesistente.csv")
    assert main(["lineup", "Tizio"]) == 1
    assert "listone" in capsys.readouterr().err


def test_profilo_mancante_spiega_cosa_fare(capsys, monkeypatch, tmp_path):
    """Il primo errore che incontrera' chiunque: deve dire cosa fare."""
    monkeypatch.setenv("JARVIS_PROFILE", str(tmp_path / "assente.npz"))
    assert main(["calibrate"]) == 1
    assert "jarvis enroll" in capsys.readouterr().err
