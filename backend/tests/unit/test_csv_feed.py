"""load_csv: validation (grid/duplicates/NaN/OHLC) and native_tf resampling
(plan 02 -- real historical data)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bot.core.errors import FeedError
from bot.data.csv_feed import load_csv

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "csv" / "eurusd_15m_sample.csv"


def _bar(ts: str, o: float = 1.0, h: float = 1.0, low_: float = 1.0, c: float = 1.0) -> dict:
    return {"open_ts": ts, "open": o, "high": h, "low": low_, "close": c, "volume": 1}


def _write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    df = pd.DataFrame(rows).set_index("open_ts")
    path = tmp_path / "custom.csv"
    df.to_csv(path)
    return path


def test_load_csv_15m_fixture_round_trips():
    frames = load_csv(FIXTURE, "15m")
    assert set(frames) == {"15m", "1H", "4H", "1D", "1W"}
    assert len(frames["15m"]) == 2000
    assert frames["15m"].index.is_monotonic_increasing


def test_load_csv_base_1h_has_no_15m(tmp_path: Path):
    frames = load_csv(FIXTURE, "15m")
    # Resample the 15m fixture down to 1H first (as a stand-in "native 1H" source),
    # then round-trip it through load_csv at native_tf="1H".
    df1h = frames["1H"]
    path_1h = tmp_path / "1h_fixture.csv"
    df1h.to_csv(path_1h)
    frames_1h = load_csv(path_1h, "1H")
    assert set(frames_1h) == {"1H", "4H", "1D", "1W"}
    assert "15m" not in frames_1h


def test_out_of_order_open_ts_rejected(tmp_path: Path):
    rows = [_bar("2024-01-01T00:15:00Z"), _bar("2024-01-01T00:00:00Z")]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(FeedError, match="strictly increasing"):
        load_csv(path, "15m")


def test_duplicate_open_ts_rejected(tmp_path: Path):
    rows = [_bar("2024-01-01T00:00:00Z"), _bar("2024-01-01T00:00:00Z")]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(FeedError, match="duplicate"):
        load_csv(path, "15m")


def test_nan_rejected(tmp_path: Path):
    rows = [_bar("2024-01-01T00:00:00Z"), {**_bar("2024-01-01T00:15:00Z"), "open": ""}]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(FeedError, match="NaN"):
        load_csv(path, "15m")


def test_high_below_close_rejected(tmp_path: Path):
    rows = [_bar("2024-01-01T00:00:00Z", o=1.0, h=0.5, low_=0.4, c=1.2)]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(FeedError, match="high"):
        load_csv(path, "15m")


def test_low_above_open_rejected(tmp_path: Path):
    rows = [_bar("2024-01-01T00:00:00Z", o=1.0, h=1.5, low_=1.1, c=1.2)]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(FeedError, match="low"):
        load_csv(path, "15m")


def test_misaligned_grid_rejected(tmp_path: Path):
    rows = [_bar("2024-01-01T00:00:00Z"), _bar("2024-01-01T00:05:00Z")]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(FeedError, match="grid"):
        load_csv(path, "15m")


def test_grid_allows_gaps(tmp_path: Path):
    # Weekend-style gap: still a multiple of 15m from the first bar -> valid.
    rows = [_bar("2024-01-01T00:00:00Z"), _bar("2024-01-03T00:00:00Z")]
    path = _write_csv(tmp_path, rows)
    frames = load_csv(path, "15m")
    assert len(frames["15m"]) == 2


def test_1d_grid_allows_missing_days_but_not_time_drift(tmp_path: Path):
    ok_rows = [_bar("2024-01-01T21:00:00Z"), _bar("2024-01-03T21:00:00Z")]
    path = _write_csv(tmp_path, ok_rows)
    frames = load_csv(path, "1D")
    assert len(frames["1D"]) == 2
    assert "1W" in frames

    bad_rows = [_bar("2024-01-01T21:00:00Z"), _bar("2024-01-02T22:00:00Z")]
    bad_path = _write_csv(tmp_path, bad_rows)
    with pytest.raises(FeedError, match="1D grid"):
        load_csv(bad_path, "1D")
