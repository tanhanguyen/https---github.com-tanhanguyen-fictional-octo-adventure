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

    is_vn = ctx.config.symbol_type.startswith("STOCK_VN")

    # Plan 05: on stock VN the whole trading session (09:00-14:30 ICT) fits inside a
    # single 1D/1W bar, and decisions are taken at that bar's CLOSE -- i.e. at 00:00
    # ICT, structurally outside every session window. Comparing that instant against
    # intraday windows would block literally every bar. A bar that spans the session
    # IS the session, so the gate passes; the windows still apply on intraday VN
    # timeframes (4H via a per-symbol override). Deliberately scoped to VN so no
    # forex/crypto behavior (or golden stream) changes.
    if is_vn and ctx.config.timeframe in ("1D", "1W"):
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=True,
            blocking=False,
            values={
                "now_utc": ctx.now.isoformat(),
                "symbol_type": ctx.config.symbol_type,
                "timeframe": ctx.config.timeframe,
                "bar_spans_session": True,
            },
            detail=f"{ctx.config.timeframe} bar spans the whole VN session",
        )

    windows = cfg.stock_vn if is_vn else cfg.forex_crypto
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
