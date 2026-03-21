"""Query local job database for application candidates."""

from __future__ import annotations

from .db import attached_local, get_connection, get_local_connection


def find_candidates() -> list[dict]:
    """Return unapplied candidate jobs, newest first."""
    conn = get_connection()
    try:
        with attached_local(conn):
            rows = conn.execute(
                """
                SELECT c.job_id, c.ats, c.title, c.company_name, c.apply_url, c.max_salary, c.first_seen_at
                FROM candidates c
                LEFT JOIN local.applications a ON c.job_id = a.job_id
                LEFT JOIN local.exclusions e ON c.job_id = e.job_id
                WHERE a.job_id IS NULL AND e.job_id IS NULL
                ORDER BY c.first_seen_at DESC
                """,
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mark_applied(job_id: str) -> None:
    """Record a successful application."""
    conn = get_local_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO applications (job_id, applied_at) VALUES (?, datetime('now'))",
            (job_id,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_excluded(job_id: str, reason: str) -> None:
    """Record a job that should not be retried."""
    conn = get_local_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO exclusions (job_id, reason, excluded_at) "
            "VALUES (?, ?, datetime('now'))",
            (job_id, reason),
        )
        conn.commit()
    finally:
        conn.close()
