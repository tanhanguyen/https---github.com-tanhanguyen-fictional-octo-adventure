"""`AlertBus` — the one fan-out point for every alert (plan 13).

`emit()` does three things, in this order and with this priority:

1. **The DB row is always written.** It is the source of truth and the backend log; the
   web UI polls it. Telegram being off, muted, throttled or broken changes the row's
   `telegram_status`, never whether the row exists.
2. **Telegram, if configured and allowed.** Below the level threshold, a muted code, or
   inside the cooldown window ⇒ the row is marked and no message goes out. `CRITICAL` is
   never throttled or muted — the whole point of the severity is that it always reaches
   a phone.
3. **The web UI needs nothing pushed.** It polls `GET /api/alerts?since_id=`.

**`emit()` never raises.** A runner calls it from inside its trading loop; an alert that
can crash the bot is worse than no alert at all. Every failure path here logs and
returns. That is why the broad `except Exception` below is deliberate and not a smell.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from bot.alerts import store
from bot.alerts.codes import ALL_CODES, default_level, level_at_least
from bot.config.models import AlertsConfig
from bot.core.wallclock import NowFn, utc_now
from bot.notify import AlertEvent, Notifier

logger = logging.getLogger("bot.alerts")

#: Most failed deliveries retried per emit. Bounds one emit's HTTP work after an outage.
MAX_RETRIES_PER_EMIT = 5


class AlertBus:
    """Fan-out: DB (always) + Telegram (conditionally). Satisfies `notify.AlertEmitter`.

    One bus per process. `run_id`/`source` tag every row it writes, so the alert log can
    say which run — and which *kind* of run — an alert came from even though it lives in
    its own database (see `bot.alerts.store`)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        notifier: Notifier | None = None,
        config: AlertsConfig | None = None,
        *,
        run_id: int | None = None,
        source: str = "",
        now_fn: NowFn = utc_now,
        run_label: str = "",
    ) -> None:
        self.conn = conn
        self.notifier = notifier
        self.config = config if config is not None else AlertsConfig()
        self.run_id = run_id
        self.source = source
        self.now_fn = now_fn
        self.run_label = run_label or (f"{source}#{run_id}" if run_id is not None else source)

    # ------------------------------------------------------------------ emit
    def emit(self, event: AlertEvent) -> None:
        try:
            self._emit(event)
        except Exception:  # noqa: BLE001 - an alert must never break its caller
            logger.exception("alert emit failed (code=%s) — swallowed", event.code)

    def _emit(self, event: AlertEvent) -> None:
        level = event.level or default_level(event.code)
        if event.code not in ALL_CODES:
            # Not fatal: log it and keep the alert. An uncatalogued code still deserves
            # to reach the operator; it just means `bot.alerts.codes` is out of date.
            logger.warning("alert code %r is not in the catalogue", event.code)
        now = self.now_fn()

        alert_id = store.insert_alert(
            self.conn,
            run_id=self.run_id,
            source=self.source,
            ts_utc=now.isoformat(),
            level=level,
            code=event.code,
            title=event.title,
            body=dict(event.body),
            dedupe_key=event.dedupe_key,
            telegram_status=store.TELEGRAM_PENDING,
        )

        status = self._telegram_status_for(event, level, now)
        if status is not None:
            store.set_telegram_status(self.conn, alert_id, status)
            return

        # Deliverable: clear the backlog first so the operator reads events in order,
        # then send this one.
        self._retry_failed()
        text = self._format(event, level)
        store.set_telegram_status(self.conn, alert_id, self._deliver(text))

    def _deliver(self, text: str) -> str:
        """Push one line at the notifier and translate the outcome into a status.

        The log-only fallback reports `logged`, not `sent`: it did its job, but the
        alert never left the machine, and a `sent_telegram` flag that lights up without
        a token would be a lie the UI repeats with an aeroplane icon."""
        if self.notifier is None:
            return store.TELEGRAM_MUTED
        if not self.notifier.send(text):
            return store.TELEGRAM_FAILED
        return store.TELEGRAM_SENT if self.notifier.remote else store.TELEGRAM_LOGGED

    def _telegram_status_for(self, event: AlertEvent, level: str, now: datetime) -> str | None:
        """The terminal `telegram_status` when this alert must NOT be sent, or None when
        it should be delivered."""
        critical = level == "CRITICAL"
        if self.notifier is None or not self.config.telegram_enabled:
            return store.TELEGRAM_MUTED
        if not critical:
            if event.code in self.config.telegram_muted_codes:
                return store.TELEGRAM_MUTED
            if not level_at_least(level, self.config.telegram_min_level):
                return store.TELEGRAM_MUTED
            if self._in_cooldown(event, now):
                return store.TELEGRAM_SUPPRESSED
        return None

    def _in_cooldown(self, event: AlertEvent, now: datetime) -> bool:
        window = self.config.cooldown_seconds
        if window <= 0:
            return False
        last = store.last_telegram_sent_ts(self.conn, event.code, event.dedupe_key)
        if last is None:
            return False
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return False
        return now - last_dt < timedelta(seconds=window)

    def _retry_failed(self) -> None:
        """Re-attempt previously failed deliveries, oldest first. Stops at the first
        failure: if the channel is still down, hammering it wastes the emit's time
        budget (and the row stays `failed`, so nothing is lost)."""
        if self.notifier is None:
            return
        for row in store.failed_deliveries(self.conn, MAX_RETRIES_PER_EMIT):
            # Labelled with the row's OWN run, not this bus's: the backlog can predate a
            # restart (or belong to the other kind of run entirely, since the alert log
            # is shared), and re-sending it under today's label would misattribute it.
            label = f"{row.source}#{row.run_id}" if row.run_id is not None else row.source
            status = self._deliver(f"[{label}] {row.level} {row.title} (gửi lại)")
            if status == store.TELEGRAM_FAILED:
                return
            store.set_telegram_status(self.conn, row.id, status)

    def _format(self, event: AlertEvent, level: str) -> str:
        prefix = f"[{self.run_label}] " if self.run_label else ""
        return f"{prefix}{level} {event.title}"
