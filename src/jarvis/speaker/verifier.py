"""Il portiere: decide, finestra per finestra, se chi parla sono io.

Il problema posto e' "in mezzo a una stanza di persone che parlano deve sentire
solo me". Non esiste un singolo trucco che lo risolva, quindi qui ci sono
quattro filtri in cascata, dal piu' economico al piu' costoso:

    1. campo vicino   il parlante lontano arriva pochi dB sopra il brusio ->
                      scartato per fisica, prima ancora di toccare la rete;
    2. somiglianza    coseno fra impronta della finestra e profilo arruolato;
    3. margine        devo somigliare a me piu' che a chiunque altro nella
                      coorte, e di almeno `reject_margin`. E' questa la regola
                      che regge in una stanza affollata: non chiede "e' simile
                      a David?" ma "e' piu' David che chiunque altro qui?";
    4. maggioranza    un turno vale se lo supera la maggior parte delle sue
                      finestre, non una singola fortunata.

In piu' due meccanismi temporali:

    isteresi          una volta agganciato il proprietario la soglia si abbassa,
                      cosi' una frase lunga non si spezza a meta';
    rifiuto precoce   dopo N finestre fallite il turno viene buttato senza
                      trascriverlo: e' cosi' che il collega che parla accanto
                      non consuma ne' latenza ne' token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..audio.dsp import NoiseFloor, dbfs, frame_signal
from ..utils.logging import get_logger
from .profile import Cohort, VoiceProfile

log = get_logger(__name__)


class Decision(Enum):
    """Esito della valutazione di una finestra o di un turno."""

    OWNER = "owner"           # sono io: procedi
    STRANGER = "stranger"     # e' un altro: ignora in silenzio
    UNCERTAIN = "uncertain"   # non abbastanza informazione (troppo corto, troppo piano)


@dataclass
class WindowScore:
    """Diagnostica di una singola finestra: serve a spiegare *perche'* una
    voce e' stata accettata o rifiutata (comando `jarvis diag`)."""

    index: int
    owner_score: float
    cohort_score: float
    margin: float
    level_db: float
    near_field: bool
    decision: Decision

    @property
    def passed(self) -> bool:
        return self.decision is Decision.OWNER


@dataclass
class VerificationResult:
    """Verdetto su un turno completo."""

    decision: Decision
    score: float                      # punteggio mediano delle finestre passate
    windows: list[WindowScore] = field(default_factory=list)
    accepted_ratio: float = 0.0
    overlap_detected: bool = False    # qualcuno ha parlato sopra di me
    reason: str = ""
    embedding: np.ndarray | None = None
    trimmed_audio: np.ndarray | None = None

    @property
    def is_owner(self) -> bool:
        return self.decision is Decision.OWNER


@dataclass
class VerifierConfig:
    """Parametri del portiere. I default vivono in config/default.yaml."""

    accept_threshold: float = 0.62
    continue_threshold: float = 0.50
    reject_margin: float = 0.10
    window_sec: float = 1.0
    hop_sec: float = 0.5
    min_windows_ratio: float = 0.6
    early_reject_windows: int = 3
    unlock_after_failures: int = 2
    near_field_enabled: bool = True
    near_field_margin_db: float = 8.0
    cohort_enabled: bool = True
    cohort_top_k: int = 20
    cohort_auto_learn: bool = True
    adaptation_enabled: bool = True
    adaptation_min_score: float = 0.78
    adaptation_rate: float = 0.05
    sample_rate: int = 16000

    @classmethod
    def from_config(cls, cfg) -> "VerifierConfig":
        """Costruisce i parametri dalla sezione `speaker` della configurazione."""
        s = cfg.section("speaker")
        return cls(
            accept_threshold=float(s.get("accept_threshold", 0.62)),
            continue_threshold=float(s.get("continue_threshold", 0.50)),
            reject_margin=float(s.get("reject_margin", 0.10)),
            window_sec=float(s.get("window_sec", 1.0)),
            hop_sec=float(s.get("hop_sec", 0.5)),
            min_windows_ratio=float(s.get("min_windows_ratio", 0.6)),
            early_reject_windows=int(s.get("early_reject_windows", 3)),
            unlock_after_failures=int(s.get("unlock_after_failures", 2)),
            near_field_enabled=bool(s.get("near_field.enabled", True)),
            near_field_margin_db=float(s.get("near_field.margin_db", 8.0)),
            cohort_enabled=bool(s.get("cohort.enabled", True)),
            cohort_top_k=int(s.get("cohort.top_k", 20)),
            cohort_auto_learn=bool(s.get("cohort.auto_learn", True)),
            adaptation_enabled=bool(s.get("adaptation.enabled", True)),
            adaptation_min_score=float(s.get("adaptation.min_score", 0.78)),
            adaptation_rate=float(s.get("adaptation.rate", 0.05)),
            sample_rate=int(cfg.get("audio.sample_rate", 16000)),
        )


