"""Closure detection (#230): a posting its board stops listing becomes
source_state='closed' after 3 consecutive successful, non-empty list fetches.

PRINCIPLES 3: only a positive "the complete list does not contain it" closes. A failed
or empty fetch never counts, and a posting a local filter dropped is still listed.
"""
from __future__ import annotations

import pytest

from ats_worker import db, pipeline
from ats_worker.fetch import ABSENCE_CLOSURE_SOURCES
from tests._helpers import NOW, make_posting

PASS_TIMES = [f"2026-06-0{d}T08:00:00.000Z" for d in range(5, 10)]


def _row(conn, ext, source="greenhouse"):
    return conn.execute("SELECT * FROM job_postings WHERE source=? AND external_id=?",
                        (source, ext)).fetchone()


def _board(source="greenhouse", slug="acme"):
    return [{"source": source, "slug": slug, "name": "Acme"}]


def _seed(conn, ids, source="greenhouse", slug="acme"):
    db.upsert_postings(conn, [make_posting(i, source=source, company_slug=slug)
                              for i in ids], now=NOW)


def _lister(listings):
    """fetch_fn serving one listing per pass; an Exception entry raises."""
    it = iter(listings)

    def fetch_fn(source, slug, name, **kw):
        nxt = next(it)
        if isinstance(nxt, Exception):
            raise nxt
        return [make_posting(i, source=source) for i in nxt]
    return fetch_fn


def _passes(conn, fetch_fn, n, *, board=None, title_filter=None, **kw):
    for now in PASS_TIMES[:n]:
        pipeline.run_fetch(conn, _board(**(board or {})), title_filter, now=now,
                           fetch_fn=fetch_fn, **kw)


def test_dropped_id_closes_after_third_successful_pass_not_second(db_path):
    conn = db.connect(db_path)
    _seed(conn, ["kept", "gone"])
    fetch_fn = _lister([["kept"]] * 3)

    _passes(conn, fetch_fn, 2)
    assert _row(conn, "gone")["source_state"] == "available"
    _passes(conn, fetch_fn, 1)
    assert _row(conn, "gone")["source_state"] == "closed"
    assert _row(conn, "kept")["source_state"] == "available"
    # Closure is source state, not lifecycle.
    assert _row(conn, "gone")["pipeline_status"] == "new"


def test_failed_and_empty_fetches_do_not_advance_the_count(db_path):
    conn = db.connect(db_path)
    _seed(conn, ["kept", "gone"])
    fetch_fn = _lister([["kept"], RuntimeError("boom"), [], ["kept"], ["kept"]])

    _passes(conn, fetch_fn, 4)
    assert _row(conn, "gone")["source_state"] == "available"
    assert _row(conn, "gone")["source_absent_count"] == 2
    _passes(conn, fetch_fn, 1)
    assert _row(conn, "gone")["source_state"] == "closed"


def test_relisting_resets_the_count_and_reopens(db_path):
    conn = db.connect(db_path)
    _seed(conn, ["kept", "flaky"])
    fetch_fn = _lister([["kept"], ["kept"], ["kept", "flaky"], ["kept"], ["kept"]])

    _passes(conn, fetch_fn, 3)
    assert _row(conn, "flaky")["source_absent_count"] == 0
    _passes(conn, fetch_fn, 2)
    assert _row(conn, "flaky")["source_state"] == "available"

    conn.execute("UPDATE job_postings SET source_state='closed' WHERE external_id='flaky'")
    pipeline.run_fetch(conn, _board(), None, now=PASS_TIMES[4],
                       fetch_fn=lambda *a, **k: [make_posting("flaky")])
    row = _row(conn, "flaky")
    assert (row["source_state"], row["source_last_seen_at"]) == ("available", PASS_TIMES[4])


def test_other_boards_of_the_same_source_are_untouched(db_path):
    conn = db.connect(db_path)
    _seed(conn, ["kept"])
    _seed(conn, ["elsewhere"], slug="other")
    _passes(conn, _lister([["kept"]] * 3), 3)
    assert _row(conn, "elsewhere")["source_state"] == "available"
    assert _row(conn, "elsewhere")["source_absent_count"] == 0


