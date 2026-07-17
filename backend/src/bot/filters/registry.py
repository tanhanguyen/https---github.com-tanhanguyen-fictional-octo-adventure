"""Filter registry: ordered list of all 16 filters, split into Phase A (unconditional)
and Phase B (need signal.direction) per the plan's decision-log section."""

from __future__ import annotations

from bot.core.types import FilterResult
from bot.filters import (
    account_risk,
    adx_filter,
    atr_ref,
    atr_zscore,
    confirmation_lag,
    dxy,
    equity_curve,
    er_filter,
    mtf,
    news,
    range_width,
    session,
    time_stop,
    trend,
    volume,
    wick,
)
from bot.filters.base import FilterContext

PHASE_A = [
    ("account_risk", account_risk.evaluate),
    ("session", session.evaluate),
    ("news", news.evaluate),
    ("atr_zscore", atr_zscore.evaluate),
    ("trend", trend.evaluate),
    ("adx_filter", adx_filter.evaluate),
    ("er_filter", er_filter.evaluate),
    ("atr_ref", atr_ref.evaluate),
    ("equity_curve", equity_curve.evaluate),
    ("range_width", range_width.evaluate),
    ("time_stop", time_stop.evaluate),
]

PHASE_B = [
    ("confirmation_lag", confirmation_lag.evaluate),
    ("wick", wick.evaluate),
    ("volume", volume.evaluate),
    ("mtf", mtf.evaluate),
    ("dxy", dxy.evaluate),
]

ALL_FILTER_IDS = [fid for fid, _ in PHASE_A] + [fid for fid, _ in PHASE_B]


def evaluate_all(ctx: FilterContext) -> dict[str, FilterResult]:
    """Evaluate-all, decide-after: run every filter regardless of short-circuiting."""
    results: dict[str, FilterResult] = {}
    for _fid, fn in PHASE_A:
        r = fn(ctx)
        results[r.id] = r
    for _fid, fn in PHASE_B:
        r = fn(ctx)
        results[r.id] = r
    return results
