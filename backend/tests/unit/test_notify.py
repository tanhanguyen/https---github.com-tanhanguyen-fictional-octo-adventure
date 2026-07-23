"""Alerts (plan 07 §4): no token -> log-only, and a dead channel never breaks the bot."""

from __future__ import annotations

import urllib.parse

import pytest

from bot.notify import LiveAlerts, LogNotifier, TelegramNotifier, build_notifier


def test_no_token_falls_back_to_log_only():
    notifier = build_notifier(env={})
    assert isinstance(notifier, LogNotifier)
    notifier.send("hello")
    assert notifier.sent == ["hello"]


@pytest.mark.parametrize(
    "env",
    [{"TELEGRAM_BOT_TOKEN": "t"}, {"TELEGRAM_CHAT_ID": "c"}],
    ids=["token-only", "chat-only"],
)
def test_half_configured_telegram_falls_back_instead_of_failing(env):
    assert isinstance(build_notifier(env=env), LogNotifier)


def test_telegram_posts_the_message_to_the_right_chat():
    calls: list[tuple[str, bytes]] = []

    def post(url: str, data: bytes, timeout: float) -> bytes:
        calls.append((url, data))
        return b'{"ok":true}'

    notifier = build_notifier(
        env={"TELEGRAM_BOT_TOKEN": "SECRET", "TELEGRAM_CHAT_ID": "4242"}, http_post=post
    )
    assert isinstance(notifier, TelegramNotifier)
    notifier.send("OPEN BTCUSDT BUY")

    url, body = calls[0]
    assert url.endswith("/botSECRET/sendMessage")
    parsed = urllib.parse.parse_qs(body.decode())
    assert parsed == {"chat_id": ["4242"], "text": ["OPEN BTCUSDT BUY"]}


def test_delivery_failure_is_swallowed_so_the_trading_loop_survives():
    def broken(url: str, data: bytes, timeout: float) -> bytes:
        raise OSError("telegram unreachable")

    TelegramNotifier("t", "c", http_post=broken).send("anything")  # must not raise


def test_degraded_alert_fires_once_per_transition_not_per_poll():
    sink = LogNotifier()
    alerts = LiveAlerts(sink, run_label="live#1")

    alerts.feed_degraded("timeout")
    alerts.feed_degraded("timeout")
    alerts.feed_degraded("timeout")
    alerts.feed_recovered()
    alerts.feed_recovered()
    alerts.feed_degraded("timeout again")

    assert [m.split(" — ")[0] for m in sink.sent] == [
        "[live#1] ⚠️ feed DEGRADED",
        "[live#1] ✅ feed recovered",
        "[live#1] ⚠️ feed DEGRADED",
    ]


def test_daily_summary_is_one_message_per_day():
    sink = LogNotifier()
    alerts = LiveAlerts(sink)
    alerts.daily_summary("2026-07-23", {"equity": 500})
    alerts.daily_summary("2026-07-23", {"equity": 501})
    alerts.daily_summary("2026-07-24", {"equity": 502})
    assert len(sink.sent) == 2


def test_trade_messages_carry_r_and_equity():
    sink = LogNotifier()
    alerts = LiveAlerts(sink, run_label="live#9")
    alerts.trade_opened("BTCUSDT", "BUY", "BREAKOUT", 500.0)
    alerts.trade_closed("BTCUSDT", "WIN", 1.5, 7.5, 507.5)

    assert sink.sent[0] == "[live#9] OPEN BTCUSDT BUY (BREAKOUT) — equity 500.00"
    assert sink.sent[1] == "[live#9] CLOSE BTCUSDT WIN +1.50R (+7.50) — equity 507.50"
