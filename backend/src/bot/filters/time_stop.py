"""Filter 12 — Time stop (EXIT). C5: wall-clock based, evaluated by the order engine
on OPEN trades (bar.close_time - entry_bar_ts >= hours), disabled after TP1 when
after_tp1=false. This module exposes the config informationally for the decision log
and provides the pure predicate the order engine calls."""

from __future__ import annotations

from datetime import datetime, timedelta

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result

FILTER_ID = "time_stop"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.time_stop
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.EXIT)

    budget = f"{cfg.bars} bars" if cfg.bars is not None else f"{cfg.hours}h"
    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.EXIT,
        enabled=True,
        evaluated=True,
        passed=None,
        blocking=False,
        values={"hours": cfg.hours, "bars": cfg.bars, "after_tp1": cfg.after_tp1},
        detail=f"time_stop={budget} after_tp1={cfg.after_tp1}",
    )


def is_expired(
    entry_bar_ts: datetime, bar_close_time: datetime, hours: float, tp1_hit: bool, after_tp1: bool
) -> bool:
    """C5: pure wall-clock predicate used by order_engine.process_bar."""
    if tp1_hit and not after_tp1:
        return False
    return (bar_close_time - entry_bar_ts) >= timedelta(hours=hours)
