"""Filter 7 — Session (GATE, D9). tz-aware windows per SYMBOL_TYPE, auto DST."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from bot.config.models import SessionWindow
from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result

FILTER_ID = "session"


def _in_window(now_utc: datetime, window: SessionWindow) -> bool:
    tz = ZoneInfo(window.tz)
    local = now_utc.astimezone(tz)
    hh1, mm1 = (int(p) for p in window.start.split(":"))
    hh2, mm2 = (int(p) for p in window.end.split(":"))
    return time(hh1, mm1) <= local.time() < time(hh2, mm2)


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.session
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    windows = cfg.stock_vn if ctx.config.symbol_type.startswith("STOCK_VN") else cfg.forex_crypto
    ok = any(_in_window(ctx.now, w) for w in windows)

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=ok,
        blocking=not ok,
        values={"now_utc": ctx.now.isoformat(), "symbol_type": ctx.config.symbol_type},
        detail="in session" if ok else "outside session",
    )
