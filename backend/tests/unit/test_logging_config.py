"""JSON-lines logging (plan 09 §3)."""

from __future__ import annotations

import json
import logging

from bot.logging_config import JsonFormatter, configure_logging


def _format(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter().format(record))


def test_basic_fields() -> None:
    rec = logging.LogRecord("bot.run", logging.INFO, __file__, 10, "hello", (), None)
    out = _format(rec)
    assert out["level"] == "INFO"
    assert out["logger"] == "bot.run"
    assert out["msg"] == "hello"
    assert "ts" in out


def test_extra_fields_promoted() -> None:
    rec = logging.LogRecord("bot.run", logging.INFO, __file__, 10, "x", (), None)
    rec.event = "run_created"  # type: ignore[attr-defined]
    rec.run_id = 7  # type: ignore[attr-defined]
    out = _format(rec)
    assert out["event"] == "run_created"
    assert out["run_id"] == 7


def test_exception_stack_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            "bot.run", logging.ERROR, __file__, 10, "failed", (), sys.exc_info()
        )
    out = _format(rec)
    assert "boom" in str(out["exc"])


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
