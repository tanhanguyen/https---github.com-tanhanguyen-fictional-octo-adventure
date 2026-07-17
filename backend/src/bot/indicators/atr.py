"""Average True Range, Wilder-smoothed (C8)."""
from __future__ import annotations

import pandas as pd

from bot.indicators._smoothing import seeded_ewm


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    a = high - low
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    tr = pd.concat([a, b, c], axis=1).max(axis=1)
    # first bar has no previous close: TR = high-low
    tr.iloc[0] = a.iloc[0]
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr = true_range(high, low, close)
    alpha = 1.0 / period
    return seeded_ewm(tr, period, alpha)
