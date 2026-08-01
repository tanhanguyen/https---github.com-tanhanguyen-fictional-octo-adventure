"""Plan 11 §"Kiểm thử": sweep on a small fixed synthetic dataset.

- enough result rows, each pointing at a REAL run that can be drilled into,
- every run deterministic (two identical sweeps agree bar-for-bar),
- `--workers 4` identical to sequential,
- the cost guard actually guards.

Synthetic data is enough here on purpose (plan 11: "Không test nào cần dữ liệu thật") —
these tests are about the sweep machinery, not about which parameters are good. The
window is deliberately short: the point is plumbing, and the engine costs ~100 bars/s.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from bot.core.errors import ConfigError
from bot.data.dataset import DatasetSpec
from bot.data.dataset import dataset_id as compute_dataset_id
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.research.spec import Selection, SweepSpec
from bot.research.sweep import run_sweep

pytestmark = pytest.mark.slow

#: A ~15-day 1H window inside the generated series: two combos over it run in a few
#: seconds while still exercising trades/decisions/equity end to end.
WINDOW_FROM = "2023-01-20"
WINDOW_TO = "2023-02-04"


def _dataset(conn) -> str:
    spec = DatasetSpec(seed=42, n_candles_15m=(400 + 400) * 4, symbol="EURUSD")
    did = compute_dataset_id(spec)
    repo.upsert_dataset(conn, did, json.dumps(asdict(spec)))
    return did


def _spec(dataset_id: str, **kwargs) -> SweepSpec:
    base = dict(
        dataset_id=dataset_id,
        name="test-sweep",
        timeframe="1H",
        from_ts=WINDOW_FROM,
        to_ts=WINDOW_TO,
        axes={"filters.session.enabled": [True, False]},
        # Relaxed so the machinery is exercised rather than short-circuited: the real
        # ❓2 constraints (30 trades) are unreachable on a 15-day synthetic window.
        selection=Selection(metric="profit_factor", max_drawdown_pct=100.0, min_trades=0),
    )
    base.update(kwargs)
    return SweepSpec(**base)  # type: ignore[arg-type]


def _rows(conn, sweep_id: int) -> list[dict]:
    return [dict(r) for r in repo.list_sweep_results(conn, sweep_id)]


def _fingerprint(rows: list[dict]) -> list[tuple]:
    """What must be identical between two runs of the same sweep — everything except
    the wall-clock timestamps."""
    return [
        (r["combo_index"], r["params_json"], r["metrics_json"], r["decision_hash"], r["run_id"])
        for r in rows
    ]


def _run(tmp_path: Path, name: str, workers: int, **spec_kwargs):
    db_path = str(tmp_path / f"{name}.db")
    conn = connect_and_migrate(db_path)
    did = _dataset(conn)
    sweep_id = run_sweep(
        db_path, _spec(did, **spec_kwargs), workers=workers, conn=conn, log=lambda _m: None
    )
    return conn, sweep_id


def test_a_sweep_produces_one_drillable_run_per_combo(tmp_path: Path) -> None:
    conn, sweep_id = _run(tmp_path, "basic", workers=1)
    try:
        rows = _rows(conn, sweep_id)
        assert len(rows) == 2

        sweep = repo.get_sweep(conn, sweep_id)
        assert sweep is not None
        assert sweep["status"] == "DONE"
        assert sweep["kind"] == "grid"
        assert sweep["n_combos"] == 2

        for row in rows:
            run = conn.execute("SELECT * FROM run WHERE id=?", (row["run_id"],)).fetchone()
            assert run is not None, "sweep row must point at a real registry run"
            assert run["config_version_id"] == row["config_version_id"]
            # The drill-down target: a Report page needs decisions + equity, not just a row.
            n_decisions = conn.execute(
                "SELECT COUNT(*) FROM decision WHERE run_id=?", (row["run_id"],)
            ).fetchone()[0]
            n_equity = conn.execute(
                "SELECT COUNT(*) FROM equity_point WHERE run_id=?", (row["run_id"],)
            ).fetchone()[0]
            assert n_decisions > 0 and n_equity == n_decisions

            # ...and the config version really carries this combo's parameter.
            cfg = json.loads(
                conn.execute(
                    "SELECT config_json FROM config_version WHERE id=?",
                    (row["config_version_id"],),
                ).fetchone()[0]
            )
            params = json.loads(row["params_json"])
            assert cfg["filters"]["session"]["enabled"] == params["filters.session.enabled"]
    finally:
        conn.close()


def test_a_sweep_never_hijacks_the_active_config_version(tmp_path: Path) -> None:
    """A research job creating 100+ versions must not leave the user's UI pointing at
    the last combo it happened to try."""
    db_path = str(tmp_path / "active.db")
    conn = connect_and_migrate(db_path)
    try:
        from bot.config.loader import load_default_config

        seeded = repo.create_config_version(
            conn, load_default_config().model_dump_json(), note="seed"
        )
        did = _dataset(conn)
        run_sweep(db_path, _spec(did), workers=1, conn=conn, log=lambda _m: None)

        active = repo.get_active_config_version(conn)
        assert active is not None and active["id"] == seeded
        assert conn.execute("SELECT COUNT(*) FROM config_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_the_toggled_parameter_actually_changes_the_runs(tmp_path: Path) -> None:
    """Guards against the failure mode the spec validation exists to prevent: if the
    patch never reached the engine, every combo would report identical numbers and the
    sweep would look conclusive while measuring nothing."""
    conn, sweep_id = _run(tmp_path, "effect", workers=1)
    try:
        hashes = {r["decision_hash"] for r in _rows(conn, sweep_id)}
        assert len(hashes) == 2
    finally:
        conn.close()


def test_two_identical_sweeps_agree_exactly(tmp_path: Path) -> None:
    a_conn, a_id = _run(tmp_path, "det-a", workers=1)
    b_conn, b_id = _run(tmp_path, "det-b", workers=1)
    try:
        assert _fingerprint(_rows(a_conn, a_id)) == _fingerprint(_rows(b_conn, b_id))
    finally:
        a_conn.close()
        b_conn.close()


def test_parallel_workers_reproduce_the_sequential_result(tmp_path: Path) -> None:
    """Plan 11 §1: "Kết quả phải giống hệt chạy tuần tự (test)". Merging in combo order
    means even the run ids line up, so the whole fingerprint is comparable."""
    seq_conn, seq_id = _run(tmp_path, "seq", workers=1)
    par_conn, par_id = _run(tmp_path, "par", workers=4)
    try:
        assert _fingerprint(_rows(par_conn, par_id)) == _fingerprint(_rows(seq_conn, seq_id))

        # The merge must carry the whole run, not just the summary row.
        for table in ("decision", "equity_point", "trade"):
            seq_n = seq_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            par_n = par_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert par_n == seq_n, table
        seq_df = seq_conn.execute("SELECT COUNT(*) FROM decision_filter").fetchone()[0]
        par_df = par_conn.execute("SELECT COUNT(*) FROM decision_filter").fetchone()[0]
        assert par_df == seq_df

        # ...and the merged foreign keys must be remapped, not copied verbatim.
        orphans = par_conn.execute(
            "SELECT COUNT(*) FROM decision_filter df "
            "LEFT JOIN decision d ON d.id = df.decision_id WHERE d.id IS NULL"
        ).fetchone()[0]
        assert orphans == 0
    finally:
        seq_conn.close()
        par_conn.close()


def test_the_cost_guard_refuses_a_big_grid_without_yes(tmp_path: Path) -> None:
    db_path = str(tmp_path / "guard.db")
    conn = connect_and_migrate(db_path)
    try:
        did = _dataset(conn)
        big = _spec(did, axes={"strategies.breakout.tp1_r": [1.0 + i / 100 for i in range(201)]})
        with pytest.raises(ConfigError, match="Re-run with --yes"):
            run_sweep(db_path, big, workers=1, conn=conn, log=lambda _m: None)
        # Nothing may have been created before the guard fired.
        assert conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sweep").fetchone()[0] == 0
    finally:
        conn.close()


def test_an_unknown_dataset_fails_before_any_run_is_created(tmp_path: Path) -> None:
    db_path = str(tmp_path / "nodata.db")
    conn = connect_and_migrate(db_path)
    try:
        with pytest.raises(ConfigError, match="unknown dataset"):
            run_sweep(db_path, _spec("nope"), workers=1, conn=conn, log=lambda _m: None)
        assert conn.execute("SELECT COUNT(*) FROM sweep").fetchone()[0] == 0
    finally:
        conn.close()
