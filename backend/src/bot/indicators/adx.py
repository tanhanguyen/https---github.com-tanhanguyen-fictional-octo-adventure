"""Average Directional Index, Wilder-smoothed throughout (C8)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.indicators._smoothing import seeded_ewm
from bot.indicators.atr import true_range


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )
    # diff() leaves index 0 NaN; DM at index 0 is undefined (no prior bar).
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan

    tr = true_range(high, low, close)
    alpha = 1.0 / period

    atr_w = seeded_ewm(tr, period, alpha)
    plus_dm_w = seeded_ewm(plus_dm, period, alpha)
    minus_dm_w = seeded_ewm(minus_dm, period, alpha)

    plus_di = 100.0 * plus_dm_w / atr_w
    minus_di = 100.0 * minus_dm_w / atr_w

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    dx = dx.where(di_sum != 0, 0.0)
    dx = dx.where(~(plus_di.isna() | minus_di.isna()), np.nan)

    return seeded_ewm(dx, period, alpha)
