"""Tests for the DB-backed watchlist + feed bookkeeping helpers in db.py."""
from __future__ import annotations

from ats_worker import db
from tests._helpers import NOW, LATER, make_posting as _posting

_COMPANIES = [
    {"source": "greenhouse", "slug": "acme", "name": "Acme", "recipe": None},
    {"source": "lever", "slug": "foobar", "name": "Foobar", "recipe": None},
]


def test_import_and_get_watchlist(db_path):
    conn = db.connect(db_path)
    assert db.count_watchlist(conn) == 0
    inserted = db.import_watchlist(conn, _COMPANIES, now=NOW)
    assert inserted == 2
    assert db.count_watchlist(conn) == 2
    assert db.get_watchlist(conn) == _COMPANIES


def test_watchlist_recipe_round_trips_as_json(db_path):
    conn = db.connect(db_path)
    recipe = {"url": "https://x", "item_path": "jobs", "page": {"type": "offset"}}
    db.import_watchlist(conn, [
        {"source": "custom", "slug": "acme", "name": "Acme", "recipe": recipe},
    ], now=NOW)
    row = db.get_watchlist(conn)[0]
    assert row["recipe"] == recipe             # stored as JSON string, decoded on read


def test_import_watchlist_is_idempotent(db_path):
    conn = db.connect(db_path)
    db.import_watchlist(conn, _COMPANIES, now=NOW)
    # re-importing the same (source, slug) inserts nothing more
    again = db.import_watchlist(conn, _COMPANIES, now=LATER)
    assert again == 0
    assert db.count_watchlist(conn) == 2


def test_record_unresolved_inserts_then_upserts_on_url(db_path):
    conn = db.connect(db_path)
    url = "https://acme.wd5.myworkdayjobs.com/External/job/X_R1"
    db.record_unresolved(conn, feed="simplify", url=url, company_name="Acme",
                         job_title="SWE", host="acme.wd5.myworkdayjobs.com",
                         reason="workday_deferred", now=NOW)
    db.record_unresolved(conn, feed="simplify", url=url, company_name="Acme",
                         job_title="SWE", host="acme.wd5.myworkdayjobs.com",
                         reason="workday_deferred", now=LATER)
    rows = conn.execute("SELECT url, reason, created_at, updated_at FROM feed_unresolved").fetchall()
    assert len(rows) == 1                       # url is the upsert key
    assert rows[0]["created_at"] == NOW
    assert rows[0]["updated_at"] == LATER       # second pass refreshed it


def test_existing_external_ids(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [
        _posting("aaaa", source="ashby"),
        _posting("bbbb", source="ashby"),
        _posting("cccc", source="lever"),
    ], now=NOW)
    got = db.existing_external_ids(conn, "ashby", ["aaaa", "bbbb", "zzzz"])
    assert got == {"aaaa", "bbbb"}              # cccc is lever; zzzz absent
    assert db.existing_external_ids(conn, "ashby", []) == set()
