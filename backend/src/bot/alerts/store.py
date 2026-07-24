"""The alert log: its own SQLite file, shared by every process that can raise an alert.

**Why a separate database.** Alerts are cross-run operational history, but the runs that
produce them live in two different files: a backtest/API run writes `runtime.db`, a live
run writes `live.db` (plan 07 §3 keeps them apart on purpose). The plan asks for one
`GET /api/alerts?since_id=` cursor over "the" alert log, and one cursor only makes sense
over one id space — so the alert log gets its own file (`backend/data/alerts.db`,
overridable with `BOT_ALERTS_DB_PATH`) that both writers append to.

Two consequences worth stating:

* The API may write here (marking alerts read) without breaking the plan 07 rule that
  the API never writes to a live run's database — this is not a run's database.
* `run_id` is recorded but is NOT a foreign key: it is qualified by `source`
  (`live` / `backtest`), because run #3 in `live.db` and run #3 in `runtime.db` are
  different runs.

Concurrency: WAL + a busy timeout, so the live writer and the API reader/marker never
block each other into an error.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: How long a writer waits for a competing writer before giving up. Alert writes are
#: tiny; anything near this means something is very wrong elsewhere.
BUSY_TIMEOUT_MS = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER,
    source          TEXT    NOT NULL DEFAULT '',
    ts_utc          TEXT    NOT NULL,
    level           TEXT    NOT NULL,
    code            TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    body_json       TEXT    NOT NULL DEFAULT '{}',
    dedupe_key      TEXT    NOT NULL DEFAULT '',
    sent_telegram   INTEGER NOT NULL DEFAULT 0,
    telegram_status TEXT    NOT NULL DEFAULT 'pending',
    read            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alert_level ON alert(level);
CREATE INDEX IF NOT EXISTS idx_alert_unread ON alert(read);
CREATE INDEX IF NOT EXISTS idx_alert_cooldown ON alert(code, dedupe_key, id);
CREATE INDEX IF NOT EXISTS idx_alert_retry ON alert(telegram_status, id);
"""

#: `telegram_status` values. `pending` never survives an emit — it exists so a row is
#: never ambiguous if a process dies between INSERT and the delivery attempt.
TELEGRAM_PENDING = "pending"
TELEGRAM_SENT = "sent"
#: Delivered to the log-only fallback sink (no token configured). Counts as delivered
#: for the cooldown, but `sent_telegram` stays 0 — nobody's phone buzzed.
TELEGRAM_LOGGED = "logged"
TELEGRAM_FAILED = "failed"  # delivery attempted and failed -> retried on a later emit
TELEGRAM_SUPPRESSED = "suppressed"  # inside the cooldown window -> deliberately not sent
TELEGRAM_MUTED = "muted"  # below threshold / muted code / channel off -> never sent


def default_alerts_db_path() -> str:
    env = os.environ.get("BOT_ALERTS_DB_PATH")
    if env:
        return env
    backend_root = Path(__file__).resolve().parents[3]
    data_dir = backend_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "alerts.db")


def connect_alerts_db(db_path: str | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the alert log. Safe to call from several processes."""
    conn = sqlite3.connect(db_path or default_alerts_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


@dataclass(frozen=True)
class AlertRow:
    id: int
    run_id: int | None
    source: str
    ts_utc: str
    level: str
    code: str
    title: str
    body: dict[str, Any]
    dedupe_key: str
    sent_telegram: bool
    telegram_status: str
    read: bool


def _row(row: sqlite3.Row) -> AlertRow:
    try:
        body = json.loads(row["body_json"])
    except (ValueError, TypeError):
        body = {}
    return AlertRow(
        id=int(row["id"]),
        run_id=None if row["run_id"] is None else int(row["run_id"]),
        source=str(row["source"]),
        ts_utc=str(row["ts_utc"]),
        level=str(row["level"]),
        code=str(row["code"]),
        title=str(row["title"]),
        body=body if isinstance(body, dict) else {"value": body},
        dedupe_key=str(row["dedupe_key"]),
        sent_telegram=bool(row["sent_telegram"]),
        telegram_status=str(row["telegram_status"]),
        read=bool(row["read"]),
    )


def insert_alert(
    conn: sqlite3.Connection,
    *,
    run_id: int | None,
    source: str,
    ts_utc: str,
    level: str,
    code: str,
    title: str,
    body: dict[str, Any],
    dedupe_key: str = "",
    telegram_status: str = TELEGRAM_PENDING,
) -> int:
    cur = conn.execute(
        "INSERT INTO alert(run_id, source, ts_utc, level, code, title, body_json, "
        "dedupe_key, sent_telegram, telegram_status, read) VALUES (?,?,?,?,?,?,?,?,0,?,0)",
        (
            run_id,
            source,
            ts_utc,
            level,
            code,
            title,
            json.dumps(body, default=str, sort_keys=True),
            dedupe_key,
            telegram_status,
        ),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def set_telegram_status(conn: sqlite3.Connection, alert_id: int, status: str) -> None:
    conn.execute(
        "UPDATE alert SET telegram_status=?, sent_telegram=? WHERE id=?",
        (status, 1 if status == TELEGRAM_SENT else 0, alert_id),
    )
    conn.commit()


def last_telegram_sent_ts(conn: sqlite3.Connection, code: str, dedupe_key: str) -> str | None:
    """Timestamp of the most recent alert of this (code, key) that actually reached
    Telegram — the anchor the cooldown window is measured from. Suppressed and failed
    rows deliberately do not count: a suppressed row must not extend its own cooldown,
    and a failed one was never delivered, so the user has not been told yet."""
    cur = conn.execute(
        "SELECT ts_utc FROM alert WHERE code=? AND dedupe_key=? AND telegram_status IN (?, ?) "
        "ORDER BY id DESC LIMIT 1",
        (code, dedupe_key, TELEGRAM_SENT, TELEGRAM_LOGGED),
    )
    row = cur.fetchone()
    return None if row is None else str(row[0])


def failed_deliveries(conn: sqlite3.Connection, limit: int) -> list[AlertRow]:
    """Oldest-first alerts whose Telegram delivery failed, for the retry-on-next-emit
    pass. Bounded so a long outage cannot turn one emit into a thousand HTTP calls."""
    cur = conn.execute(
        "SELECT * FROM alert WHERE telegram_status=? ORDER BY id ASC LIMIT ?",
        (TELEGRAM_FAILED, limit),
    )
    return [_row(r) for r in cur.fetchall()]


def list_alerts(
    conn: sqlite3.Connection,
    since_id: int | None = None,
    level: str | None = None,
    limit: int = 100,
    unread_only: bool = False,
) -> list[AlertRow]:
    """Newest first. `since_id` means "strictly newer than this id" — the frontend's
    poll cursor."""
    query = "SELECT * FROM alert WHERE 1=1"
    params: list[Any] = []
    if since_id is not None:
        query += " AND id > ?"
        params.append(since_id)
    if level:
        query += " AND level = ?"
        params.append(level)
    if unread_only:
        query += " AND read = 0"
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    return [_row(r) for r in conn.execute(query, params).fetchall()]


def unread_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM alert WHERE read = 0").fetchone()[0])


def max_alert_id(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM alert").fetchone()[0])


def mark_read(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Mark the given ids read; returns how many rows changed. Empty list = no-op
    (NOT "mark everything", which is the kind of default that loses a CRITICAL)."""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(f"UPDATE alert SET read=1 WHERE id IN ({placeholders})", tuple(ids))
    conn.commit()
    return cur.rowcount
