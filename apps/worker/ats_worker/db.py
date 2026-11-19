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
     description, posted_at, score_detail, pipeline_status, created_at,
     source_state, source_last_seen_at, source_content_hash, source_content_revision)
VALUES
    (:source, :external_id, :company_slug, :company_name, :job_title, :location, :job_url,
     :description, :posted_at, :score_detail, :pipeline_status, :created_at,
     'available', :created_at, :source_content_hash, :source_content_revision)
ON CONFLICT(source, external_id) DO NOTHING
"""


def upsert_postings(conn: sqlite3.Connection, postings, *, now: str) -> int:
    """Insert new postings, ignoring any whose (source, external_id) already
    exists. Returns the number of rows actually inserted. Existing content and
    pipeline state stay untouched; a repeated exact identity advances only its
    positive source-seen timestamp/state.
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
                # Optional per-row overrides: the fetch-time deterministic gate marks
                # a location/intern miss 'discarded' with a screen verdict, skipping
                # the Ollama call. Everything else inserts as a fresh 'new' row.
                "pipeline_status": p.get("pipeline_status") or "new",
                "score_detail": (
                    json.dumps(p["score_detail"]) if p.get("score_detail") is not None else None
                ),
                "source_content_hash": assessment_input_hash(p),
                "source_content_revision": 1 if assessment_input_hash(p) else None,
            },
        )
        inserted += cur.rowcount
        if cur.rowcount == 0:
            # A repeated exact identity is a positive source observation, but its
            # content remains immutable here; refresh owns content replacement.
            conn.execute(
                "UPDATE job_postings SET source_state='available',source_last_seen_at=? "
                "WHERE source=? AND external_id=?",
                (now, p["source"], p["external_id"]),
            )
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


# --- candidate preferences --------------------------------------------------
# The screen's hard requirements are DB-owned (one `candidate_preferences` row, id=1,
# written by the web API / MCP). config.yaml `candidate:` seeds it once when absent.

PREFERENCE_FIELDS = ("highest_degree", "work_authorization", "security_clearance",
                     "locations", "exclude_internships", "exclude_contract")


def get_preferences(conn: sqlite3.Connection) -> dict | None:
    """The stored hard requirements, or None when no row exists yet."""
    row = conn.execute("SELECT * FROM candidate_preferences WHERE id=1").fetchone()
    if row is None:
        return None
    out = dict(row)
    out["locations"] = json.loads(out["locations"] or "[]")
    out["exclude_internships"] = bool(out["exclude_internships"])
    out["exclude_contract"] = bool(out["exclude_contract"])
    return out


def seed_preferences(conn: sqlite3.Connection, candidate: dict, *, now: str) -> bool:
    """Insert the one-time config seed; a no-op (False) once any row exists."""
    values = {k: candidate[k] for k in PREFERENCE_FIELDS}
    # Same bytes as the web's JSON.stringify, so restating the seed is a no-op there.
    values["locations"] = json.dumps(list(values["locations"]), ensure_ascii=False,
                                     separators=(",", ":"))
    values["exclude_internships"] = int(bool(values["exclude_internships"]))
    values["exclude_contract"] = int(bool(values["exclude_contract"]))
    cur = conn.execute(
        "INSERT INTO candidate_preferences (id, highest_degree, work_authorization, "
        "security_clearance, locations, exclude_internships, exclude_contract, version, actor, updated_at) "
        "VALUES (1, :highest_degree, :work_authorization, :security_clearance, "
        ":locations, :exclude_internships, :exclude_contract, 1, 'config', :now) "
        "ON CONFLICT(id) DO NOTHING", {**values, "now": now})
    conn.commit()
    return cur.rowcount == 1


# --- JEV profile --------------------------------------------------------------
# The JEV inputs are DB-owned (one `jev_profile` row, id=1); config `jev_dir` seeds it
# once when absent. Texts are stored exactly as read so the policy hash is unchanged.

