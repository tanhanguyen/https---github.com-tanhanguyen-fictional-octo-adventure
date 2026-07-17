"""YAML load + deep-merge + pydantic validate. Pure I/O helper — no DB, no FastAPI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from bot.config.models import BotConfig
from bot.core.errors import ConfigError


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `patch` onto `base`; lists/scalars in patch replace base's."""
    out = dict(base)
    for key, value in patch.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top-level YAML must be a mapping")
    return data


def load_config(path: Path, overrides: dict[str, Any] | None = None) -> BotConfig:
    raw = load_yaml(path)
    if overrides:
        raw = deep_merge(raw, overrides)
    try:
        return BotConfig.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError etc.
        raise ConfigError(f"invalid config {path}: {exc}") from exc


def default_config_path() -> Path:
    # backend/config/default.yaml relative to this file: src/bot/config/loader.py
    return Path(__file__).resolve().parents[3] / "config" / "default.yaml"


def load_default_config() -> BotConfig:
    return load_config(default_config_path())


def load_instruments(path: Path | None = None) -> dict[str, dict[str, Any]]:
    if path is None:
        path = Path(__file__).resolve().parents[3] / "config" / "instruments.yaml"
    data = load_yaml(path)
    instruments = data.get("instruments", {})
    if not isinstance(instruments, dict):
        raise ConfigError(f"{path}: 'instruments' must be a mapping")
    return instruments
