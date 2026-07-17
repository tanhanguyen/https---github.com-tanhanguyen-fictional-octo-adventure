"""Shared seeded-EMA smoothing (C8): seed = SMA of first full `period` window of
non-NaN values, then recurse with the given alpha. EMA34/89 use alpha=2/(period+1);
ATR/ADX/RSI (Wilder) use alpha=1/period. Warmup is NaN, never 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def seeded_ewm(series: pd.Series, period: int, alpha: float) -> pd.Series:
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    valid = ~np.isnan(values)

    seed_idx = -1
    run = 0
    for i in range(n):
        if valid[i]:
            run += 1
        else:
            run = 0
        if run >= period:
            seed_idx = i
            break

    if seed_idx == -1:
        return pd.Series(out, index=series.index, name=series.name)

    out[seed_idx] = values[seed_idx - period + 1 : seed_idx + 1].mean()
    for i in range(seed_idx + 1, n):
        prev = out[i - 1]
        x = values[i]
        out[i] = np.nan if (np.isnan(prev) or np.isnan(x)) else alpha * x + (1 - alpha) * prev

    return pd.Series(out, index=series.index, name=series.name)
