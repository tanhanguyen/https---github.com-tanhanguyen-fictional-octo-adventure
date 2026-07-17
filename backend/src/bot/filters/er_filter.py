"""Filter 3 — Efficiency Ratio (REGIME). ER>threshold_trend -> smooth; <threshold_range -> noisy."""
from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "er_filter"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.er_filter
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.REGIME)

    value = ctx.er.iloc[-1]
    if is_nan(value):
        return warmup_result(FILTER_ID, FilterKind.REGIME)

    if value > cfg.threshold_trend:
        regime = "trend"
    elif value < cfg.threshold_range:
        regime = "range"
    else:
        regime = "transition"

    return FilterResult(
        id=FILTER_ID, kind=FilterKind.REGIME, enabled=True, evaluated=True, passed=None,
        blocking=False, values={"er": value, "regime": regime},
        detail=f"ER {value:.3f} -> {regime}",
    )
