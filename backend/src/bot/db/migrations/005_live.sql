-- Plan 07: live paper trading.
--
-- `run.mode` separates a live run from a backtest run (a live DB is a separate file,
-- but the column is what LiveRunner uses to FIND the run to resume after a restart).
-- `run.stop_requested` is the only channel by which the API may influence a live run
-- (plan 07 §2: the API never writes to a live run otherwise).
-- `trade.timeframe` is captured at open time so the hold rules (user decision
-- 2026-07-18) stay auditable even if the config changes later.
-- `strategy_state` persists the retest state machine + the in-flight trade so a restart
-- resumes exactly where it stopped (chosen over re-running decide(), which can drift).

ALTER TABLE run ADD COLUMN mode TEXT NOT NULL DEFAULT 'backtest';
ALTER TABLE run ADD COLUMN stop_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE trade ADD COLUMN timeframe TEXT;

CREATE TABLE IF NOT EXISTS strategy_state (
    run_id          INTEGER NOT NULL,
    symbol          TEXT    NOT NULL,
    state_json      TEXT    NOT NULL,
    updated_at_utc  TEXT    NOT NULL,
    PRIMARY KEY (run_id, symbol),
    FOREIGN KEY (run_id) REFERENCES run(id)
);

CREATE TABLE IF NOT EXISTS live_status (
    run_id           INTEGER PRIMARY KEY,
    feed_state       TEXT    NOT NULL DEFAULT 'ok',   -- ok | degraded
    last_bar_ts_utc  TEXT,
    last_poll_ts_utc TEXT,
    started_at_utc   TEXT,
    detail           TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (run_id) REFERENCES run(id)
);

-- Idempotency lookup: "has this (run, symbol, bar_ts) already been decided?".
CREATE INDEX IF NOT EXISTS idx_decision_run_symbol_bar
    ON decision(run_id, symbol, bar_ts_utc);
