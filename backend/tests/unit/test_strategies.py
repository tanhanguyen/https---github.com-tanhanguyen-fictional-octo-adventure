"""Strategy tests over engineered OHLC fixtures (tests/fixtures/ohlc/*.csv)."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bot.config.loader import load_default_config
from bot.core.types import Direction, StrategyName
from bot.filters.base import FilterContext
from bot.indicators.adx import adx
from bot.indicators.atr import atr
from bot.indicators.ema import ema
from bot.indicators.rsi import rsi
from bot.strategies import breakout_retest, mean_reversion
from bot.strategies.base import BreakoutState

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ohlc"


def _load_csv(name: str) -> pd.DataFrame:
    with open(FIXTURES / name, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    df = pd.DataFrame(rows)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_ts"] = pd.to_datetime(df["open_ts"])
    return df


def _df_from_rows(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    """rows: (open, high, low, close, volume) tuples, one synthetic hourly bar each."""
    start = datetime(2024, 6, 3, 0, 0)
    return pd.DataFrame(
        {
            "open_ts": [start + timedelta(hours=i) for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [r[4] for r in rows],
        }
    )


def _consolidation_rows(n: int = 35) -> list[tuple[float, float, float, float, float]]:
    """A tight ~0.0012-wide range so range_high/range_low and ATR14 land at predictable,
    small values -- lets BRB fixtures below engineer Peak1/retest thresholds by hand.

    `n` must exceed `breakout.range_period` (30 since spec_v2 §3) so the whole range
    window is consolidation and range_high/range_low are the flat values above."""
    rows = []
    for i in range(n):
        o = 1.1000
        c = 1.1000 + (0.0001 if i % 2 == 0 else -0.0001)
        h = max(o, c) + 0.0006
        low_ = min(o, c) - 0.0006
        rows.append((o, h, low_, c, 1000.0 + i))
    return rows


def _ctx_at(df: pd.DataFrame, i: int, cfg) -> FilterContext:
    sub = df.iloc[: i + 1]
    close, high, low, open_ = sub["close"], sub["high"], sub["low"], sub["open"]
    now: datetime = sub["open_ts"].iloc[-1].to_pydatetime()
    return FilterContext(
        config=cfg,
        now=now,
        symbol="EURUSD",
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=sub["volume"],
        ema_fast_close=ema(close, 34),
        ema_fast_high=ema(high, 34),
        ema_fast_low=ema(low, 34),
        ema_slow_close=ema(close, 89),
        adx=adx(high, low, close, 14),
        er=pd.Series([float("nan")] * len(sub)),
        rsi=rsi(close, 14),
        atr14=atr(high, low, close, 14),
        atr5=atr(high, low, close, 5),
        atr_zscore=pd.Series([float("nan")] * len(sub)),
        volume_ma=pd.Series([float("nan")] * len(sub)),
        signal=None,
    )


def test_breakout_retest_fires_buy_signal():
    cfg = load_default_config()
    df = _load_csv("breakout_retest_clean.csv")
    state = BreakoutState.initial()
    signal = None
    for i in range(len(df)):
        ctx = _ctx_at(df, i, cfg)
        signal, state = breakout_retest.evaluate(ctx, state, cfg.strategies.breakout, cfg.risk)
        if signal is not None:
            break
    assert signal is not None, "expected a breakout-retest signal to fire"
    assert signal.direction in (Direction.BUY, Direction.SELL)
    assert signal.strategy == StrategyName.BREAKOUT
    assert signal.range_high is not None and signal.range_low is not None


def test_breakout_sl_mirror_formula():
    atr14, sl_scale = 0.0010, 1.5
    # BUY anchors at min(retest_low, range_high): retest bar dipped below the level.
    sl_buy = breakout_retest.compute_sl(
        Direction.BUY,
        range_high=1.1050,
        range_low=1.1000,
        retest_high=1.1065,
        retest_low=1.1045,
        atr14=atr14,
        sl_scale=sl_scale,
    )
    assert sl_buy == pytest.approx(1.1045 - 0.5 * atr14 * sl_scale)
    # SELL anchors at max(retest_high, range_low).
    sl_sell = breakout_retest.compute_sl(
        Direction.SELL,
        range_high=1.1050,
        range_low=1.1000,
        retest_high=1.1008,
        retest_low=1.0990,
        atr14=atr14,
        sl_scale=sl_scale,
    )
    assert sl_sell == pytest.approx(1.1008 + 0.5 * atr14 * sl_scale)


def test_breakout_sl_capped_at_broken_level():
    """The anchor never sits beyond the broken level: a shallow retest that only
    touched the tolerance zone above range_high still gets its SL below the level."""
    atr14, sl_scale = 0.0010, 1.0
    sl_buy = breakout_retest.compute_sl(
        Direction.BUY,
        range_high=1.1050,
        range_low=1.1000,
        retest_high=1.1070,
        retest_low=1.1055,  # stayed above the level
        atr14=atr14,
        sl_scale=sl_scale,
    )
    assert sl_buy == pytest.approx(1.1050 - 0.5 * atr14 * sl_scale)


def _run_brb(rows, cfg=None) -> tuple[list, object]:
    """Run breakout_retest.evaluate() bar-by-bar over `rows`; return (state-history,
    final signal-or-None). Stops at the first fired signal, like the state machine
    would (a signal always resets state to initial())."""
    cfg = cfg or load_default_config()
    df = _df_from_rows(rows)
    state = BreakoutState.initial()
    history = []
    signal = None
    for i in range(len(df)):
        ctx = _ctx_at(df, i, cfg)
        signal, state = breakout_retest.evaluate(ctx, state, cfg.strategies.breakout, cfg.risk)
        history.append(state)
        if signal is not None:
            break
    return history, signal


def test_brb_full_cycle_fires_signal_with_peak1_and_retest():
    """docs/spec_v2.md §2: breakout-1 -> Peak1 -> retest (confirmation candle) ->
    breakout-2 fires the signal carrying peak1/retest_low/retest_high/retest_bars_ago."""
    rows = (
        _consolidation_rows()
        + [
            (1.1000, 1.1030, 1.0995, 1.1025, 2000.0),  # breakout-1: close > range_high
            (1.1025, 1.1055, 1.1020, 1.1050, 2001.0),  # Peak1 forming
            (1.1050, 1.1075, 1.1045, 1.1070, 2002.0),  # Peak1 confirmed (>= 1.0xATR)
            (1.1040, 1.1045, 1.1000, 1.1038, 2003.0),  # retest: long lower wick (pin bar)
            (1.1038, 1.1090, 1.1035, 1.1085, 2004.0),  # breakout-2: close > peak1
        ]
    )
    history, signal = _run_brb(rows)
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.strategy == StrategyName.BREAKOUT
    assert signal.peak1 is not None
    assert signal.retest_low is not None and signal.retest_high is not None
    assert signal.retest_bars_ago is not None and signal.retest_bars_ago >= 1
    # every intermediate phase was actually visited (not skipped)
    statuses = [s.status for s in history]
    assert "AWAITING_PEAK" in statuses
    assert "AWAITING_RETEST" in statuses
    assert "AWAITING_BREAKOUT2" in statuses


def test_brb_resets_when_peak1_never_confirmed_within_budget():
    cfg = load_default_config()
    rows = _consolidation_rows() + [(1.1000, 1.1030, 1.0995, 1.1025, 2000.0)]
    # highs stay within the Peak1 distance threshold (< 1.0xATR above range_high) for
    # longer than peak_max_bars -> the setup must be abandoned, not left pending.
    for i in range(cfg.strategies.breakout.peak_max_bars + 2):
        rows.append((1.1025, 1.1009, 1.1005, 1.1007, 2100.0 + i))
    history, signal = _run_brb(rows, cfg)
    assert signal is None
    assert history[-1].status == "NONE"
    assert history[-1].peak1 is None


def test_brb_resets_when_retest_never_arrives_within_budget():
    cfg = load_default_config()
    rows = _consolidation_rows() + [
        (1.1000, 1.1030, 1.0995, 1.1025, 2000.0),
        (1.1025, 1.1075, 1.1020, 1.1070, 2001.0),  # Peak1 confirmed
    ]
    # price never comes back down toward range_high -> retest budget expires.
    for i in range(cfg.strategies.breakout.retest_confirm_max_bars + 2):
        rows.append((1.1070, 1.1072, 1.1069, 1.1071, 2200.0 + i))
    history, signal = _run_brb(rows, cfg)
    assert signal is None
    assert history[-1].status == "NONE"


def test_brb_resets_when_breakout2_never_arrives_within_budget():
    cfg = load_default_config()
    rows = _consolidation_rows() + [
        (1.1000, 1.1030, 1.0995, 1.1025, 2000.0),
        (1.1025, 1.1075, 1.1020, 1.1070, 2001.0),  # Peak1 confirmed at 1.1075
        (1.1040, 1.1045, 1.1000, 1.1038, 2003.0),  # retest confirmed
    ]
    # price never closes back above peak1 (1.1075) -> breakout-2 budget expires.
    for i in range(cfg.strategies.breakout.breakout2_max_bars + 2):
        rows.append((1.1038, 1.1040, 1.1035, 1.1037, 2500.0 + i))
    history, signal = _run_brb(rows, cfg)
    assert signal is None
    assert history[-1].status == "NONE"


def test_brb_resets_when_the_retest_breaks_deep_through_the_level():
    """spec_v2 §2 step 3: a retest that blows deep back through the range is a cancelled
    setup, not a retest. Without this the machine advanced to AWAITING_BREAKOUT2 with
    retest_low far below the level -- an SL anchored there always tripped `sl_too_wide`,
    and the dead setup held the state machine for another `breakout2_max_bars`."""
    cfg = load_default_config()
    rows = _consolidation_rows() + [
        (1.1000, 1.1030, 1.0995, 1.1025, 2000.0),
        (1.1025, 1.1075, 1.1020, 1.1070, 2001.0),  # Peak1 confirmed
        (1.1060, 1.1062, 1.0960, 1.0970, 2002.0),  # deep break, far past range_high
    ]
    history, signal = _run_brb(rows, cfg)
    assert signal is None
    assert "AWAITING_RETEST" in [s.status for s in history]
    assert history[-1].status == "NONE"
    assert history[-1].peak1 is None


def test_brb_shallow_retest_dip_is_still_accepted():
    """Control for the test above: dipping just under the level (inside
    `retest_max_depth_atr_mult`) must still advance to AWAITING_BREAKOUT2."""
    cfg = load_default_config()
    rows = _consolidation_rows() + [
        (1.1000, 1.1030, 1.0995, 1.1025, 2000.0),
        (1.1025, 1.1075, 1.1020, 1.1070, 2001.0),  # Peak1 confirmed
        (1.1040, 1.1045, 1.1000, 1.1038, 2002.0),  # retest: pin bar just under the level
    ]
    history, _signal = _run_brb(rows, cfg)
    assert history[-1].status == "AWAITING_BREAKOUT2"
    assert history[-1].retest_low == pytest.approx(1.1000)


def test_brb_fallback_matches_v1_2_when_require_second_breakout_false():
    """`require_second_breakout=false` collapses back to the v1.2 single-phase machine
    (retest IS the entry) -- the emitted signal carries no peak1/retest_bars_ago."""
    cfg = load_default_config()
    cfg.strategies.breakout.require_second_breakout = False
    df = _load_csv("breakout_retest_clean.csv")
    state = BreakoutState.initial()
    signal = None
    for i in range(len(df)):
        ctx = _ctx_at(df, i, cfg)
        signal, state = breakout_retest.evaluate(ctx, state, cfg.strategies.breakout, cfg.risk)
        if signal is not None:
            break
    assert signal is not None
    assert signal.peak1 is None
    assert signal.retest_bars_ago is None


def test_mean_reversion_fires_buy_on_oversold_bounce():
    cfg = load_default_config()
    df = _load_csv("mr_oversold_clean.csv")
    signal = None
    for i in range(len(df)):
        ctx = _ctx_at(df, i, cfg)
        signal = mean_reversion.evaluate(ctx, cfg.strategies.mean_reversion)
        if signal is not None:
            break
    assert signal is not None, "expected an MR BUY signal on the oversold bounce"
    assert signal.direction == Direction.BUY
    assert signal.strategy == StrategyName.MEAN_REVERSION


def test_mean_reversion_sl_mirror_formula():
    atr5, mult = 0.0008, 1.0
    sl_buy = mean_reversion.compute_sl(
        Direction.BUY, ema34_low=1.0950, ema34_high=1.1050, atr5=atr5, mult=mult
    )
    assert sl_buy == pytest.approx(1.0950 - mult * atr5)
    sl_sell = mean_reversion.compute_sl(
        Direction.SELL, ema34_low=1.0950, ema34_high=1.1050, atr5=atr5, mult=mult
    )
    assert sl_sell == pytest.approx(1.1050 + mult * atr5)


def test_mr_entry_below_sl_guard_would_cancel():
    """D7: BUY entry <= sl -> CANCELLED. The fixture engineers a violent gap-down open
    on the fill bar so that entry (open) ends up below the SL computed at decision time."""
    cfg = load_default_config()
    df = _load_csv("mr_entry_below_sl.csv")
    signal = None
    decision_idx = None
    for i in range(len(df) - 1):  # leave the last bar as the "fill" bar
        ctx = _ctx_at(df, i, cfg)
        signal = mean_reversion.evaluate(ctx, cfg.strategies.mean_reversion)
        if signal is not None:
            decision_idx = i
            break
    assert signal is not None and decision_idx is not None
    ctx = _ctx_at(df, decision_idx, cfg)
    sl = mean_reversion.compute_sl(
        signal.direction,
        ema34_low=ctx.ema_fast_low.iloc[-1],
        ema34_high=ctx.ema_fast_high.iloc[-1],
        atr5=ctx.atr5.iloc[-1],
        mult=cfg.strategies.mean_reversion.mr_sl_atr_mult,
    )
    fill_open = df["open"].iloc[decision_idx + 1]
    if signal.direction == Direction.BUY:
        assert fill_open <= sl, "fixture should engineer entry <= sl to exercise the D7 guard"
