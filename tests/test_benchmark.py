"""Test della misura: e' lo strumento con cui si decide se fidarsi del sistema,
quindi deve essere lui per primo affidabile."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import SR, speech
from jarvis.speaker import benchmark as bm


# ------------------------------------------------------------------- EER

def test_distribuzioni_separate_hanno_eer_nullo():
    eer, soglia = bm.equal_error_rate([0.80, 0.78, 0.85], [0.10, 0.22, 0.05])
    assert eer == 0.0
    assert 0.22 < soglia <= 0.80


def test_distribuzioni_sovrapposte_hanno_eer_alto():
    eer, _ = bm.equal_error_rate([0.60, 0.55, 0.58], [0.59, 0.61, 0.56])
    assert eer > 0.3


def test_eer_senza_dati():
    assert bm.equal_error_rate([], [0.5]) == (0.0, 0.0)


# -------------------------------------------------------------- soglia

def test_la_soglia_suggerita_blocca_tutti_gli_estranei():
    mie, altri = [0.80, 0.78, 0.85, 0.72], [0.10, 0.22, 0.55, 0.31]
    soglia = bm.suggest_threshold(mie, altri)
    assert soglia > max(altri), "la soglia lascerebbe passare un estraneo"
    assert soglia < max(mie), "la soglia bloccherebbe anche me"


def test_la_soglia_non_scende_mai_sotto_il_miglior_estraneo():
    """Il bug da non rifare: proporre una soglia che un estraneo supera."""
    mie = [0.90, 0.45, 0.44, 0.43]     # la mia decima percentile e' bassa
    altri = [0.70, 0.68, 0.65]
    soglia = bm.suggest_threshold(mie, altri)
    assert soglia is not None and soglia > max(altri)


def test_nessuna_soglia_se_un_estraneo_fa_meglio_di_me():
    assert bm.suggest_threshold([0.60, 0.55], [0.71, 0.68]) is None


def test_nessuna_soglia_senza_dati():
    assert bm.suggest_threshold([], []) is None


# ------------------------------------------------------------- verdetto

def make_outcome(label, turni, accettati, punteggi):
    return bm.Outcome(label=label, turni_totali=turni, turni_accettati=accettati, punteggi=punteggi)


def test_verdetto_affidabile():
    result = bm.evaluate(
        make_outcome("io", 20, 20, [0.80] * 20),
        make_outcome("altri", 20, 0, [0.15] * 20),
    )
    assert result.far == 0.0
    assert result.frr == 0.0
    assert "AFFIDABILE" in result.verdict


def test_verdetto_buono_se_ogni_tanto_devo_ripetere():
    result = bm.evaluate(
        make_outcome("io", 20, 18, [0.75] * 18 + [0.40] * 2),
        make_outcome("altri", 20, 0, [0.15] * 20),
    )
    assert result.far == 0.0
    assert "BUONO" in result.verdict
    assert any("abbassa accept_threshold" in a for a in result.advice)


def test_verdetto_non_affidabile_se_passano_estranei():
    result = bm.evaluate(
        make_outcome("io", 20, 20, [0.70] * 20),
        make_outcome("altri", 20, 6, [0.65] * 20),
    )
    assert result.far > 0.2
    assert "NON AFFIDABILE" in result.verdict
    assert any("auricolare" in a for a in result.advice), "manca il consiglio che conta di piu'"


def test_un_solo_falso_accesso_toglie_l_affidabilita():
    """I due errori non pesano uguale: un estraneo che passa e' grave."""
    perfetto = bm.evaluate(
        make_outcome("io", 100, 100, [0.80] * 100),
        make_outcome("altri", 100, 0, [0.15] * 100),
    )
    con_un_errore = bm.evaluate(
        make_outcome("io", 100, 100, [0.80] * 100),
        make_outcome("altri", 100, 1, [0.15] * 100),
    )
    assert "AFFIDABILE" in perfetto.verdict
    assert "AFFIDABILE" not in con_un_errore.verdict


