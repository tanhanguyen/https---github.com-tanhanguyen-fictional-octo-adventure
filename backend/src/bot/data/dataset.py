"""Dataset spec + content-addressed id + CSV cache under data/generated/<dataset_id>/."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from bot.data.resample import build_all_timeframes
from bot.data.synthetic import generate_dxy_series, generate_price_series


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
