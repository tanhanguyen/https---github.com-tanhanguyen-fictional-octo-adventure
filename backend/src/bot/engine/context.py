"""Builds a FilterContext once per bar: computes every indicator exactly once (shared
across all 16 filters + both strategies) from C11-guarded closed bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from bot.config.models import BotConfig
from bot.core.timeframes import higher_tf
from bot.data.feed import Feed
from bot.filters.base import FilterContext
from bot.indicators.adx import adx
from bot.indicators.atr import atr
from bot.indicators.efficiency_ratio import efficiency_ratio
from bot.indicators.ema import ema
from bot.indicators.rsi import rsi
from bot.indicators.sma import sma
from bot.indicators.zscore import zscore

LOOKBACK = 300


@dataclass
class AccountState:
    open_trades_count: int
    daily_loss_count: int
    consecutive_wins: int
    consecutive_losses: int
    equity: float
    last_trade_result: str | None = None


def build_context(
    price_feed: Feed,
    dxy_feed: Feed | None,
    config: BotConfig,
    now: datetime,
    account: AccountState,
    lookback: int = LOOKBACK,
) -> FilterContext:
    primary = config.timeframe
    bars = price_feed.bars(primary, now, lookback)

    close, high, low, open_, volume = (
        bars["close"],
        bars["high"],
        bars["low"],
        bars["open"],
        bars["volume"],
    )

    f = config.filters
    ema_fast_close = ema(close, f.trend.ema_fast)
    ema_fast_high = ema(high, f.trend.ema_fast)
    ema_fast_low = ema(low, f.trend.ema_fast)
    ema_slow_close = ema(close, f.trend.ema_slow)
    adx_s = adx(high, low, close, f.adx_filter.period)
    er_s = efficiency_ratio(close, f.er_filter.period)
    rsi_s = rsi(close, config.strategies.mean_reversion.rsi_period)
    atr14 = atr(high, low, close, f.atr_ref.period14)
    atr5 = atr(high, low, close, f.atr_ref.period5)
    atr_z = zscore(atr14, f.atr_zscore.window)
    volume_ma = sma(volume, f.volume.period)

    htf = higher_tf(primary)
    htf_fast: pd.Series | None = None
    htf_slow: pd.Series | None = None
    if htf is not None:
        htf_bars = price_feed.bars(htf, now, lookback)
        if len(htf_bars) > 0:
            htf_fast = ema(htf_bars["close"], f.trend.ema_fast)
            htf_slow = ema(htf_bars["close"], f.trend.ema_slow)

    dxy_change: float | None = None
    if dxy_feed is not None and config.symbol_type == "FOREX":
        dxy_bars = dxy_feed.bars("1H", now, f.dxy.lookback_hours + 1)
        if len(dxy_bars) >= f.dxy.lookback_hours + 1:
            recent = dxy_bars["close"].iloc[-1]
            past = dxy_bars["close"].iloc[-(f.dxy.lookback_hours + 1)]
            dxy_change = ((recent - past) / past) * 100.0 if past != 0 else None

    return FilterContext(
        config=config,
        now=now,
        symbol=config.symbol,
        open_=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        ema_fast_close=ema_fast_close,
        ema_fast_high=ema_fast_high,
        ema_fast_low=ema_fast_low,
        ema_slow_close=ema_slow_close,
        adx=adx_s,
        er=er_s,
        rsi=rsi_s,
        atr14=atr14,
        atr5=atr5,
        atr_zscore=atr_z,
        volume_ma=volume_ma,
        signal=None,
        open_trades_count=account.open_trades_count,
        daily_loss_count=account.daily_loss_count,
        consecutive_wins=account.consecutive_wins,
        consecutive_losses=account.consecutive_losses,
        equity=account.equity,
        last_trade_result=account.last_trade_result,
        htf_ema_fast_close=htf_fast,
        htf_ema_slow_close=htf_slow,
        htf_timeframe=htf,
        dxy_change_1h_pct=dxy_change,
    )
