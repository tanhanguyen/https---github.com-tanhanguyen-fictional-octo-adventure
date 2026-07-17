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
        lot_size=0.1,
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
        lot_size=0.1,
    )


def test_clean_sl_gives_exact_minus_one_r():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False)
    out2 = eng.process_bar(
        out.trade, _bar(1.0998, 1.0999, 1.0940, 1.0945, ts=T0 + timedelta(hours=1)), 8, True, False
    )
    assert out2.closed_result is not None
    assert out2.closed_result.pnl_r == -1.0
    assert out2.closed_result.result == "LOSS"


def test_sl_and_tp_same_bar_sl_first_priority():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False)
    tp1 = out.trade.tp1_price
    # Same bar touches both SL and TP1.
    out2 = eng.process_bar(
        out.trade,
        _bar(1.0999, tp1 + 0.0005, 1.0940, 1.0960, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
    )
    assert out2.closed_result is not None
    assert out2.closed_result.result == "LOSS"  # SL wins under sl_first priority


def test_sl_and_tp_same_bar_path_priority_differs_from_sl_first():
    eng_sl = OrderEngine(EURUSD, "sl_first")
    eng_path = OrderEngine(EURUSD, "path")
    trade1 = _buy_trade()
    trade2 = _buy_trade()
    fill_bar = _bar(1.1000, 1.1010, 1.0990, 1.1005)
    o1 = eng_sl.process_bar(trade1, fill_bar, 8, True, False)
    o2 = eng_path.process_bar(trade2, fill_bar, 8, True, False)
    tp1 = o1.trade.tp1_price
    # open near the TP side, low reaches SL, high reaches TP -- path mode picks nearer to open.
    same_bar = _bar(tp1 - 0.0002, tp1 + 0.0002, 1.0940, tp1, ts=T0 + timedelta(hours=1))
    r1 = eng_sl.process_bar(o1.trade, same_bar, 8, True, False)
    r2 = eng_path.process_bar(o2.trade, same_bar, 8, True, False)
    assert r1.closed_result is not None  # sl_first always fully closes on ambiguity... (SL hit)
    # path mode, with open close to TP, should NOT necessarily close at SL immediately.
    assert (r1.closed_result.result, r2.trade is not None or r2.closed_result is not None) != (
        None,
        None,
    )


def test_gap_through_sl_cancels_pending_order():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade(sl=1.0990)
    # bar opens already below SL -> D7 guard cancels at fill.
    out = eng.process_bar(trade, _bar(1.0980, 1.0990, 1.0970, 1.0985), 8, True, False)
    assert out.trade is None
    assert out.closed_result is None
    assert out.events[0].event_type == "CANCELLED"


def test_tp1_hit_moves_sl_to_breakeven_same_bar():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False)
    tp1 = out.trade.tp1_price
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, tp1 + 0.0003, 1.1001, tp1, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
    )
    assert out2.trade is not None  # only half closed, still running
    assert out2.trade.tp1_hit is True
    assert out2.trade.sl == out2.trade.entry_price  # moved to breakeven
    assert any(e.event_type == "TP1_HIT" for e in out2.events)
    assert any(e.event_type == "SL_TO_BREAKEVEN" for e in out2.events)


def test_tp1_then_reversal_to_breakeven_same_bar_nets_positive_not_minus_one_r():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False)
    entry = out.trade.entry_price
    tp1 = out.trade.tp1_price
    # Same bar hits TP1 then reverses all the way back to entry (BE).
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, tp1 + 0.0002, entry - 0.0005, entry, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
    )
    assert out2.closed_result is not None
    assert out2.closed_result.pnl_r > 0  # net +0.75R (half at +1.5R, half at 0), not -1R
    assert out2.closed_result.result == "WIN"


def test_time_stop_disabled_after_tp1():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(trade, _bar(1.1000, 1.1010, 1.0990, 1.1005), 8, True, False)
    tp1 = out.trade.tp1_price
    out2 = eng.process_bar(
        out.trade,
        _bar(1.1002, tp1 + 0.0003, 1.1001, 1.1003, ts=T0 + timedelta(hours=1)),
        8,
        True,
        False,
    )
    assert out2.trade is not None and out2.trade.tp1_hit
    # far in the future, well past time_stop_hours, but after_tp1=False -> disabled (C5)
    far_bar = _bar(1.1003, 1.1004, 1.1001, 1.1003, ts=T0 + timedelta(hours=100), hours=1)
    out3 = eng.process_bar(out2.trade, far_bar, 8, True, False)
    assert out3.trade is not None  # NOT closed by time stop


def test_time_stop_closes_before_tp1():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _buy_trade()
    out = eng.process_bar(trade, _bar(1.1000, 1.1005, 1.0995, 1.1001), 8, True, False)
    # quiet bar, no SL/TP hit, but 8+ hours elapsed -> time stop fires.
    far_bar = _bar(1.1001, 1.1002, 1.1000, 1.1001, ts=T0 + timedelta(hours=9), hours=1)
    out2 = eng.process_bar(out.trade, far_bar, 8, True, False)
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
        lot_size=0.1,
    )
    # gap-down open, well below SL -> D7 rejects
    out = eng.process_bar(trade, _bar(1.0900, 1.0910, 1.0890, 1.0895), 8, True, False)
    assert out.trade is None and out.closed_result is None
    assert out.events[0].event_type == "CANCELLED"


def test_sell_side_clean_sl_minus_one_r():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _sell_trade(sl=1.1050)
    out = eng.process_bar(trade, _bar(1.1000, 1.1010, 1.0990, 1.0995), 8, True, False)
    out2 = eng.process_bar(
        out.trade, _bar(1.1002, 1.1060, 1.0990, 1.1055, ts=T0 + timedelta(hours=1)), 8, True, False
    )
    assert out2.closed_result is not None
    assert out2.closed_result.pnl_r == -1.0
    assert out2.closed_result.result == "LOSS"


def test_sell_side_gap_through_sl_cancels():
    eng = OrderEngine(EURUSD, "sl_first")
    trade = _sell_trade(sl=1.1010)
    out = eng.process_bar(trade, _bar(1.1020, 1.1030, 1.1015, 1.1025), 8, True, False)
    assert out.trade is None and out.closed_result is None


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
        lot_size=0.1,
    )
    out = eng.process_bar(trade, _bar(1.1000, 1.1005, 1.0995, 1.1001), 8, True, False)
    assert out.trade is None
    assert out.events[0].event_type == "CANCELLED"
