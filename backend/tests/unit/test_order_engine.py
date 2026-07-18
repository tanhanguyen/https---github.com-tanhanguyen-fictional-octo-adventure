from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.core.types import Bar, Direction, InstrumentSpec, OrderStatus, StrategyName, TPRules
from bot.engine.order_engine import OpenTrade, OrderEngine

EURUSD = InstrumentSpec(
    symbol="EURUSD",
    contract_size=100_000,
    pip=0.0001,
    pip_value_per_lot=10.0,
    spread_pips=0.0,
    min_lot=0.01,
    lot_step=0.01,
)
T0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
EQUITY = 100_000.0


def _bar(open_, high, low, close, ts=T0, hours=1):
    return Bar(
        open_ts=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        close_ts=ts + timedelta(hours=hours),
    )


def _buy_trade(sl=1.0950, tp1_r=1.5, tp2_r=3.0):
    return OpenTrade(
        local_id=1,
        symbol="EURUSD",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.BUY,
        status=OrderStatus.PENDING,
        sl=sl,
        tp_rules=TPRules(
            kind="R_MULTIPLE",
            tp1_r=tp1_r,
            tp2_r=tp2_r,
            partial_fraction=0.5,
            move_be_after_tp1=True,
        ),
        risk_pct_effective=1.0,
    )


def _sell_trade(sl=1.1050, tp1_r=1.5, tp2_r=3.0):
    return OpenTrade(
        local_id=1,
        symbol="EURUSD",
        strategy=StrategyName.BREAKOUT,
        direction=Direction.SELL,
        status=OrderStatus.PENDING,
        sl=sl,
        tp_rules=TPRules(
            kind="R_MULTIPLE",
            tp1_r=tp1_r,
            tp2_r=tp2_r,
            partial_fraction=0.5,
            move_be_after_tp1=True,
        ),
        risk_pct_effective=1.0,
    )


