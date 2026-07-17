"""Filter 6 — Volume (GATE, off by default for FOREX). Only meaningful for BREAKOUT signals."""
from __future__ import annotations

from bot.core.types import FilterKind, FilterResult, StrategyName
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "volume"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.volume
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

    vol = ctx.volume.iloc[-1]
    vol_ma = ctx.volume_ma.iloc[-1]
    if is_nan(vol, vol_ma):
        return warmup_result(FILTER_ID, FilterKind.GATE)

    threshold = cfg.multiplier * vol_ma
    ok = vol > threshold
    return FilterResult(
        id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=ok,
        blocking=not ok,
        values={"volume": vol, "volume_ma": vol_ma, "threshold": threshold},
        detail=f"volume {vol:.1f} vs {threshold:.1f}",
    )
