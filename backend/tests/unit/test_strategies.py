"""Strategy tests over engineered OHLC fixtures (tests/fixtures/ohlc/*.csv)."""

from __future__ import annotations

import csv
from datetime import datetime
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
