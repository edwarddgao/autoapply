"""Query local job database for application candidates."""

from __future__ import annotations

from pathlib import Path

from .db import attached_local, get_connection, get_local_connection


def count_candidates(db_path: Path | None = None, local_db_path: Path | None = None) -> int:
    """Return count of unapplied candidate jobs."""
    conn = get_connection(db_path)
    try:
        with attached_local(conn, local_db_path):
            return conn.execute("""
                SELECT COUNT(*) FROM candidates c
                LEFT JOIN local.applications a ON c.job_id = a.job_id
                LEFT JOIN local.exclusions e ON c.job_id = e.job_id
                WHERE a.job_id IS NULL AND e.job_id IS NULL
            """).fetchone()[0]
    finally:
        conn.close()


def find_candidates(limit: int = 100, db_path: Path | None = None, local_db_path: Path | None = None) -> list[dict]:
    """Return unapplied candidate jobs, newest first.

    Checks local.db at query time to exclude jobs applied/excluded since last filter rebuild.
    """
    conn = get_connection(db_path)
    try:
        with attached_local(conn, local_db_path):
            rows = conn.execute(
                """
                SELECT c.job_id, c.ats, c.title, c.company_name, c.apply_url, c.max_salary, c.first_seen_at
                FROM candidates c
                LEFT JOIN local.applications a ON c.job_id = a.job_id
                LEFT JOIN local.exclusions e ON c.job_id = e.job_id
                WHERE a.job_id IS NULL AND e.job_id IS NULL
                ORDER BY c.first_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mark_applied(job_id: str, local_db_path: Path | None = None) -> None:
    """Record a successful application."""
    conn = get_local_connection(local_db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO applications (job_id, applied_at) VALUES (?, datetime('now'))",
            (job_id,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_excluded(
    job_id: str,
    reason: str,
    company: str = "",
    title: str = "",
    url: str = "",
    local_db_path: Path | None = None,
) -> None:
    """Record a job that should not be retried."""
    conn = get_local_connection(local_db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO exclusions "
            "(job_id, reason, company, title, url, excluded_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (job_id, reason, company, title, url),
        )
        conn.commit()
    finally:
        conn.close()


def delete_job(job_id: str, db_path: Path | None = None, local_db_path: Path | None = None) -> None:
    """Remove a dead/invalid job from all tables."""
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM candidates WHERE job_id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()

    lconn = get_local_connection(local_db_path)
    try:
        lconn.execute("DELETE FROM exclusions WHERE job_id = ?", (job_id,))
        lconn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
        lconn.commit()
    finally:
        lconn.close()


def list_excluded(local_db_path: Path | None = None) -> list[dict]:
    """Return all excluded jobs."""
    conn = get_local_connection(local_db_path)
    try:
        rows = conn.execute("SELECT * FROM exclusions ORDER BY excluded_at DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    total = count_candidates()
    candidates = find_candidates(limit=20)
    print(f"Candidates: {total} total (showing top {len(candidates)})\n")
    for i, c in enumerate(candidates, 1):
        sal = f"${int(c['max_salary']/1000)}k" if c["max_salary"] else ""
        print(f"{i:>3}. {c['company_name']:<28} {c['title'][:45]:<45} {sal:>6}")
