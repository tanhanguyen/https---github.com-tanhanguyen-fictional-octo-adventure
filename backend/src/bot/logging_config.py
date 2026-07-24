"""JSON-lines logging to stdout (plan 09 §3).

One line per record so Docker's log driver (and `docker compose logs`) can collect and
grep structured events without a sidecar. Call `configure_logging()` once at a process
entry point (API app factory, CLI, live runner). It is idempotent: a second call replaces
the handler rather than stacking a duplicate, so importing the app in tests never doubles
every log line.

Levels follow the plan:
* INFO    — decision / trade / run-lifecycle events (the operational narrative).
* WARNING — degraded-but-running conditions (e.g. a feed falling back).
* ERROR   — failures, emitted with the exception stack (`exc_info=True`).

Extra structured fields ride on the record via `logger.info(msg, extra={"event": ...})`
and land as top-level keys in the JSON object.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys

#: Attributes the stdlib puts on every LogRecord. Anything NOT here was passed via
#: `extra=` and is worth promoting to a top-level JSON field.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str | int | None = None) -> None:
    """Install the JSON handler on the root logger. Idempotent.

    Level comes from the `LOG_LEVEL` env var (default INFO) unless overridden by the
    `level` argument.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any handlers we installed before (idempotency) but leave nothing stacked.
    root.handlers = [handler]
