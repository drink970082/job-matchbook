"""TDD for the worker's SQLite layer: WAL pragmas, dedup upsert, state writes."""
from __future__ import annotations

import json

from ats_worker import db
from tests._helpers import LATER, NOW, make_posting as posting


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
