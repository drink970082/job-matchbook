"""TDD for pipeline.run_feed — the feed discovery stage.

Exercises the whole chain with fakes (no network): prefilter -> resolve ->
record-unresolved, then board-fetch keeping ONLY the surfaced ids, with the
skip-already-ingested optimisation and per-board failure isolation.
"""
from __future__ import annotations

import json

from ats_worker import db, pipeline
from tests._helpers import NOW, FIXTURES, make_posting as _posting

# Boards the fake adapter "serves": each returns the surfaced id + an extra one
# the feed did NOT surface, to prove we keep only what the feed asked for.
BOARD = {
    ("ashby", "acme"): ["aaaa-1111", "ashby-extra"],
    ("lever", "foobar"): ["bbbb-2222", "lever-extra"],
    ("greenhouse", "acmegh"): ["3333", "9999"],
    ("smartrecruiters", "Acme"): ["12345", "sr-extra"],
}


def _listings():
    return json.loads((FIXTURES / "simplify_listings.json").read_text())


def _feed_fn():
    return _listings()


# The simplify fixture's workday listing resolves to (workday, "acme/wd5/External",
# "R123"). Workday is special: the adapter emits a GUID as external_id and carries
# the surfaced jobReqId inside job_url, so run_feed matches on job_url substring.
# This fake serves one posting whose job_url contains R123 (the wanted reqId) plus
# a decoy whose job_url contains a DIFFERENT reqId — only the right one is kept.
_WORKDAY_POSTINGS = [
    _posting("GUID-MATCH", source="workday",
             job_url="https://acme.wd5.myworkdayjobs.com/External/job/Boston/Engineer_R123"),
    _posting("GUID-DECOY", source="workday",
             job_url="https://acme.wd5.myworkdayjobs.com/External/job/Boston/Other_R999"),
]


def _make_fetch_fn(calls, raise_for=None):
    def fetch_fn(source, slug, name):
        calls.append((source, slug, name))
        if raise_for and source == raise_for:
            raise RuntimeError("board down")
        if source == "workday":
            return list(_WORKDAY_POSTINGS)
        return [_posting(i, source=source) for i in BOARD.get((source, slug), [])]
    return fetch_fn


def test_run_feed_keeps_only_surfaced_ids_and_records_unresolved(db_path):
    conn = db.connect(db_path)
    calls: list = []
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_feed_fn, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn(calls),
    )

    # 5 resolvable survivors ingested (ashby, lever, greenhouse, smartrecruiters,
    # workday); each board's extra/decoy postings are NOT kept.
    assert inserted == 5
    rows = db.get_by_status(conn, "new")
    got = {(r["source"], r["external_id"]) for r in rows}
    assert got == {
        ("ashby", "aaaa-1111"), ("lever", "bbbb-2222"), ("greenhouse", "3333"),
        ("smartrecruiters", "12345"),
        # workday: the GUID is the external_id; the surfaced R123 lived in job_url.
        ("workday", "GUID-MATCH"),
    }

    # only the embedded-greenhouse survivor stays unresolved now (workday +
    # smartrecruiters resolve); it's recorded, never dropped.
    unresolved = conn.execute("SELECT reason FROM feed_unresolved").fetchall()
    assert {r["reason"] for r in unresolved} == {"embedded_greenhouse"}
    # inactive / Hardware / explicit-no-sponsorship listings never reach here.
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 1


def test_run_feed_workday_matches_reqid_substring_of_job_url(db_path):
    # Workday surfaces the per-tenant jobReqId (R123); the adapter emits a GUID as
    # external_id and carries R123 inside job_url. run_feed must keep the posting
    # whose job_url contains R123 and DROP the decoy (R999).
    conn = db.connect(db_path)
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_feed_fn,
        keep_categories=["Software", "AI/ML/Data", "Quant"], fetch_fn=_make_fetch_fn([]),
    )
    assert inserted == 5
    wd = conn.execute(
        "SELECT external_id, job_url FROM job_postings WHERE source='workday'"
    ).fetchall()
    assert len(wd) == 1
    assert wd[0]["external_id"] == "GUID-MATCH"
    assert "R123" in wd[0]["job_url"]


def test_run_feed_persists_company_slug(db_path):
    # The resolved group slug is stamped onto each ingested posting before upsert.
    conn = db.connect(db_path)
    pipeline.run_feed(
        conn, now=NOW, feed_fn=_feed_fn,
        keep_categories=["Software", "AI/ML/Data", "Quant"], fetch_fn=_make_fetch_fn([]),
    )
    slugs = dict(conn.execute(
        "SELECT source, company_slug FROM job_postings"
    ).fetchall())
    assert slugs["ashby"] == "acme"
    assert slugs["lever"] == "foobar"
    assert slugs["greenhouse"] == "acmegh"
    assert slugs["smartrecruiters"] == "Acme"
    assert slugs["workday"] == "acme/wd5/External"  # the resolved tenant/dc/site
    # every ingested row carries a non-null slug
    assert all(v is not None for v in slugs.values())


