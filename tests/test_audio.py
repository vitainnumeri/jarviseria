"""Test dello strato audio: livelli, rumore, eco, segmentazione dei turni."""

from __future__ import annotations

import numpy as np
import pytest

from jarvis.audio.dsp import (
    NoiseFloor,
    dbfs,
    frame_signal,
    normalized_xcorr,
    resample_linear,
    rms,
    to_float32,
    to_int16,
)
from jarvis.audio.playback import NullSpeaker
from jarvis.audio.vad import EnergyVAD, TurnSegmenter, TurnState
from jarvis.config import Config, deep_merge, load_config
from jarvis.tts import stream_sentences

SR = 16000


def rumore(seconds: float = 1.0, level: float = 0.1, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(seconds * SR)) * level).astype(np.float32)


# --------------------------------------------------------------------- DSP

def test_conversione_int16_e_ritorno():
    originale = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    assert np.allclose(to_float32(to_int16(originale)), originale, atol=1e-4)


def test_il_clipping_e_gestito():
    assert np.max(to_int16(np.array([5.0], dtype=np.float32))) == 32767


def test_silenzio_e_molto_sotto_il_parlato():
    assert dbfs(np.zeros(1000, dtype=np.float32)) < -90
    assert dbfs(rumore(level=0.2)) > -20
    assert rms(np.zeros(0, dtype=np.float32)) == 0.0


def test_il_rumore_di_fondo_sale_piano_e_scende_in_fretta():
    """Una risata improvvisa non deve alzare la stima per sempre."""
    noise = NoiseFloor(initial_db=-60.0)
    for _ in range(30):
        noise.update(rumore(0.02, level=0.05))
    dopo_brusio = noise.value_db
    assert dopo_brusio > -60

    for _ in range(30):
        noise.update(np.full(320, 1e-5, dtype=np.float32))
    assert noise.value_db < dopo_brusio


def test_il_campo_vicino_distingue_la_distanza():
    noise = NoiseFloor(initial_db=-45.0)
    assert noise.is_near_field(rumore(0.1, level=0.3), margin_db=8.0)
    assert not noise.is_near_field(rumore(0.1, level=0.001), margin_db=8.0)


def test_la_correlazione_riconosce_l_eco():
    """Un segnale correlato col riprodotto e' eco; uno indipendente no."""
    riprodotto = rumore(0.5, seed=1)
    assert normalized_xcorr(riprodotto * 0.6, riprodotto, 200) > 0.8
    assert normalized_xcorr(rumore(0.5, seed=2), riprodotto, 200) < 0.3


def test_correlazione_su_segnali_troppo_corti():
    assert normalized_xcorr(np.zeros(10), np.zeros(10), 5) == 0.0


def test_ricampionamento():
    assert resample_linear(rumore(1.0), SR, 8000).size == 8000
    identico = rumore(0.1)
    assert np.array_equal(resample_linear(identico, SR, SR), identico)


