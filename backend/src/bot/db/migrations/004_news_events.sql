-- Plan 06: real data for the `news` filter (blackout windows). Events are append-only
-- (dedupe on insert, never mutated) so a run's snapshot (`run.news_snapshot_max_id`) can
-- freeze the event set it sees at creation time -- importing a new file later never
-- changes an existing run's decision stream.
CREATE TABLE IF NOT EXISTS news_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    currency TEXT NOT NULL,
    impact TEXT NOT NULL,               -- low|medium|high
    title TEXT NOT NULL,
    source_file_sha256 TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_news_event_dedupe ON news_event(ts_utc, currency, title);
CREATE INDEX IF NOT EXISTS idx_news_event_ts ON news_event(ts_utc);

ALTER TABLE run ADD COLUMN news_snapshot_max_id INTEGER NOT NULL DEFAULT 0;
