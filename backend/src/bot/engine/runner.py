"""Runner: the exact bar-processing order from the plan's "Order engine" section.

step():
  ts  = next primary-tf open
  bar = feed.bar_at(primary_tf, ts)
  1. order_engine.process_bar(bar)   -- bar t is LIVE, not yet closed
  2. clock.set(ts + duration(primary_tf))  -- bar t is now CLOSED
  3. main_loop()                     -- decide at close of t; PENDING order created
  4. decision_log.persist(...)
  5. equity_point.append(...)

Step 1 running before step 3 is what lets step-0 account-risk checks see a trade that
just closed on THIS bar, and guarantees a PENDING order created at close(t) cannot
fill on bar t itself (C11-adjacent causality guarantee, D6).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from bot.config.models import BotConfig
from bot.core.clock import Clock
from bot.core.timeframes import tf_duration, trading_day
from bot.core.types import InstrumentSpec, OrderStatus
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.engine import decision_log, main_loop
from bot.engine.context import AccountState, build_context
from bot.engine.order_engine import OpenTrade, OrderEngine
from bot.strategies.base import BreakoutState


@dataclass
class StepSummary:
    bar_ts: str
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
        price_feed: Feed,
        dxy_feed: Feed | None,
        config: BotConfig,
        instrument: InstrumentSpec,
        clock: Clock,
    ) -> None:
        self.conn = conn
        self.run_id = run_id
        self.price_feed = price_feed
        self.dxy_feed = dxy_feed
        self.config = config
        self.instrument = instrument
        self.clock = clock
        self.order_engine = OrderEngine(instrument, config.risk.intrabar_priority)

        self.trade: OpenTrade | None = None
        self.trade_db_id: int | None = None
        self.balance = config.starting_equity
        self.equity = config.starting_equity
        self.breakout_state = BreakoutState.initial()

    def _current_trading_day(self, ts: datetime) -> str:
        return trading_day(
            ts, self.config.trading_day_rollover_tz, self.config.trading_day_rollover_time
        ).isoformat()

    def step(self) -> StepSummary | None:
        primary = self.config.timeframe
        ts = self.price_feed.next_open_after(primary, self.clock.now)
        if ts is None:
            return None
        bar = self.price_feed.bar_at(primary, ts)
        if bar is None:
            return None

        # --- 1. order_engine.process_bar -----------------------------------------
        outcome = self.order_engine.process_bar(
            self.trade,
            bar,
            self.config.filters.time_stop.hours,
            self.config.filters.time_stop.enabled,
            self.config.filters.time_stop.after_tp1,
            equity=self.equity,
        )
        trade_db_id_before = self.trade_db_id
        closed_result_label = None

        if outcome.closed_result is not None:
            r = outcome.closed_result
            self.balance += r.pnl_amount
            self.equity = self.balance
            assert self.trade is not None
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
                    entry_price=self.trade.entry_price,
                    sl_price=self.trade.sl,
                    tp1_price=self.trade.tp1_price,
                    tp2_price=self.trade.tp2_price,
                    lot_size=self.trade.lot_size,
                    opened_at_utc=(
                        self.trade.entry_bar_ts.isoformat() if self.trade.entry_bar_ts else None
                    ),
                )
            self.trade = None
            self.trade_db_id = None
            closed_result_label = r.result
        elif outcome.trade is None and trade_db_id_before is not None:
            # cancelled at fill (D7 guard / gap-through-SL / TP wrong side)
            repo.update_trade(self.conn, trade_db_id_before, status="CANCELLED")
            self.trade = None
            self.trade_db_id = None
        else:
            self.trade = outcome.trade
            if (
                self.trade is not None
                and trade_db_id_before is not None
                and any(e.event_type == "FILLED" for e in outcome.events)
            ):
                repo.update_trade(
                    self.conn,
                    trade_db_id_before,
                    status="OPEN",
                    entry_price=self.trade.entry_price,
                    opened_at_utc=(
                        self.trade.entry_bar_ts.isoformat() if self.trade.entry_bar_ts else None
                    ),
                    sl_price=self.trade.sl,
                    tp1_price=self.trade.tp1_price,
                    tp2_price=self.trade.tp2_price,
                    lot_size=self.trade.lot_size,
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

        # --- 2. advance the clock -------------------------------------------------
        self.clock.set(ts + tf_duration(primary))

        # --- 3. main_loop -----------------------------------------------------------
        current_day = self._current_trading_day(self.clock.now)
        account = AccountState(
            open_trades_count=1 if self.trade is not None else 0,
            daily_loss_count=repo.daily_loss_count(self.conn, self.run_id, current_day),
            consecutive_wins=repo.consecutive_wins(self.conn, self.run_id),
            consecutive_losses=repo.consecutive_losses(self.conn, self.run_id),
            equity=self.equity,
        )
        ctx = build_context(self.price_feed, self.dxy_feed, self.config, self.clock.now, account)
        ml = main_loop.decide(ctx, self.breakout_state, self.config)
        self.breakout_state = ml.breakout_state

        new_trade_db_id = None
        if ml.open_trade_candidate is not None and self.trade is None:
            t = ml.open_trade_candidate
            new_trade_db_id = repo.insert_trade(
                self.conn,
                repo.TradeRecord(
                    run_id=self.run_id,
                    symbol=self.config.symbol,
                    strategy=t.strategy.value,
                    direction=t.direction.value,
                    status=OrderStatus.PENDING.value,
                    sl_price=t.sl,
                    lot_size=None,  # unknown until fill (tech debt #1, plans/01-stabilize.md)
                ),
            )
            t.local_id = new_trade_db_id
            self.trade = t
            self.trade_db_id = new_trade_db_id

        # --- 4. decision log ----------------------------------------------------
        decision_log.persist(
            self.conn, self.run_id, self.clock.now.isoformat(), ml.bundle, new_trade_db_id
        )

        # --- 5. equity point ------------------------------------------------------
        repo.insert_equity_point(
            self.conn, self.run_id, self.clock.now.isoformat(), self.equity, self.balance
        )
        repo.update_account_state(
            self.conn,
            self.run_id,
            equity=self.equity,
            balance=self.balance,
            open_trades=1 if self.trade is not None else 0,
            daily_loss_count=account.daily_loss_count,
            consecutive_wins=account.consecutive_wins,
            consecutive_losses=account.consecutive_losses,
            current_trading_day=current_day,
        )

        return StepSummary(
            bar_ts=self.clock.now.isoformat(),
            reason=ml.bundle.outcome.reason,
            stage=ml.bundle.outcome.stage,
            trade_event_types=[e.event_type for e in outcome.events],
            closed_result=closed_result_label,
            equity=self.equity,
        )
