"""Timeframe arithmetic and trading-day rollover (C3).

Timeframes: 15m, 1H, 4H, 1D, 1W. Bars are keyed by OPEN timestamp (UTC).
1D/1W bars anchor at the trading-day rollover (17:00 America/New_York) so daily
candles and the trading day share one boundary.

D10 / plan 05: stock VN does NOT use the 17:00 NY rollover -- its trading day is the
Asia/Ho_Chi_Minh calendar day, expressed as rollover_time="00:00" in that tz.
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


#: How many bars of the primary timeframe `build_context` feeds the indicators
#: (bot.engine.context.LOOKBACK). Lives here so the live feed can compute its warmup
#: requirement without importing the engine (dependency direction, invariant #6).
CONTEXT_LOOKBACK = 300


def tf_rank(tf: str) -> int:
    return TF_ORDER.index(tf)


def bars_per(outer_tf: str, inner_tf: str) -> int:
    """How many `inner_tf` bars fit in one `outer_tf` bar (rounded up)."""
    inner = tf_duration(inner_tf)
    outer = tf_duration(outer_tf)
    return -(-int(outer.total_seconds()) // int(inner.total_seconds()))


def warmup_bars_required(timeframe: str, lookback: int = CONTEXT_LOOKBACK) -> int:
    """Bars of `timeframe` a live feed must backfill before the first live decision.

    `build_context` asks the feed for `lookback` bars of the primary timeframe AND
    `lookback` bars of the higher timeframe (§6.5 pairs), and the higher frame is
    resampled from the primary one — so the binding constraint is the HTF, e.g. 1D
    primary needs 300 weekly bars => 300*7 daily bars. Computed, not guessed (plan 07
    §1: "tính đúng số bar cần, đừng đoán"); the +1 covers the bar being decided on.
    """
    need = lookback
    htf = higher_tf(timeframe)
    if htf is not None:
        need = max(need, lookback * bars_per(htf, timeframe))
    return need + 1


def tf_duration(tf: str) -> timedelta:
    return TF_DURATION[tf]


def higher_tf(tf: str) -> str | None:
    return TIMEFRAME_HIERARCHY[tf]


def parse_hhmm(value: str) -> time:
    hh, mm = (int(p) for p in value.split(":"))
    return time(hh, mm)


def rollover_shift(rollover_time: str) -> timedelta:
    """How far forward a local timestamp must be pushed before its DATE names the
    trading day: `(24h - rollover) mod 24h`.

    17:00 -> 7h, so local 17:00+ lands on the next calendar date (C3). 00:00 -> 0h,
    so the trading day is simply the local calendar date (plan 05, stock VN). The
    modulo is what makes midnight work: without it, `local.time() >= 00:00` is
    vacuously true and EVERY timestamp would be pushed a day forward.
    """
    t = parse_hhmm(rollover_time)
    offset = timedelta(hours=t.hour, minutes=t.minute)
    return timedelta(0) if offset == timedelta(0) else timedelta(days=1) - offset


def trading_day(
    ts: datetime, rollover_tz: str = "America/New_York", rollover_time: str = "17:00"
) -> date:
    """Trading day containing ts. A trading day named D runs from the rollover instant
    on D-1 to the rollover instant on D (C3): at/after the rollover we are in the NEXT
    day. With rollover_time="00:00" that degenerates to the local calendar day."""
    if ts.tzinfo is None:
        raise ValueError("trading_day requires tz-aware datetime")
    local = ts.astimezone(ZoneInfo(rollover_tz))
    return (local + rollover_shift(rollover_time)).date()


def trading_day_start_local(day: date, rollover_time: str) -> datetime:
    """Naive local datetime at which trading day `day` BEGINS (caller attaches tz).
    17:00 rollover -> 17:00 on D-1; midnight rollover -> 00:00 on D itself."""
    t = parse_hhmm(rollover_time)
    if rollover_shift(rollover_time) == timedelta(0):
        return datetime.combine(day, t)
    return datetime.combine(day - timedelta(days=1), t)


def vn30f_expiry(year: int, month: int) -> date:
    """VN30F1M expiry: the THIRD Thursday of the month.

    Calendar-only by design (user decision 2026-07-22): public holidays are NOT
    consulted, so an expiry falling on a holiday is off by the exchange's actual
    make-up date. Recorded as a deviation in docs/decisions.md; live trading
    (plan 07/08) reconciles against DNSE's `expirationDate` and trusts the API."""
    first = date(year, month, 1)
    days_to_thursday = (3 - first.weekday()) % 7  # Monday=0 ... Thursday=3
    return first + timedelta(days=days_to_thursday + 14)
