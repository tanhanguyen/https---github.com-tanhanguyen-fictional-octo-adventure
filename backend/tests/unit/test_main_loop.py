"""Every §8 reason in the vocabulary must be reachable, each via its own dedicated
scenario (plan requirement) -- a reason that can't be reproduced isn't trustworthy.
F3: max_concurrent_trades_reached is reachable via ONE_TRADE_PER_SYMBOL even with a
single symbol.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from bot.core.types import Direction, FilterKind, FilterResult, Signal, StrategyName
from bot.engine import main_loop
from bot.engine.decision_log import resolve_decision


def _fr(
    id_,
    kind=FilterKind.GATE,
    enabled=True,
    evaluated=True,
    passed=True,
    blocking=False,
    values=None,
    detail="",
):
    return FilterResult(
        id=id_,
        kind=kind,
        enabled=enabled,
        evaluated=evaluated,
        passed=passed,
        blocking=blocking,
        values=values or {},
        detail=detail,
    )


def _base_results():
    return {
        "account_risk": _fr("account_risk"),
        "session": _fr("session"),
        "news": _fr("news"),
        "atr_zscore": _fr(
            "atr_zscore",
            kind=FilterKind.MODIFIER,
            passed=True,
            values={"allow_breakout": True, "allow_mean_reversion": True, "sl_scale": 1.0},
        ),
        "trend": _fr("trend", kind=FilterKind.REGIME, passed=None, values={"mode": "BULL"}),
        "adx_filter": _fr(
            "adx_filter", kind=FilterKind.REGIME, passed=None, values={"regime": "trend"}
        ),
        "er_filter": _fr(
            "er_filter", kind=FilterKind.REGIME, passed=None, values={"regime": "trend"}
        ),
        "atr_ref": _fr(
            "atr_ref", kind=FilterKind.INPUT, passed=None, values={"atr14": 0.001, "atr5": 0.0005}
        ),
        "equity_curve": _fr(
            "equity_curve", kind=FilterKind.MODIFIER, passed=None, values={"risk_multiplier": 1.0}
        ),
        "range_width": _fr("range_width", passed=True),
        "time_stop": _fr("time_stop", kind=FilterKind.EXIT, passed=None),
        "confirmation_lag": _fr("confirmation_lag", passed=True),
        "wick": _fr("wick", passed=True),
        "volume": _fr("volume", enabled=False, evaluated=False, passed=None),
        "mtf": _fr("mtf", passed=True),
        "dxy": _fr("dxy", passed=True),
    }


_SIGNAL = Signal(
    direction=Direction.BUY,
    strategy=StrategyName.BREAKOUT,
    signal_bar_ts=datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc),
    range_high=1.11,
    range_low=1.10,
)


def test_reason_daily_loss_limit_reached():
    fr = _base_results()
    fr["account_risk"] = _fr(
        "account_risk",
        passed=False,
        blocking=True,
        values={"reason": "daily_loss_limit_reached", "stage": "account_risk"},
    )
    out = resolve_decision(fr, None, None, True)
    assert out.reason == "daily_loss_limit_reached"


def test_reason_max_concurrent_trades_reached_one_trade_per_symbol():
    """F3: reachable with a single symbol via the ONE_TRADE_PER_SYMBOL block."""
    fr = _base_results()
    fr["account_risk"] = _fr(
        "account_risk",
        passed=False,
        blocking=True,
        values={"reason": "max_concurrent_trades_reached", "stage": "one_trade_per_symbol"},
    )
    out = resolve_decision(fr, None, None, True)
    assert out.reason == "max_concurrent_trades_reached"
    assert out.stage == "one_trade_per_symbol"


def test_reason_wait_session():
    fr = _base_results()
    fr["session"] = _fr("session", passed=False, blocking=True)
    out = resolve_decision(fr, None, None, True)
    assert out.reason == "wait" and out.stage == "session"


def test_reason_off_atr_zscore():
    fr = _base_results()
    fr["atr_zscore"] = _fr(
        "atr_zscore",
        kind=FilterKind.MODIFIER,
        passed=False,
        blocking=True,
        values={"allow_breakout": False, "allow_mean_reversion": False, "sl_scale": 1.0},
    )
    out = resolve_decision(fr, None, None, True)
    assert out.reason == "off" and out.stage == "atr_zscore"


def test_reason_wait_warmup():
    fr = _base_results()
    fr["trend"] = _fr("trend", kind=FilterKind.REGIME, evaluated=False, passed=None)
    out = resolve_decision(fr, None, None, True)
    assert out.reason == "wait" and out.stage == "warmup"


def test_reason_wait_regime():
    fr = _base_results()
    out = resolve_decision(fr, None, None, regime_undecided=True)
    assert out.reason == "wait" and out.stage == "regime"


def test_reason_no_signal_range_width():
    fr = _base_results()
    fr["range_width"] = _fr("range_width", passed=False, blocking=True)
    out = resolve_decision(fr, None, StrategyName.BREAKOUT, regime_undecided=False)
    assert out.reason == "no_signal" and out.stage == "range_width"


def test_reason_no_signal_generic():
    fr = _base_results()
    out = resolve_decision(fr, None, StrategyName.MEAN_REVERSION, regime_undecided=False)
    assert out.reason == "no_signal" and out.stage == "mean_reversion"


def test_reason_no_confirm():
    fr = _base_results()
    fr["confirmation_lag"] = _fr("confirmation_lag", passed=False, blocking=True)
    out = resolve_decision(fr, _SIGNAL, StrategyName.BREAKOUT, regime_undecided=False)
    assert out.reason == "no_confirm"


def test_reason_mtf_conflict():
    fr = _base_results()
    fr["mtf"] = _fr("mtf", passed=False, blocking=True)
    out = resolve_decision(fr, _SIGNAL, StrategyName.BREAKOUT, regime_undecided=False)
    assert out.reason == "mtf_conflict"


def test_reason_dxy_conflict():
    fr = _base_results()
    fr["dxy"] = _fr("dxy", passed=False, blocking=True)
    out = resolve_decision(fr, _SIGNAL, StrategyName.BREAKOUT, regime_undecided=False)
    assert out.reason == "dxy_conflict"


def test_reason_done():
    fr = _base_results()
    out = resolve_decision(fr, _SIGNAL, StrategyName.BREAKOUT, regime_undecided=False)
    assert out.reason == "done" and out.stage == "place_order"


def test_full_main_loop_produces_done_and_pending_order(base_ctx):
    # base_ctx fixture is a warmed-up, in-session context (see tests/unit/conftest.py)
    from bot.strategies.base import BreakoutState

    result = main_loop.decide(base_ctx, BreakoutState.initial(), base_ctx.config)
    assert result.bundle.outcome.reason in (
        "wait",
        "no_signal",
        "off",
        "done",
        "mtf_conflict",
        "dxy_conflict",
        "no_confirm",
    )


def test_full_main_loop_account_risk_blocks_when_trade_open(base_ctx):
    from bot.strategies.base import BreakoutState

    ctx = replace(base_ctx, open_trades_count=1, symbol_open_trade=True)
    result = main_loop.decide(ctx, BreakoutState.initial(), ctx.config)
    assert result.bundle.outcome.reason == "max_concurrent_trades_reached"
    assert result.bundle.outcome.stage == "one_trade_per_symbol"
