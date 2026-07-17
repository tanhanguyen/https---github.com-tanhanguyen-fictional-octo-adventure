"""Filter framework: FilterContext (precomputed indicators + state, shared across all
16 filters so each indicator is computed once) and the disabled/warmup helpers every
filter uses (C12).

FilterResult / FilterKind live in bot.core.types (Phase 1) and are re-exported here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from bot.config.models import BotConfig
from bot.core.types import Direction, FilterKind, FilterResult, Mode, Signal

__all__ = ["FilterContext", "FilterResult", "FilterKind", "disabled_result", "warmup_result"]


@dataclass
class FilterContext:
    """Everything a filter needs, computed once per bar and shared. All series are
    already-closed-bar series on the primary timeframe, most-recent value at [-1]."""

    config: BotConfig
    now: datetime
    symbol: str

    open_: pd.Series
    high: pd.Series
    low: pd.Series
    close: pd.Series
    volume: pd.Series

    ema_fast_close: pd.Series
    ema_fast_high: pd.Series
    ema_fast_low: pd.Series
    ema_slow_close: pd.Series
    adx: pd.Series
    er: pd.Series
    rsi: pd.Series
    atr14: pd.Series
    atr5: pd.Series
    atr_zscore: pd.Series
    volume_ma: pd.Series

    # Set by main_loop after strategy/signal generation (Phase B needs signal.direction).
    signal: Optional[Signal] = None

    # Account / risk state.
    open_trades_count: int = 0
    daily_loss_count: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    equity: float = 0.0
    last_trade_result: Optional[str] = None  # "WIN"|"LOSS"|"BREAKEVEN"|None

    # MTF: pre-fetched, no-lookahead-filtered higher-timeframe closed bars (C11)
    # already resolved by the caller (feed.bars honors C11) as EMA series on the HTF.
    htf_ema_fast_close: Optional[pd.Series] = None
    htf_ema_slow_close: Optional[pd.Series] = None
    htf_timeframe: Optional[str] = None

    # DXY
    dxy_change_1h_pct: Optional[float] = None

    extra: dict[str, Any] = field(default_factory=dict)


def disabled_result(filter_id: str, kind: FilterKind) -> FilterResult:
    return FilterResult(
        id=filter_id, kind=kind, enabled=False, evaluated=False, passed=None,
        blocking=False, values={}, detail="filter disabled",
    )


def warmup_result(filter_id: str, kind: FilterKind, detail: str = "indicator warmup (NaN)") -> FilterResult:
    """C12: any filter whose required indicator reads NaN yields passed=None, stage=warmup."""
    return FilterResult(
        id=filter_id, kind=kind, enabled=True, evaluated=False, passed=None,
        blocking=False, values={}, detail=detail,
    )


def is_nan(*values: float) -> bool:
    return any(v is None or (isinstance(v, float) and math.isnan(v)) for v in values)


def opposite_side_of_signal(direction: Direction) -> str:
    return "SELL" if direction == Direction.BUY else "BUY"