def test_run_feed_skips_boards_whose_surfaced_ids_already_exist(db_path):
    conn = db.connect(db_path)
    # Pre-ingest the only ashby id the feed surfaces.
    db.upsert_postings(conn, [_posting("aaaa-1111", source="ashby")], now=NOW)

    calls: list = []
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_feed_fn, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn(calls),
    )

    fetched_sources = {c[0] for c in calls}
    assert "ashby" not in fetched_sources           # fully satisfied -> board skipped
    assert {"lever", "greenhouse", "smartrecruiters", "workday"} <= fetched_sources
    assert inserted == 4    # lever + greenhouse + smartrecruiters + workday are new


def test_run_feed_isolates_a_failing_board(db_path):
    conn = db.connect(db_path)
    calls: list = []
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=_feed_fn, keep_categories=["Software", "AI/ML/Data", "Quant"],
        fetch_fn=_make_fetch_fn(calls, raise_for="greenhouse"),
    )
    # greenhouse aborts; ashby + lever + smartrecruiters + workday still ingest.
    assert inserted == 4
    rows = db.get_by_status(conn, "new")
    assert {r["source"] for r in rows} == {"ashby", "lever", "smartrecruiters", "workday"}


def test_run_feed_record_unresolved_upserts_on_repeat(db_path):
    conn = db.connect(db_path)
    calls: list = []
    for _ in range(2):
        pipeline.run_feed(
            conn, now=NOW, feed_fn=_feed_fn,
            keep_categories=["Software", "AI/ML/Data", "Quant"],
            fetch_fn=_make_fetch_fn(calls),
        )
    # url is the upsert key -> still exactly 1 row after two passes (only the
    # embedded-greenhouse listing stays unresolved now).
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 1


def test_run_feed_detail_source_fetches_each_surfaced_id(db_path):
    # Oracle is a detail-fetch source (no board-list endpoint): run_feed must call
    # detail_fetch_fn per surfaced id and stamp the resolved slug, no keep-filter.
    conn = db.connect(db_path)
    listings = [{
        "url": ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/"
                "en/sites/CX_1001/job/210706680"),
        "company_name": "JPMC", "title": "Quant Researcher",
        "category": "Quant", "sponsorship": "Other", "active": True,
    }]
    calls: list = []

    def detail_fetch_fn(source, slug, external_id, name):
        calls.append((source, slug, external_id, name))
        return _posting(external_id, source=source, job_url=f"https://x/{external_id}")

    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Quant"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=detail_fetch_fn,
    )
    assert inserted == 1
    assert calls == [("oracle", "jpmc.fa.oraclecloud.com/CX_1001", "210706680", "JPMC")]
    row = db.get_by_status(conn, "new")[0]
    assert (row["source"], row["external_id"]) == ("oracle", "210706680")
    assert row["company_slug"] == "jpmc.fa.oraclecloud.com/CX_1001"


def test_run_feed_detail_isolates_a_bad_listing(db_path):
    conn = db.connect(db_path)
    listings = [
        {"url": f"https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/{i}",
         "company_name": "JPMC", "title": "Quant", "category": "Quant",
         "sponsorship": "Other", "active": True}
        for i in ("good", "bad")
    ]

    def detail_fetch_fn(source, slug, external_id, name):
        if external_id == "bad":
            raise RuntimeError("listing down")
        return _posting(external_id, source=source)

    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Quant"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=detail_fetch_fn,
    )
    assert inserted == 1
    assert {r["external_id"] for r in db.get_by_status(conn, "new")} == {"good"}


def test_run_feed_detail_skips_none_result(db_path):
    conn = db.connect(db_path)
    listings = [{
        "url": "https://jobs.jobvite.com/acme/job/xyz", "company_name": "Acme",
        "title": "SWE", "category": "Software", "sponsorship": "Other", "active": True,
    }]
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=["Software"],
        fetch_fn=_make_fetch_fn([]), detail_fetch_fn=lambda *a: None,
    )
    assert inserted == 0
    assert db.get_by_status(conn, "new") == []


def test_run_feed_skips_listing_without_url(db_path):
    conn = db.connect(db_path)
    pipeline.run_feed(
        conn, now=NOW,
        feed_fn=lambda: [{"category": "Software", "active": True, "sponsorship": "Other"}],
        keep_categories=["Software"], fetch_fn=_make_fetch_fn([]),
    )
    assert conn.execute("SELECT COUNT(*) FROM feed_unresolved").fetchone()[0] == 0
    assert db.get_by_status(conn, "new") == []
