"""Filter 16 — News blackout (GATE, off by default). Empty blacklist -> never blocks."""
from __future__ import annotations

from datetime import datetime

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result

FILTER_ID = "news"


def _in_blackout(now: datetime, blacklist_utc: list[str]) -> bool:
    for entry in blacklist_utc:
        start_s, _, end_s = entry.partition("/")
        start = datetime.fromisoformat(start_s)
        end = datetime.fromisoformat(end_s)
        if start <= now <= end:
            return True
    return False


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.news
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    blocked = _in_blackout(ctx.now, cfg.blacklist_utc)
    return FilterResult(
        id=FILTER_ID, kind=FilterKind.GATE, enabled=True, evaluated=True, passed=not blocked,
        blocking=blocked,
        values={"blacklist_count": len(cfg.blacklist_utc)},
        detail="news blackout" if blocked else "ok",
    )
