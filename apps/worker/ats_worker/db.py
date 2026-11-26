"""SQLite access for the worker.

Prisma OWNS the schema — this module never issues DDL. It only opens a
connection with the right pragmas for safe co-writing with the Next.js app
(WAL + busy_timeout), and reads/writes rows of four tables: `job_postings`
(the bulk of it), `watched_companies`, `app_settings`, and `feed_unresolved`.

All mutators take an explicit `now` (ISO-8601 string) so timestamps match the
String columns Prisma uses and so callers/tests stay deterministic.
"""
from __future__ import annotations

import json
import sqlite3

from .config import RECIPE_SOURCES
from .screening.errors import PROVIDER_ERROR_CATEGORIES
from .source_lifecycle import (SOURCE_ERROR_CATEGORIES, assessment_input_hash,
                               has_embedded_screen, has_fit_assessment)

# A JD shorter than this is "low-context": too thin to trust a fit verdict on.
# Hand-synced with apps/web/src/lib/constants.ts (LOW_CONTEXT_MAX_DESCRIPTION_LENGTH).
LOW_CONTEXT_MAX_DESCRIPTION_LENGTH = 200


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
     description, posted_at, pipeline_status, created_at,
     source_state, source_last_seen_at, source_content_hash, source_content_revision)
VALUES
    (:source, :external_id, :company_slug, :company_name, :job_title, :location, :job_url,
     :description, :posted_at, 'new', :created_at,
     'available', :created_at, :source_content_hash, :source_content_revision)
ON CONFLICT(source, external_id) DO NOTHING
"""


# The backend recorded on a requirements result no provider produced: the fetch-time
# deterministic gate (location, internship, contract title).
DETERMINISTIC_BACKEND = "deterministic"


def upsert_postings(conn: sqlite3.Connection, postings, *, now: str) -> int:
    """Insert new postings (`pipeline_status='new'`, verdict `pending`), ignoring any whose
    (source, external_id) already exists. Returns the number of rows actually inserted.
    Existing content and pipeline state stay untouched; a repeated exact identity advances
    only its positive source-seen timestamp/state.

    A posting carrying `requirements` (`{"result", "evaluator_version",
    "profile_version"}`) is a fetch-time deterministic discard: on insert it also gets
    that completed requirements result (job_screenings, backend `deterministic`) and the
    final verdict `discarded`, the same shape a screen-time rule discard has.
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
                "source_content_hash": assessment_input_hash(p),
                "source_content_revision": 1 if assessment_input_hash(p) else None,
            },
        )
        inserted += cur.rowcount
        if cur.rowcount and p.get("requirements"):
            req = p["requirements"]
            _insert_requirements(conn, cur.lastrowid, req["result"], now=now,
                                 evaluator_version=req["evaluator_version"],
                                 profile_version=req.get("profile_version"))
            conn.execute("UPDATE job_postings SET verdict='discarded',verdict_at=? WHERE id=?",
                         (now, cur.lastrowid))
        if cur.rowcount == 0:
            # A repeated exact identity is a positive source observation, but its
            # content remains immutable here; refresh owns content replacement.
            conn.execute(
                "UPDATE job_postings SET source_state='available',source_last_seen_at=?,"
                "source_absent_count=CASE WHEN company_slug IS ? THEN 0 "
                "ELSE source_absent_count END WHERE source=? AND external_id=?",
                (now, p.get("company_slug"), p["source"], p["external_id"]),
            )
    conn.commit()
    return inserted


def _insert_requirements(conn, posting_id: int, result: dict, *, now: str,
                         evaluator_version: str, profile_version: int | None) -> None:
    conn.execute(
        "INSERT INTO job_screenings (job_posting_id,state,result_json,backend,model,effort,"
        "evaluator_version,last_attempted_at,completed_at,source_content_revision,"
        "profile_version,created_at,updated_at) "
        "SELECT id,'complete',?,?,NULL,NULL,?,?,?,source_content_revision,?,?,? "
        "FROM job_postings WHERE id=?",
        (json.dumps(result, ensure_ascii=False, separators=(",", ":")), DETERMINISTIC_BACKEND,
         evaluator_version, now, now, profile_version, now, now, posting_id))


# A posting absent from this many consecutive successful, non-empty lists of its
# board is closed at the source.
ABSENT_LISTS_TO_CLOSE = 3


