"""Thin repository layer over sqlite3. No business logic -- engine calls these.

Derived counters (plan: `account_state` is a CACHE, `trade` table is the source of
truth): `daily_loss_count` / `consecutive_losses` are always computed here from
`trade`, never accumulated in place, so the mutate-and-drift bug class is structurally
impossible.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


def _lastrowid(cur: sqlite3.Cursor) -> int:
    assert cur.lastrowid is not None
    return cur.lastrowid


# ---------------------------------------------------------------------------
# config_version: immutable versioned snapshots (PATCH -> merge -> validate -> new
# version -> activate).
# ---------------------------------------------------------------------------


def create_config_version(
    conn: sqlite3.Connection, config_json: str, note: str = "", activate: bool = True
) -> int:
    cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM config_version")
    next_version = cur.fetchone()[0] + 1
    if activate:
        conn.execute("UPDATE config_version SET is_active = 0")
    cur = conn.execute(
        "INSERT INTO config_version(version, config_json, is_active, created_at_utc, note) "
        "VALUES (?, ?, ?, datetime('now'), ?)",
        (next_version, config_json, 1 if activate else 0, note),
    )
    conn.commit()
    return _lastrowid(cur)


def get_active_config_version(conn: sqlite3.Connection) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM config_version WHERE is_active = 1 LIMIT 1")
    row: sqlite3.Row | None = cur.fetchone()
    return row


def activate_config_version(conn: sqlite3.Connection, config_version_id: int) -> None:
    conn.execute("UPDATE config_version SET is_active = 0")
    conn.execute("UPDATE config_version SET is_active = 1 WHERE id = ?", (config_version_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# dataset / run
# ---------------------------------------------------------------------------


def upsert_dataset(conn: sqlite3.Connection, dataset_id: str, spec_json: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO dataset(id, spec_json, created_at_utc, kind) "
        "VALUES (?, ?, datetime('now'), 'synthetic')",
        (dataset_id, spec_json),
    )
    conn.commit()


def get_dataset(conn: sqlite3.Connection, dataset_id: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM dataset WHERE id = ?", (dataset_id,))
    row: sqlite3.Row | None = cur.fetchone()
    return row


def register_csv_dataset(
    conn: sqlite3.Connection,
    dataset_id: str,
    source_path: str,
    file_sha256: str,
    symbol: str,
    native_tf: str,
    start_ts: str,
    end_ts: str,
    bar_count: int,
    gap_count: int,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO dataset(id, spec_json, created_at_utc, kind, source_path, "
        "file_sha256, symbol, native_tf, start_ts, end_ts, bar_count, gap_count) "
        "VALUES (?, '{}', datetime('now'), 'csv', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dataset_id,
            source_path,
            file_sha256,
            symbol,
            native_tf,
            start_ts,
            end_ts,
            bar_count,
            gap_count,
        ),
    )
    conn.commit()


def create_run(
    conn: sqlite3.Connection,
    config_version_id: int,
    symbol_datasets: dict[str, str],
    starting_equity: float,
    mode: str = "backtest",
) -> int:
    """`symbol_datasets` maps each symbol in this (portfolio) run to its own dataset id
    (plan 04). `run.dataset_id`/`run.symbol` stay populated (first symbol alphabetically /
    comma-joined) for backward-compatible display; `run_symbol_dataset` is the real
    per-symbol source of truth.

    `news_snapshot_max_id` (plan 06) freezes the news_event id high-water mark at run
    creation: events are append-only, so a run only ever sees events that existed when it
    was created -- importing a new file later never changes an existing run's decisions."""
    symbols = sorted(symbol_datasets)
    primary_dataset_id = symbol_datasets[symbols[0]]
    news_snapshot_max_id = int(
        conn.execute("SELECT COALESCE(MAX(id), 0) FROM news_event").fetchone()[0]
    )
    cur = conn.execute(
        "INSERT INTO run(dataset_id, config_version_id, symbol, status, starting_equity, "
        "created_at_utc, symbols_json, news_snapshot_max_id, mode) "
        "VALUES (?, ?, ?, 'RUNNING', ?, datetime('now'), ?, ?, ?)",
        (
            primary_dataset_id,
            config_version_id,
            ",".join(symbols),
            starting_equity,
            json.dumps(symbols),
            news_snapshot_max_id,
            mode,
        ),
    )
    run_id = _lastrowid(cur)
    for sym in symbols:
        conn.execute(
            "INSERT INTO run_symbol_dataset(run_id, symbol, dataset_id) VALUES (?, ?, ?)",
            (run_id, sym, symbol_datasets[sym]),
        )
    conn.execute(
        "INSERT INTO account_state(run_id, equity, balance, open_trades, daily_loss_count, "
        "consecutive_wins, consecutive_losses, risk_multiplier, bot_enabled) "
        "VALUES (?, ?, ?, 0, 0, 0, 0, 1.0, 1)",
        (run_id, starting_equity, starting_equity),
    )
    conn.execute(
        "INSERT INTO breakout_state(run_id, status, bars_waited) VALUES (?, 'NONE', 0)",
        (run_id,),
    )
    conn.commit()
    return run_id


