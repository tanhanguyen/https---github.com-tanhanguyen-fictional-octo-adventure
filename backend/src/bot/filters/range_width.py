"""Filter 13 — Range width (GATE, Phase A). Range over range_period must exceed
atr_mult x ATR14 for a breakout region to be considered meaningful."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "range_width"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.range_width
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    period = ctx.config.strategies.breakout.range_period
    if len(ctx.high) < period:
        return warmup_result(FILTER_ID, FilterKind.GATE)

    range_high = ctx.high.iloc[-period:].max()
    range_low = ctx.low.iloc[-period:].min()
    atr14 = ctx.atr14.iloc[-1]
    if is_nan(range_high, range_low, atr14):
        return warmup_result(FILTER_ID, FilterKind.GATE)

    width = range_high - range_low
    threshold = cfg.atr_mult * atr14
    ok = width > threshold

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=ok,
        blocking=not ok,
        values={
            "range_high": range_high,
            "range_low": range_low,
            "width": width,
            "threshold": threshold,
        },
        detail=f"width {width:.5f} vs {threshold:.5f}",
    )
