"""Filter 10 — Confirmation lag (GATE, Phase B). D6/C2: fill convention never changes;
this only decides whether the just-closed bar *confirms* the signal direction, using
§6.1 semantics (close[-1] vs close[-2]) per docs/decisions.md deviation #14."""
from __future__ import annotations

from bot.core.types import Direction, FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "confirmation_lag"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.confirmation_lag
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    if ctx.signal is None:
        return FilterResult(
            id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=None,
            blocking=False, values={}, detail="no signal yet",
        )

    if len(ctx.close) < 2:
        return warmup_result(FILTER_ID, FilterKind.GATE)

    close_confirm = ctx.close.iloc[-1]
    close_signal = ctx.close.iloc[-2]
    if is_nan(close_confirm, close_signal):
        return warmup_result(FILTER_ID, FilterKind.GATE)

    if ctx.signal.direction == Direction.BUY:
        ok = close_confirm > close_signal
    else:
        ok = close_confirm < close_signal

    return FilterResult(
        id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=ok,
        blocking=not ok,
        values={"close_confirm": close_confirm, "close_signal": close_signal},
        detail="confirmed" if ok else "not confirmed",
    )
