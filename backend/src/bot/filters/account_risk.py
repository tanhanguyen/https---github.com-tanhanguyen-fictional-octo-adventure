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

    if cfg.one_trade_per_symbol and ctx.symbol_open_trade:
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

    # Plan 04, user decision 2026-07-18 đợt 3: optional account-wide risk cap, default
    # off (None) so single-symbol/default-config behavior (and its golden hash) is
    # unaffected. Same reason vocabulary (§8), new stage.
    cap = ctx.config.risk.max_total_open_risk_pct
    if cap is not None and ctx.open_risk_pct_total >= cap:
        return FilterResult(
            id=FILTER_ID,
            kind=FilterKind.GATE,
            enabled=True,
            evaluated=True,
            passed=False,
            blocking=True,
            values={
                "open_risk_pct_total": ctx.open_risk_pct_total,
                "max_total_open_risk_pct": cap,
                "reason": "max_concurrent_trades_reached",
                "stage": "total_risk_cap",
            },
            detail="total_risk_cap blocking (open_risk_pct_total >= max_total_open_risk_pct)",
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
