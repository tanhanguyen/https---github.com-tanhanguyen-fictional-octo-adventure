"""Sweep worker process: one combo -> one temp sqlite file the parent merges.

Why a temp DB per combo instead of writing to the shared file: sqlite serialises writers
per database, and the engine commits on essentially every insert (one decision + ~16
decision_filter rows per bar), so N processes on one file would spend their time in
`SQLITE_BUSY` retries rather than in the engine. Per-combo files also mean a crashed
worker leaves nothing half-written in the real registry.

The temp DB is seeded with the `dataset` and `news_event` rows because the engine reads
both: `create_run` freezes `news_snapshot_max_id` from `MAX(news_event.id)`, so a worker
DB without those rows would silently run with the news filter seeing nothing — and the
parallel result would differ from the sequential one. Ids are copied verbatim to keep
that snapshot identical.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from bot.config.models import BotConfig
from bot.db.connection import connect_and_migrate
from bot.research.execute import SweepContext, build_sweep_context, run_combo
from bot.research.spec import SweepSpec
from bot.research.windows import to_utc, window_frames


@dataclass(frozen=True)
class InitPayload:
    db_path: str
    spec: SweepSpec
    base_config_json: str


@dataclass(frozen=True)
class Task:
    combo_index: int
    params: dict[str, Any]
    window_from: str
    window_to: str
    note: str
    tmp_db: str


@dataclass(frozen=True)
class Outcome:
    combo_index: int
    params: dict[str, Any]
    metrics: dict[str, Any]
    decision_hash: str
    n_bars: int
    tmp_db: str


#: Process-global, built once per worker: loading a 100k-bar CSV bundle per combo would
#: dominate the runtime of the whole sweep.
_STATE: dict[str, Any] = {}


def init(payload: InitPayload) -> None:
    source = sqlite3.connect(payload.db_path)
    source.row_factory = sqlite3.Row
    try:
        ctx = build_sweep_context(
            source, payload.spec, BotConfig.model_validate_json(payload.base_config_json)
        )
        _STATE["ctx"] = ctx
        _STATE["datasets"] = [dict(r) for r in source.execute("SELECT * FROM dataset")]
        _STATE["news"] = [dict(r) for r in source.execute("SELECT * FROM news_event ORDER BY id")]
    finally:
        source.close()


def execute(task: Task) -> Outcome:
    ctx: SweepContext = _STATE["ctx"]
    window = window_frames(
        ctx.bundle.price, ctx.primary_tf, to_utc(task.window_from), to_utc(task.window_to)
    )
    conn = connect_and_migrate(task.tmp_db)
    try:
        _seed(conn)
        result = run_combo(conn, ctx, window, task.params, task.combo_index, task.note)
    finally:
        conn.close()
    return Outcome(
        combo_index=result.combo_index,
        params=result.params,
        metrics=result.metrics,
        decision_hash=result.decision_hash,
        n_bars=result.n_bars,
        tmp_db=task.tmp_db,
    )


def _seed(conn: sqlite3.Connection) -> None:
    for row in _STATE["datasets"]:
        _insert(conn, "dataset", row)
    for row in _STATE["news"]:
        _insert(conn, "news_event", row)
    conn.commit()


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    cols = list(row)
    conn.execute(
        f"INSERT OR IGNORE INTO {table}({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})",
        [row[c] for c in cols],
    )
