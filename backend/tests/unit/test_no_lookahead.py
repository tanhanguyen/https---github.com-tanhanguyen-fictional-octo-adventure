"""C11: a bar is visible only once open_ts + tf_duration <= clock.now. This is the
single most load-bearing invariant in the codebase (MTF look-ahead trap)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from bot.core.timeframes import tf_duration
from bot.data.feed import Feed


def _make_4h_frame(n: int, start: datetime) -> pd.DataFrame:
    idx = [start + timedelta(hours=4 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "open": range(n),
            "high": range(n),
            "low": range(n),
            "close": range(n),
            "volume": [1.0] * n,
        },
        index=pd.DatetimeIndex(idx, name="open_ts"),
    ).astype(float)


def test_guarded_bars_never_include_a_still_forming_bar():
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    df4h = _make_4h_frame(50, start)
    feed = Feed(frames={"4H": df4h})

    # clock at 11:00: the 4H bar opened at 08:00 is still forming (closes at 12:00).
    now = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
    visible = feed.bars("4H", now, n=200)

    assert visible.index.max() < now
    last_open = visible.index.max()
    assert last_open + tf_duration("4H") <= now
    # The forming 08:00 bar must NOT be in the visible set.
    assert start + timedelta(hours=8) not in visible.index


def test_naive_tail_would_leak_the_forming_bar():
    """Demonstrates the trap: an ungated .tail(n) on the raw frame includes bars whose
    open_ts is before `now` even though they haven't closed yet -- exactly the bug C11
    exists to prevent."""
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    df4h = _make_4h_frame(50, start)
    now = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)

    naive = df4h[df4h.index <= now].tail(200)  # WRONG: doesn't check the bar has closed
    forming_bar_ts = start + timedelta(hours=8)
    assert forming_bar_ts in naive.index  # the naive approach leaks it

    feed = Feed(frames={"4H": df4h})
    guarded = feed.bars("4H", now, n=200)
    assert forming_bar_ts not in guarded.index  # the guarded approach does not


def test_bar_becomes_visible_exactly_at_close():
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    df4h = _make_4h_frame(10, start)
    feed = Feed(frames={"4H": df4h})

    bar_open = start + timedelta(hours=4)  # closes at 08:00
    just_before_close = bar_open + timedelta(hours=4) - timedelta(minutes=1)
    at_close = bar_open + timedelta(hours=4)

    assert bar_open not in feed.bars("4H", just_before_close, n=200).index
    assert bar_open in feed.bars("4H", at_close, n=200).index


def test_tail_n_applied_after_lookahead_filter():
    """Regression guard for the exact bug: filter-then-tail vs tail-then-filter give
    different results once a forming bar would otherwise occupy one of the last N slots."""
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    df4h = _make_4h_frame(20, start)
    feed = Feed(frames={"4H": df4h})

    now = start + timedelta(hours=4 * 10 + 2)  # bar #10 (index10) is still forming
    guarded = feed.bars("4H", now, n=5)
    assert len(guarded) == 5
    assert guarded.index.max() == start + timedelta(hours=4 * 9)  # bar #9, the last CLOSED one
