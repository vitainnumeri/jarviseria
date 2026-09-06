"""Cattura dal microfono: thread dedicato + coda di frame.

`sounddevice` viene importato pigramente cosi' il resto del pacchetto (e i test)
funziona su macchine senza scheda audio.
"""

from __future__ import annotations

import queue
import threading
from typing import Iterator

import numpy as np

from ..utils.logging import get_logger

log = get_logger(__name__)


class MicrophoneStream:
    """Flusso microfonico che consegna frame float32 mono di durata fissa.

    Il callback di PortAudio gira in un thread real-time: si limita a copiare
    nella coda, senza mai bloccare. Se il consumatore resta indietro, i frame
    piu' vecchi vengono scartati (meglio perdere audio che accumulare ritardo:
    in una conversazione il ritardo e' peggio di un buco).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        device: int | str | None = None,
        max_queue_frames: int = 200,
    ):
        self.sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.frame_len = int(self.sample_rate * self.frame_ms / 1000)
        self.device = device
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue_frames)
        self._stream = None
        self._running = threading.Event()
        self.dropped_frames = 0

    def _callback(self, indata, frames, time_info, status):  # pragma: no cover - I/O
        if status:
            log.debug("stato stream input: %s", status)
        frame = np.asarray(indata, dtype=np.float32).reshape(-1)
        try:
            self._queue.put_nowait(frame.copy())
        except queue.Full:
            self.dropped_frames += 1
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(frame.copy())
            except queue.Empty:  # pragma: no cover - corsa improbabile
                pass

    def start(self) -> "MicrophoneStream":  # pragma: no cover - I/O
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_len,
            device=self.device,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self._running.set()
        log.info("microfono attivo: %d Hz, frame %d ms", self.sample_rate, self.frame_ms)
        return self

    def stop(self) -> None:  # pragma: no cover - I/O
        self._running.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Preleva il frame successivo, o None se scade il timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def frames(self) -> Iterator[np.ndarray]:  # pragma: no cover - I/O
        while self._running.is_set():
            frame = self.read(timeout=0.5)
            if frame is not None:
                yield frame

    def __enter__(self) -> "MicrophoneStream":  # pragma: no cover - I/O
        return self.start()

    def __exit__(self, *exc) -> None:  # pragma: no cover - I/O
        self.stop()


def list_devices() -> str:  # pragma: no cover - I/O
    """Elenco leggibile dei dispositivi audio, per `jarvis devices`."""
    import sounddevice as sd

    lines = []
    for idx, dev in enumerate(sd.query_devices()):
        kind = []
        if dev["max_input_channels"]:
            kind.append(f"in:{dev['max_input_channels']}")
        if dev["max_output_channels"]:
            kind.append(f"out:{dev['max_output_channels']}")
        lines.append(f"[{idx:2d}] {dev['name']}  ({', '.join(kind)})  {dev['default_samplerate']:.0f} Hz")
    return "\n".join(lines)
