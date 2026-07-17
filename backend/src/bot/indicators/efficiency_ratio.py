"""Kaufman-style Efficiency Ratio (§6.3): |close[i]-close[i-period]| / sum(|close diffs|)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def efficiency_ratio(close: pd.Series, period: int = 10) -> pd.Series:
    movement = (close - close.shift(period)).abs()
    noise = close.diff().abs().rolling(window=period, min_periods=period).sum()
    er = movement / noise
    er = er.where(noise != 0, 0.0)  # spec: noise==0 -> 0 (flat price, not a warmup case)
    er = er.where(~movement.isna(), np.nan)  # true warmup: insufficient history
    return er
