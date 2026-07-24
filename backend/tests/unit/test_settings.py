"""bot.settings — the single env-reading seam (plan 09 §1)."""

from __future__ import annotations

from bot import settings


def test_api_token_defaults_empty() -> None:
    assert settings.api_token(env={}) == ""


def test_api_token_stripped() -> None:
    assert settings.api_token(env={"BOT_API_TOKEN": "  abc  "}) == "abc"


def test_api_port_default() -> None:
    assert settings.api_port(env={}) == settings.DEFAULT_API_PORT


def test_api_port_parsed() -> None:
    assert settings.api_port(env={"BOT_API_PORT": "9001"}) == 9001


def test_api_port_bad_value_falls_back() -> None:
    assert settings.api_port(env={"BOT_API_PORT": "not-a-number"}) == settings.DEFAULT_API_PORT


def test_telegram_credentials() -> None:
    token, chat = settings.telegram_credentials(
        env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    )
    assert (token, chat) == ("t", "c")


def test_live_db_path_override() -> None:
    assert settings.live_db_path(env={"BOT_DB_PATH": "/tmp/x.db"}) == "/tmp/x.db"


def test_alerts_db_path_override() -> None:
    assert settings.alerts_db_path(env={"BOT_ALERTS_DB_PATH": "/tmp/a.db"}) == "/tmp/a.db"
