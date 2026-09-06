"""Logging e trascrizione della conversazione."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_CONFIGURED = False


def setup_logging(level: str = "INFO", file: str | Path | None = None) -> None:
    """Configura il logger radice una sola volta per processo."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if file:
        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("speechbrain").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class TranscriptWriter:
    """Scrive la conversazione in JSONL: utile per rivedere un'asta a posteriori."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, role: str, text: str, **meta: Any) -> None:
        if not self.path or not text:
            return
        record = {"ts": time.time(), "role": role, "text": text, **meta}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
