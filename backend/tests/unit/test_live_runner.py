"""LiveRunner (plan 07 §2).

The pivotal test is `test_live_matches_replay_bar_by_bar` and its catch-up/restart
siblings: the live path and the replay path must produce **byte-identical** decision
streams over the same bars. If that ever stops holding, "we backtested it" stops meaning
anything about what the bot does live, so these tests are the point of the whole module.

No test here touches the network or the wall clock — the venue is a `FakeSource` over a
generated bar series and time is a list of instants the test controls.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig, SymbolEntry, live_effective_config
from bot.core.clock import Clock
from bot.core.timeframes import tf_duration
from bot.data.feed import Feed
from bot.data.live_feed import LiveFeedError, empty_frame
from bot.data.resample import build_all_timeframes
from bot.data.synthetic import generate_price_series
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.context import build_symbol_context
from bot.engine.live_runner import LiveRunner, LiveSymbol
from bot.engine.runner import Runner
from bot.notify import LiveAlerts, LogNotifier

UTC = timezone.utc
SYMBOL = "BTCUSDT"
TF = "15m"
WARMUP = 320  # bars of history before the first decided bar (test-sized, not production)


# --------------------------------------------------------------------------- fixtures


def base_bars(n: int = 900, seed: int = 42) -> pd.DataFrame:
    """A synthetic 15m OHLCV frame shaped exactly like a live feed's output: no
    `sub_path` column (a real venue gives closed candles, not intrabar paths)."""
    df, _labels = generate_price_series(seed, n, start_price=60000.0)
    return df[["open", "high", "low", "close", "volume"]]


def crypto_config() -> BotConfig:
    cfg = load_default_config()
    # BRB's Peak1 -> retest -> breakout-2 -> scoring gate (docs/spec_v2.md) cuts entry
    # frequency by design; this fixed synthetic seed/window is tuned for v1.2's single-
    # phase entries so these live-runner plumbing tests reliably see a trade. BRB itself
    # is covered by test_strategies.py / test_main_loop.py.
    strategies = cfg.strategies.model_copy(
        update={
            "breakout": cfg.strategies.breakout.model_copy(
                update={"require_second_breakout": False}
            )
        }
    )
    return cfg.model_copy(
        update={
            "symbol": SYMBOL,
            "symbol_type": "CRYPTO",
            "timeframe": TF,
            "symbols": [SymbolEntry(symbol=SYMBOL, symbol_type="CRYPTO")],
            "strategies": strategies,
        }
    )


def effective(cfg: BotConfig) -> BotConfig:
    return live_effective_config(cfg, cfg.symbols[0])


def instrument():
    from bot.engine.portfolio import _instrument_from_yaml

    return _instrument_from_yaml(SYMBOL, load_instruments())


class FakeSource:
    """A venue that hands out whatever of `df` has closed by `now`."""

    def __init__(self, df: pd.DataFrame, timeframe: str = TF, symbol: str = SYMBOL) -> None:
        self.df = df
        self.symbol = symbol
        self.timeframe = timeframe
        self.duration = tf_duration(timeframe)
        self.fail_next = 0

    def _closed(self, now: datetime) -> pd.DataFrame:
        return self.df[self.df.index + self.duration <= pd.Timestamp(now)]

    def backfill(self, now: datetime, bars: int | None = None) -> pd.DataFrame:
        closed = self._closed(now)
        return closed if bars is None else closed.tail(bars)

    def fetch_closed(
        self, now: datetime, limit: int = 500, end_time: datetime | None = None
    ) -> pd.DataFrame:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise LiveFeedError("simulated venue outage")
        closed = self._closed(now)
        return closed.tail(limit) if len(closed) else empty_frame()

    def next_close_after(self, now: datetime) -> datetime:
        step = int(self.duration.total_seconds())
        epoch = datetime(1970, 1, 5, tzinfo=UTC)
        elapsed = int((now - epoch).total_seconds())
        return epoch + timedelta(seconds=(elapsed // step + 1) * step)


class FakeClock:
    """Wall clock under test control: `advance()` is the only thing that moves it."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def make_conn() -> sqlite3.Connection:
    return connect_and_migrate(":memory:")


