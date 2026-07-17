"""Determinism: two replay runs with the same seed must produce an identical
decision-stream hash and final equity. Uses a smaller bar count than the CLI's default
(5000) to keep the test fast while still exercising the full runner loop end to end."""

from __future__ import annotations

from bot.cli import _build_instrument
from bot.config.loader import load_default_config, load_instruments
from bot.core.clock import Clock
from bot.data.dataset import DatasetSpec, generate_bundle
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.runner import Runner

BARS = 600


def _run_once(seed: int) -> tuple[list[tuple[str, str, str]], float]:
    config = load_default_config()
    instrument = _build_instrument(config, load_instruments())

    dataset_spec = DatasetSpec(seed=seed, n_candles_15m=(BARS + 400) * 4, symbol=config.symbol)
    bundle = generate_bundle(dataset_spec)
    price_feed = Feed(frames=bundle["price"])
    dxy_feed = Feed(frames=bundle["dxy"])

    conn = connect_and_migrate(":memory:")
    repo.upsert_dataset(conn, "golden", "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json())
    run_id = repo.create_run(conn, "golden", cv_id, config.symbol, config.starting_equity)

    primary = config.timeframe
    first_ts = price_feed.frames[primary].index[0].to_pydatetime()
    clock = Clock(first_ts)
    runner = Runner(conn, run_id, price_feed, dxy_feed, config, instrument, clock)

    stream = []
    for _ in range(BARS):
        summary = runner.step()
        if summary is None:
            break
        stream.append((summary.bar_ts, summary.reason, summary.stage))

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
    instrument = _build_instrument(config, load_instruments())
    dataset_spec = DatasetSpec(seed=42, n_candles_15m=(BARS + 400) * 4, symbol=config.symbol)
    bundle = generate_bundle(dataset_spec)
    price_feed = Feed(frames=bundle["price"])
    dxy_feed = Feed(frames=bundle["dxy"])
    conn = connect_and_migrate(":memory:")
    repo.upsert_dataset(conn, "golden2", "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json())
    run_id = repo.create_run(conn, "golden2", cv_id, config.symbol, config.starting_equity)
    primary = config.timeframe
    first_ts = price_feed.frames[primary].index[0].to_pydatetime()
    clock = Clock(first_ts)
    runner = Runner(conn, run_id, price_feed, dxy_feed, config, instrument, clock)

    equities = []
    for _ in range(BARS):
        summary = runner.step()
        if summary is None:
            break
        equities.append(summary.equity)

    # No single-bar equity change should exceed a few % of starting equity (sanity,
    # not a strict risk-management assertion -- MAX_RISK_PER_TRADE=1% per trade means
    # single-trade losses stay small; this just catches gross accounting bugs).
    for prev, cur in zip(equities, equities[1:], strict=False):
        assert abs(cur - prev) < 0.10 * config.starting_equity
