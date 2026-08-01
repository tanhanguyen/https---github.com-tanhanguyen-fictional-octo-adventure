"""Grid / random parameter sweep (plan 11 §1).

Sequential by default. `--workers N` runs each combo in its own process against its own
temp sqlite file, then merges that file's run into the main DB (`research.merge`) — the
results are IDENTICAL to a sequential run, because a combo is deterministic given its
config and its data window, and the merge happens in combo order so even the run ids
line up. `tests/integration/test_sweep.py` pins that equivalence.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import statistics
import tempfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.config.loader import load_default_config
from bot.config.models import BotConfig
from bot.core.errors import ConfigError
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.research.execute import (
    ComboResult,
    SweepContext,
    build_sweep_context,
    full_range,
    run_combo,
    slice_window,
)
from bot.research.merge import merge_single_run
from bot.research.spec import BARS_PER_SECOND, DEFAULT_MAX_COMBOS, Selection, SweepSpec
from bot.research.windows import SlicedWindow, bar_count

Log = Callable[[str], None]


@dataclass(frozen=True)
class ScoredResult:
    """A ComboResult plus the selection verdict (❓2 constraints)."""

    result: ComboResult
    metric_value: float | None
    eligible: bool
    ineligible_reason: str


@dataclass(frozen=True)
class CostEstimate:
    n_combos: int
    n_windows: int
    bars_per_run: int
    seconds: float

    @property
    def n_runs(self) -> int:
        return self.n_combos * self.n_windows

    def describe(self) -> str:
        minutes = self.seconds / 60.0
        return (
            f"{self.n_runs} run(s) = {self.n_combos} combo(s) x {self.n_windows} window(s), "
            f"~{self.bars_per_run} bars each -> ước lượng ~{minutes:.1f} phút "
            f"(1 worker, ~{BARS_PER_SECOND:g} bar/s)"
        )


def base_config_for(conn: sqlite3.Connection) -> tuple[BotConfig, int | None]:
    """The config a sweep varies FROM: the DB's active version if there is one, else the
    checked-in default. Recorded on the sweep row so a result is reproducible even after
    the active version moves on."""
    row = repo.get_active_config_version(conn)
    if row is None:
        return load_default_config(), None
    return BotConfig.model_validate_json(row["config_json"]), int(row["id"])


def estimate_cost(
    ctx: SweepContext, n_combos: int, windows: Sequence[SlicedWindow]
) -> CostEstimate:
    bars = max(bar_count(w.frames, ctx.primary_tf, w.cursor) for w in windows) if windows else 0
    return CostEstimate(
        n_combos=n_combos,
        n_windows=len(windows),
        bars_per_run=bars,
        seconds=n_combos * len(windows) * bars / BARS_PER_SECOND,
    )


def check_cost_guard(
    estimate: CostEstimate, assume_yes: bool, max_combos: int = DEFAULT_MAX_COMBOS
) -> None:
    if estimate.n_runs > max_combos and not assume_yes:
        raise ConfigError(
            f"sweep would run {estimate.n_runs} runs (> {max_combos}): {estimate.describe()}. "
            "Re-run with --yes if that is intended."
        )


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def score(results: Iterable[ComboResult], selection: Selection) -> list[ScoredResult]:
    scored: list[ScoredResult] = []
    for r in results:
        value, eligible, reason = selection.evaluate(r.metrics)
        scored.append(ScoredResult(r, value, eligible, reason))
    return scored


def pick_best_index(scored: Sequence[ScoredResult]) -> int | None:
    """Position (in `scored`) of the highest metric among ELIGIBLE combos; ties broken by
    the lower combo_index so the winner never depends on dict/thread ordering. None when
    nothing was eligible — a window that could not be calibrated is reported as such
    rather than traded blind."""
    candidates = [
        i for i, s in enumerate(scored) if s.eligible and s.metric_value is not None
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda i: (-float(scored[i].metric_value or 0.0), scored[i].result.combo_index),
    )


def distribution(scored: Sequence[ScoredResult]) -> dict[str, Any]:
    """Spread of the IS metric over ALL combos, not just the winner (plan 11 §2): if the
    winner barely beats the median, the "best" parameter set is noise."""
    values = sorted(s.metric_value for s in scored if s.metric_value is not None)
    if not values:
        return {"n": 0, "n_defined": 0, "n_eligible": sum(1 for s in scored if s.eligible)}
    quantiles = statistics.quantiles(values, n=4) if len(values) >= 2 else [values[0]] * 3
    return {
        "n": len(scored),
        "n_defined": len(values),
        "n_eligible": sum(1 for s in scored if s.eligible),
        "min": values[0],
        "p25": quantiles[0],
        "median": statistics.median(values),
        "p75": quantiles[2],
        "max": values[-1],
        "mean": statistics.fmean(values),
    }


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------


class WorkerPool:
    """A process pool that outlives a single window.

    Each worker loads the dataset bundle ONCE in its initializer (a 100k-bar CSV takes
    seconds). Walk-forward runs one window after another, so a pool per window would pay
    that cost `n_windows x n_workers` times — minutes of pure re-reading on a real spec.
    """

    def __init__(self, db_path: str, ctx: SweepContext, workers: int) -> None:
        import multiprocessing as mp

        from bot.research import worker

        self._worker = worker
        self._tmp_root = Path(tempfile.mkdtemp(prefix="bot-sweep-"))
        payload = worker.InitPayload(
            db_path=db_path, spec=ctx.spec, base_config_json=ctx.base_config.model_dump_json()
        )
        self._pool = mp.get_context("spawn").Pool(
            processes=workers, initializer=worker.init, initargs=(payload,)
        )

    def run(
        self,
        conn: sqlite3.Connection,
        window: SlicedWindow,
        combos: Sequence[dict[str, Any]],
        note: str,
    ) -> Iterator[ComboResult]:
        tasks = [
            self._worker.Task(
                combo_index=i,
                params=params,
                window_from=window.cursor.isoformat(),
                window_to=window.end.isoformat(),
                note=note,
                tmp_db=str(self._tmp_root / f"{note}-{i:05d}.db".replace(":", "_")),
            )
            for i, params in enumerate(combos)
        ]
        # imap (ORDERED, not imap_unordered): merging in combo order is what makes the
        # parallel run byte-identical to the sequential one down to the run ids.
        for outcome in self._pool.imap(self._worker.execute, tasks):
            run_id, cv_id = merge_single_run(conn, outcome.tmp_db)
            Path(outcome.tmp_db).unlink(missing_ok=True)
            yield ComboResult(
                combo_index=outcome.combo_index,
                params=outcome.params,
                run_id=run_id,
                config_version_id=cv_id,
                metrics=outcome.metrics,
                decision_hash=outcome.decision_hash,
                n_bars=outcome.n_bars,
            )

    def close(self) -> None:
        self._pool.terminate()
        self._pool.join()
        shutil.rmtree(self._tmp_root, ignore_errors=True)


def make_pool(db_path: str, ctx: SweepContext, workers: int, n_tasks: int) -> WorkerPool | None:
    if workers <= 1 or n_tasks <= 1:
        return None
    return WorkerPool(db_path, ctx, min(workers, n_tasks))


def execute_window(
    conn: sqlite3.Connection,
    ctx: SweepContext,
    window: SlicedWindow,
    combos: Sequence[dict[str, Any]],
    note: str,
    log: Log,
    pool: WorkerPool | None = None,
) -> list[ComboResult]:
    """Run every combo over one window. Without a pool, everything writes straight to
    `conn` in this process."""
    results: list[ComboResult] = []
    stream: Iterator[ComboResult]
    if pool is None:
        stream = (
            run_combo(conn, ctx, window, params, i, note) for i, params in enumerate(combos)
        )
    else:
        stream = pool.run(conn, window, combos, note)
    for result in stream:
        results.append(result)
        log(
            f"  [{result.combo_index + 1}/{len(combos)}] run #{result.run_id} "
            f"{_params_str(result.params)} -> trades={result.metrics['n_trades']} "
            f"pf={_fmt(result.metrics['profit_factor'])} "
            f"dd={_fmt(result.metrics['max_drawdown_pct'])}%"
        )
    return results


def persist_results(
    conn: sqlite3.Connection,
    sweep_id: int,
    window_index: int,
    phase: str,
    scored: Sequence[ScoredResult],
    window_from: str,
    window_to: str,
) -> list[int]:
    return [
        repo.insert_sweep_result(
            conn,
            sweep_id=sweep_id,
            window_index=window_index,
            phase=phase,
            combo_index=s.result.combo_index,
            params_json=json.dumps(s.result.params, sort_keys=True),
            run_id=s.result.run_id,
            config_version_id=s.result.config_version_id,
            metrics_json=json.dumps(s.result.metrics),
            metric_value=s.metric_value,
            eligible=s.eligible,
            ineligible_reason=s.ineligible_reason,
            window_from=window_from,
            window_to=window_to,
            decision_hash=s.result.decision_hash,
        )
        for s in scored
    ]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def run_sweep(
    db_path: str,
    spec: SweepSpec,
    workers: int = 1,
    assume_yes: bool = False,
    log: Log = print,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Run a plain (single-window) grid/random sweep. Returns the `sweep` row id."""
    owned = conn is None
    conn = conn if conn is not None else connect_and_migrate(db_path)
    try:
        base, base_cv_id = base_config_for(conn)
        ctx = build_sweep_context(conn, spec, base)
        start, end = full_range(ctx)
        window = slice_window(ctx, start, end)
        combos = spec.combos()

        est = estimate_cost(ctx, len(combos), [window])
        log(f"sweep '{spec.name}' — {est.describe()}")
        check_cost_guard(est, assume_yes)

        sweep_id = repo.create_sweep(
            conn,
            kind="grid",
            name=spec.name,
            dataset_id=spec.dataset_id,
            symbol=ctx.entry.symbol,
            timeframe=ctx.primary_tf,
            spec_json=spec.to_json(),
            base_config_version_id=base_cv_id,
            n_combos=len(combos),
        )
        pool = make_pool(db_path, ctx, workers, len(combos))
        try:
            results = execute_window(
                conn, ctx, window, combos, f"sweep:{spec.name}", log, pool
            )
            scored = score(results, spec.selection)
            ids = persist_results(
                conn, sweep_id, 0, "is", scored, start.isoformat(), end.isoformat()
            )
            best_idx = pick_best_index(scored)
            if best_idx is not None:
                best = scored[best_idx]
                repo.mark_sweep_result_selected(conn, ids[best_idx])
                log(
                    f"best: {_params_str(best.result.params)} "
                    f"{spec.selection.metric}={_fmt(best.metric_value)} (run #{best.result.run_id})"
                )
            else:
                log(
                    "KHÔNG tổ hợp nào đạt ràng buộc "
                    f"(min_trades={spec.selection.min_trades}, "
                    f"max_dd={spec.selection.max_drawdown_pct:g}%)"
                )
            repo.finish_sweep(conn, sweep_id, "DONE", len(results))
        except Exception as exc:
            repo.finish_sweep(conn, sweep_id, "FAILED", 0, str(exc))
            raise
        finally:
            if pool is not None:
                pool.close()
        return sweep_id
    finally:
        if owned:
            conn.close()


def _params_str(params: dict[str, Any]) -> str:
    return " ".join(f"{k.rsplit('.', 1)[-1]}={v}" for k, v in params.items())


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def stitched_equity(conn: sqlite3.Connection, run_ids: Sequence[int]) -> list[dict[str, Any]]:
    """Chain per-window OOS equity curves into one out-of-sample-only curve.

    Each OOS run starts from `starting_equity` again, so the curves are chained by
    RETURN, not by absolute level: window k+1's series is rescaled by the equity reached
    at the end of window k. The result is what compounding the walk-forward would have
    produced; it is not a claim that the windows were traded on one account."""
    out: list[dict[str, Any]] = []
    factor = 1.0
    starting: float | None = None
    for run_id in run_ids:
        row = conn.execute("SELECT starting_equity FROM run WHERE id=?", (run_id,)).fetchone()
        if row is None:
            continue
        run_start = float(row[0])
        if starting is None:
            starting = run_start
        points = conn.execute(
            "SELECT bar_ts_utc, equity FROM equity_point WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        for ts, equity in points:
            out.append(
                {"bar_ts_utc": ts, "equity": starting * factor * (float(equity) / run_start)}
            )
        if points:
            factor *= float(points[-1][1]) / run_start
    return out
