"""TDD for the worker's SQLite layer: WAL pragmas, dedup upsert, state writes."""
from __future__ import annotations

import json

import pytest

from ats_worker import db
from tests._helpers import LATER, NOW, make_posting as posting, seed_scored, set_scored


# --- connection / pragmas -------------------------------------------------

def test_connect_enables_wal_and_busy_timeout(db_path):
    conn = db.connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# --- app settings ---------------------------------------------------------

def test_upsert_setting_inserts_then_overwrites(db_path):
    conn = db.connect(db_path)
    db.upsert_setting(conn, "categories", '["Finance","Others"]', now=NOW)
    row = conn.execute(
        "SELECT value, updated_at FROM app_settings WHERE key='categories'"
    ).fetchone()
    assert row["value"] == '["Finance","Others"]'
    assert row["updated_at"] == NOW
    # a second call overwrites the same key in place (no duplicate row, bumps ts)
    db.upsert_setting(conn, "categories", '["Product"]', now=LATER)
    rows = conn.execute("SELECT value FROM app_settings WHERE key='categories'").fetchall()
    assert [r["value"] for r in rows] == ['["Product"]']


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


def test_update_refuses_unknown_column(db_path):
    # Defense-in-depth: _update builds its SET clause from dict keys, so a key
    # outside the allowlist must never reach the SQL string, even though today's
    # callers (save_score, mark_notified) only ever pass code-constant keys.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1")], now=NOW)
    pid = _one(conn)["id"]
    with pytest.raises(ValueError):
        db._update(conn, pid, {"job_title": "pwned"})  # not an allowed column


EVEN_LATER = "2026-06-04T10:00:00.000Z"


# --- the dedup invariant: a re-fetch must not clobber an in-flight posting --

def test_refetch_does_not_clobber_scored_posting(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1", job_title="Original")], now=NOW)
    pid = _one(conn)["id"]
    set_scored(conn, pid, score=88, score_detail={"k": 1}, now=LATER)  # -> scored
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


# --- save_score status override (disqualify -> discarded) -----------------


# --- get_by_status ordering --

def test_get_by_status_orders_by_score_then_id(db_path):
    conn = db.connect(db_path)
    seed_scored(conn, {"a": 90, "b": 90, "c": 40}, detail={})
    rows = db.get_by_status(conn, "scored")
    assert [r["external_id"] for r in rows] == ["a", "b", "c"]  # 90s by id, then 40


def test_upsert_stores_board_posted_at(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1", posted_at="2026-04-17")], now=NOW)
    row = db.get_by_status(conn, "new")[0]
    assert row["posted_at"] == "2026-04-17"


def test_upsert_falls_back_to_scrape_date_when_no_posted_at(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("2")], now=NOW)   # make_posting has no posted_at
    row = db.get_by_status(conn, "new")[0]
    assert row["posted_at"] == NOW[:10]                 # "2026-06-04"


# --- get_notifiable (verdict-based notify gate) ---------------------------

# >= 200 chars so the description-length low-context gate (mirrors the web's
# LOW_CONTEXT_MAX_DESCRIPTION_LENGTH) does NOT hold these rows back.
LONG_DESC = "Build backend services in Python and Go across data pipelines. " * 4


# --- upsert with optional per-row pipeline_status + score_detail ----------

def test_upsert_honors_pipeline_status_and_score_detail(db_path):
    conn = db.connect(db_path)
    p = posting("1", pipeline_status="discarded",
                score_detail={"disqualified": True,
                              "disqualification_reason": "location: on-site in China"})
    db.upsert_postings(conn, [p], now=NOW)
    rows = db.get_by_status(conn, "discarded")
    assert [r["external_id"] for r in rows] == ["1"]
    detail = json.loads(rows[0]["score_detail"])
    assert detail["disqualified"] is True


def test_upsert_defaults_status_new_and_null_detail(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("2")], now=NOW)
    row = db.get_by_status(conn, "new")[0]
    assert row["external_id"] == "2"
    assert row["score_detail"] is None


