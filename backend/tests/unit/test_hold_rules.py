"""Hold rules by timeframe (plan 07 §4, user decision 2026-07-18).

TF <= H1: 8h time stop that survives TP1, no weekend carry (forex).
TF  > H1: time stop off, weekend carry allowed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.config.hold_rules import HOLD_MAX_HOURS, hold_rule_patch, is_fast_timeframe
from bot.config.loader import load_default_config
from bot.config.models import BotConfig, SymbolEntry, live_effective_config
from bot.core.types import Bar, Direction, InstrumentSpec, OrderStatus, StrategyName, TPRules
from bot.engine.context import market_rules_for
from bot.engine.order_engine import OpenTrade, OrderEngine

UTC = timezone.utc


@pytest.mark.parametrize("tf", ["15m", "1H"])
def test_fast_timeframes_get_an_8h_time_stop_that_survives_tp1(tf):
    patch = hold_rule_patch(tf, "CRYPTO")["filters"]["time_stop"]
    assert patch == {
        "enabled": True,
        "bars": None,  # hours, not bars: the cap is wall-clock exposure
        "hours": HOLD_MAX_HOURS,
        "after_tp1": True,  # deliberate deviation from C5
    }
    assert is_fast_timeframe(tf)


@pytest.mark.parametrize("tf", ["4H", "1D", "1W"])
def test_slow_timeframes_have_the_time_stop_off(tf):
    assert hold_rule_patch(tf, "FOREX")["filters"]["time_stop"] == {"enabled": False}
    assert hold_rule_patch(tf, "FOREX")["execution"]["weekend_flat"] is False
    assert not is_fast_timeframe(tf)


def test_weekend_flat_only_applies_where_the_market_actually_closes():
    assert hold_rule_patch("15m", "FOREX")["execution"]["weekend_flat"] is True
    # Crypto perpetuals are 24/7: there is no weekend window to flatten into.
    assert hold_rule_patch("15m", "CRYPTO")["execution"]["weekend_flat"] is False


def _cfg(tf: str, symbol: str, symbol_type: str, overrides=None) -> BotConfig:
    base = load_default_config()
    return base.model_copy(
        update={
            "timeframe": tf,
            "symbols": [
                SymbolEntry(symbol=symbol, symbol_type=symbol_type, overrides=overrides or {})
            ],
        }
    )


def test_live_effective_config_applies_the_rules_and_backtest_config_does_not():
    cfg = _cfg("15m", "BTCUSDT", "CRYPTO")
    live = live_effective_config(cfg, cfg.symbols[0])
    assert (live.filters.time_stop.hours, live.filters.time_stop.after_tp1) == (8.0, True)
    assert live.filters.time_stop.bars is None

    from bot.config.models import effective_config_for_symbol

    backtest = effective_config_for_symbol(cfg, cfg.symbols[0])
    assert backtest.filters.time_stop.bars == 16  # untouched default
    assert backtest.filters.time_stop.after_tp1 is False


def test_explicit_per_symbol_override_still_beats_the_hold_rule():
    cfg = _cfg(
        "15m",
        "BTCUSDT",
        "CRYPTO",
        overrides={"filters": {"time_stop": {"enabled": False}}},
    )
    live = live_effective_config(cfg, cfg.symbols[0])
    assert live.filters.time_stop.enabled is False


def test_vn_profile_timeframe_drives_the_rule_not_the_global_one():
    """A VN symbol is forced to 1D by its profile even under a global 15m config, so it
    must land in the SLOW bucket (time stop off), not the fast one."""
    cfg = _cfg("15m", "VN30F1M", "STOCK_VN_DERIV")
    live = live_effective_config(cfg, cfg.symbols[0])
    assert live.timeframe == "1D"
    assert live.filters.time_stop.enabled is False


# ------------------------------------------------------- weekend force-close (engine)


def _instrument() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="EURUSD",
        contract_size=100000,
        pip=0.0001,
        pip_value_per_lot=10.0,
        spread_pips=0.0,
        min_lot=0.01,
        lot_step=0.01,
    )


def _open_trade() -> OpenTrade:
    return OpenTrade(
        local_id=1,
        symbol="EURUSD",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.BUY,
        status=OrderStatus.OPEN,
        sl=1.0900,
        tp_rules=TPRules(kind="R_MULTIPLE", tp1_r=1.5, tp2_r=3.0),
        lot_size=0.1,
        entry_price=1.1000,
        tp1_price=1.2000,
        tp2_price=1.3000,
        entry_bar_ts=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        initial_sl_distance=0.0100,
    )


def _bar(close_ts: datetime) -> Bar:
    return Bar(
        open_ts=close_ts - timedelta(hours=1),
        open=1.1000,
        high=1.1050,
        low=1.0950,
        close=1.1010,
        volume=100.0,
        close_ts=close_ts,
    )


def _engine(weekend_flat: bool) -> OrderEngine:
    cfg = _cfg("1H", "EURUSD", "FOREX").model_copy()
    cfg.execution.weekend_flat = weekend_flat
    return OrderEngine(_instrument(), "sl_first", rules=market_rules_for(cfg))


def test_weekend_flat_closes_at_the_last_bar_of_the_forex_week():
    # 2026-07-24 is a Friday; 21:00 UTC == 17:00 America/New_York (the C3 rollover).
    bar = _bar(datetime(2026, 7, 24, 21, 0, tzinfo=UTC))
    outcome = _engine(True).process_bar(_open_trade(), bar, 8.0, False, False, equity=10_000)

    assert outcome.trade is None
    assert outcome.closed_result is not None
    assert [e.event_type for e in outcome.events] == ["weekend_close", "CLOSED"]
    assert outcome.closed_result.closed_at == bar.close_ts
    assert outcome.closed_result.result in {"WIN", "LOSS", "BREAKEVEN"}  # classified as usual


def test_weekend_flat_leaves_a_midweek_bar_alone():
    bar = _bar(datetime(2026, 7, 22, 21, 0, tzinfo=UTC))  # Wednesday
    outcome = _engine(True).process_bar(_open_trade(), bar, 999.0, False, False, equity=10_000)
    assert outcome.trade is not None and outcome.closed_result is None


def test_weekend_flat_leaves_a_friday_morning_bar_alone():
    bar = _bar(datetime(2026, 7, 24, 14, 0, tzinfo=UTC))  # Friday 10:00 New York
    outcome = _engine(True).process_bar(_open_trade(), bar, 999.0, False, False, equity=10_000)
    assert outcome.trade is not None and outcome.closed_result is None


def test_weekend_flat_off_is_the_default_and_holds_through_friday_close():
    bar = _bar(datetime(2026, 7, 24, 21, 0, tzinfo=UTC))
    outcome = _engine(False).process_bar(_open_trade(), bar, 999.0, False, False, equity=10_000)
    assert outcome.trade is not None and outcome.closed_result is None
    assert market_rules_for(load_default_config()).weekend_flat is False
