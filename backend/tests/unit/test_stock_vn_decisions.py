"""Plan 05 — decision-level VN rules: ALLOW_SHORT on cash and `lot_below_min`.

Both are driven through the REAL `main_loop.decide` (not a hand-built
`resolve_decision` call) with a pre-armed retest state, so the assertions cover the
actual wiring: strategy -> filters -> decision -> pending order.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from bot.config.loader import load_default_config
from bot.config.models import BotConfig, effective_config_for_symbol
from bot.core.types import Direction, InstrumentSpec
from bot.engine import main_loop
from bot.filters.base import FilterContext
from bot.indicators.adx import adx
from bot.indicators.atr import atr
from bot.indicators.efficiency_ratio import efficiency_ratio
from bot.indicators.ema import ema
from bot.indicators.rsi import rsi
from bot.indicators.sma import sma
from bot.indicators.zscore import zscore
from bot.strategies.base import BreakoutState

VN30F = InstrumentSpec(
    symbol="VN30F1M",
    contract_size=100_000,
    pip=0.1,
    pip_value_per_lot=10_000.0,
    spread_pips=0.0,
    min_lot=1,
    lot_step=1,
    currencies=("VND",),
)


def _vn_config(symbol: str, symbol_type: str) -> BotConfig:
    base = load_default_config()
    cfg = BotConfig.model_validate(
        {
            **base.model_dump(mode="json"),
            "symbols": [{"symbol": symbol, "symbol_type": symbol_type}],
        }
    )
    # This file exercises ALLOW_SHORT/lot_below_min wiring through a hand-armed
    # AWAITING_RETEST state that completes on the SAME bar (v1.2 shape) -- not the BRB
    # Peak1/breakout-2 flow. Disable require_second_breakout so `_armed_sell_state`'s
    # single-phase state still reaches `done` (BRB coverage lives in test_strategies.py /
    # test_main_loop.py instead).
    cfg.strategies.breakout.require_second_breakout = False
    return effective_config_for_symbol(cfg, cfg.symbols[0])


def _downtrend_ctx(cfg: BotConfig, equity: float) -> FilterContext:
    """120 daily bars sloping down, so a SELL breakout is the natural signal."""
    n = 120
    close = [1400.0 - 1.0 * i for i in range(n)]
    high = [c + 4.0 for c in close]
    low = [c - 4.0 for c in close]
    open_ = [c + 0.5 for c in close]
    volume = [1000.0 + (i % 5) * 10 for i in range(n)]

    s = (
        pd.Series(close, dtype=float),
        pd.Series(high, dtype=float),
        pd.Series(low, dtype=float),
        pd.Series(open_, dtype=float),
        pd.Series(volume, dtype=float),
    )
    close_s, high_s, low_s, open_s, vol_s = s
    atr14 = atr(high_s, low_s, close_s, 14)

    return FilterContext(
        config=cfg,
        now=datetime(2024, 6, 4, 0, 0, tzinfo=timezone.utc),
        symbol=cfg.symbol,
        open_=open_s,
        high=high_s,
        low=low_s,
        close=close_s,
        volume=vol_s,
        ema_fast_close=ema(close_s, 34),
        ema_fast_high=ema(high_s, 34),
        ema_fast_low=ema(low_s, 34),
        ema_slow_close=ema(close_s, 89),
        adx=adx(high_s, low_s, close_s, 14),
        er=efficiency_ratio(close_s, 10),
        rsi=rsi(close_s, 14),
        atr14=atr14,
        atr5=atr(high_s, low_s, close_s, 5),
        atr_zscore=zscore(atr14, 100),
        volume_ma=sma(vol_s, 20),
        equity=equity,
        htf_timeframe="1W",
        instrument=VN30F,
    )


def _armed_sell_state(ctx: FilterContext) -> BreakoutState:
    """A breakout that already fired; THIS bar completes the retest (close below the
    broken level, high back up within tolerance)."""
    level = float(ctx.close.iloc[-1]) + 1.0  # close is below the level -> retest done
    return BreakoutState(
        status="AWAITING_RETEST",
        direction=Direction.SELL,
        range_high=level + 40.0,
        range_low=level,
        breakout_bar_ts=ctx.now,
        bars_waited=0,
    )


def test_sell_signal_reaches_done_on_vn30f_where_shorting_is_allowed():
    """Control for the ALLOW_SHORT test below: the identical setup must trade."""
    ctx = _downtrend_ctx(_vn_config("VN30F1M", "STOCK_VN_DERIV"), equity=500_000_000.0)
    result = main_loop.decide(ctx, _armed_sell_state(ctx), ctx.config)

    assert result.bundle.signal is not None
    assert result.bundle.signal.direction == Direction.SELL
    assert result.bundle.outcome.reason == "done"
    assert result.open_trade_candidate is not None
    assert result.open_trade_candidate.direction == Direction.SELL


def test_sell_is_blocked_on_cash_market_with_stage_allow_short():
    cfg = _vn_config("HPG", "STOCK_VN_CASH")
    assert cfg.risk.allow_short is False
    ctx = _downtrend_ctx(cfg, equity=500_000_000.0)
    result = main_loop.decide(ctx, _armed_sell_state(ctx), ctx.config)

    # The signal is still generated and logged -- only the order is blocked.
    assert result.bundle.signal is not None
    assert result.bundle.signal.direction == Direction.SELL
    assert result.bundle.outcome.reason == "no_signal"  # §8 vocabulary, invariant #4
    assert result.bundle.outcome.stage == "allow_short"
    assert result.bundle.outcome.detail == "SELL blocked: cash market"
    assert result.open_trade_candidate is None


def test_buy_is_unaffected_by_allow_short_false():
    """The cash block must be direction-specific, not a blanket veto."""
    cfg = _vn_config("HPG", "STOCK_VN_CASH")
    ctx = _downtrend_ctx(cfg, equity=500_000_000.0)
    state = replace(_armed_sell_state(ctx), direction=Direction.BUY)
    result = main_loop.decide(ctx, state, ctx.config)
    # A BUY retest doesn't complete on this bar, but it is never rejected for shorting.
    assert result.bundle.outcome.stage != "allow_short"


def test_equity_too_small_for_one_contract_waits_with_stage_lot_below_min():
    # 5m VND equity at 1% risk = 50,000 VND, while one VN30F contract risks millions.
    ctx = _downtrend_ctx(_vn_config("VN30F1M", "STOCK_VN_DERIV"), equity=5_000_000.0)
    result = main_loop.decide(ctx, _armed_sell_state(ctx), ctx.config)

    assert result.bundle.outcome.reason == "wait"  # §8 vocabulary, invariant #4
    assert result.bundle.outcome.stage == "lot_below_min"
    assert "min_lot" in result.bundle.outcome.detail
    # Crucially: no PENDING order is created, so nothing to cancel at fill.
    assert result.open_trade_candidate is None
    # The signal is still reported for the UI.
    assert result.bundle.signal is not None


def test_lot_below_min_never_fires_when_capital_is_sufficient():
    ctx = _downtrend_ctx(_vn_config("VN30F1M", "STOCK_VN_DERIV"), equity=500_000_000.0)
    result = main_loop.decide(ctx, _armed_sell_state(ctx), ctx.config)
    assert result.bundle.outcome.stage != "lot_below_min"


def test_no_instrument_on_context_skips_the_check(base_ctx):
    """Pre-plan-05 call sites (no instrument on the context) must be unaffected."""
    assert base_ctx.instrument is None
    result = main_loop.decide(base_ctx, BreakoutState.initial(), base_ctx.config)
    assert result.bundle.outcome.stage != "lot_below_min"


@pytest.mark.parametrize("symbol_type", ["STOCK_VN_CASH", "STOCK_VN_DERIV"])
def test_vn_decisions_report_the_disabled_daily_loss_limit(symbol_type):
    """D10 transparency: the decision row says the limit is off rather than hiding it."""
    ctx = _downtrend_ctx(_vn_config("HPG", symbol_type), equity=500_000_000.0)
    result = main_loop.decide(ctx, BreakoutState.initial(), ctx.config)
    values = result.bundle.filter_results["account_risk"].values
    assert values["daily_loss_limit_enabled"] is False
    assert values["max_concurrent_trades"] == 2
