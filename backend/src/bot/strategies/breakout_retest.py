"""Strategy 1 — Breakout-Retest (§4). D5: ATR-based retest tolerance. C6: RETEST_MAX_BARS=5.

The state machine evaluates EVERY bar (plan requirement) because it carries state across
bars: a regime flicker for one bar must not silently drop a pending retest. Regime and
range-width gating therefore happen at ARM time (the breakout bar), via arm_buy/arm_sell
and min_range_atr_mult — once armed, the pending retest survives regime flickers.
SL/TP formulas: docs/decisions.md mirror table (BUY/SELL)."""

from __future__ import annotations

import math

from bot.config.models import BreakoutConfig, RiskConfig
from bot.core.types import Direction, Signal, StrategyName, TPRules
from bot.filters.base import FilterContext
from bot.strategies.base import BreakoutState


def _retest_tolerance(ctx: FilterContext, risk_cfg: RiskConfig) -> float:
    atr14: float = float(ctx.atr14.iloc[-1])
    if risk_cfg.retest_tolerance_mode == "atr":
        if math.isnan(atr14):
            return float("nan")
        return float(risk_cfg.retest_tolerance_atr_mult * atr14)
    return float(risk_cfg.retest_tolerance_percent * ctx.close.iloc[-1])


def evaluate(
    ctx: FilterContext,
    state: BreakoutState,
    breakout_cfg: BreakoutConfig,
    risk_cfg: RiskConfig,
    arm_buy: bool = True,
    arm_sell: bool = True,
    min_range_atr_mult: float | None = None,
) -> tuple[Signal | None, BreakoutState]:
    period = breakout_cfg.range_period
    if len(ctx.high) < period + 1:
        return None, state

    close = ctx.close.iloc[-1]
    high = ctx.high.iloc[-1]
    low = ctx.low.iloc[-1]
    if math.isnan(close) or math.isnan(high) or math.isnan(low):
        return None, state

    if state.status == "AWAITING_RETEST":
        tolerance = _retest_tolerance(ctx, risk_cfg)
        bars_waited = state.bars_waited + 1
        if math.isnan(tolerance) or bars_waited > risk_cfg.retest_max_bars:
            return None, BreakoutState.initial()

        assert state.direction is not None
        assert state.range_high is not None and state.range_low is not None

        if state.direction == Direction.BUY:
            level = state.range_high
            retested = low <= level + tolerance and close > level
        else:
            level = state.range_low
            retested = high >= level - tolerance and close < level

        if retested:
            signal = Signal(
                direction=state.direction,
                strategy=StrategyName.BREAKOUT,
                signal_bar_ts=ctx.now,
                range_high=state.range_high,
                range_low=state.range_low,
            )
            return signal, BreakoutState.initial()

        return None, BreakoutState(
            status="AWAITING_RETEST",
            direction=state.direction,
            range_high=state.range_high,
            range_low=state.range_low,
            breakout_bar_ts=state.breakout_bar_ts,
            bars_waited=bars_waited,
        )

    # status == NONE: look for a fresh breakout. Range computed over the `period` bars
    # BEFORE the current (breakout) bar, so the breakout bar itself isn't self-referential.
    window_high = ctx.high.iloc[-(period + 1) : -1]
    window_low = ctx.low.iloc[-(period + 1) : -1]
    range_high = window_high.max()
    range_low = window_low.min()
    if math.isnan(range_high) or math.isnan(range_low):
        return None, state

    # Arm-time quality gate: the pre-breakout range must be meaningfully wide
    # (range_width filter, checked here at the breakout bar — not at retest time).
    if min_range_atr_mult is not None:
        atr14 = float(ctx.atr14.iloc[-1])
        if math.isnan(atr14) or (range_high - range_low) <= min_range_atr_mult * atr14:
            return None, state

    if close > range_high and arm_buy:
        return None, BreakoutState(
            status="AWAITING_RETEST",
            direction=Direction.BUY,
            range_high=range_high,
            range_low=range_low,
            breakout_bar_ts=ctx.now,
            bars_waited=0,
        )
    if close < range_low and arm_sell:
        return None, BreakoutState(
            status="AWAITING_RETEST",
            direction=Direction.SELL,
            range_high=range_high,
            range_low=range_low,
            breakout_bar_ts=ctx.now,
            bars_waited=0,
        )
    return None, state


def compute_sl(
    direction: Direction,
    range_high: float,
    range_low: float,
    retest_high: float,
    retest_low: float,
    atr14: float,
    sl_scale: float,
) -> float:
    """Mirror table (docs/decisions.md, revised): SL anchors at the retest bar's extreme,
    capped at the broken level — NOT at the far side of the whole range (which made
    1R ≈ full range width and pushed TP1=1.5R out of reach of the time stop).

    BUY  sl = min(retest_low,  range_high) - 0.5*ATR14*sl_scale
    SELL sl = max(retest_high, range_low)  + 0.5*ATR14*sl_scale
    """
    if direction == Direction.BUY:
        return min(retest_low, range_high) - 0.5 * atr14 * sl_scale
    return max(retest_high, range_low) + 0.5 * atr14 * sl_scale


def compute_tp_rules(breakout_cfg: BreakoutConfig) -> TPRules:
    return TPRules(
        kind="R_MULTIPLE",
        tp1_r=breakout_cfg.tp1_r,
        tp2_r=breakout_cfg.tp2_r,
        partial_fraction=breakout_cfg.partial_fraction,
        move_be_after_tp1=True,
    )
