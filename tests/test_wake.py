"""Test della parola di attivazione (usata solo negli ambienti estremi)."""

from __future__ import annotations

import pytest

from conftest import speech
from jarvis.session.wake import WakeWordGate
from test_session import build_session, feed


# ------------------------------------------------------------ disattivata

def test_disattivata_lascia_passare_tutto():
    gate = WakeWordGate(enabled=False)
    passa, testo = gate.check("quanto offro per Lautaro?")
    assert passa and testo == "quanto offro per Lautaro?"


# --------------------------------------------------------------- attivata

@pytest.fixture
def gate() -> WakeWordGate:
    return WakeWordGate(enabled=True, phrases=["jarvis", "ehi jarvis"], timeout_s=30.0)


def test_senza_parola_chiave_il_turno_non_passa(gate):
    passa, _ = gate.check("quanto offro per Lautaro?")
    assert not passa


def test_con_la_parola_chiave_passa_e_viene_tolta(gate):
    passa, testo = gate.check("Jarvis, quanto offro per Lautaro?")
    assert passa
    assert "jarvis" not in testo.lower()
    assert testo == "quanto offro per Lautaro?"


def test_la_frase_piu_lunga_ha_la_precedenza(gate):
    """"ehi jarvis" deve essere tolta per intero, non solo "jarvis"."""
    passa, testo = gate.check("Ehi Jarvis dimmi la formazione")
    assert passa and testo == "dimmi la formazione"


def test_la_parola_chiave_a_meta_frase_vale(gate):
    passa, testo = gate.check("senti jarvis dimmi una cosa")
    assert passa and testo == "senti jarvis dimmi una cosa"


def test_accenti_e_punteggiatura_non_bloccano(gate):
    assert gate.check("JARVIS! quanto costa?")[0]


def test_dopo_l_attivazione_la_conversazione_prosegue_libera(gate):
    """Non si deve ripetere la parola chiave a ogni frase."""
    assert gate.check("jarvis, quanto offro?")[0]
    assert gate.check("e per il secondo attaccante?")[0]
    assert gate.check("e in difesa?")[0]


def test_la_finestra_si_chiude_dopo_il_timeout():
    gate = WakeWordGate(enabled=True, phrases=["jarvis"], timeout_s=0.0)
    assert gate.check("jarvis dimmi")[0]
    assert not gate.check("e adesso?")[0]


def test_chiusura_manuale(gate):
    gate.check("jarvis dimmi")
    gate.close()
    assert not gate.check("e adesso?")[0]


def test_solo_la_parola_chiave_non_svuota_il_testo(gate):
    """"Jarvis" da solo: meglio inoltrarlo che mandare una stringa vuota."""
    passa, testo = gate.check("Jarvis")
    assert passa and testo.strip() != ""


# ------------------------------------------------- integrazione di sessione

def test_in_sessione_la_mia_voce_senza_parola_chiave_viene_ignorata(verifier):
    from test_session import FakeTranscriber

    session = build_session(
        verifier,
        transcriber=FakeTranscriber("quanto offro per Lautaro"),
        cfg_overrides={"speaker": {"wake_word": {"enabled": True, "phrases": ["jarvis"]}}},
    )
    feed(session, speech(0, 3.0))

    assert session.stats.turni_miei == 0
    assert session.stats.turni_senza_attivazione == 1
    assert session.agent.asked == []


def test_in_sessione_con_parola_chiave_risponde(verifier):
    from test_session import FakeTranscriber

    session = build_session(
        verifier,
        transcriber=FakeTranscriber("jarvis quanto offro per Lautaro"),
        cfg_overrides={"speaker": {"wake_word": {"enabled": True, "phrases": ["jarvis"]}}},
    )
    feed(session, speech(0, 3.0))

    assert session.stats.turni_miei == 1
    assert session.agent.asked == ["quanto offro per Lautaro"]
