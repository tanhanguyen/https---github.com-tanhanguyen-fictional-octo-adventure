"""Plan 11 §2: walk-forward end to end on synthetic data.

The assertion that matters is the boundary one — after a full IS sweep + OOS run, NO
decision of an out-of-sample run may fall inside its in-sample window and vice versa.
That is checked against the persisted `decision` rows, i.e. against what the engine
actually did, not against the slicing helper that is already unit-tested.

Window months are 1/1/1 instead of the chosen 12/3/3 purely for runtime: the schedule
arithmetic is timeframe-agnostic and unit-tested in `test_walkforward_windows.py`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from bot.data.dataset import DatasetSpec
from bot.data.dataset import dataset_id as compute_dataset_id
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.research.spec import Selection, SweepSpec, WalkForward
from bot.research.walkforward import run_walkforward

pytestmark = pytest.mark.slow

#: ~4 months of 1H bars -> three complete 1m-IS + 1m-OOS windows.
N_CANDLES_15M = 4 * 30 * 24 * 4


def _spec(dataset_id: str) -> SweepSpec:
    return SweepSpec(
        dataset_id=dataset_id,
        name="test-wf",
        timeframe="1H",
        axes={"filters.session.enabled": [True, False]},
        # `final_equity` is always defined (profit_factor is None on a trade-less
        # synthetic window, which would make every window "no eligible combo" and leave
        # nothing to assert about the OOS pass).
        selection=Selection(metric="final_equity", max_drawdown_pct=100.0, min_trades=0),
        walkforward=WalkForward(is_months=1, oos_months=1, step_months=1),
    )


@pytest.fixture(scope="module")
def walkforward_db(tmp_path_factory) -> tuple[str, int]:
    tmp_path = tmp_path_factory.mktemp("wf")
    db_path = str(tmp_path / "wf.db")
    conn = connect_and_migrate(db_path)
    try:
        spec = DatasetSpec(seed=42, n_candles_15m=N_CANDLES_15M, symbol="EURUSD")
        did = compute_dataset_id(spec)
        repo.upsert_dataset(conn, did, json.dumps(asdict(spec)))
        sweep_id = run_walkforward(
            db_path, _spec(did), workers=1, conn=conn, log=lambda _m: None
        )
    finally:
        conn.close()
    return db_path, sweep_id


@pytest.fixture
def conn(walkforward_db):
    db_path, _ = walkforward_db
    c = connect_and_migrate(db_path)
    yield c
    c.close()


@pytest.fixture
def sweep_id(walkforward_db) -> int:
    return walkforward_db[1]


def _decision_span(conn, run_id: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    lo, hi = conn.execute(
        "SELECT MIN(bar_ts_utc), MAX(bar_ts_utc) FROM decision WHERE run_id=?", (run_id,)
    ).fetchone()
    return pd.Timestamp(lo), pd.Timestamp(hi)


def test_every_window_ran_the_full_grid_on_is_and_exactly_one_run_on_oos(conn, sweep_id) -> None:
    windows = repo.list_sweep_windows(conn, sweep_id)
    assert len(windows) >= 2

    results = repo.list_sweep_results(conn, sweep_id)
    for w in windows:
        idx = w["window_index"]
        is_rows = [r for r in results if r["window_index"] == idx and r["phase"] == "is"]
        oos_rows = [r for r in results if r["window_index"] == idx and r["phase"] == "oos"]
        assert len(is_rows) == 2, "the whole grid must run on IS"
        assert len(oos_rows) == 1, "exactly one OOS run per window"
        assert sum(r["selected"] for r in is_rows) == 1
        assert w["n_combos"] == 2

        selected = next(r for r in is_rows if r["selected"])
        assert json.loads(oos_rows[0]["params_json"]) == json.loads(selected["params_json"])
        assert w["is_run_id"] == selected["run_id"]
        assert w["oos_run_id"] == oos_rows[0]["run_id"]


def test_no_oos_run_ever_decided_on_an_in_sample_bar(conn, sweep_id) -> None:
    """The leak test, on persisted engine output: OOS decisions live strictly inside the
    OOS window, IS decisions strictly inside the IS window. A decision timestamp is the
    bar CLOSE, hence the half-open (from, to] bounds."""
    for w in repo.list_sweep_windows(conn, sweep_id):
        is_from, is_to = pd.Timestamp(w["is_from"]), pd.Timestamp(w["is_to"])
        oos_from, oos_to = pd.Timestamp(w["oos_from"]), pd.Timestamp(w["oos_to"])
        assert oos_from == is_to

        lo, hi = _decision_span(conn, w["oos_run_id"])
        assert lo > oos_from and hi <= oos_to
        assert lo > is_to, "an OOS run decided on an in-sample bar"

        for r in repo.list_sweep_results(conn, sweep_id):
            if r["window_index"] != w["window_index"] or r["phase"] != "is":
                continue
            lo, hi = _decision_span(conn, r["run_id"])
            assert lo > is_from and hi <= is_to, "an IS run decided outside its window"


def test_the_windows_slide_by_the_configured_step(conn, sweep_id) -> None:
    windows = repo.list_sweep_windows(conn, sweep_id)
    for a, b in zip(windows, windows[1:], strict=False):
        assert pd.Timestamp(b["is_from"]) == pd.Timestamp(a["is_from"]) + pd.DateOffset(months=1)


def test_the_overfit_report_records_the_full_is_distribution(conn, sweep_id) -> None:
    """Plan 11 §2: the denominator of the selection bias (how many combos were tried)
    and the spread of the metric over all of them, not just the winner."""
    sweep = repo.get_sweep(conn, sweep_id)
    assert sweep is not None and sweep["status"] == "DONE"
    assert sweep["kind"] == "walkforward"

    for w in repo.list_sweep_windows(conn, sweep_id):
        dist = json.loads(w["distribution_json"])
        assert dist["n"] == w["n_combos"] == 2
        assert dist["min"] <= dist["median"] <= dist["max"]
        assert w["n_eligible"] == dist["n_eligible"]


def test_degradation_matches_the_is_and_oos_metrics(conn, sweep_id) -> None:
    for w in repo.list_sweep_windows(conn, sweep_id):
        if w["degradation"] is None:
            continue
        expected = (w["oos_metric"] - w["is_metric"]) / abs(w["is_metric"])
        assert w["degradation"] == pytest.approx(expected)


def test_every_sweep_row_points_at_a_run_that_can_be_reported_on(conn, sweep_id) -> None:
    for r in repo.list_sweep_results(conn, sweep_id):
        run = conn.execute("SELECT * FROM run WHERE id=?", (r["run_id"],)).fetchone()
        assert run is not None
        n = conn.execute(
            "SELECT COUNT(*) FROM equity_point WHERE run_id=?", (r["run_id"],)
        ).fetchone()[0]
        assert n == json.loads(r["metrics_json"])["n_bars"] > 0


def test_stitched_oos_equity_covers_every_traded_window(conn, sweep_id) -> None:
    from bot.research.sweep import stitched_equity

    run_ids = [
        w["oos_run_id"] for w in repo.list_sweep_windows(conn, sweep_id) if w["oos_run_id"]
    ]
    curve = stitched_equity(conn, run_ids)
    assert len(curve) == sum(
        conn.execute("SELECT COUNT(*) FROM equity_point WHERE run_id=?", (rid,)).fetchone()[0]
        for rid in run_ids
    )
    assert [p["bar_ts_utc"] for p in curve] == sorted(p["bar_ts_utc"] for p in curve)


def test_walkforward_needs_a_walkforward_block(tmp_path: Path) -> None:
    from bot.core.errors import ConfigError

    db_path = str(tmp_path / "x.db")
    conn = connect_and_migrate(db_path)
    try:
        spec = SweepSpec(dataset_id="x", axes={"timeframe": ["1H"]})
        with pytest.raises(ConfigError, match="walkforward"):
            run_walkforward(db_path, spec, conn=conn, log=lambda _m: None)
    finally:
        conn.close()
