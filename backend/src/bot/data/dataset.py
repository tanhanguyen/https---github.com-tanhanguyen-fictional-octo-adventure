"""Dataset spec + content-addressed id + CSV cache under data/generated/<dataset_id>/."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from bot.core.timeframes import tf_duration
from bot.data.csv_feed import load_csv
from bot.data.resample import build_all_timeframes
from bot.data.synthetic import generate_dxy_series, generate_price_series
from bot.db import repositories as repo

if TYPE_CHECKING:
    from bot.config.models import BotConfig


@dataclass(frozen=True)
class DatasetSpec:
    seed: int
    n_candles_15m: int
    start_price: float = 1.1000
    symbol: str = "EURUSD"
    rollover_tz: str = "America/New_York"
    rollover_time: str = "17:00"


def canonical_json(spec: DatasetSpec) -> str:
    return json.dumps(asdict(spec), sort_keys=True, separators=(",", ":"))


def dataset_id(spec: DatasetSpec) -> str:
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()[:16]


def named_child_seed(base_seed: int, name: str) -> int:
    """Plan 04: a deterministic per-symbol child seed derived from a portfolio-level
    base seed + the symbol name (a *name*, not a positional index) -- so adding a new
    symbol to `BotConfig.symbols` never perturbs another symbol's synthetic stream."""
    name_hash = zlib.crc32(name.encode("utf-8")) & 0xFFFFFFFF
    seq = np.random.SeedSequence(base_seed, spawn_key=(name_hash,))
    return int(seq.generate_state(1, dtype=np.uint32)[0])


def _generated_root() -> Path:
    # src/bot/data/dataset.py -> parents[3] == backend/
    return Path(__file__).resolve().parents[3] / "data" / "generated"


def generate_bundle(spec: DatasetSpec) -> dict[str, dict[str, pd.DataFrame]]:
    """Returns {"price": {tf: df}, "dxy": {tf: df}}. Does not touch disk."""
    df15, _labels = generate_price_series(spec.seed, spec.n_candles_15m, spec.start_price)
    dxy15 = generate_dxy_series(spec.seed, df15)
    price_frames = build_all_timeframes(df15, spec.rollover_tz, spec.rollover_time)
    dxy_frames = build_all_timeframes(dxy15, spec.rollover_tz, spec.rollover_time)
    return {"price": price_frames, "dxy": dxy_frames}


def load_or_generate(spec: DatasetSpec, cache: bool = True) -> dict[str, dict[str, pd.DataFrame]]:
    """Cache the 15m base frames to CSV under data/generated/<id>/ (plan requirement);
    higher timeframes are always recomputed by resampling (cheap, and keeps a single
    source of truth for MTF consistency)."""
    did = dataset_id(spec)
    root = _generated_root() / did
    price_path = root / "price_15m.csv"
    dxy_path = root / "dxy_15m.csv"

    if cache and price_path.exists() and dxy_path.exists():
        df15 = pd.read_csv(price_path, index_col="open_ts", parse_dates=["open_ts"])
        dxy15 = pd.read_csv(dxy_path, index_col="open_ts", parse_dates=["open_ts"])
    else:
        df15, _labels = generate_price_series(spec.seed, spec.n_candles_15m, spec.start_price)
        dxy15 = generate_dxy_series(spec.seed, df15)
        if cache:
            root.mkdir(parents=True, exist_ok=True)
            df15.to_csv(price_path)
            dxy15.to_csv(dxy_path)

    price_frames = build_all_timeframes(df15, spec.rollover_tz, spec.rollover_time)
    dxy_frames = build_all_timeframes(dxy15, spec.rollover_tz, spec.rollover_time)
    return {"price": price_frames, "dxy": dxy_frames}