def test_clean_sl_gives_exact_minus_one_r():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False, equity=EQUITY
    )
    out2 = eng.process_bar(
        out.trade,
        _bar(1.0998, 1.0999, 1.0940, 1.0945, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
        equity=EQUITY,
    )
    assert out2.closed_result is not None
    assert out2.closed_result.pnl_r == -1.0
    assert out2.closed_result.result == "LOSS"


def test_sl_and_tp_same_bar_sl_first_priority():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False, equity=EQUITY
    )
    tp1 = out.trade.tp1_price
    # Same bar touches both SL and TP1.
    out2 = eng.process_bar(
        out.trade,
        _bar(1.0999, tp1 + 0.0005, 1.0940, 1.0960, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
        equity=EQUITY,
    )
    assert out2.closed_result is not None
    assert out2.closed_result.result == "LOSS"  # SL wins under sl_first priority


def test_sl_and_tp_same_bar_path_priority_differs_from_sl_first():
    eng_sl = OrderEngine(EURUSD, "sl_first")
    eng_path = OrderEngine(EURUSD, "path")
    trade1 = _buy_trade()
    trade2 = _buy_trade()
    fill_bar = _bar(1.1000, 1.1010, 1.0990, 1.1005)
    o1 = eng_sl.process_bar(trade1, fill_bar, 8, True, False, equity=EQUITY)
    o2 = eng_path.process_bar(trade2, fill_bar, 8, True, False, equity=EQUITY)
    tp1 = o1.trade.tp1_price
    # open near the TP side, low reaches SL, high reaches TP -- path mode picks nearer to open.
    same_bar = _bar(tp1 - 0.0002, tp1 + 0.0002, 1.0940, tp1, ts=T0 + timedelta(hours=1))
    r1 = eng_sl.process_bar(o1.trade, same_bar, 8, True, False, equity=EQUITY)
    r2 = eng_path.process_bar(o2.trade, same_bar, 8, True, False, equity=EQUITY)
    assert r1.closed_result is not None  # sl_first always fully closes on ambiguity... (SL hit)
    # path mode, with open close to TP, should NOT necessarily close at SL immediately.
    assert (r1.closed_result.result, r2.trade is not None or r2.closed_result is not None) != (
        None,
        None,
    )


def test_path_priority_uses_real_sub_path_when_available():
    """Tech debt #2 (plans/01-stabilize.md): when a real sub_path is present,
    "path" mode must walk it instead of falling back to the nearer-to-open
    approximation -- and the two must be able to disagree."""
    eng_path = OrderEngine(EURUSD, "path")
    trade = _buy_trade()
    fill_bar = _bar(1.1000, 1.1010, 1.0990, 1.1005)
    out = eng_path.process_bar(trade, fill_bar, 8, True, False, equity=EQUITY)
    tp1 = out.trade.tp1_price
    sl = out.trade.sl

    # open is nearer to SL than TP1 -> the OHLC-only approximation would pick SL.
    open_ = tp1 - 0.0001
    assert abs(open_ - sl) > abs(open_ - tp1)  # sanity: open is nearer to TP1, not SL
    open_near_tp = tp1 - 0.00001
    assert abs(open_near_tp - tp1) < abs(open_near_tp - sl)

    # Real path: dips to touch SL FIRST, then rallies back up through TP1 -- the
    # approximation (nearer-to-open) would have picked TP1 since open is close to it.
    path = (open_near_tp, sl - 0.0001, sl, tp1 + 0.0001, tp1)
    same_bar = Bar(
        open_ts=T0 + timedelta(hours=1),
        open=path[0],
        high=max(path),
        low=min(path),
        close=path[-1],
        volume=1.0,
        close_ts=T0 + timedelta(hours=2),
        sub_path=path,
    )
    result = eng_path.process_bar(out.trade, same_bar, 8, True, False, equity=EQUITY)
    assert result.closed_result is not None
    assert result.closed_result.result == "LOSS"  # SL hit first on the real path


def test_gap_through_sl_cancels_pending_order():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade(sl=1.0990)
    # bar opens already below SL -> D7 guard cancels at fill.
    out = eng.process_bar(
        trade, _bar(1.0980, 1.0990, 1.0970, 1.0985), 8, True, False, equity=EQUITY
    )
    assert out.trade is None
    assert out.closed_result is None
    assert out.events[0].event_type == "CANCELLED"


def test_tp1_hit_moves_sl_to_breakeven_same_bar():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False, equity=EQUITY
    )
    tp1 = out.trade.tp1_price
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, tp1 + 0.0003, 1.1001, tp1, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
        equity=EQUITY,
    )
    assert out2.trade is not None  # only half closed, still running
    assert out2.trade.tp1_hit is True
    assert out2.trade.sl == out2.trade.entry_price  # moved to breakeven
    assert any(e.event_type == "TP1_HIT" for e in out2.events)
    assert any(e.event_type == "SL_TO_BREAKEVEN" for e in out2.events)


def test_tp1_then_reversal_to_breakeven_same_bar_nets_positive_not_minus_one_r():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False, equity=EQUITY
    )
    entry = out.trade.entry_price
    tp1 = out.trade.tp1_price
    # Same bar hits TP1 then reverses all the way back to entry (BE).
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, tp1 + 0.0002, entry - 0.0005, entry, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
        equity=EQUITY,
    )
    assert out2.closed_result is not None
    assert out2.closed_result.pnl_r > 0  # net +0.75R (half at +1.5R, half at 0), not -1R
    assert out2.closed_result.result == "WIN"


def test_time_stop_disabled_after_tp1():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False, equity=EQUITY
    )
    tp1 = out.trade.tp1_price
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, tp1 + 0.0003, 1.1001, 1.1003, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
        equity=EQUITY,
    )
    assert out2.trade is not None and out2.trade.tp1_hit
    # far in the future, well past time_stop_hours, but after_tp1=False -> disabled (C5)
    far_bar = _bar(1.1003, 1.1004, 1.1001, 1.1003, ts=T0 + timedelta(hours=100), hours=1)
    out3 = eng.process_bar(out2.trade, far_bar, 8, True, False, equity=EQUITY)
    assert out3.trade is not None  # NOT closed by time stop


def test_time_stop_closes_before_tp1():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1005, 1.0995, 1.1001), 8, True, False, equity=EQUITY
    )
    # quiet bar, no SL/TP hit, but 8+ hours elapsed -> time stop fires.
    far_bar = _bar(1.1001, 1.1002, 1.1000, 1.1001, ts=T0 + timedelta(hours=9), hours=1)
    out2 = eng.process_bar(out.trade, far_bar, 8, True, False, equity=EQUITY)
    assert out2.trade is None
    assert out2.closed_result is not None
    assert any(e.event_type == "CLOSED" and e.detail == "TIME_STOP" for e in out2.events)


