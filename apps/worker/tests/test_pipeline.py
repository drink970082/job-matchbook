"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

import json as _json
import sqlite3
import time

import pytest

from ats_worker import db, pipeline
from tests._helpers import (
    set_scored,
    LATER,
    NOW,
    bootstrap_db,
    make_posting as _posting,
    seed_new as _seed_new,
    seed_scored as _seed_scored,
)


# --- run_fetch ------------------------------------------------------------

def test_run_fetch_inserts_filtered_postings(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [
            _posting("1", job_title="Python Engineer", location="Remote"),
            _posting("2", job_title="Sales Rep", location="NYC"),
        ]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, ["engineer"], now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1
    rows = db.get_by_status(conn, "new")
    assert [r["external_id"] for r in rows] == ["1"]
    # run_fetch stamps the company's slug onto each ingested posting before upsert.
    assert rows[0]["company_slug"] == "acme"


def test_run_fetch_one_company_failing_does_not_abort(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        if slug == "bad":
            raise RuntimeError("boom")
        return [_posting("ok")]

    companies = [
        {"source": "greenhouse", "slug": "bad", "name": "Bad"},
        {"source": "lever", "slug": "good", "name": "Good"},
    ]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1


def test_run_fetch_logs_the_skipped_company(db_path, capsys):
    # The docstring promises "logged-and-skipped", but the bare except was silent —
    # a dead board / typo'd source vanished with no trace. It must now print.
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        raise RuntimeError("boom")

    companies = [{"source": "greenhouse", "slug": "bad", "name": "Bad"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    out = capsys.readouterr().out
    assert "greenhouse/bad" in out and "boom" in out


def test_run_fetch_requires_injected_fetch_fn():
    # fetch_fn defaults to None: the real adapter is wired only in run.py.
    import inspect
    assert inspect.signature(pipeline.run_fetch).parameters["fetch_fn"].default is None


def test_run_fetch_passes_now_to_the_workday_stub_gate(db_path):
    # workday's list stub dates are relative prose, so parse_stub needs `now` to make
    # them comparable. It reaches workday.fetch via kw; phenom.fetch takes no `now`.
    conn = db.connect(db_path)
    seen = {}

    def fetch_fn(source, slug, name, **kw):
        seen[source] = kw
        return []

    companies = [{"source": "workday", "slug": "t/wd5/s", "name": "W"},
                 {"source": "phenom", "slug": "x", "name": "P"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn, max_age_days=30)
    assert seen["workday"].get("now") == NOW      # threaded for workday
    assert "keep" in seen["workday"]
    assert "now" not in seen["phenom"]            # not for phenom (its fetch rejects it)
    assert "keep" in seen["phenom"]


def test_run_fetch_raises_when_fetch_fn_missing(db_path):
    # Omitting fetch_fn must fail loud (a wiring mistake), not degrade into a
    # per-company swallowed TypeError that silently fetches nothing.
    conn = db.connect(db_path)
    companies = [{"source": "greenhouse", "slug": "x", "name": "X"}]
    with pytest.raises(ValueError):
        pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=None)


def test_run_fetch_marks_location_miss_discarded(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("1", location="Shanghai, China"),
                _posting("2", location="Remote")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn,
                                  candidate={"locations": ["remote", "USA"]})
    assert inserted == 2  # both rows recorded; the miss is discarded, not dropped
    assert [r["external_id"] for r in db.get_by_status(conn, "discarded")] == ["1"]
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["2"]
    detail = _json.loads(db.get_by_status(conn, "discarded")[0]["score_detail"])
    assert detail["disqualified"] is True
    assert detail["screen"]["location"]["pass"] is False


def test_run_fetch_drops_stale_by_max_age(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("fresh", posted_at="2026-06-01"),
                _posting("stale", posted_at="2026-01-01")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn,
                                  max_age_days=30)
    assert inserted == 1
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["fresh"]


def test_run_fetch_drops_bodyless_postings(db_path, capsys):
    # A title-only row is permanent (ON CONFLICT DO NOTHING) and would reach the paid
    # fit scorer with no JD. It must be dropped at the board insert path, logged, and
    # recorded in feed_unresolved so the broken scraper surfaces (not just a log line).
    conn = db.connect(db_path)

    # `browser` is stub-gated now, so run_fetch hands it the `keep` the real adapter takes.
    def fetch_fn(source, slug, name, **kw):
        return [_posting("body"),
                _posting("empty", description="", job_url="https://x.co/empty")]

    companies = [{"source": "browser", "slug": "citadel.com", "name": "Citadel"}]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["body"]
    assert "browser/citadel.com" in capsys.readouterr().out
    unresolved = conn.execute(
        "SELECT feed, url, reason FROM feed_unresolved").fetchall()
    assert [(r["feed"], r["url"], r["reason"]) for r in unresolved] == [
        ("watchlist", "https://x.co/empty", "empty_description")]


def test_run_fetch_no_candidate_leaves_all_new(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("1", location="Shanghai, China")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["1"]
    assert db.get_by_status(conn, "discarded") == []


def test_run_fetch_passes_keep_only_to_stub_gate_sources(db_path):
    conn = db.connect(db_path)
    seen = {}

    def fetch_fn(source, slug, name, **kw):
        seen[source] = kw
        return [_posting(f"{source}-1", job_title="Python Engineer", location="Remote")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"},
                 {"source": "phenom", "slug": "h/d", "name": "Big Co"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn,
                       candidate={"locations": ["remote", "USA"]})
    assert "keep" not in seen["greenhouse"]
    assert callable(seen["phenom"]["keep"])


def test_run_fetch_keep_predicate_classifies_stubs(db_path):
    conn = db.connect(db_path)
    verdicts = {}

    def fetch_fn(source, slug, name, keep=None):
        for stub in (_posting("a", job_title="Sales Rep", location="Remote"),
                     _posting("b", job_title="Python Engineer", location="Shanghai, China"),
                     _posting("c", job_title="Python Engineer", location="Remote"),
                     _posting("d", job_title="Python Engineer", location="Remote",
                              posted_at="2026-01-01"),
                     _posting("e", job_title="Python Engineer", location=None)):
            verdicts[stub["external_id"]] = keep(stub)
        return []

    companies = [{"source": "phenom", "slug": "h/d", "name": "Big Co"}]
    pipeline.run_fetch(conn, companies, ["engineer"], now=NOW, fetch_fn=fetch_fn,
                       max_age_days=30, candidate={"locations": ["remote", "USA"]})
    assert verdicts == {"a": "drop",        # title miss -> silent drop
                        "b": "discard",     # location miss -> stored, un-hydrated
                        "c": "hydrate",     # survivor
                        "d": "drop",        # too old -> silent drop
                        "e": "hydrate"}     # no location -> resolve_location's
                                            # rule (A) treats missing as keep -> survivor
    # The predicate must be TOTAL — nothing try/excepts the keep() call in the
    # adapter, so a raise on a location-less stub would abort the whole board.
    assert verdicts["e"] == "hydrate"


def test_run_fetch_gated_batch_matches_the_ungated_statuses(db_path, tmp_path):
    # The gate must change which HTTP calls happen, never which status a row gets.
    rows = [_posting("1", job_title="Python Engineer", location="Shanghai, China"),
            _posting("2", job_title="Python Engineer", location="Remote"),
            _posting("3", job_title="Sales Rep", location="Remote")]
    cand = {"locations": ["remote", "USA"]}

    def gated_fetch_fn(source, slug, name, keep=None):
        # Mimics the adapter: 'drop' never comes back, 'discard' comes back
        # un-hydrated, survivors come back whole.
        return [dict(r, description="") if keep(r) == "discard" else r
                for r in rows if keep(r) != "drop"]

    def plain_fetch_fn(source, slug, name):
        return list(rows)

    conn = db.connect(db_path)
    pipeline.run_fetch(conn, [{"source": "phenom", "slug": "h/d", "name": "Co"}],
                       ["engineer"], now=NOW, fetch_fn=gated_fetch_fn, candidate=cand)
    gated = {s: [r["external_id"] for r in db.get_by_status(conn, s)]
             for s in ("new", "discarded")}

    conn2 = db.connect(bootstrap_db(tmp_path / "plain.db"))
    pipeline.run_fetch(conn2, [{"source": "greenhouse", "slug": "acme", "name": "Co"}],
                       ["engineer"], now=NOW, fetch_fn=plain_fetch_fn, candidate=cand)
    plain = {s: [r["external_id"] for r in db.get_by_status(conn2, s)]
             for s in ("new", "discarded")}

    assert gated == plain == {"new": ["2"], "discarded": ["1"]}


# --- run_expire -------------------------------------------------------------

DETAIL_SRC = "smartrecruiters"   # a real per-listing source (has fetch_one)


class _HTTPError(Exception):
    """Shaped like requests.HTTPError: carries .response.status_code."""

    def __init__(self, status):
        super().__init__(str(status))
        self.response = type("R", (), {"status_code": status})()


def _seed_live(conn, ids, *, source=DETAIL_SRC, status="scored"):
    db.upsert_postings(conn, [_posting(i, source=source) for i in ids], now=NOW)
    for r in conn.execute("SELECT id, external_id FROM job_postings").fetchall():
        if r["external_id"] in ids:
            set_scored(conn, r["id"], score_detail={}, now=NOW,
                          status=status)


def _statuses(conn):
    return {r["external_id"]: r["pipeline_status"]
            for r in conn.execute("SELECT * FROM job_postings").fetchall()}


@pytest.mark.parametrize("status", [404, 410])
def test_run_expire_closes_gone_listings_at_the_source(db_path, status):
    # Closure is source state: a 404/410 writes source_state='closed' and leaves the
    # lifecycle (and updated_at, which orders the screen/JEV queues) alone.
    conn = db.connect(db_path)
    _seed_live(conn, ["dead"])

    def fetch_one(source, slug, ext, name):
        raise _HTTPError(status)

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 1
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "scored"
    assert row["source_state"] == "closed"
    assert row["source_last_check_outcome"] == "confirmed_closed"
    assert row["source_last_checked_at"] == LATER
    assert row["updated_at"] == NOW


def test_run_expire_does_not_recheck_closed_rows(db_path):
    conn = db.connect(db_path)
    _seed_live(conn, ["shut"])
    conn.execute("UPDATE job_postings SET source_state='closed'")
    conn.commit()

    def fetch_one(source, slug, ext, name):
        raise AssertionError("a closed row must not be re-checked")

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 0


@pytest.mark.parametrize("exc", [_HTTPError(403), _HTTPError(500), RuntimeError("timeout")])
def test_run_expire_keeps_row_on_any_non_gone_error(db_path, exc):
    # A bot wall / 5xx / timeout must NEVER expire a live posting — wrongly
    # expiring a match costs the operator a job.
    conn = db.connect(db_path)
    _seed_live(conn, ["alive"])

    def fetch_one(source, slug, ext, name):
        raise exc

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 0
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert (row["pipeline_status"], row["source_state"]) == ("scored", "available")
    assert row["updated_at"] == NOW
    # The attempt is recorded as inconclusive (never 'found'), which rotates the row.
    assert row["source_last_check_outcome"] == "inconclusive"
    assert row["source_last_check_attempted_at"] == LATER
    assert row["source_last_checked_at"] is None


def test_run_expire_failing_rows_do_not_starve_the_queue(db_path):
    # A row whose check always errors (a 429 storm, an HTML page where JSON was
    # expected) used to stay at the head of the queue forever, so the sweep re-tried
    # the same `limit` rows every pass and never reached the rest.
    conn = db.connect(db_path)
    _seed_live(conn, ["broken", "next"])
    checked = []

    def fetch_one(source, slug, ext, name):
        checked.append(ext)
        if ext == "broken":
            raise _HTTPError(429)
        return _posting(ext, source=DETAIL_SRC)

    pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one, limit=1)
    pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one, limit=1)
    assert checked == ["broken", "next"]
    row = conn.execute("SELECT * FROM job_postings WHERE external_id='broken'").fetchone()
    assert row["source_last_check_error_category"] == "http_429"


def test_run_expire_hands_workday_fetch_one_the_job_path_not_the_guid(db_path):
    # #266: workday's fetch_one takes the /job/... path; the stored external_id is the
    # posting GUID. The default recheck key derives the path from the stored job_url.
    conn = db.connect(db_path)
    url = "https://acme.wd5.myworkdayjobs.com/Careers/job/NYC/Quant_R1"
    db.upsert_postings(conn, [_posting("0097a5", source="workday", job_url=url)], now=NOW)
    seen = []

    def fetch_one(source, slug, ext, name):
        seen.append((source, ext))
        raise _HTTPError(404)

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 1
    assert seen == [("workday", "/job/NYC/Quant_R1")]


def test_run_expire_skips_a_row_with_no_recheck_key(db_path):
    # No reliable key (a workday row whose job_url has no /job/ path): no request is
    # made, and the row is recorded inconclusive - never touched as alive.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting("0097a5", source="workday",
                                       job_url="https://acme.wd5.myworkdayjobs.com/Careers")],
                       now=NOW)

    def fetch_one(*a):
        raise AssertionError("no fetch without a recheck key")

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 0
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["source_state"] != "closed"
    assert (row["source_last_check_outcome"], row["source_last_check_error_category"],
            row["source_last_check_attempted_at"]) == ("inconclusive", "no_recheck_key", LATER)


def test_run_expire_touches_live_rows_to_rotate_the_queue(db_path):
    # A successful check rewrites updated_at, so the least-recently-checked
    # ordering hands the NEXT pass different rows (no dedicated column needed).
    conn = db.connect(db_path)
    _seed_live(conn, ["a", "b"])
    checked = []

    def fetch_one(source, slug, ext, name):
        checked.append(ext)
        return _posting(ext, source=DETAIL_SRC)

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one, limit=1) == 0
    assert checked == ["a"]
    pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one, limit=1)
    assert checked == ["a", "b"]         # 'a' rotated to the back


