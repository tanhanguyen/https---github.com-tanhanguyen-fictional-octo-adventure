"""Filter 11 — Equity curve (MODIFIER). §6.2: streak-based risk_multiplier."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result

FILTER_ID = "equity_curve"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.equity_curve
    if not cfg.enabled:
        result = disabled_result(FILTER_ID, FilterKind.MODIFIER)
        result.values = {"risk_multiplier": 1.0}
        return result

    if ctx.consecutive_wins >= cfg.win_streak_trigger:
        risk_multiplier = cfg.win_reduce_to
    elif ctx.consecutive_losses >= cfg.loss_streak_trigger:
        risk_multiplier = cfg.loss_reduce_to
    else:
        risk_multiplier = 1.0

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.MODIFIER,
        enabled=True,
        evaluated=True,
        passed=None,
        blocking=False,
        values={
            "risk_multiplier": risk_multiplier,
            "consecutive_wins": ctx.consecutive_wins,
            "consecutive_losses": ctx.consecutive_losses,
        },
        detail=f"risk_multiplier={risk_multiplier}",
    )
