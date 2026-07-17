"""Shared value types. Pure — no I/O, no engine imports."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class Direction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Mode(str, enum.Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


class StrategyName(str, enum.Enum):
    BREAKOUT = "BREAKOUT"
    MEAN_REVERSION = "MEAN_REVERSION"


class TradeResult(str, enum.Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SymbolType(str, enum.Enum):
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    STOCK_VN_CASH = "STOCK_VN_CASH"
    STOCK_VN_DERIV = "STOCK_VN_DERIV"


class FilterKind(str, enum.Enum):
    REGIME = "REGIME"
    INPUT = "INPUT"
    GATE = "GATE"
    MODIFIER = "MODIFIER"
    EXIT = "EXIT"


@dataclass(frozen=True)
class Bar:
    """One closed candle. open_ts is tz-aware UTC; the bar is only visible
    once open_ts + tf_duration <= clock.now (C11)."""

    open_ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_ts: datetime


@dataclass(frozen=True)
class Signal:
    direction: Direction
    strategy: StrategyName
    signal_bar_ts: datetime
    # Breakout only:
    range_high: float | None = None
    range_low: float | None = None


@dataclass(frozen=True)
class TPRules:
    """TP is a *rule* fixed at decision time; prices resolve at fill (deviation 7).
    kind R_MULTIPLE: tp1/tp2 = entry ± r×|entry−sl| (breakout).
    kind ABSOLUTE:   tp1 = fixed price known at decision time (mean reversion)."""

    kind: str  # "R_MULTIPLE" | "ABSOLUTE"
    tp1_r: float | None = None
    tp2_r: float | None = None
    tp1_abs: float | None = None
    partial_fraction: float = 0.5
    move_be_after_tp1: bool = False


@dataclass
class FilterResult:
    id: str
    kind: FilterKind
    enabled: bool
    evaluated: bool
    passed: bool | None  # None: disabled, warmup, or informational (no verdict)
    blocking: bool = False
    values: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


@dataclass(frozen=True)
class DecisionOutcome:
    """§8 vocabulary verbatim in `reason`; stage/detail add UI-grade context."""

    reason: str  # wait|off|no_signal|no_confirm|mtf_conflict|dxy_conflict|
    #              daily_loss_limit_reached|max_concurrent_trades_reached|done
    stage: str
    detail: str


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    balance: float
    open_trades: int
    daily_loss_count: int
    consecutive_wins: int
    consecutive_losses: int


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    contract_size: float
    pip: float
    pip_value_per_lot: float
    spread_pips: float
    min_lot: float
    lot_step: float
