"""Filter 9 — DXY correlation (GATE, Phase B, FOREX only). §6.6."""

from __future__ import annotations

from bot.core.types import Direction, FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "dxy"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.dxy
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    if ctx.config.symbol_type != "FOREX" or "USD" not in ctx.symbol:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=True,
            blocking=False,
            values={},
            detail="not applicable (non-FOREX or no USD leg)",
        )

    if ctx.signal is None:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=None,
            blocking=False,
            values={"dxy_change_1h_pct": ctx.dxy_change_1h_pct},
            detail="no signal yet",
        )

    if is_nan(ctx.dxy_change_1h_pct):
        return warmup_result(FILTER_ID, FilterKind.GATE)
    change: float = ctx.dxy_change_1h_pct  # type: ignore[assignment]

    is_usd_base = ctx.symbol.startswith("USD")
    direction = ctx.signal.direction
    blocked = False
    if change > cfg.change_threshold_pct:
        if not is_usd_base and direction == Direction.BUY:
            blocked = True
        if is_usd_base and direction == Direction.SELL:
            blocked = True
    elif change < -cfg.change_threshold_pct:
        if not is_usd_base and direction == Direction.SELL:
            blocked = True
        if is_usd_base and direction == Direction.BUY:
            blocked = True

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=not blocked,
        blocking=blocked,
        values={
            "dxy_change_1h_pct": change,
            "is_usd_base": is_usd_base,
            "direction": direction.value,
        },
        detail=f"DXY 1h change {change:.3f}% vs {direction.value}",
    )
