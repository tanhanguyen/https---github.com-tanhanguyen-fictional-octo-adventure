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

from bot.analytics.metrics import RunReport, compute_run_report
from bot.config.loader import load_default_config, load_instruments
from bot.config.models import BotConfig, effective_config_for_symbol
from bot.core.clock import Clock
from bot.core.errors import ConfigError
from bot.core.timeframes import tf_rank
from bot.core.types import InstrumentSpec
from bot.data.dataset import import_csv_dataset, load_bundle_for_dataset
from bot.data.feed import Feed
from bot.data.news import import_news_csv
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.engine.context import SymbolContext, build_symbol_context
from bot.engine.portfolio import build_portfolio_from_synthetic
from bot.engine.runner import Runner
from bot.filters.registry import ALL_FILTER_IDS


def _default_db_path() -> str:
    # src/bot/cli.py -> parents[2] == backend/
    data_dir = Path(__file__).resolve().parents[2] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "runtime.db")


def _build_instrument(symbol: str, instruments_yaml: dict[str, Any]) -> InstrumentSpec:
    spec = instruments_yaml[symbol]
    return InstrumentSpec(
        symbol=spec["symbol"],
        contract_size=spec["contract_size"],
        pip=spec["pip"],
        pip_value_per_lot=spec["pip_value_per_lot"],
        spread_pips=spec["spread_pips"],
        min_lot=spec["min_lot"],
        lot_step=spec["lot_step"],
        currencies=tuple(spec.get("currencies", ())),
    )


@dataclass
class _RunResult:
    stream: list[tuple[str, str, str, str]]  # (bar_ts, symbol, reason, stage)
    decision_hash: str
    order_count: int
    final_equity: float
    reason_histogram: Counter[str]
    result_histogram: Counter[str]
    report: RunReport


def _run(
    conn_tag: str,
    config: BotConfig,
    symbols: dict[str, SymbolContext],
    dxy_feed: Feed | None,
    bars: int,
) -> _RunResult:
    conn = connect_and_migrate(":memory:")
    # One dummy dataset row per symbol, purely to satisfy run_symbol_dataset's FK --
    # the actual price data lives in each SymbolContext's Feed, not this bookkeeping conn.
    symbol_datasets = {sym: f"{conn_tag}:{sym}" for sym in symbols}
    for did in symbol_datasets.values():
        repo.upsert_dataset(conn, did, "{}")
    cv_id = repo.create_config_version(conn, config.model_dump_json(), note=conn_tag)
    run_id = repo.create_run(conn, cv_id, symbol_datasets, config.starting_equity)

    clock = Clock(min(sc.cursor for sc in symbols.values()))
    runner = Runner(conn, run_id, symbols, dxy_feed, config, clock)

    stream: list[tuple[str, str, str, str]] = []
    reason_histogram: Counter[str] = Counter()
    result_histogram: Counter[str] = Counter()
    for _ in range(bars):
        summaries = runner.step()
        if not summaries:
            break
        for summary in summaries:
            stream.append((summary.bar_ts, summary.symbol, summary.reason, summary.stage))
            reason_histogram[summary.reason] += 1
            if summary.closed_result is not None:
                result_histogram[summary.closed_result] += 1

    order_count = conn.execute(
        "SELECT COUNT(*) FROM trade WHERE run_id=?", (run_id,)
    ).fetchone()[0]

    closed_trades = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM trade WHERE run_id=? AND status='CLOSED' ORDER BY id", (run_id,)
        )
    ]
    equity_series = [
        float(r[0])
        for r in conn.execute(
            "SELECT equity FROM equity_point WHERE run_id=? ORDER BY id", (run_id,)
        )
    ]
    filter_blocks = {
        str(r[0]): int(r[1])
        for r in conn.execute(
            "SELECT df.filter_id, COUNT(*) FROM decision_filter df "
            "JOIN decision d ON d.id = df.decision_id "
            "WHERE d.run_id=? AND df.blocking=1 GROUP BY df.filter_id",
            (run_id,),
        )
    }
    report = compute_run_report(
        closed_trades,
        equity_series,
        config.starting_equity,
        config.timeframe,
        dict(reason_histogram),
        filter_blocks,
    )
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
        report=report,
    )


def _fmt(x: float | None, spec: str = ".2f", suffix: str = "") -> str:
    return "n/a" if x is None else f"{format(x, spec)}{suffix}"


