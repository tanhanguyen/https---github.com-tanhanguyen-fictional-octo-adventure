"""Copy the single run of a worker's temp DB into the sweep's main DB.

`--workers N` gives each combo its own sqlite file (plan 11 §1: "mỗi worker một DB tạm
... rồi merge dòng kết quả về DB chính -- tránh tranh chấp write SQLite"). The rows still
have to end up in the real registry, or the sweep table could not link to a Report page,
so this module re-inserts them with remapped ids.

The only subtlety is the `trade <-> decision` cycle: `trade.decision_id` points at the
decision that created it and `decision.trade_id` points back. Trades therefore go in
first with a NULL `decision_id`, decisions follow using the trade map, and the trade
back-references are patched afterwards -- the same order `RunnerService.delete_run` uses
to break the cycle from the other end.
"""

from __future__ import annotations

import sqlite3
from typing import Any

#: Copied verbatim except for the id columns this module remaps.
_TRADE_COLUMNS = [
    "symbol", "strategy", "direction", "status", "entry_price", "sl_price", "tp1_price",
    "tp2_price", "lot_size", "opened_at_utc", "closed_at_utc", "trading_day", "result",
    "pnl_amount", "pnl_r", "timeframe", "range_high", "range_low",
]
_DECISION_COLUMNS = ["bar_ts_utc", "reason", "stage", "detail", "strategy", "direction", "symbol"]
_DECISION_FILTER_COLUMNS = [
    "filter_id", "kind", "enabled", "evaluated", "passed", "blocking", "values_json", "detail",
]
_ACCOUNT_STATE_COLUMNS = [
    "equity", "balance", "open_trades", "daily_loss_count", "consecutive_wins",
    "consecutive_losses", "current_trading_day", "risk_multiplier", "bot_enabled",
    "blocked_reason",
]
_BREAKOUT_STATE_COLUMNS = [
    "status", "direction", "range_high", "range_low", "breakout_bar_ts_utc", "bars_waited",
]

_CHUNK = 5000


def merge_single_run(dst: sqlite3.Connection, src_path: str) -> tuple[int, int]:
    """Import the one run held in `src_path` into `dst`. Returns (run_id, config_version_id)
    in the DESTINATION. All-or-nothing: any failure rolls back, so a half-imported run can
    never be committed by an unrelated later commit on the shared connection."""
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    try:
        run = src.execute("SELECT * FROM run ORDER BY id LIMIT 1").fetchone()
        if run is None:
            raise ValueError(f"{src_path}: no run to merge")
        cv = src.execute(
            "SELECT * FROM config_version WHERE id=?", (run["config_version_id"],)
        ).fetchone()
        if cv is None:  # pragma: no cover - the FK makes this impossible
            raise ValueError(f"{src_path}: run {run['id']} has no config_version")
        try:
            new_run_id, new_cv_id = _copy(dst, src, run, cv)
        except Exception:
            dst.rollback()
            raise
        dst.commit()
        return new_run_id, new_cv_id
    finally:
        src.close()


