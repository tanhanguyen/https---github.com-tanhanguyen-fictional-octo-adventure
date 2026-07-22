"""News calendar import (plan 06): standardized CSV -> `news_event` table (append-only,
dedupe by (ts_utc, currency, title)), and loading the sorted lookup index the `news`
filter reads from `FilterContext`. Pure data types + the O(log n) lookup live in
`bot.core.types` (NewsEvent/NewsEventsIndex) so filters stay I/O-free; this module is
where the actual file/DB I/O happens, called once per run by `bot.engine.runner`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bot.core.errors import ConfigError
from bot.core.types import IMPACT_RANK, NewsEvent, NewsEventsIndex
from bot.db import repositories as repo

REQUIRED_COLUMNS = {"ts_utc", "currency", "impact", "title"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class NewsImportResult:
    file_sha256: str
    row_count: int
    inserted_count: int
    duplicate_count: int


def _parse_ts(raw: object) -> datetime:
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise ConfigError(f"news import: invalid ts_utc {raw!r} (expected ISO 8601)") from exc
    if ts.tzinfo is None:
        raise ConfigError(f"news import: ts_utc {raw!r} must be timezone-aware (UTC)")
    return ts


def import_news_csv(conn: sqlite3.Connection, path: Path) -> NewsImportResult:
    """Standard-format CSV -> `news_event` (idempotent: re-importing the same rows is a
    no-op via the dedupe unique index). Use `scripts/convert_news.py` first to turn a raw
    ForexFactory export into this standard format."""
    file_sha = sha256_file(path)
    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ConfigError(f"news CSV {path}: missing columns {sorted(missing)}")

    inserted = 0
    duplicate = 0
    for row in df.itertuples(index=False):
        ts = _parse_ts(row.ts_utc)
        impact = str(row.impact).strip().lower()
        if impact not in IMPACT_RANK:
            raise ConfigError(
                f"news CSV {path}: unknown impact {row.impact!r} (expected low/medium/high)"
            )
        currency = str(row.currency).strip().upper()
        title = str(row.title).strip()
        was_inserted = repo.insert_news_event(
            conn, ts.astimezone(timezone.utc).isoformat(), currency, impact, title, file_sha
        )
        if was_inserted:
            inserted += 1
        else:
            duplicate += 1
    conn.commit()
    return NewsImportResult(
        file_sha256=file_sha,
        row_count=len(df),
        inserted_count=inserted,
        duplicate_count=duplicate,
    )


def load_news_events_index(conn: sqlite3.Connection, max_id: int) -> NewsEventsIndex:
    rows = repo.list_news_events_upto(conn, max_id)
    return NewsEventsIndex(
        events=[
            NewsEvent(
                ts_utc=datetime.fromisoformat(r["ts_utc"]),
                currency=r["currency"],
                impact=r["impact"],
                title=r["title"],
            )
            for r in rows
        ]
    )
