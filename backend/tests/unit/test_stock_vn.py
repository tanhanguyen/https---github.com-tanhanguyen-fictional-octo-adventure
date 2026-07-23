"""Plan 05 — STOCK_VN_CASH / STOCK_VN_DERIV market rules.

Covers every behavior the plan calls out: VN trading day (no 17:00 NY rollover), the
two-window VN session, D1 profile defaults, ALLOW_SHORT on cash, whole-lot sizing and
the `lot_below_min` decision, T+2.5 exit suppression, and VN30F expiry force-close.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig, SymbolEntry, effective_config_for_symbol
from bot.core.timeframes import trading_day, vn30f_expiry
from bot.core.types import Bar, Direction, InstrumentSpec, OrderStatus, StrategyName, TPRules
from bot.data.resample import resample_trading_day
from bot.engine import risk_manager
from bot.engine.context import market_rules_for
from bot.engine.order_engine import OpenTrade, OrderEngine
from bot.filters import session as session_filter
from bot.filters.base import FilterContext

ICT = ZoneInfo("Asia/Ho_Chi_Minh")

HPG = InstrumentSpec(
    symbol="HPG",
    contract_size=100,
    pip=1.0,
    pip_value_per_lot=100.0,
    spread_pips=0.0,
    min_lot=1,
    lot_step=1,
    currencies=("VND",),
)
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


def _vn_config(symbol: str, symbol_type: str, **overrides) -> BotConfig:
    base = load_default_config()
    cfg = BotConfig.model_validate(
        {
            **base.model_dump(mode="json"),
            "symbols": [{"symbol": symbol, "symbol_type": symbol_type, **overrides}],
        }
    )
    return effective_config_for_symbol(cfg, cfg.symbols[0])


# ---------------------------------------------------------------------------
# Trading day + expiry calendar
# ---------------------------------------------------------------------------


def test_vn_trading_day_is_the_ict_calendar_day_not_ny_rollover():
    # 14:30 ICT (session close) on 2024-03-05 == 07:30 UTC. Under the forex C3 rule
    # this is still "trading day Mar 5" too, so pick an instant where the two rules
    # DISAGREE: 23:00 ICT == 16:00 UTC == 11:00 NY -> Mar 5 either way; but
    # 2024-03-05 22:00 UTC is 17:00 NY (past the forex rollover -> Mar 6) while in
    # ICT it is 05:00 on Mar 6 already -> Mar 6. Use the morning session instead:
    # 2024-03-05 02:00 UTC == 09:00 ICT (Mar 5) == 21:00 NY on Mar 4 (trading day Mar 5).
    ts = datetime(2024, 3, 5, 2, 0, tzinfo=timezone.utc)
    assert trading_day(ts, "Asia/Ho_Chi_Minh", "00:00") == date(2024, 3, 5)
    # The decisive case: the VN day must NOT roll over at 17:00 New York.
    late = datetime(2024, 3, 5, 22, 30, tzinfo=timezone.utc)  # 17:30 NY, 05:30 ICT Mar 6
    assert trading_day(late, "America/New_York", "17:00") == date(2024, 3, 6)
    assert trading_day(late, "Asia/Ho_Chi_Minh", "00:00") == date(2024, 3, 6)
    # ... and an instant inside the VN session never advances a day mid-session.
    for hour_ict in (9, 11, 13, 14):
        local = datetime(2024, 3, 5, hour_ict, 0, tzinfo=ICT)
        assert trading_day(local, "Asia/Ho_Chi_Minh", "00:00") == date(2024, 3, 5)


def test_midnight_rollover_does_not_shift_every_bar_forward():
    """Regression: `local.time() >= 00:00` is vacuously true, which would have pushed
    EVERY timestamp one day forward under a midnight rollover."""
    for hour in range(24):
        local = datetime(2024, 6, 12, hour, 0, tzinfo=ICT)
        assert trading_day(local, "Asia/Ho_Chi_Minh", "00:00") == date(2024, 6, 12)


def test_vn_daily_bar_grid_is_identical_under_utc_and_ict_days():
    """The whole VN session (02:00-07:45 UTC) sits inside one UTC day AND one ICT day,
    so grouping by either yields the same daily bars (plan 05 safety claim)."""
    rows = []
    for day in range(1, 6):
        for hour in (2, 4, 6):
            rows.append(
                {
                    "open_ts": datetime(2024, 4, day, hour, tzinfo=timezone.utc),
                    "open": 100.0 + day,
                    "high": 101.0 + day,
                    "low": 99.0 + day,
                    "close": 100.5 + day,
                    "volume": 1.0,
                }
            )
    df = pd.DataFrame(rows).set_index("open_ts")

    ict = resample_trading_day(df, "Asia/Ho_Chi_Minh", "00:00")
    utc = resample_trading_day(df, "UTC", "00:00")
    assert len(ict) == len(utc) == 5
    assert list(ict["high"]) == list(utc["high"])
    assert list(ict["low"]) == list(utc["low"])
    # Each ICT daily bar opens at 00:00 Asia/Ho_Chi_Minh.
    for ts in ict.index:
        local = ts.tz_convert(ICT)
        assert (local.hour, local.minute) == (0, 0)


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2024, 1, date(2024, 1, 18)),
        (2024, 2, date(2024, 2, 15)),
        (2024, 8, date(2024, 8, 15)),  # month starts on a Thursday
        (2024, 9, date(2024, 9, 19)),  # month starts on a Sunday
        (2026, 7, date(2026, 7, 16)),
    ],
)
def test_vn30f_expiry_is_third_thursday(year, month, expected):
    got = vn30f_expiry(year, month)
    assert got == expected
    assert got.weekday() == 3  # Thursday
    assert 15 <= got.day <= 21  # third occurrence of that weekday


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def test_vn_cash_profile_defaults():
    cfg = _vn_config("HPG", "STOCK_VN_CASH")
    assert cfg.timeframe == "1D"
    assert cfg.risk.allow_short is False  # D11 / deviation #12
    assert cfg.filters.account_risk.max_concurrent_trades == 2  # D10
    assert cfg.filters.account_risk.daily_loss_limit_enabled is False  # D10
    assert cfg.filters.time_stop.enabled is False  # TF > H1
    assert cfg.filters.dxy.enabled is False  # §6.6 is forex-only
    assert cfg.trading_day_rollover_tz == "Asia/Ho_Chi_Minh"
    assert cfg.trading_day_rollover_time == "00:00"


def test_vn_deriv_profile_allows_short():
    cfg = _vn_config("VN30F1M", "STOCK_VN_DERIV")
    assert cfg.risk.allow_short is True
    assert cfg.timeframe == "1D"
    assert cfg.filters.account_risk.daily_loss_limit_enabled is False


def test_per_symbol_override_still_beats_the_profile():
    cfg = _vn_config("VN30F1M", "STOCK_VN_DERIV", overrides={"timeframe": "4H"})
    assert cfg.timeframe == "4H"


def test_forex_profile_is_empty_so_defaults_are_untouched():
    base = load_default_config()
    cfg = effective_config_for_symbol(base, SymbolEntry(symbol="EURUSD", symbol_type="FOREX"))
    assert cfg.timeframe == base.timeframe
    assert cfg.filters.time_stop.enabled is base.filters.time_stop.enabled
    assert cfg.filters.account_risk.max_concurrent_trades == (
        base.filters.account_risk.max_concurrent_trades
    )
    assert cfg.trading_day_rollover_tz == "America/New_York"


def test_mixing_vn_and_non_vn_symbols_is_rejected():
    base = load_default_config().model_dump(mode="json")
    with pytest.raises(ValueError, match="cannot mix stock VN"):
        BotConfig.model_validate(
            {
                **base,
                "symbols": [
                    {"symbol": "HPG", "symbol_type": "STOCK_VN_CASH"},
                    {"symbol": "EURUSD", "symbol_type": "FOREX"},
                ],
            }
        )


def test_two_vn_symbols_of_different_vn_types_are_allowed():
    base = load_default_config().model_dump(mode="json")
    cfg = BotConfig.model_validate(
        {
            **base,
            "symbols": [
                {"symbol": "HPG", "symbol_type": "STOCK_VN_CASH"},
                {"symbol": "VN30F1M", "symbol_type": "STOCK_VN_DERIV"},
            ],
        }
    )
    assert cfg.trading_day_rollover_tz == "Asia/Ho_Chi_Minh"


def test_instruments_yaml_vn_entries_satisfy_sizing_pnl_invariant():
    """pip_value_per_lot == pip x contract_size, and VN lots are whole numbers."""
    instruments = load_instruments()
    for symbol in ("HPG", "FPT", "VN30F1M"):
        spec = instruments[symbol]
        assert spec["pip_value_per_lot"] == pytest.approx(spec["pip"] * spec["contract_size"])
        assert spec["min_lot"] == 1
        assert spec["lot_step"] == 1


# ---------------------------------------------------------------------------
# Session (two windows/day + daily-bar bypass)
# ---------------------------------------------------------------------------


def _session_ctx(now: datetime, symbol_type: str, timeframe: str) -> FilterContext:
    cfg = _vn_config("HPG", symbol_type, overrides={"timeframe": timeframe})
    empty = pd.Series(dtype=float)
    return FilterContext(
        config=cfg,
        now=now,
        symbol=cfg.symbol,
        open_=empty,
        high=empty,
        low=empty,
        close=empty,
        volume=empty,
        ema_fast_close=empty,
        ema_fast_high=empty,
        ema_fast_low=empty,
        ema_slow_close=empty,
        adx=empty,
        er=empty,
        rsi=empty,
        atr14=empty,
        atr5=empty,
        atr_zscore=empty,
        volume_ma=empty,
    )


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (8, 59, False),  # before the open
        (9, 0, True),  # morning window starts
        (11, 29, True),
        (11, 30, False),  # lunch break -- the gap between the two windows
        (12, 30, False),
        (13, 0, True),  # afternoon window starts
        (14, 29, True),
        (14, 30, False),  # after the close
    ],
)
def test_vn_session_has_two_windows_per_day(hour, minute, expected):
    now = datetime(2024, 3, 5, hour, minute, tzinfo=ICT).astimezone(timezone.utc)
    result = session_filter.evaluate(_session_ctx(now, "STOCK_VN_CASH", "4H"))
    assert result.passed is expected
    assert result.blocking is (not expected)


def test_vn_daily_bar_passes_session_gate():
    """A 1D decision is taken at 00:00 ICT -- structurally outside every window. The
    bar spans the whole session, so the gate must pass instead of blocking every bar."""
    close_of_daily_bar = datetime(2024, 3, 6, 0, 0, tzinfo=ICT).astimezone(timezone.utc)
    result = session_filter.evaluate(_session_ctx(close_of_daily_bar, "STOCK_VN_CASH", "1D"))
    assert result.passed is True
    assert result.blocking is False
    assert result.values["bar_spans_session"] is True


def test_forex_daily_bar_still_obeys_session_windows():
    """The bypass is scoped to VN: forex behavior (and its golden stream) is untouched."""
    base = load_default_config()
    cfg = effective_config_for_symbol(
        base, SymbolEntry(symbol="EURUSD", symbol_type="FOREX", overrides={"timeframe": "1D"})
    )
    ctx = _session_ctx(datetime(2024, 3, 5, 3, 0, tzinfo=timezone.utc), "STOCK_VN_CASH", "1D")
    ctx.config = cfg  # 03:00 UTC = 04:00 London, outside both forex windows
    result = session_filter.evaluate(ctx)
    assert result.passed is False
    assert result.blocking is True


# ---------------------------------------------------------------------------
# Whole-lot sizing
# ---------------------------------------------------------------------------


def test_vn_cash_lot_is_a_whole_number_of_round_lots():
    # 500m VND equity, 1% risk = 5m VND. SL distance 1,500 VND/share -> 150,000 VND
    # of risk per lot (100 shares) -> 33.3 lots -> floors to 33.
    result = risk_manager.calculate_lot(500_000_000.0, 1.0, 1.0, 1500.0, HPG)
    assert result.lot == 33
    assert float(result.lot).is_integer()
    assert result.realized_risk_amount == pytest.approx(33 * 1500 * 100)
    assert result.realized_risk_amount <= result.risk_amount


def test_vn30f_lot_is_a_whole_number_of_contracts():
    # 500m VND equity, 1% = 5m VND. SL 20 index points -> 2m VND per contract -> 2.5 -> 2.
    result = risk_manager.calculate_lot(500_000_000.0, 1.0, 1.0, 20.0, VN30F)
    assert result.lot == 2
    assert result.realized_risk_amount == pytest.approx(2 * 20 * 100_000)


def test_lot_below_min_returns_zero_rather_than_a_fractional_lot():
    # 10m VND equity, 1% = 100k VND, but one HPG lot risks 150k -> unaffordable.
    result = risk_manager.calculate_lot(10_000_000.0, 1.0, 1.0, 1500.0, HPG)
    assert result.lot == 0.0
    assert result.realized_risk_amount == 0.0


# ---------------------------------------------------------------------------
# T+2.5 settlement (STOCK_VN_CASH)
# ---------------------------------------------------------------------------


def _daily_bar(day: date, open_, high, low, close) -> Bar:
    """A VN daily bar: opens 09:00 ICT, closes at the next day's 09:00 ICT (the engine
    dates bars by open + tf duration), which is how the real CSV data is stamped."""
    open_ts = datetime(day.year, day.month, day.day, 9, 0, tzinfo=ICT).astimezone(timezone.utc)
    return Bar(
        open_ts=open_ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        close_ts=open_ts + timedelta(days=1),
    )


def _cash_engine() -> OrderEngine:
    return OrderEngine(HPG, rules=market_rules_for(_vn_config("HPG", "STOCK_VN_CASH")))


def _cash_buy(sl: float) -> OpenTrade:
    return OpenTrade(
        local_id=1,
        symbol="HPG",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.BUY,
        status=OrderStatus.PENDING,
        sl=sl,
        tp_rules=TPRules(kind="R_MULTIPLE", tp1_r=1.5, tp2_r=3.0, partial_fraction=0.5),
        risk_pct_effective=1.0,
    )


def _process(engine: OrderEngine, trade, bar: Bar):
    return engine.process_bar(trade, bar, 8.0, False, False, equity=500_000_000.0)


def test_t25_suppresses_sl_before_settlement_then_exits_when_released():
    engine = _cash_engine()
    trade = _cash_buy(sl=26_000.0)

    # T (Mon 2024-03-04): fill at open 27,000.
    out = _process(engine, trade, _daily_bar(date(2024, 3, 4), 27_000, 27_500, 26_800, 27_200))
    assert [e.event_type for e in out.events] == ["FILLED"]
    assert out.trade is not None and out.trade.lot_size > 0

    # T+1: price slices straight through the stop -- but the shares are not settled,
    # so the position CANNOT be sold. Recorded, not exited.
    out = _process(engine, out.trade, _daily_bar(date(2024, 3, 5), 26_900, 27_000, 25_500, 25_800))
    assert out.closed_result is None
    assert out.trade is not None
    assert [e.event_type for e in out.events] == ["exit_suppressed_settlement"]
    assert "SL touched but unsettled" in out.events[0].detail

    # T+2: shares land in the afternoon session -> the stop finally executes.
    out = _process(engine, out.trade, _daily_bar(date(2024, 3, 6), 25_900, 26_100, 25_000, 25_200))
    assert out.closed_result is not None
    assert out.closed_result.result == "LOSS"
    assert out.trade is None
    assert "CLOSED" in [e.event_type for e in out.events]


def test_t25_counts_trading_days_from_bars_so_holidays_and_weekends_are_skipped():
    """Entry on a Friday: the next two bars are Mon and Tue (the weekend has no bars),
    so the release lands on Tuesday, not on the Sunday two calendar days later."""
    engine = _cash_engine()
    trade = _cash_buy(sl=26_000.0)
    out = _process(  # Friday
        engine, trade, _daily_bar(date(2024, 3, 8), 27_000, 27_500, 26_800, 27_200)
    )
    out = _process(  # Monday -- T+1
        engine, out.trade, _daily_bar(date(2024, 3, 11), 26_900, 27_000, 25_500, 25_800)
    )
    assert out.closed_result is None
    assert [e.event_type for e in out.events] == ["exit_suppressed_settlement"]
    out = _process(  # Tuesday -- T+2, released
        engine, out.trade, _daily_bar(date(2024, 3, 12), 25_900, 26_100, 25_000, 25_200)
    )
    assert out.closed_result is not None


def test_t25_does_not_suppress_the_take_profit_after_release():
    engine = _cash_engine()
    trade = _cash_buy(sl=26_000.0)
    out = _process(engine, trade, _daily_bar(date(2024, 3, 4), 27_000, 27_200, 26_900, 27_100))
    for day in (5, 6):  # T+1 quiet, T+2 releases
        out = _process(
            engine, out.trade, _daily_bar(date(2024, 3, day), 27_100, 27_300, 27_000, 27_200)
        )
        assert out.closed_result is None
    # TP1 = entry + 1.5 x 1000 = 28,500 -- reachable now that the shares settled.
    out = _process(engine, out.trade, _daily_bar(date(2024, 3, 7), 27_200, 28_600, 27_100, 28_500))
    assert "TP1_HIT" in [e.event_type for e in out.events]


def _intraday_bar(day: date, hour: int, open_, high, low, close, hours: int = 4) -> Bar:
    open_ts = datetime(day.year, day.month, day.day, hour, 0, tzinfo=ICT).astimezone(timezone.utc)
    return Bar(
        open_ts=open_ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        close_ts=open_ts + timedelta(hours=hours),
    )


def test_t25_on_an_intraday_timeframe_releases_at_the_afternoon_session():
    """The release instant must stay anchored to the T+2 trading day. Re-deriving it
    from each bar's own day would leave a T+3 MORNING bar (which closes before 13:00 on
    its own day) reading as still-unsettled -- i.e. a position stuck forever."""
    engine = _cash_engine()
    trade = _cash_buy(sl=26_000.0)

    # T: morning + afternoon 4H bars.
    out = _process(
        engine, trade, _intraday_bar(date(2024, 3, 4), 9, 27_000, 27_200, 26_900, 27_100)
    )
    out = _process(
        engine, out.trade, _intraday_bar(date(2024, 3, 4), 13, 27_100, 27_200, 27_000, 27_150)
    )
    # T+1 and the T+2 MORNING bar: still unsettled, an SL touch is only recorded.
    out = _process(
        engine, out.trade, _intraday_bar(date(2024, 3, 5), 9, 27_100, 27_150, 25_900, 26_000)
    )
    assert [e.event_type for e in out.events] == ["exit_suppressed_settlement"]
    out = _process(
        engine, out.trade, _intraday_bar(date(2024, 3, 6), 9, 26_000, 26_100, 25_800, 25_900)
    )
    assert out.closed_result is None, "T+2 morning is before the shares land"
    assert [e.event_type for e in out.events] == ["exit_suppressed_settlement"]

    # T+2 afternoon: released.
    out = _process(
        engine, out.trade, _intraday_bar(date(2024, 3, 6), 13, 25_900, 26_000, 25_500, 25_600)
    )
    assert out.closed_result is not None


def test_t25_intraday_stays_released_on_later_mornings():
    """Regression companion to the test above: once released, a LATER morning bar must
    not flip back to unsettled."""
    engine = _cash_engine()
    trade = _cash_buy(sl=26_000.0)
    for day, hour in ((4, 9), (5, 9), (6, 9), (6, 13)):
        trade = _process(
            engine, trade, _intraday_bar(date(2024, 3, day), hour, 27_100, 27_200, 27_000, 27_150)
        ).trade
        assert trade is not None
    # T+3 morning -- price finally hits the stop.
    out = _process(
        engine, trade, _intraday_bar(date(2024, 3, 7), 9, 27_000, 27_050, 25_000, 25_500)
    )
    assert out.closed_result is not None
    assert "exit_suppressed_settlement" not in [e.event_type for e in out.events]


def test_forex_engine_has_no_settlement_lock():
    """Default MarketRules (forex/crypto) must behave exactly as before plan 05."""
    engine = OrderEngine(HPG)  # no rules -> settlement_trading_days is None
    trade = _cash_buy(sl=26_000.0)
    out = _process(engine, trade, _daily_bar(date(2024, 3, 4), 27_000, 27_500, 26_800, 27_200))
    out = _process(engine, out.trade, _daily_bar(date(2024, 3, 5), 26_900, 27_000, 25_500, 25_800))
    assert out.closed_result is not None  # stopped out immediately, no suppression


# ---------------------------------------------------------------------------
# VN30F expiry force-close (STOCK_VN_DERIV)
# ---------------------------------------------------------------------------


def _deriv_engine() -> OrderEngine:
    return OrderEngine(VN30F, rules=market_rules_for(_vn_config("VN30F1M", "STOCK_VN_DERIV")))


def _deriv_buy(sl: float) -> OpenTrade:
    return OpenTrade(
        local_id=1,
        symbol="VN30F1M",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.BUY,
        status=OrderStatus.PENDING,
        sl=sl,
        tp_rules=TPRules(kind="R_MULTIPLE", tp1_r=1.5, tp2_r=3.0, partial_fraction=0.5),
        risk_pct_effective=1.0,
    )


def test_vn30f_position_is_force_closed_on_the_expiry_bar():
    engine = _deriv_engine()
    trade = _deriv_buy(sl=1200.0)
    # 2024-08-15 is the third Thursday of August 2024.
    assert vn30f_expiry(2024, 8) == date(2024, 8, 15)

    out = _process(engine, trade, _daily_bar(date(2024, 8, 14), 1250, 1260, 1245, 1255))
    assert out.closed_result is None  # ordinary bar, position survives

    out = _process(engine, out.trade, _daily_bar(date(2024, 8, 15), 1255, 1265, 1250, 1262))
    assert out.trade is None
    assert out.closed_result is not None
    assert out.closed_result.result == "WIN"
    events = [e.event_type for e in out.events]
    assert "expiry_close" in events and "CLOSED" in events
    # Closed at the expiry bar's CLOSE (1262), not at an SL/TP level. Entry was the
    # previous bar's open (1250); SL 1200 -> 50 points risk -> 5m VND per contract ->
    # exactly 1 contract at 1% of 500m equity.
    assert out.closed_result.pnl_amount == pytest.approx((1262 - 1250) * 100_000 * 1.0)


def test_vn30f_normal_exit_still_wins_over_expiry_on_the_expiry_day():
    """If the stop is hit during the expiry session, that is the real exit."""
    engine = _deriv_engine()
    trade = _deriv_buy(sl=1200.0)
    out = _process(engine, trade, _daily_bar(date(2024, 8, 15), 1250, 1255, 1190, 1195))
    assert out.closed_result is not None
    assert [e.event_type for e in out.events][:2] == ["FILLED", "CLOSED"]
    assert "expiry_close" not in [e.event_type for e in out.events]


def test_cash_engine_never_force_closes_on_a_third_thursday():
    engine = _cash_engine()
    trade = _cash_buy(sl=26_000.0)
    out = _process(engine, trade, _daily_bar(date(2024, 8, 15), 27_000, 27_200, 26_900, 27_100))
    assert out.closed_result is None
    assert out.trade is not None
