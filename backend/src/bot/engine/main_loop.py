"""main_loop: evaluate-all-decide-after (plan). Runs Phase A filters, resolves the
regime/strategy candidate (§8 step 5-6, disabled-filter defaults per docs/decisions.md),
always advances the breakout-retest state machine (cross-bar state, plan requirement),
generates a signal, runs Phase B filters, resolves the final decision, and -- if
`done` -- builds the PENDING order (SL fixed at decision time; TP AND lot fixed at fill,
deviation #7 -- lot sizing happens in OrderEngine.process_bar against the real fill
entry, see docs/decisions.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bot.config.models import BotConfig
from bot.core.types import DecisionOutcome, Direction, FilterResult, OrderStatus, StrategyName
from bot.engine import risk_manager
from bot.engine.decision_log import DecisionBundle, resolve_decision
from bot.engine.order_engine import OpenTrade
from bot.filters.base import FilterContext
from bot.filters.registry import PHASE_A, PHASE_B
from bot.strategies import breakout_retest, mean_reversion, scoring
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

    # BRB scoring gate (docs/spec_v2.md §5): a breakout-2 signal must clear
    # `scoring_threshold_ratio` of the confirmation matrix. `signal.peak1 is not None`
    # scopes this to the BRB path -- v1.2 fallback signals (require_second_breakout=false)
    # carry no peak1/retest_bars_ago and are unaffected. Not "done" -> the veto-preserving
    # block below keeps the pending breakout-2 alive within its remaining budget instead of
    # burning the state machine (plan: "không đốt state").
    if (
        outcome.reason == "done"
        and signal is not None
        and signal.strategy == StrategyName.BREAKOUT
        and signal.peak1 is not None
        and config.strategies.breakout.scoring_enabled
    ):
        bcfg = config.strategies.breakout
        score = scoring.compute_score(ctx, signal)
        verdict = scoring.gate(
            score,
            primary_ratio=bcfg.scoring_threshold_ratio,
            secondary_ratio=bcfg.scoring_secondary_threshold_ratio,
        )
        if not verdict.passed:
            outcome = DecisionOutcome(
                reason="wait",
                stage="scoring_below_threshold",
                detail=(
                    f"score {score.total}/{score.max_available} ({score.ratio:.2f}) "
                    f"< threshold {bcfg.scoring_threshold_ratio:.2f}; core "
                    f"A1+B1+C1 {score.core_total}/{scoring.CORE_REQUIRED_POINTS}"
                ),
            )

    # ALLOW_SHORT (deviation #12, D11): STOCK_VN_CASH has no short side. The signal is
    # still generated and logged -- only the order is blocked. §8 vocabulary is kept
    # (invariant #4): `no_signal` because on this market a SELL signal is, tradeably
    # speaking, not a signal at all; `stage` carries the real reason.
    if (
        outcome.reason == "done"
        and signal is not None
        and signal.direction == Direction.SELL
        and not config.risk.allow_short
    ):
        outcome = DecisionOutcome(
            reason="no_signal",
            stage="allow_short",
            detail="SELL blocked: cash market",
        )

    # A signal that fired but was vetoed downstream (wick/mtf/session/account_risk/
    # scoring...) must not burn the pending setup: keep waiting for a better bar within
    # the same-phase budget instead of silently resetting the state machine. v1.2
    # fallback fires from AWAITING_RETEST (budget = risk.retest_max_bars); BRB fires from
    # AWAITING_BREAKOUT2 (budget = breakout.breakout2_max_bars).
    if breakout_signal is not None and outcome.reason != "done":
        if breakout_state.status == "AWAITING_RETEST":
            veto_budget = config.risk.retest_max_bars
        elif breakout_state.status == "AWAITING_BREAKOUT2":
            veto_budget = config.strategies.breakout.breakout2_max_bars
        else:
            veto_budget = None
        if veto_budget is not None and breakout_state.bars_waited + 1 <= veto_budget:
            new_breakout_state = replace(breakout_state, bars_waited=breakout_state.bars_waited + 1)

    open_trade: OpenTrade | None = None
    if outcome.reason == "done":
        assert signal is not None
        sl_scale = all_results["atr_zscore"].values.get("sl_scale", 1.0)
        if signal.strategy == StrategyName.BREAKOUT:
            assert signal.range_high is not None and signal.range_low is not None
            atr14 = float(ctx.atr14.iloc[-1])
            bcfg = config.strategies.breakout
            # BRB (signal.retest_low/high set): SL anchors at the SAVED retest candle, not
            # the current (breakout-2) bar. v1.2 fallback: entry IS the retest bar, so
            # ctx.high/low.iloc[-1] is the retest candle itself (unchanged behavior).
            retest_high = signal.retest_high if signal.retest_high is not None else float(
                ctx.high.iloc[-1]
            )
            retest_low = signal.retest_low if signal.retest_low is not None else float(
                ctx.low.iloc[-1]
            )
            sl = breakout_retest.compute_sl(
                signal.direction,
                signal.range_high,
                signal.range_low,
                retest_high=retest_high,
                retest_low=retest_low,
                atr14=atr14,
                sl_scale=sl_scale,
                sl_buffer_atr_mult=bcfg.sl_buffer_atr_mult if signal.peak1 is not None else 0.5,
            )
            tp_rules = breakout_retest.compute_tp_rules(bcfg)

            # Guard chong-1-nen (docs/spec_v2.md §4): reject setups whose 1R is too small
            # (a normal-volatility bar would sweep the whole stop) or too large (risk cap).
            # Scoped to BRB only (signal.peak1 is not None) -- v1.2 fallback keeps its
            # original unguarded behavior for A/B comparison.
            if signal.peak1 is not None and not math.isnan(atr14):
                entry_est = float(ctx.close.iloc[-1])
                risk_distance = abs(entry_est - sl)
                if risk_distance < bcfg.min_stop_atr_mult * atr14:
                    bundle = DecisionBundle(
                        outcome=DecisionOutcome(
                            reason="wait",
                            stage="min_stop_distance",
                            detail=(
                                f"1R {risk_distance:.6f} < "
                                f"{bcfg.min_stop_atr_mult}xATR14 {atr14:.6f}"
                            ),
                        ),
                        filter_results=all_results,
                        signal=signal,
                        strategy=used_strategy,
                    )
                    return MainLoopResult(
                        bundle=bundle, open_trade_candidate=None, breakout_state=new_breakout_state
                    )
                if risk_distance > bcfg.max_sl_atr_mult * atr14:
                    bundle = DecisionBundle(
                        outcome=DecisionOutcome(
                            reason="wait",
                            stage="sl_too_wide",
                            detail=(
                                f"1R {risk_distance:.6f} > "
                                f"{bcfg.max_sl_atr_mult}xATR14 {atr14:.6f}"
                            ),
                        ),
                        filter_results=all_results,
                        signal=signal,
                        strategy=used_strategy,
                    )
                    return MainLoopResult(
                        bundle=bundle, open_trade_candidate=None, breakout_state=new_breakout_state
                    )
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
        risk_pct_effective = config.risk.max_risk_per_trade_pct * risk_multiplier

        # Plan 05: whole-lot markets (VN cash = 100 shares, VN30F = 1 contract) can
        # simply be unaffordable at the current equity. Size a PROVISIONAL lot off
        # close[-1] -- the real entry is only known at fill -- and if it rounds below
        # one lot, don't place an order at all. §8 vocabulary kept (invariant #4):
        # `wait` because this is a "not enough capital for THIS setup right now"
        # state that a later bar (different equity/SL distance) can clear; it is not
        # an account-risk limit (`daily_loss_limit_reached`/
        # `max_concurrent_trades_reached` would both misreport what happened).
        # OrderEngine keeps its own cancel-at-fill backstop for the case where the
        # real entry moves the lot to zero (plan 01 tech debt #1).
        if ctx.instrument is not None:
            provisional = risk_manager.calculate_lot(
                ctx.equity,
                risk_pct_effective,
                1.0,
                abs(float(ctx.close.iloc[-1]) - sl),
                ctx.instrument,
            )
            if provisional.lot <= 0:
                bundle = DecisionBundle(
                    outcome=DecisionOutcome(
                        reason="wait",
                        stage="lot_below_min",
                        detail=(
                            f"risk {risk_pct_effective:.3f}% of equity "
                            f"{ctx.equity:.2f} buys less than min_lot "
                            f"{ctx.instrument.min_lot:g}"
                        ),
                    ),
                    filter_results=all_results,
                    signal=signal,
                    strategy=used_strategy,
                )
                return MainLoopResult(
                    bundle=bundle,
                    open_trade_candidate=None,
                    breakout_state=new_breakout_state,
                )

        open_trade = OpenTrade(
            local_id=0,
            symbol=config.symbol,
            strategy=signal.strategy,
            direction=signal.direction,
            status=OrderStatus.PENDING,
            sl=sl,
            tp_rules=tp_rules,
            risk_pct_effective=risk_pct_effective,
        )

    bundle = DecisionBundle(
        outcome=outcome, filter_results=all_results, signal=signal, strategy=used_strategy
    )
    return MainLoopResult(
        bundle=bundle, open_trade_candidate=open_trade, breakout_state=new_breakout_state
    )
