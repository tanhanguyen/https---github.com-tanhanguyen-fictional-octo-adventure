-- Plan 11: parameter sweeps + walk-forward. A sweep NEVER stores its own copy of a
-- result: every row points at a real `run` in the registry (plan 03), so clicking a
-- sweep row lands on that run's Report page with its decisions/trades/equity intact.
-- `metrics_json` is a denormalised cache of that run's RunReport, kept so the sweep
-- table can be sorted/filtered without recomputing 100+ reports per page load.

CREATE TABLE IF NOT EXISTS sweep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'grid',          -- grid | walkforward
    name TEXT NOT NULL DEFAULT '',
    dataset_id TEXT NOT NULL REFERENCES dataset(id),
    symbol TEXT NOT NULL DEFAULT '',
    timeframe TEXT NOT NULL DEFAULT '',
    spec_json TEXT NOT NULL,                    -- the resolved SweepSpec (axes, selection, window)
    base_config_version_id INTEGER REFERENCES config_version(id),
    status TEXT NOT NULL DEFAULT 'RUNNING',     -- RUNNING | DONE | FAILED
    n_combos INTEGER NOT NULL DEFAULT 0,        -- combos per window (the selection-bias denominator)
    n_runs INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sweep_created ON sweep(created_at_utc DESC);

-- One row per (window, phase, combo) = one real run.
CREATE TABLE IF NOT EXISTS sweep_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_id INTEGER NOT NULL REFERENCES sweep(id),
    window_index INTEGER NOT NULL DEFAULT 0,    -- 0 for a plain grid sweep
    phase TEXT NOT NULL DEFAULT 'is',           -- is | oos
    combo_index INTEGER NOT NULL,
    params_json TEXT NOT NULL,                  -- {dotted.path: value} of THIS combo only
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version_id INTEGER NOT NULL REFERENCES config_version(id),
    metrics_json TEXT NOT NULL,
    metric_value REAL,                          -- the selection metric (NULL = undefined)
    eligible INTEGER NOT NULL DEFAULT 1,        -- passed the max_dd / min_trades constraints
    ineligible_reason TEXT NOT NULL DEFAULT '',
    selected INTEGER NOT NULL DEFAULT 0,        -- the IS winner of its window
    window_from TEXT NOT NULL DEFAULT '',
    window_to TEXT NOT NULL DEFAULT '',
    decision_hash TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sweep_result_sweep ON sweep_result(sweep_id, window_index, phase);

-- Walk-forward only: the IS-vs-OOS row the overfit report is built from.
CREATE TABLE IF NOT EXISTS sweep_window (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_id INTEGER NOT NULL REFERENCES sweep(id),
    window_index INTEGER NOT NULL,
    is_from TEXT NOT NULL,
    is_to TEXT NOT NULL,
    oos_from TEXT NOT NULL,
    oos_to TEXT NOT NULL,
    n_combos INTEGER NOT NULL DEFAULT 0,        -- combos tried on this window
    n_eligible INTEGER NOT NULL DEFAULT 0,      -- how many passed the constraints
    selected_params_json TEXT,                  -- NULL when no combo was eligible
    is_metric REAL,
    oos_metric REAL,
    degradation REAL,                           -- (oos - is) / |is|, NULL if either side is
    is_run_id INTEGER REFERENCES run(id),
    oos_run_id INTEGER REFERENCES run(id),
    distribution_json TEXT NOT NULL DEFAULT '{}'  -- IS metric spread over ALL combos, not just the winner
);
CREATE INDEX IF NOT EXISTS idx_sweep_window_sweep ON sweep_window(sweep_id, window_index);
