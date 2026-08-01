"""Plan 11 §3: `GET /api/sweeps` + `GET /api/sweeps/{id}`.

The rows are inserted directly rather than produced by a real sweep: this is a
serialisation test (does the Sweep page get what it needs, does a row link to a
drillable run), and running the engine here would add a minute per assertion for
nothing. The engine side is covered by tests/integration/test_sweep.py.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from bot.config.loader import load_default_config
from bot.db import repositories as repo


def _seed_walkforward(conn) -> int:
    repo.upsert_dataset(conn, "ds1", "{}")
    cfg_json = load_default_config().model_dump_json()
    sweep_id = repo.create_sweep(
        conn,
        kind="walkforward",
        name="wf-demo",
        dataset_id="ds1",
        symbol="EURUSD",
        timeframe="1H",
        spec_json=json.dumps(
            {
                "axes": {"strategies.breakout.scoring_threshold_ratio": [0.5, 0.66]},
                "selection": {
                    "metric": "profit_factor",
                    "max_drawdown_pct": 20.0,
                    "min_trades": 30,
                },
            }
        ),
        base_config_version_id=None,
        n_combos=2,
    )
    run_ids = []
    for i, (pf, trades) in enumerate([(1.4, 40), (0.8, 35)]):
        cv_id = repo.create_config_version(conn, cfg_json, note=f"combo{i}", activate=False)
        run_id = repo.create_run(conn, cv_id, {"EURUSD": "ds1"}, 10_000.0)
        repo.insert_equity_point(conn, run_id, "2022-01-01T00:00:00+00:00", 10_000.0, 10_000.0)
        repo.insert_equity_point(conn, run_id, "2022-01-01T01:00:00+00:00", 10_100.0, 10_100.0)
        repo.insert_sweep_result(
            conn,
            sweep_id=sweep_id,
            window_index=0,
            phase="is",
            combo_index=i,
            params_json=json.dumps(
                {"strategies.breakout.scoring_threshold_ratio": [0.5, 0.66][i]}
            ),
            run_id=run_id,
            config_version_id=cv_id,
            metrics_json=json.dumps(
                {"n_trades": trades, "profit_factor": pf, "max_drawdown_pct": 8.0}
            ),
            metric_value=pf,
            eligible=True,
            ineligible_reason="",
            window_from="2022-01-01T00:00:00+00:00",
            window_to="2023-01-01T00:00:00+00:00",
            decision_hash=f"hash{i}",
        )
        run_ids.append(run_id)
    repo.insert_sweep_window(
        conn,
        sweep_id=sweep_id,
        window_index=0,
        is_from="2022-01-01T00:00:00+00:00",
        is_to="2023-01-01T00:00:00+00:00",
        oos_from="2023-01-01T00:00:00+00:00",
        oos_to="2023-04-01T00:00:00+00:00",
        n_combos=2,
        n_eligible=2,
        selected_params_json=json.dumps(
            {"strategies.breakout.scoring_threshold_ratio": 0.5}
        ),
        is_metric=1.4,
        oos_metric=0.7,
        degradation=-0.5,
        is_run_id=run_ids[0],
        oos_run_id=run_ids[1],
        distribution_json=json.dumps({"n": 2, "n_defined": 2, "n_eligible": 2, "median": 1.1}),
    )
    repo.finish_sweep(conn, sweep_id, "DONE", 3)
    return sweep_id


def test_sweeps_list_is_empty_before_any_sweep(client: TestClient) -> None:
    assert client.get("/api/sweeps").json() == []


def test_sweeps_list_and_detail(client: TestClient) -> None:
    service = client.app.state.runner_service
    sweep_id = _seed_walkforward(service.conn)

    listed = client.get("/api/sweeps").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "wf-demo"
    assert listed[0]["kind"] == "walkforward"
    assert listed[0]["status"] == "DONE"

    detail = client.get(f"/api/sweeps/{sweep_id}").json()
    assert detail["axes"] == ["strategies.breakout.scoring_threshold_ratio"]
    assert detail["selection"]["min_trades"] == 30
    assert len(detail["results"]) == 2
    assert detail["results"][0]["params"] == {
        "strategies.breakout.scoring_threshold_ratio": 0.5
    }
    assert detail["windows"][0]["degradation"] == -0.5
    assert detail["windows"][0]["distribution"]["median"] == 1.1


def test_a_sweep_row_links_to_a_run_that_reports(client: TestClient) -> None:
    """The drill-down promised by plan 11 §1: click a row -> that run's Report page."""
    service = client.app.state.runner_service
    sweep_id = _seed_walkforward(service.conn)
    run_id = client.get(f"/api/sweeps/{sweep_id}").json()["results"][0]["run_id"]

    report = client.get(f"/api/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["run_id"] == run_id


def test_the_stitched_oos_curve_is_returned_for_a_walkforward(client: TestClient) -> None:
    service = client.app.state.runner_service
    sweep_id = _seed_walkforward(service.conn)
    curve = client.get(f"/api/sweeps/{sweep_id}").json()["oos_equity"]
    assert [p["bar_ts_utc"] for p in curve] == [
        "2022-01-01T00:00:00+00:00",
        "2022-01-01T01:00:00+00:00",
    ]
    assert curve[0]["equity"] == 10_000.0


def test_unknown_sweep_is_404(client: TestClient) -> None:
    assert client.get("/api/sweeps/999").status_code == 404
