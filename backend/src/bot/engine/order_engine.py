"""Order engine: fills PENDING orders at bar.open (D6), manages OPEN trades through
gap/SL/TP/partial-TP1/breakeven/time-stop, and produces the aggregated close result
(F2 three-way classification). C10: takes all time from Bar timestamps, never wallclock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bot.config.models import ExecutionCostsConfig
from bot.core.timeframes import parse_hhmm, trading_day, vn30f_expiry
from bot.core.types import Bar, Direction, InstrumentSpec, OrderStatus, StrategyName, TPRules
from bot.engine import risk_manager
from bot.filters.time_stop import is_expired

EPS_R = 1e-9

UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class MarketRules:
    """Exchange rules the order engine must obey for one symbol (plan 05).

    Defaults are the neutral FOREX/CRYPTO behavior: no settlement lock, no expiry --
    so every pre-plan-05 call site keeps its exact semantics.
    """

    #: T+n settlement: a position may not be CLOSED until the release instant on the
    #: n-th trading day after entry. None -> no lock (forex, crypto, futures).
    settlement_trading_days: int | None = None
    #: Local time on that day when the shares actually land (HOSE: afternoon session).
    settlement_release_time: str = "13:00"
    settlement_tz: str = "Asia/Ho_Chi_Minh"
    #: Trading-day definition used for counting settlement days and dating expiry.
    rollover_tz: str = "America/New_York"
    rollover_time: str = "17:00"
    #: VN30F1M: force-close any open position at the close of the expiry-day bar.
    expiry_force_close: bool = False


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
    # Plan 05 (T+2.5). Trading days are COUNTED FROM THE BARS ACTUALLY SEEN rather
    # than from the calendar: an exchange holiday simply has no bar, so it is skipped
    # for free and no VN holiday calendar is needed.
    entry_trading_day: date | None = None
    last_seen_trading_day: date | None = None
    trading_days_since_entry: int = 0
    #: The trading day on which the shares land; fixed once reached, so the release
    #: instant stays anchored to THAT day rather than being re-derived per bar.
    settlement_release_day: date | None = None


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


def _worsen_sl_by_slippage(
    direction: Direction, price: float, slippage_pips: float, pip: float
) -> float:
    """§10: SL exits are worsened by slippage (conservative model); TP is left
    exact. BUY stops out lower, SELL stops out higher than the raw level/gap price."""
    if slippage_pips <= 0:
        return price
    slip = slippage_pips * pip
    return price - slip if direction == Direction.BUY else price + slip


class OrderEngine:
    def __init__(
        self,
        instrument: InstrumentSpec,
        intrabar_priority: str = "sl_first",
        costs: ExecutionCostsConfig | None = None,
        rules: MarketRules | None = None,
    ) -> None:
        self.instrument = instrument
        self.priority = intrabar_priority
        self.costs = costs or ExecutionCostsConfig()
        self.rules = rules or MarketRules()

    def _bar_trading_day(self, bar: Bar) -> date:
        return trading_day(bar.open_ts, self.rules.rollover_tz, self.rules.rollover_time)

    def _track_settlement(self, trade: OpenTrade, bar: Bar) -> None:
        """Advance the trade's settlement day counter once per NEW trading day, and
        latch the release day the first time the counter reaches T+n."""
        day = self._bar_trading_day(bar)
        if trade.entry_trading_day is None:
            trade.entry_trading_day = day
            trade.last_seen_trading_day = day
            trade.trading_days_since_entry = 0
        elif trade.last_seen_trading_day != day:
            trade.last_seen_trading_day = day
            trade.trading_days_since_entry += 1

        n = self.rules.settlement_trading_days
        if n is not None and trade.settlement_release_day is None:
            if trade.trading_days_since_entry >= n:
                trade.settlement_release_day = day

    def _settlement_released(self, trade: OpenTrade, bar: Bar) -> bool:
        """True when the position may be closed. HOSE T+2.5: shares bought on T land in
        the AFTERNOON session of T+2, so the release instant is
        `settlement_release_time` local on the T+2 trading day -- the LATCHED day, not
        the current bar's. Anchoring to the latched day is what keeps this right on
        intraday timeframes: re-deriving it per bar would make a T+3 morning bar (which
        closes before 13:00 on ITS own day) read as still-unsettled. Comparing
        `bar.close_ts` against that instant is exact on any timeframe -- a 1D bar closes
        well after 13:00 ICT, a T+2 morning bar does not."""
        if self.rules.settlement_trading_days is None:
            return True
        if trade.settlement_release_day is None:
            return False
        tz = ZoneInfo(self.rules.settlement_tz)
        release_local = datetime.combine(
            trade.settlement_release_day, parse_hhmm(self.rules.settlement_release_time)
        )
        return bar.close_ts > release_local.replace(tzinfo=tz).astimezone(UTC)

    def _maybe_expiry_close(
        self, trade: OpenTrade, bar: Bar, events: list[TradeEventRecord]
    ) -> ClosedResult | None:
        """VN30F1M: a contract stops existing at expiry, so any position still open on
        the expiry-day bar is closed at that bar's close (result classified normally,
        F2). Expiry is the 3rd Thursday by calendar only -- see vn30f_expiry()."""
        if not self.rules.expiry_force_close:
            return None
        day = self._bar_trading_day(bar)
        if day != vn30f_expiry(day.year, day.month):
            return None
        events.append(
            TradeEventRecord(
                "expiry_close", bar.close_ts, bar.close, f"VN30F expiry {day.isoformat()}"
            )
        )
        return self._finalize(trade, bar.close, bar.close_ts, events, "EXPIRY")

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
            # §10: entry cost = spread + slippage, both unfavorable (config, versioned;
            # instrument.spread_pips is no longer read here -- see plans/02-real-data.md).
            cost_amount = (self.costs.spread_pips + self.costs.slippage_pips) * self.instrument.pip
            entry = (
                bar.open + cost_amount
                if trade.direction == Direction.BUY
                else bar.open - cost_amount
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

        # Settlement bookkeeping runs on EVERY bar the trade is open, including its
        # fill bar (which seeds entry_trading_day).
        self._track_settlement(trade, bar)
        released = self._settlement_released(trade, bar)

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

        # T+2.5 (user decision 2026-07-22): before the shares settle, the position
        # CANNOT be exited -- an SL/TP touch is recorded and otherwise ignored, so the
        # backtest carries the same un-cuttable risk the real market imposes rather
        # than quietly booking an exit that could not have happened.
        if outcome1 is not None and not released:
            price_touched, kind_touched = outcome1
            events.append(
                TradeEventRecord(
                    "exit_suppressed_settlement",
                    bar.open_ts,
                    price_touched,
                    f"{kind_touched} touched but unsettled "
                    f"(T+{self.rules.settlement_trading_days}, "
                    f"day {trade.trading_days_since_entry} since entry)",
                )
            )
            return BarOutcome(trade=trade, events=events, closed_result=None)

        if outcome1 is not None:
            price, kind = outcome1
            if kind == "SL":
                price = _worsen_sl_by_slippage(
                    trade.direction, price, self.costs.slippage_pips, self.instrument.pip
                )
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
                if kind2 == "SL":
                    price2 = _worsen_sl_by_slippage(
                        trade.direction, price2, self.costs.slippage_pips, self.instrument.pip
                    )
                closed = self._finalize(
                    trade, price2, bar.open_ts, events, "BE" if kind2 == "SL" else "TP2"
                )
                return BarOutcome(trade=None, events=events, closed_result=closed)
            # The remaining half survived TP1 -- it still cannot outlive the contract.
            expired = self._maybe_expiry_close(trade, bar, events)
            if expired is not None:
                return BarOutcome(trade=None, events=events, closed_result=expired)
            return BarOutcome(trade=trade, events=events, closed_result=None)

        # No exit this bar -- expiry force-close first (the contract ceases to exist,
        # which outranks the time stop), then the time stop at bar.close (C5).
        expired = self._maybe_expiry_close(trade, bar, events)
        if expired is not None:
            return BarOutcome(trade=None, events=events, closed_result=expired)

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

        # §10: commission is a $ cost, charged once per round-turn on the full lot;
        # it does NOT touch pnl_r (R stays a pure price-distance risk metric so
        # equity-curve/streak filters are unaffected structurally).
        trade.realized_pnl_amount -= self.costs.commission_per_lot * trade.lot_size

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
