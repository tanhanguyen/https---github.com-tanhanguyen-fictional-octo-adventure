"""Timeframe arithmetic and trading-day rollover (C3).

Timeframes: 15m, 1H, 4H, 1D, 1W. Bars are keyed by OPEN timestamp (UTC).
1D/1W bars anchor at the trading-day rollover (17:00 America/New_York) so daily
candles and the trading day share one boundary.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TF_DURATION: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1H": timedelta(hours=1),
    "4H": timedelta(hours=4),
    "1D": timedelta(days=1),
    "1W": timedelta(weeks=1),
}

# §6.5: fixed pairs, Weekly has no higher frame.
TIMEFRAME_HIERARCHY: dict[str, str | None] = {
    "15m": "1H",
    "1H": "4H",
    "4H": "1D",
    "1D": "1W",
    "1W": None,
}

# Plan 02: ordering for "native_tf must be <= config.timeframe" (finer-or-equal) checks.
TF_ORDER: list[str] = ["15m", "1H", "4H", "1D", "1W"]


def tf_rank(tf: str) -> int:
    return TF_ORDER.index(tf)


def tf_duration(tf: str) -> timedelta:
    return TF_DURATION[tf]


def higher_tf(tf: str) -> str | None:
    return TIMEFRAME_HIERARCHY[tf]


def trading_day(
    ts: datetime, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> date:
    """Trading day containing ts. A trading day named D runs from 17:00 NY on D-1
    to 17:00 NY on D (C3): at/after the rollover instant we are in the NEXT day."""
    if ts.tzinfo is None:
        raise ValueError("trading_day requires tz-aware datetime")
    tz = ZoneInfo(rollover_tz)
    local = ts.astimezone(tz)
    hh, mm = (int(p) for p in rollover_time.split(":"))
    if local.time() >= time(hh, mm):
        return (local + timedelta(days=1)).date()
    return local.date()
