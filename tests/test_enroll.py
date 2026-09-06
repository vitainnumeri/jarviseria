"""Test dell'arruolamento: qualita' del profilo e proposta delle soglie."""

from __future__ import annotations

import numpy as np

from conftest import SR, speech
from jarvis.speaker.enroll import (
    ENROLLMENT_PHRASES,
    _quality_warning,
    profile_consistency,
    suggest_threshold,
)
from jarvis.speaker.profile import Cohort, VoiceProfile


# ------------------------------------------------------- qualita' dell'audio

def test_audio_troppo_basso_segnalato():
    assert "troppo basso" in _quality_warning(np.full(SR, 1e-4, dtype=np.float32))


def test_audio_saturo_segnalato():
    avviso = _quality_warning(np.ones(SR, dtype=np.float32))
    assert avviso is not None and ("forte" in avviso or "satura" in avviso)


def test_audio_buono_non_da_avvisi():
    rng = np.random.default_rng(0)
    assert _quality_warning((rng.standard_normal(SR) * 0.15).astype(np.float32)) is None


def test_le_frasi_di_arruolamento_coprono_il_gergo():
    testo = " ".join(ENROLLMENT_PHRASES).lower()
    for termine in ("asta", "crediti", "rosa", "formazione", "rigorista"):
        assert termine in testo, f"manca '{termine}' fra le frasi di arruolamento"


# --------------------------------------------------------- coerenza profilo

def test_profilo_coerente_se_registrato_bene(embedder, owner_profile):
    """Frasi della stessa persona: coerenza alta."""
    assert profile_consistency(owner_profile) > 0.70


def test_profilo_incoerente_se_ha_letto_qualcun_altro(embedder):
    """Se in mezzo alle registrazioni finisce un'altra voce, la coerenza crolla."""
    misto = VoiceProfile()
    for persona in (0, 0, 0, 4, 5, 6):
        misto.add(embedder.embed(speech(persona, 4.0)))
    assert profile_consistency(misto) < profile_consistency_of_owner(embedder)


def profile_consistency_of_owner(embedder) -> float:
    pulito = VoiceProfile()
    for i in range(6):
        pulito.add(embedder.embed(speech(0, 4.0 + i * 0.3)))
    return profile_consistency(pulito)


def test_profilo_con_una_sola_impronta(embedder):
    solo = VoiceProfile()
    solo.add(embedder.embed(speech(0, 4.0)))
    assert profile_consistency(solo) == 1.0


# ------------------------------------------------------------- soglie

def test_senza_coorte_le_soglie_sono_prudenziali(owner_profile):
    suggerimento = suggest_threshold(owner_profile, Cohort())
    assert 0.4 <= suggerimento["accept_threshold"] <= 0.85
    assert suggerimento["continue_threshold"] < suggerimento["accept_threshold"]
    assert "nessuna coorte" in suggerimento["note"]


def test_con_una_coorte_la_soglia_separa_me_dagli_altri(embedder, owner_profile):
    coorte = Cohort()
    for persona in range(1, 7):
        coorte.add(embedder.embed(speech(persona, 3.0)))

    suggerimento = suggest_threshold(owner_profile, coorte)
    assert suggerimento["self_p10"] > suggerimento["impostor_p95"]
    assert suggerimento["impostor_p95"] < suggerimento["accept_threshold"] < suggerimento["self_p10"]
    assert "affidabile" in suggerimento["note"]


def test_la_soglia_avverte_se_le_distribuzioni_si_toccano(embedder):
    """Con un profilo fatto male nessuna soglia puo' separare: va detto."""
    scadente = VoiceProfile()
    for persona in (0, 1, 2, 3):
        scadente.add(embedder.embed(speech(persona, 3.0)))
    coorte = Cohort()
    for persona in (1, 2, 3):
        coorte.add(embedder.embed(speech(persona, 4.0)))

    assert "rifai l'arruolamento" in suggest_threshold(scadente, coorte)["note"]


# ---------------------------------------------------------------- coorte

def test_la_coorte_scarta_i_quasi_duplicati(embedder):
    coorte = Cohort()
    impronta = embedder.embed(speech(3, 3.0))
    assert coorte.add(impronta)
    assert not coorte.add(impronta)      # identica: non porta informazione
    assert coorte.size == 1


def test_la_coorte_ha_un_tetto(embedder):
    coorte = Cohort(max_size=5)
    for i in range(20):
        coorte.add(embedder.embed(speech(i % 8, 2.0 + i * 0.1)))
    assert coorte.size <= 5


def test_la_coorte_si_salva_e_ricarica(tmp_path, embedder):
    coorte = Cohort()
    for persona in range(1, 5):
        coorte.add(embedder.embed(speech(persona, 3.0)))
    path = coorte.save(tmp_path / "cohort.npz")
    assert Cohort.load(path).size == coorte.size


def test_coorte_assente_non_e_un_errore(tmp_path):
    assert Cohort.load(tmp_path / "mai_creata.npz").size == 0


def test_adattamento_lento_non_stravolge_il_profilo(embedder, owner_profile):
    """L'adattamento deve seguire il microfono, non spostarmi su un'altra persona."""
    centroide_prima = owner_profile.centroid.copy()
    owner_profile.adapt(embedder.embed(speech(0, 3.0)), rate=0.05)
    assert float(np.dot(centroide_prima, owner_profile.centroid)) > 0.98
