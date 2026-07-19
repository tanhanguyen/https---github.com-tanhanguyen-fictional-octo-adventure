"""Fixture-driven tests for bot/analytics/metrics.py. Ground truth = hand-derived
fixture tests/fixtures/analytics/run_report_hand.json (see its `derivation` field)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bot.analytics.metrics import (
    TradeStats,
    compute_run_report,
    compute_series_stats,
    compute_trade_stats,
    diff_histograms,
    diff_reports,
    r_multiple_histogram,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "analytics" / "run_report_hand.json"
)


@pytest.fixture(scope="module")
def fx() -> dict[str, Any]:
    with open(FIXTURE, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _assert_trade_stats(stats: TradeStats, expected: dict[str, Any]) -> None:
    for key, exp in expected.items():
        if key == "r_histogram_nonzero":
            got = {b.label: b.count for b in stats.r_histogram if b.count > 0}
            assert got == exp
        elif isinstance(exp, float):
            assert getattr(stats, key) == pytest.approx(exp, rel=1e-9), key
        else:
            assert getattr(stats, key) == exp, key


def test_run_report_matches_hand_fixture(fx: dict[str, Any]) -> None:
    report = compute_run_report(
        fx["trades"],
        fx["equity"],
        fx["starting_equity"],
        fx["timeframe"],
        reason_histogram={"wait": 3, "done": 6},
        filter_block_counts={"session": 2},
    )
    _assert_trade_stats(report.overall, fx["expected"]["overall"])
    assert set(report.per_strategy) == set(fx["expected"]["per_strategy"])
    for strat, exp in fx["expected"]["per_strategy"].items():
        _assert_trade_stats(report.per_strategy[strat], exp)
    series_exp = fx["expected"]["series"]
    for key, exp in series_exp.items():
        if isinstance(exp, float):
            assert getattr(report.series, key) == pytest.approx(exp, rel=1e-9), key
        else:
            assert getattr(report.series, key) == exp, key
    assert report.reason_histogram == {"wait": 3, "done": 6}
    assert report.filter_block_counts == {"session": 2}


def test_empty_inputs_give_none_not_crash() -> None:
    stats = compute_trade_stats([])
    assert stats.n_total == 0
    assert stats.win_rate is None
    assert stats.profit_factor is None
    assert stats.expectancy_r is None
    assert stats.avg_holding_hours is None

    series = compute_series_stats([], 10000.0, "1H")
    assert series.final_equity == 10000.0
    assert series.total_return_pct == 0.0
    assert series.max_drawdown_abs == 0.0
    assert series.longest_drawdown_bars == 0
    assert series.sharpe is None


def test_profit_factor_none_when_no_losses() -> None:
    trades = [
        {"strategy": "BREAKOUT", "direction": "BUY", "result": "WIN", "pnl_amount": 10.0,
         "pnl_r": 1.0, "opened_at_utc": None, "closed_at_utc": None},
    ]
    stats = compute_trade_stats(trades)
    assert stats.profit_factor is None
    assert stats.win_rate == 1.0
    assert stats.avg_holding_hours is None


def test_flat_equity_has_no_sharpe() -> None:
    series = compute_series_stats([10000.0, 10000.0, 10000.0], 10000.0, "1H")
    assert series.sharpe is None
    assert series.max_drawdown_abs == 0.0


def test_r_histogram_open_bins_and_edges() -> None:
    bins = {b.label: b.count for b in r_multiple_histogram([-5.0, -2.0, 2.99, 3.0, 10.0])}
    assert bins["<-2"] == 1
    assert bins["[-2,-1.5)"] == 1  # lo edge inclusive
    assert bins["[2.5,3)"] == 1
    assert bins[">=3"] == 2


def test_diff_reports_and_histograms(fx: dict[str, Any]) -> None:
    report_a = compute_run_report(
        fx["trades"], fx["equity"], fx["starting_equity"], fx["timeframe"], {"done": 6}, {}
    )
    report_b = compute_run_report(
        fx["trades"][:2], fx["equity"][:3], fx["starting_equity"], fx["timeframe"],
        {"done": 2, "wait": 1}, {},
    )
    diff = diff_reports(report_a, report_b)
    assert diff["n_total"] == {"a": 6.0, "b": 2.0, "delta": -4.0}
    # b has 1 WIN + 1 LOSS -> win_rate 0.5 on both sides
    assert diff["win_rate"]["delta"] == pytest.approx(0.0)
    assert diff["final_equity"] == {"a": 10250.0, "b": 9950.0, "delta": -300.0}

    hist = diff_histograms({"done": 6}, {"done": 2, "wait": 1})
    assert hist == {
        "done": {"a": 6, "b": 2, "delta": -4},
        "wait": {"a": 0, "b": 1, "delta": 1},
    }
