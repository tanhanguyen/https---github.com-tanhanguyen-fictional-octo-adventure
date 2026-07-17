"""Pure candle geometry helpers used by strategies/filters (e.g. wick ratio, D4)."""

from __future__ import annotations

import pandas as pd


def candle_range(high: pd.Series, low: pd.Series) -> pd.Series:
    return high - low


def upper_wick(open_: pd.Series, high: pd.Series, close: pd.Series) -> pd.Series:
    return high - pd.concat([open_, close], axis=1).max(axis=1)


def lower_wick(open_: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return pd.concat([open_, close], axis=1).min(axis=1) - low


def is_bullish(open_: pd.Series, close: pd.Series) -> pd.Series:
    return close > open_


def wick_ratio(open_: float, high: float, low: float, close: float, side: str) -> float:
    """Ratio of the wick opposite to `side` ("BUY"/"SELL") over the candle range (D4).

    BUY (looking for rejection of the downside) -> lower wick / range.
    SELL (looking for rejection of the upside)  -> upper wick / range.
    High == Low -> ratio 0 (per docs/decisions.md D4).
    """
    rng = high - low
    if rng <= 0:
        return 0.0
    body_top = max(open_, close)
    body_bottom = min(open_, close)
    if side == "BUY":
        wick = body_bottom - low
    else:
        wick = high - body_top
    return wick / rng
