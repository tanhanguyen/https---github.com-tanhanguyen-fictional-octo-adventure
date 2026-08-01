"""Walk-forward + overfit report (plan 11 §2).

Per window: sweep the grid on IS -> pick the winner by ❓2 -> run it EXACTLY ONCE on OOS.
The headline result is the concatenated OOS curve; the honest result is the overfit
report next to it:

- per-window `IS metric vs OOS metric` and the degradation between them,
- the distribution of the IS metric across **every** combo tried, not just the winner
  (a winner a hair above the median is noise wearing a crown),
- the total number of combos tried — the denominator of the selection bias.

Deliberately nothing deeper: deflated Sharpe and friends are out of scope (plan 11).

No-leak: windows come from `research.windows`, where OOS starts exactly where IS ends
and every feed is sliced `[warmup, window_end)` with the cursor at the window start.
A combo therefore never sees a bar from the window it is being validated on.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from bot.core.errors import ConfigError
from bot.db import repositories as repo
from bot.db.connection import connect_and_migrate
from bot.research.execute import (
    ComboResult,
    SweepContext,
    build_sweep_context,
    full_range,
    slice_window,
)
from bot.research.spec import SweepSpec
from bot.research.sweep import (
    Log,
    WorkerPool,
    base_config_for,
    check_cost_guard,
    distribution,
    estimate_cost,
    execute_window,
    make_pool,
    persist_results,
    pick_best_index,
    score,
)
from bot.research.windows import Window, build_windows


def degradation(is_metric: float | None, oos_metric: float | None) -> float | None:
    """(OOS - IS) / |IS|. -1.0 means the OOS result gave back the whole IS edge; a value
    below -1 means OOS was worse than flat relative to IS. None when either side is
    undefined or IS is 0 (no meaningful ratio)."""
    if is_metric is None or oos_metric is None or is_metric == 0:
        return None
    return (oos_metric - is_metric) / abs(is_metric)


def run_walkforward(
    db_path: str,
    spec: SweepSpec,
    workers: int = 1,
    assume_yes: bool = False,
    log: Log = print,
    conn: sqlite3.Connection | None = None,
) -> int:
    if spec.walkforward is None:
        raise ConfigError("walk-forward needs a `walkforward:` block in the spec")
    wf = spec.walkforward

    owned = conn is None
    conn = conn if conn is not None else connect_and_migrate(db_path)
    try:
        base, base_cv_id = base_config_for(conn)
        ctx = build_sweep_context(conn, spec, base)
        data_from, data_to = full_range(ctx)
        windows = build_windows(
            data_from, data_to, wf.is_months, wf.oos_months, wf.step_months
        )
        combos = spec.combos()

        # +1 run per window for the OOS pass; the estimate uses the IS window (the
        # longer of the two) for every run, so it errs on the pessimistic side.
        slices = [slice_window(ctx, w.is_from, w.is_to) for w in windows]
        est = estimate_cost(ctx, len(combos) + 1, slices)
        log(
            f"walk-forward '{spec.name}' — {len(windows)} cửa sổ "
            f"(IS {wf.is_months}m / OOS {wf.oos_months}m / trượt {wf.step_months}m), "
            f"{est.describe()}"
        )
        check_cost_guard(est, assume_yes)

        sweep_id = repo.create_sweep(
            conn,
            kind="walkforward",
            name=spec.name,
            dataset_id=spec.dataset_id,
            symbol=ctx.entry.symbol,
            timeframe=ctx.primary_tf,
            spec_json=spec.to_json(),
            base_config_version_id=base_cv_id,
            n_combos=len(combos),
        )
        n_runs = 0
        # ONE pool for the whole walk-forward: each worker loads the dataset bundle in
        # its initializer, and re-paying that per window would cost minutes on a real spec.
        pool = make_pool(db_path, ctx, workers, len(combos))
        try:
            for window in windows:
                n_runs += _one_window(conn, ctx, sweep_id, window, combos, pool, log)
            repo.finish_sweep(conn, sweep_id, "DONE", n_runs)
        except Exception as exc:
            repo.finish_sweep(conn, sweep_id, "FAILED", n_runs, str(exc))
            raise
        finally:
            if pool is not None:
                pool.close()
        return sweep_id
    finally:
        if owned:
            conn.close()


def _one_window(
    conn: sqlite3.Connection,
    ctx: SweepContext,
    sweep_id: int,
    window: Window,
    combos: list[dict[str, Any]],
    pool: WorkerPool | None,
    log: Log,
) -> int:
    spec: SweepSpec = ctx.spec
    log(
        f"window {window.index}: IS {window.is_from.date()}..{window.is_to.date()} | "
        f"OOS {window.oos_from.date()}..{window.oos_to.date()}"
    )
    is_slice = slice_window(ctx, window.is_from, window.is_to)
    is_results = execute_window(
        conn, ctx, is_slice, combos, f"wf-{spec.name}-w{window.index}-is", log, pool
    )
    scored = score(is_results, spec.selection)
    is_ids = persist_results(
        conn,
        sweep_id,
        window.index,
        "is",
        scored,
        window.is_from.isoformat(),
        window.is_to.isoformat(),
    )
    dist = distribution(scored)
    best_idx = pick_best_index(scored)

    oos_result: ComboResult | None = None
    oos_metric: float | None = None
    if best_idx is None:
        log(
            f"  -> không tổ hợp nào đạt ràng buộc trên IS "
            f"(eligible 0/{len(scored)}); BỎ QUA OOS của cửa sổ này"
        )
        selected_params_json = None
        is_metric = None
        is_run_id = None
    else:
        best = scored[best_idx]
        repo.mark_sweep_result_selected(conn, is_ids[best_idx])
        selected_params_json = json.dumps(best.result.params, sort_keys=True)
        is_metric = best.metric_value
        is_run_id = best.result.run_id

        oos_slice = slice_window(ctx, window.oos_from, window.oos_to)
        # No pool: one run, and a round-trip through a worker + merge would cost more
        # than it saves.
        oos_results = execute_window(
            conn,
            ctx,
            oos_slice,
            [best.result.params],
            f"wf-{spec.name}-w{window.index}-oos",
            log,
        )
        oos_result = oos_results[0]
        oos_scored = score(oos_results, spec.selection)
        persist_results(
            conn,
            sweep_id,
            window.index,
            "oos",
            oos_scored,
            window.oos_from.isoformat(),
            window.oos_to.isoformat(),
        )
        # The OOS metric is reported RAW: the min-trades / max-dd constraints are a
        # selection rule for IS, not a filter on what out-of-sample actually did.
        raw = oos_result.metrics.get(spec.selection.metric)
        oos_metric = None if raw is None else float(raw)
        log(
            f"  -> chọn {best.result.params} | IS {spec.selection.metric}="
            f"{is_metric:.3f} vs OOS={_fmt(oos_metric)} "
            f"(OOS trades={oos_result.metrics['n_trades']})"
        )

    repo.insert_sweep_window(
        conn,
        sweep_id=sweep_id,
        window_index=window.index,
        is_from=window.is_from.isoformat(),
        is_to=window.is_to.isoformat(),
        oos_from=window.oos_from.isoformat(),
        oos_to=window.oos_to.isoformat(),
        n_combos=len(scored),
        n_eligible=int(dist.get("n_eligible", 0)),
        selected_params_json=selected_params_json,
        is_metric=is_metric,
        oos_metric=oos_metric,
        degradation=degradation(is_metric, oos_metric),
        is_run_id=is_run_id,
        oos_run_id=None if oos_result is None else oos_result.run_id,
        distribution_json=json.dumps(dist),
    )
    return len(is_results) + (1 if oos_result is not None else 0)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"