def get_run_symbol_datasets(conn: sqlite3.Connection, run_id: int) -> dict[str, str]:
    cur = conn.execute(
        "SELECT symbol, dataset_id FROM run_symbol_dataset WHERE run_id=?", (run_id,)
    )
    return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# trade / trade_event
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    run_id: int
    symbol: str
    strategy: str
    direction: str
    status: str
    entry_price: float | None = None
    sl_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None
    lot_size: float | None = None
    opened_at_utc: str | None = None
    closed_at_utc: str | None = None
    trading_day: str | None = None
    result: str | None = None
    pnl_amount: float | None = None
    pnl_r: float | None = None
    decision_id: int | None = None
    # Plan 07: the timeframe this trade was opened on, snapshotted so the hold rules
    # (TF <= H1 vs TF > H1) stay auditable when the config changes later.
    timeframe: str | None = None
    # Plan 14: the breakout range at signal time (None for mean reversion), snapshotted
    # here so an on-demand chart render can redraw it later (see migration 006).
    range_high: float | None = None
    range_low: float | None = None


def insert_trade(conn: sqlite3.Connection, t: TradeRecord) -> int:
    cur = conn.execute(
        "INSERT INTO trade(run_id, symbol, strategy, direction, status, entry_price, "
        "sl_price, tp1_price, tp2_price, lot_size, opened_at_utc, closed_at_utc, "
        "trading_day, result, pnl_amount, pnl_r, decision_id, timeframe, "
        "range_high, range_low) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            t.run_id,
            t.symbol,
            t.strategy,
            t.direction,
            t.status,
            t.entry_price,
            t.sl_price,
            t.tp1_price,
            t.tp2_price,
            t.lot_size,
            t.opened_at_utc,
            t.closed_at_utc,
            t.trading_day,
            t.result,
            t.pnl_amount,
            t.pnl_r,
            t.decision_id,
            t.timeframe,
            t.range_high,
            t.range_low,
        ),
    )
    conn.commit()
    return _lastrowid(cur)


def update_trade(conn: sqlite3.Connection, trade_id: int, **fields: object) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE trade SET {cols} WHERE id = ?", (*fields.values(), trade_id))
    conn.commit()


def insert_trade_event(
    conn: sqlite3.Connection,
    trade_id: int,
    event_type: str,
    ts_utc: str,
    price: float | None = None,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO trade_event(trade_id, event_type, ts_utc, price, detail) VALUES (?,?,?,?,?)",
        (trade_id, event_type, ts_utc, price, detail),
    )
    conn.commit()


def count_open_trades(conn: sqlite3.Connection, run_id: int) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) FROM trade WHERE run_id = ? AND status IN ('PENDING','OPEN')",
        (run_id,),
    )
    return int(cur.fetchone()[0])


def daily_loss_count(conn: sqlite3.Connection, run_id: int, trading_day_str: str) -> int:
    """C4/D8: LOSS + BREAKEVEN both count."""
    cur = conn.execute(
        "SELECT COUNT(*) FROM trade WHERE run_id=? AND trading_day=? AND result IN "
        "('LOSS','BREAKEVEN')",
        (run_id, trading_day_str),
    )
    return int(cur.fetchone()[0])


def consecutive_losses(conn: sqlite3.Connection, run_id: int) -> int:
    """D8: BREAKEVEN treated as a loss for streak purposes."""
    cur = conn.execute(
        "SELECT result FROM trade WHERE run_id=? AND status='CLOSED' AND result IS NOT NULL "
        "ORDER BY closed_at_utc DESC",
        (run_id,),
    )
    count = 0
    for (result,) in cur.fetchall():
        if result in ("LOSS", "BREAKEVEN"):
            count += 1
        else:
            break
    return count


