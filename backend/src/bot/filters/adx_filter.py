"""Filter 2 — ADX (REGIME). ADX>threshold_trend -> trend regime; <threshold_range -> range."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "adx_filter"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.adx_filter
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.REGIME)

    value = ctx.adx.iloc[-1]
    if is_nan(value):
        return warmup_result(FILTER_ID, FilterKind.REGIME)

    if value > cfg.threshold_trend:
        regime = "trend"
    elif value < cfg.threshold_range:
        regime = "range"
    else:
        regime = "transition"

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.REGIME,
        enabled=True,
        evaluated=True,
        passed=None,
        blocking=False,
        values={"adx": value, "regime": regime},
        detail=f"ADX {value:.2f} -> {regime}",
    )
