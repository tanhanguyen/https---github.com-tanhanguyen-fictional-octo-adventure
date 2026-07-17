"""Filter 8 — Multi-timeframe (GATE, Phase B). §6.5. Caller must supply
ctx.htf_ema_fast_close/htf_ema_slow_close already lookahead-filtered per C11 —
this module only compares already-closed HTF bars, it does not fetch/filter bars."""
from __future__ import annotations

from bot.core.types import Direction, FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "mtf"


def _htf_trend(fast: float, slow: float) -> str:
    if fast > slow:
        return "BULL"
    if fast < slow:
        return "BEAR"
    return "NEUTRAL"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.mtf
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    if ctx.htf_timeframe is None:
        # Already at the highest timeframe (Weekly) -- nothing to reconcile against.
        return FilterResult(
            id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=True,
            blocking=False, values={}, detail="no higher timeframe (already at top)",
        )

    if ctx.htf_ema_fast_close is None or ctx.htf_ema_slow_close is None:
        return warmup_result(FILTER_ID, FilterKind.GATE, "htf data unavailable")

    fast = ctx.htf_ema_fast_close.iloc[-1]
    slow = ctx.htf_ema_slow_close.iloc[-1]

    if ctx.signal is None:
        if is_nan(fast, slow):
            return warmup_result(FILTER_ID, FilterKind.GATE)
        htf_trend = _htf_trend(fast, slow)
        return FilterResult(
            id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=None,
            blocking=False,
            values={"htf": ctx.htf_timeframe, "htf_trend": htf_trend},
            detail=f"htf={ctx.htf_timeframe} trend={htf_trend} (no signal yet)",
        )

    if is_nan(fast, slow):
        return warmup_result(FILTER_ID, FilterKind.GATE)

    htf_trend = _htf_trend(fast, slow)
    direction = ctx.signal.direction

    blocked = False
    if direction == Direction.BUY and htf_trend == "BEAR":
        blocked = True
    elif direction == Direction.SELL and htf_trend == "BULL":
        blocked = True
    elif cfg.block_on_neutral and htf_trend == "NEUTRAL":
        blocked = True

    return FilterResult(
        id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=not blocked,
        blocking=blocked,
        values={"htf": ctx.htf_timeframe, "htf_trend": htf_trend, "direction": direction.value},
        detail=f"htf={ctx.htf_timeframe} trend={htf_trend} vs {direction.value}",
    )
