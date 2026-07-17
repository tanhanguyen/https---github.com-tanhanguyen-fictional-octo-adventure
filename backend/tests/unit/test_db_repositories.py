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
    run_id = repo.create_run(conn, "ds1", cv_id, "EURUSD", 10_000.0)
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
