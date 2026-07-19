-- Plan 02: real CSV datasets alongside synthetic. Existing rows default kind='synthetic'.
ALTER TABLE dataset ADD COLUMN kind TEXT NOT NULL DEFAULT 'synthetic';
ALTER TABLE dataset ADD COLUMN source_path TEXT;
ALTER TABLE dataset ADD COLUMN file_sha256 TEXT;
ALTER TABLE dataset ADD COLUMN symbol TEXT;
ALTER TABLE dataset ADD COLUMN native_tf TEXT;
ALTER TABLE dataset ADD COLUMN start_ts TEXT;
ALTER TABLE dataset ADD COLUMN end_ts TEXT;
ALTER TABLE dataset ADD COLUMN bar_count INTEGER;
ALTER TABLE dataset ADD COLUMN gap_count INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_dataset_file_sha256 ON dataset(file_sha256);