def make_run(conn: sqlite3.Connection, cfg: BotConfig, mode: str) -> int:
    repo.upsert_live_dataset(conn, f"{mode}:{SYMBOL}", SYMBOL, TF)
    cv = repo.create_config_version(conn, cfg.model_dump_json(), note=mode)
    return repo.create_run(conn, cv, {SYMBOL: f"{mode}:{SYMBOL}"}, cfg.starting_equity, mode=mode)


def stream_of(conn: sqlite3.Connection, run_id: int) -> list[tuple[str, str, str, str]]:
    return [
        (str(r[0]), str(r[1]), str(r[2]), str(r[3]))
        for r in conn.execute(
            "SELECT bar_ts_utc, symbol, reason, stage FROM decision WHERE run_id=? ORDER BY id",
            (run_id,),
        )
    ]


def trades_of(conn: sqlite3.Connection, run_id: int) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT symbol, direction, status, result, ROUND(COALESCE(pnl_r,0),9), timeframe "
            "FROM trade WHERE run_id=? ORDER BY id",
            (run_id,),
        )
    ]


# ------------------------------------------------------------------- reference replay


def run_replay(df: pd.DataFrame, cfg: BotConfig, start_index: int) -> tuple:
    """The ground truth: the ordinary Runner over the whole frame, starting at the same
    bar the live runner starts at."""
    eff = effective(cfg)
    frames = build_all_timeframes(
        df, eff.trading_day_rollover_tz, eff.trading_day_rollover_time, base_tf=TF
    )
    context = build_symbol_context(eff, Feed(frames=frames), instrument())
    context.cursor = df.index[start_index].to_pydatetime()

    conn = make_conn()
    run_id = make_run(conn, cfg, "backtest")
    runner = Runner(conn, run_id, {SYMBOL: context}, None, cfg, Clock(context.cursor))
    while runner.step():
        pass
    return stream_of(conn, run_id), trades_of(conn, run_id), runner.equity, conn


def make_live(
    conn: sqlite3.Connection,
    run_id: int,
    cfg: BotConfig,
    source: FakeSource,
    clock: FakeClock,
    alerts: LiveAlerts | None = None,
) -> LiveRunner:
    eff = effective(cfg)
    context = build_symbol_context(
        eff, Feed(frames={TF: empty_frame()}), instrument(), cursor=clock()
    )
    return LiveRunner(
        conn,
        run_id,
        {SYMBOL: LiveSymbol(context=context, source=source)},
        cfg,
        alerts if alerts is not None else LiveAlerts(LogNotifier(), run_label="test"),
        now_fn=clock,
        sleep_fn=lambda _s: None,
    )


# ------------------------------------------------------------------------------ tests


@pytest.mark.parametrize("bars_per_poll", [1, 4], ids=["bar-by-bar", "miss-3-bars"])
def test_live_matches_replay(bars_per_poll: int):
    """Live == replay, whether bars arrive one at a time or four at a time.

    `bars_per_poll=4` is the downtime case from the plan: three bars were missed, they
    all show up in one poll, and catch-up must process them sequentially — each decided
    with the clock set to ITS OWN close, never with the newest price in view."""
    df = base_bars()
    cfg = crypto_config()

    expected_stream, expected_trades, expected_equity, ref_conn = run_replay(df, cfg, WARMUP)

    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.start()

    end = df.index[-1].to_pydatetime() + tf_duration(TF) * 2
    while clock() <= end:
        live.poll()
        live.drain()
        clock.advance(tf_duration(TF) * bars_per_poll)

    assert stream_of(conn, run_id) == expected_stream
    assert trades_of(conn, run_id) == expected_trades
    assert live.runner is not None
    assert live.runner.equity == pytest.approx(expected_equity)
    assert len(expected_stream) > 100  # the comparison is not vacuous
    ref_conn.close()
    conn.close()


