"""Run registry endpoints (plan 03): /api/runs list, report, per-run reads, compare,
bars (no-lookahead), delete."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _make_run(client: TestClient, seed: int, bars: int, steps: int) -> int:
    resp = client.post("/api/run", json={"seed": seed, "bars": bars})
    assert resp.status_code == 200
    run_id: int = resp.json()["id"]
    for _ in range(steps):
        if client.post("/api/run/step").json()["exhausted"]:
            break
    return run_id


def test_list_runs_and_report(client: TestClient) -> None:
    run_a = _make_run(client, seed=42, bars=400, steps=150)
    run_b = _make_run(client, seed=42, bars=400, steps=50)  # replaces active run

    runs = client.get("/api/runs").json()
    assert [r["id"] for r in runs] == [run_b, run_a]
    by_id = {r["id"]: r for r in runs}
    assert by_id[run_b]["is_active"] is True
    assert by_id[run_a]["is_active"] is False
    assert by_id[run_a]["bars_processed"] == 150
    assert by_id[run_a]["final_equity"] is not None
    assert by_id[run_a]["config_version"] >= 1

    # report works on the OLD (non-active) run
    report = client.get(f"/api/runs/{run_a}/report")
    assert report.status_code == 200
    body = report.json()
    assert body["run_id"] == run_a
    assert body["series"]["n_bars"] == 150
    assert sum(body["reason_histogram"].values()) == 150
    assert body["overall"]["n_total"] == body["overall"]["n_win"] + body["overall"][
        "n_loss"
    ] + body["overall"]["n_breakeven"]
    assert isinstance(body["filter_block_counts"], dict)

    assert client.get("/api/runs/99999/report").status_code == 404


def test_per_run_reads_on_old_run(client: TestClient) -> None:
    run_a = _make_run(client, seed=42, bars=300, steps=100)
    _make_run(client, seed=7, bars=300, steps=10)

    equity = client.get(f"/api/runs/{run_a}/equity").json()
    assert len(equity) == 100

    decisions = client.get(f"/api/runs/{run_a}/decisions?limit=1000").json()
    assert len(decisions) == 100
    assert all(d["run_id"] == run_a for d in decisions)

    trades = client.get(f"/api/runs/{run_a}/trades").json()
    assert all(t["run_id"] == run_a for t in trades)

    assert client.get("/api/runs/99999/equity").status_code == 404


def test_compare_runs(client: TestClient) -> None:
    run_a = _make_run(client, seed=42, bars=300, steps=100)
    run_b = _make_run(client, seed=42, bars=300, steps=60)

    resp = client.get(f"/api/runs/compare?a={run_a}&b={run_b}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["same_dataset"] is True
    assert body["same_config_version"] is True
    assert body["metrics"]["n_total"]["a"] is not None
    assert set(body["metrics"]) >= {"win_rate", "final_equity", "max_drawdown_pct"}
    # compare reports the config VERSION number, the same one /api/runs shows -- not the
    # config_version row id.
    by_id = {r["id"]: r for r in client.get("/api/runs").json()}
    assert body["config_version_a"] == by_id[run_a]["config_version"]
    assert body["config_version_b"] == by_id[run_b]["config_version"]
    hist_diff = body["reason_histogram"]
    assert sum(v["a"] for v in hist_diff.values()) == 100
    assert sum(v["b"] for v in hist_diff.values()) == 60

    assert client.get(f"/api/runs/compare?a={run_a}&b=99999").status_code == 404


def test_bars_no_lookahead_grows_one_candle_per_step(client: TestClient) -> None:
    # One chart candle per step only holds at the run's OWN timeframe; a coarser chart tf
    # advances slower (30 steps of 15m = 7.5h = 7 closed 1H candles).
    run_tf: str = client.get("/api/config").json()["config"]["timeframe"]
    run_id = _make_run(client, seed=42, bars=300, steps=30)

    bars = client.get(f"/api/runs/{run_id}/bars", params={"tf": run_tf}).json()
    # exactly the processed bars are closed -- never more (C11)
    assert len(bars) == 30
    assert list(bars[0]) == ["ts_utc", "open", "high", "low", "close"]

    client.post("/api/run/step")
    bars2 = client.get(f"/api/runs/{run_id}/bars", params={"tf": run_tf}).json()
    assert len(bars2) == 31
    assert bars2[:30] == bars

    # a coarser chart tf never shows a candle that has not closed yet (C11)
    last_close = client.get(f"/api/runs/{run_id}/equity").json()[-1]["bar_ts_utc"]
    hourly = client.get(f"/api/runs/{run_id}/bars", params={"tf": "1H"}).json()
    assert hourly, "expected at least one closed 1H candle after 31 steps"
    assert max(b["ts_utc"] for b in hourly) < last_close

    # range filter
    windowed = client.get(
        f"/api/runs/{run_id}/bars",
        params={"tf": run_tf, "from": bars[5]["ts_utc"], "to": bars[10]["ts_utc"]},
    ).json()
    assert [b["ts_utc"] for b in windowed] == [b["ts_utc"] for b in bars[5:11]]

    # limit keeps the most recent bars
    tail = client.get(f"/api/runs/{run_id}/bars", params={"tf": run_tf, "limit": 5}).json()
    assert tail == bars2[-5:]

    assert client.get(f"/api/runs/{run_id}/bars?tf=nope").status_code == 400
    assert client.get("/api/runs/99999/bars").status_code == 404


def test_delete_run_forbids_active(client: TestClient) -> None:
    run_a = _make_run(client, seed=42, bars=300, steps=20)
    run_b = _make_run(client, seed=7, bars=300, steps=5)

    assert client.delete(f"/api/runs/{run_b}").status_code == 409  # active
    assert client.delete("/api/runs/99999").status_code == 404

    resp = client.delete(f"/api/runs/{run_a}")
    assert resp.status_code == 200
    assert [r["id"] for r in client.get("/api/runs").json()] == [run_b]
    assert client.get(f"/api/runs/{run_a}/report").status_code == 404
