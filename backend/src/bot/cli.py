"""CLI. `python -m bot.cli replay --seed 42 --bars 5000` runs the full runner loop over
synthetic data and prints a summary. Deterministic: two runs with the same seed produce
an identical decision-stream hash (bar_ts, reason, stage tuples) + final equity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig
from bot.core.clock import Clock
from bot.core.errors import ConfigError
from bot.core.timeframes import tf_rank
from bot.core.types import InstrumentSpec
from bot.data.dataset import (
    DatasetSpec,
    generate_bundle,
    import_csv_dataset,
    load_bundle_for_dataset,
)
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.runner import Runner
from bot.filters.registry import ALL_FILTER_IDS


def _default_db_path() -> str:
    # src/bot/cli.py -> parents[2] == backend/
    data_dir = Path(__file__).resolve().parents[2] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "runtime.db")


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


@dataclass
class _RunResult:
    stream: list[tuple[str, str, str]]
    decision_hash: str
    order_count: int
    final_equity: float
    reason_histogram: Counter[str]
    result_histogram: Counter[str]


def _run(
    conn_tag: str,
    config: BotConfig,
    instrument: InstrumentSpec,
    price_feed: Feed,
    dxy_feed: Feed | None,
    bars: int,
) -> _RunResult:
    conn = connect_and_migrate(":memory:")
    repo.upsert_dataset(conn, conn_tag, "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json(), note=conn_tag)
    run_id = repo.create_run(conn, conn_tag, cv_id, config.symbol, config.starting_equity)

    primary = config.timeframe
    first_ts = price_feed.frames[primary].index[0].to_pydatetime()
    clock = Clock(first_ts)
    runner = Runner(conn, run_id, price_feed, dxy_feed, config, instrument, clock)

    stream: list[tuple[str, str, str]] = []
    reason_histogram: Counter[str] = Counter()
    result_histogram: Counter[str] = Counter()
    for _ in range(bars):
        summary = runner.step()
        if summary is None:
            break
        stream.append((summary.bar_ts, summary.reason, summary.stage))
        reason_histogram[summary.reason] += 1
        if summary.closed_result is not None:
            result_histogram[summary.closed_result] += 1

    order_count = conn.execute(
        "SELECT COUNT(*) FROM trade WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    conn.close()

    stream_json = json.dumps(stream, separators=(",", ":"))
    decision_hash = hashlib.sha256(stream_json.encode("utf-8")).hexdigest()
    return _RunResult(
        stream=stream,
        decision_hash=decision_hash,
        order_count=order_count,
        final_equity=runner.equity,
        reason_histogram=reason_histogram,
        result_histogram=result_histogram,
    )


def cmd_replay(seed: int, bars: int) -> int:
    config = load_default_config()
    instrument = _build_instrument(config, load_instruments())

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

    result = _run("replay-inmem", config, instrument, price_feed, dxy_feed, bars)

    print(f"bars processed: {len(result.stream)}")
    print(f"reason histogram: {dict(result.reason_histogram)}")
    print(f"result histogram: {dict(result.result_histogram)}")
    print(f"final equity: {result.final_equity:.2f}")
    print(f"decision_stream_hash: {result.decision_hash}")
    print(f"final_equity_repr: {result.final_equity!r}")
    return 0


def cmd_import_csv(path: str, symbol: str, native_tf: str) -> int:
    conn = connect_and_migrate(_default_db_path())
    try:
        result = import_csv_dataset(conn, Path(path), symbol, native_tf)
    finally:
        conn.close()
    print(f"dataset_id: {result.dataset_id}")
    print(f"kind: {result.kind}")
    print(f"symbol: {result.symbol}  native_tf: {result.native_tf}")
    print(f"bars: {result.bar_count}  gaps: {result.gap_count}")
    print(f"range: {result.start_ts} -> {result.end_ts}")
    return 0


def cmd_replay_dataset(dataset_id: str, bars: int) -> int:
    config = load_default_config()
    instrument = _build_instrument(config, load_instruments())

    store_conn = connect_and_migrate(_default_db_path())
    try:
        row = repo.get_dataset(store_conn, dataset_id)
        if row is None:
            raise ConfigError(f"unknown dataset id {dataset_id!r}")
        if row["kind"] == "csv" and tf_rank(row["native_tf"]) > tf_rank(config.timeframe):
            raise ConfigError(
                f"dataset native_tf {row['native_tf']!r} is coarser than "
                f"config.timeframe {config.timeframe!r} -- pick a finer-or-equal timeframe"
            )
        bundle = load_bundle_for_dataset(store_conn, dataset_id, config)
    finally:
        store_conn.close()

    price_feed = Feed(frames=bundle.price)
    dxy_feed = Feed(frames=bundle.dxy) if bundle.dxy is not None else None

    result = _run(f"replay-dataset-{dataset_id}", config, instrument, price_feed, dxy_feed, bars)

    print(f"bars processed: {len(result.stream)}")
    print(f"reason histogram: {dict(result.reason_histogram)}")
    print(f"result histogram: {dict(result.result_histogram)}")
    print(f"final equity: {result.final_equity:.2f}")
    print(f"decision_stream_hash: {result.decision_hash}")
    print(f"final_equity_repr: {result.final_equity!r}")
    return 0


# Filters that never toggle (locked, or DERIVED/structural) -- excluded from the A/B sweep.
_AB_EXCLUDED_FILTERS = {"atr_ref"}

# Rarely-triggered on synthetic data (docs/decisions.md, Phase 2/3 deviations): toggling
# them may not change the decision stream for a given seed/bars, so the harness only warns
# instead of failing when their hash doesn't move.
_AB_MAY_BE_INERT = {
    "news",
    "dxy",
    "volume",
    "atr_zscore",
    "equity_curve",
    "range_width",
    "wick",
    "account_risk",
    "time_stop",
    # Since 2026-07-19 confirmation_lag no longer applies to BREAKOUT signals (retest
    # embeds its own confirmation, docs/decisions.md) -- it only gates MEAN_REVERSION,
    # which is itself rare on synthetic data (3-condition AND).
    "confirmation_lag",
    # Breakout signals are inherently trend-following, so their direction structurally
    # tends to already agree with the HTF trend -- an mtf conflict is rare on synthetic
    # data (same class of rarity as MR's 3-condition AND, see docs/decisions.md).
    "mtf",
}


def cmd_ab(seed: int, bars: int) -> int:
    config = load_default_config()
    instrument = _build_instrument(config, load_instruments())

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

    baseline = _run("ab-baseline", config, instrument, price_feed, dxy_feed, bars)

    print(f"{'filter':<18}{'hash changed?':<16}{'delta orders':<14}")
    dead: list[str] = []
    for fid in ALL_FILTER_IDS:
        if fid in _AB_EXCLUDED_FILTERS:
            continue
        variant = config.model_copy(deep=True)
        toggle = getattr(variant.filters, fid)
        toggle.enabled = not toggle.enabled
        result = _run(f"ab-{fid}", variant, instrument, price_feed, dxy_feed, bars)

        changed = result.decision_hash != baseline.decision_hash
        delta = result.order_count - baseline.order_count
        print(f"{fid:<18}{('YES' if changed else 'no'):<16}{delta:+d}")
        if not changed and fid not in _AB_MAY_BE_INERT:
            dead.append(fid)

    if dead:
        print(f"WARNING: unexplained dead filters (no hash change on toggle): {dead}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot")
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay", help="Run the bot over synthetic mock data or a dataset")
    replay.add_argument("--seed", type=int, default=42)
    replay.add_argument("--bars", type=int, default=5000)
    replay.add_argument(
        "--dataset", type=str, default=None, help="Run against an imported dataset id"
    )

    ab = sub.add_parser("ab", help="A/B each filter (baseline vs toggled) against a baseline")
    ab.add_argument("--seed", type=int, default=42)
    ab.add_argument("--bars", type=int, default=5000)

    import_csv = sub.add_parser("import-csv", help="Register a real OHLCV CSV as a dataset")
    import_csv.add_argument("--path", type=str, required=True)
    import_csv.add_argument("--symbol", type=str, required=True)
    import_csv.add_argument(
        "--native-tf", type=str, default="15m", choices=["15m", "1H", "4H", "1D"]
    )

    args = parser.parse_args(argv)
    if args.command == "replay":
        if args.dataset is not None:
            return cmd_replay_dataset(args.dataset, args.bars)
        return cmd_replay(args.seed, args.bars)
    if args.command == "ab":
        return cmd_ab(args.seed, args.bars)
    if args.command == "import-csv":
        return cmd_import_csv(args.path, args.symbol, args.native_tf)
    return 1


if __name__ == "__main__":
    sys.exit(main())
