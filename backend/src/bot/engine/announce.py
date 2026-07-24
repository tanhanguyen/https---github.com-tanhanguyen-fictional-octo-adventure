"""Turning one `StepSummary` into trade-lifecycle alerts (plan 13).

Both runners produce the same events for the same reasons — the live runner from a
real-time bar, the API's replay runner from a stepped one — so the mapping lives here
once instead of drifting between them.

This module observes; it never decides. It also imports `bot.notify` (the formatter)
and never `bot.alerts` (the bus), which is what keeps `bot/engine` on the right side of
invariant #6 — see `test_dependency_direction`.
"""

from __future__ import annotations

from bot.engine.context import SymbolContext
from bot.engine.runner import StepSummary
from bot.notify import LiveAlerts


def announce_trade_events(alerts: LiveAlerts, summary: StepSummary, sc: SymbolContext) -> None:
    """Emit the trade-lifecycle alerts implied by one symbol's tick.

    `sc` is that symbol's context AFTER the tick, which is where the live trade's prices
    and lot live (a `StepSummary` carries the outcome, not the position)."""
    trade = sc.trade
    if "FILLED" in summary.trade_event_types:
        alerts.trade_opened(
            summary.symbol,
            trade.direction.value if trade else "?",
            trade.strategy.value if trade else "?",
            summary.equity,
            entry=trade.entry_price if trade else None,
            sl=trade.sl if trade else None,
            tp1=trade.tp1_price if trade else None,
            lot=trade.lot_size if trade else None,
            risk_pct=trade.risk_pct_effective if trade else None,
        )
    if "TP1_HIT" in summary.trade_event_types:
        alerts.tp1_hit(summary.symbol, summary.equity)
    if "CANCELLED" in summary.trade_event_types:
        alerts.trade_cancelled(summary.symbol, summary.stage or "pending order cancelled")
    elif summary.opened_trade_db_id is not None and "FILLED" not in summary.trade_event_types:
        # A PENDING row was created on this tick and has not filled yet. Noisy by
        # nature, which is why `trade_pending` is muted for Telegram by default — it is
        # still logged and still toasts on the web UI.
        alerts.trade_pending(
            summary.symbol,
            trade.direction.value if trade else "?",
            trade.strategy.value if trade else "?",
            trade.sl if trade else None,
        )
    if summary.closed_result is not None:
        alerts.trade_closed(
            summary.symbol,
            summary.closed_result,
            summary.closed_pnl_r or 0.0,
            summary.closed_pnl_amount or 0.0,
            summary.equity,
        )