def test_finestramento():
    finestre = frame_signal(np.zeros(SR * 3), SR, SR // 2)
    assert len(finestre) == 5
    assert all(f.size == SR for f in finestre)


# --------------------------------------------------------------------- VAD

def test_il_vad_a_energia_distingue_voce_e_silenzio():
    vad = EnergyVAD()
    for _ in range(30):
        vad.is_speech(np.full(320, 1e-4, dtype=np.float32))   # assesta il fondo
    assert vad.is_speech(rumore(0.02, level=0.3))
    assert not vad.is_speech(np.full(320, 1e-4, dtype=np.float32))


# -------------------------------------------------------- segmentazione

@pytest.fixture
def segmenter() -> TurnSegmenter:
    return TurnSegmenter(sample_rate=SR, frame_ms=20, min_speech_ms=100,
                         min_silence_ms=200, pre_roll_ms=100)


def test_il_turno_si_chiude_dopo_il_silenzio(segmenter):
    frame = np.zeros(320, dtype=np.float32)
    segmento = None
    for _ in range(30):
        segmento = segmenter.push(frame, True) or segmento
    assert segmento is None and segmenter.state is TurnState.SPEAKING
    for _ in range(15):
        segmento = segmenter.push(frame, False) or segmento
    assert segmento is not None
    assert segmenter.state is TurnState.SILENCE


def test_il_pre_roll_salva_la_prima_sillaba(segmenter):
    """Senza pre-roll l'attacco della parola andrebbe perso."""
    frame = np.zeros(320, dtype=np.float32)
    for _ in range(10):
        segmenter.push(frame, False)     # riempio il pre-roll
    for _ in range(10):
        segmenter.push(frame, True)
    for _ in range(15):
        segmento = segmenter.push(frame, False)
        if segmento:
            break
    # 10 frame di parlato + il pre-roll conservato + la coda di silenzio.
    assert segmento.duration > 10 * 0.02


def test_un_rumore_isolato_non_apre_un_turno(segmenter):
    frame = np.zeros(320, dtype=np.float32)
    segmenter.push(frame, True)          # un solo frame: sotto min_speech_ms
    for _ in range(20):
        assert segmenter.push(frame, False) is None
    assert segmenter.state is TurnState.SILENCE


def test_taglio_di_sicurezza_sui_monologhi():
    segmenter = TurnSegmenter(sample_rate=SR, frame_ms=20, min_speech_ms=40, max_utterance_s=1.0)
    frame = np.zeros(320, dtype=np.float32)
    segmento = None
    for _ in range(200):
        segmento = segmenter.push(frame, True) or segmento
        if segmento:
            break
    assert segmento is not None and segmento.truncated


def test_abort_svuota_il_turno(segmenter):
    frame = np.zeros(320, dtype=np.float32)
    for _ in range(20):
        segmenter.push(frame, True)
    segmenter.abort()
    assert segmenter.state is TurnState.SILENCE
    assert segmenter.active_audio.size == 0


# ---------------------------------------------------------------- playback

def test_lo_stop_interrompe_la_riproduzione():
    speaker = NullSpeaker()
    assert speaker.play(np.zeros(1000, dtype=np.float32))
    speaker.stop()
    assert not speaker.play(np.zeros(1000, dtype=np.float32))


def test_il_segnale_di_riferimento_serve_all_anti_eco():
    speaker = NullSpeaker()
    speaker.play(np.full(500, 0.3, dtype=np.float32))
    assert speaker.reference_signal(500).size > 0


def test_il_ducking_abbassa_il_guadagno():
    speaker = NullSpeaker()
    speaker.duck(-12.0)
    assert speaker._gain == pytest.approx(0.251, abs=0.01)
    speaker.unduck()
    assert speaker._gain == 1.0


# ------------------------------------------------------- frasi per la voce

def test_le_frasi_escono_una_alla_volta():
    frasi = list(stream_sentences(["Direi Lautaro. ", "Il tetto e' 180 crediti, non oltre."]))
    assert len(frasi) == 2
    assert frasi[0] == "Direi Lautaro."


def test_le_frasi_corte_si_uniscono_alla_successiva():
    """"Sì." da sola suonerebbe spezzata."""
    frasi = list(stream_sentences(["Si'. ", "Puoi arrivare a centottanta crediti tranquillamente."]))
    assert len(frasi) == 1


def test_il_testo_finale_senza_punteggiatura_esce_comunque():
    assert list(stream_sentences(["risposta senza punto finale"])) == ["risposta senza punto finale"]


# ------------------------------------------------------------ configurazione

def test_la_configurazione_di_default_si_carica():
    cfg = load_config()
    assert cfg.get("speaker.accept_threshold") == 0.62
    assert cfg.get("fanta.slots.A") == 6


def test_accesso_puntato_e_default():
    cfg = Config({"a": {"b": 1}})
    assert cfg.get("a.b") == 1
    assert cfg.get("a.c", "default") == "default"
    assert cfg.get("x.y.z") is None


def test_merge_ricorsivo_senza_mutare_gli_originali():
    base = {"a": {"b": 1, "c": 2}}
    merged = deep_merge(base, {"a": {"c": 99}})
    assert merged == {"a": {"b": 1, "c": 99}}
    assert base["a"]["c"] == 2


def test_i_percorsi_si_risolvono_dalla_radice_del_progetto():
    cfg = load_config()
    assert cfg.resolve_path("speaker.profile_path").is_absolute()
