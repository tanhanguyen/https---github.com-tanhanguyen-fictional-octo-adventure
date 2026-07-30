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


def body_size(open_: float, close: float) -> float:
    return abs(close - open_)


def rejection_wick(open_: float, high: float, low: float, close: float, side: str) -> float:
    """Absolute size (not ratio) of the wick opposite `side` -- BUY: lower wick,
    SELL: upper wick. Used by pin-bar/long-wick checks that compare against body size."""
    body_top = max(open_, close)
    body_bottom = min(open_, close)
    return body_bottom - low if side == "BUY" else high - body_top


def is_pin_bar(
    open_: float,
    high: float,
    low: float,
    close: float,
    side: str,
    wick_body_mult: float = 2.0,
    body_max_position: float | None = None,
) -> bool:
    """BRB retest confirmation / scoring B1 (spec_v2 §5): rejection wick opposite `side`
    is at least `wick_body_mult` times the candle body (a zero body with any wick counts
    as a pin).

    `body_max_position` adds spec B1's "thân gần mép": the body must sit within that
    fraction of the range measured from the edge the wick rejects away from (BUY: the
    top; SELL: the bottom). Left None, only the wick/body ratio is tested -- which is
    what makes B3 ("bóng dài", 1.5x) a strictly weaker criterion than B1 rather than a
    duplicate of it."""
    body = body_size(open_, close)
    wick = rejection_wick(open_, high, low, close, side)
    if body <= 0:
        wick_ok = wick > 0
    else:
        wick_ok = wick > wick_body_mult * body
    if not wick_ok:
        return False
    if body_max_position is None:
        return True
    rng = high - low
    if rng <= 0:
        return False
    if side == "BUY":
        return (high - min(open_, close)) / rng <= body_max_position
    return (max(open_, close) - low) / rng <= body_max_position


def is_engulfing(
    prev_open: float, prev_close: float, open_: float, close: float, side: str
) -> bool:
    """BRB retest confirmation / scoring B2: this candle's body engulfs the previous
    candle's body, in the direction that rejects `side`'s broken level."""
    prev_top = max(prev_open, prev_close)
    prev_bottom = min(prev_open, prev_close)
    if side == "BUY":
        return close > open_ and open_ <= prev_bottom and close >= prev_top
    return close < open_ and open_ >= prev_top and close <= prev_bottom
