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


def find_dataset_by_sha256(conn: sqlite3.Connection, file_sha256: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM dataset WHERE file_sha256 = ?", (file_sha256,))
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
    dataset_id: str,
    config_version_id: int,
    symbol: str,
    starting_equity: float,
) -> int:
    cur = conn.execute(
        "INSERT INTO run(dataset_id, config_version_id, symbol, status, starting_equity, "
        "created_at_utc) VALUES (?, ?, ?, 'RUNNING', ?, datetime('now'))",
        (dataset_id, config_version_id, symbol, starting_equity),
    )
    conn.execute(
        "INSERT INTO account_state(run_id, equity, balance, open_trades, daily_loss_count, "
        "consecutive_wins, consecutive_losses, risk_multiplier, bot_enabled) "
        "VALUES (?, ?, ?, 0, 0, 0, 0, 1.0, 1)",
        (cur.lastrowid, starting_equity, starting_equity),
    )
    conn.execute(
        "INSERT INTO breakout_state(run_id, status, bars_waited) VALUES (?, 'NONE', 0)",
        (cur.lastrowid,),
    )
    conn.commit()
    return _lastrowid(cur)


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


def insert_trade(conn: sqlite3.Connection, t: TradeRecord) -> int:
    cur = conn.execute(
        "INSERT INTO trade(run_id, symbol, strategy, direction, status, entry_price, "
        "sl_price, tp1_price, tp2_price, lot_size, opened_at_utc, closed_at_utc, "
        "trading_day, result, pnl_amount, pnl_r, decision_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
) -> int:
    cur = conn.execute(
        "INSERT INTO decision(run_id, bar_ts_utc, reason, stage, detail, strategy, "
        "direction, trade_id) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, bar_ts_utc, reason, stage, detail, strategy, direction, trade_id),
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
