"""Arruolamento: insegnare al sistema com'e' fatta la mia voce.

Qualita' dell'arruolamento = qualita' di tutto il resto. Le frasi proposte sono
foneticamente varie e includono il lessico del fantacalcio, perche' l'impronta
regge meglio sul vocabolario che userò davvero.

Consiglio importante: arruola con LO STESSO microfono e nella STESSA posizione
d'uso. Un profilo fatto col portatile sul tavolo non funziona bene con
l'auricolare, e viceversa.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..audio.dsp import dbfs, to_float32
from ..utils.logging import get_logger
from .profile import Cohort, VoiceProfile

log = get_logger(__name__)

# Frasi di arruolamento: foneticamente varie + gergo d'asta.
ENROLLMENT_PHRASES = [
    "Ciao, sono io. Questa e' la mia voce e voglio che tu riconosca solo me.",
    "Quest'anno all'asta punto forte sul centrocampo e tengo crediti per il finale.",
    "Quanto vale questo attaccante secondo le quotazioni e qual e' il prezzo massimo?",
    "Schiera il tre cinque due con il portiere titolare e i due difensori della stessa squadra.",
    "Trentatre trentini entrarono a Trento tutti e trentatre trotterellando.",
    "Se il rigorista e' diffidato, preferisco la punta che gioca in casa contro l'ultima in classifica.",
    "Aggiudicato a centoventi crediti: aggiorna la rosa e ricalcola quello che mi resta.",
    "Dimmi la probabile formazione, chi e' infortunato e chi rientra dalla squalifica.",
]

MIN_RECOMMENDED_SECONDS = 25.0


def _record(seconds: float, sample_rate: int, device=None) -> np.ndarray:  # pragma: no cover - I/O
    """Registra `seconds` secondi dal microfono."""
    import sounddevice as sd

    audio = sd.rec(
        int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="float32", device=device
    )
    sd.wait()
    return to_float32(np.asarray(audio)).ravel()


def _quality_warning(audio: np.ndarray) -> str | None:
    """Controlli elementari ma decisivi sulla registrazione."""
    level = dbfs(audio)
    if level < -45.0:
        return "audio troppo basso: avvicina il microfono o alza il guadagno d'ingresso"
    if level > -6.0:
        return "audio troppo forte, rischio di distorsione: allontanati un po'"
    if float(np.max(np.abs(audio))) >= 0.999:
        return "il segnale satura (clipping): abbassa il guadagno d'ingresso"
    return None


def enroll_interactive(
    embedder,
    profile_path: str | Path,
    *,
    sample_rate: int = 16000,
    phrase_seconds: float = 5.0,
    phrases: list[str] | None = None,
    device=None,
    name: str = "owner",
) -> VoiceProfile:  # pragma: no cover - richiede microfono
    """Arruolamento guidato del proprietario."""
    phrases = phrases or ENROLLMENT_PHRASES
    profile = VoiceProfile(name=name)

    print("\n=== Arruolamento della tua voce ===")
    print("Leggi ogni frase con voce naturale, come parlerai al bot.")
    print("Usa lo stesso microfono e la stessa distanza che userai davvero.\n")

    for i, phrase in enumerate(phrases, start=1):
        input(f"[{i}/{len(phrases)}] Premi INVIO e leggi:\n    «{phrase}»\n> ")
        print(f"    registro {phrase_seconds:.0f}s...", flush=True)
        audio = _record(phrase_seconds, sample_rate, device)

        warning = _quality_warning(audio)
        if warning:
            print(f"    ATTENZIONE: {warning}. Ripeto questa frase.")
            audio = _record(phrase_seconds, sample_rate, device)

        profile.add(embedder.embed(audio, sample_rate), seconds=phrase_seconds)
        print(f"    ok ({profile.sample_seconds:.0f}s totali)\n")

    if profile.sample_seconds < MIN_RECOMMENDED_SECONDS:
        print(
            f"Nota: solo {profile.sample_seconds:.0f}s di voce. "
            f"Sotto i {MIN_RECOMMENDED_SECONDS:.0f}s il riconoscimento e' meno affidabile."
        )

    profile.meta["sample_rate"] = sample_rate
    profile.meta["consistency"] = round(profile_consistency(profile), 4)
    profile.save(profile_path)
    print(f"\nProfilo salvato in {profile_path}")
    print(f"Coerenza interna del profilo: {profile.meta['consistency']:.3f} (sopra 0.70 e' buono)")
    return profile


def enroll_from_files(
    embedder, audio_paths: list[str | Path], profile_path: str | Path, *, sample_rate: int = 16000
) -> VoiceProfile:
    """Arruolamento da file gia' registrati (WAV/FLAC mono)."""
    import soundfile as sf

    profile = VoiceProfile()
    for path in audio_paths:
        audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
        audio = to_float32(np.asarray(audio))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        # Spezzo i file lunghi: piu' impronte coprono meglio la variabilita'.
        chunk = int(5.0 * sr)
        for start in range(0, max(audio.size - chunk // 2, 1), chunk):
            piece = audio[start : start + chunk]
            if piece.size >= sr:
                profile.add(embedder.embed(piece, sr), seconds=piece.size / sr)
    if profile.is_empty:
        raise ValueError("nessun audio utilizzabile nei file forniti")
    profile.meta["sample_rate"] = sample_rate
    profile.meta["consistency"] = round(profile_consistency(profile), 4)
    profile.save(profile_path)
    return profile


def build_cohort_from_files(
    embedder, audio_paths: list[str | Path], cohort_path: str | Path, *, max_size: int = 300
) -> Cohort:
    """Costruisce la coorte da registrazioni di ALTRE persone.

    Non e' obbligatorio (la coorte si popola da sola durante l'uso), ma partire
    con le voci di chi sara' nella stanza rende il sistema severo fin dal primo
    minuto d'asta.
    """
    import soundfile as sf

    cohort = Cohort(max_size=max_size)
    for path in audio_paths:
        audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
        audio = to_float32(np.asarray(audio))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        chunk = int(3.0 * sr)
        for start in range(0, max(audio.size - chunk // 2, 1), chunk):
            piece = audio[start : start + chunk]
            if piece.size >= sr:
                cohort.add(embedder.embed(piece, sr))
    cohort.save(cohort_path)
    log.info("coorte salvata in %s (%d impronte)", cohort_path, cohort.size)
    return cohort


def profile_consistency(profile: VoiceProfile) -> float:
    """Somiglianza media fra le impronte di arruolamento.

    Valore basso = registrazioni disomogenee (rumore, microfoni diversi,
    qualcun altro che ha letto una frase). Sotto 0.55 conviene rifare tutto.
    """
    if profile.embeddings.shape[0] < 2:
        return 1.0
    sims = profile.embeddings @ profile.embeddings.T
    n = sims.shape[0]
    off_diagonal = (sims.sum() - np.trace(sims)) / (n * (n - 1))
    return float(off_diagonal)


def suggest_threshold(profile: VoiceProfile, cohort: Cohort, *, safety: float = 0.05) -> dict:
    """Propone le soglie a partire dai dati realmente arruolati.

    Idea: la soglia deve stare fra "quanto somiglio a me stesso" (che vogliamo
    quasi sempre sopra) e "quanto somiglio agli altri" (che vogliamo sempre
    sotto). Se le due distribuzioni si toccano, il profilo va rifatto: nessuna
    soglia potra' separarle.
    """
    self_scores = [
        profile.score(profile.embeddings[i]) for i in range(profile.embeddings.shape[0])
    ] or [1.0]
    self_p10 = float(np.percentile(self_scores, 10))

    if cohort.size == 0:
        return {
            "accept_threshold": round(max(0.45, self_p10 - 0.15), 3),
            "continue_threshold": round(max(0.35, self_p10 - 0.27), 3),
            "note": "nessuna coorte: soglie prudenziali, si affinano con l'uso",
        }

    impostor = [profile.score(cohort.embeddings[i]) for i in range(cohort.size)]
    impostor_p95 = float(np.percentile(impostor, 95))
    accept = (self_p10 + impostor_p95) / 2.0 + safety
    accept = float(min(max(accept, 0.40), 0.85))
    return {
        "accept_threshold": round(accept, 3),
        "continue_threshold": round(max(0.35, accept - 0.12), 3),
        "self_p10": round(self_p10, 3),
        "impostor_p95": round(impostor_p95, 3),
        "separation": round(self_p10 - impostor_p95, 3),
        "note": (
            "separazione ampia: riconoscimento affidabile"
            if self_p10 - impostor_p95 > 0.15
            else "separazione stretta: rifai l'arruolamento con lo stesso microfono d'uso"
        ),
    }
