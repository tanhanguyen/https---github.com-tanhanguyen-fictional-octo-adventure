"""Z-score of a series over a rolling window (C9): sample stdev (ddof=1), window
includes the current value."""

from __future__ import annotations

import pandas as pd


def zscore(series: pd.Series, window: int = 100) -> pd.Series:
    roll_mean = series.rolling(window=window, min_periods=window).mean()
    roll_std = series.rolling(window=window, min_periods=window).std(ddof=1)
    return (series - roll_mean) / roll_std
