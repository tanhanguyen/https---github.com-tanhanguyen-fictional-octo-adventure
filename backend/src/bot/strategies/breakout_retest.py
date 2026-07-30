"""Strategy 1 — Breakout-Retest-Breakout / BRB (docs/spec_v2.md §2-4). D5: ATR-based
retest tolerance. C6: RETEST_MAX_BARS=5 (v1.2 fallback only; BRB uses its own budgets).

The state machine evaluates EVERY bar (plan requirement) because it carries state across
bars: a regime flicker for one bar must not silently drop a pending setup. Regime and
range-width gating therefore happen at ARM time (the breakout-1 bar), via arm_buy/arm_sell
and min_range_atr_mult -- once armed, the pending setup survives regime flickers.

`breakout_cfg.require_second_breakout` (default True) selects BRB's 4-phase machine
(NONE -> AWAITING_PEAK -> AWAITING_RETEST -> AWAITING_BREAKOUT2 -> signal). False falls
back to the v1.2 machine (NONE -> AWAITING_RETEST -> signal at retest) for A/B comparison.
SL/TP formulas: docs/decisions.md mirror table (BUY/SELL)."""

from __future__ import annotations

import math

from bot.config.models import BreakoutConfig, RiskConfig
from bot.core.types import Direction, Signal, StrategyName, TPRules
from bot.filters.base import FilterContext
from bot.indicators.candle import is_engulfing, is_pin_bar
from bot.strategies.base import BreakoutState


def _retest_tolerance(ctx: FilterContext, risk_cfg: RiskConfig) -> float:
    atr14: float = float(ctx.atr14.iloc[-1])
    if risk_cfg.retest_tolerance_mode == "atr":
        if math.isnan(atr14):
            return float("nan")
        return float(risk_cfg.retest_tolerance_atr_mult * atr14)
    return float(risk_cfg.retest_tolerance_percent * ctx.close.iloc[-1])


def _retest_confirmed(ctx: FilterContext, direction: Direction) -> bool:
    """Pin bar / engulfing / long wick at the retest bar (spec_v2 §2 step 3)."""
    open_ = float(ctx.open_.iloc[-1])
    high = float(ctx.high.iloc[-1])
    low = float(ctx.low.iloc[-1])
    close = float(ctx.close.iloc[-1])
    side = direction.value
    # "Pin bar hoặc bóng dài": the 1.5x long-wick test subsumes the 2.0x pin bar, so one
    # call is the whole wick branch (scoring B1/B3 keep the two thresholds apart).
    if is_pin_bar(open_, high, low, close, side, wick_body_mult=1.5):
        return True
    if len(ctx.close) < 2:
        return False
    prev_open = float(ctx.open_.iloc[-2])
    prev_close = float(ctx.close.iloc[-2])
    if math.isnan(prev_open) or math.isnan(prev_close):
        return False
    return is_engulfing(prev_open, prev_close, open_, close, side)


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

    if breakout_cfg.require_second_breakout:
        if state.status in ("AWAITING_PEAK", "AWAITING_RETEST", "AWAITING_BREAKOUT2"):
            return _evaluate_brb_pending(ctx, state, breakout_cfg, risk_cfg)
    else:
        if state.status == "AWAITING_RETEST":
            return _evaluate_v1_retest(ctx, state, risk_cfg)

    # status == NONE: look for a fresh breakout-1. Range computed over the `period` bars
    # BEFORE the current (breakout) bar, so the breakout bar itself isn't self-referential.
    window_high = ctx.high.iloc[-(period + 1) : -1]
    window_low = ctx.low.iloc[-(period + 1) : -1]
    range_high = window_high.max()
    range_low = window_low.min()
    if math.isnan(range_high) or math.isnan(range_low):
        return None, state

    # Arm-time quality gate: the pre-breakout range must be meaningfully wide
    # (range_width filter, checked here at the breakout bar -- not at retest time).
    if min_range_atr_mult is not None:
        atr14 = float(ctx.atr14.iloc[-1])
        if math.isnan(atr14) or (range_high - range_low) <= min_range_atr_mult * atr14:
            return None, state

    next_status = "AWAITING_PEAK" if breakout_cfg.require_second_breakout else "AWAITING_RETEST"
    if close > range_high and arm_buy:
        return None, BreakoutState(
            status=next_status,
            direction=Direction.BUY,
            range_high=range_high,
            range_low=range_low,
            breakout_bar_ts=ctx.now,
            bars_waited=0,
        )
    if close < range_low and arm_sell:
        return None, BreakoutState(
            status=next_status,
            direction=Direction.SELL,
            range_high=range_high,
            range_low=range_low,
            breakout_bar_ts=ctx.now,
            bars_waited=0,
        )
    return None, state


def _evaluate_v1_retest(
    ctx: FilterContext, state: BreakoutState, risk_cfg: RiskConfig
) -> tuple[Signal | None, BreakoutState]:
    """v1.2 fallback: retest IS the entry (no Peak1 / breakout-2)."""
    close = ctx.close.iloc[-1]
    high = ctx.high.iloc[-1]
    low = ctx.low.iloc[-1]

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


