"""Single source of truth for environment configuration.

Every environment variable the bot reads is declared here so there is exactly one place
to look when wiring Docker / launchd / a `.env` file — no `os.environ` scattered across
modules (plan 09 §1). Each accessor takes an optional `env` mapping so tests can inject a
fake environment instead of mutating the real process env.

Variables
---------
BOT_DB_PATH          Path to the *live* runner database (plan 07). Default: backend/data/live.db.
BOT_ALERTS_DB_PATH   Path to the alert log database.       Default: <data>/alerts.db.
BOT_API_TOKEN        Bearer token guarding the API. Unset -> dev mode, no auth (plan 09 §2).
BOT_API_PORT         Port uvicorn binds in the container.  Default: 8000.
TELEGRAM_BOT_TOKEN   Telegram bot token for alert delivery (both needed or log-only).
TELEGRAM_CHAT_ID     Telegram chat id for alert delivery.

The API's own replay/backtest database (backend/data/runtime.db) is *not* env-driven — it
is a fixed on-disk location, distinct from the live database above.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

Env = Mapping[str, str] | None

DEFAULT_API_PORT = 8000


def _environ(env: Env) -> Mapping[str, str]:
    return env if env is not None else os.environ


def data_dir() -> Path:
    """backend/data/, created on demand. Holds every SQLite DB plus imported CSVs."""
    # src/bot/settings.py -> parents[2] == backend/
    path = Path(__file__).resolve().parents[2] / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_db_path() -> str:
    """The API's replay/backtest database. Fixed location, not overridable by env."""
    return str(data_dir() / "runtime.db")


def alerts_db_path(env: Env = None) -> str:
    value = _environ(env).get("BOT_ALERTS_DB_PATH", "").strip()
    return value or str(data_dir() / "alerts.db")


def live_db_path(env: Env = None) -> str:
    value = _environ(env).get("BOT_DB_PATH", "").strip()
    return value or str(data_dir() / "live.db")


def api_token(env: Env = None) -> str:
    """Bearer token guarding the API; empty string means auth is disabled (dev mode)."""
    return _environ(env).get("BOT_API_TOKEN", "").strip()


def api_port(env: Env = None) -> int:
    raw = _environ(env).get("BOT_API_PORT", "").strip()
    if not raw:
        return DEFAULT_API_PORT
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_API_PORT


def telegram_credentials(env: Env = None) -> tuple[str, str]:
    """(token, chat_id); either or both may be empty. build_notifier decides the fallback."""
    environ = _environ(env)
    return (
        environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        environ.get("TELEGRAM_CHAT_ID", "").strip(),
    )
