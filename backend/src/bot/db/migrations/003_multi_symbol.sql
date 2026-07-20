-- Plan 04: multi-symbol portfolio. decision needs to know which symbol it's about;
-- run needs to record its full symbol list (run.symbol keeps working as a
-- comma-joined display string for backward compatibility, not the source of truth);
-- run_symbol_dataset maps each symbol in a run to its own (child-seeded or CSV) dataset.
ALTER TABLE decision ADD COLUMN symbol TEXT;
CREATE INDEX IF NOT EXISTS idx_decision_run_symbol ON decision(run_id, symbol);

ALTER TABLE run ADD COLUMN symbols_json TEXT;

CREATE TABLE IF NOT EXISTS run_symbol_dataset (
    run_id INTEGER NOT NULL REFERENCES run(id),
    symbol TEXT NOT NULL,
    dataset_id TEXT NOT NULL REFERENCES dataset(id),
    PRIMARY KEY (run_id, symbol)
);