def _evaluate_brb_pending(
    ctx: FilterContext,
    state: BreakoutState,
    breakout_cfg: BreakoutConfig,
    risk_cfg: RiskConfig,
) -> tuple[Signal | None, BreakoutState]:
    assert state.direction is not None
    assert state.range_high is not None and state.range_low is not None
    direction = state.direction
    close = float(ctx.close.iloc[-1])
    high = float(ctx.high.iloc[-1])
    low = float(ctx.low.iloc[-1])

    if state.status == "AWAITING_PEAK":
        atr14 = float(ctx.atr14.iloc[-1])
        if math.isnan(atr14):
            return None, BreakoutState.initial()

        if direction == Direction.BUY:
            peak1 = max(state.peak1, high) if state.peak1 is not None else high
            distance = peak1 - state.range_high
        else:
            peak1 = min(state.peak1, low) if state.peak1 is not None else low
            distance = state.range_low - peak1

        if distance >= breakout_cfg.peak_min_atr_mult * atr14:
            return None, BreakoutState(
                status="AWAITING_RETEST",
                direction=direction,
                range_high=state.range_high,
                range_low=state.range_low,
                breakout_bar_ts=state.breakout_bar_ts,
                bars_waited=0,
                peak1=peak1,
            )

        bars_waited = state.bars_waited + 1
        if bars_waited > breakout_cfg.peak_max_bars:
            return None, BreakoutState.initial()
        return None, BreakoutState(
            status="AWAITING_PEAK",
            direction=direction,
            range_high=state.range_high,
            range_low=state.range_low,
            breakout_bar_ts=state.breakout_bar_ts,
            bars_waited=bars_waited,
            peak1=peak1,
        )

    if state.status == "AWAITING_RETEST":
        assert state.peak1 is not None
        tolerance = _retest_tolerance(ctx, risk_cfg)
        atr14 = float(ctx.atr14.iloc[-1])
        bars_waited = state.bars_waited + 1
        if (
            math.isnan(tolerance)
            or math.isnan(atr14)
            or bars_waited > breakout_cfg.retest_confirm_max_bars
        ):
            return None, BreakoutState.initial()

        # spec_v2 §2 step 3: "Nếu Retest thủng sâu không quay lại → hủy tín hiệu". Without
        # this, price blowing straight back through the range still counted as "touched"
        # -- the machine advanced to AWAITING_BREAKOUT2 with a retest_low far below the
        # level, so SL anchored there always tripped `sl_too_wide` while holding the state
        # hostage for another `breakout2_max_bars`. The v1.2 branch got this for free from
        # its `close > level` condition; BRB needs it stated explicitly.
        max_depth = breakout_cfg.retest_max_depth_atr_mult * atr14
        if direction == Direction.BUY:
            level = state.range_high
            if low < level - max_depth:
                return None, BreakoutState.initial()
            touched = low <= level + tolerance
        else:
            level = state.range_low
            if high > level + max_depth:
                return None, BreakoutState.initial()
            touched = high >= level - tolerance

        if touched and (
            not breakout_cfg.require_retest_confirmation or _retest_confirmed(ctx, direction)
        ):
            return None, BreakoutState(
                status="AWAITING_BREAKOUT2",
                direction=direction,
                range_high=state.range_high,
                range_low=state.range_low,
                breakout_bar_ts=state.breakout_bar_ts,
                bars_waited=0,
                peak1=state.peak1,
                retest_low=low,
                retest_high=high,
            )

        return None, BreakoutState(
            status="AWAITING_RETEST",
            direction=direction,
            range_high=state.range_high,
            range_low=state.range_low,
            breakout_bar_ts=state.breakout_bar_ts,
            bars_waited=bars_waited,
            peak1=state.peak1,
        )

    # AWAITING_BREAKOUT2
    assert state.peak1 is not None
    assert state.retest_low is not None and state.retest_high is not None
    bars_waited = state.bars_waited + 1

    broke = close > state.peak1 if direction == Direction.BUY else close < state.peak1
    if broke:
        signal = Signal(
            direction=direction,
            strategy=StrategyName.BREAKOUT,
            signal_bar_ts=ctx.now,
            range_high=state.range_high,
            range_low=state.range_low,
            peak1=state.peak1,
            retest_low=state.retest_low,
            retest_high=state.retest_high,
            retest_bars_ago=bars_waited,
        )
        return signal, BreakoutState.initial()

    if bars_waited > breakout_cfg.breakout2_max_bars:
        return None, BreakoutState.initial()

    return None, BreakoutState(
        status="AWAITING_BREAKOUT2",
        direction=direction,
        range_high=state.range_high,
        range_low=state.range_low,
        breakout_bar_ts=state.breakout_bar_ts,
        bars_waited=bars_waited,
        peak1=state.peak1,
        retest_low=state.retest_low,
        retest_high=state.retest_high,
    )


def compute_sl(
    direction: Direction,
    range_high: float,
    range_low: float,
    retest_high: float,
    retest_low: float,
    atr14: float,
    sl_scale: float,
    sl_buffer_atr_mult: float = 0.5,
) -> float:
    """Mirror table (docs/decisions.md, revised): SL anchors at the retest bar's extreme,
    capped at the broken level -- NOT at the far side of the whole range (which made
    1R ≈ full range width and pushed TP1=1.5R out of reach of the time stop).

    BUY  sl = min(retest_low,  range_high) - sl_buffer_atr_mult*ATR14*sl_scale
    SELL sl = max(retest_high, range_low)  + sl_buffer_atr_mult*ATR14*sl_scale
    """
    if direction == Direction.BUY:
        return min(retest_low, range_high) - sl_buffer_atr_mult * atr14 * sl_scale
    return max(retest_high, range_low) + sl_buffer_atr_mult * atr14 * sl_scale


def compute_tp_rules(breakout_cfg: BreakoutConfig) -> TPRules:
    return TPRules(
        kind="R_MULTIPLE",
        tp1_r=breakout_cfg.tp1_r,
        tp2_r=breakout_cfg.tp2_r,
        partial_fraction=breakout_cfg.partial_fraction,
        move_be_after_tp1=True,
    )
