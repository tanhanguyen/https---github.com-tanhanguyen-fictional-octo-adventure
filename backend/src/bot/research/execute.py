"""One sweep cell = one ORDINARY run.

Plan 11 §"Ràng buộc cứng": "Sweep không có đường tắt nào bỏ qua engine." So this module
does exactly what `cli.cmd_replay_dataset` / `RunnerService.create_run` do — build a
versioned config, register a run, drive `Runner.step()` — and adds only two things:
the config patch of the combo, and the window slice. Nothing here can change engine
behavior, which is why `test_replay_golden` is untouched by this plan.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd

from bot.analytics.metrics import RunReport, compute_run_report
from bot.config.loader import deep_merge, load_instruments
from bot.config.models import BotConfig, SymbolEntry, effective_config_for_symbol
from bot.core.clock import Clock
from bot.core.errors import ConfigError
from bot.core.timeframes import tf_rank
from bot.core.types import InstrumentSpec
from bot.data.dataset import DatasetBundle, load_bundle_for_dataset
from bot.data.feed import Feed
from bot.db import repositories as repo
from bot.engine.context import build_symbol_context
from bot.engine.runner import Runner
from bot.research.spec import SweepSpec, patch_from_params
from bot.research.windows import SlicedWindow, slice_between, to_utc, window_frames


@dataclass(frozen=True)
class ComboResult:
    combo_index: int
    params: dict[str, Any]
    run_id: int
    config_version_id: int
    metrics: dict[str, Any]
    decision_hash: str
    n_bars: int


@dataclass
class SweepContext:
    """Everything a combo needs that does NOT vary between combos — resolved once and
    reused, because loading a 100k-bar CSV bundle per combo would dominate the runtime."""

    spec: SweepSpec
    base_config: BotConfig
    entry: SymbolEntry
    instrument: InstrumentSpec
    bundle: DatasetBundle
    primary_tf: str
    data_from: pd.Timestamp
    data_to: pd.Timestamp


def build_instrument(symbol: str, instruments_yaml: dict[str, Any]) -> InstrumentSpec:
    spec = instruments_yaml.get(symbol)
    if spec is None:
        raise ConfigError(f"no instrument spec for symbol {symbol!r}")
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


def _pick_entry(config: BotConfig, wanted: str | None) -> SymbolEntry:
    """A sweep is single-symbol on purpose: the point is to attribute a metric change to
    a parameter, and a portfolio adds cross-symbol coupling (shared daily-loss budget,
    MAX_CONCURRENT_TRADES) that would make the attribution ambiguous."""
    enabled = [e for e in config.symbols if e.enabled]
    if not enabled:
        raise ConfigError("no enabled symbols in config.symbols")
    if wanted is not None:
        for entry in enabled:
            if entry.symbol == wanted:
                return entry
        raise ConfigError(
            f"symbol {wanted!r} is not an enabled entry in config.symbols "
            f"(have: {', '.join(e.symbol for e in enabled)})"
        )
    if len(enabled) > 1:
        raise ConfigError(
            f"{len(enabled)} symbols are enabled -- a sweep runs one symbol; name it "
            f"with `symbol:` in the spec (have: {', '.join(e.symbol for e in enabled)})"
        )
    return enabled[0]


def build_sweep_context(conn: sqlite3.Connection, spec: SweepSpec, base: BotConfig) -> SweepContext:
    """Resolve dataset + symbol + timeframe once. `spec.base_patch` and `spec.timeframe`
    are applied HERE (not per combo) so the loaded bundle already matches the timeframe
    the runs will use."""
    patch: dict[str, Any] = dict(spec.base_patch)
    if spec.timeframe is not None:
        patch = deep_merge(patch, {"timeframe": spec.timeframe})
    config = BotConfig.model_validate(deep_merge(base.model_dump(mode="json"), patch))

    entry = _pick_entry(config, spec.symbol)
    eff = effective_config_for_symbol(config, entry)

    row = repo.get_dataset(conn, spec.dataset_id)
    if row is None:
        raise ConfigError(f"unknown dataset id {spec.dataset_id!r}")
    if row["kind"] == "csv" and tf_rank(row["native_tf"]) > tf_rank(eff.timeframe):
        raise ConfigError(
            f"dataset native_tf {row['native_tf']!r} is coarser than timeframe "
            f"{eff.timeframe!r} -- pick a finer-or-equal timeframe"
        )
    bundle = load_bundle_for_dataset(conn, spec.dataset_id, eff)
    base_frame = bundle.price.get(eff.timeframe)
    if base_frame is None or len(base_frame) == 0:
        raise ConfigError(f"dataset has no bars on timeframe {eff.timeframe!r}")

    return SweepContext(
        spec=spec,
        base_config=config,
        entry=entry,
        instrument=build_instrument(entry.symbol, load_instruments()),
        bundle=bundle,
        primary_tf=eff.timeframe,
        data_from=base_frame.index[0],
        data_to=base_frame.index[-1],
    )


def full_range(ctx: SweepContext) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The [from, to) the spec asks for, clipped to what the dataset actually holds.
    `to` is exclusive, so the default end is one instant past the last bar open."""
    start = to_utc(ctx.spec.from_ts) if ctx.spec.from_ts else ctx.data_from
    end = to_utc(ctx.spec.to_ts) if ctx.spec.to_ts else ctx.data_to + pd.Timedelta(seconds=1)
    if end <= start:
        raise ConfigError(f"empty date range: from {start.isoformat()} to {end.isoformat()}")
    return start, end


