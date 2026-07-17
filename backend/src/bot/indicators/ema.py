"""EMA34/89 style exponential moving average (C8): alpha=2/(period+1), seeded with SMA."""

from __future__ import annotations

import pandas as pd

from bot.indicators._smoothing import seeded_ewm


def ema(series: pd.Series, period: int) -> pd.Series:
    alpha = 2.0 / (period + 1)
    return seeded_ewm(series, period, alpha)
