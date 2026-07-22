"""Plan 06: news calendar import + per-run snapshot freeze.

Determinism requirement (plan 06 §3): news events are appended to `news_event` and
imported files never mutate existing rows, but a RUN only ever sees the snapshot taken
at its own creation time -- importing a new file later must not change an existing
run's decision stream. A brand-new run created after the import DOES see it."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.config.loader import load_default_config, load_instruments
from bot.core.clock import Clock
from bot.data.news import import_news_csv
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.portfolio import build_portfolio_from_synthetic
from bot.engine.runner import Runner

BARS = 50


def _write_news_csv(path: Path, ts_utc: str) -> None:
    pd.DataFrame(
        [{"ts_utc": ts_utc, "currency": "EUR", "impact": "high", "title": "ECB rate decision"}]
    ).to_csv(path, index=False)


def _build_runner(conn, config, portfolio, tag: str) -> Runner:
    symbol_datasets = {sym: f"{tag}:{sym}" for sym in portfolio.symbols}
    for did in symbol_datasets.values():
        repo.upsert_dataset(conn, did, "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json(), note=tag)
    run_id = repo.create_run(conn, cv_id, symbol_datasets, config.starting_equity)
    clock = Clock(min(sc.cursor for sc in portfolio.symbols.values()))
    return Runner(conn, run_id, portfolio.symbols, portfolio.dxy_feed, config, clock)


def test_import_news_csv_is_idempotent(tmp_path: Path):
    path = tmp_path / "news.csv"
    _write_news_csv(path, "2024-06-03T10:00:00+00:00")
    conn = connect_and_migrate(":memory:")
    r1 = import_news_csv(conn, path)
    r2 = import_news_csv(conn, path)
    assert r1.inserted_count == 1 and r1.duplicate_count == 0
    assert r2.inserted_count == 0 and r2.duplicate_count == 1
    count = conn.execute("SELECT COUNT(*) FROM news_event").fetchone()[0]
    assert count == 1


def test_news_snapshot_freezes_existing_run_but_blocks_new_run(tmp_path: Path):
    config = load_default_config()
    config.filters.news.enabled = True
    config.filters.news.window_before_min = 10_000_000  # wide enough to cover the whole run
    config.filters.news.window_after_min = 10_000_000

    portfolio_a = build_portfolio_from_synthetic(config, load_instruments(), 42, (BARS + 400) * 4)
    conn = connect_and_migrate(":memory:")

    runner_a = _build_runner(conn, config, portfolio_a, "run-a")
    first_ts = portfolio_a.symbols["EURUSD"].price_feed.frames[config.timeframe].index[0]

    # Import happens AFTER runner_a's snapshot was taken (Runner.__init__ already ran).
    news_path = tmp_path / "news.csv"
    _write_news_csv(news_path, first_ts.isoformat())
    import_news_csv(conn, news_path)

    stream_a = []
    for _ in range(BARS):
        summaries = runner_a.step()
        if not summaries:
            break
        stream_a.extend((s.reason, s.stage) for s in summaries)

    assert not any(stage == "news_blackout" for _reason, stage in stream_a), (
        "an existing run must not see events imported after its snapshot was taken"
    )

    # A brand-new run built on the SAME conn after the import sees the event.
    portfolio_b = build_portfolio_from_synthetic(config, load_instruments(), 42, (BARS + 400) * 4)
    runner_b = _build_runner(conn, config, portfolio_b, "run-b")
    stream_b = []
    for _ in range(BARS):
        summaries = runner_b.step()
        if not summaries:
            break
        stream_b.extend((s.reason, s.stage) for s in summaries)

    assert any(stage == "news_blackout" for _reason, stage in stream_b), (
        "a run created after the import must see the snapshotted event"
    )
