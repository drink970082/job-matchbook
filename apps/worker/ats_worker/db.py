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
    (source, external_id, company_slug, company_name, job_title, location, job_url,
     description, posted_at, pipeline_status, attempts, created_at)
VALUES
    (:source, :external_id, :company_slug, :company_name, :job_title, :location, :job_url,
     :description, :posted_at, 'new', 0, :created_at)
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
                "company_slug": p.get("company_slug"),
                "company_name": p["company_name"],
                "job_title": p["job_title"],
                "location": p.get("location"),
                "job_url": p["job_url"],
                "description": p["description"],
                # posted_at is date-only; fall back to the scrape day so it's never null.
                "posted_at": (p.get("posted_at") or now)[:10],
                "created_at": now,
            },
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


# --- watchlist ------------------------------------------------------------
# The watchlist is DB-owned (table `watched_companies`), so the web UI manages it
# and a future promotion step can append to it. The worker reads it here instead
# of config.yaml; config is seeded in once (see import_watchlist / run.py).

def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT source, slug, name FROM watched_companies ORDER BY id ASC"
    ).fetchall()
    return [{"source": r["source"], "slug": r["slug"], "name": r["name"]} for r in rows]


def count_watchlist(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM watched_companies").fetchone()[0]


def import_watchlist(conn: sqlite3.Connection, companies, *, now: str) -> int:
    """Idempotently seed watched_companies (dedup on (source, slug)). Returns rows
    inserted. Used for the one-time migration of config.yaml `companies:`."""
    inserted = 0
    for c in companies:
        cur = conn.execute(
            "INSERT INTO watched_companies (source, slug, name, created_at) "
            "VALUES (:source, :slug, :name, :created_at) "
            "ON CONFLICT(source, slug) DO NOTHING",
            {"source": c["source"], "slug": c["slug"], "name": c["name"], "created_at": now},
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


# --- feed bookkeeping -----------------------------------------------------

def record_unresolved(conn: sqlite3.Connection, *, feed: str, url: str,
                      company_name: str, job_title: str, host: str, reason: str,
                      now: str) -> None:
    """Record a feed listing whose URL couldn't be mapped to a supported board.
    Upsert on `url` so repeated passes refresh `updated_at` instead of piling up.
    """
    conn.execute(
        "INSERT INTO feed_unresolved "
        "(feed, url, company_name, job_title, host, reason, created_at) "
        "VALUES (:feed, :url, :company_name, :job_title, :host, :reason, :now) "
        "ON CONFLICT(url) DO UPDATE SET updated_at=:now, reason=:reason, host=:host",
        {"feed": feed, "url": url, "company_name": company_name,
         "job_title": job_title, "host": host, "reason": reason, "now": now},
    )
    conn.commit()


def existing_external_ids(conn: sqlite3.Connection, source: str, ids) -> set[str]:
    """The subset of `ids` already present for `source` — lets run_feed skip a
    board fetch when every surfaced posting is already ingested."""
    ids = list(ids)
    if not ids:
        return set()
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT external_id FROM job_postings WHERE source=? AND external_id IN ({placeholders})",
        [source, *ids],
    ).fetchall()
    return {r["external_id"] for r in rows}


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


def save_score(conn, posting_id: int, *, score: int, score_detail, now: str,
               status: str = "scored") -> None:
    # status is normally 'scored'; the scorer can route a disqualified posting
    # straight to 'discarded' (see pipeline.run_score) while still keeping its
    # score + reason for the UI.
    _update(conn, posting_id, {
        "score": score,
        "score_detail": json.dumps(score_detail),
        "pipeline_status": status,
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


def mark_failed(conn, posting_id: int, *, error: str, now: str) -> None:
    # increment attempts atomically; keep it in one statement.
    conn.execute(
        "UPDATE job_postings SET pipeline_status='failed', pipeline_error=?, "
        "attempts=attempts+1, updated_at=? WHERE id=?",
        (error, now, posting_id),
    )
    conn.commit()
