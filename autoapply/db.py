"""Database schema, initialization, and helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "jobs.db"
LOCAL_DB_PATH = Path(__file__).parent.parent / "local.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,  -- "{ats}:{slug}"
    slug TEXT NOT NULL,
    ats TEXT NOT NULL,
    name TEXT,
    last_probed_at INTEGER,
    is_dead INTEGER DEFAULT 0,
    UNIQUE(ats, slug)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,       -- "{ats}:{native_id}"
    ats TEXT NOT NULL,
    company_id TEXT NOT NULL,
    ats_job_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company_name TEXT,
    description_text TEXT,
    location_raw TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    is_remote INTEGER DEFAULT 0,
    department TEXT,
    employment_type TEXT,
    experience_level TEXT,
    min_salary REAL,
    max_salary REAL,
    apply_url TEXT NOT NULL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    content_hash TEXT,
    UNIQUE(ats, ats_job_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_ats ON jobs(ats);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_department ON jobs(department);

-- candidates table is created by filter.py (CREATE TABLE AS SELECT from jobs).
-- Do not define it here — filter.py is the schema authority.

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

LOCAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exclusions (
    job_id TEXT PRIMARY KEY,
    reason TEXT,
    company TEXT,
    title TEXT,
    url TEXT,
    excluded_at TEXT NOT NULL
);

"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL mode and row factory."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_local_schema_created: set[str] = set()


def get_local_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection to local.db (applications/exclusions).

    Creates tables on first connection per path. Uses a 10s busy timeout
    to handle concurrent writers without 'database is locked' errors.
    """
    path = db_path or LOCAL_DB_PATH
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    key = str(path)
    if key not in _local_schema_created:
        conn.executescript(LOCAL_SCHEMA)
        _local_schema_created.add(key)
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if they don't exist."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.close()


_local_initialized = False


def init_local_db(db_path: Path | None = None) -> None:
    """Create local.db tables and migrate from jobs.db if needed.

    Safe to call multiple times — migration only runs once per process
    and only when local.db is brand new.
    """
    global _local_initialized
    if _local_initialized:
        return
    _local_initialized = True

    path = db_path or LOCAL_DB_PATH
    is_new = not path.exists()
    conn = get_local_connection(db_path)

    # Migrate from jobs.db on first creation only
    if is_new and DB_PATH.exists():
        try:
            conn.execute(f"ATTACH DATABASE '{DB_PATH}' AS jobs")
            conn.execute(
                "INSERT OR IGNORE INTO applications SELECT * FROM jobs.applications"
            )
            conn.execute(
                "INSERT OR IGNORE INTO exclusions SELECT * FROM jobs.exclusions"
            )
            conn.commit()
            conn.execute("DETACH DATABASE jobs")
        except sqlite3.OperationalError:
            pass  # jobs.db doesn't have these tables yet

    conn.close()


def attach_local(conn: sqlite3.Connection, db_path: Path | None = None) -> None:
    """ATTACH local.db to an existing connection with proper escaping."""
    path = str(db_path or LOCAL_DB_PATH).replace("'", "''")
    conn.execute(f"ATTACH DATABASE '{path}' AS local")


@contextmanager
def attached_local(conn: sqlite3.Connection, db_path: Path | None = None):
    """Context manager: ATTACH local.db, yield, DETACH."""
    attach_local(conn, db_path)
    try:
        yield
    finally:
        conn.execute("DETACH DATABASE local")