def _print_report(report: RunReport) -> None:
    o, s = report.overall, report.series
    win_rate_pct = None if o.win_rate is None else o.win_rate * 100.0
    print("--- RunReport ---")
    print(
        f"trades: {o.n_total} (WIN {o.n_win} / LOSS {o.n_loss} / BE {o.n_breakeven})  "
        f"strategy: {o.n_by_strategy}  direction: {o.n_by_direction}"
    )
    print(
        f"win_rate: {_fmt(win_rate_pct, '.1f', '%')}  "
        f"profit_factor: {_fmt(o.profit_factor)}  "
        f"expectancy: {_fmt(o.expectancy_r, '.3f', 'R')}  "
        f"avg_hold: {_fmt(o.avg_holding_hours, '.1f', 'h')}"
    )
    print(
        f"avg/max win: {_fmt(o.avg_win)}/{_fmt(o.max_win)}  "
        f"avg/max loss: {_fmt(o.avg_loss)}/{_fmt(o.max_loss)}"
    )
    print(
        f"final_equity: {s.final_equity:.2f}  return: {s.total_return_pct:.2f}%  "
        f"max_dd: {s.max_drawdown_abs:.2f} ({s.max_drawdown_pct:.2f}%)  "
        f"longest_dd: {s.longest_drawdown_bars} bars  sharpe: {_fmt(s.sharpe)}"
    )
    if report.filter_block_counts:
        print(f"filter_blocks: {report.filter_block_counts}")


def cmd_replay(seed: int, bars: int) -> int:
    config = load_default_config()
    n_candles_15m = (bars + 400) * 4
    portfolio = build_portfolio_from_synthetic(config, load_instruments(), seed, n_candles_15m)

    result = _run("replay-inmem", config, portfolio.symbols, portfolio.dxy_feed, bars)

    print(f"bars processed: {len(result.stream)}")
    print(f"reason histogram: {dict(result.reason_histogram)}")
    print(f"result histogram: {dict(result.result_histogram)}")
    print(f"final equity: {result.final_equity:.2f}")
    print(f"decision_stream_hash: {result.decision_hash}")
    print(f"final_equity_repr: {result.final_equity!r}")
    _print_report(result.report)
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


def cmd_import_news(path: str) -> int:
    conn = connect_and_migrate(_default_db_path())
    try:
        result = import_news_csv(conn, Path(path))
    finally:
        conn.close()
    print(f"file_sha256: {result.file_sha256}")
    print(f"rows: {result.row_count}  inserted: {result.inserted_count}"
          f"  duplicates: {result.duplicate_count}")
    return 0


def cmd_replay_dataset(dataset_id: str, bars: int) -> int:
    # Plan 04 scope limit: `replay --dataset` (real/imported CSV data) stays single-symbol
    # -- it always replays the FIRST enabled entry in config.symbols. Multi-symbol
    # portfolios over real CSV data is plan 05/07 territory.
    config = load_default_config()
    enabled = [e for e in config.symbols if e.enabled]
    if not enabled:
        raise ConfigError("no enabled symbols in config.symbols")
    entry = enabled[0]
    eff_cfg = effective_config_for_symbol(config, entry)
    instrument = _build_instrument(entry.symbol, load_instruments())

    store_conn = connect_and_migrate(_default_db_path())
    try:
        row = repo.get_dataset(store_conn, dataset_id)
        if row is None:
            raise ConfigError(f"unknown dataset id {dataset_id!r}")
        if row["kind"] == "csv" and tf_rank(row["native_tf"]) > tf_rank(eff_cfg.timeframe):
            raise ConfigError(
                f"dataset native_tf {row['native_tf']!r} is coarser than "
                f"config.timeframe {eff_cfg.timeframe!r} -- pick a finer-or-equal timeframe"
            )
        bundle = load_bundle_for_dataset(store_conn, dataset_id, eff_cfg)
    finally:
        store_conn.close()

    price_feed = Feed(frames=bundle.price)
    dxy_feed = Feed(frames=bundle.dxy) if bundle.dxy is not None else None
    symbols = {entry.symbol: build_symbol_context(eff_cfg, price_feed, instrument)}

    result = _run(f"replay-dataset-{dataset_id}", config, symbols, dxy_feed, bars)

    print(f"bars processed: {len(result.stream)}")
    print(f"reason histogram: {dict(result.reason_histogram)}")
    print(f"result histogram: {dict(result.result_histogram)}")
    print(f"final equity: {result.final_equity:.2f}")
    print(f"decision_stream_hash: {result.decision_hash}")
    print(f"final_equity_repr: {result.final_equity!r}")
    _print_report(result.report)
    return 0


