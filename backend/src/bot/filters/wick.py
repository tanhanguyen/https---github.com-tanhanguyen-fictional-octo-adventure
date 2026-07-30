"""Filter 15 — Wick rejection (GATE, D4, Phase B). WICK_MIN_RATIO=0.5. Only meaningful
for BREAKOUT retest signals; always passes for MEAN_REVERSION.

The candle this reads is the RETEST candle, which is not always the decision bar: under
v1.2 (`require_second_breakout=false`) the retest bar IS the signal bar (`[-1]`), but
under BRB the signal fires on the breakout-2 bar, `signal.retest_bars_ago` bars later.
Reading `[-1]` unconditionally there inverted the filter's meaning -- it demanded a large
rejection wick on the very bar BRB (and scoring A1/A2) want to be a big-body, small-wick
momentum candle, so it silently blocked BRB signals as `no_signal/wick`."""

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
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=None,
            blocking=False,
            values={},
            detail="no signal yet",
        )
    if ctx.signal.strategy != StrategyName.BREAKOUT:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=True,
            blocking=False,
            values={},
            detail="not applicable (mean reversion)",
        )

    bars_ago = ctx.signal.retest_bars_ago or 0
    idx = -(1 + bars_ago)
    if -idx > len(ctx.close):
        return warmup_result(FILTER_ID, FilterKind.GATE, detail="retest bar outside series")

    o, h, low, c = (
        ctx.open_.iloc[idx],
        ctx.high.iloc[idx],
        ctx.low.iloc[idx],
        ctx.close.iloc[idx],
    )
    if is_nan(o, h, low, c):
        return warmup_result(FILTER_ID, FilterKind.GATE)

    ratio = wick_ratio(o, h, low, c, ctx.signal.direction.value)
    ok = ratio >= cfg.min_ratio

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=ok,
        blocking=not ok,
        values={
            "wick_ratio": ratio,
            "min_ratio": cfg.min_ratio,
            "retest_bars_ago": bars_ago,
        },
        detail=f"retest wick ratio {ratio:.3f} vs {cfg.min_ratio} ({bars_ago} bars ago)",
    )
