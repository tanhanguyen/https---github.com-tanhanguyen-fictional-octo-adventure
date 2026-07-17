"""Filter 14 — Account risk limit (GATE, Phase A). §6.7 + D10 + F3.

F3: the one-trade-per-symbol block itself must emit reason=max_concurrent_trades_reached,
stage=one_trade_per_symbol so that reason is reachable with a single symbol (Phase 1/2)."""

from __future__ import annotations

from bot.core.types import FilterKind, FilterResult
from bot.filters.base import FilterContext, disabled_result

FILTER_ID = "account_risk"


def evaluate(ctx: FilterContext) -> FilterResult:
    cfg = ctx.config.filters.account_risk
    if not cfg.enabled:
        return disabled_result(FILTER_ID, FilterKind.GATE)

    if cfg.daily_loss_limit_enabled and ctx.daily_loss_count >= cfg.daily_max_losses:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=False,
            blocking=True,
            values={
                "daily_loss_count": ctx.daily_loss_count,
                "daily_max_losses": cfg.daily_max_losses,
                "reason": "daily_loss_limit_reached",
                "stage": "account_risk",
            },
            detail="daily_loss_limit_reached",
        )

    if cfg.one_trade_per_symbol and ctx.open_trades_count >= 1:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=False,
            blocking=True,
            values={
                "open_trades_count": ctx.open_trades_count,
                "reason": "max_concurrent_trades_reached",
                "stage": "one_trade_per_symbol",
            },
            detail="one_trade_per_symbol blocking (open trade present)",
        )

    if ctx.open_trades_count >= cfg.max_concurrent_trades:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=False,
            blocking=True,
            values={
                "open_trades_count": ctx.open_trades_count,
                "max_concurrent_trades": cfg.max_concurrent_trades,
                "reason": "max_concurrent_trades_reached",
                "stage": "account_risk",
            },
            detail="max_concurrent_trades_reached",
        )

    return FilterResult(
        id=FILTER_ID,
        kind=FilterKind.GATE,
        enabled=True,
        evaluated=True,
        passed=True,
        blocking=False,
        values={
            "open_trades_count": ctx.open_trades_count,
            "daily_loss_count": ctx.daily_loss_count,
        },
        detail="ok",
    )
