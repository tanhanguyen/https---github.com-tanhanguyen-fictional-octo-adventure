"""Determinism: two replay runs with the same seed must produce an identical
decision-stream hash and final equity. Uses a smaller bar count than the CLI's default
(5000) to keep the test fast while still exercising the full runner loop end to end."""

from __future__ import annotations

from bot.config.loader import load_default_config, load_instruments
from bot.core.clock import Clock
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.portfolio import build_portfolio_from_synthetic
from bot.engine.runner import Runner

BARS = 600


def _run_once(seed: int) -> tuple[list[tuple[str, str, str, str]], float]:
    config = load_default_config()
    # Plan 04: even a 1-symbol config now generates its dataset via
    # named_child_seed(seed, symbol) rather than the raw seed directly (documented
    # deviation, docs/decisions.md) -- the *stream* is still fully deterministic, which
    # is all this test asserts (there is no externally pinned hash to match).
    portfolio = build_portfolio_from_synthetic(
        config, load_instruments(), seed, (BARS + 400) * 4
    )

    conn = connect_and_migrate(":memory:")
    symbol_datasets = {sym: f"golden:{sym}" for sym in portfolio.symbols}
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


def test_replay_is_deterministic_across_runs():
    stream1, equity1 = _run_once(42)
    stream2, equity2 = _run_once(42)
    assert stream1 == stream2
    assert equity1 == equity2


def test_replay_different_seed_diverges():
    stream1, _ = _run_once(42)
    stream3, _ = _run_once(7)
    assert stream1 != stream3


def test_replay_equity_curve_stable_no_absurd_jumps():
    config = load_default_config()
    portfolio = build_portfolio_from_synthetic(
        config, load_instruments(), 42, (BARS + 400) * 4
    )
    conn = connect_and_migrate(":memory:")
    symbol_datasets = {sym: f"golden2:{sym}" for sym in portfolio.symbols}
    for did in symbol_datasets.values():
        repo.upsert_dataset(conn, did, "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json())
    run_id = repo.create_run(conn, cv_id, symbol_datasets, config.starting_equity)
    clock = Clock(min(sc.cursor for sc in portfolio.symbols.values()))
    runner = Runner(conn, run_id, portfolio.symbols, portfolio.dxy_feed, config, clock)

    equities = []
    for _ in range(BARS):
        summaries = runner.step()
        if not summaries:
            break
        equities.extend(s.equity for s in summaries)

    # No single-bar equity change should exceed a few % of starting equity (sanity,
    # not a strict risk-management assertion -- MAX_RISK_PER_TRADE=1% per trade means
    # single-trade losses stay small; this just catches gross accounting bugs).
    for prev, cur in zip(equities, equities[1:], strict=False):
        assert abs(cur - prev) < 0.10 * config.starting_equity