def cmd_live(symbol: str | None, db_path: str | None, testnet: bool, iterations: int | None) -> int:
    """Plan 07: one process runs the whole live portfolio (account-wide caps only mean
    something if one process owns them). `--symbol` is a debug override for running a
    single symbol; `--iterations` bounds the loop for smoke tests."""
    from bot.alerts import build_live_alerts, connect_alerts_db, default_alerts_db_path
    from bot.data.live_feed import BINANCE_FUTURES_MAINNET, BINANCE_FUTURES_TESTNET
    from bot.engine.live_factory import build_live_session
    from bot.logging_config import configure_logging

    # The live runner is the long-running, Docker-collected process: send its operational
    # events (feed degraded, trade opened/closed, errors) to stdout as JSON lines.
    configure_logging()

    # Plan 13: this is the composition root that decides a live run's alerts go to the
    # shared alert log (and from there to Telegram + the web UI), not just to a logger.
    # The thresholds come from the run's own config — resumed runs keep the frozen one.
    alerts_conn = connect_alerts_db()

    session = build_live_session(
        db_path=db_path,
        only_symbol=symbol,
        base_url=BINANCE_FUTURES_TESTNET if testnet else BINANCE_FUTURES_MAINNET,
        alerts_factory=lambda run_id, cfg: build_live_alerts(
            alerts_conn, cfg.alerts, run_id=run_id, source="live"
        ),
    )
    print(f"live run_id: {session.run_id}  ({'resumed' if session.resumed else 'new'})")
    print(f"symbols: {sorted(session.runner.symbols)}")
    print(f"db: {db_path or 'BOT_DB_PATH / backend/data/live.db'}")
    print(f"alerts db: {default_alerts_db_path()}")
    try:
        stats = session.runner.run_forever(max_iterations=iterations)
    finally:
        session.close()
        alerts_conn.close()
    print(
        f"bars processed: {stats.bars_processed}  polls: {stats.polls} "
        f"(failures {stats.poll_failures})  opened: {stats.trades_opened} "
        f"closed: {stats.trades_closed}  skipped duplicate ticks: "
        f"{stats.skipped_duplicate_ticks}"
    )
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
    n_candles_15m = (bars + 400) * 4
    portfolio = build_portfolio_from_synthetic(config, load_instruments(), seed, n_candles_15m)

    baseline = _run("ab-baseline", config, portfolio.symbols, portfolio.dxy_feed, bars)

    print(f"{'filter':<18}{'hash changed?':<16}{'delta orders':<14}")
    dead: list[str] = []
    for fid in ALL_FILTER_IDS:
        if fid in _AB_EXCLUDED_FILTERS:
            continue
        variant = config.model_copy(deep=True)
        toggle = getattr(variant.filters, fid)
        toggle.enabled = not toggle.enabled
        # Reuse the SAME generated feeds/instruments as baseline (only the effective
        # config's filter toggle changes) -- avoids regenerating datasets per variant.
        variant_symbols = {
            entry.symbol: build_symbol_context(
                effective_config_for_symbol(variant, entry),
                portfolio.symbols[entry.symbol].price_feed,
                portfolio.symbols[entry.symbol].order_engine.instrument,
            )
            for entry in variant.symbols
            if entry.enabled
        }
        result = _run(f"ab-{fid}", variant, variant_symbols, portfolio.dxy_feed, bars)

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

    live = sub.add_parser("live", help="Run live paper trading on a real-time venue feed")
    live.add_argument(
        "--symbol", type=str, default=None, help="Debug override: run this symbol only"
    )
    live.add_argument("--db", type=str, default=None, help="Live DB path (default: $BOT_DB_PATH)")
    live.add_argument(
        "--testnet", action="store_true", help="Use the Binance futures testnet base URL"
    )
    live.add_argument(
        "--iterations", type=int, default=None, help="Stop after N poll rounds (smoke test)"
    )

    import_news = sub.add_parser(
        "import-news", help="Import a standardized news-calendar CSV into news_event"
    )
    import_news.add_argument("--path", type=str, required=True)

    args = parser.parse_args(argv)
    if args.command == "replay":
        if args.dataset is not None:
            return cmd_replay_dataset(args.dataset, args.bars)
        return cmd_replay(args.seed, args.bars)
    if args.command == "ab":
        return cmd_ab(args.seed, args.bars)
    if args.command == "import-csv":
        return cmd_import_csv(args.path, args.symbol, args.native_tf)
    if args.command == "import-news":
        return cmd_import_news(args.path)
    if args.command == "live":
        return cmd_live(args.symbol, args.db, args.testnet, args.iterations)
    return 1


if __name__ == "__main__":
    sys.exit(main())