def record_board_listing(conn: sqlite3.Connection, source: str, slug: str, listed_ids,
                         *, now: str, count_absence: bool) -> int:
    """Apply one successful board list to the stored rows of `(source, slug)`.

    Both halves are scoped to the board `(source, company_slug)`, so a second board that
    lists the same id (overlapping custom boards) neither stamps nor resets the first
    board's row. Every listed id stored under this board is a positive observation:
    available, seen now, absence count reset. With `count_absence` and a non-empty list, every other open
    row of the board counts one absence and closes at ABSENT_LISTS_TO_CLOSE. An empty
    list proves nothing and only stamps. Returns the rows closed by this call.
    """
    ids = sorted({str(i) for i in listed_ids if i})
    if not ids:
        return 0
    listed = json.dumps(ids)   # one bound parameter, however long the board is
    conn.execute(
        "UPDATE job_postings SET source_state='available',source_last_seen_at=?,"
        "source_absent_count=0 WHERE source=? AND company_slug=? "
        "AND external_id IN (SELECT value FROM json_each(?))", (now, source, slug, listed))
    closed = 0
    if count_absence:
        absent = ("source=? AND company_slug=? AND source_state<>'closed' "
                  "AND external_id NOT IN (SELECT value FROM json_each(?))")
        conn.execute("UPDATE job_postings SET source_absent_count=source_absent_count+1 "
                     f"WHERE {absent}", (source, slug, listed))
        closed = conn.execute(
            f"UPDATE job_postings SET source_state='closed' WHERE {absent} "
            "AND source_absent_count>=?", (source, slug, listed, ABSENT_LISTS_TO_CLOSE)).rowcount
    conn.commit()
    return closed


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


BOARD_HEALTH_FIGURES = ("fetched", "kept", "new", "bodyless", "detail_failed", "desc_median")

# A kept median description SHORTER than this is a teaser, not a job description. Not a
# gate (nothing is dropped on it), only the threshold the health line and the `teaser`
# state use. Healthy boards measure 1,900-2,200 median chars; the boards that turned out
# to be serving a summary measured 250-850, and the gap between them is empty. The web
# Sources page holds the same number (lib/board-health.ts), pinned by
# tests/fixtures/board-health-cases.json.
TEASER_MEDIAN_CHARS = 1500


def board_health(row) -> str:
    """The state a watchlist row's last-pass record reads as (#231), first match wins:
    never_fetched; disabled (a browser row skipped while enable_browser_sources is off);
    fetch_failed; empty (listed nothing); with nothing kept, details_failed (detail
    calls failed), bodyless (postings came back with no description) or kept_zero (the
    filters kept none); with some kept, details_failed or bodyless when that cause is a
    majority of the postings that reached hydration (kept + bodyless + detail_failed);
    teaser (a measured median under the threshold; NULL = nothing measured); else ok.
    `row` is a mapping of the watched_companies last_* columns."""
    status = row["last_fetch_status"]
    if not status:
        return "never_fetched"
    if status == "disabled":
        return "disabled"
    if status != "ok":
        return "fetch_failed"
    if not row["last_fetched"]:
        return "empty"
    kept, bodyless = row["last_kept"] or 0, row["last_bodyless"] or 0
    failed = row["last_detail_failed"] or 0
    if not kept:
        return "details_failed" if failed else "bodyless" if bodyless else "kept_zero"
    reached = kept + bodyless + failed
    if failed * 2 > reached:
        return "details_failed"
    if bodyless * 2 > reached:
        return "bodyless"
    median = row["last_desc_median"]
    if median is not None and median < TEASER_MEDIAN_CHARS:
        return "teaser"
    return "ok"


def record_board_health(conn: sqlite3.Connection, source: str, slug: str, *, now: str,
                        status: str, figures: dict | None = None) -> None:
    """Overwrite a watchlist row's last-pass record (#231): `status` is `ok`, `disabled` or a closed
    error category; `figures` (BOARD_HEALTH_FIGURES) is None for a failed fetch, so a
    failure never shows the previous pass's counts. A board not on the watchlist (a
    config-only company) updates nothing."""
    f = figures or {}
    conn.execute(
        "UPDATE watched_companies SET last_fetched_at=?, last_fetch_status=?, "
        + ", ".join(f"last_{k}=?" for k in BOARD_HEALTH_FIGURES)
        + " WHERE source=? AND slug=?",
        (now, status, *(f.get(k) for k in BOARD_HEALTH_FIGURES), source, slug))
    conn.commit()


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


