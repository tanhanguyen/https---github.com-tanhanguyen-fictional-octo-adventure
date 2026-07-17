from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from bot.config.loader import load_default_config
from bot.filters.base import FilterContext


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


@pytest.fixture
def base_ctx() -> FilterContext:
    """A fully warmed-up context: 120 bars of mild uptrend, all indicators non-NaN,
    NEUTRAL/BULL-ish trend, ADX/ER in the 'trend' zone, atr_zscore near 0."""
    cfg = load_default_config()
    n = 120
    close = [100.0 + 0.05 * i for i in range(n)]
    high = [c + 0.3 for c in close]
    low = [c - 0.3 for c in close]
    open_ = [c - 0.02 for c in close]
    volume = [1000.0 + (i % 5) * 10 for i in range(n)]

    from bot.indicators.adx import adx
    from bot.indicators.atr import atr
    from bot.indicators.efficiency_ratio import efficiency_ratio
    from bot.indicators.ema import ema
    from bot.indicators.rsi import rsi
    from bot.indicators.sma import sma
    from bot.indicators.zscore import zscore

    close_s, high_s, low_s, open_s, vol_s = (
        _series(close),
        _series(high),
        _series(low),
        _series(open_),
        _series(volume),
    )
    atr14 = atr(high_s, low_s, close_s, 14)
    atr5 = atr(high_s, low_s, close_s, 5)

    return FilterContext(
        config=cfg,
        now=datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc),  # Monday 10:00 UTC -> London session
        symbol="EURUSD",
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
        atr5=atr5,
        atr_zscore=zscore(atr14, 100),
        volume_ma=sma(vol_s, 20),
        signal=None,
        open_trades_count=0,
        daily_loss_count=0,
        consecutive_wins=0,
        consecutive_losses=0,
        equity=10_000.0,
        htf_ema_fast_close=None,
        htf_ema_slow_close=None,
        htf_timeframe="4H",
        dxy_change_1h_pct=0.0,
    )
