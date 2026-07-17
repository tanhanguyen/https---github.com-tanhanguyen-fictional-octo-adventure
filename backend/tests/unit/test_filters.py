"""Table-driven filter tests: disabled / pass / fail / boundary / warmup per filter."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from bot.core.types import Direction, Signal, StrategyName
from bot.filters import (
    account_risk,
    adx_filter,
    atr_ref,
    atr_zscore,
    confirmation_lag,
    dxy,
    equity_curve,
    er_filter,
    mtf,
    news,
    range_width,
    session,
    time_stop,
    trend,
    volume,
    wick,
)


def _disable(ctx, filter_id):
    cfg2 = ctx.config.model_copy(deep=True)
    getattr(cfg2.filters, filter_id).enabled = False
    return replace(ctx, config=cfg2)


def test_trend_disabled(base_ctx):
    r = trend.evaluate(_disable(base_ctx, "trend"))
    assert r.enabled is False and r.evaluated is False and r.passed is None and not r.blocking


def test_trend_bull(base_ctx):
    r = trend.evaluate(base_ctx)
    assert r.evaluated
    assert r.values["mode"] in ("BULL", "NEUTRAL", "BEAR")


def test_trend_warmup():

    n = 5
    s = pd.Series([1.0] * n)
    ctx = _minimal_ctx(close=s, high=s, low=s, open_=s)
    r = trend.evaluate(ctx)
    assert r.passed is None and not r.evaluated and r.detail.startswith("indicator warmup")


def _minimal_ctx(**overrides):
    from bot.config.loader import load_default_config
    from bot.filters.base import FilterContext

    cfg = load_default_config()
    n = len(overrides.get("close", pd.Series([1.0])))
    nan_series = pd.Series([float("nan")] * n)
    defaults = dict(
        config=cfg,
        now=datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc),
        symbol="EURUSD",
        open_=nan_series,
        high=nan_series,
        low=nan_series,
        close=nan_series,
        volume=pd.Series([1000.0] * n),
        ema_fast_close=nan_series,
        ema_fast_high=nan_series,
        ema_fast_low=nan_series,
        ema_slow_close=nan_series,
        adx=nan_series,
        er=nan_series,
        rsi=nan_series,
        atr14=nan_series,
        atr5=nan_series,
        atr_zscore=nan_series,
        volume_ma=nan_series,
        signal=None,
        open_trades_count=0,
        daily_loss_count=0,
        consecutive_wins=0,
        consecutive_losses=0,
        equity=10_000.0,
        htf_ema_fast_close=None,
        htf_ema_slow_close=None,
        htf_timeframe="4H",
        dxy_change_1h_pct=float("nan"),
    )
    defaults.update(overrides)
    return FilterContext(**defaults)


def test_adx_filter_boundary_trend_strict(base_ctx):
    cfg2 = base_ctx.config.model_copy(deep=True)
    base_ctx = replace(base_ctx, config=cfg2)
    adx_series = base_ctx.adx.copy()
    adx_series.iloc[-1] = 30.0  # exactly threshold_trend -> NOT > -> not "trend"
    ctx = replace(base_ctx, adx=adx_series)
    r = adx_filter.evaluate(ctx)
    assert r.values["regime"] != "trend"


def test_adx_filter_disabled(base_ctx):
    r = adx_filter.evaluate(_disable(base_ctx, "adx_filter"))
    assert r.enabled is False and r.passed is None


def test_er_filter_boundary(base_ctx):
    er_series = base_ctx.er.copy()
    er_series.iloc[-1] = 0.3  # exactly threshold_range -> NOT < -> not "range"
    ctx = replace(base_ctx, er=er_series)
    r = er_filter.evaluate(ctx)
    assert r.values["regime"] != "range"


def test_atr_ref_locked_still_toggle(base_ctx):
    r = atr_ref.evaluate(base_ctx)
    assert r.enabled and r.evaluated
    assert "atr14" in r.values and "atr5" in r.values


def test_atr_zscore_off_below_threshold(base_ctx):
    z = base_ctx.atr_zscore.copy()
    z.iloc[-1] = -2.0
    ctx = replace(base_ctx, atr_zscore=z)
    r = atr_zscore.evaluate(ctx)
    assert not r.passed and r.blocking
    assert r.values["allow_breakout"] is False and r.values["allow_mean_reversion"] is False


def test_atr_zscore_boundary_one_point_zero_goes_normal(base_ctx):
    z = base_ctx.atr_zscore.copy()
    z.iloc[-1] = 1.0
    ctx = replace(base_ctx, atr_zscore=z)
    r = atr_zscore.evaluate(ctx)
    assert r.values["sl_scale"] == pytest.approx(1.0)


def test_atr_zscore_breakout_only_above_2(base_ctx):
    z = base_ctx.atr_zscore.copy()
    z.iloc[-1] = 2.5
    ctx = replace(base_ctx, atr_zscore=z)
    r = atr_zscore.evaluate(ctx)
    assert r.values["allow_mean_reversion"] is False
    assert r.values["allow_breakout"] is True


def test_volume_disabled_by_default(base_ctx):
    r = volume.evaluate(base_ctx)
    assert r.enabled is False  # off for FOREX per plan


def test_volume_pass_and_fail(base_ctx):
    cfg2 = base_ctx.config.model_copy(deep=True)
    cfg2.filters.volume.enabled = True
    signal = Signal(
        direction=Direction.BUY, strategy=StrategyName.BREAKOUT, signal_bar_ts=base_ctx.now
    )
    ctx = replace(base_ctx, config=cfg2, signal=signal)
    vol = ctx.volume.copy()
    vol.iloc[-1] = 10000.0  # far above MA*1.5
    ctx = replace(ctx, volume=vol)
    r = volume.evaluate(ctx)
    assert r.passed

    vol.iloc[-1] = 1.0
    ctx = replace(ctx, volume=vol)
    r = volume.evaluate(ctx)
    assert not r.passed and r.blocking


def test_session_in_and_out(base_ctx):
    r = session.evaluate(base_ctx)
    assert r.passed  # fixture ts is 10:00 UTC Monday -> within London window

    out_of_session = replace(base_ctx, now=datetime(2024, 6, 2, 2, 0, tzinfo=timezone.utc))
    r2 = session.evaluate(out_of_session)
    assert not r2.passed and r2.blocking


def test_session_disabled(base_ctx):
    r = session.evaluate(_disable(base_ctx, "session"))
    assert r.enabled is False


def test_mtf_no_higher_tf_passes(base_ctx):
    ctx = replace(base_ctx, htf_timeframe=None)
    r = mtf.evaluate(ctx)
    assert r.passed


def test_mtf_blocks_buy_when_htf_bear(base_ctx):
    n = len(base_ctx.close)
    fast = pd.Series([1.0] * n)
    slow = pd.Series([2.0] * n)  # fast < slow -> BEAR
    signal = Signal(
        direction=Direction.BUY, strategy=StrategyName.BREAKOUT, signal_bar_ts=base_ctx.now
    )
    ctx = replace(base_ctx, htf_ema_fast_close=fast, htf_ema_slow_close=slow, signal=signal)
    r = mtf.evaluate(ctx)
    assert not r.passed and r.blocking


def test_mtf_no_signal_still_reports_htf_trend(base_ctx):
    n = len(base_ctx.close)
    fast = pd.Series([1.0] * n)
    slow = pd.Series([2.0] * n)
    ctx = replace(base_ctx, htf_ema_fast_close=fast, htf_ema_slow_close=slow, signal=None)
    r = mtf.evaluate(ctx)
    assert r.passed is None
    assert r.values["htf_trend"] == "BEAR"


def test_dxy_not_applicable_non_forex(base_ctx):
    cfg2 = base_ctx.config.model_copy(deep=True)
    cfg2.symbol_type = "CRYPTO"
    ctx = replace(base_ctx, config=cfg2)
    r = dxy.evaluate(ctx)
    assert r.passed


def test_dxy_blocks_buy_on_usd_strength(base_ctx):
    signal = Signal(
        direction=Direction.BUY, strategy=StrategyName.BREAKOUT, signal_bar_ts=base_ctx.now
    )
    ctx = replace(base_ctx, signal=signal, dxy_change_1h_pct=0.5)
    r = dxy.evaluate(ctx)
    assert not r.passed and r.blocking


def test_confirmation_lag_pass_fail(base_ctx):
    close = base_ctx.close.copy()
    close.iloc[-1] = close.iloc[-2] + 1.0  # confirms BUY
    signal = Signal(
        direction=Direction.BUY, strategy=StrategyName.BREAKOUT, signal_bar_ts=base_ctx.now
    )
    ctx = replace(base_ctx, close=close, signal=signal)
    r = confirmation_lag.evaluate(ctx)
    assert r.passed

    close.iloc[-1] = close.iloc[-2] - 1.0  # does NOT confirm BUY
    ctx = replace(ctx, close=close)
    r = confirmation_lag.evaluate(ctx)
    assert not r.passed and r.blocking


def test_equity_curve_win_streak_reduces_risk(base_ctx):
    ctx = replace(base_ctx, consecutive_wins=3)
    r = equity_curve.evaluate(ctx)
    assert r.values["risk_multiplier"] == base_ctx.config.filters.equity_curve.win_reduce_to


def test_equity_curve_loss_streak_reduces_risk(base_ctx):
    ctx = replace(base_ctx, consecutive_losses=2)
    r = equity_curve.evaluate(ctx)
    assert r.values["risk_multiplier"] == base_ctx.config.filters.equity_curve.loss_reduce_to


def test_equity_curve_default_multiplier_one(base_ctx):
    r = equity_curve.evaluate(base_ctx)
    assert r.values["risk_multiplier"] == 1.0


def test_time_stop_disabled(base_ctx):
    r = time_stop.evaluate(_disable(base_ctx, "time_stop"))
    assert r.enabled is False


def test_time_stop_predicate():
    from datetime import timedelta

    entry = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert time_stop.is_expired(entry, entry + timedelta(hours=8), 8, False, False) is True
    assert (
        time_stop.is_expired(entry, entry + timedelta(hours=7, minutes=59), 8, False, False)
        is False
    )
    assert (
        time_stop.is_expired(entry, entry + timedelta(hours=20), 8, True, False) is False
    )  # after TP1, disabled
    assert (
        time_stop.is_expired(entry, entry + timedelta(hours=20), 8, True, True) is True
    )  # after_tp1=True


def test_range_width_pass_fail(base_ctx):
    high = base_ctx.high.copy()
    low = base_ctx.low.copy()
    high.iloc[-20:] = 105.0
    low.iloc[-20:] = 104.9  # tiny range -> fails
    ctx = replace(base_ctx, high=high, low=low)
    r = range_width.evaluate(ctx)
    assert not r.passed and r.blocking

    high.iloc[-20:] = 200.0  # huge range -> passes
    ctx = replace(base_ctx, high=high, low=low)
    r = range_width.evaluate(ctx)
    assert r.passed


def test_account_risk_daily_loss_limit(base_ctx):
    ctx = replace(base_ctx, daily_loss_count=3)
    r = account_risk.evaluate(ctx)
    assert not r.passed and r.blocking
    assert r.values["reason"] == "daily_loss_limit_reached"


def test_account_risk_one_trade_per_symbol(base_ctx):
    ctx = replace(base_ctx, open_trades_count=1)
    r = account_risk.evaluate(ctx)
    assert not r.passed and r.blocking
    assert r.values["reason"] == "max_concurrent_trades_reached"
    assert r.values["stage"] == "one_trade_per_symbol"


def test_account_risk_ok(base_ctx):
    r = account_risk.evaluate(base_ctx)
    assert r.passed


def test_wick_pass_fail_boundary(base_ctx):
    signal = Signal(
        direction=Direction.BUY, strategy=StrategyName.BREAKOUT, signal_bar_ts=base_ctx.now
    )
    open_ = base_ctx.open_.copy()
    high = base_ctx.high.copy()
    low = base_ctx.low.copy()
    close = base_ctx.close.copy()
    open_.iloc[-1] = 10.0
    high.iloc[-1] = 10.5
    low.iloc[-1] = 9.5
    close.iloc[-1] = 10.0  # ratio exactly 0.5 -> boundary pass
    ctx = replace(base_ctx, open_=open_, high=high, low=low, close=close, signal=signal)
    r = wick.evaluate(ctx)
    assert r.passed

    low.iloc[-1] = 9.9  # thin wick -> fail
    ctx = replace(ctx, low=low)
    r = wick.evaluate(ctx)
    assert not r.passed and r.blocking


def test_wick_not_applicable_mean_reversion(base_ctx):
    signal = Signal(
        direction=Direction.BUY, strategy=StrategyName.MEAN_REVERSION, signal_bar_ts=base_ctx.now
    )
    ctx = replace(base_ctx, signal=signal)
    r = wick.evaluate(ctx)
    assert r.passed


def test_news_off_by_default(base_ctx):
    r = news.evaluate(base_ctx)
    assert r.enabled is False


def test_news_blocks_within_blacklist(base_ctx):
    cfg2 = base_ctx.config.model_copy(deep=True)
    cfg2.filters.news.enabled = True
    cfg2.filters.news.blacklist_utc = ["2024-06-03T09:00:00+00:00/2024-06-03T11:00:00+00:00"]
    ctx = replace(base_ctx, config=cfg2)  # now=10:00 UTC -> inside window
    r = news.evaluate(ctx)
    assert not r.passed and r.blocking
