"""LiveFeed (plan 07 §1): closed-bar filtering, warmup backfill, retry/backoff.

Every test drives an injected `http_get` — no test in this file (or anywhere) opens a
socket.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from bot.core.errors import FeedError
from bot.core.timeframes import warmup_bars_required
from bot.data.live_feed import (
    MAX_KLINES_PER_REQUEST,
    BinanceFuturesFeed,
    LiveFeedError,
    RetryPolicy,
)

UTC = timezone.utc


def kline(open_ts: datetime, tf_minutes: int, price: float) -> list[object]:
    """One Binance kline row; the venue's close_time is open + interval - 1ms."""
    open_ms = int(open_ts.timestamp() * 1000)
    close_ms = open_ms + tf_minutes * 60_000 - 1
    return [
        open_ms,
        f"{price:.2f}",
        f"{price + 1:.2f}",
        f"{price - 1:.2f}",
        f"{price + 0.5:.2f}",
        "10.0",
        close_ms,
        "0",
        0,
        "0",
        "0",
        "0",
    ]


def series(start: datetime, count: int, tf_minutes: int = 15) -> list[list[object]]:
    return [
        kline(start + timedelta(minutes=tf_minutes * i), tf_minutes, 100.0 + i)
        for i in range(count)
    ]


def responder(rows: list[list[object]]):
    def _get(url: str, timeout: float) -> bytes:
        return json.dumps(rows).encode()

    return _get


def test_unclosed_last_bar_is_dropped():
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    rows = series(start, 4)  # 00:00, 00:15, 00:30, 00:45
    feed = BinanceFuturesFeed("BTCUSDT", "15m", http_get=responder(rows))

    # 00:52 -> the 00:45 bar is still forming; the 00:30 bar closed at 00:45.
    df = feed.fetch_closed(datetime(2026, 7, 20, 0, 52, tzinfo=UTC))

    assert list(df.index) == [
        start,
        start + timedelta(minutes=15),
        start + timedelta(minutes=30),
    ]
    assert df.index.tz is not None


def test_bar_closing_exactly_now_is_included():
    """`open_ts + duration <= now` — the boundary belongs to the CLOSED side, matching
    Feed.bars() in replay (and NOT the venue's open+interval-1ms close_time)."""
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    feed = BinanceFuturesFeed("BTCUSDT", "15m", http_get=responder(series(start, 2)))

    df = feed.fetch_closed(datetime(2026, 7, 20, 0, 30, tzinfo=UTC))

    assert list(df.index) == [start, start + timedelta(minutes=15)]


def test_ohlcv_values_are_parsed_as_floats():
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    feed = BinanceFuturesFeed("BTCUSDT", "15m", http_get=responder(series(start, 1)))

    row = feed.fetch_closed(datetime(2026, 7, 20, 1, 0, tzinfo=UTC)).iloc[0]

    assert (row["open"], row["high"], row["low"], row["close"], row["volume"]) == (
        100.0,
        101.0,
        99.0,
        100.5,
        10.0,
    )


def test_retry_then_success_sleeps_with_backoff():
    attempts = {"n": 0}
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)

    def flaky(url: str, timeout: float) -> bytes:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("connection reset")
        return json.dumps(series(start, 2)).encode()

    slept: list[float] = []
    feed = BinanceFuturesFeed(
        "BTCUSDT",
        "15m",
        http_get=flaky,
        retry=RetryPolicy(max_attempts=5, base_delay=1.0, rng=random.Random(0)),
        sleep_fn=slept.append,
    )

    df = feed.fetch_closed(datetime(2026, 7, 20, 1, 0, tzinfo=UTC))

    assert attempts["n"] == 3
    assert len(df) == 2
    assert len(slept) == 2  # one pause after each of the two failures
    assert 0.0 <= slept[0] <= 1.0 and 0.0 <= slept[1] <= 2.0  # full jitter, growing cap


def test_exhausted_retries_raise_live_feed_error_not_crash_material():
    def always_fails(url: str, timeout: float) -> bytes:
        raise OSError("no route to host")

    feed = BinanceFuturesFeed(
        "BTCUSDT",
        "15m",
        http_get=always_fails,
        retry=RetryPolicy(max_attempts=3, rng=random.Random(0)),
        sleep_fn=lambda _s: None,
    )

    with pytest.raises(LiveFeedError) as exc:
        feed.fetch_closed(datetime(2026, 7, 20, tzinfo=UTC))
    assert "3 attempts failed" in str(exc.value)