# --- candidate profile --------------------------------------------------------
# The one candidate input (#224): one `candidate_profile` row, id=1, written by the web
# API / MCP. Parsed and derived by ats_worker/profile.py; config.yaml seeds it once.

def get_candidate_profile(conn: sqlite3.Connection) -> dict | None:
    """The stored row as a dict, or None when none exists yet."""
    row = conn.execute("SELECT * FROM candidate_profile WHERE id=1").fetchone()
    return dict(row) if row else None


def write_candidate_profile(conn: sqlite3.Connection, values: dict, *, actor: str, now: str,
                            confirmed_at: str | None = None, changed_at: str | None = None,
                            replace: bool = False) -> bool:
    """Insert the one-time seed (a no-op, False, once a row exists), or with `replace`
    overwrite the row's profile fields (the migration replacing an untouched config seed).
    `values` holds profile.PROFILE_FIELDS; booleans are stored as 0/1."""
    cols = {**values, "exclude_internships": int(bool(values["exclude_internships"])),
            "exclude_contract": int(bool(values["exclude_contract"])),
            "actor": actor, "updated_at": now, "confirmed_at": confirmed_at,
            "changed_at": changed_at}
    names = sorted(cols)
    if replace:
        sql = (f"UPDATE candidate_profile SET {', '.join(f'{n}=:{n}' for n in names)}, "
               "version=1 WHERE id=1")
    else:
        sql = (f"INSERT INTO candidate_profile (id, version, {', '.join(names)}) "
               f"VALUES (1, 1, {', '.join(':' + n for n in names)}) ON CONFLICT(id) DO NOTHING")
    cur = conn.execute(sql, cols)
    conn.commit()
    return cur.rowcount == 1


# --- app settings ---------------------------------------------------------
# A web-owned key-value preferences table (app_settings). The worker never reads
# it; this mutator seeds onboarding preferences (the category vocabulary).

def upsert_setting(conn: sqlite3.Connection, key: str, value: str, *, now: str) -> None:
    """Insert or overwrite one app_settings row. `value` is stored verbatim (the
    caller JSON-encodes structured values, mirroring watched_companies.recipe)."""
    conn.execute(
        "INSERT INTO app_settings (key, value, updated_at) "
        "VALUES (:key, :value, :now) "
        "ON CONFLICT(key) DO UPDATE SET value=:value, updated_at=:now",
        {"key": key, "value": value, "now": now},
    )
    conn.commit()


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


def clear_empty_descriptions(conn: sqlite3.Connection, urls) -> None:
    """Clear the `empty_description` rows of URLs that came back with a body. Only that
    reason: a feed's unsupported_host row for the same URL is still true of the feed."""
    conn.executemany("DELETE FROM feed_unresolved WHERE url = ? AND reason='empty_description'",
                     [(u,) for u in urls])
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
    """Rows in `status`, oldest first."""
    return conn.execute(
        "SELECT * FROM job_postings WHERE pipeline_status=? ORDER BY id ASC",
        [status],
    ).fetchall()


# A posting is evaluated only while it is in the window: posted_at, else created_at, on
# or after the window start (a YYYY-MM-DD bound parameter).
IN_WINDOW = "substr(COALESCE(p.posted_at, p.created_at), 1, 10) >= ?"
# Still waiting for a stage: `new`, verdict pending, not closed at the source.
_PENDING = "p.pipeline_status='new' AND p.verdict='pending' AND p.source_state<>'closed'"


def get_screen_candidates(conn: sqlite3.Connection, since: str) -> list[dict]:
    """Return eligible standalone-screen work: pending in-window rows with no result,
    newest-first, then provider errors oldest-attempt-first. A completed result is never
    re-queued, and a posting closed at the source is never screened.
    """
    fresh = conn.execute(
        "SELECT p.* FROM job_postings p "
        "LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
        f"WHERE {_PENDING} AND {IN_WINDOW} AND s.id IS NULL "
        "ORDER BY COALESCE(p.updated_at,'') DESC, p.id DESC", (since,)
    ).fetchall()
    errors = conn.execute(
        "SELECT p.* FROM job_postings p "
        "JOIN job_screenings s ON s.job_posting_id=p.id "
        f"WHERE {_PENDING} AND {IN_WINDOW} AND s.state='provider_error' "
        "ORDER BY s.last_attempted_at ASC, p.id ASC", (since,)
    ).fetchall()
    return [dict(row) for row in (*fresh, *errors)]


