"""Database connections and schema for local.db."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "jobs.db"
LOCAL_DB_PATH = Path(__file__).parent.parent / "local.db"

LOCAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exclusions (
    job_id TEXT PRIMARY KEY,
    reason TEXT,
    excluded_at TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    """Open a connection to jobs.db with WAL mode and row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_local_db() -> None:
    """Ensure local.db tables exist (for ATTACH use cases)."""
    get_local_connection().close()


def get_local_connection() -> sqlite3.Connection:
    """Open a connection to local.db.

    Uses a 10s busy timeout to handle concurrent writers.
    """
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(LOCAL_SCHEMA)
    return conn


@contextmanager
def attached_local(conn: sqlite3.Connection):
    """Context manager: ATTACH local.db, yield, DETACH."""
    path = str(LOCAL_DB_PATH).replace("'", "''")
    conn.execute(f"ATTACH DATABASE '{path}' AS local")
    try:
        yield
    finally:
        conn.execute("DETACH DATABASE local")