def consecutive_wins(conn: sqlite3.Connection, run_id: int) -> int:
    cur = conn.execute(
        "SELECT result FROM trade WHERE run_id=? AND status='CLOSED' AND result IS NOT NULL "
        "ORDER BY closed_at_utc DESC",
        (run_id,),
    )
    count = 0
    for (result,) in cur.fetchall():
        if result == "WIN":
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# decision / decision_filter
# ---------------------------------------------------------------------------


def insert_decision(
    conn: sqlite3.Connection,
    run_id: int,
    bar_ts_utc: str,
    reason: str,
    stage: str,
    detail: str,
    strategy: str | None,
    direction: str | None,
    trade_id: int | None,
    symbol: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO decision(run_id, bar_ts_utc, reason, stage, detail, strategy, "
        "direction, trade_id, symbol) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, bar_ts_utc, reason, stage, detail, strategy, direction, trade_id, symbol),
    )
    conn.commit()
    return _lastrowid(cur)


def insert_decision_filter(
    conn: sqlite3.Connection,
    decision_id: int,
    filter_id: str,
    kind: str,
    enabled: bool,
    evaluated: bool,
    passed: bool | None,
    blocking: bool,
    values: dict[str, Any],
    detail: str,
) -> None:
    conn.execute(
        "INSERT INTO decision_filter(decision_id, filter_id, kind, enabled, evaluated, "
        "passed, blocking, values_json, detail) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            decision_id,
            filter_id,
            kind,
            int(enabled),
            int(evaluated),
            None if passed is None else int(passed),
            int(blocking),
            json.dumps(values, default=str),
            detail,
        ),
    )


# ---------------------------------------------------------------------------
# account_state cache / breakout_state / equity_point
# ---------------------------------------------------------------------------


def update_account_state(conn: sqlite3.Connection, run_id: int, **fields: object) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE account_state SET {cols} WHERE run_id = ?", (*fields.values(), run_id))
    conn.commit()


