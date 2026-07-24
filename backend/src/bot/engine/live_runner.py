"""LiveRunner — 24/7 paper trading on a real-time feed (plan 07 §2).

The whole design is one sentence: **the live path does not decide anything.** It only
gets closed bars into a `Feed` and then calls the ordinary replay `Runner.step()`. Every
rule — evaluate-all-decide-after, fill-at-next-open (D6), the C11 visibility guard, the
merged multi-symbol clock tick — comes from the exact same code a backtest runs, which
is why `test_live_matches_replay` can demand byte-identical decision streams from the
two paths. Anything a live runner is tempted to reimplement (catch-up after downtime,
"has this bar been seen") is expressed as a cursor into that same loop instead.

Consequences worth stating explicitly:

* **Catch-up is free.** Missing three bars during a restart is not a special case: three
  bars simply arrive at once, and `step()` processes them one at a time, each with the
  clock set to its own close — so decisions stay causal instead of peeking at the
  newest price.
* **No wall-clock in the engine.** Real time enters only through the injected `now_fn`
  (see `bot.core.wallclock`); this module never calls a system clock directly, so
  invariant #3 holds unchanged and every live test runs on a deterministic fake clock.
* **The clock only ever moves to a bar close.** Wall-clock time is used to decide *when
  to poll*; the engine's `Clock` is set to the `close_ts` of the bar being processed,
  exactly as in replay.
* **Idempotent by bar_ts.** A tick whose decisions are already in the DB is skipped, so
  a crash between the DB write and the state write cannot double-trade.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd

from bot.config.models import BotConfig
from bot.core.clock import Clock
from bot.core.errors import FeedError
from bot.core.timeframes import trading_day, warmup_bars_required
from bot.core.wallclock import NowFn, utc_now
from bot.data.feed import Feed
from bot.data.live_feed import LiveFeedError, empty_frame
from bot.data.resample import build_all_timeframes
from bot.db import repositories as repo
from bot.engine import live_state
from bot.engine.announce import announce_trade_events
from bot.engine.context import SymbolContext
from bot.engine.runner import Runner, StepSummary
from bot.notify import LiveAlerts

logger = logging.getLogger("bot.live")

#: Poll this long after a bar is due to close, so the venue has published it.
DEFAULT_GRACE_SECONDS = 5.0

#: Never sleep longer than this in one go: `stop_requested` and feed recovery are
#: checked once per wake-up, and a 1D run must not be 24h late noticing either.
MAX_SLEEP_SECONDS = 30.0

#: Extra bars kept beyond the warmup requirement. Bounds memory/CPU over a run of
#: arbitrary length while leaving the oldest (possibly partial) resample bucket well
#: outside the 300-bar lookback window.
TRIM_MARGIN_BARS = 128


class BarSource(Protocol):
    """What LiveRunner needs from a venue feed — `bot.data.live_feed.BinanceFuturesFeed`
    satisfies it, and so does the FakeSource used in tests."""

    symbol: str
    timeframe: str

    def backfill(self, now: datetime, bars: int | None = None) -> pd.DataFrame: ...

    def fetch_closed(
        self, now: datetime, limit: int = 500, end_time: datetime | None = None
    ) -> pd.DataFrame: ...

    def next_close_after(self, now: datetime) -> datetime: ...


@dataclass
class LiveSymbol:
    """One symbol's live wiring: the replay-side context plus its venue feed and the
    accumulating base-timeframe frame the higher frames are resampled from."""

    context: SymbolContext
    source: BarSource
    base_df: pd.DataFrame = field(default_factory=empty_frame)

    @property
    def timeframe(self) -> str:
        return self.context.effective_config.timeframe


@dataclass
class LiveStats:
    bars_processed: int = 0
    polls: int = 0
    poll_failures: int = 0
    trades_opened: int = 0
    trades_closed: int = 0
    skipped_duplicate_ticks: int = 0


class LiveRunner:
    def __init__(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        symbols: dict[str, LiveSymbol],
        config: BotConfig,
        alerts: LiveAlerts,
        dxy_feed: Feed | None = None,
        now_fn: NowFn = utc_now,
        sleep_fn: Callable[[float], None] | None = None,
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
        max_sleep_seconds: float = MAX_SLEEP_SECONDS,
    ) -> None:
        if not symbols:
            raise ValueError("LiveRunner requires at least one symbol")
        self.conn = conn
        self.run_id = run_id
        self.symbols = symbols
        self.config = config
        self.alerts = alerts
        self.dxy_feed = dxy_feed
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn if sleep_fn is not None else _real_sleep
        self.grace = timedelta(seconds=grace_seconds)
        self.max_sleep_seconds = max_sleep_seconds

        self.stats = LiveStats()
        self.degraded = False
        self.runner: Runner | None = None
        self._started_at = now_fn()
        self._last_summary_day: str | None = None
        # Plan 13 drawdown alert: the peak this process measures the drawdown from.
        # `start()` raises it to the restored equity if a resumed run is already up, so a
        # restart cannot invent a drawdown that never happened — and it deliberately
        # never LOWERS it, so a restart in the middle of a real drawdown still reports
        # one instead of quietly adopting the sunken equity as the new peak.
        self._peak_equity = config.starting_equity
        self._drawdown_band = 0

    # ------------------------------------------------------------------ startup
    def start(self) -> None:
        """Backfill warmup history, restore any persisted state, build the Runner.

        Order matters: history first (so the resampled frames exist), then the restored
        cursor (so a resumed run does not re-decide bars it already decided), then the
        Runner (whose `Clock` must start at the earliest cursor)."""
        now = self.now_fn()
        states = {
            sym: live_state.load_symbol_state(payload)
            for sym, payload in repo.load_strategy_states(self.conn, self.run_id).items()
        }

        for sym, ls in self.symbols.items():
            bars = ls.source.backfill(now, warmup_bars_required(ls.timeframe))
            if bars.empty:
                raise LiveFeedError(f"{sym}: backfill returned no closed bars")
            ls.base_df = bars
            self._rebuild_frames(ls)
            # Fresh run: the newest closed bar is the first bar to process (everything
            # older is warmup only). Resumed run: the persisted cursor wins.
            ls.context.cursor = bars.index[-1].to_pydatetime()

        restored: list[live_state.SymbolStateSnapshot] = []
        for sym, snapshot in states.items():
            if sym not in self.symbols:
                continue
            if snapshot is None:
                raise ValueError(
                    f"{sym}: persisted strategy_state has an unknown version — refusing "
                    "to resume with a half-understood state (start a new live run)"
                )
            sc = self.symbols[sym].context
            sc.breakout_state = snapshot.breakout_state
            sc.trade = snapshot.trade
            sc.trade_db_id = snapshot.trade_db_id
            sc.cursor = snapshot.cursor
            restored.append(snapshot)

        # balance/equity are ACCOUNT-wide and written to every symbol's row in the same
        # `_persist_state` call, so they agree — except after a crash midway through
        # that write, where the freshest cursor identifies the newest (correct) pair.
        newest = max(restored, key=lambda s: s.cursor) if restored else None

        contexts = {sym: ls.context for sym, ls in self.symbols.items()}
        clock = Clock(min(sc.cursor for sc in contexts.values()))
        runner = Runner(self.conn, self.run_id, contexts, self.dxy_feed, self.config, clock)
        if newest is not None:
            # Restored: the account scalars live in strategy_state, not in the (derived)
            # account_state cache, so put them back before the first step.
            runner.balance, runner.equity = newest.balance, newest.equity
        self.runner = runner
        self._peak_equity = max(self._peak_equity, runner.equity)
        self._reconcile_orphan_trades()

        repo.update_live_status(
            self.conn,
            self.run_id,
            feed_state="ok",
            started_at_utc=self._started_at.isoformat(),
            last_poll_ts_utc=now.isoformat(),
        )
        self.alerts.started(
            f"run #{self.run_id} ({'resumed' if restored else 'fresh'}) — "
            f"equity {runner.equity:,.2f}",
            symbols=sorted(self.symbols),
        )

    def _reconcile_orphan_trades(self) -> None:
        """Cancel PENDING/OPEN trade rows that no restored state claims.

        `Runner.step` commits the trade row (and its decision) BEFORE the live layer
        writes `strategy_state`, so a kill in that window leaves a row nobody owns: the
        bar it belongs to is already decided, so the idempotency check will skip it
        forever and the row would sit PENDING for the rest of the run — polluting
        `count_open_trades`, and with it `MAX_CONCURRENT_TRADES` and the open-risk cap.

        Cancelling (rather than adopting the row) is the fail-closed choice: the columns
        do not carry enough state to rebuild the trade faithfully, and a paper trade that
        never filled costs nothing to drop."""
        claimed = {
            ls.context.trade_db_id
            for ls in self.symbols.values()
            if ls.context.trade_db_id is not None
        }
        for row in repo.open_trades_for_run(self.conn, self.run_id):
            trade_id = int(row["id"])
            if trade_id in claimed:
                continue
            repo.update_trade(self.conn, trade_id, status="CANCELLED")
            repo.insert_trade_event(
                self.conn,
                trade_id,
                "CANCELLED",
                self.now_fn().isoformat(),
                None,
                "orphaned by restart: no persisted strategy_state claims this trade",
            )
            logger.warning("cancelled orphaned trade %s on restart", trade_id)
            self.alerts.stopped(f"cancelled orphaned trade #{trade_id} ({row['symbol']})")

    # ------------------------------------------------------------------- feeds
    def _rebuild_frames(self, ls: LiveSymbol) -> None:
        """Resample the accumulated base frame into every timeframe, in place.

        Mutating the existing `Feed.frames` dict (rather than replacing the Feed) is
        deliberate: the SymbolContext, OrderEngine and Runner all hold a reference to
        that one Feed instance."""
        cfg = ls.context.effective_config
        frames = build_all_timeframes(
            ls.base_df,
            cfg.trading_day_rollover_tz,
            cfg.trading_day_rollover_time,
            base_tf=ls.timeframe,
        )
        ls.context.price_feed.frames.clear()
        ls.context.price_feed.frames.update(frames)

    def _trim(self, ls: LiveSymbol) -> None:
        keep = warmup_bars_required(ls.timeframe) + TRIM_MARGIN_BARS
        if len(ls.base_df) > keep:
            ls.base_df = ls.base_df.tail(keep)

    def poll(self) -> int:
        """Fetch closed bars for every symbol; returns how many NEW bars arrived.

        A feed failure degrades this symbol for this round (alert + `degraded` status)
        and returns whatever the other symbols managed — the loop keeps running, which
        is the entire point of the degraded state."""
        now = self.now_fn()
        self.stats.polls += 1
        new_bars = 0
        failures: list[str] = []

        for sym, ls in self.symbols.items():
            try:
                page = ls.source.fetch_closed(now)
            except (FeedError, ValueError, TypeError, IndexError) as exc:
                # FeedError covers unreachable/erroring venues; the value/type/index
                # errors cover a venue that answers with a well-formed HTTP 200 and
                # malformed rows. Both are "the feed is unusable right now", which is
                # what `degraded` means -- neither is worth killing a 48h run over.
                # The catch is scoped to the parse boundary: anything that goes wrong
                # deeper in (resampling, DB) still propagates and restarts the process.
                failures.append(f"{sym}: {type(exc).__name__}: {exc}")
                continue
            if page.empty:
                continue
            fresh = page[~page.index.isin(ls.base_df.index)]
            if fresh.empty:
                continue
            combined = pd.concat([ls.base_df, page]).sort_index()
            ls.base_df = combined[~combined.index.duplicated(keep="last")]
            self._trim(ls)
            self._rebuild_frames(ls)
            new_bars += len(fresh)

        if failures:
            self.stats.poll_failures += 1
            self.degraded = True
            detail = "; ".join(failures)
            self.alerts.feed_degraded(detail)
            repo.update_live_status(
                self.conn,
                self.run_id,
                feed_state="degraded",
                detail=detail[:500],
                last_poll_ts_utc=now.isoformat(),
            )
        else:
            if self.degraded:
                self.degraded = False
                self.alerts.feed_recovered()
            repo.update_live_status(
                self.conn,
                self.run_id,
                feed_state="ok",
                detail="",
                last_poll_ts_utc=now.isoformat(),
            )
        return new_bars

    # ------------------------------------------------------------------ stepping
    def drain(self) -> list[StepSummary]:
        """Process every bar currently available, oldest first, then return.

        This is the catch-up path AND the normal path — after downtime there are simply
        more bars queued, and each is still decided with the clock set to its own close.
        """
        assert self.runner is not None
        out: list[StepSummary] = []
        while True:
            upcoming = self.runner.next_tick()
            if upcoming is None:
                break
            tick, due = upcoming
            if self._already_processed(tick, due):
                self.stats.skipped_duplicate_ticks += 1
                for sym, _ts in due:
                    self.symbols[sym].context.cursor = tick
                if self.runner.clock.now < tick:
                    self.runner.clock.set(tick)
                continue
            summaries = self.runner.step()
            if not summaries:
                break
            self.stats.bars_processed += len(summaries)
            out.extend(summaries)
            self._persist_state()
            self._announce(summaries)
        if out:
            last = out[-1].bar_ts
            repo.update_live_status(self.conn, self.run_id, last_bar_ts_utc=last)
            self._maybe_daily_summary(datetime.fromisoformat(last))
        return out

    def _already_processed(self, tick: datetime, due: list[tuple[str, datetime]]) -> bool:
        """True if ANY due symbol already has a decision at this bar_ts.

        `any`, not `all`, on purpose: a crash midway through a multi-symbol tick leaves
        some symbols decided and some not, and re-running the tick would duplicate the
        decided ones (and possibly their trades). Skipping the whole tick costs the
        undecided symbol one bar of inaction — the fail-closed side of the trade-off."""
        ts = tick.isoformat()
        return any(repo.decision_exists(self.conn, self.run_id, sym, ts) for sym, _ts in due)

    def _persist_state(self) -> None:
        assert self.runner is not None
        now_iso = self.now_fn().isoformat()
        for sym, ls in self.symbols.items():
            sc = ls.context
            repo.save_strategy_state(
                self.conn,
                self.run_id,
                sym,
                live_state.dump_symbol_state(
                    sc.breakout_state,
                    sc.trade,
                    sc.trade_db_id,
                    sc.cursor,
                    self.runner.balance,
                    self.runner.equity,
                ),
                now_iso,
            )

    def _announce(self, summaries: list[StepSummary]) -> None:
        """Turn one tick's summaries into alerts (plan 13's event catalogue).

        Everything here is *observation* — the live layer watches what the shared replay
        engine did and reports it. No alert may change a decision, and no alert failure
        may stop the loop (`AlertBus.emit` swallows; `LiveAlerts` only formats)."""
        for s in summaries:
            if "FILLED" in s.trade_event_types:
                self.stats.trades_opened += 1
            if s.closed_result is not None:
                self.stats.trades_closed += 1
            announce_trade_events(self.alerts, s, self.symbols[s.symbol].context)

            if s.reason == "daily_loss_limit_reached":
                # The cooldown key is the trading day, so a day spent blocked is one
                # Telegram message rather than one per bar.
                day = self._trading_day_of(s.bar_ts)
                self.alerts.daily_loss_limit(
                    day, repo.daily_loss_count(self.conn, self.run_id, day)
                )
            # LiveAlerts only speaks when the multiplier actually changes.
            self.alerts.equity_multiplier(
                s.risk_multiplier,
                repo.consecutive_wins(self.conn, self.run_id),
                repo.consecutive_losses(self.conn, self.run_id),
            )

        if summaries:
            self._check_drawdown(summaries[-1].equity)

    def _check_drawdown(self, equity: float) -> None:
        """Alert when equity falls a configured % below its peak (plan 08 §2 thresholds:
        WARN 5%, CRITICAL 10%).

        Band bookkeeping, not a per-bar test: an alert fires when the drawdown ENTERS a
        worse band and re-arms only after equity climbs back out of it, so a long
        drawdown is one message rather than one per bar. Plan 08 owns the *action*
        attached to the critical band (auto-revert to paper); a live paper run has
        nothing to revert, so here it is a report."""
        cfg = self.config.alerts
        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity <= 0:
            return
        dd_pct = max(0.0, (self._peak_equity - equity) / self._peak_equity * 100.0)
        band = 0
        if dd_pct >= cfg.drawdown_critical_pct:
            band = 2
        elif dd_pct >= cfg.drawdown_warn_pct:
            band = 1
        if band > self._drawdown_band:
            self.alerts.drawdown(
                dd_pct, equity, self._peak_equity, "critical" if band == 2 else "warn"
            )
        self._drawdown_band = band

    def _trading_day_of(self, bar_ts_iso: str) -> str:
        return trading_day(
            datetime.fromisoformat(bar_ts_iso),
            self.config.trading_day_rollover_tz,
            self.config.trading_day_rollover_time,
        ).isoformat()

    def _maybe_daily_summary(self, bar_ts: datetime) -> None:
        day = trading_day(
            bar_ts,
            self.config.trading_day_rollover_tz,
            self.config.trading_day_rollover_time,
        ).isoformat()
        if day == self._last_summary_day:
            return
        if self._last_summary_day is not None:
            # Summarize the day that just ended, not the one starting.
            assert self.runner is not None
            self.alerts.daily_summary(
                self._last_summary_day,
                {
                    "equity": round(self.runner.equity, 2),
                    "bars": self.stats.bars_processed,
                    "opened": self.stats.trades_opened,
                    "closed": self.stats.trades_closed,
                    "feed": "degraded" if self.degraded else "ok",
                },
            )
        self._last_summary_day = day

    # ---------------------------------------------------------------------- loop
    def _next_wake(self) -> datetime:
        now = self.now_fn()
        return min(ls.source.next_close_after(now) for ls in self.symbols.values()) + self.grace

    def _sleep_until(self, target: datetime) -> None:
        """Sleep in bounded chunks so `stop_requested` is noticed within one chunk even
        when the next bar is hours away."""
        while True:
            remaining = (target - self.now_fn()).total_seconds()
            if remaining <= 0:
                return
            self.sleep_fn(min(remaining, self.max_sleep_seconds))
            if self._stop_requested():
                return

    def _stop_requested(self) -> bool:
        return repo.stop_requested(self.conn, self.run_id)

    def run_forever(self, max_iterations: int | None = None) -> LiveStats:
        """Poll → drain → sleep, until stop is requested (or `max_iterations` rounds,
        which is how the tests bound the loop)."""
        if self.runner is None:
            self.start()
        iteration = 0
        try:
            while max_iterations is None or iteration < max_iterations:
                iteration += 1
                if self._stop_requested():
                    self.alerts.stopped("stop_requested flag set")
                    repo.set_run_status(self.conn, self.run_id, "STOPPED")
                    break
                self.poll()
                self.drain()
                if max_iterations is not None and iteration >= max_iterations:
                    break
                self._sleep_until(self._next_wake())
        except Exception as exc:
            # Alert, mark the run, and re-raise: the supervisor (systemd/launchd, plan
            # 09) restarts the process and `start()` resumes from strategy_state.
            self.alerts.crashed(f"{type(exc).__name__}: {exc}")
            repo.update_live_status(
                self.conn, self.run_id, feed_state="degraded", detail=str(exc)[:500]
            )
            logger.exception("live runner crashed")
            raise
        return self.stats


def _real_sleep(seconds: float) -> None:
    import time  # local import: keeps the module-level namespace free of `time`

    time.sleep(seconds)
