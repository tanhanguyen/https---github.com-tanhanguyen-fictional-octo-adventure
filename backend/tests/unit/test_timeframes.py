"""trading_day() across NY DST transitions and around the 17:00 NY boundary (C3);
D1/W1 resample anchoring (C3)."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.core.timeframes import trading_day
from bot.data.resample import resample_trading_day, resample_trading_week


def test_trading_day_before_and_after_rollover():
    # 16:59 NY on Jan 1 -> still trading day Jan 1. 17:00 NY -> trading day Jan 2.
    before = datetime(2024, 1, 1, 21, 59, tzinfo=timezone.utc)  # 16:59 EST (UTC-5)
    at_rollover = datetime(2024, 1, 1, 22, 0, tzinfo=timezone.utc)  # 17:00 EST
    assert trading_day(before) == datetime(2024, 1, 1).date()
    assert trading_day(at_rollover) == datetime(2024, 1, 2).date()


def test_trading_day_across_spring_forward_dst():
    # US spring-forward 2024: 2024-03-10 02:00 EST -> 03:00 EDT. 17:00 NY local time
    # is still 17:00 local regardless of the clock jump (zoneinfo handles the offset).
    # 21:59 UTC on 2024-03-11 is 17:59 EDT (UTC-4) -> already past rollover -> next day.
    ts = datetime(2024, 3, 11, 21, 30, tzinfo=timezone.utc)
    assert trading_day(ts) == datetime(2024, 3, 12).date()


def test_trading_day_across_fall_back_dst():
    # After fall-back (early Nov), NY is back to EST (UTC-5). 17:00 EST = 22:00 UTC.
    before = datetime(2024, 11, 5, 21, 59, tzinfo=timezone.utc)
    after = datetime(2024, 11, 5, 22, 0, tzinfo=timezone.utc)
    assert trading_day(before) == datetime(2024, 11, 5).date()
    assert trading_day(after) == datetime(2024, 11, 6).date()


def test_1d_resample_anchors_at_rollover():
    import pandas as pd

    # 1H bars spanning two trading days around the 17:00 NY (22:00 UTC in winter) boundary.
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="1h")
    df = pd.DataFrame(
        {
            "open": range(48),
            "high": range(48),
            "low": range(48),
            "close": range(48),
            "volume": [1.0] * 48,
        },
        index=idx,
    ).astype(float)
    df.index.name = "open_ts"

    daily = resample_trading_day(df)
    # Each daily bar's open_ts must be exactly 17:00 America/New_York (converted to UTC)
    # of the PRIOR calendar day, per C3.
    from zoneinfo import ZoneInfo

    for ts in daily.index:
        local = ts.tz_convert(ZoneInfo("America/New_York"))
        assert (local.hour, local.minute) == (17, 0)


def test_1w_resample_anchors_monday_trading_day():
    import pandas as pd

    idx = pd.date_range("2024-01-01T00:00:00Z", periods=24 * 21, freq="1h")
    df = pd.DataFrame(
        {
            "open": range(len(idx)),
            "high": range(len(idx)),
            "low": range(len(idx)),
            "close": range(len(idx)),
            "volume": [1.0] * len(idx),
        },
        index=idx,
    ).astype(float)
    df.index.name = "open_ts"
    daily = resample_trading_day(df)
    weekly = resample_trading_week(daily)

    from zoneinfo import ZoneInfo

    for ts in weekly.index:
        local = ts.tz_convert(ZoneInfo("America/New_York"))
        assert (local.hour, local.minute) == (17, 0)
        # local date should be a Sunday (so the trading day starting there is Monday's)
        assert local.weekday() == 6  # Sunday
