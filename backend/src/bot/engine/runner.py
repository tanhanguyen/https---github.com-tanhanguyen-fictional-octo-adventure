"""Runner: portfolio-aware bar-processing loop (plan 04).

step() now processes one MERGED CLOCK TICK, not one bar of one symbol: it finds the
earliest upcoming bar-close across every symbol's own timeframe, processes every symbol
whose bar closes at that instant (in deterministic alphabetical order), then advances the
shared clock once. Per symbol, per due-tick, the original single-symbol order still holds:

  1. order_engine.process_bar(bar)   -- bar t is LIVE, not yet closed
  2. clock.set(ts + duration(tf))     -- (once per tick, after all due symbols' step 1)
  3. main_loop()                      -- decide at close of t; PENDING order created
  4. decision_log.persist(...)
  5. equity_point.append(...)         -- once per tick

Step 1 running before step 3 is what lets step-0 account-risk checks see a trade that
just closed on THIS bar, and guarantees a PENDING order created at close(t) cannot
fill on bar t itself (C11-adjacent causality guarantee, D6). Processing due symbols in
alphabetical order and inserting a new trade immediately (before the next due symbol is
decided) is what makes alphabetical order the tie-break for the last MAX_CONCURRENT_TRADES
slot when two symbols signal in the same tick (plan 04 test (b)).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from bot.config.models import BotConfig
from bot.core.clock import Clock
from bot.core.timeframes import tf_duration, trading_day
from bot.core.types import OrderStatus
from bot.data.feed import Feed
from bot.data.news import load_news_events_index
from bot.db import repositories as repo
from bot.engine import decision_log, main_loop
from bot.engine.context import AccountState, SymbolContext, build_context

EPS = 1e-12


@dataclass
class StepSummary:
    bar_ts: str
    symbol: str
    reason: str
    stage: str
    trade_event_types: list[str] = field(default_factory=list)
    closed_result: str | None = None
    equity: float = 0.0


class Runner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        symbols: dict[str, SymbolContext],
        dxy_feed: Feed | None,
        config: BotConfig,
        clock: Clock,
    ) -> None:
        if not symbols:
            raise ValueError("Runner requires at least one symbol")
        self.conn = conn
        self.run_id = run_id
        self.symbols = symbols
        self.dxy_feed = dxy_feed
        self.config = config  # base/portfolio config: starting_equity, rollover tz/time
        self.clock = clock

        self.balance = config.starting_equity
        self.equity = config.starting_equity

        # Plan 06: news events are loaded ONCE per run, frozen at the snapshot recorded
        # by repo.create_run -- importing a new file mid-run (or after) never changes
        # this run's decisions (determinism invariant).
        row = conn.execute(
            "SELECT news_snapshot_max_id FROM run WHERE id=?", (run_id,)
        ).fetchone()
        news_snapshot_max_id = int(row["news_snapshot_max_id"]) if row is not None else 0
        self.news_events = load_news_events_index(conn, news_snapshot_max_id)

    def _current_trading_day(self, ts: datetime) -> str:
        return trading_day(
            ts, self.config.trading_day_rollover_tz, self.config.trading_day_rollover_time
        ).isoformat()

    def _portfolio_open_trades_count(self) -> int:
        return sum(1 for sc in self.symbols.values() if sc.trade is not None)

    def _portfolio_open_risk_pct_total(self) -> float:
        return sum(
            sc.trade.risk_pct_effective for sc in self.symbols.values() if sc.trade is not None
        )

    def step(self) -> list[StepSummary]:
        # --- find the next merged clock tick -------------------------------------
        candidates: list[tuple[datetime, str, datetime]] = []
        for sym, sc in self.symbols.items():
            tf = sc.effective_config.timeframe
            ts = sc.price_feed.next_open_after(tf, sc.cursor)
            if ts is None:
                continue
            candidates.append((ts + tf_duration(tf), sym, ts))
        if not candidates:
            return []

        next_tick = min(c[0] for c in candidates)
        due = sorted(
            ((sym, ts) for close_ts, sym, ts in candidates if close_ts == next_tick),
            key=lambda pair: pair[0],
        )

        # --- 1. order_engine.process_bar for every due symbol (bar t still LIVE) ---
        events_by_symbol: dict[str, list[str]] = {}
        closed_result_by_symbol: dict[str, str | None] = {}
        for sym, ts in due:
            sc = self.symbols[sym]
            bar = sc.price_feed.bar_at(sc.effective_config.timeframe, ts)
            assert bar is not None
            outcome = sc.order_engine.process_bar(
                sc.trade,
                bar,
                sc.time_stop_hours,
                sc.effective_config.filters.time_stop.enabled,
                sc.effective_config.filters.time_stop.after_tp1,
                equity=self.equity,
            )
            trade_db_id_before = sc.trade_db_id
            closed_result_label: str | None = None

            if outcome.closed_result is not None:
                r = outcome.closed_result
                self.balance += r.pnl_amount
                self.equity = self.balance
                assert sc.trade is not None
                if trade_db_id_before is not None:
                    repo.update_trade(
                        self.conn,
                        trade_db_id_before,
                        status="CLOSED",
                        result=r.result,
                        pnl_amount=r.pnl_amount,
                        pnl_r=r.pnl_r,
                        closed_at_utc=r.closed_at.isoformat(),
                        trading_day=self._current_trading_day(r.closed_at),
                        entry_price=sc.trade.entry_price,
                        sl_price=sc.trade.sl,
                        tp1_price=sc.trade.tp1_price,
                        tp2_price=sc.trade.tp2_price,
                        lot_size=sc.trade.lot_size,
                        opened_at_utc=(
                            sc.trade.entry_bar_ts.isoformat() if sc.trade.entry_bar_ts else None
                        ),
                    )
                sc.trade = None
                sc.trade_db_id = None
                closed_result_label = r.result
            elif outcome.trade is None and trade_db_id_before is not None:
                repo.update_trade(self.conn, trade_db_id_before, status="CANCELLED")
                sc.trade = None
                sc.trade_db_id = None
            else:
                sc.trade = outcome.trade
                if (
                    sc.trade is not None
                    and trade_db_id_before is not None
                    and any(e.event_type == "FILLED" for e in outcome.events)
                ):
                    repo.update_trade(
                        self.conn,
                        trade_db_id_before,
                        status="OPEN",
                        entry_price=sc.trade.entry_price,
                        opened_at_utc=(
                            sc.trade.entry_bar_ts.isoformat() if sc.trade.entry_bar_ts else None
                        ),
                        sl_price=sc.trade.sl,
                        tp1_price=sc.trade.tp1_price,
                        tp2_price=sc.trade.tp2_price,
                        lot_size=sc.trade.lot_size,
                    )

            if trade_db_id_before is not None:
                for ev in outcome.events:
                    repo.insert_trade_event(
                        self.conn,
                        trade_db_id_before,
                        ev.event_type,
                        ev.ts_utc.isoformat(),
                        ev.price,
                        ev.detail,
                    )

            events_by_symbol[sym] = [e.event_type for e in outcome.events]
            closed_result_by_symbol[sym] = closed_result_label

        # --- 2. advance the shared clock once for the whole tick -------------------
        self.clock.set(next_tick)
        current_day = self._current_trading_day(self.clock.now)

        # --- 3-4-5. decide + persist per due symbol, alphabetical order ------------
        summaries: list[StepSummary] = []
        for sym, _ts in due:
            sc = self.symbols[sym]
            account = AccountState(
                open_trades_count=self._portfolio_open_trades_count(),
                daily_loss_count=repo.daily_loss_count(self.conn, self.run_id, current_day),
                consecutive_wins=repo.consecutive_wins(self.conn, self.run_id),
                consecutive_losses=repo.consecutive_losses(self.conn, self.run_id),
                equity=self.equity,
                symbol_open_trade=sc.trade is not None,
                open_risk_pct_total=self._portfolio_open_risk_pct_total(),
            )
            ctx = build_context(
                sc.price_feed,
                self.dxy_feed,
                sc.effective_config,
                self.clock.now,
                account,
                news_events=self.news_events,
                instrument_currencies=sc.currencies,
            )
            ml = main_loop.decide(ctx, sc.breakout_state, sc.effective_config)
            sc.breakout_state = ml.breakout_state

            new_trade_db_id = None
            if ml.open_trade_candidate is not None and sc.trade is None:
                t = ml.open_trade_candidate
                new_trade_db_id = repo.insert_trade(
                    self.conn,
                    repo.TradeRecord(
                        run_id=self.run_id,
                        symbol=sym,
                        strategy=t.strategy.value,
                        direction=t.direction.value,
                        status=OrderStatus.PENDING.value,
                        sl_price=t.sl,
                        lot_size=None,
                    ),
                )
                t.local_id = new_trade_db_id
                sc.trade = t
                sc.trade_db_id = new_trade_db_id

            decision_log.persist(
                self.conn, self.run_id, self.clock.now.isoformat(), ml.bundle, new_trade_db_id, sym
            )

            summaries.append(
                StepSummary(
                    bar_ts=self.clock.now.isoformat(),
                    symbol=sym,
                    reason=ml.bundle.outcome.reason,
                    stage=ml.bundle.outcome.stage,
                    trade_event_types=events_by_symbol.get(sym, []),
                    closed_result=closed_result_by_symbol.get(sym),
                    equity=self.equity,
                )
            )

            # Advance this symbol's cursor to its own next bar.
            sc.cursor = next_tick

        # --- one equity_point + account_state row per tick (not per symbol) --------
        repo.insert_equity_point(
            self.conn, self.run_id, self.clock.now.isoformat(), self.equity, self.balance
        )
        repo.update_account_state(
            self.conn,
            self.run_id,
            equity=self.equity,
            balance=self.balance,
            open_trades=self._portfolio_open_trades_count(),
            daily_loss_count=repo.daily_loss_count(self.conn, self.run_id, current_day),
            consecutive_wins=repo.consecutive_wins(self.conn, self.run_id),
            consecutive_losses=repo.consecutive_losses(self.conn, self.run_id),
            current_trading_day=current_day,
        )

        return summaries