def test_avverte_se_le_distribuzioni_sono_vicine():
    result = bm.evaluate(
        make_outcome("io", 20, 20, [0.62] * 20),
        make_outcome("altri", 20, 0, [0.58] * 20),
    )
    assert result.separation < 0.15
    assert any("distribuzioni sono vicine" in a for a in result.advice)


def test_il_rapporto_contiene_i_numeri_che_contano():
    result = bm.evaluate(
        make_outcome("io", 20, 19, [0.78] * 20),
        make_outcome("altri", 20, 0, [0.20] * 20),
    )
    testo = bm.format_report(result)
    assert "Falsi accessi" in testo and "Falsi rifiuti" in testo
    assert "accept_threshold" in testo
    assert "coorte" in testo, "manca l'avvertenza sulla contaminazione della prova"


# --------------------------------------------------------------- turni

def test_le_registrazioni_si_spezzano_in_turni():
    turni = bm.split_turns(speech(0, 20.0), SR, turn_seconds=4.0)
    assert len(turni) == 5
    assert all(t.size == 4 * SR for t in turni)


def test_le_pause_non_contano_come_turni():
    audio = np.concatenate([speech(0, 4.0), np.zeros(4 * SR, dtype=np.float32), speech(0, 4.0)])
    assert len(bm.split_turns(audio, SR, turn_seconds=4.0)) == 2


def test_una_coda_troppo_corta_viene_scartata():
    assert len(bm.split_turns(speech(0, 4.5), SR, turn_seconds=4.0)) == 1


# --------------------------------------------------- misura end-to-end

@pytest.fixture
def registrazioni(monkeypatch, tmp_path):
    """Finti file audio: il nome dice quale persona parla."""
    def fake_load(path, target_rate=SR):
        persona = int(str(path).rsplit("_", 1)[-1].split(".")[0])
        return speech(persona, 20.0)

    monkeypatch.setattr(bm, "load_audio", fake_load)
    return lambda persona: tmp_path / f"voce_{persona}.wav"


def test_misura_completa_su_un_profilo_buono(verifier, registrazioni):
    result = bm.run_benchmark(
        verifier,
        [registrazioni(0)],
        [registrazioni(1), registrazioni(2), registrazioni(3)],
    )
    assert result.far == 0.0, "un estraneo e' passato"
    assert result.frr == 0.0, "non ha riconosciuto il proprietario"
    assert "AFFIDABILE" in result.verdict
    assert result.separation > 0.15


def test_la_misura_non_impara_dalle_registrazioni_che_valuta(verifier, registrazioni):
    """Se imparasse dalle voci sotto esame, si giudicherebbe da sola."""
    coorte_prima = verifier.cohort.size
    bm.run_benchmark(verifier, [registrazioni(0)], [registrazioni(1), registrazioni(2)])
    assert verifier.cohort.size == coorte_prima


def test_la_misura_non_altera_il_profilo(verifier, registrazioni):
    centroide = verifier.profile.centroid.copy()
    bm.run_benchmark(verifier, [registrazioni(0)], [registrazioni(4)])
    assert np.allclose(centroide, verifier.profile.centroid)


def test_senza_mie_registrazioni_l_errore_e_chiaro(verifier, registrazioni, monkeypatch):
    monkeypatch.setattr(bm, "load_audio", lambda p, r=SR: np.zeros(SR * 8, dtype=np.float32))
    with pytest.raises(ValueError, match="tue registrazioni"):
        bm.run_benchmark(verifier, [registrazioni(0)], [registrazioni(1)])


def test_la_soglia_consigliata_non_scende_sotto_un_minimo_prudenziale():
    """Le voci di prova sono poche; quelle che entreranno nella stanza no.

    Una soglia cucita su quattro estranei noti non protegge dal quinto.
    """
    soglia = bm.suggest_threshold([0.90, 0.85, 0.88], [0.01, 0.02, 0.03])
    assert soglia >= bm.SOGLIA_MINIMA_CONSIGLIATA