def get_account_state(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM account_state WHERE run_id = ?", (run_id,))
    row: sqlite3.Row | None = cur.fetchone()
    return row


def update_breakout_state(conn: sqlite3.Connection, run_id: int, **fields: object) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE breakout_state SET {cols} WHERE run_id = ?", (*fields.values(), run_id))
    conn.commit()


def get_breakout_state(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM breakout_state WHERE run_id = ?", (run_id,))
    row: sqlite3.Row | None = cur.fetchone()
    return row


def insert_equity_point(
    conn: sqlite3.Connection, run_id: int, bar_ts_utc: str, equity: float, balance: float
) -> None:
    conn.execute(
        "INSERT INTO equity_point(run_id, bar_ts_utc, equity, balance) VALUES (?,?,?,?)",
        (run_id, bar_ts_utc, equity, balance),
    )
    conn.commit()


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _day(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# Live paper trading (plan 07): run mode / stop flag / strategy state / feed status.
# ---------------------------------------------------------------------------


def upsert_live_dataset(conn: sqlite3.Connection, dataset_id: str, symbol: str, tf: str) -> None:
    """A live 'dataset' is the venue stream itself: there is no file to hash, but `run`
    has an FK to `dataset`, and naming the stream keeps a live run's provenance
    (venue/symbol/timeframe) readable in the run registry."""
    conn.execute(
        "INSERT OR IGNORE INTO dataset(id, spec_json, created_at_utc, kind, symbol, native_tf) "
        "VALUES (?, '{}', datetime('now'), 'live', ?, ?)",
        (dataset_id, symbol, tf),
    )
    conn.commit()


def find_active_live_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The most recent RUNNING run with mode='live' — what a restarted LiveRunner
    resumes. There is at most one in practice (a live DB holds one live run at a time);
    picking the newest keeps the choice deterministic if an older one was left RUNNING."""
    cur = conn.execute(
        "SELECT * FROM run WHERE mode='live' AND status='RUNNING' ORDER BY id DESC LIMIT 1"
    )
    row: sqlite3.Row | None = cur.fetchone()
    return row


def set_run_status(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    conn.execute("UPDATE run SET status=? WHERE id=?", (status, run_id))
    conn.commit()


def request_stop(conn: sqlite3.Connection, run_id: int, requested: bool = True) -> None:
    conn.execute("UPDATE run SET stop_requested=? WHERE id=?", (1 if requested else 0, run_id))
    conn.commit()


def stop_requested(conn: sqlite3.Connection, run_id: int) -> bool:
    cur = conn.execute("SELECT stop_requested FROM run WHERE id=?", (run_id,))
    row = cur.fetchone()
    return bool(row[0]) if row is not None else False


def save_strategy_state(
    conn: sqlite3.Connection, run_id: int, symbol: str, state_json: str, now_iso: str
) -> None:
    conn.execute(
        "INSERT INTO strategy_state(run_id, symbol, state_json, updated_at_utc) "
        "VALUES (?,?,?,?) ON CONFLICT(run_id, symbol) DO UPDATE SET "
        "state_json=excluded.state_json, updated_at_utc=excluded.updated_at_utc",
        (run_id, symbol, state_json, now_iso),
    )
    conn.commit()


def load_strategy_states(conn: sqlite3.Connection, run_id: int) -> dict[str, str]:
    cur = conn.execute("SELECT symbol, state_json FROM strategy_state WHERE run_id=?", (run_id,))
    return {str(row[0]): str(row[1]) for row in cur.fetchall()}


def update_live_status(conn: sqlite3.Connection, run_id: int, **fields: object) -> None:
    """Upsert the live_status row for `run_id` (created on first call)."""
    conn.execute("INSERT OR IGNORE INTO live_status(run_id) VALUES (?)", (run_id,))
    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE live_status SET {cols} WHERE run_id = ?", (*fields.values(), run_id))
    conn.commit()


def get_live_status(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM live_status WHERE run_id=?", (run_id,))
    row: sqlite3.Row | None = cur.fetchone()
    return row


def decision_exists(conn: sqlite3.Connection, run_id: int, symbol: str, bar_ts_utc: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM decision WHERE run_id=? AND symbol=? AND bar_ts_utc=? LIMIT 1",
        (run_id, symbol, bar_ts_utc),
    )
    return cur.fetchone() is not None


def get_trade(conn: sqlite3.Connection, trade_id: int) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM trade WHERE id=?", (trade_id,))
    row: sqlite3.Row | None = cur.fetchone()
    return row


def signal_decision_for_trade(conn: sqlite3.Connection, trade_id: int) -> sqlite3.Row | None:
    """Plan 14: the `done`/`place_order` decision that created this trade — its
    `bar_ts_utc` is the signal bar, used as the snapshot's signal marker. `ORDER BY id
    ASC LIMIT 1` because `trade_id` is unique to the tick that created the PENDING row."""
    cur = conn.execute(
        "SELECT * FROM decision WHERE trade_id=? AND reason='done' ORDER BY id ASC LIMIT 1",
        (trade_id,),
    )
    row: sqlite3.Row | None = cur.fetchone()
    return row


def open_trades_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM trade WHERE run_id=? AND status IN ('PENDING','OPEN') ORDER BY id",
        (run_id,),
    )
    return list(cur.fetchall())


# ---------------------------------------------------------------------------
# news_event (plan 06): append-only, dedupe on (ts_utc, currency, title).
# ---------------------------------------------------------------------------


def insert_news_event(
    conn: sqlite3.Connection,
    ts_utc: str,
    currency: str,
    impact: str,
    title: str,
    source_file_sha256: str,
) -> bool:
    """Returns True if a new row was inserted, False if it was a duplicate."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO news_event(ts_utc, currency, impact, title, "
        "source_file_sha256, created_at_utc) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (ts_utc, currency, impact, title, source_file_sha256),
    )
    return cur.rowcount == 1


def list_news_events_upto(conn: sqlite3.Connection, max_id: int) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM news_event WHERE id <= ? ORDER BY ts_utc ASC", (max_id,))
    return list(cur.fetchall())


def list_news_events_range(
    conn: sqlite3.Connection, from_ts: str | None, to_ts: str | None
) -> list[sqlite3.Row]:
    query = "SELECT * FROM news_event WHERE 1=1"
    params: list[Any] = []
    if from_ts:
        query += " AND ts_utc >= ?"
        params.append(from_ts)
    if to_ts:
        query += " AND ts_utc <= ?"
        params.append(to_ts)
    query += " ORDER BY ts_utc ASC"
    cur = conn.execute(query, params)
    return list(cur.fetchall())