def slice_window(ctx: SweepContext, start: pd.Timestamp, end: pd.Timestamp) -> SlicedWindow:
    return window_frames(ctx.bundle.price, ctx.primary_tf, start, end)


def combo_config(ctx: SweepContext, params: dict[str, Any]) -> BotConfig:
    merged = deep_merge(ctx.base_config.model_dump(mode="json"), patch_from_params(params))
    return BotConfig.model_validate(merged)


def flatten_metrics(report: RunReport) -> dict[str, Any]:
    """The RunReport fields a sweep table sorts/filters on. Deliberately flat and small:
    it is cached per row in `sweep_result.metrics_json`, and the full report is always
    one click away on the run's own Report page."""
    o, s = report.overall, report.series
    return {
        "n_trades": o.n_total,
        "n_win": o.n_win,
        "n_loss": o.n_loss,
        "n_breakeven": o.n_breakeven,
        "win_rate": o.win_rate,
        "profit_factor": o.profit_factor,
        "expectancy_r": o.expectancy_r,
        "avg_holding_hours": o.avg_holding_hours,
        "final_equity": s.final_equity,
        "total_return_pct": s.total_return_pct,
        "max_drawdown_pct": s.max_drawdown_pct,
        "sharpe": s.sharpe,
        "n_bars": s.n_bars,
    }


def run_combo(
    conn: sqlite3.Connection,
    ctx: SweepContext,
    window: SlicedWindow,
    params: dict[str, Any],
    combo_index: int,
    note: str,
) -> ComboResult:
    """Execute one combo end-to-end against `conn` (which may be a per-worker temp DB).

    The config version is created with `activate=False` on purpose: a 108-combo sweep
    would otherwise reassign the user's ACTIVE config 108 times as a side effect of a
    research job. It is still a real immutable version row (invariant #7), and the run
    row points at it, so the drill-down shows exactly which parameters produced it."""
    config = combo_config(ctx, params)
    eff = effective_config_for_symbol(config, ctx.entry)

    price_feed = Feed(frames=window.frames)
    dxy_feed = None
    if ctx.bundle.dxy is not None:
        dxy_feed = Feed(frames=slice_between(ctx.bundle.dxy, window.warm_from, window.end))

    cv_id = repo.create_config_version(conn, config.model_dump_json(), note=note, activate=False)
    run_id = repo.create_run(
        conn, cv_id, {ctx.entry.symbol: ctx.spec.dataset_id}, config.starting_equity
    )

    symbols = {
        ctx.entry.symbol: build_symbol_context(
            eff, price_feed, ctx.instrument, cursor=window.cursor
        )
    }
    runner = Runner(conn, run_id, symbols, dxy_feed, config, Clock(window.cursor))

    stream: list[tuple[str, str, str, str]] = []
    reason_histogram: Counter[str] = Counter()
    while True:
        summaries = runner.step()
        if not summaries:
            break
        for s in summaries:
            stream.append((s.bar_ts, s.symbol, s.reason, s.stage))
            reason_histogram[s.reason] += 1

    # A sweep run is always played to the end of its window, so unlike an interactive
    # backtest (which is stepped by hand and stays RUNNING) it can honestly say DONE.
    repo.set_run_status(conn, run_id, "DONE")
    report = _report_for(conn, run_id, config, reason_histogram)
    decision_hash = hashlib.sha256(
        json.dumps(stream, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ComboResult(
        combo_index=combo_index,
        params=params,
        run_id=run_id,
        config_version_id=cv_id,
        metrics=flatten_metrics(report),
        decision_hash=decision_hash,
        n_bars=len(stream),
    )


def _report_for(
    conn: sqlite3.Connection, run_id: int, config: BotConfig, reason_histogram: Counter[str]
) -> RunReport:
    closed = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM trade WHERE run_id=? AND status='CLOSED' ORDER BY id", (run_id,)
        )
    ]
    equity = [
        float(r[0])
        for r in conn.execute(
            "SELECT equity FROM equity_point WHERE run_id=? ORDER BY id", (run_id,)
        )
    ]
    blocks = {
        str(r[0]): int(r[1])
        for r in conn.execute(
            "SELECT df.filter_id, COUNT(*) FROM decision_filter df "
            "JOIN decision d ON d.id = df.decision_id "
            "WHERE d.run_id=? AND df.blocking=1 GROUP BY df.filter_id",
            (run_id,),
        )
    }
    return compute_run_report(
        closed,
        equity,
        config.starting_equity,
        config.timeframe,
        dict(reason_histogram),
        blocks,
    )