def _settle(conn: sqlite3.Connection, posting_id: int, verdict: str, *, now: str) -> None:
    """Write a posting's final verdict; a verdict once set never changes."""
    conn.execute("UPDATE job_postings SET verdict=?,verdict_at=? "
                 "WHERE id=? AND verdict='pending'", (verdict, now, posting_id))


def needs_evaluate_once_migration(conn: sqlite3.Connection) -> bool:
    """True until ats_worker.migrate_evaluate_once has run: a row is still in the retired
    `pipeline_status='discarded'` shape, or a pending posting carries a finished screen
    discard or triage verdict. The worker settles both the moment it writes them, so
    neither exists after the migration; before it, a pass would age them out as
    `not_evaluated`. run_once, the daemon and the migration all read this one test."""
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM job_postings WHERE pipeline_status='discarded') "
        "OR EXISTS (SELECT 1 FROM job_postings p WHERE p.verdict='pending' AND ("
        "EXISTS (SELECT 1 FROM job_screenings s WHERE s.job_posting_id=p.id "
        "AND s.state='complete' AND json_valid(s.result_json) "
        "AND COALESCE(json_extract(s.result_json,'$.disqualified'),0)=1) "
        "OR EXISTS (SELECT 1 FROM job_jev_assessments j WHERE j.job_posting_id=p.id "
        "AND j.state='complete' AND j.verdict IN ('keep','skip'))))").fetchone()[0] == 1


def age_out(conn: sqlite3.Connection, *, since: str, now: str, commit: bool = True) -> int:
    """Finalize every pending posting outside the window as `not_evaluated`: nothing
    evaluates it any more. Returns the rows aged out this call. `commit=False` leaves
    the write in the caller's transaction (the migration)."""
    cur = conn.execute(
        "UPDATE job_postings SET verdict='not_evaluated',verdict_at=? WHERE id IN "
        f"(SELECT p.id FROM job_postings p WHERE p.verdict='pending' AND NOT ({IN_WINDOW}))",
        (now, since))
    if commit:
        conn.commit()
    return cur.rowcount


def save_screening(conn: sqlite3.Connection, posting_id: int, *, state: str,
                   result: dict | None, error_category: str | None, backend: str,
                   model: str | None, effort: str | None,
                   evaluator_version: str, now: str, profile_version: int | None = None,
                   final_on_pass: bool = False) -> bool:
    """Persist one screen result if the posting is still pending, with the profile
    version it ran under. A completed disqualification sets the verdict `discarded`; a
    completed pass sets `keep` when `final_on_pass` (no triage stage follows).

    The result, the verdict and the eligibility check share a short transaction. Screen provider errors
    deliberately carry only a fixed message and a closed category; raw provider output
    can contain job text or credentials and is never persisted here.
    """
    if state not in {"complete", "provider_error"}:
        raise ValueError(f"invalid screen state: {state!r}")
    if state == "complete" and result is None:
        raise ValueError("a completed screen requires a result")
    if state == "provider_error" and result is not None:
        raise ValueError("provider errors cannot be cached as successful results")
    safe_category = error_category if state == "provider_error" else None
    if safe_category is not None and safe_category not in PROVIDER_ERROR_CATEGORIES:
        raise ValueError("invalid screen error category")
    result_json = (json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                   if result is not None else None)
    error_message = ("Screen provider failed; retry is pending."
                     if state == "provider_error" else None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        eligible = conn.execute(
            "SELECT source_content_revision FROM job_postings "
            "WHERE id=? AND pipeline_status='new' AND verdict='pending'",
            (posting_id,),
        ).fetchone()
        if eligible is None:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO job_screenings "
            "(job_posting_id,state,result_json,error_category,error_message,backend,model,"
            "effort,evaluator_version,last_attempted_at,completed_at,source_content_revision,"
            "profile_version,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_posting_id) DO UPDATE SET "
            "state=excluded.state,result_json=excluded.result_json,"
            "error_category=excluded.error_category,error_message=excluded.error_message,"
            "backend=excluded.backend,model=excluded.model,effort=excluded.effort,"
            "evaluator_version=excluded.evaluator_version,"
            "last_attempted_at=excluded.last_attempted_at,"
            "completed_at=excluded.completed_at,"
            "source_content_revision=excluded.source_content_revision,"
            "profile_version=excluded.profile_version,"
            "updated_at=excluded.updated_at",
            (posting_id, state, result_json, safe_category, error_message, backend, model,
             effort, evaluator_version, now, now if state == "complete" else None,
             eligible["source_content_revision"] if state == "complete" else None,
             profile_version, now, now),
        )
        if state == "complete" and result.get("disqualified"):
            _settle(conn, posting_id, "discarded", now=now)
        elif state == "complete" and final_on_pass:
            _settle(conn, posting_id, "keep", now=now)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


