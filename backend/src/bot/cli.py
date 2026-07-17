"""CLI. `python -m bot.cli replay --seed 42 --bars 5000` runs the full runner loop over
synthetic data and prints a summary. Deterministic: two runs with the same seed produce
an identical decision-stream hash (bar_ts, reason, stage tuples) + final equity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from typing import Any

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig
from bot.core.clock import Clock
from bot.core.types import InstrumentSpec
from bot.data.dataset import DatasetSpec, generate_bundle
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.runner import Runner


def _build_instrument(config: BotConfig, instruments_yaml: dict[str, Any]) -> InstrumentSpec:
    spec = instruments_yaml[config.symbol]
    return InstrumentSpec(
        symbol=spec["symbol"],
        contract_size=spec["contract_size"],
        pip=spec["pip"],
        pip_value_per_lot=spec["pip_value_per_lot"],
        spread_pips=spec["spread_pips"],
        min_lot=spec["min_lot"],
        lot_step=spec["lot_step"],
    )


def cmd_replay(seed: int, bars: int) -> int:
    config = load_default_config()
    instruments_yaml = load_instruments()
    instrument = _build_instrument(config, instruments_yaml)

    n_candles_15m = (bars + 400) * 4
    dataset_spec = DatasetSpec(
        seed=seed,
        n_candles_15m=n_candles_15m,
        symbol=config.symbol,
        rollover_tz=config.trading_day_rollover_tz,
        rollover_time=config.trading_day_rollover_time,
    )
    bundle = generate_bundle(dataset_spec)
    price_feed = Feed(frames=bundle["price"])
    dxy_feed = Feed(frames=bundle["dxy"])

    conn = connect_and_migrate(":memory:")
    repo.upsert_dataset(conn, "replay-inmem", json.dumps({"seed": seed, "bars": bars}))
    cv_id = repo.create_config_version(conn, config.model_dump_json(), note="replay")
    run_id = repo.create_run(conn, "replay-inmem", cv_id, config.symbol, config.starting_equity)

    primary = config.timeframe
    first_ts = price_feed.frames[primary].index[0].to_pydatetime()
    clock = Clock(first_ts)

    runner = Runner(conn, run_id, price_feed, dxy_feed, config, instrument, clock)

    stream: list[tuple[str, str, str]] = []
    reason_histogram: Counter[str] = Counter()
    strategy_trade_count: Counter[str] = Counter()

    for _ in range(bars):
        summary = runner.step()
        if summary is None:
            break
        stream.append((summary.bar_ts, summary.reason, summary.stage))
        reason_histogram[summary.reason] += 1
        if summary.closed_result is not None:
            strategy_trade_count[summary.closed_result] += 1

    cur = conn.execute(
        "SELECT strategy, COUNT(*) FROM trade WHERE run_id=? AND status='CLOSED' GROUP BY strategy",
        (run_id,),
    )
    per_strategy = dict(cur.fetchall())

    stream_json = json.dumps(stream, separators=(",", ":"))
    decision_hash = hashlib.sha256(stream_json.encode("utf-8")).hexdigest()

    print(f"bars processed: {len(stream)}")
    print(f"trades per strategy: {per_strategy}")
    print(f"reason histogram: {dict(reason_histogram)}")
    print(f"result histogram: {dict(strategy_trade_count)}")
    print(f"final equity: {runner.equity:.2f}")
    print(f"decision_stream_hash: {decision_hash}")
    print(f"final_equity_repr: {runner.equity!r}")

    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot")
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay", help="Run the bot over synthetic mock data")
    replay.add_argument("--seed", type=int, default=42)
    replay.add_argument("--bars", type=int, default=5000)

    args = parser.parse_args(argv)
    if args.command == "replay":
        return cmd_replay(args.seed, args.bars)
    return 1


if __name__ == "__main__":
    sys.exit(main())
