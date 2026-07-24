"""`/api/alerts` — the web UI's half of the alert center (plan 13).

The frontend polls `GET /api/alerts?since_id=<cursor>` every few seconds and toasts
whatever is new; the bell dropdown reads the same endpoint without a cursor. There is no
push channel on purpose: polling a WAL-mode SQLite file costs nothing next to a
websocket's reconnect/auth surface, and an alert that arrives 10s late is still an alert.

This router is the one place the API *writes* to the alert log (marking rows read).
That is safe precisely because the alert log is its own database — see
`bot.alerts.store` for why it is not `live.db`.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query, Request

from bot.alerts import store
from bot.api.schemas import AlertListOut, AlertOut, AlertReadIn, AlertReadOut

router = APIRouter()

#: Hard ceiling on one page, so a forgotten `limit` cannot pull a year of alerts.
MAX_LIMIT = 500


def get_alerts_conn(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection = request.app.state.alerts_conn
    return conn


def _out(row: store.AlertRow) -> AlertOut:
    return AlertOut(
        id=row.id,
        run_id=row.run_id,
        source=row.source,
        ts_utc=row.ts_utc,
        level=row.level,
        code=row.code,
        title=row.title,
        body=row.body,
        sent_telegram=row.sent_telegram,
        telegram_status=row.telegram_status,
        read=row.read,
    )


@router.get("/alerts", response_model=AlertListOut)
def list_alerts(
    since_id: int | None = Query(None, ge=0),
    level: str | None = None,
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    unread_only: bool = False,
    conn: sqlite3.Connection = Depends(get_alerts_conn),
) -> AlertListOut:
    rows = store.list_alerts(
        conn, since_id=since_id, level=level, limit=limit, unread_only=unread_only
    )
    # `max_id` comes from the table, not from `rows`: with a `level` filter an empty page
    # still has to advance the cursor, or the client re-scans the same ids forever.
    return AlertListOut(
        alerts=[_out(r) for r in rows],
        unread=store.unread_count(conn),
        max_id=store.max_alert_id(conn),
    )


@router.post("/alerts/read", response_model=AlertReadOut)
def mark_alerts_read(
    body: AlertReadIn, conn: sqlite3.Connection = Depends(get_alerts_conn)
) -> AlertReadOut:
    """Idempotent: marking an already-read id is a no-op that still returns 200. An
    empty list marks nothing (it is NOT "mark all")."""
    marked = store.mark_read(conn, body.ids)
    return AlertReadOut(marked=marked, unread=store.unread_count(conn))