# ---------------------------------------------------------------------------
# CSV datasets (plan 02): real historical data, registered in the `dataset` table
# alongside synthetic specs, distinguished by `kind`.
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_grid_gaps(df: pd.DataFrame, tf: str) -> int:
    """Informational only (plan: gap policy is no-fill, just counted). Counts
    missing slots on the tf grid anchored at the first bar; for 1D, counts missing
    calendar days between first and last bar (weekends/holidays included, since we
    can't tell those apart from real gaps without a calendar -- purely informational)."""
    if len(df) < 2:
        return 0
    if tf == "1D":
        span_days = int((df.index[-1].normalize() - df.index[0].normalize()).days)
        return max(0, span_days - (len(df) - 1))
    dur = tf_duration(tf)
    expected_slots = int((df.index[-1] - df.index[0]) / dur)
    return max(0, expected_slots - (len(df) - 1))


@dataclass(frozen=True)
class CsvImportResult:
    dataset_id: str
    kind: str
    source_path: str
    file_sha256: str
    symbol: str
    native_tf: str
    start_ts: str
    end_ts: str
    bar_count: int
    gap_count: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CsvImportResult:
        return cls(
            dataset_id=row["id"],
            kind=row["kind"],
            source_path=row["source_path"],
            file_sha256=row["file_sha256"],
            symbol=row["symbol"],
            native_tf=row["native_tf"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            bar_count=row["bar_count"],
            gap_count=row["gap_count"],
        )


def import_csv_dataset(
    conn: sqlite3.Connection,
    path: Path,
    symbol: str,
    native_tf: str,
    rollover_tz: str = "America/New_York",
    rollover_time: str = "17:00",
) -> CsvImportResult:
    """Idempotent by file content: importing the same bytes twice returns the same
    dataset id without re-registering (plan requirement)."""
    file_sha = sha256_file(path)
    existing = repo.find_dataset_by_sha256(conn, file_sha)
    if existing is not None:
        return CsvImportResult.from_row(existing)

    frames = load_csv(path, native_tf, rollover_tz, rollover_time)  # raises FeedError
    base = frames[native_tf]
    gaps = count_grid_gaps(base, native_tf)
    did = hashlib.sha256(f"{file_sha}:{symbol}:{native_tf}".encode()).hexdigest()[:16]
    start_ts = base.index[0].isoformat()
    end_ts = base.index[-1].isoformat()
    bar_count = len(base)
    repo.register_csv_dataset(
        conn, did, str(path), file_sha, symbol, native_tf, start_ts, end_ts, bar_count, gaps
    )
    return CsvImportResult(
        dataset_id=did,
        kind="csv",
        source_path=str(path),
        file_sha256=file_sha,
        symbol=symbol,
        native_tf=native_tf,
        start_ts=start_ts,
        end_ts=end_ts,
        bar_count=bar_count,
        gap_count=gaps,
    )


@dataclass(frozen=True)
class DatasetBundle:
    price: dict[str, pd.DataFrame]
    dxy: dict[str, pd.DataFrame] | None


def load_bundle_for_dataset(
    conn: sqlite3.Connection, dataset_id: str, config: BotConfig
) -> DatasetBundle:
    """Regardless of whether `dataset_id` is a synthetic or a CSV dataset (plan 02
    unification point for CLI/API)."""
    row = repo.get_dataset(conn, dataset_id)
    if row is None:
        raise KeyError(dataset_id)

    kind = row["kind"] if "kind" in row.keys() else "synthetic"
    if kind == "synthetic":
        spec = DatasetSpec(**json.loads(row["spec_json"]))
        bundle = generate_bundle(spec)
        return DatasetBundle(price=bundle["price"], dxy=bundle["dxy"])

    price = load_csv(
        Path(row["source_path"]),
        row["native_tf"],
        config.trading_day_rollover_tz,
        config.trading_day_rollover_time,
    )
    dxy: dict[str, pd.DataFrame] | None = None
    dxy_dataset_id = config.filters.dxy.dataset_id
    if dxy_dataset_id:
        dxy_row = repo.get_dataset(conn, dxy_dataset_id)
        if dxy_row is None:
            raise KeyError(dxy_dataset_id)
        dxy = load_csv(
            Path(dxy_row["source_path"]),
            dxy_row["native_tf"],
            config.trading_day_rollover_tz,
            config.trading_day_rollover_time,
        )
    return DatasetBundle(price=price, dxy=dxy)
