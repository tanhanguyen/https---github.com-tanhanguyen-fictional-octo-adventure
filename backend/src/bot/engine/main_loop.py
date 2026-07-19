"""main_loop: evaluate-all-decide-after (plan). Runs Phase A filters, resolves the
regime/strategy candidate (§8 step 5-6, disabled-filter defaults per docs/decisions.md),
always advances the breakout-retest state machine (cross-bar state, plan requirement),
generates a signal, runs Phase B filters, resolves the final decision, and -- if
`done` -- builds the PENDING order (SL fixed at decision time; TP AND lot fixed at fill,
deviation #7 -- lot sizing happens in OrderEngine.process_bar against the real fill
entry, see docs/decisions.md).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from bot.config.models import BotConfig
from bot.core.types import FilterResult, OrderStatus, StrategyName
from bot.engine.decision_log import DecisionBundle, resolve_decision
from bot.engine.order_engine import OpenTrade
from bot.filters.base import FilterContext
from bot.filters.registry import PHASE_A, PHASE_B
from bot.strategies import breakout_retest, mean_reversion
from bot.strategies.base import BreakoutState


@dataclass
class MainLoopResult:
    bundle: DecisionBundle
    open_trade_candidate: OpenTrade | None
    breakout_state: BreakoutState


def _regime_flags(fr_dict: dict[str, FilterResult]) -> tuple[bool, bool, bool, bool, str | None]:
    adx_r = fr_dict["adx_filter"]
    er_r = fr_dict["er_filter"]
    trend_r = fr_dict["trend"]

    adx_ok_trend = (not adx_r.enabled) or (
        adx_r.evaluated and adx_r.values.get("regime") == "trend"
    )
    adx_ok_range = (not adx_r.enabled) or (
        adx_r.evaluated and adx_r.values.get("regime") == "range"
    )
    er_ok_trend = (not er_r.enabled) or (er_r.evaluated and er_r.values.get("regime") == "trend")
    er_ok_range = (not er_r.enabled) or (er_r.evaluated and er_r.values.get("regime") == "range")

    mode: str | None
    if not trend_r.enabled:
        mode = "NEUTRAL"
    elif trend_r.evaluated:
        mode = trend_r.values.get("mode")
    else:
        mode = None

    return adx_ok_trend, adx_ok_range, er_ok_trend, er_ok_range, mode


def decide(
    ctx: FilterContext, breakout_state: BreakoutState, config: BotConfig
) -> MainLoopResult:
    phase_a = {r.id: r for _fid, fn in PHASE_A for r in [fn(ctx)]}

    adx_ok_trend, adx_ok_range, er_ok_trend, er_ok_range, mode = _regime_flags(phase_a)
    atr_z = phase_a["atr_zscore"]
    allow_breakout = atr_z.values.get("allow_breakout", True)
    allow_mr = atr_z.values.get("allow_mean_reversion", True)

    strategy_candidate: StrategyName | None = None
    if (
        adx_ok_trend
        and er_ok_trend
        and allow_breakout
        and mode in ("BULL", "BEAR")
        and config.strategies.breakout.enabled
    ):
        strategy_candidate = StrategyName.BREAKOUT
    elif adx_ok_range and er_ok_range and allow_mr and config.strategies.mean_reversion.enabled:
        strategy_candidate = StrategyName.MEAN_REVERSION
    regime_undecided = strategy_candidate is None

    # Breakout-retest state machine runs EVERY bar (plan requirement: a pending retest
    # survives regime flickers). Regime gating happens at ARM time instead: a new
    # breakout is only armed when the CURRENT bar's regime selects BREAKOUT and the
    # breakout direction agrees with the trend mode (BULL->BUY, BEAR->SELL). This also
    # closes the hole where breakout signals fired (and traded) inside a range regime.
    arm_buy = strategy_candidate == StrategyName.BREAKOUT and mode == "BULL"
    arm_sell = strategy_candidate == StrategyName.BREAKOUT and mode == "BEAR"
    rw_cfg = config.filters.range_width
    breakout_signal, new_breakout_state = breakout_retest.evaluate(
        ctx,
        breakout_state,
        config.strategies.breakout,
        config.risk,
        arm_buy=arm_buy,
        arm_sell=arm_sell,
        min_range_atr_mult=rw_cfg.atr_mult if rw_cfg.enabled else None,
    )

    mr_signal = None
    if strategy_candidate == StrategyName.MEAN_REVERSION:
        mr_signal = mean_reversion.evaluate(ctx, config.strategies.mean_reversion)

    signal = breakout_signal if breakout_signal is not None else mr_signal
    used_strategy = (
        StrategyName.BREAKOUT
        if breakout_signal is not None
        else (StrategyName.MEAN_REVERSION if mr_signal is not None else strategy_candidate)
    )

    ctx.signal = signal
    phase_b = {r.id: r for _fid, fn in PHASE_B for r in [fn(ctx)]}
    all_results = {**phase_a, **phase_b}

    outcome = resolve_decision(all_results, signal, strategy_candidate, regime_undecided)

    # A retest that fired but was vetoed downstream (wick/mtf/session/account_risk...)
    # must not burn the pending breakout: keep waiting for a better retest bar within
    # the same RETEST_MAX_BARS budget instead of silently resetting the state machine.
    if (
        breakout_signal is not None
        and outcome.reason != "done"
        and breakout_state.status == "AWAITING_RETEST"
        and breakout_state.bars_waited + 1 <= config.risk.retest_max_bars
    ):
        new_breakout_state = replace(breakout_state, bars_waited=breakout_state.bars_waited + 1)

    open_trade: OpenTrade | None = None
    if outcome.reason == "done":
        assert signal is not None
        sl_scale = all_results["atr_zscore"].values.get("sl_scale", 1.0)
        if signal.strategy == StrategyName.BREAKOUT:
            assert signal.range_high is not None and signal.range_low is not None
            atr14 = float(ctx.atr14.iloc[-1])
            sl = breakout_retest.compute_sl(
                signal.direction,
                signal.range_high,
                signal.range_low,
                retest_high=float(ctx.high.iloc[-1]),
                retest_low=float(ctx.low.iloc[-1]),
                atr14=atr14,
                sl_scale=sl_scale,
            )
            tp_rules = breakout_retest.compute_tp_rules(config.strategies.breakout)
        else:
            ema34_low = float(ctx.ema_fast_low.iloc[-1])
            ema34_high = float(ctx.ema_fast_high.iloc[-1])
            atr5 = float(ctx.atr5.iloc[-1])
            sl = mean_reversion.compute_sl(
                signal.direction,
                ema34_low,
                ema34_high,
                atr5,
                config.strategies.mean_reversion.mr_sl_atr_mult,
            )
            ema34_close = float(ctx.ema_fast_close.iloc[-1])
            tp_rules = mean_reversion.compute_tp_rules(ema34_close)

        # Lot is NOT sized here -- it depends on the real fill entry, which is only
        # known in OrderEngine.process_bar (tech debt #1, plans/01-stabilize.md). A
        # PENDING order is always built for a `done` signal; if the eventual real-entry
        # lot rounds to zero, OrderEngine cancels it at fill.
        risk_multiplier = all_results["equity_curve"].values.get("risk_multiplier", 1.0)
        open_trade = OpenTrade(
            local_id=0,
            symbol=config.symbol,
            strategy=signal.strategy,
            direction=signal.direction,
            status=OrderStatus.PENDING,
            sl=sl,
            tp_rules=tp_rules,
            risk_pct_effective=config.risk.max_risk_per_trade_pct * risk_multiplier,
        )

    bundle = DecisionBundle(
        outcome=outcome, filter_results=all_results, signal=signal, strategy=used_strategy
    )
    return MainLoopResult(
        bundle=bundle, open_trade_candidate=open_trade, breakout_state=new_breakout_state
    )
