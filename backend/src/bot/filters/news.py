"""Filter 16 — News blackout (GATE, off by default). Plan 06: real imported events
(bot.data.news, snapshotted per-run in ctx.news_events) replace the old hand-typed
blacklist_utc ranges. No event data / no matching currency -> never blocks."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result

FILTER_ID = "news"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.news
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    currencies = set(ctx.instrument_currencies)
    event = None
    if ctx.news_events is not None:
        event = ctx.news_events.blocking_event(
            ctx.now, cfg.window_before_min, cfg.window_after_min, currencies, cfg.min_impact
        )
    blocked = event is not None
    detail = (
        f"news blackout: {event.currency} {event.impact} '{event.title}' @ "
        f"{event.ts_utc.isoformat()}"
        if event is not None
        else "ok"
    )
    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=not blocked,
        blocking=blocked,
        values={
            "event_count": len(ctx.news_events.events) if ctx.news_events is not None else 0,
            "currencies": sorted(currencies),
        },
        detail=detail,
    )
