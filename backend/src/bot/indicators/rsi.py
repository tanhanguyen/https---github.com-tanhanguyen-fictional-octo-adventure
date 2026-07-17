"""Relative Strength Index, Wilder-smoothed (C8)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.indicators._smoothing import seeded_ewm


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = seeded_ewm(gain, period, 1.0 / period)
    avg_loss = seeded_ewm(loss, period, 1.0 / period)

    rs = avg_gain / avg_loss
    result = 100.0 - 100.0 / (1.0 + rs)
    # avg_loss == 0 and avg_gain == 0 -> flat market, conventionally 50
    result = result.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    # avg_loss == 0 and avg_gain > 0 -> RS -> inf -> RSI 100
    result = result.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    result = result.where(~(avg_gain.isna() | avg_loss.isna()), np.nan)
    return result
