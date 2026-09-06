"""Misura vera: quante volte sbaglia, e in che direzione.

`jarvis diag` mostra i punteggi mentre scorrono. Utile per capire cosa succede,
inutile per decidere se fidarsi: guardare righe che scorrono non e' una misura.

Qui invece si contano due errori, che NON sono simmetrici:

    falso rifiuto (FRR)   parlo io e non mi sente.
                          Fastidioso: ripeto la frase.

    falso accesso (FAR)   parla un altro e gli risponde.
                          Grave: e' esattamente cio' che non deve succedere,
                          e in un'asta puo' voler dire un'offerta partita da
                          sola.

Quindi il criterio non e' "quanti errori in totale" ma "zero falsi accessi,
falsi rifiuti pochi". Un sistema che mi fa ripetere una frase su dieci ma non
apre mai a un estraneo e' buono; uno che non mi fa mai ripetere ma risponde a
un collega su venti e' inutilizzabile.

Il modulo e' NumPy puro: si collauda senza microfono e senza modelli.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Soglie del verdetto finale. Il FAR pesa molto di piu' del FRR.
FAR_OTTIMO = 0.0
FAR_ACCETTABILE = 0.02
FRR_OTTIMO = 0.05
FRR_ACCETTABILE = 0.15

# Pavimento della soglia consigliata. Le persone che hai registrato sono poche;
# quelle che entreranno nella stanza no. Una soglia cucita su quattro voci note
# non protegge dalla quinta, quindi non si scende sotto un minimo prudenziale
# per quanto bene siano andate le registrazioni di prova.
SOGLIA_MINIMA_CONSIGLIATA = 0.45


@dataclass
class Outcome:
    """Esito su un gruppo di registrazioni (le mie, oppure quelle degli altri)."""

    label: str
    turni_totali: int = 0
    turni_accettati: int = 0
    punteggi: list[float] = field(default_factory=list)
    finestre_totali: int = 0
    finestre_accettate: int = 0

    @property
    def tasso_accettazione(self) -> float:
        return self.turni_accettati / self.turni_totali if self.turni_totali else 0.0

    @property
    def punteggio_mediano(self) -> float:
        return float(np.median(self.punteggi)) if self.punteggi else 0.0

    def to_dict(self) -> dict:
        return {
            "gruppo": self.label,
            "turni": self.turni_totali,
            "turni_accettati": self.turni_accettati,
            "tasso_accettazione": round(self.tasso_accettazione, 4),
            "punteggio_mediano": round(self.punteggio_mediano, 4),
            "finestre": self.finestre_totali,
            "finestre_accettate": self.finestre_accettate,
        }


@dataclass
class BenchmarkResult:
    """Il verdetto, con i numeri che lo sostengono."""

    mine: Outcome
    others: Outcome
    eer: float = 0.0
    eer_threshold: float = 0.0
    separation: float = 0.0
    suggested_threshold: float | None = None
    verdict: str = ""
    advice: list[str] = field(default_factory=list)

    @property
    def frr(self) -> float:
        """Falsi rifiuti: quante volte parlo io e non mi sente."""
        return 1.0 - self.mine.tasso_accettazione

    @property
    def far(self) -> float:
        """Falsi accessi: quante volte parla un altro e gli risponde."""
        return self.others.tasso_accettazione

    def to_dict(self) -> dict:
        return {
            "verdetto": self.verdict,
            "falsi_accessi": round(self.far, 4),
            "falsi_rifiuti": round(self.frr, 4),
            "eer": round(self.eer, 4),
            "soglia_eer": round(self.eer_threshold, 4),
            "separazione": round(self.separation, 4),
            "soglia_suggerita": self.suggested_threshold,
            "mie_registrazioni": self.mine.to_dict(),
            "altre_voci": self.others.to_dict(),
            "consigli": self.advice,
        }


def equal_error_rate(mine: list[float], others: list[float]) -> tuple[float, float]:
    """Punto in cui falsi accessi e falsi rifiuti si equivalgono.

    E' la misura standard per confrontare due configurazioni fra loro: piu' e'
    basso, meglio le due distribuzioni sono separate. Non e' la soglia da usare
    davvero — quella va spostata verso i falsi rifiuti, perche' i due errori
    non costano uguale.

    Restituisce (eer, soglia a cui si verifica).
    """
    if not mine or not others:
        return 0.0, 0.0

    mine_arr = np.asarray(mine, dtype=np.float64)
    others_arr = np.asarray(others, dtype=np.float64)

    best_gap = float("inf")
    best_eer, best_threshold = 1.0, 0.0
    for threshold in sorted(set(mine) | set(others)):
        frr = float(np.mean(mine_arr < threshold))
        far = float(np.mean(others_arr >= threshold))
        gap = abs(far - frr)
        if gap < best_gap:
            best_gap = gap
            best_eer = (far + frr) / 2.0
            best_threshold = float(threshold)
    return best_eer, best_threshold


def suggest_threshold(mine: list[float], others: list[float], *, margin: float = 0.04) -> float | None:
    """La soglia piu' bassa che azzera i falsi accessi.

    La strategia e' esplicita: appena sopra il punteggio piu' alto ottenuto da
    un estraneo. Piu' in basso di cosi' qualcuno passa; piu' in alto ti fa
    ripetere le frasi senza guadagnare sicurezza.

    Restituisce None se nemmeno quella soglia funziona, cioe' se un estraneo ha
    fatto meglio di te: in quel caso il problema non e' il numero da scrivere
    in configurazione, e' l'arruolamento o il microfono.
    """
    if not mine or not others:
        return None
    soglia = max(float(np.max(others)) + margin, SOGLIA_MINIMA_CONSIGLIATA)
    if soglia >= float(np.max(mine)):
        return None
    return round(soglia, 3)


def _verdict(far: float, frr: float, separation: float) -> tuple[str, list[str]]:
    """Traduce i numeri in una frase e in cosa fare dopo."""
    advice: list[str] = []

    if far <= FAR_OTTIMO and frr <= FRR_OTTIMO:
        verdict = "AFFIDABILE: nessun estraneo e' passato e ti sente quasi sempre"
    elif far <= FAR_OTTIMO and frr <= FRR_ACCETTABILE:
        verdict = "BUONO: nessun estraneo e' passato, ogni tanto devi ripetere"
        advice.append(
            "Per farti ripetere di meno abbassa accept_threshold di 0.03 alla volta "
            "e rifai questa prova: fermati appena un estraneo passa."
        )
    elif far <= FAR_ACCETTABILE:
        verdict = "AL LIMITE: qualche voce altrui e' passata"
        advice.append("Alza accept_threshold di 0.05 e rifai la prova.")
        advice.append(
            "Registra la coorte con le voci di chi ti sta intorno "
            "(jarvis cohort --files ...): e' la contromisura piu' efficace."
        )
    else:
        verdict = "NON AFFIDABILE: troppe voci altrui passano"
        advice.append(
            "Prima di toccare le soglie: usa un auricolare con microfono vicino alla bocca. "
            "Recuperi 20 dB di vantaggio che nessun parametro puo' darti."
        )
        advice.append("Poi rifai l'arruolamento con QUEL microfono: jarvis enroll")

    if frr > FRR_ACCETTABILE:
        advice.append(
            f"Ti perde {frr:.0%} delle frasi: parla piu' vicino al microfono, "
            "oppure abbassa accept_threshold."
        )
    if separation < 0.15:
        advice.append(
            f"Le due distribuzioni sono vicine (separazione {separation:+.3f}): "
            "il profilo non distingue bene. Rifai l'arruolamento nelle condizioni d'uso reali."
        )
    return verdict, advice


def evaluate(mine: Outcome, others: Outcome) -> BenchmarkResult:
    """Compone il verdetto a partire dai due gruppi di registrazioni."""
    result = BenchmarkResult(mine=mine, others=others)

    if mine.punteggi and others.punteggi:
        result.eer, result.eer_threshold = equal_error_rate(mine.punteggi, others.punteggi)
        result.separation = float(
            np.percentile(mine.punteggi, 10) - np.percentile(others.punteggi, 90)
        )
        result.suggested_threshold = suggest_threshold(mine.punteggi, others.punteggi)

    result.verdict, result.advice = _verdict(result.far, result.frr, result.separation)
    if result.suggested_threshold is None and mine.punteggi and others.punteggi:
        result.advice.append(
            "Nessuna soglia separa la tua voce da quelle degli altri in queste "
            "registrazioni: il problema e' a monte (microfono o arruolamento)."
        )
    return result


def format_report(result: BenchmarkResult) -> str:
    """Il rapporto da leggere a schermo."""
    lines = [
        "",
        "=" * 62,
        f"  {result.verdict}",
        "=" * 62,
        "",
        f"  Falsi accessi (parla un altro, risponde) : {result.far:6.1%}"
        f"   <- deve essere 0%",
        f"  Falsi rifiuti (parli tu, non ti sente)   : {result.frr:6.1%}"
        f"   <- sotto il 15% va bene",
        "",
        f"  Separazione fra te e gli altri           : {result.separation:+6.3f}"
        f"   <- sopra 0.15 e' solida",
        f"  Equal Error Rate                         : {result.eer:6.1%}",
        "",
        f"  Tue registrazioni  : {result.mine.turni_accettati:>3}/{result.mine.turni_totali:<3} turni "
        f"riconosciuti  (punteggio mediano {result.mine.punteggio_mediano:.3f})",
        f"  Voci altrui        : {result.others.turni_accettati:>3}/{result.others.turni_totali:<3} turni "
        f"passati       (punteggio mediano {result.others.punteggio_mediano:.3f})",
    ]

    if result.suggested_threshold is not None:
        lines += [
            "",
            "  Soglia suggerita da queste registrazioni, per config/local.yaml:",
            "",
            "    speaker:",
            f"      accept_threshold: {result.suggested_threshold}",
        ]

    if result.advice:
        lines += ["", "  Cosa fare adesso:"]
        lines += [f"    - {a}" for a in result.advice]

    lines += [
        "",
        "  Nota: usa registrazioni DIVERSE da quelle con cui hai costruito la",
        "  coorte, altrimenti la prova si giudica da sola e i numeri mentono.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------- valutazione
def load_audio(path, target_rate: int = 16000) -> np.ndarray:
    """Carica un file audio come mono float32 alla frequenza richiesta."""
    import soundfile as sf

    from ..audio.dsp import resample_linear, to_float32

    samples, rate = sf.read(str(path), dtype="float32", always_2d=False)
    audio = to_float32(np.asarray(samples))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return resample_linear(audio, rate, target_rate) if rate != target_rate else audio


def split_turns(audio: np.ndarray, sample_rate: int, *, turn_seconds: float = 4.0,
                silence_db: float = -50.0) -> list[np.ndarray]:
    """Spezza una registrazione in turni della durata di una frase parlata.

    Taglio a durata fissa invece che con il VAD: qui interessa valutare la
    biometria, e far dipendere la misura anche dalla segmentazione la
    renderebbe piu' difficile da interpretare. I pezzi quasi silenziosi (pause,
    code di registrazione) vengono scartati perche' non sono turni.
    """
    from ..audio.dsp import dbfs

    step = int(turn_seconds * sample_rate)
    if step <= 0:
        return []
    turns = []
    for start in range(0, audio.size, step):
        chunk = audio[start : start + step]
        if chunk.size >= sample_rate and dbfs(chunk) > silence_db:
            turns.append(chunk)
    return turns


def score_recordings(verifier, paths, label: str, *, turn_seconds: float = 4.0) -> Outcome:
    """Valuta un gruppo di registrazioni con la configurazione attuale.

    L'apprendimento e' disattivato di proposito: durante una misura il sistema
    non deve imparare dalle registrazioni che sta valutando, altrimenti si
    giudica da solo.
    """
    outcome = Outcome(label=label)
    sample_rate = verifier.cfg.sample_rate

    for path in paths:
        audio = load_audio(path, sample_rate)
        for turn in split_turns(audio, sample_rate, turn_seconds=turn_seconds):
            result = verifier.verify(turn, learn=False)
            verifier.reset_turn()          # ogni turno parte pulito: niente isteresi fra file
            outcome.turni_totali += 1
            outcome.turni_accettati += int(result.is_owner)
            outcome.punteggi.append(result.score)
            outcome.finestre_totali += len(result.windows)
            outcome.finestre_accettate += sum(1 for w in result.windows if w.passed)
    return outcome


def run_benchmark(verifier, mine_paths, others_paths, *, turn_seconds: float = 4.0) -> BenchmarkResult:
    """Misura completa: le mie registrazioni contro quelle degli altri."""
    mine = score_recordings(verifier, mine_paths, "io", turn_seconds=turn_seconds)
    others = score_recordings(verifier, others_paths, "altri", turn_seconds=turn_seconds)
    if mine.turni_totali == 0:
        raise ValueError("nessun turno utilizzabile nelle tue registrazioni: sono troppo corte o silenziose")
    if others.turni_totali == 0:
        raise ValueError("nessun turno utilizzabile nelle registrazioni degli altri")
    return evaluate(mine, others)