def test_run_expire_live_check_leaves_updated_at_alone(db_path):
    # updated_at orders the screen and JEV queues newest-first; a liveness check on a
    # `new` row must not move it to the front of them.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting("old", source=DETAIL_SRC)], now=NOW)
    before = conn.execute("SELECT updated_at FROM job_postings").fetchone()[0]
    pipeline.run_expire(conn, now=LATER,
                        detail_fetch_fn=lambda *a: _posting("old", source=DETAIL_SRC))
    row = conn.execute("SELECT updated_at, source_last_check_attempted_at "
                       "FROM job_postings").fetchone()
    assert tuple(row) == (before, LATER)


def test_run_expire_zero_budget_checks_nothing(db_path):
    conn = db.connect(db_path)
    _seed_live(conn, ["x"])
    assert pipeline.run_expire(
        conn, now=LATER, limit=0,
        detail_fetch_fn=lambda *a: (_ for _ in ()).throw(AssertionError("no fetch"))) == 0


def test_run_expire_rechecks_new_rows(db_path):
    # Nothing writes scored/notified any more, so `new` is the live inventory; a
    # new posting from a detail source must be checked for closure too.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting("fresh", source=DETAIL_SRC)], now=NOW)

    def fetch_one(source, slug, ext, name):
        raise _HTTPError(404)

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 1
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert (row["pipeline_status"], row["source_state"]) == ("new", "closed")