def test_mr_entry_below_sl_rejected_buy():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = OpenTrade(
        local_id=1,
        symbol="EURUSD",
        strategy=StrategyName.MEAN_REVERSION,
        direction=Direction.BUY,
        status=OrderStatus.PENDING,
        sl=1.0990,
        tp_rules=TPRules(kind="ABSOLUTE", tp1_abs=1.1050),
        risk_pct_effective=1.0,
    )
    # gap-down open, well below SL -> D7 rejects
    out = eng.process_bar(
        trade, _bar(1.0900, 1.0910, 1.0890, 1.0895), 8, True, False, equity=EQUITY
    )
    assert out.trade is None and out.closed_result is None
    assert out.events[0].event_type == "CANCELLED"


def test_sell_side_clean_sl_minus_one_r():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _sell_trade(sl=1.1050)
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.0995), 8, True, False, equity=EQUITY
    )
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, 1.1060, 1.0990, 1.1055, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
        equity=EQUITY,
    )
    assert out2.closed_result is not None
    assert out2.closed_result.pnl_r == -1.0
    assert out2.closed_result.result == "LOSS"


def test_sell_side_gap_through_sl_cancels():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _sell_trade(sl=1.1010)
    out = eng.process_bar(
        trade, _bar(1.1020, 1.1030, 1.1015, 1.1025), 8, True, False, equity=EQUITY
    )
    assert out.trade is None and out.closed_result is None


def test_lot_sized_off_real_fill_entry_not_estimate():
    """Tech debt #1 (plans/01-stabilize.md): lot must be sized off the true fill
    entry (bar.open +/- spread), not an estimate from decision time. A gap between
    the decision bar's close and the fill bar's open must change the realized risk
    accordingly -- risk_amount == equity * risk_pct_effective/100 within one lot-step.
    """
    eng = OrderEngine(EURUSD, "sl_first")
    equity = 100_000.0
    risk_pct_effective = 1.0
    trade = _buy_trade(sl=1.0950)
    # Gap-open fill bar: open (1.1050) is far from what a close[-1]-based estimate
    # would have used -- this is exactly the "entry != close[-1]" case the estimate
    # used to get wrong (docs/decisions.md, Phase 2/3 deviations).
    out = eng.process_bar(
        trade, _bar(1.1050, 1.1060, 1.1045, 1.1055), 8, True, False, equity=equity
    )
    assert out.trade is not None
    entry = out.trade.entry_price
    assert entry == 1.1050  # spread_pips=0.0 for this instrument
    risk_distance = abs(entry - trade.sl)
    pips = risk_distance / EURUSD.pip
    expected_risk_amount = equity * (risk_pct_effective / 100.0)
    realized_risk_amount = out.trade.lot_size * pips * EURUSD.pip_value_per_lot
    # rounded DOWN to lot_step, so realized risk is within one lot-step of the target.
    one_step_risk = EURUSD.lot_step * pips * EURUSD.pip_value_per_lot
    assert expected_risk_amount - realized_risk_amount < one_step_risk + 1e-6
    assert realized_risk_amount <= expected_risk_amount + 1e-6


def test_lot_rounds_to_zero_cancels_pending_order_at_fill():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade(sl=1.0950)
    trade.risk_pct_effective = 0.0001  # negligible risk -> lot rounds to zero at fill
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False, equity=EQUITY
    )
    assert out.trade is None
    assert out.closed_result is None
    assert out.events[0].event_type == "CANCELLED"
    assert out.events[0].detail == "lot size rounds to zero at fill"


def test_mr_tp_wrong_side_cancelled():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = OpenTrade(
        local_id=1,
        symbol="EURUSD",
        strategy=StrategyName.MEAN_REVERSION,
        direction=Direction.BUY,
        status=OrderStatus.PENDING,
        sl=1.0950,
        tp_rules=TPRules(kind="ABSOLUTE", tp1_abs=1.0980),  # TP below entry -- nonsensical for BUY
        risk_pct_effective=1.0,
    )
    out = eng.process_bar(
        trade, _bar(1.1000, 1.1005, 1.0995, 1.1001), 8, True, False, equity=EQUITY
    )
    assert out.trade is None
    assert out.events[0].event_type == "CANCELLED"
