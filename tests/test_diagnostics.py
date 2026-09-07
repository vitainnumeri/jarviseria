"""Test del controllo prerequisiti.

Serve a chi e' bloccato, quindi la cosa da collaudare non e' solo "rileva cio'
che manca" ma "dice quanti passi mancano e non li duplica".
"""

from __future__ import annotations

import pytest

from jarvis import diagnostics as dg
from jarvis.config import Config


def manca(nome: str, rimedio: str, bloccante: bool = True) -> dg.Check:
    return dg.Check(nome, dg.MANCA, "non installato", rimedio, bloccante=bloccante)


@pytest.fixture
def cfg() -> Config:
    return Config({
        "speaker": {"profile_path": "profiles/owner.npz"},
        "tts": {"provider": "piper", "voice": "it_IT-test", "model_dir": "models/piper"},
        "fanta": {"listone_path": None},
    })


# ------------------------------------------------------------ singoli check

def test_python_attuale_va_bene():
    assert dg.check_python().stato == dg.OK


def test_dipendenza_presente_e_assente():
    assert dg.check_dipendenza("numpy", "numpy", "audio").stato == dg.OK
    assente = dg.check_dipendenza("Fantasia", "modulo_inesistente_xyz", "audio")
    assert assente.stato == dg.MANCA
    assert 'pip install -e ".[audio]"' == assente.rimedio


def test_chiave_api(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert dg.check_chiave_api().stato == dg.MANCA
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    assert dg.check_chiave_api().stato == dg.OK


def test_profilo_mancante_indica_enroll(tmp_path):
    check = dg.check_profilo(tmp_path / "assente.npz")
    assert check.stato == dg.MANCA
    assert "jarvis enroll" in check.rimedio


def test_profilo_troppo_corto_e_solo_un_avviso(tmp_path, embedder):
    """Un profilo scarso funziona male, ma non impedisce di partire."""
    from conftest import speech
    from jarvis.speaker.profile import VoiceProfile

    profilo = VoiceProfile()
    profilo.add(embedder.embed(speech(0, 3.0)), seconds=3.0)
    profilo.save(tmp_path / "owner.npz")

    check = dg.check_profilo(tmp_path / "owner.npz")
    assert check.stato == dg.AVVISO
    assert not check.bloccante


def test_profilo_buono(tmp_path, owner_profile):
    owner_profile.sample_seconds = 40.0
    owner_profile.save(tmp_path / "owner.npz")
    assert dg.check_profilo(tmp_path / "owner.npz").stato == dg.OK


def test_il_listone_non_blocca_mai():
    check = dg.check_listone(None)
    assert check.stato == dg.AVVISO
    assert not check.bloccante


def test_la_porta_occupata_viene_rilevata():
    import socket

    presa = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    presa.bind(("127.0.0.1", 0))
    presa.listen(1)
    porta = presa.getsockname()[1]
    try:
        check = dg.check_porta(porta)
        assert check.stato == dg.MANCA
        assert f"--port {porta + 1}" in check.rimedio
    finally:
        presa.close()


def test_una_porta_libera_va_bene():
    assert dg.check_porta(0).stato == dg.OK


def test_la_rete_suggerisce_l_indirizzo_per_il_telefono():
    check = dg.check_rete(8765)
    assert ":8765" in check.dettaglio


def test_la_voce_cloud_controlla_la_chiave(monkeypatch):
    cfg = Config({"tts": {"provider": "elevenlabs"}})
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert dg.check_voce_sintetica(cfg).stato == dg.MANCA
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xxx")
    assert dg.check_voce_sintetica(cfg).stato == dg.OK


# ------------------------------------------------------------- i passi

def test_quattro_pacchetti_mancanti_sono_un_comando_solo():
    """Elencarli separatamente farebbe installare tre volte la stessa cosa."""
    bloccanti = [
        manca("speechbrain", 'pip install -e ".[audio]"'),
        manca("silero", 'pip install -e ".[audio]"'),
        manca("whisper", 'pip install -e ".[asr-local]"'),
        manca("anthropic", 'pip install -e ".[llm]"'),
    ]
    passi = dg._passi(bloccanti)
    assert len(passi) == 1
    assert passi[0][0] == 'pip install -e ".[audio,asr-local,llm]"'


def test_i_pacchetti_vengono_prima_di_tutto():
    """Senza librerie gli altri passi non si possono nemmeno eseguire."""
    bloccanti = [
        manca("Profilo", "jarvis enroll"),
        manca("speechbrain", 'pip install -e ".[audio]"'),
    ]
    assert dg._passi(bloccanti)[0][0].startswith("pip install")


def test_rimedi_identici_non_si_ripetono():
    bloccanti = [manca("Uno", "jarvis enroll"), manca("Due", "jarvis enroll")]
    passi = dg._passi(bloccanti)
    assert len(passi) == 1
    assert passi[0][1] == ["Uno", "Due"]


def test_nessun_extra_duplicato():
    bloccanti = [
        manca("a", 'pip install -e ".[audio]"'),
        manca("b", 'pip install -e ".[audio]"'),
    ]
    assert dg._passi(bloccanti)[0][0] == 'pip install -e ".[audio]"'


# ------------------------------------------------------------- referto

def test_il_referto_elenca_i_passi(cfg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    checks = dg.run_checks(cfg, modalita="telefono")
    testo = dg.format_report(checks, "telefono")
    assert "Controllo prerequisiti" in testo
    assert "Ti mancano" in testo
    assert dg.exit_code(checks) == 1


def test_il_referto_non_ha_spazi_in_coda(cfg):
    for riga in dg.format_report(dg.run_checks(cfg, modalita="telefono"), "telefono").split("\n"):
        assert riga == riga.rstrip(), f"spazi in coda: {riga!r}"


def test_tutto_a_posto_invita_a_partire():
    checks = [dg.Check("Tutto", dg.OK)]
    assert "jarvis serve" in dg.format_report(checks, "telefono")
    assert dg.exit_code(checks) == 0


def test_solo_avvisi_non_bloccano():
    checks = [dg.Check("Listone", dg.AVVISO, "assente", "vedi README", bloccante=False)]
    assert dg.exit_code(checks) == 0
    assert "Non bloccanti" in dg.format_report(checks, "telefono")


def test_la_modalita_telefono_controlla_la_rete(cfg):
    nomi = [c.nome for c in dg.run_checks(cfg, modalita="telefono")]
    assert "Rete locale" in nomi and "openssl" in nomi
    assert "Microfono" not in nomi


def test_la_modalita_pc_controlla_il_microfono(cfg):
    nomi = [c.nome for c in dg.run_checks(cfg, modalita="pc")]
    assert "Microfono" in nomi
    assert "Rete locale" not in nomi
