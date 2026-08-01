from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "csv" / "eurusd_15m_sample.csv"
DAILY_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "csv" / "hpg_1d_sample.csv"


def test_full_run_flow(client: TestClient) -> None:
    resp = client.post("/api/run", json={"seed": 42, "bars": 500})
    assert resp.status_code == 200
    run = resp.json()
    assert run["status"] == "RUNNING"

    equities = []
    for _ in range(200):
        step_resp = client.post("/api/run/step")
        assert step_resp.status_code == 200
        summaries = step_resp.json()
        if summaries[0]["exhausted"]:
            break
        equities.extend(s["equity"] for s in summaries)
    assert len(equities) > 0

    account = client.get("/api/account").json()
    assert account["run_id"] == run["id"]

    trades = client.get("/api/trades").json()
    assert isinstance(trades, list)

    decisions = client.get("/api/decisions?limit=10").json()
    assert len(decisions) > 0

    decision_id = decisions[0]["id"]
    detail = client.get(f"/api/decisions/{decision_id}").json()
    assert len(detail["filters"]) > 1

    stats = client.get("/api/decisions/stats").json()
    assert sum(stats["histogram"].values()) > 0


def test_step_without_run_returns_409(client: TestClient) -> None:
    resp = client.post("/api/run/step")
    assert resp.status_code == 409


def test_create_run_with_coarser_dataset_returns_400(client: TestClient) -> None:
    dataset = client.post(
        "/api/datasets/import",
        json={"path": str(DAILY_FIXTURE), "symbol": "EURUSD", "native_tf": "1D"},
    ).json()

    resp = client.post("/api/run", json={"dataset_id": dataset["id"]})

    assert resp.status_code == 400
    assert "coarser" in resp.json()["detail"]


def test_create_run_with_unknown_dataset_returns_404(client: TestClient) -> None:
    resp = client.post("/api/run", json={"dataset_id": "does-not-exist"})
    assert resp.status_code == 404


def test_create_run_with_timeframe_overrides_the_config_default(client: TestClient) -> None:
    dataset = client.post(
        "/api/datasets/import",
        json={"path": str(FIXTURE), "symbol": "EURUSD", "native_tf": "15m"},
    ).json()

    resp = client.post(
        "/api/run",
        json={"dataset_id": dataset["id"], "timeframe": "1H"},
    )
    assert resp.status_code == 200
    run = resp.json()

    for _ in range(50):
        step_resp = client.post("/api/run/step")
        summaries = step_resp.json()
        if summaries[0]["exhausted"]:
            break

    bars = client.get(f"/api/runs/{run['id']}/bars", params={"tf": "1H", "limit": 20000}).json()
    assert bars
    stamps = [b["ts_utc"] for b in bars[:5]]
    for a, b in zip(stamps, stamps[1:]):
        assert a < b


def test_create_run_with_unknown_timeframe_returns_400(client: TestClient) -> None:
    dataset = client.post(
        "/api/datasets/import",
        json={"path": str(FIXTURE), "symbol": "EURUSD", "native_tf": "15m"},
    ).json()

    resp = client.post(
        "/api/run",
        json={"dataset_id": dataset["id"], "timeframe": "5m"},
    )
    assert resp.status_code == 400


def test_play_pause(client: TestClient) -> None:
    client.post("/api/run", json={"seed": 1, "bars": 200})
    resp = client.post("/api/run/play", json={"interval_ms": 10})
    assert resp.status_code == 200
    assert resp.json()["is_playing"] is True

    import time

    time.sleep(0.2)

    pause_resp = client.post("/api/run/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["is_playing"] is False

    account = client.get("/api/account").json()
    assert account["equity"] != 0


def test_play_concurrent_with_reads_does_not_corrupt_db(client: TestClient) -> None:
    client.post("/api/run", json={"seed": 7, "bars": 5000})
    client.post("/api/run/play", json={"interval_ms": 1})

    errors: list[Exception] = []
    stop = threading.Event()

    def hammer_reads() -> None:
        while not stop.is_set():
            try:
                client.get("/api/account")
                client.get("/api/decisions?limit=10")
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

    readers = [threading.Thread(target=hammer_reads) for _ in range(4)]
    for t in readers:
        t.start()
    time.sleep(2.0)
    stop.set()
    for t in readers:
        t.join(timeout=5.0)

    client.post("/api/run/pause")

    assert errors == []

    runner_service = client.app.state.runner_service
    with runner_service.lock:
        row = runner_service.conn.execute("PRAGMA integrity_check").fetchone()
    assert row[0] == "ok"
