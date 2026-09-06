"""Caricamento della configurazione.

Precedenza (dalla piu' bassa alla piu' alta):
    config/default.yaml  ->  config/local.yaml  ->  file passato a mano  ->  variabili d'ambiente
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.yaml"
LOCAL_CONFIG = PROJECT_ROOT / "config" / "local.yaml"

# Variabili d'ambiente che sovrascrivono chiavi di configurazione.
ENV_OVERRIDES = {
    "JARVIS_LLM_MODEL": "llm.model",
    "JARVIS_ASR_PROVIDER": "asr.provider",
    "JARVIS_ASR_MODEL": "asr.model",
    "JARVIS_TTS_PROVIDER": "tts.provider",
    "JARVIS_PROFILE": "speaker.profile_path",
    "JARVIS_LISTONE": "fanta.listone_path",
    "JARVIS_INPUT_DEVICE": "audio.input_device",
    "JARVIS_LOG_LEVEL": "log.level",
}


class Config:
    """Dizionario annidato con accesso puntato e valori di default.

    >>> cfg = Config({"speaker": {"accept_threshold": 0.62}})
    >>> cfg.get("speaker.accept_threshold")
    0.62
    >>> cfg.get("speaker.inesistente", 1)
    1
    """

    def __init__(self, data: Mapping[str, Any] | None = None):
        self._data: dict[str, Any] = copy.deepcopy(dict(data or {}))

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in path.split("."):
            if not isinstance(node, Mapping) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, path: str, value: Any) -> None:
        keys = path.split(".")
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def section(self, path: str) -> "Config":
        return Config(self.get(path, {}) or {})

    def resolve_path(self, path: str, default: str | None = None) -> Path:
        """Risolve un percorso di configurazione rispetto alla radice del progetto."""
        raw = self.get(path, default)
        if raw is None:
            raise KeyError(f"percorso non configurato: {path}")
        p = Path(str(raw)).expanduser()
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def __repr__(self) -> str:  # pragma: no cover - diagnostica
        return f"Config({self._data!r})"


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Fonde `override` dentro `base` ricorsivamente, senza mutare gli input."""
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _coerce(text: str) -> Any:
    """Converte una stringa d'ambiente nel tipo YAML piu' plausibile."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def load_config(extra: str | Path | None = None, *, use_env: bool = True) -> Config:
    """Costruisce la configurazione effettiva della sessione."""
    data: dict[str, Any] = {}
    for candidate in (DEFAULT_CONFIG, LOCAL_CONFIG, Path(extra) if extra else None):
        if candidate and Path(candidate).is_file():
            loaded = yaml.safe_load(Path(candidate).read_text(encoding="utf-8")) or {}
            data = deep_merge(data, loaded)

    cfg = Config(data)
    if use_env:
        for env_key, cfg_path in ENV_OVERRIDES.items():
            raw = os.environ.get(env_key)
            if raw not in (None, ""):
                cfg.set(cfg_path, _coerce(raw))
    return cfg


def require_env(name: str, *, hint: str = "") -> str:
    """Legge una variabile d'ambiente obbligatoria con un messaggio d'errore utile."""
    value = os.environ.get(name)
    if not value:
        suffix = f" {hint}" if hint else ""
        raise RuntimeError(f"Variabile d'ambiente {name} mancante.{suffix} Vedi .env.example.")
    return value