class SpeakerVerifier:
    """Applica la cascata di filtri a finestre e a turni interi.

    L'oggetto e' con stato (isteresi, rumore di fondo, coorte adattiva): va
    creato una volta per sessione, non per turno.
    """

    def __init__(
        self,
        embedder,
        profile: VoiceProfile,
        config: VerifierConfig | None = None,
        cohort: Cohort | None = None,
    ):
        self.embedder = embedder
        self.profile = profile
        self.cfg = config or VerifierConfig()
        self.cohort = cohort if cohort is not None else Cohort()
        self.noise = NoiseFloor()
        self._locked = False          # sto gia' ascoltando il proprietario?
        self._consecutive_fail = 0
        self.stats = {"turns_accepted": 0, "turns_rejected": 0, "windows": 0}

    # ------------------------------------------------------------------ util
    @property
    def locked(self) -> bool:
        """Vero mentre il turno del proprietario e' in corso (isteresi attiva)."""
        return self._locked

    def observe_noise(self, frame: np.ndarray) -> float:
        """Aggiorna il rumore di fondo con un frame di NON parlato."""
        return self.noise.update(frame)

    def reset_turn(self) -> None:
        self._locked = False
        self._consecutive_fail = 0

    def _threshold(self) -> float:
        """Soglia effettiva: piu' bassa mentre sto gia' parlando (isteresi)."""
        return self.cfg.continue_threshold if self._locked else self.cfg.accept_threshold

    # -------------------------------------------------------------- finestre
    def score_window(self, audio: np.ndarray, index: int = 0) -> WindowScore:
        """Valuta una finestra di ~1 secondo."""
        level_db = dbfs(audio)
        near = (
            self.noise.is_near_field(audio, self.cfg.near_field_margin_db)
            if self.cfg.near_field_enabled
            else True
        )

        embedding = self.embedder.embed(audio, self.cfg.sample_rate)
        owner = self.profile.score(embedding)
        cohort_best = self.cohort.best_match(embedding) if self.cfg.cohort_enabled else -1.0
        margin = owner - cohort_best if cohort_best > -1.0 else float("inf")

        threshold = self._threshold()
        if not near:
            decision = Decision.STRANGER          # troppo lontano dal microfono
        elif owner < threshold:
            decision = Decision.STRANGER          # non somiglia abbastanza a me
        elif margin < self.cfg.reject_margin:
            decision = Decision.STRANGER          # somiglia troppo a un altro presente
        else:
            decision = Decision.OWNER

        self.stats["windows"] += 1
        return WindowScore(
            index=index,
            owner_score=owner,
            cohort_score=cohort_best,
            margin=float(margin) if np.isfinite(margin) else 1.0,
            level_db=level_db,
            near_field=near,
            decision=decision,
        )

    def _windows(self, audio: np.ndarray) -> list[np.ndarray]:
        win = int(self.cfg.window_sec * self.cfg.sample_rate)
        hop = int(self.cfg.hop_sec * self.cfg.sample_rate)
        return frame_signal(audio, win, hop) or ([audio] if audio.size else [])

    # ----------------------------------------------------------------- turni
    def verify(self, audio: np.ndarray, *, learn: bool = True) -> VerificationResult:
        """Verdetto su un turno completo di parlato."""
        audio = np.asarray(audio, dtype=np.float32).ravel()
        min_len = int(0.35 * self.cfg.sample_rate)
        if audio.size < min_len:
            return VerificationResult(
                Decision.UNCERTAIN, 0.0, reason="segmento troppo breve per identificare la voce"
            )

        scores = [self.score_window(win, i) for i, win in enumerate(self._windows(audio))]
        if not scores:
            return VerificationResult(Decision.UNCERTAIN, 0.0, reason="nessuna finestra analizzabile")

        passed = [s for s in scores if s.passed]
        ratio = len(passed) / len(scores)
        owner_scores = [s.owner_score for s in scores]
        # Sovrapposizione: alcune finestre mie, altre chiaramente di un altro.
        overlap = bool(passed) and any(
            s.owner_score < self.cfg.continue_threshold - 0.10 for s in scores
        )

        if ratio >= self.cfg.min_windows_ratio:
            score = float(np.median([s.owner_score for s in passed]))
            result = VerificationResult(
                decision=Decision.OWNER,
                score=score,
                windows=scores,
                accepted_ratio=ratio,
                overlap_detected=overlap,
                reason="voce del proprietario confermata"
                + (" (con sovrapposizione di altre voci)" if overlap else ""),
                trimmed_audio=self._trim(audio, scores),
            )
            self.stats["turns_accepted"] += 1
            if learn:
                self._maybe_adapt(audio, score)
            return result

        self.stats["turns_rejected"] += 1
        # Impara la voce solo se e' CHIARAMENTE di un altro. Un turno mio
        # respinto per un soffio - ho parlato piano, mi sono girato dall'altra
        # parte - non deve finire fra gli estranei: da li' in poi il margine
        # lavorerebbe contro di me e il sistema smetterebbe progressivamente di
        # riconoscermi. E' una deriva silenziosa e lenta, quindi difficile da
        # attribuire quando succede.
        median_score = float(np.median(owner_scores))
        clearly_stranger = median_score < self._threshold() * 0.5
        if learn and self.cfg.cohort_auto_learn and ratio == 0.0 and clearly_stranger:
            self._learn_stranger(audio)
        return VerificationResult(
            decision=Decision.STRANGER,
            score=float(np.median(owner_scores)),
            windows=scores,
            accepted_ratio=ratio,
            overlap_detected=overlap,
            reason=f"voce non riconosciuta ({len(passed)}/{len(scores)} finestre superate)",
        )

    def _trim(self, audio: np.ndarray, scores: list[WindowScore]) -> np.ndarray:
        """Taglia le finestre estranee in testa e in coda al turno.

        Caso tipico: qualcuno finisce la sua frase mentre io comincio la mia.
        Tagliando i bordi la trascrizione non eredita le sue parole.
        """
        idx = [s.index for s in scores if s.passed]
        if not idx or len(scores) < 2:
            return audio
        hop = int(self.cfg.hop_sec * self.cfg.sample_rate)
        win = int(self.cfg.window_sec * self.cfg.sample_rate)
        start = max(0, min(idx) * hop)
        end = min(audio.size, max(idx) * hop + win)
        return audio[start:end] if end - start >= int(0.3 * self.cfg.sample_rate) else audio

    def _maybe_adapt(self, audio: np.ndarray, score: float) -> None:
        """Adatta il profilo solo su turni davvero inequivocabili."""
        if not self.cfg.adaptation_enabled or score < self.cfg.adaptation_min_score:
            return
        embedding = self.embedder.embed(audio, self.cfg.sample_rate)
        self.profile.adapt(embedding, rate=self.cfg.adaptation_rate)
        log.debug("profilo adattato (punteggio %.3f)", score)

    def _learn_stranger(self, audio: np.ndarray) -> None:
        embedding = self.embedder.embed(audio, self.cfg.sample_rate)
        if self.cohort.add(embedding):
            log.debug("nuova voce estranea in coorte (totale %d)", self.cohort.size)

    # ------------------------------------------------- verifica incrementale
    def stream_decision(self, scores: list[WindowScore]) -> Decision:
        """Decisione parziale su un turno ancora in corso.

        Chiamata dall'orchestratore ogni `hop_sec` mentre l'utente parla:
        permette di scartare un estraneo dopo ~1,5 s invece di aspettare la
        fine della frase, trascriverla e poi buttarla.
        """
        if not scores:
            return Decision.UNCERTAIN

        tail = scores[-self.cfg.early_reject_windows :]
        if len(tail) >= self.cfg.early_reject_windows and not any(s.passed for s in tail):
            self._locked = False
            self._consecutive_fail = 0
            return Decision.STRANGER

        if any(s.passed for s in scores):
            self._locked = True
            self._consecutive_fail = sum(1 for s in reversed(scores) if not s.passed)
            if self._consecutive_fail >= self.cfg.unlock_after_failures:
                self._locked = False
            return Decision.OWNER

        return Decision.UNCERTAIN
