-- Phase 3 schema. OHLC data does NOT live here (CSV/parquet under data/generated/<id>/) --
-- this DB holds runtime state + audit log only. WAL + foreign_keys are set by connection.py.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);

-- Immutable versioned config snapshots (plan: PATCH -> deep-merge -> validate -> NEW
-- version -> activate). Never mutated in place.
CREATE TABLE IF NOT EXISTS config_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_config_version_active ON config_version(is_active);

CREATE TABLE IF NOT EXISTS dataset (
    id TEXT PRIMARY KEY,
    spec_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL REFERENCES dataset(id),
    config_version_id INTEGER NOT NULL REFERENCES config_version(id),
    symbol TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CREATED',
    starting_equity REAL NOT NULL,
    created_at_utc TEXT NOT NULL
);

-- Cache only (plan: derived counters are the source of truth; this table must always
-- equal COUNT(*)-derived values from `trade` -- see test_counters_consistent.py).
CREATE TABLE IF NOT EXISTS account_state (
    run_id INTEGER PRIMARY KEY REFERENCES run(id),
    equity REAL NOT NULL,
    balance REAL NOT NULL,
    open_trades INTEGER NOT NULL DEFAULT 0,
    daily_loss_count INTEGER NOT NULL DEFAULT 0,
    consecutive_wins INTEGER NOT NULL DEFAULT 0,
    consecutive_losses INTEGER NOT NULL DEFAULT 0,
    current_trading_day TEXT,
    risk_multiplier REAL NOT NULL DEFAULT 1.0,
    bot_enabled INTEGER NOT NULL DEFAULT 1,
    blocked_reason TEXT
);

CREATE TABLE IF NOT EXISTS trade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES run(id),
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    status TEXT NOT NULL,               -- PENDING|OPEN|CLOSED|CANCELLED
    entry_price REAL,
    sl_price REAL,
    tp1_price REAL,
    tp2_price REAL,
    lot_size REAL,
    opened_at_utc TEXT,
    closed_at_utc TEXT,
    trading_day TEXT,                   -- C4: trading day at CLOSE time
    result TEXT,                        -- WIN|LOSS|BREAKEVEN (F2 three-way)
    pnl_amount REAL,
    pnl_r REAL,
    decision_id INTEGER REFERENCES decision(id)
);
CREATE INDEX IF NOT EXISTS idx_trade_run_status ON trade(run_id, status);
CREATE INDEX IF NOT EXISTS idx_trade_run_trading_day ON trade(run_id, trading_day);
CREATE INDEX IF NOT EXISTS idx_trade_run_closed_at ON trade(run_id, closed_at_utc);

CREATE TABLE IF NOT EXISTS trade_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trade(id),
    event_type TEXT NOT NULL,           -- FILLED|GAP_CANCELLED|TP1_HIT|SL_TO_BREAKEVEN|...
    ts_utc TEXT NOT NULL,
    price REAL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_trade_event_trade ON trade_event(trade_id);

CREATE TABLE IF NOT EXISTS decision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES run(id),
    bar_ts_utc TEXT NOT NULL,
    reason TEXT NOT NULL,               -- §8 vocabulary verbatim
    stage TEXT NOT NULL,
    detail TEXT,
    strategy TEXT,
    direction TEXT,
    trade_id INTEGER REFERENCES trade(id)
);
CREATE INDEX IF NOT EXISTS idx_decision_run_bar ON decision(run_id, bar_ts_utc);
CREATE INDEX IF NOT EXISTS idx_decision_run_reason ON decision(run_id, reason);

CREATE TABLE IF NOT EXISTS decision_filter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decision(id),
    filter_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    evaluated INTEGER NOT NULL,
    passed INTEGER,                     -- NULL = disabled/warmup/informational
    blocking INTEGER NOT NULL DEFAULT 0,
    values_json TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_decision_filter_decision ON decision_filter(decision_id);

-- Breakout-retest state machine, persisted per run+symbol (Phase 1/2: one symbol).
CREATE TABLE IF NOT EXISTS breakout_state (
    run_id INTEGER PRIMARY KEY REFERENCES run(id),
    status TEXT NOT NULL DEFAULT 'NONE',
    direction TEXT,
    range_high REAL,
    range_low REAL,
    breakout_bar_ts_utc TEXT,
    bars_waited INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS equity_point (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES run(id),
    bar_ts_utc TEXT NOT NULL,
    equity REAL NOT NULL,
    balance REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_equity_point_run_bar ON equity_point(run_id, bar_ts_utc);
