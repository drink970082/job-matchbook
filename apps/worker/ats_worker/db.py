"""SQLite access for the worker.

Prisma OWNS the schema — this module never issues DDL. It only opens a
connection with the right pragmas for safe co-writing with the Next.js app
(WAL + busy_timeout), and reads/writes rows of the `job_postings` table.

All mutators take an explicit `now` (ISO-8601 string) so timestamps match the
String columns Prisma uses and so callers/tests stay deterministic.
"""
from __future__ import annotations

import json
import sqlite3


def connect(path: str, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Open a connection configured for cross-process co-writing.

    WAL lets the Next.js reader and this writer proceed concurrently;
    busy_timeout makes brief lock contention block-and-retry instead of
    raising `database is locked`.
    """
    conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# --- ingest ---------------------------------------------------------------

_INSERT = """
INSERT INTO job_postings
    (source, external_id, company_name, job_title, location, job_url,
     description, pipeline_status, attempts, created_at)
VALUES
    (:source, :external_id, :company_name, :job_title, :location, :job_url,
     :description, 'new', 0, :created_at)
ON CONFLICT(source, external_id) DO NOTHING
"""


def upsert_postings(conn: sqlite3.Connection, postings, *, now: str) -> int:
    """Insert new postings, ignoring any whose (source, external_id) already
    exists. Returns the number of rows actually inserted. Existing rows are
    left untouched (we never clobber a posting mid-pipeline).
    """
    inserted = 0
    for p in postings:
        cur = conn.execute(
            _INSERT,
            {
                "source": p["source"],
                "external_id": p["external_id"],
                "company_name": p["company_name"],
                "job_title": p["job_title"],
                "location": p.get("location"),
                "job_url": p["job_url"],
                "description": p["description"],
                "created_at": now,
            },
        )
        inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    return inserted


# --- queries --------------------------------------------------------------

def get_by_status(conn: sqlite3.Connection, status: str, *, min_score: int | None = None,
                  limit: int | None = None):
    sql = "SELECT * FROM job_postings WHERE pipeline_status=?"
    params: list = [status]
    if min_score is not None:
        sql += " AND score >= ?"
        params.append(min_score)
    sql += " ORDER BY score DESC, id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


# --- state transitions ----------------------------------------------------

def _update(conn: sqlite3.Connection, posting_id: int, sets: dict) -> None:
    cols = ", ".join(f"{k}=:{k}" for k in sets)
    params = {**sets, "id": posting_id}
    conn.execute(f"UPDATE job_postings SET {cols} WHERE id=:id", params)
    conn.commit()


def save_score(conn, posting_id: int, *, score: int, score_detail, now: str) -> None:
    _update(conn, posting_id, {
        "score": score,
        "score_detail": json.dumps(score_detail),
        "pipeline_status": "scored",
        "updated_at": now,
    })


def save_resume(conn, posting_id: int, *, resume_tex: str, resume_path: str,
                resume_pages: int, now: str) -> None:
    _update(conn, posting_id, {
        "resume_tex": resume_tex,
        "resume_path": resume_path,
        "resume_pages": resume_pages,
        "pipeline_status": "tailored",
        "updated_at": now,
    })


def mark_notified(conn, posting_id: int, *, now: str) -> None:
    _update(conn, posting_id, {"pipeline_status": "notified", "updated_at": now})


def mark_applied(conn, posting_id: int, *, application_id: int, now: str) -> None:
    _update(conn, posting_id, {
        "pipeline_status": "applied",
        "application_id": application_id,
        "updated_at": now,
    })


def mark_failed(conn, posting_id: int, *, error: str, now: str) -> None:
    # increment attempts atomically; keep it in one statement.
    conn.execute(
        "UPDATE job_postings SET pipeline_status='failed', pipeline_error=?, "
        "attempts=attempts+1, updated_at=? WHERE id=?",
        (error, now, posting_id),
    )
    conn.commit()


def discard(conn, posting_id: int, *, now: str) -> None:
    _update(conn, posting_id, {"pipeline_status": "discarded", "updated_at": now})
