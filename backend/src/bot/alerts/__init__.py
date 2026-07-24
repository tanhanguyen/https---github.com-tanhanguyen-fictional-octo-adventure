"""Alert center (plan 13): one event bus, three destinations — DB log, Telegram, web UI.

Nothing under `bot/engine`, `bot/filters`, `bot/strategies` or `bot/indicators` may
import this package (invariant #6, enforced by `test_dependency_direction`). Runners
emit through `bot.notify.LiveAlerts`; the composition root (`bot.cli`, the API layer)
decides that the transport behind it is `AlertBus`.
"""

from __future__ import annotations

import sqlite3

from bot.alerts.bus import AlertBus
from bot.alerts.codes import ALERT_CATALOGUE, ALL_CODES, Level, default_level, level_at_least
from bot.alerts.store import (
    AlertRow,
    connect_alerts_db,
    default_alerts_db_path,
    list_alerts,
    mark_read,
    unread_count,
)
from bot.config.models import AlertsConfig
from bot.core.wallclock import NowFn, utc_now
from bot.notify import LiveAlerts, Notifier, build_notifier

__all__ = [
    "ALERT_CATALOGUE",
    "ALL_CODES",
    "AlertBus",
    "AlertRow",
    "AlertsConfig",
    "Level",
    "build_live_alerts",
    "connect_alerts_db",
    "default_alerts_db_path",
    "default_level",
    "level_at_least",
    "list_alerts",
    "mark_read",
    "unread_count",
]


def build_live_alerts(
    alerts_conn: sqlite3.Connection,
    config: AlertsConfig | None = None,
    *,
    run_id: int | None = None,
    source: str = "live",
    notifier: Notifier | None = None,
    now_fn: NowFn = utc_now,
) -> LiveAlerts:
    """The wiring a runner wants: a `LiveAlerts` formatter backed by a real `AlertBus`.

    `notifier=None` means "build one from the environment" — which is the log-only sink
    when `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are unset, so a token-less deployment
    still gets every alert in the DB and on the web UI.
    """
    bus = AlertBus(
        alerts_conn,
        notifier if notifier is not None else build_notifier(),
        config,
        run_id=run_id,
        source=source,
        now_fn=now_fn,
    )
    return LiveAlerts(run_label=bus.run_label, emitter=bus)
