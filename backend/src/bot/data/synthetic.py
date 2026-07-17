"""Synthetic mock data generator. One base 15m frame, resampled upward (plan's mock
data feed section): MTF consistency becomes structural rather than something to test.

Segments cycle through TREND/RANGE/VOL_SPIKE/QUIET regimes so every branch of the bot
is reachable. DXY is a correlated (rho=-0.85) companion series. Named child RNG streams
(price/dxy/volume) via Generator.spawn() so future features don't shift existing streams.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

SUB_STEPS = 15  # each 15m candle built from 15 sub-steps -> realistic wick distribution

_SEGMENT_CYCLE = ["TREND_UP", "RANGE", "VOL_SPIKE", "TREND_DOWN", "QUIET", "RANGE"]
_SEGMENT_LEN_15M = 400  # bars per segment (100 hours) -- long enough for regime detection


@dataclass(frozen=True)
class RegimeParams:
    drift: float  # per sub-step drift, as a fraction of price
    vol: float  # per sub-step stdev, as a fraction of price
    mean_revert: float  # 0 = pure random walk, >0 pulls toward segment anchor


_REGIME_PARAMS: dict[str, RegimeParams] = {
    "TREND_UP": RegimeParams(drift=0.000012, vol=0.00006, mean_revert=0.0),
    "TREND_DOWN": RegimeParams(drift=-0.000012, vol=0.00006, mean_revert=0.0),
    "RANGE": RegimeParams(drift=0.0, vol=0.00004, mean_revert=0.02),
    "VOL_SPIKE": RegimeParams(drift=0.0, vol=0.00035, mean_revert=0.0),
    "QUIET": RegimeParams(drift=0.0, vol=0.000006, mean_revert=0.01),
}


def _build_sub_step_path(
    n_candles: int, start_price: float, rng: np.random.Generator
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], list[str]]:
    """Returns an array of shape (n_candles, SUB_STEPS+1) of sub-step prices (the last
    column of candle i equals the first column of candle i+1), plus the regime label
    per candle."""
    total_sub = n_candles * SUB_STEPS
    prices = np.empty(total_sub + 1, dtype=float)
    prices[0] = start_price
    labels = []

    idx = 0
    anchor = start_price
    seg_i = 0
    seg_remaining = _SEGMENT_LEN_15M
    regime = _SEGMENT_CYCLE[0]

    for _c in range(n_candles):
        if seg_remaining <= 0:
            seg_i = (seg_i + 1) % len(_SEGMENT_CYCLE)
            regime = _SEGMENT_CYCLE[seg_i]
            seg_remaining = _SEGMENT_LEN_15M
            anchor = prices[idx]
        seg_remaining -= 1
        labels.append(regime)
        params = _REGIME_PARAMS[regime]
        for _ in range(SUB_STEPS):
            shock = rng.normal(loc=params.drift, scale=params.vol)
            revert = params.mean_revert * (anchor - prices[idx]) / max(anchor, 1e-9)
            prices[idx + 1] = prices[idx] * (1.0 + shock + revert)
            idx += 1

    return prices, labels


def _candles_from_path(
    prices: np.ndarray[Any, np.dtype[np.float64]],
    n_candles: int,
    start_ts: datetime,
    freq_minutes: int,
) -> pd.DataFrame:
    rows = []
    for c in range(n_candles):
        sub = prices[c * SUB_STEPS : (c + 1) * SUB_STEPS + 1]
        o = sub[0]
        cl = sub[-1]
        hi = sub.max()
        lo = sub.min()
        ts = start_ts + timedelta(minutes=freq_minutes * c)
        rows.append({"open_ts": ts, "open": o, "high": hi, "low": lo, "close": cl})
    df = pd.DataFrame(rows).set_index("open_ts")
    df.index.name = "open_ts"
    return df


def generate_price_series(
    seed: int, n_candles: int, start_price: float = 1.1000, start_ts: datetime | None = None
) -> tuple[pd.DataFrame, list[str]]:
    if start_ts is None:
        start_ts = datetime(2023, 1, 2, 0, 0, tzinfo=timezone.utc)
    rng = np.random.default_rng(seed)
    price_rng, _dxy_rng, volume_rng = rng.spawn(3)

    prices, labels = _build_sub_step_path(n_candles, start_price, price_rng)
    df = _candles_from_path(prices, n_candles, start_ts, freq_minutes=15)
    volume = volume_rng.uniform(500, 1500, size=n_candles)
    df["volume"] = volume
    return df, labels


def generate_dxy_series(
    seed: int, price_df: pd.DataFrame, rho: float = -0.85, start_value: float = 100.0
) -> pd.DataFrame:
    """DXY 15m series correlated to the price series' returns at rho=-0.85, built from
    the same seed's dedicated child stream so it never shifts the price stream."""
    rng = np.random.default_rng(seed)
    _price_rng, dxy_rng, _volume_rng = rng.spawn(3)

    price_close = price_df["close"].to_numpy()
    price_returns = np.diff(np.log(price_close))
    price_returns = np.concatenate([[0.0], price_returns])
    std = price_returns.std() if price_returns.std() > 0 else 1e-9
    normalized = price_returns / std

    independent = dxy_rng.normal(size=len(price_returns))
    dxy_returns = rho * normalized * 0.0004 + np.sqrt(max(1 - rho**2, 0.0)) * independent * 0.0004

    dxy_close = start_value * np.exp(np.cumsum(dxy_returns))
    dxy_open = np.concatenate([[start_value], dxy_close[:-1]])
    noise = dxy_rng.uniform(0.00005, 0.0002, size=len(dxy_close))
    dxy_high = np.maximum(dxy_open, dxy_close) + noise
    dxy_low = np.minimum(dxy_open, dxy_close) - noise

    out = pd.DataFrame(
        {
            "open_ts": price_df.index,
            "open": dxy_open,
            "high": dxy_high,
            "low": dxy_low,
            "close": dxy_close,
            "volume": np.zeros(len(dxy_close)),
        }
    ).set_index("open_ts")
    out.index.name = "open_ts"
    return out
