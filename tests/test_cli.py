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


def test_i_comandi_di_prova_esistono():
    parser = build_parser()
    args = parser.parse_args(["benchmark", "--mine", "a.wav", "--others", "b.wav"])
    assert callable(args.func)
    assert args.mine == ["a.wav"] and args.others == ["b.wav"]

    args = parser.parse_args(["record", "--out", "x.wav", "--seconds", "30"])
    assert args.out == "x.wav" and args.seconds == 30.0


def test_benchmark_esce_con_errore_se_un_estraneo_passa(monkeypatch, tmp_path, capsys):
    """Il codice d'uscita serve a poterlo mettere in uno script."""
    from conftest import FakeEmbedder, speech
    from jarvis.cli import cmd_benchmark
    from jarvis.config import load_config
    from jarvis.speaker import benchmark as bm
    from jarvis.speaker.profile import Cohort, VoiceProfile
    from jarvis.speaker.verifier import SpeakerVerifier, VerifierConfig

    embedder = FakeEmbedder()
    profile = VoiceProfile(name="io")
    for i in range(6):
        profile.add(embedder.embed(speech(0, 4.0 + i * 0.3)))

    # Soglia volutamente permissiva: passano tutti, quindi il verdetto e' negativo.
    verifier = SpeakerVerifier(
        embedder, profile,
        VerifierConfig(accept_threshold=-1.0, reject_margin=-1.0, near_field_enabled=False),
        Cohort(),
    )
    monkeypatch.setattr("jarvis.cli._build_verifier", lambda cfg, **kw: (embedder, verifier))
    monkeypatch.setattr(bm, "load_audio", lambda path, rate=16000: speech(int(str(path)[-5]), 20.0))

    class Args:
        mine = [str(tmp_path / "v_0.wav")]
        others = [str(tmp_path / "v_3.wav")]
        turn_seconds = 4.0
        json = False

    assert cmd_benchmark(Args(), load_config()) == 1
    assert "NON AFFIDABILE" in capsys.readouterr().out


def test_benchmark_esce_a_zero_se_nessun_estraneo_passa(monkeypatch, tmp_path, capsys):
    from conftest import FakeEmbedder, speech
    from jarvis.cli import cmd_benchmark
    from jarvis.config import load_config
    from jarvis.speaker import benchmark as bm
    from jarvis.speaker.profile import Cohort, VoiceProfile
    from jarvis.speaker.verifier import SpeakerVerifier, VerifierConfig

    embedder = FakeEmbedder()
    profile = VoiceProfile(name="io")
    for i in range(6):
        profile.add(embedder.embed(speech(0, 4.0 + i * 0.3)))

    verifier = SpeakerVerifier(
        embedder, profile,
        VerifierConfig(accept_threshold=0.62, near_field_enabled=False),
        Cohort(),
    )
    monkeypatch.setattr("jarvis.cli._build_verifier", lambda cfg, **kw: (embedder, verifier))
    monkeypatch.setattr(bm, "load_audio", lambda path, rate=16000: speech(int(str(path)[-5]), 20.0))

    class Args:
        mine = [str(tmp_path / "v_0.wav")]
        others = [str(tmp_path / "v_3.wav")]
        turn_seconds = 4.0
        json = False

    assert cmd_benchmark(Args(), load_config()) == 0
    assert "AFFIDABILE" in capsys.readouterr().out


def test_doctor_esiste_e_riporta_cosa_manca(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROFILE", str(tmp_path / "assente.npz"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "Controllo prerequisiti" in output
    assert "jarvis enroll" in output


def test_doctor_in_json(capsys, monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("JARVIS_PROFILE", str(tmp_path / "assente.npz"))
    main(["doctor", "--json"])
    dati = json.loads(capsys.readouterr().out)
    assert any(c["controllo"] == "Profilo vocale" and c["stato"] == "manca" for c in dati)


def test_serve_non_parte_senza_prerequisiti_e_spiega_tutto(capsys, monkeypatch, tmp_path):
    """Il problema che ha fatto nascere doctor: morire al primo errore."""
    monkeypatch.setenv("JARVIS_PROFILE", str(tmp_path / "assente.npz"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["serve"]) == 1
    errore = capsys.readouterr().err
    assert "Controllo prerequisiti" in errore
    assert "jarvis doctor" in errore
