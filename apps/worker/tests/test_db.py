"""TDD for the worker's SQLite layer: WAL pragmas, dedup upsert, state writes."""
from __future__ import annotations

import json

from ats_worker import db
from tests._helpers import LATER, NOW, make_posting as posting, seed_scored


# --- connection / pragmas -------------------------------------------------

def test_connect_enables_wal_and_busy_timeout(db_path):
    conn = db.connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# --- upsert / dedup -------------------------------------------------------

def test_upsert_inserts_new_rows_as_new_status(db_path):
    conn = db.connect(db_path)
    inserted = db.upsert_postings(conn, [posting("1"), posting("2")], now=NOW)
    assert inserted == 2
    rows = db.get_by_status(conn, "new")
    assert {r["external_id"] for r in rows} == {"1", "2"}
    assert all(r["pipeline_status"] == "new" for r in rows)
    assert all(r["created_at"] == NOW for r in rows)


def test_upsert_dedupes_on_source_external_id(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1", job_title="Original")], now=NOW)
    # same (source, external_id), different title — must NOT insert or overwrite
    inserted = db.upsert_postings(conn, [posting("1", job_title="Changed")], now=LATER)
    assert inserted == 0
    rows = db.get_by_status(conn, "new")
    assert len(rows) == 1
    assert rows[0]["job_title"] == "Original"


def test_upsert_same_external_id_different_source_are_distinct(db_path):
    conn = db.connect(db_path)
    inserted = db.upsert_postings(
        conn, [posting("1", source="greenhouse"), posting("1", source="lever")], now=NOW
    )
    assert inserted == 2


# --- state transitions ----------------------------------------------------

def _one(conn, external_id="1"):
    return conn.execute(
        "SELECT * FROM job_postings WHERE external_id=?", (external_id,)
    ).fetchone()


def test_save_score_writes_detail_and_advances_status(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    detail = {"matched": ["python"], "missing": ["go"], "reasoning": "ok"}
    db.save_score(conn, pid, score=82, score_detail=detail, now=LATER)
    row = _one(conn)
    assert row["score"] == 82
    assert json.loads(row["score_detail"]) == detail
    assert row["pipeline_status"] == "scored"
    assert row["updated_at"] == LATER


def test_get_by_status_can_filter_high_scores(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1"), posting("2")], now=NOW)
    ids = {r["external_id"]: r["id"] for r in db.get_by_status(conn, "new")}
    db.save_score(conn, ids["1"], score=90, score_detail={}, now=LATER)
    db.save_score(conn, ids["2"], score=40, score_detail={}, now=LATER)
    scored = db.get_by_status(conn, "scored", min_score=75)
    assert [r["external_id"] for r in scored] == ["1"]


def test_save_resume_advances_to_tailored(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    db.save_resume(conn, pid, resume_tex="\\documentclass{article}",
                   resume_path="resumes/1.pdf", resume_pages=1, now=LATER)
    row = _one(conn)
    assert row["resume_path"] == "resumes/1.pdf"
    assert row["resume_pages"] == 1
    assert row["pipeline_status"] == "tailored"


def test_mark_notified(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    db.mark_notified(conn, pid, now=LATER)
    assert _one(conn)["pipeline_status"] == "notified"


def test_mark_applied_backfills_application_id(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    app_id = conn.execute(
        "INSERT INTO applications (company_name, job_title, date_applied, status) "
        "VALUES ('Acme','Software Engineer','2026-06-04','Applied')"
    ).lastrowid
    conn.commit()
    db.mark_applied(conn, pid, application_id=app_id, now=LATER)
    row = _one(conn)
    assert row["pipeline_status"] == "applied"
    assert row["application_id"] == app_id


def test_mark_failed_records_error_and_increments_attempts(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    db.mark_failed(conn, pid, error="tectonic exploded", now=LATER)
    row = _one(conn)
    assert row["pipeline_status"] == "failed"
    assert row["pipeline_error"] == "tectonic exploded"
    assert row["attempts"] == 1
    db.mark_failed(conn, pid, error="again", now=LATER)
    assert _one(conn)["attempts"] == 2


def test_discard(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    db.discard(conn, pid, now=LATER)
    assert _one(conn)["pipeline_status"] == "discarded"


EVEN_LATER = "2026-06-04T10:00:00.000Z"


# --- the dedup invariant: a re-fetch must not clobber an in-flight posting --

def test_refetch_does_not_clobber_scored_posting(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1", job_title="Original")], now=NOW)
    pid = _one(conn)["id"]
    db.save_score(conn, pid, score=88, score_detail={"k": 1}, now=LATER)  # -> scored
    # The fetcher sees the same (source, external_id) again next run.
    inserted = db.upsert_postings(conn, [posting("1", job_title="Changed")], now=EVEN_LATER)
    row = _one(conn)
    assert inserted == 0
    assert row["pipeline_status"] == "scored"   # not reset to 'new'
    assert row["score"] == 88                    # score survives
    assert row["job_title"] == "Original"        # not overwritten
    assert row["created_at"] == NOW              # original insert time kept


def test_insert_leaves_updated_at_null_and_attempts_zero(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    row = _one(conn)
    assert row["updated_at"] is None
    assert row["attempts"] == 0


def test_null_location_round_trips(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1", location=None)], now=NOW)
    assert _one(conn)["location"] is None


# --- mutator field isolation ---------------------------------------------

def test_mark_failed_keeps_score_and_save_score_keeps_attempts(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    db.save_score(conn, pid, score=77, score_detail={}, now=LATER)
    db.mark_failed(conn, pid, error="boom", now=EVEN_LATER)
    row = _one(conn)
    assert row["pipeline_status"] == "failed"
    assert row["score"] == 77          # mark_failed must not wipe the score
    assert row["attempts"] == 1
    # a later save_score must not reset the attempts counter
    db.save_score(conn, pid, score=80, score_detail={}, now=EVEN_LATER)
    assert _one(conn)["attempts"] == 1


# --- save_score status override (disqualify -> discarded) -----------------

def test_save_score_status_override_to_discarded(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    detail = {"disqualified": True, "disqualification_reason": "needs PhD"}
    db.save_score(conn, pid, score=42, score_detail=detail, now=LATER, status="discarded")
    row = _one(conn)
    assert row["pipeline_status"] == "discarded"
    assert row["score"] == 42                       # score kept for the UI
    assert json.loads(row["score_detail"]) == detail


# --- get_by_status ordering / limit / min_score boundary / NULL-excluded --

def test_get_by_status_orders_by_score_then_id(db_path):
    conn = db.connect(db_path)
    seed_scored(conn, {"a": 90, "b": 90, "c": 40}, detail={})
    rows = db.get_by_status(conn, "scored")
    assert [r["external_id"] for r in rows] == ["a", "b", "c"]  # 90s by id, then 40


def test_get_by_status_min_score_is_inclusive_and_limited(db_path):
    conn = db.connect(db_path)
    seed_scored(conn, {"a": 90, "b": 90, "c": 40}, detail={})
    assert [r["external_id"] for r in db.get_by_status(conn, "scored", min_score=75)] == ["a", "b"]
    # boundary: score == min_score is included (>= not >)
    assert [r["external_id"] for r in db.get_by_status(conn, "scored", min_score=90)] == ["a", "b"]
    assert [r["external_id"] for r in db.get_by_status(conn, "scored", limit=1)] == ["a"]


def test_get_by_status_null_score_excluded_by_min_score(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)  # 'new', score is NULL
    assert db.get_by_status(conn, "new", min_score=75) == []
