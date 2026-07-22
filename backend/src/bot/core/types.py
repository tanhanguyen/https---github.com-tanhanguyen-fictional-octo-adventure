"""Shared value types. Pure — no I/O, no engine imports."""

from __future__ import annotations

import enum
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    # Real intrabar sub-step path (open -> ... -> close), when the feed can provide one
    # (synthetic 15m data only, for now). None for real CSV data and resampled
    # timeframes -- OrderEngine falls back to its OHLC-only approximation then
    # (tech debt #2, plans/01-stabilize.md).
    sub_path: tuple[float, ...] | None = None


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
    # Plan 06: which currencies moving this symbol -- news filter intersects this with
    # each event's currency. Not hardcoded in filter config; lives on the instrument
    # profile so it's defined once per symbol.
    currencies: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Plan 06: news calendar events. Pure data + lookup here; I/O (CSV import, DB load)
# lives in bot.data.news so filters can stay I/O-free (invariant #6).
# ---------------------------------------------------------------------------

IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class NewsEvent:
    ts_utc: datetime
    currency: str
    impact: str
    title: str


@dataclass
class NewsEventsIndex:
    """`events` sorted ascending by `ts_utc`. `blocking_event` answers "is `now` inside
    [event.ts - before, event.ts + after] for some qualifying event?" in O(log n + k)
    via bisect on the precomputed timestamp list, k = candidates in the widened window."""

    events: list[NewsEvent] = field(default_factory=list)
    _ts: list[datetime] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._ts = [e.ts_utc for e in self.events]

    def blocking_event(
        self,
        now: datetime,
        window_before_min: int,
        window_after_min: int,
        currencies: set[str],
        min_impact: str,
    ) -> NewsEvent | None:
        if not self.events or not currencies:
            return None
        min_rank = IMPACT_RANK[min_impact]
        before = timedelta(minutes=window_before_min)
        after = timedelta(minutes=window_after_min)
        # An event at ts blocks `now` iff ts - before <= now <= ts + after, i.e.
        # ts is in [now - after, now + before] -- narrow the scan to that band first.
        lo = bisect_left(self._ts, now - after)
        hi = bisect_right(self._ts, now + before)
        for ev in self.events[lo:hi]:
            if IMPACT_RANK.get(ev.impact, 0) < min_rank:
                continue
            if ev.currency not in currencies:
                continue
            if ev.ts_utc - before <= now <= ev.ts_utc + after:
                return ev
        return None
