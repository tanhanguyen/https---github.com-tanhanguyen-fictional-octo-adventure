"""Filter 15 — Wick rejection (GATE, D4, Phase B). WICK_MIN_RATIO=0.5. Only meaningful
for BREAKOUT retest signals; always passes for MEAN_REVERSION."""
from __future__ import annotations

from bot.core.types import FilterKind, FilterResult, StrategyName
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result
from bot.indicators.candle import wick_ratio

FILTER_ID = "wick"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.wick
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    if ctx.signal is None:
        return FilterResult(
            id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=None,
            blocking=False, values={}, detail="no signal yet",
        )
    if ctx.signal.strategy != StrategyName.BREAKOUT:
        return FilterResult(
            id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=True,
            blocking=False, values={}, detail="not applicable (mean reversion)",
        )

    o, h, low, c = ctx.open_.iloc[-1], ctx.high.iloc[-1], ctx.low.iloc[-1], ctx.close.iloc[-1]
    if is_nan(o, h, low, c):
        return warmup_result(FILTER_ID, FilterKind.GATE)

    ratio = wick_ratio(o, h, low, c, ctx.signal.direction.value)
    ok = ratio >= cfg.min_ratio

    return FilterResult(
        id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=ok,
        blocking=not ok,
        values={"wick_ratio": ratio, "min_ratio": cfg.min_ratio},
        detail=f"wick ratio {ratio:.3f} vs {cfg.min_ratio}",
    )
