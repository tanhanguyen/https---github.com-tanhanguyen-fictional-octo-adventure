"""SQLite connection + migration runner. WAL mode + foreign_keys=ON."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, "
        "applied_at_utc TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}

    for path in sorted(_migrations_dir().glob("*.sql")):
        version = int(path.stem.split("_", 1)[0])
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at_utc) VALUES (?, datetime('now'))",
            (version,),
        )
        conn.commit()


def connect_and_migrate(db_path: str) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn)
    return conn