def test_run_expire_ignores_board_sources_and_dead_statuses(db_path):
    # Only live (new|scored|notified) rows from per-LISTING sources are re-checked:
    # a board source has no per-job endpoint, and 'discarded' rows aren't in the
    # operator's queue.
    conn = db.connect(db_path)
    _seed_live(conn, ["board"], source="greenhouse")
    _seed_live(conn, ["dropped"], status="discarded")
    _seed_new(conn, ["fresh"])

    def fetch_one(source, slug, ext, name):
        raise AssertionError(f"must not re-check {source}/{ext}")

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 0


def test_run_expire_declined_fetch_is_treated_as_alive(db_path):
    # fetch_one returning None means "couldn't build a request", not "gone".
    conn = db.connect(db_path)
    _seed_live(conn, ["x"], status="notified")

    assert pipeline.run_expire(
        conn, now=LATER, detail_fetch_fn=lambda *a: None) == 0
    assert _statuses(conn)["x"] == "notified"


# --- per-board health line: the thing that makes a teaser board visible ---

def test_run_fetch_logs_a_health_line_per_board(db_path, capsys):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name, **kw):
        return [_posting("a", description="x" * 2000), _posting("b", description="y" * 2200)]

    pipeline.run_fetch(conn, [{"source": "greenhouse", "slug": "acme", "name": "Acme"}],
                       None, now=NOW, fetch_fn=fetch_fn)
    line = [l for l in capsys.readouterr().out.splitlines() if "greenhouse/acme" in l][0]
    assert "fetched=2" in line and "kept=2" in line and "new=2" in line
    assert "desc_median=2200" in line
    assert "TEASER" not in line


def test_run_fetch_health_line_flags_a_teaser_board(db_path, capsys):
    """A board serving 250-char summaries reads as a healthy fetch: nothing is empty,
    nothing raises, `_valid_posting` passes. Only the median says otherwise."""
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name, **kw):
        return [_posting(str(i), description="teaser " * 35) for i in range(3)]

    pipeline.run_fetch(conn, [{"source": "custom", "slug": "ibm", "name": "IBM"}],
                       None, now=NOW, fetch_fn=fetch_fn)
    line = [l for l in capsys.readouterr().out.splitlines() if "custom/ibm" in l][0]
    assert "TEASER?" in line and "detail step" in line


def test_run_fetch_health_line_on_an_empty_board(db_path, capsys):
    conn = db.connect(db_path)
    pipeline.run_fetch(conn, [{"source": "lever", "slug": "gone", "name": "Gone"}],
                       None, now=NOW, fetch_fn=lambda *a, **kw: [])
    line = [l for l in capsys.readouterr().out.splitlines() if "lever/gone" in l][0]
    assert "fetched=0" in line and "desc_median=0" in line
    assert "TEASER" not in line, "an empty board is not a teaser board"
