"""Live session wiring (plan 07 §3): create-or-resume, frozen config, portfolio scope."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_live_runner import FakeSource, base_bars

from bot.config.loader import load_default_config
from bot.config.models import BotConfig, SymbolEntry
from bot.core.errors import ConfigError
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.live_factory import build_live_session, default_live_db_path
from bot.notify import LogNotifier

UTC = timezone.utc
NOW = datetime(2023, 1, 20, tzinfo=UTC)


def crypto_portfolio() -> BotConfig:
    return load_default_config().model_copy(
        update={
            "symbol": "BTCUSDT",
            "symbol_type": "CRYPTO",
            "timeframe": "15m",
            "symbols": [
                SymbolEntry(symbol="BTCUSDT", symbol_type="CRYPTO"),
                SymbolEntry(symbol="ETHUSDT", symbol_type="CRYPTO"),
            ],
        }
    )


def sources(symbol: str, timeframe: str) -> FakeSource:
    seed = 42 if symbol == "BTCUSDT" else 11
    return FakeSource(base_bars(400, seed), timeframe=timeframe, symbol=symbol)


def make(path: Path, **kwargs):
    return build_live_session(
        db_path=str(path),
        source_factory=sources,
        notifier=LogNotifier(),
        now_fn=lambda: NOW,
        sleep_fn=lambda _s: None,
        **kwargs,
    )


def test_one_process_runs_the_whole_portfolio(tmp_path):
    session = make(tmp_path / "live.db", config=crypto_portfolio())
    try:
        assert sorted(session.runner.symbols) == ["BTCUSDT", "ETHUSDT"]
        assert session.resumed is False
        row = session.conn.execute(
            "SELECT mode, symbol FROM run WHERE id=?", (session.run_id,)
        ).fetchone()
        assert row["mode"] == "live"
        assert row["symbol"] == "BTCUSDT,ETHUSDT"
    finally:
        session.close()


def test_symbol_override_narrows_to_one_symbol_for_debugging(tmp_path):
    session = make(tmp_path / "live.db", config=crypto_portfolio(), only_symbol="ETHUSDT")
    try:
        assert sorted(session.runner.symbols) == ["ETHUSDT"]
    finally:
        session.close()


def test_unknown_symbol_filter_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="no enabled symbols"):
        make(tmp_path / "live.db", config=crypto_portfolio(), only_symbol="DOGEUSDT")


def test_second_start_resumes_the_existing_run_with_its_frozen_config(tmp_path):
    path = tmp_path / "live.db"
    first = make(path, config=crypto_portfolio())
    run_id, starting = first.run_id, first.config.starting_equity
    first.close()

    # A config change between restarts must NOT leak into the running live run.
    edited = crypto_portfolio().model_copy(update={"starting_equity": starting + 12_345})
    second = make(path, config=edited)
    try:
        assert second.resumed is True
        assert second.run_id == run_id
        assert second.config.starting_equity == starting
        runs = second.conn.execute("SELECT COUNT(*) FROM run WHERE mode='live'").fetchone()[0]
        assert runs == 1
    finally:
        second.close()


def test_restarting_against_a_different_venue_is_refused(tmp_path):
    """Testnet and mainnet are different price series. Resuming across them would keep
    the equity curve and open positions while the prices under them changed."""
    path = tmp_path / "live.db"
    first = make(path, config=crypto_portfolio())
    first.close()

    with pytest.raises(ConfigError, match="different feed"):
        make(path, config=crypto_portfolio(), base_url="https://testnet.binancefuture.com")


def test_restart_clears_a_stale_stop_flag(tmp_path):
    path = tmp_path / "live.db"
    first = make(path, config=crypto_portfolio())
    repo.request_stop(first.conn, first.run_id)
    first.close()

    second = make(path, config=crypto_portfolio())
    try:
        assert repo.stop_requested(second.conn, second.run_id) is False
    finally:
        second.close()


def test_forex_and_vn_are_refused_until_their_feeds_exist(tmp_path):
    cfg = load_default_config().model_copy(
        update={"symbols": [SymbolEntry(symbol="EURUSD", symbol_type="FOREX")]}
    )
    with pytest.raises(ConfigError, match="not implemented"):
        make(tmp_path / "live.db", config=cfg)


def test_default_db_path_follows_the_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_DB_PATH", str(tmp_path / "custom.db"))
    assert default_live_db_path() == str(tmp_path / "custom.db")
    monkeypatch.delenv("BOT_DB_PATH")
    # Live never lands in the backtest DB.
    assert default_live_db_path().endswith("live.db")


def test_a_full_session_runs_end_to_end_and_records_status(tmp_path):
    session = make(tmp_path / "live.db", config=crypto_portfolio())
    try:
        stats = session.runner.run_forever(max_iterations=1)
        assert stats.bars_processed > 0
        status = repo.get_live_status(session.conn, session.run_id)
        assert status is not None
        assert status["feed_state"] == "ok"
        assert status["last_bar_ts_utc"] is not None
        # Both symbols persisted their state, so a restart can resume either.
        assert sorted(repo.load_strategy_states(session.conn, session.run_id)) == [
            "BTCUSDT",
            "ETHUSDT",
        ]
    finally:
        session.close()


def test_live_db_is_separate_from_the_backtest_db(tmp_path):
    live_path = tmp_path / "live.db"
    session = make(live_path, config=crypto_portfolio())
    session.close()

    backtest = connect_and_migrate(str(tmp_path / "runtime.db"))
    try:
        assert backtest.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 0
    finally:
        backtest.close()