def test_venue_error_object_is_retried_then_reported():
    def error_payload(url: str, timeout: float) -> bytes:
        return json.dumps({"code": -1121, "msg": "Invalid symbol."}).encode()

    feed = BinanceFuturesFeed(
        "NOPE",
        "15m",
        http_get=error_payload,
        retry=RetryPolicy(max_attempts=2, rng=random.Random(0)),
        sleep_fn=lambda _s: None,
    )

    with pytest.raises(LiveFeedError) as exc:
        feed.fetch_closed(datetime(2026, 7, 20, tzinfo=UTC))
    assert "Invalid symbol" in str(exc.value)


def test_backfill_pages_backwards_until_warmup_is_covered():
    """A 1D run needs 300 weekly bars of warmup = 2101 daily bars — more than the 1500
    the venue returns in one response, so backfill must page."""
    now = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    target = warmup_bars_required("1D")
    assert target > MAX_KLINES_PER_REQUEST

    day = 24 * 60
    all_rows = series(now - timedelta(minutes=day * 4000), 4000, tf_minutes=day)
    urls: list[str] = []

    def paged(url: str, timeout: float) -> bytes:
        urls.append(url)
        end_ms = None
        if "endTime=" in url:
            end_ms = int(url.split("endTime=")[1].split("&")[0])
        rows = [r for r in all_rows if end_ms is None or int(r[0]) <= end_ms]
        return json.dumps(rows[-MAX_KLINES_PER_REQUEST:]).encode()

    feed = BinanceFuturesFeed("BTCUSDT", "1D", http_get=paged)
    df = feed.backfill(now)

    assert len(df) == target
    assert len(urls) == 2  # 1500 + 1500 covers 2101
    assert df.index.is_monotonic_increasing and df.index.is_unique
    # The newest bars are the ones kept (the oldest surplus is trimmed).
    assert df.index[-1] == all_rows_last_open(all_rows)


def all_rows_last_open(rows: list[list[object]]) -> datetime:
    return datetime.fromtimestamp(int(rows[-1][0]) / 1000, tz=UTC)


def test_backfill_stops_when_the_venue_runs_out_of_history():
    now = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    rows = series(now - timedelta(minutes=15 * 50), 50)

    calls = {"n": 0}

    def short_history(url: str, timeout: float) -> bytes:
        calls["n"] += 1
        return json.dumps(rows if calls["n"] == 1 else []).encode()

    feed = BinanceFuturesFeed("BTCUSDT", "15m", http_get=short_history)
    df = feed.backfill(now)

    assert len(df) == 50  # returns what exists instead of looping forever


def test_unknown_timeframe_is_rejected_at_construction():
    with pytest.raises(FeedError):
        BinanceFuturesFeed("BTCUSDT", "3m")


@pytest.mark.parametrize(
    ("tf", "now", "expected"),
    [
        ("15m", datetime(2026, 7, 20, 0, 7, tzinfo=UTC), datetime(2026, 7, 20, 0, 15, tzinfo=UTC)),
        ("15m", datetime(2026, 7, 20, 0, 15, tzinfo=UTC), datetime(2026, 7, 20, 0, 30, tzinfo=UTC)),
        ("1H", datetime(2026, 7, 20, 0, 1, tzinfo=UTC), datetime(2026, 7, 20, 1, 0, tzinfo=UTC)),
        ("4H", datetime(2026, 7, 20, 5, 0, tzinfo=UTC), datetime(2026, 7, 20, 8, 0, tzinfo=UTC)),
        ("1D", datetime(2026, 7, 20, 5, 0, tzinfo=UTC), datetime(2026, 7, 21, 0, 0, tzinfo=UTC)),
        # Binance anchors weeklies to Monday 00:00 UTC; 2026-07-20 is a Monday.
        ("1W", datetime(2026, 7, 22, 5, 0, tzinfo=UTC), datetime(2026, 7, 27, 0, 0, tzinfo=UTC)),
    ],
)
def test_next_close_after(tf, now, expected):
    feed = BinanceFuturesFeed("BTCUSDT", tf, http_get=responder([]))
    assert feed.next_close_after(now) == expected


def test_warmup_is_computed_from_the_higher_timeframe():
    # 300 HTF bars is the binding constraint, +1 for the bar being decided.
    assert warmup_bars_required("15m") == 300 * 4 + 1  # htf 1H
    assert warmup_bars_required("1H") == 300 * 4 + 1  # htf 4H
    assert warmup_bars_required("4H") == 300 * 6 + 1  # htf 1D
    assert warmup_bars_required("1D") == 300 * 7 + 1  # htf 1W
    assert warmup_bars_required("1W") == 301  # no higher frame
