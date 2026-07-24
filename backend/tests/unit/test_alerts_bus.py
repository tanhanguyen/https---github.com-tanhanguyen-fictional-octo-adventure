"""Plan 13 alert bus: fan-out, cooldown, and the promise that emit() cannot hurt you.

The invariant under test throughout is the priority order from the plan: the DB row is
written no matter what happens to Telegram, and CRITICAL is never throttled or muted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.alerts import store
from bot.alerts.bus import AlertBus
from bot.alerts.codes import ALL_CODES, default_level, level_at_least
from bot.config.models import AlertsConfig
from bot.notify import AlertEvent, LiveAlerts

START = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)


class FakeNotifier:
    """A Telegram stand-in. `fail` flips it into "channel is down" mode; nothing here
    ever touches a socket (plan 13: no test calls Telegram for real)."""

    remote = True

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text: str) -> bool:
        if self.fail:
            return False
        self.sent.append(text)
        return True


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def conn(tmp_path):
    connection = store.connect_alerts_db(str(tmp_path / "alerts.db"))
    yield connection
    connection.close()


def _bus(conn, notifier=None, config=None, clock=None) -> AlertBus:
    return AlertBus(
        conn,
        notifier,
        config if config is not None else AlertsConfig(),
        run_id=1,
        source="live",
        now_fn=clock if clock is not None else FakeClock(),
    )


def _rows(conn) -> list[store.AlertRow]:
    return list(reversed(store.list_alerts(conn, limit=500)))


# --------------------------------------------------------------------- fan-out


def test_every_emit_writes_a_db_row_even_with_no_telegram(conn):
    bus = _bus(conn, notifier=None)
    bus.emit(AlertEvent(code="trade_opened", title="OPEN BTCUSDT BUY"))

    rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0].code == "trade_opened"
    assert rows[0].level == "INFO"
    assert rows[0].run_id == 1 and rows[0].source == "live"
    assert rows[0].sent_telegram is False
    assert rows[0].telegram_status == store.TELEGRAM_MUTED


def test_telegram_and_db_both_get_the_alert(conn):
    notifier = FakeNotifier()
    bus = _bus(conn, notifier)
    bus.emit(AlertEvent(code="feed_degraded", title="feed DEGRADED — timeout"))

    assert len(notifier.sent) == 1
    assert "WARN" in notifier.sent[0] and "DEGRADED" in notifier.sent[0]
    assert _rows(conn)[0].telegram_status == store.TELEGRAM_SENT
    assert _rows(conn)[0].sent_telegram is True


def test_body_is_stored_and_round_trips(conn):
    bus = _bus(conn)
    bus.emit(AlertEvent(code="trade_closed", title="CLOSE", body={"pnl_r": 1.5, "symbol": "BTC"}))
    assert _rows(conn)[0].body == {"pnl_r": 1.5, "symbol": "BTC"}


# -------------------------------------------------------------------- cooldown


def test_same_code_and_key_inside_the_window_is_not_re_sent(conn):
    notifier = FakeNotifier()
    clock = FakeClock()
    bus = _bus(conn, notifier, AlertsConfig(cooldown_seconds=600), clock)

    bus.emit(AlertEvent(code="trade_opened", title="first", dedupe_key="BTCUSDT"))
    clock.advance(minutes=5)
    bus.emit(AlertEvent(code="trade_opened", title="second", dedupe_key="BTCUSDT"))

    assert len(notifier.sent) == 1  # throttled...
    rows = _rows(conn)
    assert [r.title for r in rows] == ["first", "second"]  # ...but both are logged
    assert rows[1].telegram_status == store.TELEGRAM_SUPPRESSED


def test_cooldown_is_per_key_so_another_symbol_still_gets_through(conn):
    notifier = FakeNotifier()
    bus = _bus(conn, notifier, AlertsConfig(cooldown_seconds=600))
    bus.emit(AlertEvent(code="trade_opened", title="btc", dedupe_key="BTCUSDT"))
    bus.emit(AlertEvent(code="trade_opened", title="eth", dedupe_key="ETHUSDT"))
    assert len(notifier.sent) == 2


def test_cooldown_expires(conn):
    notifier = FakeNotifier()
    clock = FakeClock()
    bus = _bus(conn, notifier, AlertsConfig(cooldown_seconds=600), clock)
    bus.emit(AlertEvent(code="trade_opened", title="first", dedupe_key="BTCUSDT"))
    clock.advance(minutes=11)
    bus.emit(AlertEvent(code="trade_opened", title="second", dedupe_key="BTCUSDT"))
    assert len(notifier.sent) == 2


def test_critical_is_never_suppressed_muted_or_throttled(conn):
    notifier = FakeNotifier()
    config = AlertsConfig(
        cooldown_seconds=3600,
        telegram_min_level="ERROR",
        telegram_muted_codes=["naked_position_closed"],
    )
    bus = _bus(conn, notifier, config)

    for _ in range(3):
        bus.emit(AlertEvent(code="naked_position_closed", title="SL failed — closed at market"))

    assert len(notifier.sent) == 3
    assert all(r.telegram_status == store.TELEGRAM_SENT for r in _rows(conn))


def test_level_threshold_mutes_quieter_codes_but_still_logs_them(conn):
    notifier = FakeNotifier()
    bus = _bus(conn, notifier, AlertsConfig(telegram_min_level="WARN"))
    bus.emit(AlertEvent(code="trade_opened", title="an INFO event"))
    bus.emit(AlertEvent(code="feed_degraded", title="a WARN event"))

    assert len(notifier.sent) == 1
    assert [r.telegram_status for r in _rows(conn)] == [
        store.TELEGRAM_MUTED,
        store.TELEGRAM_SENT,
    ]


def test_trade_pending_is_muted_for_telegram_by_default(conn):
    notifier = FakeNotifier()
    bus = _bus(conn, notifier)
    bus.emit(AlertEvent(code="trade_pending", title="PENDING BTCUSDT"))
    assert notifier.sent == []
    assert _rows(conn)[0].telegram_status == store.TELEGRAM_MUTED


# ------------------------------------------------------------------- failures


def test_a_log_only_sink_never_claims_the_alert_reached_telegram(conn):
    """No token configured: the fallback logger accepted the line, but nobody's phone
    buzzed, so `sent_telegram` must stay false (the UI draws an aeroplane off it)."""
    from bot.notify import LogNotifier

    bus = _bus(conn, LogNotifier())
    bus.emit(AlertEvent(code="trade_opened", title="OPEN BTCUSDT"))
    row = _rows(conn)[0]
    assert row.telegram_status == store.TELEGRAM_LOGGED
    assert row.sent_telegram is False


def test_a_telegram_exception_never_escapes_emit(conn):
    class ExplodingNotifier:
        remote = True

        def send(self, text: str) -> bool:
            raise RuntimeError("telegram library blew up")

    bus = _bus(conn, ExplodingNotifier())
    bus.emit(AlertEvent(code="trade_opened", title="still fine"))  # must not raise

    # The row must survive the failure: the DB is the source of truth, not Telegram.
    assert [r.title for r in _rows(conn)] == ["still fine"]


def test_a_broken_db_never_escapes_emit(conn):
    conn.execute("DROP TABLE alert")
    conn.commit()
    _bus(conn, FakeNotifier()).emit(AlertEvent(code="trade_opened", title="nowhere to go"))


def test_failed_delivery_is_retried_on_the_next_emit(conn):
    notifier = FakeNotifier(fail=True)
    clock = FakeClock()
    bus = _bus(conn, notifier, AlertsConfig(cooldown_seconds=0), clock)

    bus.emit(AlertEvent(code="feed_degraded", title="down"))
    assert _rows(conn)[0].telegram_status == store.TELEGRAM_FAILED

    notifier.fail = False
    clock.advance(minutes=1)
    bus.emit(AlertEvent(code="feed_recovered", title="up"))

    assert [r.telegram_status for r in _rows(conn)] == [
        store.TELEGRAM_SENT,
        store.TELEGRAM_SENT,
    ]
    assert "gửi lại" in notifier.sent[0]  # the backlog goes out first, marked as a resend


# --------------------------------------------------------------- LiveAlerts glue


def test_live_alerts_routes_the_plan_07_event_set_through_the_bus(conn):
    bus = _bus(conn, FakeNotifier())
    alerts = LiveAlerts(run_label="live#1", emitter=bus)

    alerts.trade_opened("BTCUSDT", "BUY", "BREAKOUT", 500.0, entry=1.0, sl=0.9)
    alerts.tp1_hit("BTCUSDT", 505.0)
    alerts.trade_closed("BTCUSDT", "WIN", 1.5, 7.5, 507.5)
    alerts.feed_degraded("timeout")
    alerts.feed_degraded("timeout")  # transition dedupe: still one row
    alerts.feed_recovered()

    codes = [r.code for r in _rows(conn)]
    assert codes == [
        "trade_opened",
        "tp1_hit",
        "trade_closed",
        "feed_degraded",
        "feed_recovered",
    ]
    assert _rows(conn)[0].body["symbol"] == "BTCUSDT"


def test_equity_multiplier_only_speaks_on_a_change(conn):
    bus = _bus(conn, FakeNotifier())
    alerts = LiveAlerts(emitter=bus)
    alerts.equity_multiplier(1.0, 0, 0)  # unchanged from the initial 1.0 -> silent
    alerts.equity_multiplier(0.5, 3, 0)
    alerts.equity_multiplier(0.5, 3, 0)
    alerts.equity_multiplier(1.0, 0, 0)
    assert [r.body["multiplier"] for r in _rows(conn)] == [0.5, 1.0]


# ------------------------------------------------------------------ catalogue


def test_levels_are_ordered():
    assert level_at_least("CRITICAL", "INFO")
    assert not level_at_least("INFO", "WARN")
    assert level_at_least("WARN", "WARN")


def test_every_catalogued_code_has_a_known_level():
    assert all(default_level(code) in {"INFO", "WARN", "ERROR", "CRITICAL"} for code in ALL_CODES)


def test_an_uncatalogued_code_is_still_logged_not_dropped(conn):
    bus = _bus(conn, FakeNotifier())
    bus.emit(AlertEvent(code="not_a_real_code", title="from the future"))
    assert _rows(conn)[0].code == "not_a_real_code"
    assert _rows(conn)[0].level == "WARN"  # unknown codes are never quietly INFO


# ----------------------------------------------------------------- read/unread


def test_mark_read_is_explicit_and_idempotent(conn):
    bus = _bus(conn)
    for i in range(3):
        bus.emit(AlertEvent(code="trade_opened", title=f"#{i}"))

    assert store.unread_count(conn) == 3
    ids = [r.id for r in _rows(conn)][:2]
    assert store.mark_read(conn, ids) == 2
    assert store.unread_count(conn) == 1
    store.mark_read(conn, ids)  # again: no error, no change
    assert store.unread_count(conn) == 1
    assert store.mark_read(conn, []) == 0  # empty list is NOT "mark everything"
    assert store.unread_count(conn) == 1


def test_since_id_returns_only_newer_rows(conn):
    bus = _bus(conn)
    for i in range(5):
        bus.emit(AlertEvent(code="trade_opened", title=f"#{i}"))
    all_rows = _rows(conn)
    cursor = all_rows[2].id
    newer = store.list_alerts(conn, since_id=cursor)
    assert [r.title for r in newer] == ["#4", "#3"]  # newest first