def test_restart_mid_run_resumes_without_losing_or_duplicating_anything():
    """Kill the process halfway, rebuild everything from the DB, keep going: the result
    must still equal the uninterrupted replay."""
    df = base_bars()
    cfg = crypto_config()
    expected_stream, expected_trades, expected_equity, ref_conn = run_replay(df, cfg, WARMUP)

    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    halfway = df.index[(WARMUP + len(df)) // 2].to_pydatetime()

    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    first = make_live(conn, run_id, cfg, FakeSource(df), clock)
    first.start()
    while clock() <= halfway:
        first.poll()
        first.drain()
        clock.advance(tf_duration(TF))
    assert first.stats.bars_processed > 0
    mid_stream = stream_of(conn, run_id)
    assert 0 < len(mid_stream) < len(expected_stream)  # genuinely mid-run

    # --- restart: brand-new objects, same DB (nothing carried over in memory) ---
    resumed = make_live(conn, run_id, cfg, FakeSource(df), clock)
    resumed.start()
    end = df.index[-1].to_pydatetime() + tf_duration(TF) * 2
    while clock() <= end:
        resumed.poll()
        resumed.drain()
        clock.advance(tf_duration(TF))

    assert stream_of(conn, run_id) == expected_stream
    assert trades_of(conn, run_id) == expected_trades
    assert resumed.runner is not None
    assert resumed.runner.equity == pytest.approx(expected_equity)
    ref_conn.close()
    conn.close()


def test_restart_restores_an_in_flight_trade_in_full():
    """A trade open across the restart keeps its identity and its un-columned state
    (tp_rules / partials / settlement counters live only in strategy_state)."""
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")

    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.start()

    # Advance until a trade is actually in flight.
    while clock() <= df.index[-1].to_pydatetime():
        live.poll()
        live.drain()
        if live.symbols[SYMBOL].context.trade is not None:
            break
        clock.advance(tf_duration(TF))
    before = live.symbols[SYMBOL].context.trade
    assert before is not None, "no trade was open in the sample — pick another seed"
    before_db_id = live.symbols[SYMBOL].context.trade_db_id

    resumed = make_live(conn, run_id, cfg, FakeSource(df), clock)
    resumed.start()
    after = resumed.symbols[SYMBOL].context.trade

    assert after is not None
    assert resumed.symbols[SYMBOL].context.trade_db_id == before_db_id
    assert (after.direction, after.strategy, after.status) == (
        before.direction,
        before.strategy,
        before.status,
    )
    assert after.sl == before.sl
    assert after.tp_rules == before.tp_rules
    assert after.remaining_fraction == before.remaining_fraction
    assert after.tp1_hit == before.tp1_hit
    assert after.risk_pct_effective == before.risk_pct_effective
    assert resumed.symbols[SYMBOL].context.breakout_state == (
        live.symbols[SYMBOL].context.breakout_state
    )
    conn.close()


def test_replayed_bar_is_skipped_instead_of_decided_twice():
    """Idempotency by bar_ts: rewinding the cursor (what a lost state write looks like)
    must not produce a second decision row for a bar already decided."""
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")

    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.start()
    for _ in range(5):
        live.poll()
        live.drain()
        clock.advance(tf_duration(TF))
    before = stream_of(conn, run_id)
    assert len(before) >= 4

    # Rewind two bars, as a state write lost to a kill -9 would.
    live.symbols[SYMBOL].context.cursor = datetime.fromisoformat(before[-2][0]) - tf_duration(TF)
    live.drain()

    assert stream_of(conn, run_id) == before
    assert live.stats.skipped_duplicate_ticks >= 1
    conn.close()


def test_feed_failure_degrades_and_recovers_without_crashing():
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")

    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    source = FakeSource(df)
    notifier = LogNotifier()
    eff = effective(cfg)
    context = build_symbol_context(
        eff, Feed(frames={TF: empty_frame()}), instrument(), cursor=clock()
    )
    live = LiveRunner(
        conn,
        run_id,
        {SYMBOL: LiveSymbol(context=context, source=source)},
        cfg,
        LiveAlerts(notifier, run_label="test"),
        now_fn=clock,
        sleep_fn=lambda _s: None,
    )
    live.start()

    source.fail_next = 2
    clock.advance(tf_duration(TF))
    live.poll()  # first failure -> degraded
    live.poll()  # second failure -> still degraded, only ONE alert
    assert live.degraded is True
    status = repo.get_live_status(conn, run_id)
    assert status is not None and status["feed_state"] == "degraded"
    assert sum("DEGRADED" in m for m in notifier.sent) == 1

    live.poll()  # source recovers
    assert live.degraded is False
    status = repo.get_live_status(conn, run_id)
    assert status is not None and status["feed_state"] == "ok"
    assert sum("recovered" in m for m in notifier.sent) == 1
    conn.close()


def test_a_malformed_venue_payload_degrades_rather_than_killing_the_run():
    """HTTP 200 with garbage rows is still "the feed is unusable right now" — the same
    class of problem as an unreachable venue, and not worth ending a 48h run over."""
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    source = FakeSource(df)
    live = make_live(conn, run_id, cfg, source, clock)
    live.start()

    def garbage(now, limit=500, end_time=None):
        raise ValueError("could not convert string to float: 'n/a'")

    source.fetch_closed = garbage  # type: ignore[method-assign]
    clock.advance(tf_duration(TF))
    live.poll()

    assert live.degraded is True
    status = repo.get_live_status(conn, run_id)
    assert status is not None and status["feed_state"] == "degraded"
    assert "ValueError" in str(status["detail"])
    conn.close()


def test_stop_requested_ends_the_loop_and_marks_the_run():
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.start()

    repo.request_stop(conn, run_id)
    live.run_forever(max_iterations=10)

    row = conn.execute("SELECT status FROM run WHERE id=?", (run_id,)).fetchone()
    assert row["status"] == "STOPPED"
    assert live.stats.polls == 0  # stopped before doing any work
    conn.close()


def test_orphaned_trade_row_is_cancelled_on_restart():
    """`Runner.step` commits the trade row before the live layer writes strategy_state.
    A kill in that window leaves a row nobody owns — and since the bar it belongs to is
    already decided, the idempotency check will never revisit it. It must be cancelled,
    or it counts against MAX_CONCURRENT_TRADES for the rest of the run."""
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.start()
    live.poll()
    live.drain()

    orphan = repo.insert_trade(
        conn,
        repo.TradeRecord(
            run_id=run_id,
            symbol=SYMBOL,
            strategy="BREAKOUT",
            direction="BUY",
            status="PENDING",
            sl_price=1.0,
            timeframe=TF,
        ),
    )
    assert repo.count_open_trades(conn, run_id) == 1

    resumed = make_live(conn, run_id, cfg, FakeSource(df), clock)
    resumed.start()

    row = conn.execute("SELECT status FROM trade WHERE id=?", (orphan,)).fetchone()
    assert row["status"] == "CANCELLED"
    assert repo.count_open_trades(conn, run_id) == 0
    events = [r["event_type"] for r in repo_events(conn, orphan)]
    assert events == ["CANCELLED"]
    conn.close()


def repo_events(conn: sqlite3.Connection, trade_id: int):
    return conn.execute(
        "SELECT * FROM trade_event WHERE trade_id=? ORDER BY id", (trade_id,)
    ).fetchall()


def test_a_restored_trade_is_not_mistaken_for_an_orphan():
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    live.start()
    while clock() <= df.index[-1].to_pydatetime():
        live.poll()
        live.drain()
        if live.symbols[SYMBOL].context.trade is not None:
            break
        clock.advance(tf_duration(TF))
    trade_db_id = live.symbols[SYMBOL].context.trade_db_id
    assert trade_db_id is not None

    resumed = make_live(conn, run_id, cfg, FakeSource(df), clock)
    resumed.start()

    row = conn.execute("SELECT status FROM trade WHERE id=?", (trade_db_id,)).fetchone()
    assert row["status"] in {"PENDING", "OPEN"}
    assert resumed.symbols[SYMBOL].context.trade is not None
    conn.close()


def test_an_unexpected_crash_alerts_marks_the_run_and_re_raises():
    """The supervisor (systemd/launchd, plan 09) restarts the process; the alert is how
    a human finds out, and `degraded` is how the dashboard shows it."""
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    notifier = LogNotifier()
    eff = effective(cfg)
    context = build_symbol_context(
        eff, Feed(frames={TF: empty_frame()}), instrument(), cursor=clock()
    )
    live = LiveRunner(
        conn,
        run_id,
        {SYMBOL: LiveSymbol(context=context, source=FakeSource(df))},
        cfg,
        LiveAlerts(notifier, run_label="test"),
        now_fn=clock,
        sleep_fn=lambda _s: None,
    )
    live.start()

    def boom() -> int:
        raise RuntimeError("disk on fire")

    live.poll = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="disk on fire"):
        live.run_forever(max_iterations=1)

    assert any("crashed" in m and "disk on fire" in m for m in notifier.sent)
    status = repo.get_live_status(conn, run_id)
    assert status is not None and status["feed_state"] == "degraded"
    conn.close()


