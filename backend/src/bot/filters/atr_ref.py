"""Filter 4 — ATR reference (INPUT, locked). Not a gate: feeds every SL calculation."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "atr_ref"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.atr_ref
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.INPUT)

    atr14 = ctx.atr14.iloc[-1]
    atr5 = ctx.atr5.iloc[-1]
    if is_nan(atr14, atr5):
        return warmup_result(FILTER_ID, FilterKind.INPUT)

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.INPUT,
        enabled=True,
        evaluated=True,
        passed=None,
        blocking=False,
        values={"atr14": atr14, "atr5": atr5},
        detail=f"ATR14={atr14:.5f} ATR5={atr5:.5f}",
    )
