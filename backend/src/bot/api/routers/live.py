"""`GET /api/live/status` — is the live process alive, and how far behind is it?

The live runner writes to its OWN database (plan 07 §3), so this router opens that file
**read-only** rather than going through RunnerService. Two rules from the plan hold here:

* the API never writes to a live run — the single exception is `POST /api/live/stop`,
  which sets `run.stop_requested`, the flag LiveRunner checks once per loop;
* WAL mode lets this reader run concurrently with the live writer, so a status poll can
  never block a trading decision.

Missing DB / no live run is a normal answer (`running: false`), not an error: the
dashboard shows "no live run" instead of a red toast when nothing is running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from bot.api.schemas import LiveStatusOut
from bot.db import repositories as repo
from bot.engine.live_factory import default_live_db_path

router = APIRouter()


def _open_readonly(path: str) -> sqlite3.Connection | None:
    if not Path(path).exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _iso(value: object) -> str | None:
    return None if value is None else str(value)


def live_status(db_path: str | None = None) -> LiveStatusOut:
    path = db_path or default_live_db_path()
    conn = _open_readonly(path)
    if conn is None:
        return LiveStatusOut(running=False, db_path=path)
    try:
        try:
            run = repo.find_active_live_run(conn)
        except sqlite3.DatabaseError:
            # The live DB exists but has not been migrated yet (nothing has ever run).
            return LiveStatusOut(running=False, db_path=path)
        if run is None:
            return LiveStatusOut(running=False, db_path=path)
        run_id = int(run["id"])
        status_row = repo.get_live_status(conn, run_id)
        last_bar = _iso(status_row["last_bar_ts_utc"]) if status_row is not None else None
        started = _iso(status_row["started_at_utc"]) if status_row is not None else None
        now = datetime.now(timezone.utc)
        lag = (
            (now - datetime.fromisoformat(last_bar)).total_seconds()
            if last_bar is not None
            else None
        )
        uptime = (
            (now - datetime.fromisoformat(started)).total_seconds() if started is not None else None
        )
        account = repo.get_account_state(conn, run_id)
        return LiveStatusOut(
            running=True,
            db_path=path,
            run_id=run_id,
            symbols=str(run["symbol"]).split(","),
            feed_state=str(status_row["feed_state"]) if status_row is not None else "unknown",
            detail=str(status_row["detail"]) if status_row is not None else "",
            last_bar_ts_utc=last_bar,
            started_at_utc=started,
            lag_seconds=lag,
            uptime_seconds=uptime,
            stop_requested=bool(run["stop_requested"]),
            equity=float(account["equity"]) if account is not None else None,
            open_trades=int(account["open_trades"]) if account is not None else None,
        )
    finally:
        conn.close()


@router.get("/live/status", response_model=LiveStatusOut)
def get_live_status() -> LiveStatusOut:
    return live_status()


@router.post("/live/stop", response_model=LiveStatusOut)
def post_live_stop() -> LiveStatusOut:
    """Ask the live runner to stop after its current bar (the only write the API makes
    to a live run). Idempotent: asking twice is not an error."""
    path = default_live_db_path()
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="no live database")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        run = repo.find_active_live_run(conn)
        if run is None:
            raise HTTPException(status_code=404, detail="no active live run")
        repo.request_stop(conn, int(run["id"]))
    finally:
        conn.close()
    return live_status()
