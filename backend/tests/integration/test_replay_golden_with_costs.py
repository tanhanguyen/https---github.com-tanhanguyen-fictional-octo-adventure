"""§10: with execution.costs > 0, the replay is still deterministic, and strictly
worse (equity-wise) than the same seed's zero-cost golden run -- costs never help.
Companion to test_replay_golden.py; that file's config (all costs default to 0)
is untouched, so its pinned hash is unaffected by this plan."""

from __future__ import annotations

from bot.config.loader import load_default_config, load_instruments
from bot.core.clock import Clock
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.portfolio import build_portfolio_from_synthetic
from bot.engine.runner import Runner
from tests.integration.test_replay_golden import BARS, _run_once


def _run_once_with_costs(seed: int) -> tuple[list[tuple[str, str, str, str]], float]:
    config = load_default_config()
    config.execution.costs.spread_pips = 1.0
    config.execution.costs.slippage_pips = 0.5
    config.execution.costs.commission_per_lot = 2.0
    portfolio = build_portfolio_from_synthetic(
        config, load_instruments(), seed, (BARS + 400) * 4
    )

    conn = connect_and_migrate(":memory:")
    symbol_datasets = {sym: f"golden-costs:{sym}" for sym in portfolio.symbols}
    for did in symbol_datasets.values():
        repo.upsert_dataset(conn, did, "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json())
    run_id = repo.create_run(conn, cv_id, symbol_datasets, config.starting_equity)

    clock = Clock(min(sc.cursor for sc in portfolio.symbols.values()))
    runner = Runner(conn, run_id, portfolio.symbols, portfolio.dxy_feed, config, clock)

    stream: list[tuple[str, str, str, str]] = []
    for _ in range(BARS):
        summaries = runner.step()
        if not summaries:
            break
        for summary in summaries:
            stream.append((summary.bar_ts, summary.symbol, summary.reason, summary.stage))

    conn.close()
    return stream, runner.equity


def test_replay_with_costs_is_deterministic():
    stream1, equity1 = _run_once_with_costs(42)
    stream2, equity2 = _run_once_with_costs(42)
    assert stream1 == stream2
    assert equity1 == equity2


def test_costs_strictly_hurt_equity_vs_zero_cost_golden_run():
    zero_cost_stream, zero_cost_equity = _run_once(42)
    costs_stream, costs_equity = _run_once_with_costs(42)

    # Same signals/decisions structurally: costs only move fill/exit prices and
    # commission, they don't change the decision stream's reason/stage sequence
    # length-for-length (same bars processed).
    assert len(zero_cost_stream) == len(costs_stream)
    assert costs_equity < zero_cost_equity
