"""`GET /api/live/status` + `POST /api/live/stop` (plan 07 §4).

The live runner owns its own DB file; the API only reads it (and writes exactly one
flag). These tests point `BOT_DB_PATH` at a temp file and drive it directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bot.api.app import create_app
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate

UTC = timezone.utc


@pytest.fixture
def live_db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "live.db"
    monkeypatch.setenv("BOT_DB_PATH", str(path))
    return path


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(db_path=str(tmp_path / "api.db"))
    with TestClient(app) as c:
        yield c
    app.state.runner_service.close()


def seed_live_run(path: Path, last_bar: datetime | None, started: datetime) -> int:
    conn = connect_and_migrate(str(path))
    repo.upsert_live_dataset(conn, "live:BTCUSDT", "BTCUSDT", "15m")
    cv = repo.create_config_version(conn, "{}", note="live")
    run_id = repo.create_run(conn, cv, {"BTCUSDT": "live:BTCUSDT"}, 500.0, mode="live")
    repo.update_live_status(
        conn,
        run_id,
        feed_state="ok",
        started_at_utc=started.isoformat(),
        last_bar_ts_utc=None if last_bar is None else last_bar.isoformat(),
    )
    conn.close()
    return run_id


def test_no_live_db_is_a_normal_answer_not_an_error(client, live_db):
    body = client.get("/api/live/status").json()
    assert body["running"] is False
    assert body["run_id"] is None


def test_status_reports_lag_uptime_and_feed_state(client, live_db):
    now = datetime.now(UTC)
    run_id = seed_live_run(live_db, now - timedelta(minutes=3), now - timedelta(hours=5))

    body = client.get("/api/live/status").json()

    assert body["running"] is True
    assert body["run_id"] == run_id
    assert body["symbols"] == ["BTCUSDT"]
    assert body["feed_state"] == "ok"
    assert body["stop_requested"] is False
    assert 170 < body["lag_seconds"] < 190
    assert 17_000 < body["uptime_seconds"] < 19_000
    assert body["equity"] == 500.0
    assert body["open_trades"] == 0


def test_status_without_a_processed_bar_reports_no_lag(client, live_db):
    seed_live_run(live_db, None, datetime.now(UTC))
    body = client.get("/api/live/status").json()
    assert body["running"] is True
    assert body["lag_seconds"] is None


def test_degraded_feed_is_surfaced_with_its_detail(client, live_db):
    run_id = seed_live_run(live_db, datetime.now(UTC), datetime.now(UTC))
    conn = connect_and_migrate(str(live_db))
    repo.update_live_status(conn, run_id, feed_state="degraded", detail="BTCUSDT: timeout")
    conn.close()

    body = client.get("/api/live/status").json()
    assert body["feed_state"] == "degraded"
    assert body["detail"] == "BTCUSDT: timeout"


def test_stop_sets_the_flag_the_runner_polls(client, live_db):
    run_id = seed_live_run(live_db, datetime.now(UTC), datetime.now(UTC))

    body = client.post("/api/live/stop").json()
    assert body["stop_requested"] is True

    conn = connect_and_migrate(str(live_db))
    assert repo.stop_requested(conn, run_id) is True
    # Idempotent.
    assert client.post("/api/live/stop").json()["stop_requested"] is True
    conn.close()


def test_stop_without_a_live_run_is_404(client, live_db):
    assert client.post("/api/live/stop").status_code == 404
    seed_live_run(live_db, None, datetime.now(UTC))
    conn = connect_and_migrate(str(live_db))
    repo.set_run_status(conn, 1, "STOPPED")
    conn.close()
    assert client.post("/api/live/stop").status_code == 404
