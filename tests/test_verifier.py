"""Test del portiere biometrico.

Le voci sintetiche e l'embedder controllato vivono in conftest.py: qui si
collauda solo la *logica* di decisione.
"""

from __future__ import annotations

import numpy as np
import pytest

from jarvis.speaker.embedder import EMBEDDING_DIM, l2_normalize
from jarvis.speaker.profile import Cohort, VoiceProfile
from jarvis.speaker.verifier import Decision, SpeakerVerifier, VerifierConfig

from conftest import SR, speech


# ------------------------------------------------------------------ base

def test_riconosce_il_proprietario(verifier):
    result = verifier.verify(speech(0, 3.0))
    assert result.decision is Decision.OWNER
    assert result.score > 0.62
    assert result.accepted_ratio == pytest.approx(1.0)


@pytest.mark.parametrize("stranger", [1, 2, 3, 4, 5, 6, 7])
def test_ignora_ogni_estraneo(verifier, stranger):
    result = verifier.verify(speech(stranger, 3.0))
    assert result.decision is Decision.STRANGER, f"persona {stranger} accettata per errore"


def test_segmento_troppo_breve_e_incerto(verifier):
    result = verifier.verify(speech(0, 0.2))
    assert result.decision is Decision.UNCERTAIN
    assert "breve" in result.reason


# ------------------------------------- la stanza affollata: il caso critico

def test_stanza_affollata_solo_il_proprietario_passa(verifier):
    """Sette estranei parlano a turno, io parlo una volta: passa solo il mio turno."""
    accepted = [p for p in range(8) if verifier.verify(speech(p, 3.0)).is_owner]
    assert accepted == [0]


def test_coorte_impara_gli_estranei_da_sola(verifier):
    """Le voci rifiutate entrano in coorte: il sistema impara chi c'e' nella stanza."""
    assert verifier.cohort.size == 0
    for stranger in range(1, 6):
        verifier.verify(speech(stranger, 3.0))
    assert verifier.cohort.size >= 4


def test_il_margine_di_coorte_blocca_una_voce_somigliante(embedder, owner_profile):
    """Una voce vicina alla mia viene respinta se lo e' altrettanto a un estraneo noto.

    E' la regola che conta in mezzo alla gente: non basta somigliarmi, devo
    somigliarmi *piu' di chiunque altro presente*.
    """
    cfg = VerifierConfig(accept_threshold=0.30, reject_margin=0.25, near_field_enabled=False)
    verifier = SpeakerVerifier(embedder, owner_profile, cfg, Cohort())

    ambigua = l2_normalize(0.5 * embedder.people[0] + 0.5 * embedder.people[3])
    verifier.cohort.add(embedder.people[3])

    class Fisso:
        dim = EMBEDDING_DIM

        def embed(self, audio, sample_rate=SR):
            return ambigua

    verifier.embedder = Fisso()
    assert verifier.verify(speech(3, 3.0)).decision is Decision.STRANGER


# ------------------------------------------------ campo vicino e isteresi

def test_voce_lontana_scartata_dal_filtro_di_campo_vicino(embedder, owner_profile):
    """La mia stessa voce, ma da lontano (livello basso), non apre un turno."""
    cfg = VerifierConfig(near_field_enabled=True, near_field_margin_db=8.0)
    verifier = SpeakerVerifier(embedder, owner_profile, cfg, Cohort())
    for _ in range(50):  # il rumore di fondo della stanza si assesta
        verifier.observe_noise(speech(6, 0.1, level=0.02))

    assert verifier.verify(speech(0, 3.0, level=0.25)).is_owner          # vicino: ok
    assert not verifier.verify(speech(0, 3.0, level=0.004)).is_owner     # lontano: no


def test_isteresi_abbassa_la_soglia_a_turno_aperto(verifier):
    assert verifier._threshold() == pytest.approx(0.62)
    verifier._locked = True
    assert verifier._threshold() == pytest.approx(0.50)
    verifier.reset_turn()
    assert verifier._threshold() == pytest.approx(0.62)


def test_rifiuto_precoce_di_un_estraneo(verifier):
    """Tre finestre fallite bastano a chiudere il turno senza trascriverlo."""
    scores = [verifier.score_window(w, i) for i, w in enumerate(verifier._windows(speech(2, 3.0)))]
    assert verifier.stream_decision(scores[:3]) is Decision.STRANGER


def test_decisione_incrementale_aggancia_il_proprietario(verifier):
    scores = [verifier.score_window(w, i) for i, w in enumerate(verifier._windows(speech(0, 3.0)))]
    assert verifier.stream_decision(scores[:2]) is Decision.OWNER
    assert verifier.locked


# ------------------------------------------------------- sovrapposizione

def test_rileva_sovrapposizione_e_taglia_i_bordi(verifier):
    """Un estraneo finisce la frase mentre comincio io: il bordo viene tagliato."""
    audio = np.concatenate([speech(4, 1.2), speech(0, 4.0)])
    result = verifier.verify(audio)
    assert result.is_owner
    assert result.overlap_detected
    assert result.trimmed_audio is not None
    assert result.trimmed_audio.size < audio.size


# ------------------------------------------------------------ adattamento

def test_adattamento_solo_su_turni_certi(embedder, owner_profile):
    cfg = VerifierConfig(
        adaptation_enabled=True, adaptation_min_score=0.99, near_field_enabled=False
    )
    verifier = SpeakerVerifier(embedder, owner_profile, cfg, Cohort())
    before = verifier.profile.embeddings.shape[0]
    verifier.verify(speech(0, 3.0))
    assert verifier.profile.embeddings.shape[0] == before  # soglia irraggiungibile: niente deriva


def test_profilo_si_salva_e_ricarica(tmp_path, owner_profile):
    path = tmp_path / "owner.npz"
    owner_profile.save(path)
    loaded = VoiceProfile.load(path)
    assert loaded.name == "david"
    assert np.allclose(loaded.centroid, owner_profile.centroid)


def test_errore_chiaro_se_il_profilo_non_esiste(tmp_path):
    with pytest.raises(FileNotFoundError, match="jarvis enroll"):
        VoiceProfile.load(tmp_path / "assente.npz")


def test_un_mio_turno_rifiutato_per_un_soffio_non_finisce_fra_gli_estranei(embedder, owner_profile):
    """La deriva silenziosa: se i miei turni borderline entrano in coorte, il
    margine comincia a lavorarmi contro e il sistema smette di riconoscermi.

    Trovato misurando la versione per telefono, dove costava meta' dei falsi
    rifiuti; qui la logica e' identica, quindi il difetto c'era uguale.
    """
    cfg = VerifierConfig(accept_threshold=0.95, near_field_enabled=False)  # soglia irreale
    verifier = SpeakerVerifier(embedder, owner_profile, cfg, Cohort())

    risultato = verifier.verify(speech(0, 3.0))          # sono io, ma vengo respinto
    assert not risultato.is_owner
    assert verifier.cohort.size == 0, "la mia voce e' finita fra gli estranei"


def test_una_voce_davvero_estranea_entra_in_coorte(embedder, owner_profile):
    cfg = VerifierConfig(accept_threshold=0.62, near_field_enabled=False)
    verifier = SpeakerVerifier(embedder, owner_profile, cfg, Cohort())
    verifier.verify(speech(4, 3.0))
    assert verifier.cohort.size == 1
