"""Backtest metrics (plan 03). Pure functions, no I/O — inputs are plain lists so every
number can be unit-tested against a hand-derived fixture (tests/fixtures/analytics/).

Conventions (pinned by the fixtures):
- win_rate = WIN / (WIN + LOSS + BREAKEVEN). D8: BREAKEVEN counts as a loss.
- profit_factor = gross win / gross loss (absolute); None when there is no losing trade.
- expectancy_r = mean pnl_r over closed trades that have a pnl_r (R = pnl / risk-at-entry,
  already computed by the order engine).
- avg_loss / max_loss are signed (negative) pnl amounts; max_loss is the most negative.
- Sharpe is for RELATIVE comparison between runs only:
      sharpe = mean(returns) / std(returns, ddof=1) * sqrt(bars_per_year)
      returns[i] = equity[i] / equity[i-1] - 1, with equity[-1] := starting_equity
      bars_per_year = 365 * 24 * 3600 / tf_duration(timeframe).total_seconds()
  No trading-calendar adjustment on purpose — do not read it as an absolute number.
- Drawdown runs against a peak initialised at starting_equity; a bar is "in drawdown"
  while equity < running peak, and longest_drawdown_bars is the longest such streak.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bot.core.timeframes import tf_duration

# R-multiple histogram: fixed bins so two runs are always comparable — open bin below
# -2R, 0.5R-wide bins on [-2, 3), open bin at 3R and above.
_R_BIN_LO = -2.0
_R_BIN_HI = 3.0
_R_BIN_WIDTH = 0.5


@dataclass(frozen=True)
class HistogramBin:
    label: str
    lo: float | None  # None = open below
    hi: float | None  # None = open above
    count: int


@dataclass(frozen=True)
class TradeStats:
    n_total: int
    n_by_strategy: dict[str, int]
    n_by_direction: dict[str, int]
    n_win: int
    n_loss: int
    n_breakeven: int
    win_rate: float | None
    profit_factor: float | None
    expectancy_r: float | None
    avg_win: float | None
    max_win: float | None
    avg_loss: float | None
    max_loss: float | None
    avg_holding_hours: float | None
    r_histogram: list[HistogramBin] = field(default_factory=list)


@dataclass(frozen=True)
class SeriesStats:
    final_equity: float
    total_return_pct: float
    max_drawdown_abs: float
    max_drawdown_pct: float
    longest_drawdown_bars: int
    sharpe: float | None
    n_bars: int


@dataclass(frozen=True)
class RunReport:
    overall: TradeStats
    per_strategy: dict[str, TradeStats]
    series: SeriesStats
    reason_histogram: dict[str, int]
    filter_block_counts: dict[str, int]


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _holding_hours(trade: Mapping[str, Any]) -> float | None:
    opened, closed = trade.get("opened_at_utc"), trade.get("closed_at_utc")
    if not opened or not closed:
        return None
    dt = datetime.fromisoformat(closed) - datetime.fromisoformat(opened)
    return dt.total_seconds() / 3600.0


def r_multiple_histogram(rs: Sequence[float]) -> list[HistogramBin]:
    bins: list[HistogramBin] = []
    counts: Counter[int] = Counter()
    n_inner = round((_R_BIN_HI - _R_BIN_LO) / _R_BIN_WIDTH)
    for r in rs:
        if r < _R_BIN_LO:
            counts[-1] += 1
        elif r >= _R_BIN_HI:
            counts[n_inner] += 1
        else:
            counts[int((r - _R_BIN_LO) // _R_BIN_WIDTH)] += 1
    bins.append(HistogramBin(label=f"<{_R_BIN_LO:g}", lo=None, hi=_R_BIN_LO, count=counts[-1]))
    for i in range(n_inner):
        lo = _R_BIN_LO + i * _R_BIN_WIDTH
        hi = lo + _R_BIN_WIDTH
        bins.append(HistogramBin(label=f"[{lo:g},{hi:g})", lo=lo, hi=hi, count=counts[i]))
    bins.append(
        HistogramBin(label=f">={_R_BIN_HI:g}", lo=_R_BIN_HI, hi=None, count=counts[n_inner])
    )
    return bins


def compute_trade_stats(closed_trades: Sequence[Mapping[str, Any]]) -> TradeStats:
    """`closed_trades`: rows/dicts of CLOSED trades with a `result` (WIN|LOSS|BREAKEVEN)."""
    by_strategy: Counter[str] = Counter()
    by_direction: Counter[str] = Counter()
    results: Counter[str] = Counter()
    wins: list[float] = []
    losses: list[float] = []
    rs: list[float] = []
    holds: list[float] = []

    for t in closed_trades:
        by_strategy[str(t["strategy"])] += 1
        by_direction[str(t["direction"])] += 1
        results[str(t["result"])] += 1
        pnl = t.get("pnl_amount")
        if pnl is not None:
            if pnl > 0:
                wins.append(float(pnl))
            elif pnl < 0:
                losses.append(float(pnl))
        r = t.get("pnl_r")
        if r is not None:
            rs.append(float(r))
        hold = _holding_hours(t)
        if hold is not None:
            holds.append(hold)

    n_win, n_loss, n_be = results["WIN"], results["LOSS"], results["BREAKEVEN"]
    n_resulted = n_win + n_loss + n_be
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    return TradeStats(
        n_total=len(closed_trades),
        n_by_strategy=dict(by_strategy),
        n_by_direction=dict(by_direction),
        n_win=n_win,
        n_loss=n_loss,
        n_breakeven=n_be,
        win_rate=n_win / n_resulted if n_resulted else None,
        profit_factor=gross_win / gross_loss if gross_loss > 0 else None,
        expectancy_r=_mean(rs),
        avg_win=_mean(wins),
        max_win=max(wins) if wins else None,
        avg_loss=_mean(losses),
        max_loss=min(losses) if losses else None,
        avg_holding_hours=_mean(holds),
        r_histogram=r_multiple_histogram(rs),
    )


def compute_series_stats(
    equity: Sequence[float], starting_equity: float, timeframe: str
) -> SeriesStats:
    """`equity`: one point per processed bar, in bar order (equity_point.equity)."""
    final = float(equity[-1]) if equity else starting_equity
    total_return_pct = (
        (final - starting_equity) / starting_equity * 100.0 if starting_equity else 0.0
    )

    peak = starting_equity
    dd_abs = 0.0
    dd_pct = 0.0
    longest = 0
    current = 0
    for eq in equity:
        if eq >= peak:
            peak = eq
            current = 0
        else:
            current += 1
            longest = max(longest, current)
            dd_abs = max(dd_abs, peak - eq)
            if peak > 0:
                dd_pct = max(dd_pct, (peak - eq) / peak * 100.0)

    sharpe: float | None = None
    prev = [starting_equity, *equity][:-1]
    returns = [e / p - 1.0 for e, p in zip(equity, prev, strict=True) if p != 0]
    if len(returns) >= 2:
        mu = sum(returns) / len(returns)
        var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
        if var > 0:
            bars_per_year = 365 * 24 * 3600 / tf_duration(timeframe).total_seconds()
            sharpe = mu / math.sqrt(var) * math.sqrt(bars_per_year)

    return SeriesStats(
        final_equity=final,
        total_return_pct=total_return_pct,
        max_drawdown_abs=dd_abs,
        max_drawdown_pct=dd_pct,
        longest_drawdown_bars=longest,
        sharpe=sharpe,
        n_bars=len(equity),
    )


def compute_run_report(
    closed_trades: Sequence[Mapping[str, Any]],
    equity: Sequence[float],
    starting_equity: float,
    timeframe: str,
    reason_histogram: Mapping[str, int],
    filter_block_counts: Mapping[str, int],
) -> RunReport:
    per_strategy = {
        strat: compute_trade_stats([t for t in closed_trades if t["strategy"] == strat])
        for strat in sorted({str(t["strategy"]) for t in closed_trades})
    }
    return RunReport(
        overall=compute_trade_stats(closed_trades),
        per_strategy=per_strategy,
        series=compute_series_stats(equity, starting_equity, timeframe),
        reason_histogram=dict(reason_histogram),
        filter_block_counts=dict(filter_block_counts),
    )


# ------------------------------------------------------------------ A/B diff (plan 03 §3)

#: The metrics a compare endpoint diffs, as (section, field) paths into RunReport.
KEY_METRICS: list[str] = [
    "n_total",
    "win_rate",
    "profit_factor",
    "expectancy_r",
    "final_equity",
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe",
]


def _metric_value(report: RunReport, name: str) -> float | None:
    for section in (report.overall, report.series):
        if hasattr(section, name):
            value = getattr(section, name)
            return None if value is None else float(value)
    raise KeyError(name)


def diff_reports(a: RunReport, b: RunReport) -> dict[str, dict[str, float | None]]:
    """{metric: {a, b, delta}} for KEY_METRICS. delta = b - a, None if either side is."""
    out: dict[str, dict[str, float | None]] = {}
    for name in KEY_METRICS:
        va, vb = _metric_value(a, name), _metric_value(b, name)
        delta = None if va is None or vb is None else vb - va
        out[name] = {"a": va, "b": vb, "delta": delta}
    return out


def diff_histograms(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, dict[str, int]]:
    """{reason: {a, b, delta}} over the union of keys, delta = b - a."""
    return {
        key: {"a": a.get(key, 0), "b": b.get(key, 0), "delta": b.get(key, 0) - a.get(key, 0)}
        for key in sorted(set(a) | set(b))
    }
