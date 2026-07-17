"""Filter 1 — Trend (REGIME). §3: BULL/BEAR/NEUTRAL from EMA34 channel vs EMA89."""
from __future__ import annotations

from bot.core.types import FilterKind, FilterResult, Mode
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "trend"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.trend
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.REGIME)

    close = ctx.close.iloc[-1]
    ema_fast_high = ctx.ema_fast_high.iloc[-1]
    ema_fast_low = ctx.ema_fast_low.iloc[-1]
    ema_fast_close = ctx.ema_fast_close.iloc[-1]
    ema_slow_close = ctx.ema_slow_close.iloc[-1]

    if is_nan(close, ema_fast_high, ema_fast_low, ema_fast_close, ema_slow_close):
        return warmup_result(FILTER_ID, FilterKind.REGIME)

    if close > ema_fast_high and ema_fast_close > ema_slow_close:
        mode = Mode.BULL
    elif close < ema_fast_low and ema_fast_close < ema_slow_close:
        mode = Mode.BEAR
    else:
        mode = Mode.NEUTRAL

    return FilterResult(
        id=FILTER_ID, kind=FilterKind.REGIME, enabled=True, evaluated=True, passed=None,
        blocking=False,
        values={
            "mode": mode.value, "close": close, "ema_fast_high": ema_fast_high,
            "ema_fast_low": ema_fast_low, "ema_fast_close": ema_fast_close,
            "ema_slow_close": ema_slow_close,
        },
        detail=f"mode={mode.value}",
    )