def test_state_written_by_an_unknown_version_refuses_to_resume():
    """Fail closed: a payload this build does not understand must not be half-applied."""
    df = base_bars()
    cfg = crypto_config()
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    repo.save_strategy_state(conn, run_id, SYMBOL, '{"version": 999}', "2026-07-23T00:00:00")

    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    live = make_live(conn, run_id, cfg, FakeSource(df), clock)
    with pytest.raises(ValueError, match="unknown version"):
        live.start()
    conn.close()


def test_trade_rows_record_their_timeframe():
    df = base_bars()
    cfg = crypto_config()
    _stream, trades, _equity, conn = run_replay(df, cfg, WARMUP)
    assert trades, "expected at least one trade in the sample"
    assert all(t[-1] == TF for t in trades)
    conn.close()


# ------------------------------------------------------------- plan 13: alert fan-out


def test_a_live_run_writes_its_lifecycle_to_the_alert_log(tmp_path):
    """Plan 13 definition of done, live half: running paper must land the trade
    lifecycle in the alert DB, with Telegram unconfigured (log-only)."""
    from bot.alerts import build_live_alerts, connect_alerts_db, list_alerts

    df = base_bars()
    cfg = crypto_config()
    alerts_conn = connect_alerts_db(str(tmp_path / "alerts.db"))
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")

    live = make_live(
        conn,
        run_id,
        cfg,
        FakeSource(df),
        clock,
        alerts=build_live_alerts(
            alerts_conn, cfg.alerts, run_id=run_id, source="live", now_fn=clock
        ),
    )
    live.start()
    end = df.index[-1].to_pydatetime() + tf_duration(TF) * 2
    while clock() <= end:
        live.poll()
        live.drain()
        clock.advance(tf_duration(TF))

    rows = list_alerts(alerts_conn, limit=500)
    codes = [r.code for r in rows]
    assert codes[-1] == "runner_started"  # oldest row: the run announced itself
    assert {"trade_pending", "trade_opened", "trade_closed"} <= set(codes)
    assert all(r.run_id == run_id and r.source == "live" for r in rows)
    # No token in the test environment: every row is logged, none was sent.
    assert not any(r.sent_telegram for r in rows)
    # The body is what the toast renders, so it must actually carry the numbers.
    opened = next(r for r in rows if r.code == "trade_opened")
    assert opened.body["symbol"] == SYMBOL
    assert opened.body["entry"] is not None and opened.body["sl"] is not None

    alerts_conn.close()
    conn.close()


def test_a_degraded_feed_alerts_once_per_transition_into_the_alert_log(tmp_path):
    from bot.alerts import build_live_alerts, connect_alerts_db, list_alerts

    df = base_bars()
    cfg = crypto_config()
    alerts_conn = connect_alerts_db(str(tmp_path / "alerts.db"))
    clock = FakeClock(df.index[WARMUP].to_pydatetime() + tf_duration(TF))
    conn = make_conn()
    run_id = make_run(conn, cfg, "live")
    source = FakeSource(df)
    live = make_live(
        conn,
        run_id,
        cfg,
        source,
        clock,
        alerts=build_live_alerts(
            alerts_conn, cfg.alerts, run_id=run_id, source="live", now_fn=clock
        ),
    )
    live.start()

    source.fail_next = 3
    for _ in range(3):
        live.poll()
        clock.advance(tf_duration(TF))
    live.poll()  # recovered

    codes = [r.code for r in list_alerts(alerts_conn, limit=100)]
    assert codes.count("feed_degraded") == 1  # not once per failed poll
    assert codes.count("feed_recovered") == 1
    alerts_conn.close()
    conn.close()
