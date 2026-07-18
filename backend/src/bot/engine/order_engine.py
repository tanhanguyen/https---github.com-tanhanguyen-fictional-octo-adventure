"""Order engine: fills PENDING orders at bar.open (D6), manages OPEN trades through
gap/SL/TP/partial-TP1/breakeven/time-stop, and produces the aggregated close result
(F2 three-way classification). C10: takes all time from Bar timestamps, never wallclock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot.core.types import Bar, Direction, InstrumentSpec, OrderStatus, StrategyName, TPRules
from bot.engine import risk_manager
from bot.filters.time_stop import is_expired

EPS_R = 1e-9


@dataclass
class OpenTrade:
    local_id: int
    symbol: str
    strategy: StrategyName
    direction: Direction
    status: OrderStatus
    sl: float  # mutates to entry on breakeven move
    tp_rules: TPRules
    risk_pct_effective: float = 0.0  # max_risk_per_trade_pct x risk_multiplier, from decision time
    lot_size: float = 0.0  # unknown until fill (C7: sized off the real entry, not the estimate)
    entry_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None
    entry_bar_ts: datetime | None = None
    tp1_hit: bool = False
    initial_sl_distance: float | None = None
    remaining_fraction: float = 1.0
    realized_pnl_amount: float = 0.0
    realized_pnl_r: float = 0.0


@dataclass
class TradeEventRecord:
    event_type: str
    ts_utc: datetime
    price: float | None
    detail: str = ""


@dataclass
class ClosedResult:
    result: str  # WIN | LOSS | BREAKEVEN (F2)
    pnl_amount: float
    pnl_r: float
    closed_at: datetime


@dataclass
class BarOutcome:
    trade: OpenTrade | None  # None if the trade closed/was cancelled this bar
    events: list[TradeEventRecord] = field(default_factory=list)
    closed_result: ClosedResult | None = None


def _sign(direction: Direction) -> float:
    return 1.0 if direction == Direction.BUY else -1.0


def _price_move(direction: Direction, entry: float, exit_price: float) -> float:
    return _sign(direction) * (exit_price - entry)


def _gap_through_sl(direction: Direction, open_: float, sl: float) -> bool:
    """Unfavorable gap: bar opened already beyond the stop."""
    if direction == Direction.BUY:
        return open_ <= sl
    return open_ >= sl


def _gap_through_tp(direction: Direction, open_: float, tp: float) -> bool:
    """Favorable gap: bar opened already beyond the target."""
    if direction == Direction.BUY:
        return open_ >= tp
    return open_ <= tp


def _in_range(low: float, high: float, level: float) -> bool:
    return low <= level <= high


def _walk_path_first_touch(
    sub_path: tuple[float, ...], sl: float, tp: float
) -> tuple[float, str] | None:
    """Walk the real intrabar sub-step path in order; the first segment where SL or
    TP falls inside its [min, max] wins. If a single sub-step segment crosses both
    (rare -- sub-steps are small), resolve by proximity to the segment's start, i.e.
    whichever the path reaches first within that step."""
    for a, b in zip(sub_path, sub_path[1:], strict=False):
        seg_low, seg_high = (a, b) if a <= b else (b, a)
        sl_in = seg_low <= sl <= seg_high
        tp_in = seg_low <= tp <= seg_high
        if sl_in and tp_in:
            return (sl, "SL") if abs(a - sl) <= abs(a - tp) else (tp, "TP")
        if sl_in:
            return sl, "SL"
        if tp_in:
            return tp, "TP"
    return None


def _bar_exit(
    direction: Direction,
    low: float,
    high: float,
    open_: float,
    sl: float,
    tp: float | None,
    priority: str,
    sub_path: tuple[float, ...] | None = None,
) -> tuple[float, str] | None:
    """Returns (exit_price, kind) where kind in {"SL","TP"}, or None if neither hit.
    Gap-through (open already past a level) wins over intrabar comparisons and fills
    at bar.open, not at the level price."""
    if _gap_through_sl(direction, open_, sl):
        return open_, "SL"
    if tp is not None and _gap_through_tp(direction, open_, tp):
        return open_, "TP"

    sl_hit = _in_range(low, high, sl)
    tp_hit = tp is not None and _in_range(low, high, tp)

    if sl_hit and tp_hit:
        if priority == "sl_first":
            return sl, "SL"
        # "path" mode: prefer the real sub-bar path (tech debt #2, plans/01-stabilize.md)
        # when the feed provides one (synthetic 15m only); otherwise fall back to the
        # documented approximation -- nearer to open wins (see docs/decisions.md).
        if sub_path is not None:
            walked = _walk_path_first_touch(sub_path, sl, float(tp))  # type: ignore[arg-type]
            if walked is not None:
                return walked
        if abs(open_ - sl) <= abs(open_ - float(tp)):  # type: ignore[arg-type]
            return sl, "SL"
        return float(tp), "TP"  # type: ignore[arg-type]
    if sl_hit:
        return sl, "SL"
    if tp_hit:
        return float(tp), "TP"  # type: ignore[arg-type]
    return None


class OrderEngine:
    def __init__(self, instrument: InstrumentSpec, intrabar_priority: str = "sl_first") -> None:
        self.instrument = instrument
        self.priority = intrabar_priority

    def _pnl_amount(
        self, direction: Direction, entry: float, exit_price: float, lot: float
    ) -> float:
        move = _price_move(direction, entry, exit_price)
        return move * lot * self.instrument.contract_size

    def process_bar(
        self,
        trade: OpenTrade | None,
        bar: Bar,
        time_stop_hours: float,
        time_stop_enabled: bool,
        time_stop_after_tp1: bool,
        equity: float = 0.0,
    ) -> BarOutcome:
        if trade is None:
            return BarOutcome(trade=None)

        events: list[TradeEventRecord] = []

        if trade.status == OrderStatus.PENDING:
            spread_amount = self.instrument.spread_pips * self.instrument.pip
            entry = (
                bar.open + spread_amount
                if trade.direction == Direction.BUY
                else bar.open - spread_amount
            )

            cancelled = (trade.direction == Direction.BUY and entry <= trade.sl) or (
                trade.direction == Direction.SELL and entry >= trade.sl
            )
            if cancelled:
                events.append(
                    TradeEventRecord(
                        "CANCELLED",
                        bar.open_ts,
                        entry,
                        "entry beyond SL at fill (D7 guard / gap-through-SL)",
                    )
                )
                return BarOutcome(trade=None, events=events, closed_result=None)

            risk_distance = abs(entry - trade.sl)

            # Lot sized here, against the real fill entry, not the estimate used at
            # decision time (tech debt #1, plans/01-stabilize.md).
            lot_result = risk_manager.calculate_lot(
                equity, trade.risk_pct_effective, 1.0, risk_distance, self.instrument
            )
            if lot_result.lot <= 0:
                events.append(
                    TradeEventRecord(
                        "CANCELLED", bar.open_ts, entry, "lot size rounds to zero at fill"
                    )
                )
                return BarOutcome(trade=None, events=events, closed_result=None)
            trade.lot_size = lot_result.lot

            tp1: float | None
            tp2: float | None
            if trade.tp_rules.kind == "R_MULTIPLE":
                assert trade.tp_rules.tp1_r is not None
                tp1 = entry + _sign(trade.direction) * trade.tp_rules.tp1_r * risk_distance
                tp2 = (
                    entry + _sign(trade.direction) * trade.tp_rules.tp2_r * risk_distance
                    if trade.tp_rules.tp2_r is not None
                    else None
                )
            else:  # ABSOLUTE (mean reversion)
                tp1 = trade.tp_rules.tp1_abs
                tp2 = None
                assert tp1 is not None
                wrong_side = (trade.direction == Direction.BUY and tp1 <= entry) or (
                    trade.direction == Direction.SELL and tp1 >= entry
                )
                if wrong_side:
                    events.append(
                        TradeEventRecord("CANCELLED", bar.open_ts, entry, "TP wrong side of entry")
                    )
                    return BarOutcome(trade=None, events=events, closed_result=None)

            trade.entry_price = entry
            trade.entry_bar_ts = bar.open_ts
            trade.tp1_price = tp1
            trade.tp2_price = tp2
            trade.initial_sl_distance = risk_distance
            trade.status = OrderStatus.OPEN
            events.append(TradeEventRecord("FILLED", bar.open_ts, entry, "order filled"))

        assert trade.status == OrderStatus.OPEN
        assert trade.entry_price is not None and trade.initial_sl_distance is not None

        active_tp = trade.tp1_price if not trade.tp1_hit else trade.tp2_price
        outcome1 = _bar_exit(
            trade.direction,
            bar.low,
            bar.high,
            bar.open,
            trade.sl,
            active_tp,
            self.priority,
            bar.sub_path,
        )

        if outcome1 is not None:
            price, kind = outcome1
            if kind == "SL" or trade.tp_rules.kind == "ABSOLUTE" or trade.tp1_hit:
                # Full close (either a stop, an absolute-TP strategy, or the remaining
                # half after TP1 already happened).
                closed = self._finalize(
                    trade, price, bar.open_ts, events, "SL" if kind == "SL" else "TP"
                )
                return BarOutcome(trade=None, events=events, closed_result=closed)

            # kind == "TP" and R_MULTIPLE and not yet tp1_hit -> partial TP1.
            fraction = trade.tp_rules.partial_fraction
            self._realize_partial(trade, price, fraction)
            events.append(TradeEventRecord("TP1_HIT", bar.open_ts, price, f"closed {fraction:.0%}"))
            trade.tp1_hit = True
            trade.remaining_fraction = 1.0 - fraction
            trade.sl = trade.entry_price  # SL_TO_BREAKEVEN, immediately, same bar
            events.append(TradeEventRecord("SL_TO_BREAKEVEN", bar.open_ts, trade.entry_price, ""))

            # Same-bar second pass on the remaining position (plan requirement). Reuses
            # the whole-bar sub_path as an approximation -- the path isn't sliced to
            # start exactly at the TP1 touch point (would need the walk to also return
            # a segment index; not worth the complexity here, see plans/01-stabilize.md).
            outcome2 = _bar_exit(
                trade.direction,
                bar.low,
                bar.high,
                price,
                trade.sl,
                trade.tp2_price,
                self.priority,
                bar.sub_path,
            )
            if outcome2 is not None:
                price2, kind2 = outcome2
                closed = self._finalize(
                    trade, price2, bar.open_ts, events, "BE" if kind2 == "SL" else "TP2"
                )
                return BarOutcome(trade=None, events=events, closed_result=closed)
            return BarOutcome(trade=trade, events=events, closed_result=None)

        # No exit this bar -- check time stop at bar.close (C5).
        assert trade.entry_bar_ts is not None
        if time_stop_enabled and is_expired(
            trade.entry_bar_ts, bar.close_ts, time_stop_hours, trade.tp1_hit, time_stop_after_tp1
        ):
            closed = self._finalize(trade, bar.close, bar.close_ts, events, "TIME_STOP")
            return BarOutcome(trade=None, events=events, closed_result=closed)

        return BarOutcome(trade=trade, events=events, closed_result=None)

    def _realize_partial(self, trade: OpenTrade, price: float, fraction: float) -> None:
        assert trade.entry_price is not None and trade.initial_sl_distance is not None
        pnl = self._pnl_amount(trade.direction, trade.entry_price, price, trade.lot_size * fraction)
        move = _price_move(trade.direction, trade.entry_price, price)
        r = (move / trade.initial_sl_distance) * fraction if trade.initial_sl_distance > 0 else 0.0
        trade.realized_pnl_amount += pnl
        trade.realized_pnl_r += r

    def _finalize(
        self,
        trade: OpenTrade,
        price: float,
        ts: datetime,
        events: list[TradeEventRecord],
        kind: str,
    ) -> ClosedResult:
        self._realize_partial(trade, price, trade.remaining_fraction)
        events.append(TradeEventRecord("CLOSED", ts, price, kind))

        pnl_r = trade.realized_pnl_r
        if pnl_r > EPS_R:
            result = "WIN"
        elif pnl_r < -EPS_R:
            result = "LOSS"
        else:
            result = "BREAKEVEN"

        return ClosedResult(
            result=result, pnl_amount=trade.realized_pnl_amount, pnl_r=pnl_r, closed_at=ts
        )
