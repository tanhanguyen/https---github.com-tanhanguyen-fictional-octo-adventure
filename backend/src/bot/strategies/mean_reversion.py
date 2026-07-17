"""Strategy 2 — Mean Reversion via EMA34 channel + RSI (§5). Signal decided at close[-1]
(C2/D6); confirmation candle logic lives in the confirmation_lag filter (Phase B), not here."""

from __future__ import annotations

import math

from bot.config.models import MeanReversionConfig
from bot.core.types import Direction, Signal, StrategyName, TPRules
from bot.filters.base import FilterContext


def evaluate(ctx: FilterContext, mr_cfg: MeanReversionConfig) -> Signal | None:
    ema_high = ctx.ema_fast_high.iloc[-1]
    ema_low = ctx.ema_fast_low.iloc[-1]
    ema_close = ctx.ema_fast_close.iloc[-1]
    close = ctx.close.iloc[-1]
    rsi_v = ctx.rsi.iloc[-1]

    if any(math.isnan(v) for v in (ema_high, ema_low, ema_close, close, rsi_v)):
        return None

    overbought = ema_high + 0.5 * (ema_high - ema_close)
    oversold = ema_low - 0.5 * (ema_close - ema_low)

    if close > overbought and rsi_v > mr_cfg.rsi_overbought:
        return Signal(
            direction=Direction.SELL, strategy=StrategyName.MEAN_REVERSION, signal_bar_ts=ctx.now
        )
    if close < oversold and rsi_v < mr_cfg.rsi_oversold:
        return Signal(
            direction=Direction.BUY, strategy=StrategyName.MEAN_REVERSION, signal_bar_ts=ctx.now
        )
    return None


def compute_sl(
    direction: Direction, ema34_low: float, ema34_high: float, atr5: float, mult: float
) -> float:
    """Mirror table: BUY sl = ema34_low - mult*ATR5; SELL sl = ema34_high + mult*ATR5.
    sl_scale (atr_zscore) does NOT apply to MR (§6.8)."""
    if direction == Direction.BUY:
        return ema34_low - mult * atr5
    return ema34_high + mult * atr5


def compute_tp_rules(ema34_close: float) -> TPRules:
    """Single absolute target at decision time (§6.8): no TP1/TP2 split, no BE move."""
    return TPRules(
        kind="ABSOLUTE", tp1_abs=ema34_close, partial_fraction=1.0, move_be_after_tp1=False
    )