_JEV_ELIGIBLE = (
    f"{_PENDING} AND s.state='complete' AND json_valid(s.result_json) "
    "AND COALESCE(json_extract(s.result_json,'$.disqualified'),0)=0"
)


def get_jev_candidates(conn: sqlite3.Connection, since: str) -> list[dict]:
    """Pending, screened, not-disqualified in-window postings with no completed triage
    verdict (window start `since`, YYYY-MM-DD).

    Unassessed postings first, newest-first; then provider errors, oldest attempt first.
    A completed verdict is never re-queued, whatever changes afterwards.
    """
    fresh = conn.execute(
        "SELECT p.* FROM job_postings p JOIN job_screenings s ON s.job_posting_id=p.id "
        "LEFT JOIN job_jev_assessments j ON j.job_posting_id=p.id "
        f"WHERE {_JEV_ELIGIBLE} AND j.id IS NULL AND {IN_WINDOW} "
        "ORDER BY COALESCE(p.updated_at,'') DESC, p.id DESC", (since,)).fetchall()
    errors = conn.execute(
        "SELECT p.* FROM job_postings p JOIN job_screenings s ON s.job_posting_id=p.id "
        "JOIN job_jev_assessments j ON j.job_posting_id=p.id "
        f"WHERE {_JEV_ELIGIBLE} AND j.state='provider_error' "
        # An oversized request never changes, so retrying it would only burn limit
        # slots; it stays pending until it leaves the window.
        "AND j.error_category IS NOT 'request_too_large' "
        f"AND {IN_WINDOW} "
        "ORDER BY j.last_attempted_at ASC, p.id ASC", (since,)).fetchall()
    return [dict(row) for row in (*fresh, *errors)]


