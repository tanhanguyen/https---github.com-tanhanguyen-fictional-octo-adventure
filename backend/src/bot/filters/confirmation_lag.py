"""Filter 10 — Confirmation lag (GATE, Phase B). D6/C2: fill convention never changes;
this only decides whether the just-closed bar *confirms* the signal direction, using
§6.1 semantics (close[-1] vs close[-2]) per docs/decisions.md deviation #14.

Not applicable to BREAKOUT retest signals: the retest bar already embeds its own
confirmation (close back beyond the broken level), and close[-1] > close[-2] would
systematically reject the classic pullback-then-rejection retest shape (the prior
bar's close sits higher during a BUY pullback by construction)."""

from __future__ import annotations

from bot.core.types import Direction, FilterKind, FilterResult, StrategyName
from bot.filters.base import FilterContext, disabled_result, is_nan, warmup_result

FILTER_ID = "confirmation_lag"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.confirmation_lag
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    if ctx.signal is None:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=None,
            blocking=False,
            values={},
            detail="no signal yet",
        )

    if ctx.signal.strategy == StrategyName.BREAKOUT:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=True,
            blocking=False,
            values={},
            detail="not applicable (breakout retest embeds its own confirmation)",
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
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=ok,
        blocking=not ok,
        values={"close_confirm": close_confirm, "close_signal": close_signal},
        detail="confirmed" if ok else "not confirmed",
    )
