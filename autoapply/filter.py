"""Rebuild the candidates table from jobs using filter.sql."""

from __future__ import annotations

import sys
from pathlib import Path

from .db import (
    DB_PATH,
    attached_local,
    get_connection,
    init_db,
    init_local_db,
)

FILTER_PATH = Path(__file__).parent.parent / "filter.sql"

SELECT_COLS = """
    j.job_id, j.ats, j.title, j.company_name, j.description_text,
    j.location_raw, j.city, j.state, j.country, j.is_remote,
    j.department, j.employment_type, j.experience_level,
    j.min_salary, j.max_salary, j.apply_url, j.first_seen_at
"""


def rebuild_candidates(
    db_path: Path | None = None,
    filter_path: Path | None = None,
    local_db_path: Path | None = None,
) -> int:
    """Rebuild the candidates table using the WHERE clause from filter.sql.

    Returns the number of candidates.
    """
    fp = filter_path or FILTER_PATH
    if not fp.exists():
        raise FileNotFoundError(f"{fp} not found.")

    where = fp.read_text().strip()
    if not where:
        raise ValueError("filter.sql is empty.")

    path = db_path or DB_PATH
    init_db(path)
    init_local_db(local_db_path)

    conn = get_connection(path)
    try:
        with attached_local(conn, local_db_path):
            conn.execute("DROP TABLE IF EXISTS candidates_new")
            conn.execute(f"""
                CREATE TABLE candidates_new AS
                SELECT {SELECT_COLS}
                FROM jobs j
                LEFT JOIN local.applications a ON j.job_id = a.job_id
                LEFT JOIN local.exclusions e ON j.job_id = e.job_id
                WHERE a.job_id IS NULL AND e.job_id IS NULL
                AND ({where})
            """)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_new_jid ON candidates_new(job_id)"
            )

            count = conn.execute("SELECT COUNT(*) FROM candidates_new").fetchone()[0]
            conn.execute("DROP TABLE IF EXISTS candidates")
            conn.execute("ALTER TABLE candidates_new RENAME TO candidates")
            conn.commit()
    finally:
        conn.close()

    print(f"Rebuilt candidates table: {count} rows")
    return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rebuild candidates table from filter.sql")
    parser.add_argument("--db", type=Path, default=None, help="Path to jobs.db")
    parser.add_argument("--filter", type=Path, default=None, help="Path to filter.sql")
    args = parser.parse_args()

    try:
        rebuild_candidates(db_path=args.db, filter_path=args.filter)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
