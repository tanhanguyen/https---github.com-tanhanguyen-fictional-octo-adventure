"""import_csv_dataset: idempotent by file content, load_bundle_for_dataset dispatches
on `kind`, native_tf guard at run-creation time (plan 02)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bot.api.run_service import RunnerService
from bot.config.loader import load_default_config
from bot.core.errors import ConfigError
from bot.core.timeframes import tf_rank
from bot.data.dataset import import_csv_dataset, load_bundle_for_dataset
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "csv" / "eurusd_15m_sample.csv"


def _daily_bar(ts: str) -> dict:
    return {"open_ts": ts, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}


def _write_daily_fixture(tmp_path: Path, name: str) -> Path:
    rows = [_daily_bar("2024-01-01T21:00:00Z"), _daily_bar("2024-01-02T21:00:00Z")]
    path = tmp_path / name
    pd.DataFrame(rows).set_index("open_ts").to_csv(path)
    return path


def test_import_is_idempotent_by_file_content():
    conn = connect_and_migrate(":memory:")
    r1 = import_csv_dataset(conn, FIXTURE, "EURUSD", "15m")
    r2 = import_csv_dataset(conn, FIXTURE, "EURUSD", "15m")
    assert r1.dataset_id == r2.dataset_id
    rows = conn.execute("SELECT COUNT(*) FROM dataset WHERE kind='csv'").fetchone()
    assert rows[0] == 1


def test_registered_metadata_matches_fixture():
    conn = connect_and_migrate(":memory:")
    result = import_csv_dataset(conn, FIXTURE, "EURUSD", "15m")
    assert result.symbol == "EURUSD"
    assert result.native_tf == "15m"
    assert result.bar_count == 2000
    assert result.gap_count == 0  # contiguous synthetic fixture, no gaps


def test_load_bundle_for_dataset_csv_kind():
    conn = connect_and_migrate(":memory:")
    result = import_csv_dataset(conn, FIXTURE, "EURUSD", "15m")
    config = load_default_config()
    bundle = load_bundle_for_dataset(conn, result.dataset_id, config)
    assert "15m" in bundle.price
    assert bundle.dxy is None  # no dxy dataset_id configured


def test_native_tf_coarser_than_config_timeframe_is_rejected(tmp_path: Path):
    conn = connect_and_migrate(":memory:")
    # Build a native-1D dataset (only 2 daily bars needed for the rank check itself).
    path = _write_daily_fixture(tmp_path, "daily_fixture.csv")

    result = import_csv_dataset(conn, path, "EURUSD", "1D")
    config = load_default_config()  # default timeframe is "1H", coarser than 1D
    row = repo.get_dataset(conn, result.dataset_id)
    assert row is not None
    assert tf_rank(row["native_tf"]) > tf_rank(config.timeframe)


def test_run_service_rejects_coarser_native_tf(tmp_path: Path):
    """End-to-end: RunnerService.create_run must refuse a CSV dataset whose
    native_tf is coarser than the active config.timeframe (default config runs 1H)."""
    path = _write_daily_fixture(tmp_path, "daily_fixture2.csv")

    service = RunnerService(":memory:")
    imported = service.import_csv(str(path), "EURUSD", "1D")
    with pytest.raises(ConfigError):
        service.create_run(dataset_id=imported.dataset_id)


def test_run_service_accepts_finer_or_equal_native_tf():
    service = RunnerService(":memory:")
    imported = service.import_csv(str(FIXTURE), "EURUSD", "15m")
    # default config.timeframe is "1H"; native "15m" is finer -> allowed.
    info = service.create_run(dataset_id=imported.dataset_id)
    assert info["dataset_id"] == imported.dataset_id
    summary = service.step()
    assert summary is not None