def _copy(
    dst: sqlite3.Connection, src: sqlite3.Connection, run: sqlite3.Row, cv: sqlite3.Row
) -> tuple[int, int]:
    old_run_id = int(run["id"])

    next_version = int(
        dst.execute("SELECT COALESCE(MAX(version), 0) FROM config_version").fetchone()[0]
    ) + 1
    cur = dst.execute(
        "INSERT INTO config_version(version, config_json, is_active, created_at_utc, note) "
        "VALUES (?, ?, 0, ?, ?)",
        (next_version, cv["config_json"], cv["created_at_utc"], cv["note"]),
    )
    new_cv_id = _rowid(cur)

    cur = dst.execute(
        "INSERT INTO run(dataset_id, config_version_id, symbol, status, starting_equity, "
        "created_at_utc, symbols_json, news_snapshot_max_id, mode) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run["dataset_id"],
            new_cv_id,
            run["symbol"],
            run["status"],
            run["starting_equity"],
            run["created_at_utc"],
            run["symbols_json"],
            run["news_snapshot_max_id"],
            run["mode"],
        ),
    )
    new_run_id = _rowid(cur)

    dst.executemany(
        "INSERT INTO run_symbol_dataset(run_id, symbol, dataset_id) VALUES (?,?,?)",
        [
            (new_run_id, r["symbol"], r["dataset_id"])
            for r in src.execute(
                "SELECT * FROM run_symbol_dataset WHERE run_id=?", (old_run_id,)
            )
        ],
    )
    _copy_singleton(dst, src, "account_state", _ACCOUNT_STATE_COLUMNS, old_run_id, new_run_id)
    _copy_singleton(dst, src, "breakout_state", _BREAKOUT_STATE_COLUMNS, old_run_id, new_run_id)

    trade_map: dict[int, int] = {}
    for row in src.execute("SELECT * FROM trade WHERE run_id=? ORDER BY id", (old_run_id,)):
        cur = dst.execute(
            f"INSERT INTO trade(run_id, {', '.join(_TRADE_COLUMNS)}, decision_id) "
            f"VALUES (?{', ?' * len(_TRADE_COLUMNS)}, NULL)",
            (new_run_id, *(row[c] for c in _TRADE_COLUMNS)),
        )
        trade_map[int(row["id"])] = _rowid(cur)

    decision_map: dict[int, int] = {}
    for row in src.execute("SELECT * FROM decision WHERE run_id=? ORDER BY id", (old_run_id,)):
        old_trade = row["trade_id"]
        cur = dst.execute(
            f"INSERT INTO decision(run_id, {', '.join(_DECISION_COLUMNS)}, trade_id) "
            f"VALUES (?{', ?' * len(_DECISION_COLUMNS)}, ?)",
            (
                new_run_id,
                *(row[c] for c in _DECISION_COLUMNS),
                None if old_trade is None else trade_map[int(old_trade)],
            ),
        )
        decision_map[int(row["id"])] = _rowid(cur)

    for row in src.execute(
        "SELECT id, decision_id FROM trade WHERE run_id=? AND decision_id IS NOT NULL",
        (old_run_id,),
    ):
        dst.execute(
            "UPDATE trade SET decision_id=? WHERE id=?",
            (decision_map[int(row["decision_id"])], trade_map[int(row["id"])]),
        )

    _copy_chunked(
        dst,
        src.execute(
            "SELECT df.* FROM decision_filter df JOIN decision d ON d.id=df.decision_id "
            "WHERE d.run_id=? ORDER BY df.id",
            (old_run_id,),
        ),
        f"INSERT INTO decision_filter(decision_id, {', '.join(_DECISION_FILTER_COLUMNS)}) "
        f"VALUES (?{', ?' * len(_DECISION_FILTER_COLUMNS)})",
        lambda r: (decision_map[int(r["decision_id"])], *(r[c] for c in _DECISION_FILTER_COLUMNS)),
    )
    _copy_chunked(
        dst,
        src.execute(
            "SELECT te.* FROM trade_event te JOIN trade t ON t.id=te.trade_id "
            "WHERE t.run_id=? ORDER BY te.id",
            (old_run_id,),
        ),
        "INSERT INTO trade_event(trade_id, event_type, ts_utc, price, detail) VALUES (?,?,?,?,?)",
        lambda r: (
            trade_map[int(r["trade_id"])], r["event_type"], r["ts_utc"], r["price"], r["detail"]
        ),
    )
    _copy_chunked(
        dst,
        src.execute("SELECT * FROM equity_point WHERE run_id=? ORDER BY id", (old_run_id,)),
        "INSERT INTO equity_point(run_id, bar_ts_utc, equity, balance) VALUES (?,?,?,?)",
        lambda r: (new_run_id, r["bar_ts_utc"], r["equity"], r["balance"]),
    )
    return new_run_id, new_cv_id


def _copy_singleton(
    dst: sqlite3.Connection,
    src: sqlite3.Connection,
    table: str,
    columns: list[str],
    old_run_id: int,
    new_run_id: int,
) -> None:
    row = src.execute(f"SELECT * FROM {table} WHERE run_id=?", (old_run_id,)).fetchone()
    if row is None:  # pragma: no cover - created_run always writes both
        return
    dst.execute(
        f"INSERT INTO {table}(run_id, {', '.join(columns)}) "
        f"VALUES (?{', ?' * len(columns)})",
        (new_run_id, *(row[c] for c in columns)),
    )


def _copy_chunked(
    dst: sqlite3.Connection,
    cursor: sqlite3.Cursor,
    sql: str,
    to_params: Any,
) -> None:
    """`decision_filter` is ~16 rows per bar — a 6000-bar run is ~100k rows. Stream it in
    chunks instead of materialising the whole list in memory."""
    while True:
        rows = cursor.fetchmany(_CHUNK)
        if not rows:
            return
        dst.executemany(sql, [to_params(r) for r in rows])


def _rowid(cur: sqlite3.Cursor) -> int:
    assert cur.lastrowid is not None
    return cur.lastrowid
