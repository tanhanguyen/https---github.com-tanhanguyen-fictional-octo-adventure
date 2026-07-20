"""Plan 04 DoD: a second golden determinism test for a 3-symbol portfolio (companion
to test_replay_golden.py's 1-symbol case) -- same determinism assertions, proving the
merged-clock/portfolio machinery is itself deterministic, not just the single-symbol
path."""

from __future__ import annotations

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import SymbolEntry
from bot.core.clock import Clock
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.portfolio import build_portfolio_from_synthetic
from bot.engine.runner import Runner

BARS = 400


def _three_symbol_config():
    config = load_default_config()
    config.symbols = [
        SymbolEntry(symbol="EURUSD", symbol_type="FOREX"),
        SymbolEntry(symbol="GBPUSD", symbol_type="FOREX"),
        SymbolEntry(
            symbol="XAUUSD",
            symbol_type="FOREX",
            overrides={"risk": {"max_risk_per_trade_pct": 0.5}},
        ),
    ]
    return config


def _run_once(seed: int) -> tuple[list[tuple[str, str, str, str]], float]:
    config = _three_symbol_config()
    portfolio = build_portfolio_from_synthetic(
        config, load_instruments(), seed, (BARS + 400) * 4
    )

    conn = connect_and_migrate(":memory:")
    symbol_datasets = {sym: f"golden-multi:{sym}" for sym in portfolio.symbols}
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


def test_multi_symbol_replay_is_deterministic_across_runs():
    stream1, equity1 = _run_once(42)
    stream2, equity2 = _run_once(42)
    assert stream1 == stream2
    assert equity1 == equity2
    # Sanity: all 3 symbols actually got processed (not silently dropped).
    assert {sym for _, sym, _, _ in stream1} == {"EURUSD", "GBPUSD", "XAUUSD"}


def test_multi_symbol_replay_different_seed_diverges():
    stream1, _ = _run_once(42)
    stream3, _ = _run_once(7)
    assert stream1 != stream3