def get_jev_profile(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM jev_profile WHERE id=1").fetchone()
    return dict(row) if row else None


def seed_jev_profile(conn: sqlite3.Connection, texts: dict, *, now: str) -> bool:
    cur = conn.execute(
        "INSERT INTO jev_profile (id, profile_text, c_pack, yoe_pack, yoe_context, version, "
        "actor, updated_at) VALUES (1, :profile_text, :c_pack, :yoe_pack, :yoe_context, 1, "
        "'config', :now) ON CONFLICT(id) DO NOTHING", {**texts, "now": now})
    conn.commit()
    return cur.rowcount == 1


# --- app settings ---------------------------------------------------------
# A web-owned key-value preferences table (app_settings). The worker never reads
# it. This mutator seeds onboarding preferences (the category vocabulary) and records
# JEV_POLICY_SETTING, the policy hash of the latest JEV pass, which MCP compares
# against each assessment to label older verdicts stale.
JEV_POLICY_SETTING = "jev_current_policy_sha256"

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


def get_screen_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Return eligible standalone-screen work: fresh rows newest-first, then errors
    oldest-attempt-first. Completed rows remain cached until explicitly cleared.
    """
    fresh = conn.execute(
        "SELECT p.* FROM job_postings p "
        "LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
        "WHERE p.pipeline_status='new' AND s.id IS NULL "
        "ORDER BY COALESCE(p.updated_at,'') DESC, p.id DESC"
    ).fetchall()
    errors = conn.execute(
        "SELECT p.* FROM job_postings p "
        "JOIN job_screenings s ON s.job_posting_id=p.id "
        "WHERE p.pipeline_status='new' AND s.state='provider_error' "
        "ORDER BY s.last_attempted_at ASC, p.id ASC"
    ).fetchall()
    return [dict(row) for row in (*fresh, *errors)]


def clear_completed_screenings(conn: sqlite3.Connection) -> int:
    """Clear successful screen cache for eligible `new` rows only."""
    cur = conn.execute(
        "DELETE FROM job_screenings WHERE state='complete' AND job_posting_id IN "
        "(SELECT id FROM job_postings WHERE pipeline_status='new')"
    )
    conn.commit()
    return cur.rowcount


def save_screening(conn: sqlite3.Connection, posting_id: int, *, state: str,
                   result: dict | None, error_category: str | None, backend: str,
                   model: str | None, effort: str | None,
                   evaluator_version: str, now: str) -> bool:
    """Persist one latest screen result if the posting is still eligible.

    The result and eligibility check share a short transaction. Screen provider errors
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
    if safe_category not in {None, "provider_error", "timeout", "executable_missing",
                             "screen_error"}:
        raise ValueError("invalid screen error category")
    result_json = (json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                   if result is not None else None)
    error_message = ("Screen provider failed; retry is pending."
                     if state == "provider_error" else None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        eligible = conn.execute(
            "SELECT source_content_revision FROM job_postings "
            "WHERE id=? AND pipeline_status='new'",
            (posting_id,),
        ).fetchone()
        if eligible is None:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO job_screenings "
            "(job_posting_id,state,result_json,error_category,error_message,backend,model,"
            "effort,evaluator_version,last_attempted_at,completed_at,source_content_revision,"
            "created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_posting_id) DO UPDATE SET "
            "state=excluded.state,result_json=excluded.result_json,"
            "error_category=excluded.error_category,error_message=excluded.error_message,"
            "backend=excluded.backend,model=excluded.model,effort=excluded.effort,"
            "evaluator_version=excluded.evaluator_version,"
            "last_attempted_at=excluded.last_attempted_at,"
            "completed_at=excluded.completed_at,"
            "source_content_revision=excluded.source_content_revision,"
            "updated_at=excluded.updated_at",
            (posting_id, state, result_json, safe_category, error_message, backend, model,
             effort, evaluator_version, now, now if state == "complete" else None,
             eligible["source_content_revision"] if state == "complete" else None,
             now, now),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


_JEV_ELIGIBLE = (
    "p.pipeline_status='new' AND s.state='complete' AND json_valid(s.result_json) "
    "AND COALESCE(json_extract(s.result_json,'$.disqualified'),0)=0"
)


def get_jev_candidates(conn: sqlite3.Connection, policy_sha: str,
                       posted_since: str) -> list[dict]:
    """Screened, not-disqualified `new` postings needing a JEV verdict under `policy_sha`,
    posted on or after `posted_since` (YYYY-MM-DD; posted_at, else created_at).

    Fresh work first (no row, or a row bound to another policy or source revision),
    newest-first; then same-binding provider errors, oldest attempt first.
    """
    recent = "substr(COALESCE(p.posted_at, p.created_at), 1, 10) >= ?"
    stale = ("(j.id IS NULL OR j.policy_sha256 IS NOT ? "
             "OR j.source_content_revision IS NOT p.source_content_revision)")
    fresh = conn.execute(
        "SELECT p.* FROM job_postings p JOIN job_screenings s ON s.job_posting_id=p.id "
        "LEFT JOIN job_jev_assessments j ON j.job_posting_id=p.id "
        f"WHERE {_JEV_ELIGIBLE} AND {stale} AND {recent} "
        "ORDER BY COALESCE(p.updated_at,'') DESC, p.id DESC", (policy_sha, posted_since)).fetchall()
    errors = conn.execute(
        "SELECT p.* FROM job_postings p JOIN job_screenings s ON s.job_posting_id=p.id "
        "JOIN job_jev_assessments j ON j.job_posting_id=p.id "
        f"WHERE {_JEV_ELIGIBLE} AND NOT {stale} AND j.state='provider_error' "
        # An oversized request never changes until its source or policy does (which
        # re-queues it as fresh work above); retrying it would only burn limit slots.
        # Raising jev.MAX_REQUEST_BYTES does not re-queue these: bump RULE_VERSION too.
        "AND j.error_category IS NOT 'request_too_large' "
        f"AND {recent} "
        "ORDER BY j.last_attempted_at ASC, p.id ASC", (policy_sha, posted_since)).fetchall()
    return [dict(row) for row in (*fresh, *errors)]


def save_jev(conn: sqlite3.Connection, posting_id: int, *, state: str, verdict: str | None,
             reasons: list[str] | None, result: dict | None, error_category: str | None,
             model: str | None, policy_sha: str, cost_usd: str | None, now: str) -> bool:
    """Persist one posting's latest JEV verdict if it is still `new`.

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
            "SELECT source_content_revision FROM job_postings WHERE id=? AND pipeline_status='new'",
            (posting_id,)).fetchone()
        if eligible is None:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO job_jev_assessments (job_posting_id,state,verdict,reasons_json,result_json,"
            "error_category,model,policy_sha256,source_content_revision,cost_usd,last_attempted_at,"
            "completed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_posting_id) DO UPDATE SET state=excluded.state,"
            "verdict=excluded.verdict,reasons_json=excluded.reasons_json,"
            "result_json=excluded.result_json,error_category=excluded.error_category,"
            "model=excluded.model,policy_sha256=excluded.policy_sha256,"
            "source_content_revision=excluded.source_content_revision,cost_usd=excluded.cost_usd,"
            "last_attempted_at=excluded.last_attempted_at,completed_at=excluded.completed_at,"
            "updated_at=excluded.updated_at",
            (posting_id, state, verdict, dump(reasons), dump(result),
             error_category if state == "provider_error" else None, model, policy_sha,
             eligible["source_content_revision"], cost_usd, now,
             now if state == "complete" else None, now, now))
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
        f"AND source IN ({placeholders}) "
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


def mark_expired(conn, posting_id: int, *, now: str) -> None:
    """The listing is gone from its board (404/410) — park it out of the live
    buckets. Terminal, like 'removed': nothing requeues an expired row."""
    _update(conn, posting_id, {"pipeline_status": "expired", "updated_at": now})


def touch(conn, posting_id: int, *, now: str) -> None:
    """Re-checked and still live: stamp the check attempt so the row rotates to the
    back of get_recheck_candidates' queue. updated_at is left alone — bumping it
    would move a `new` row to the front of the screen/JEV queues."""
    _update(conn, posting_id, {"source_last_check_attempted_at": now})