def save_jev(conn: sqlite3.Connection, posting_id: int, *, state: str, verdict: str | None,
             reasons: list[str] | None, result: dict | None, error_category: str | None,
             model: str | None, cost_usd: str | None, now: str,
             profile_version: int | None = None) -> bool:
    """Persist one posting's JEV result if it is still `new` and pending, with the
    profile version it ran under. A completed keep/skip is the posting's final verdict.

    Like save_screening: provider errors store only a closed category, never provider
    output, and the source revision is captured in the same transaction.
    """
    if state not in {"complete", "provider_error"}:
        raise ValueError(f"invalid jev state: {state!r}")
    if state == "complete" and verdict not in {"keep", "skip"}:
        raise ValueError("a completed jev assessment requires keep or skip")
    if state == "provider_error" and (verdict is not None or result is not None):
        raise ValueError("provider errors cannot carry a verdict")
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":")) if v is not None else None
    try:
        conn.execute("BEGIN IMMEDIATE")
        eligible = conn.execute(
            "SELECT source_content_revision FROM job_postings "
            "WHERE id=? AND pipeline_status='new' AND verdict='pending'",
            (posting_id,)).fetchone()
        if eligible is None:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO job_jev_assessments (job_posting_id,state,verdict,reasons_json,result_json,"
            "error_category,model,source_content_revision,profile_version,cost_usd,"
            "last_attempted_at,completed_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_posting_id) DO UPDATE SET state=excluded.state,"
            "verdict=excluded.verdict,reasons_json=excluded.reasons_json,"
            "result_json=excluded.result_json,error_category=excluded.error_category,"
            "model=excluded.model,source_content_revision=excluded.source_content_revision,"
            "profile_version=excluded.profile_version,cost_usd=excluded.cost_usd,"
            "last_attempted_at=excluded.last_attempted_at,completed_at=excluded.completed_at,"
            "updated_at=excluded.updated_at",
            (posting_id, state, verdict, dump(reasons), dump(result),
             error_category if state == "provider_error" else None, model,
             eligible["source_content_revision"], profile_version, cost_usd, now,
             now if state == "complete" else None, now, now))
        if state == "complete":
            _settle(conn, posting_id, verdict, now=now)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def get_recheck_candidates(conn: sqlite3.Connection, sources, limit: int):
    """Live postings (new|scored|notified) from per-listing sources, least-recently
    checked first — the expiry re-check queue (pipeline.run_expire). A live check
    stamps source_last_check_attempted_at (`touch`), so the queue rotates itself
    without touching updated_at, which orders the screen and JEV queues."""
    sources = list(sources)
    if not sources or limit <= 0:
        return []
    placeholders = ",".join("?" for _ in sources)
    return conn.execute(
        "SELECT * FROM job_postings WHERE pipeline_status IN ('new','scored','notified') "
        f"AND source_state<>'closed' AND source IN ({placeholders}) "
        "ORDER BY COALESCE(source_last_check_attempted_at,updated_at,'') ASC, id ASC LIMIT ?",
        [*sources, limit],
    ).fetchall()


_UNSCORED_REFRESH_STATES = ("new", "failed", "discarded", "expired")
_KNOWN_PIPELINE_STATES = ("new", "scored", "notified", "applied", "discarded",
                          "failed", "removed", "expired")


def get_unscored_refresh_candidates(conn: sqlite3.Connection, source: str, limit: int):
    """Return eligible unscored rows, oldest refresh attempt first.

    Assessment presence is decoded in Python so malformed or legacy score_detail JSON
    cannot crash a SQLite JSON query or masquerade as a fit assessment.
    """
    if not source or limit <= 0:
        return []
    placeholders = ",".join("?" for _ in _UNSCORED_REFRESH_STATES)
    rows = conn.execute(
        "SELECT * FROM job_postings WHERE source=? AND application_id IS NULL "
        f"AND pipeline_status IN ({placeholders}) "
        "ORDER BY COALESCE(source_last_check_attempted_at,'') ASC, id ASC",
        [source, *_UNSCORED_REFRESH_STATES],
    ).fetchall()
    selected = []
    for row in rows:
        if has_fit_assessment(row["score_detail"]):
            continue
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def count_unknown_refresh_statuses(conn: sqlite3.Connection, source: str) -> int:
    """Count source rows with lifecycle values outside the known state vocabulary."""
    placeholders = ",".join("?" for _ in _KNOWN_PIPELINE_STATES)
    return conn.execute(
        f"SELECT COUNT(*) FROM job_postings WHERE source=? "
        f"AND pipeline_status NOT IN ({placeholders})",
        [source, *_KNOWN_PIPELINE_STATES],
    ).fetchone()[0]


def _source_refresh_eligible(row, expected_source: str) -> bool:
    return (row is not None and row["source"] == expected_source
            and row["pipeline_status"] in _UNSCORED_REFRESH_STATES
            and row["application_id"] is None
            and not has_fit_assessment(row["score_detail"]))


def _attribute_legacy_assessments(conn: sqlite3.Connection, row, revision: int) -> None:
    """Stamp unversioned existing assessments with the provable pre-change revision."""
    if (has_fit_assessment(row["score_detail"])
            or has_embedded_screen(row["score_detail"])):
        try:
            detail = json.loads(row["score_detail"])
        except (TypeError, json.JSONDecodeError):
            detail = None
        if isinstance(detail, dict) and detail.get("source_content_revision") is None:
            detail["source_content_revision"] = revision
            conn.execute("UPDATE job_postings SET score_detail=? WHERE id=?",
                         (json.dumps(detail, ensure_ascii=False), row["id"]))
    screening = conn.execute(
        "SELECT id FROM job_screenings WHERE job_posting_id=? AND state='complete' "
        "AND source_content_revision IS NULL", (row["id"],),
    ).fetchone()
    if screening:
        conn.execute("UPDATE job_screenings SET source_content_revision=? WHERE id=?",
                     (revision, screening["id"]))


