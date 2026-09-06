"""Primitive DSP: livelli, rumore di fondo, correlazione d'eco.

Tutto qui dentro e' NumPy puro: nessuna dipendenza pesante, quindi testabile
senza microfono e senza modelli.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-10


def to_float32(audio: np.ndarray) -> np.ndarray:
    """Normalizza PCM int16 (o altro) in float32 nell'intervallo [-1, 1]."""
    if audio.dtype == np.float32:
        return audio
    if audio.dtype == np.int16:
        return (audio.astype(np.float32) / 32768.0).clip(-1.0, 1.0)
    return audio.astype(np.float32)


def to_int16(audio: np.ndarray) -> np.ndarray:
    """Converte float32 [-1, 1] in PCM int16 con clipping."""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)


def rms(audio: np.ndarray) -> float:
    """Valore efficace del segnale."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(to_float32(audio), dtype=np.float64))))


def dbfs(audio: np.ndarray) -> float:
    """Livello in dB rispetto al fondo scala. Il silenzio digitale vale -100 dB."""
    return float(20.0 * np.log10(max(rms(audio), EPS)))


class NoiseFloor:
    """Stima adattiva del rumore di fondo della stanza.

    Sale lentamente e scende velocemente: cosi' una risata improvvisa non alza
    la stima per sempre, ma il brusio costante di una sala d'asta si'.
    """

    def __init__(self, initial_db: float = -60.0, up: float = 0.02, down: float = 0.25):
        self.value_db = float(initial_db)
        self.up = float(up)
        self.down = float(down)

    def update(self, frame: np.ndarray) -> float:
        level = dbfs(frame)
        alpha = self.up if level > self.value_db else self.down
        self.value_db += alpha * (level - self.value_db)
        return self.value_db

    def is_near_field(self, frame: np.ndarray, margin_db: float) -> bool:
        """Vero se il frame e' abbastanza sopra il fondo da venire da vicino.

        Chi parla dall'altra parte della stanza arriva pochi dB sopra il brusio:
        e' il filtro piu' economico contro le voci lontane, e non sbaglia mai
        per ragioni "statistiche" perche' e' fisica.
        """
        return dbfs(frame) >= self.value_db + margin_db


def normalized_xcorr(signal: np.ndarray, reference: np.ndarray, max_lag: int) -> float:
    """Massima cross-correlazione normalizzata fra ingresso e segnale riprodotto.

    Serve al guardiano dell'eco: se cio' che il microfono sente e' fortemente
    correlato con cio' che l'altoparlante sta suonando, e' il bot che si
    riascolta, non l'utente.

    Restituisce un valore in [0, 1].
    """
    x = to_float32(np.asarray(signal, dtype=np.float32)).ravel()
    y = to_float32(np.asarray(reference, dtype=np.float32)).ravel()
    n = min(x.size, y.size)
    if n < 64:
        return 0.0
    x, y = x[-n:], y[-n:]
    x = x - x.mean()
    y = y - y.mean()
    denom = float(np.linalg.norm(x) * np.linalg.norm(y))
    if denom < EPS:
        return 0.0
    max_lag = max(1, min(int(max_lag), n - 1))
    best = 0.0
    # Il ritardo altoparlante->microfono e' ignoto: provo una griglia di lag.
    for lag in range(0, max_lag, max(1, max_lag // 24)):
        seg_x = x[lag:]
        seg_y = y[: seg_x.size]
        if seg_x.size < 64:
            break
        best = max(best, abs(float(np.dot(seg_x, seg_y)) / denom))
    return min(best, 1.0)


def resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Ricampionamento lineare (sufficiente per fattori piccoli e voce)."""
    audio = to_float32(np.asarray(audio)).ravel()
    if src_rate == dst_rate or audio.size == 0:
        return audio
    duration = audio.size / float(src_rate)
    dst_len = max(1, int(round(duration * dst_rate)))
    src_idx = np.linspace(0.0, audio.size - 1, num=dst_len, dtype=np.float64)
    return np.interp(src_idx, np.arange(audio.size), audio).astype(np.float32)


def frame_signal(audio: np.ndarray, frame_len: int, hop_len: int) -> list[np.ndarray]:
    """Divide il segnale in finestre sovrapposte (l'ultima parziale e' scartata)."""
    audio = np.asarray(audio).ravel()
    if frame_len <= 0 or hop_len <= 0 or audio.size < frame_len:
        return [audio] if audio.size else []
    return [audio[i : i + frame_len] for i in range(0, audio.size - frame_len + 1, hop_len)]
