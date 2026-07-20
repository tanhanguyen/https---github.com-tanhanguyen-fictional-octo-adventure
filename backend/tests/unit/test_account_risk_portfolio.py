"""Plan 04: account_risk filter's portfolio-wide fields (open_trades_count,
symbol_open_trade, open_risk_pct_total) — filter-level unit tests complementing the
Runner-level integration test in test_multi_symbol_clock.py."""

from __future__ import annotations

from dataclasses import replace

from bot.filters import account_risk


def test_max_concurrent_trades_reached_without_symbol_open_trade(base_ctx):
    """Scenario (a) at filter level: portfolio already has MAX_CONCURRENT_TRADES open
    trades (none of them on THIS symbol) -- a 4th symbol's signal must still be blocked,
    with stage=account_risk/max_concurrent_trades (not one_trade_per_symbol, since this
    symbol itself has no open trade)."""
    cfg = base_ctx.config.filters.account_risk
    ctx = replace(
        base_ctx,
        open_trades_count=cfg.max_concurrent_trades,
        symbol_open_trade=False,
    )
    r = account_risk.evaluate(ctx)
    assert not r.passed and r.blocking
    assert r.values["reason"] == "max_concurrent_trades_reached"
    assert r.values["stage"] == "account_risk"


def test_total_risk_cap_blocks_when_set_and_exceeded(base_ctx):
    cfg = base_ctx.config.model_copy(deep=True)
    cfg.risk.max_total_open_risk_pct = 2.0
    ctx = replace(base_ctx, config=cfg, open_risk_pct_total=2.0, symbol_open_trade=False)
    r = account_risk.evaluate(ctx)
    assert not r.passed and r.blocking
    assert r.values["reason"] == "max_concurrent_trades_reached"
    assert r.values["stage"] == "total_risk_cap"


def test_total_risk_cap_off_by_default_does_not_block(base_ctx):
    assert base_ctx.config.risk.max_total_open_risk_pct is None
    ctx = replace(base_ctx, open_risk_pct_total=999.0)
    r = account_risk.evaluate(ctx)
    assert r.passed and not r.blocking


def test_total_risk_cap_does_not_block_below_threshold(base_ctx):
    cfg = base_ctx.config.model_copy(deep=True)
    cfg.risk.max_total_open_risk_pct = 5.0
    ctx = replace(base_ctx, config=cfg, open_risk_pct_total=1.0, symbol_open_trade=False)
    r = account_risk.evaluate(ctx)
    assert r.passed and not r.blocking
