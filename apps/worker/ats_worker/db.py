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

from .config import RECIPE_SOURCES


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
        "SELECT source, slug, name, recipe FROM watched_companies ORDER BY id ASC"
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            recipe = json.loads(r["recipe"]) if r["recipe"] else None
        except json.JSONDecodeError:
            # One malformed recipe must not abort the whole read (the pass would then
            # fetch nothing). Only RECIPE_SOURCES (custom/browser) actually need a
            # recipe to fetch — skip those loudly; a platform row fetches fine
            # without one, so keep it with recipe=None instead of dropping it.
            if r["source"] in RECIPE_SOURCES:
                print(f"[watchlist] {r['source']}/{r['slug']}: skipping row with "
                      f"malformed recipe JSON")
                continue
            print(f"[watchlist] {r['source']}/{r['slug']}: ignoring malformed "
                  f"recipe JSON (platform source needs none)")
            recipe = None
        out.append({"source": r["source"], "slug": r["slug"], "name": r["name"],
                    "recipe": recipe})
    return out


def count_watchlist(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM watched_companies").fetchone()[0]


def import_watchlist(conn: sqlite3.Connection, companies, *, now: str) -> int:
    """Idempotently seed watched_companies (dedup on (source, slug)). Returns rows
    inserted. Used for the one-time migration of config.yaml `companies:`."""
    inserted = 0
    for c in companies:
        recipe = c.get("recipe")
        cur = conn.execute(
            "INSERT INTO watched_companies (source, slug, name, recipe, created_at) "
            "VALUES (:source, :slug, :name, :recipe, :created_at) "
            "ON CONFLICT(source, slug) DO NOTHING",
            {"source": c["source"], "slug": c["slug"], "name": c["name"],
             "recipe": json.dumps(recipe) if recipe else None, "created_at": now},
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


def delete_unresolved(conn: sqlite3.Connection, url: str) -> None:
    """Clear a feed_unresolved row by its url (the table's only join key back to
    a posting). A no-op if the url isn't present — the caller doesn't know or
    care whether a row existed before a posting successfully (re-)ingests.
    """
    conn.execute("DELETE FROM feed_unresolved WHERE url = ?", (url,))
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

def get_by_status(conn: sqlite3.Connection, status: str):
    return conn.execute(
        "SELECT * FROM job_postings WHERE pipeline_status=? ORDER BY score DESC, id ASC",
        [status],
    ).fetchall()


def get_notifiable(conn: sqlite3.Connection):
    """Scored rows the fit verdicts mark a strong match — the notify gate.
    Replaces the old score>=threshold gate: seniority AND domain must both be
    `match`, and a **thin JD is held back** for human review two ways, so this gate
    mirrors the web's Matched tab exactly (actions.ts `matchedIds()` minus
    `lowContextIds()`): the model's own `insufficient_context` flag, OR a description
    shorter than 200 chars (`LOW_CONTEXT_MAX_DESCRIPTION_LENGTH` — kept in sync by hand
    with apps/web/src/lib/constants.ts; a short blurb the model may still rate
    confidently). Without the length clause the worker would alert on thin JDs the UI
    hides under Low-context. json_extract reads the verdicts out of score_detail."""
    return conn.execute(
        "SELECT * FROM job_postings WHERE pipeline_status='scored' "
        "AND json_extract(score_detail,'$.assessment.seniority.verdict')='match' "
        "AND json_extract(score_detail,'$.assessment.domain.verdict')='match' "
        "AND COALESCE(json_extract(score_detail,'$.insufficient_context'),0)<>1 "
        "AND LENGTH(TRIM(description)) >= 200 "
        "ORDER BY score DESC, id ASC"
    ).fetchall()


# --- state transitions ----------------------------------------------------

# The only columns the state-transition helpers ever set (save_score,
# mark_notified — attempts/application_id are written by fixed-SQL callers
# instead, never through this dict path). `_update` builds its SET clause from
# dict keys, so gate them against this allowlist: a stray/untrusted key must
# never reach the SQL string (defense-in-depth; today all callers pass constants).
_UPDATABLE_COLUMNS = frozenset({
    "score", "score_detail", "pipeline_status", "pipeline_error", "updated_at",
})


def _update(conn: sqlite3.Connection, posting_id: int, sets: dict) -> None:
    unknown = set(sets) - _UPDATABLE_COLUMNS
    if unknown:
        raise ValueError(f"_update: refusing to build SET for unknown column(s): {sorted(unknown)}")
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


def mark_notified(conn, posting_id: int, *, now: str) -> None:
    # pipeline_error is cleared so a row that recovered from a failed send
    # doesn't carry a stale error string.
    _update(conn, posting_id, {"pipeline_status": "notified", "pipeline_error": None,
                               "updated_at": now})


def mark_failed(conn, posting_id: int, *, error: str, now: str) -> None:
    # increment attempts atomically; keep it in one statement.
    conn.execute(
        "UPDATE job_postings SET pipeline_status='failed', pipeline_error=?, "
        "attempts=attempts+1, updated_at=? WHERE id=?",
        (error, now, posting_id),
    )
    conn.commit()


def record_notify_failure(conn, posting_id: int, *, error: str, now: str,
                          exhausted: bool) -> None:
    """Record a failed notify send. Unlike mark_failed (terminal), the row keeps
    its 'scored' status — so the next pass retries the send — until the caller
    declares the retry budget exhausted, which parks it 'failed'. Either way the
    error and the attempts counter land on the row, so a retrying failure is
    visible, not swallowed."""
    conn.execute(
        "UPDATE job_postings SET pipeline_status=?, pipeline_error=?, "
        "attempts=attempts+1, updated_at=? WHERE id=?",
        ("failed" if exhausted else "scored", error, now, posting_id),
    )
    conn.commit()