def test_max_age_dropped_posting_is_still_stamped_seen(db_path):
    conn = db.connect(db_path)
    _seed(conn, ["fresh", "old"])

    def fetch_fn(source, slug, name, **kw):
        return [make_posting("fresh", posted_at="2026-06-01"),
                make_posting("old", posted_at="2026-01-01")]

    _passes(conn, fetch_fn, 3, max_age_days=30)
    row = _row(conn, "old")
    assert row["source_state"] == "available"
    assert row["source_last_seen_at"] == PASS_TIMES[2]
    assert row["source_absent_count"] == 0


def test_stub_gate_dropped_stub_is_still_listed(db_path):
    # icims drops a title-filtered stub inside fetch (keep -> 'drop'); run_fetch never
    # sees it in the returned list, only through the gate. It must still count as listed.
    conn = db.connect(db_path)
    _seed(conn, ["eng", "sales"], source="icims")

    def fetch_fn(source, slug, name, keep=None, **kw):
        stubs = [make_posting("eng", source=source, job_title="Engineer"),
                 make_posting("sales", source=source, job_title="Sales Rep")]
        return [s for s in stubs if keep(s) != "drop"]

    _passes(conn, fetch_fn, 3, board={"source": "icims"},
            title_exclude=["sales"])
    row = _row(conn, "sales", source="icims")
    assert (row["source_state"], row["source_last_seen_at"]) == ("available", PASS_TIMES[2])


@pytest.mark.parametrize("source", ["workday", "smartrecruiters", "phenom", "browser",
                                    "icims", "custom"])
def test_sources_without_a_complete_id_list_never_close_by_absence(db_path, source):
    # workday stubs carry no stored id (jobReqId, not the GUID) and its detail failure
    # drops the row; smartrecruiters also drops on detail failure; phenom salvages a
    # throttled board as a short list; browser pagination ends on a render that timed
    # out; icims ends on the first page with no parsed cards; a custom recipe may fetch
    # one capped page. None of those lists proves absence. workday/smartrecruiters stay covered by
    # run_expire's per-id check.
    assert source not in ABSENCE_CLOSURE_SOURCES
    conn = db.connect(db_path)
    _seed(conn, ["kept", "gone"], source=source)
    _passes(conn, _lister([["kept"]] * 5), 5, board={"source": source})
    row = _row(conn, "gone", source=source)
    assert (row["source_state"], row["source_absent_count"]) == ("available", 0)
    # A returned id is still a positive observation.
    assert _row(conn, "kept", source=source)["source_last_seen_at"] == PASS_TIMES[4]


def test_absence_closure_sources_are_complete_list_boards():
    assert ABSENCE_CLOSURE_SOURCES == {"greenhouse", "lever", "ashby", "pinpoint",
                                       "workable"}


def test_listing_scope_is_the_board_for_both_stamp_and_count(db_path):
    # Board "other" listing an id stored under board "acme" must not stamp or reset
    # acme's row; only acme's own lists decide it.
    conn = db.connect(db_path)
    _seed(conn, ["kept", "shared"])
    _passes(conn, _lister([["kept"]] * 2), 2)
    db.record_board_listing(conn, "greenhouse", "other", ["shared"], now=PASS_TIMES[2],
                            count_absence=True)
    row = _row(conn, "shared")
    assert (row["source_absent_count"], row["source_last_seen_at"]) == (2, NOW)
    _passes(conn, _lister([["kept"]]), 1)
    assert _row(conn, "shared")["source_state"] == "closed"


def test_closed_rows_leave_the_screen_and_jev_queues(db_path):
    conn = db.connect(db_path)
    _seed(conn, ["open", "shut"])
    conn.execute("UPDATE job_postings SET source_state='closed' WHERE external_id='shut'")
    conn.commit()
    assert [r["external_id"] for r in db.get_screen_candidates(conn)] == ["open"]
    for r in conn.execute("SELECT id FROM job_postings").fetchall():
        db.save_screening(conn, r["id"], state="complete",
                          result={"screen": {}, "disqualified": False,
                                  "disqualification_reason": ""},
                          error_category=None, backend="ollama", model="m",
                          effort=None, evaluator_version="v", now=NOW)
    ids = [r["external_id"] for r in db.get_jev_candidates(conn, "sha", "2000-01-01")]
    assert ids == ["open"]