def save_source_observation(conn: sqlite3.Connection, posting_id: int, *,
                            expected_source: str, expected_external_id: str,
                            observation: dict, now: str) -> bool:
    """Apply one refresh result only while the stored row remains eligible.

    The identity and eligibility checks share the write transaction. Returns False
    when a concurrent user/status/application change made the fetched result stale.
    """
    state = observation.get("state") if isinstance(observation, dict) else None
    if state not in {"available", "closed", "unknown"}:
        state = "unknown"
        observation = {"state": state, "error_category": "malformed_response"}
    category = observation.get("error_category")
    if category not in SOURCE_ERROR_CATEGORIES:
        category = "refresh_error" if state == "unknown" else None
    posting = observation.get("posting") if state == "available" else None
    if state == "available":
        identity_ok = (isinstance(posting, dict)
                       and posting.get("source") == expected_source
                       and str(posting.get("external_id") or "") == expected_external_id
                       and assessment_input_hash(posting) is not None
                       and isinstance(posting.get("job_url"), str)
                       and bool(posting["job_url"].strip()))
        if not identity_ok:
            state, category, posting = "unknown", "identity_mismatch", None

    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM job_postings WHERE id=?", (posting_id,)).fetchone()
        if (not _source_refresh_eligible(row, expected_source)
                or row["source"] != expected_source
                or row["external_id"] != expected_external_id):
            conn.rollback()
            return False

        if state == "unknown":
            conn.execute(
                "UPDATE job_postings SET source_last_check_attempted_at=?,"
                "source_last_check_outcome='inconclusive',"
                "source_last_check_error_category=? WHERE id=?",
                (now, category, posting_id),
            )
        elif state == "closed":
            conn.execute(
                "UPDATE job_postings SET source_state='closed',"
                "source_last_check_attempted_at=?,source_last_checked_at=?,"
                "source_last_check_outcome='confirmed_closed',"
                "source_last_check_error_category=NULL WHERE id=?",
                (now, now, posting_id),
            )
        else:
            old_values = {
                "company_name": row["company_name"], "job_title": row["job_title"],
                "location": row["location"], "description": row["description"],
            }
            old_hash = row["source_content_hash"] or assessment_input_hash(old_values)
            new_hash = assessment_input_hash(posting)
            old_revision = row["source_content_revision"]
            old_revision = int(old_revision) if old_revision is not None else (1 if old_hash else None)
            if old_hash and old_hash == new_hash:
                revision = old_revision or 1
                changed_at = row["source_content_changed_at"]
            elif old_hash:
                revision = (old_revision or 1) + 1
                changed_at = now
                _attribute_legacy_assessments(conn, row, old_revision or 1)
            else:
                revision = (old_revision or 0) + 1
                changed_at = now

            conn.execute(
                "UPDATE job_postings SET company_name=?,job_title=?,location=?,job_url=?,"
                "description=?,source_state='available',source_last_seen_at=?,"
                "source_last_check_attempted_at=?,source_last_checked_at=?,"
                "source_last_check_outcome='found',source_last_check_error_category=NULL,"
                "source_content_hash=?,source_content_revision=?,source_content_changed_at=? "
                "WHERE id=?",
                (posting["company_name"], posting["job_title"], posting.get("location"),
                 posting["job_url"], posting["description"], now, now, now, new_hash,
                 revision, changed_at, posting_id),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


# --- state transitions ----------------------------------------------------

# The only columns the state-transition helpers ever set (application_id
# is written by fixed-SQL callers instead, never through this dict path). `_update` builds its SET clause from
# dict keys, so gate them against this allowlist: a stray/untrusted key must
# never reach the SQL string (defense-in-depth; today all callers pass constants).
_UPDATABLE_COLUMNS = frozenset({
    "score_detail", "pipeline_status", "pipeline_error", "updated_at",
    "source_last_check_attempted_at",
})


def _update(conn: sqlite3.Connection, posting_id: int, sets: dict) -> None:
    unknown = set(sets) - _UPDATABLE_COLUMNS
    if unknown:
        raise ValueError(f"_update: refusing to build SET for unknown column(s): {sorted(unknown)}")
    cols = ", ".join(f"{k}=:{k}" for k in sets)
    params = {**sets, "id": posting_id}
    conn.execute(f"UPDATE job_postings SET {cols} WHERE id=:id", params)
    conn.commit()


def mark_source_closed(conn, posting_id: int, *, now: str) -> None:
    """The listing's detail endpoint answered 404/410: the posting is closed at the
    source. Lifecycle and updated_at are left alone; closure is source state, and a
    later list observation reopens it (upsert_postings / record_board_listing)."""
    conn.execute(
        "UPDATE job_postings SET source_state='closed',source_last_check_attempted_at=?,"
        "source_last_checked_at=?,source_last_check_outcome='confirmed_closed',"
        "source_last_check_error_category=NULL WHERE id=?", (now, now, posting_id))
    conn.commit()


def record_check_inconclusive(conn, posting_id: int, *, now: str, category: str) -> None:
    """A detail check that proved nothing (transient error, no usable key, or the
    adapter declined with None): stamp the attempt and an allow-listed error category
    (SOURCE_ERROR_CATEGORIES) so the row rotates to the back of
    get_recheck_candidates' queue. Never 'found', never closed; source_state and
    updated_at are left alone."""
    conn.execute(
        "UPDATE job_postings SET source_last_check_attempted_at=?,"
        "source_last_check_outcome='inconclusive',source_last_check_error_category=? "
        "WHERE id=?", (now, category, posting_id))
    conn.commit()


def record_check_found(conn, posting_id: int, *, now: str) -> None:
    """The listing's detail endpoint served the posting: a conclusive `found` check,
    clearing any earlier inconclusive category, and the row rotates to the back of
    get_recheck_candidates' queue. source_state, the content and updated_at are left
    alone — bumping updated_at would move a `new` row to the front of the screen/JEV
    queues; refreshing content is run_unscored_refresh's job."""
    conn.execute(
        "UPDATE job_postings SET source_last_check_attempted_at=?,source_last_checked_at=?,"
        "source_last_check_outcome='found',source_last_check_error_category=NULL "
        "WHERE id=?", (now, now, posting_id))
    conn.commit()


# --- pass record (worker_runs) ---------------------------------------------

def _json(value) -> str:
    # default=str: run_jev's spend is a Decimal.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def start_pass(conn: sqlite3.Connection, *, now: str, fetch_only: bool,
               jev_enabled: bool, config: dict) -> int:
    """Insert this pass's `running` row and return its id. Any row still `running` is
    a pass that died: the caller holds the pass lock, so no other pass is live. It is
    marked `failed`/`abandoned` with finished_at left NULL (the death time is unknown).
    `config` is the effective runtime config and must carry no secret."""
    conn.execute("UPDATE worker_runs SET status='failed', error_category='abandoned' "
                 "WHERE status='running'")
    cur = conn.execute(
        "INSERT INTO worker_runs (started_at, status, fetch_only, jev_enabled, "
        "config_json, counts_json) VALUES (?, 'running', ?, ?, ?, '{}')",
        (now, bool(fetch_only), bool(jev_enabled), _json(config)))
    conn.commit()
    return int(cur.lastrowid)


def update_pass_counts(conn: sqlite3.Connection, run_id: int, counts: dict) -> None:
    """Store the stage tallies so far, so a pass that dies keeps what it finished."""
    conn.execute("UPDATE worker_runs SET counts_json=? WHERE id=?", (_json(counts), run_id))
    conn.commit()


def finish_pass(conn: sqlite3.Connection, run_id: int, *, now: str, counts: dict) -> None:
    conn.execute("UPDATE worker_runs SET status='ok', finished_at=?, counts_json=? "
                 "WHERE id=? AND status='running'", (now, _json(counts), run_id))
    conn.commit()


def fail_pass(conn: sqlite3.Connection, run_id: int, *, now: str) -> None:
    """Mark a pass that raised `failed`/`crashed`. The stage's uncommitted writes are
    rolled back first; the tallies already stored stay."""
    conn.rollback()
    conn.execute("UPDATE worker_runs SET status='failed', error_category='crashed', "
                 "finished_at=? WHERE id=? AND status='running'", (now, run_id))
    conn.commit()


