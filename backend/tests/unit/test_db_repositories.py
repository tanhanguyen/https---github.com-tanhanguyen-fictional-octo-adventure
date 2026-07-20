"""DB smoke tests + counters-consistent invariant (plan requirement): account_state
cache must equal the derived-from-trade values after every closed trade."""

from __future__ import annotations

from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate


def _fresh_conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = connect_and_migrate(db_path)
    return conn


def _make_run(conn):
    repo.upsert_dataset(conn, "ds1", "{}")
    cv_id = repo.create_config_version(conn, "{}", note="test")
    run_id = repo.create_run(conn, cv_id, {"EURUSD": "ds1"}, 10_000.0)
    return run_id


def test_migration_creates_all_tables(tmp_path):
    conn = _fresh_conn(tmp_path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "schema_version",
        "config_version",
        "dataset",
        "run",
        "account_state",
        "trade",
        "trade_event",
        "decision",
        "decision_filter",
        "breakout_state",
        "equity_point",
    }
    assert expected.issubset(tables)


def test_wal_and_foreign_keys_enabled(tmp_path):
    conn = _fresh_conn(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_config_version_immutable_snapshots(tmp_path):
    conn = _fresh_conn(tmp_path)
    v1 = repo.create_config_version(conn, '{"a": 1}', note="v1")
    active = repo.get_active_config_version(conn)
    assert active["id"] == v1
    v2 = repo.create_config_version(conn, '{"a": 2}', note="v2")
    active2 = repo.get_active_config_version(conn)
    assert active2["id"] == v2
    # v1 row is untouched (immutable) -- just inactive now.
    row1 = conn.execute(
        "SELECT config_json, is_active FROM config_version WHERE id=?",
        (v1,),
    ).fetchone()
    assert row1["config_json"] == '{"a": 1}'
    assert row1["is_active"] == 0


def test_counters_consistent_after_closed_trades(tmp_path):
    conn = _fresh_conn(tmp_path)
    run_id = _make_run(conn)

    results = ["WIN", "LOSS", "BREAKEVEN", "WIN", "LOSS", "LOSS"]
    trading_day = "2024-01-02"
    for i, result in enumerate(results):
        t = repo.TradeRecord(
            run_id=run_id,
            symbol="EURUSD",
            strategy="BREAKOUT",
            direction="BUY",
            status="CLOSED",
            entry_price=1.1,
            sl_price=1.09,
            result=result,
            trading_day=trading_day,
            closed_at_utc=f"2024-01-02T{10+i:02d}:00:00+00:00",
            pnl_amount=1.0 if result == "WIN" else (0.0 if result == "BREAKEVEN" else -1.0),
            pnl_r=1.5 if result == "WIN" else (0.0 if result == "BREAKEVEN" else -1.0),
        )
        repo.insert_trade(conn, t)

        derived_daily_loss = repo.daily_loss_count(conn, run_id, trading_day)
        derived_consec_losses = repo.consecutive_losses(conn, run_id)
        derived_consec_wins = repo.consecutive_wins(conn, run_id)
        repo.update_account_state(
            conn,
            run_id,
            daily_loss_count=derived_daily_loss,
            consecutive_losses=derived_consec_losses,
            consecutive_wins=derived_consec_wins,
        )

        cache = repo.get_account_state(conn, run_id)
        assert cache["daily_loss_count"] == derived_daily_loss
        assert cache["consecutive_losses"] == derived_consec_losses
        assert cache["consecutive_wins"] == derived_consec_wins

    # Final expected values: WIN,LOSS,BREAKEVEN,WIN,LOSS,LOSS (chronological)
    # daily_loss_count = LOSS+BREAKEVEN count = 4 (LOSS,BREAKEVEN,LOSS,LOSS)
    assert repo.daily_loss_count(conn, run_id, trading_day) == 4
    # consecutive_losses scanning DESC: LOSS,LOSS -> stop at WIN => 2
    assert repo.consecutive_losses(conn, run_id) == 2
    assert repo.consecutive_wins(conn, run_id) == 0


def test_counters_consistent_multi_symbol_portfolio(tmp_path):
    """Plan 04: daily_loss_count/consecutive_* and account_state.open_trades must stay
    portfolio-wide (aggregated across every symbol in the run), not per-symbol."""
    conn = _fresh_conn(tmp_path)
    repo.upsert_dataset(conn, "ds-eur", "{}")
    repo.upsert_dataset(conn, "ds-gbp", "{}")
    cv_id = repo.create_config_version(conn, "{}", note="test")
    run_id = repo.create_run(conn, cv_id, {"EURUSD": "ds-eur", "GBPUSD": "ds-gbp"}, 10_000.0)

    trading_day = "2024-01-02"
    # A LOSS on EURUSD, then a LOSS on GBPUSD -- the derived counters must combine both,
    # since account risk (daily-loss-limit, consecutive-loss streaks) is account-wide.
    for symbol, result in [("EURUSD", "LOSS"), ("GBPUSD", "LOSS")]:
        repo.insert_trade(
            conn,
            repo.TradeRecord(
                run_id=run_id,
                symbol=symbol,
                strategy="BREAKOUT",
                direction="BUY",
                status="CLOSED",
                result=result,
                trading_day=trading_day,
                closed_at_utc=f"2024-01-02T{10 if symbol == 'EURUSD' else 11:02d}:00:00+00:00",
                pnl_amount=-1.0,
                pnl_r=-1.0,
            ),
        )

    assert repo.daily_loss_count(conn, run_id, trading_day) == 2
    assert repo.consecutive_losses(conn, run_id) == 2

    # Open one PENDING trade per symbol -- `open_trades` in the account_state cache must
    # equal a live COUNT(*) across BOTH symbols, not per-symbol.
    for symbol in ("EURUSD", "GBPUSD"):
        repo.insert_trade(
            conn,
            repo.TradeRecord(
                run_id=run_id, symbol=symbol, strategy="BREAKOUT", direction="BUY", status="PENDING"
            ),
        )
    live_open_count = repo.count_open_trades(conn, run_id)
    assert live_open_count == 2
    repo.update_account_state(conn, run_id, open_trades=live_open_count)
    cache = repo.get_account_state(conn, run_id)
    assert cache["open_trades"] == 2 == live_open_count
