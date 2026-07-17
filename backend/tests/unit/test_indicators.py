"""Fixture-driven indicator tests. Ground truth = hand-derived fixtures under
tests/fixtures/indicators/*.json (see docs/decisions.md for the derivations).
Not cross-checked against ta-lib/pandas-ta by design (plan constraint)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from bot.indicators.adx import adx
from bot.indicators.atr import atr
from bot.indicators.candle import wick_ratio
from bot.indicators.efficiency_ratio import efficiency_ratio
from bot.indicators.ema import ema
from bot.indicators.rsi import rsi
from bot.indicators.zscore import zscore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "indicators"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _assert_series_matches(actual: pd.Series, expected: list[float | None]) -> None:
    assert len(actual) == len(expected)
    for i, exp in enumerate(expected):
        got = actual.iloc[i]
        if exp is None:
            assert math.isnan(got), f"index {i}: expected NaN, got {got}"
        else:
            assert got == pytest.approx(exp, rel=1e-9), f"index {i}: expected {exp}, got {got}"


def test_ema_period3_basic():
    fx = _load("ema_period3_basic.json")
    close = pd.Series(fx["input"]["close"], dtype=float)
    result = ema(close, fx["period"])
    _assert_series_matches(result, fx["expected"])


def test_atr_wilder_period3():
    fx = _load("atr_wilder_period3.json")
    high = pd.Series(fx["input"]["high"], dtype=float)
    low = pd.Series(fx["input"]["low"], dtype=float)
    close = pd.Series(fx["input"]["close"], dtype=float)
    result = atr(high, low, close, fx["period"])
    _assert_series_matches(result, fx["expected"])


def test_rsi_wilder_period14():
    fx = _load("rsi_wilder_period14.json")
    close = pd.Series(fx["input"]["close"], dtype=float)
    result = rsi(close, fx["period"])
    _assert_series_matches(result, fx["expected"])


def test_er_period10():
    fx = _load("er_period10.json")
    close = pd.Series(fx["input"]["close"], dtype=float)
    result = efficiency_ratio(close, fx["period"])
    _assert_series_matches(result, fx["expected"])


def test_zscore_window5_ddof1():
    fx = _load("zscore_window5_ddof1.json")
    series = pd.Series(fx["input"]["series"], dtype=float)
    result = zscore(series, fx["window"])
    _assert_series_matches(result, fx["expected"])


def test_adx_period14_warmup_and_spot_check():
    fx = _load("adx_period14.json")
    high = pd.Series(fx["input"]["high"], dtype=float)
    low = pd.Series(fx["input"]["low"], dtype=float)
    close = pd.Series(fx["input"]["close"], dtype=float)
    result = adx(high, low, close, fx["period"])

    nan_through = fx["expected_nan_through_index"]
    for i in range(nan_through + 1):
        assert math.isnan(result.iloc[i]), f"index {i} expected NaN warmup"

    for idx_str, expected_val in fx["spot_check"].items():
        idx = int(idx_str)
        assert result.iloc[idx] == pytest.approx(expected_val, rel=1e-9)


@pytest.mark.parametrize("case_idx", range(5))
def test_wick_ratio_cases(case_idx):
    fx = _load("wick_ratio_cases.json")
    case = fx["cases"][case_idx]
    got = wick_ratio(case["open"], case["high"], case["low"], case["close"], case["side"])
    assert got == pytest.approx(case["expected"], rel=1e-9), case["name"]


def test_ema_never_zero_during_warmup():
    close = pd.Series([1.0, 2.0])
    result = ema(close, period=5)
    assert result.isna().all()


def test_sma_seed_consistency_for_ema_and_wilder():
    # C8: both smoothing families seed with SMA of the first full window.
    from bot.indicators.sma import sma

    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    s = sma(close, 3)
    e = ema(close, 3)
    assert e.iloc[2] == pytest.approx(s.iloc[2])
