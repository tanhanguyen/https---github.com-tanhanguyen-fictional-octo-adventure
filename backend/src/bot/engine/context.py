"""Builds a FilterContext once per bar: computes every indicator exactly once (shared
across all 16 filters + both strategies) from C11-guarded closed bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from bot.config.models import BotConfig
from bot.core.timeframes import higher_tf, tf_duration
from bot.core.types import InstrumentSpec
from bot.data.feed import Feed
from bot.engine.order_engine import OpenTrade, OrderEngine
from bot.filters.base import FilterContext
from bot.indicators.adx import adx
from bot.indicators.atr import atr
from bot.indicators.efficiency_ratio import efficiency_ratio
from bot.indicators.ema import ema
from bot.indicators.rsi import rsi
from bot.indicators.sma import sma
from bot.indicators.zscore import zscore
from bot.strategies.base import BreakoutState

LOOKBACK = 300


@dataclass
class AccountState:
    # Portfolio-wide (plan 04): total open/pending trades across all symbols.
    open_trades_count: int
    daily_loss_count: int
    consecutive_wins: int
    consecutive_losses: int
    equity: float
    last_trade_result: str | None = None
    # Per-symbol (plan 04): does THIS symbol already have an open/pending trade.
    symbol_open_trade: bool = False
    # Portfolio-wide (plan 04): sum of risk_pct_effective across open/pending trades.
    open_risk_pct_total: float = 0.0


@dataclass
class SymbolContext:
    """Plan 04: per-symbol run-time state the portfolio Runner threads through each
    merged clock tick. One instance per entry in `BotConfig.symbols`."""

    symbol: str
    effective_config: BotConfig
    price_feed: Feed
    order_engine: OrderEngine
    time_stop_hours: float
    breakout_state: BreakoutState
    cursor: datetime  # next bar-open to process on this symbol's own timeframe
    trade: OpenTrade | None = None
    trade_db_id: int | None = None


def build_symbol_context(
    effective_config: BotConfig, price_feed: Feed, instrument: InstrumentSpec
) -> SymbolContext:
    """Shared by CLI and API: builds one symbol's run-time state from its own effective
    (already-merged) config, feed and instrument spec (plan 04)."""
    tf = effective_config.timeframe
    ts_cfg = effective_config.filters.time_stop
    if ts_cfg.bars is not None:
        time_stop_hours = ts_cfg.bars * tf_duration(tf).total_seconds() / 3600.0
    else:
        time_stop_hours = ts_cfg.hours

    order_engine = OrderEngine(
        instrument,
        effective_config.risk.intrabar_priority,
        costs=effective_config.execution.costs,
    )
    first_ts = price_feed.frames[tf].index[0].to_pydatetime()
    return SymbolContext(
        symbol=effective_config.symbol,
        effective_config=effective_config,
        price_feed=price_feed,
        order_engine=order_engine,
        time_stop_hours=time_stop_hours,
        breakout_state=BreakoutState.initial(),
        cursor=first_ts,
    )


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
        symbol_open_trade=account.symbol_open_trade,
        open_risk_pct_total=account.open_risk_pct_total,
        htf_ema_fast_close=htf_fast,
        htf_ema_slow_close=htf_slow,
        htf_timeframe=htf,
        dxy_change_1h_pct=dxy_change,
    )
