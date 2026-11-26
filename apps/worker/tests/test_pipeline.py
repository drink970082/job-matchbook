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


def _verdicts(conn) -> dict:
    return {r["external_id"]: (r["pipeline_status"], r["verdict"]) for r in conn.execute(
        "SELECT external_id, pipeline_status, verdict FROM job_postings ORDER BY id")}


def _requirements(conn, external_id):
    return conn.execute(
        "SELECT s.state, s.result_json, s.backend, s.model, s.effort, s.evaluator_version, "
        "s.profile_version, p.score_detail, p.verdict_at FROM job_screenings s "
        "JOIN job_postings p ON p.id=s.job_posting_id WHERE p.external_id=?",
        (external_id,)).fetchone()


def test_run_fetch_stores_a_location_miss_as_a_requirements_discard(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("1", location="Shanghai, China"),
                _posting("2", location="Remote")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn,
                                  candidate={"locations": ["remote", "USA"]},
                                  profile_version=3)
    assert inserted == 2  # both rows recorded; the miss is discarded, not dropped
    assert _verdicts(conn) == {"1": ("new", "discarded"), "2": ("new", "pending")}
    req = _requirements(conn, "1")
    result = _json.loads(req["result_json"])
    assert result["disqualified"] is True
    assert result["screen"]["location"]["pass"] is False
    assert tuple(req)[0:1] + tuple(req)[2:] == (
        "complete", "deterministic", None, None, pipeline.SCREEN_EVALUATOR_VERSION, 3,
        None, NOW)
    assert _requirements(conn, "2") is None


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


def test_run_fetch_clears_the_unresolved_row_once_the_board_returns_the_body(db_path):
    conn = db.connect(db_path)
    bodies = {"1": "", "2": "", "3": ""}

    def fetch_fn(source, slug, name, **kw):
        return [_posting(i, description=d, job_url=f"https://x.co/{i}",
                         posted_at="2026-01-01" if i == "3" and d else "2026-06-01")
                for i, d in bodies.items()]

    def urls():
        return {r["url"] for r in conn.execute("SELECT url FROM feed_unresolved")}

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn, max_age_days=30)
    assert urls() == {"https://x.co/1", "https://x.co/2", "https://x.co/3"}
    # 1 is fixed and stored; 3 is fixed too, though its age now filters it out.
    bodies.update({"1": "a full description", "3": "a full description"})
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn, max_age_days=30)
    assert urls() == {"https://x.co/2"}
    # The still-empty row is refreshed, never deleted and re-recorded.
    assert [r["id"] for r in conn.execute("SELECT id FROM feed_unresolved")] == [2]
    # Already stored on the next pass: still cleared (the row may predate the clearing).
    db.record_unresolved(conn, feed="watchlist", url="https://x.co/1", company_name="Acme",
                         job_title="E", host="x.co", reason="empty_description", now=NOW)
    # A feed's own unresolved row for a URL the board serves is not the board's to clear.
    db.record_unresolved(conn, feed="simplify", url="https://x.co/3", company_name="Acme",
                         job_title="E", host="x.co", reason="unsupported_host", now=NOW)
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn, max_age_days=30)
    assert urls() == {"https://x.co/2", "https://x.co/3"}


def test_run_fetch_no_candidate_leaves_all_new(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("1", location="Shanghai, China")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    assert _verdicts(conn) == {"1": ("new", "pending")}


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
    gated = _verdicts(conn)

    conn2 = db.connect(bootstrap_db(tmp_path / "plain.db"))
    pipeline.run_fetch(conn2, [{"source": "greenhouse", "slug": "acme", "name": "Co"}],
                       ["engineer"], now=NOW, fetch_fn=plain_fetch_fn, candidate=cand)
    plain = _verdicts(conn2)

    assert gated == plain == {"1": ("new", "discarded"), "2": ("new", "pending")}


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
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    # Alive by default, but the check proved nothing: not 'found'.
    assert (row["source_state"], row["source_last_check_outcome"],
            row["source_last_check_error_category"]) == (
        "available", "inconclusive", "incomplete_content")


def test_run_expire_success_after_an_inconclusive_check_records_found(db_path):
    # A 429 pass then a served posting: the row must read as found, not keep the
    # stale 429 the web detail modal and MCP would report as a failed check.
    conn = db.connect(db_path)
    _seed_live(conn, ["x"])
    pipeline.run_expire(conn, now=NOW,
                        detail_fetch_fn=lambda *a: (_ for _ in ()).throw(_HTTPError(429)))
    pipeline.run_expire(conn, now=LATER,
                        detail_fetch_fn=lambda *a: _posting("x", source=DETAIL_SRC))
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert (row["source_last_check_outcome"], row["source_last_check_error_category"],
            row["source_last_checked_at"], row["source_last_check_attempted_at"]) == (
        "found", None, LATER, LATER)


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
    assert "fetched=0" in line and "desc_median=-" in line  # nothing measured
    assert "TEASER" not in line, "an empty board is not a teaser board"


# --- per-board health record (#231): the health line, persisted on the watchlist row ---

_HEALTH_COLS = ("last_fetched_at", "last_fetch_status", "last_fetched", "last_kept",
                "last_new", "last_bodyless", "last_detail_failed", "last_desc_median")


def _watch(conn, *boards):
    for source, slug in boards:
        conn.execute("INSERT INTO watched_companies (source, slug, name, created_at) "
                     "VALUES (?, ?, ?, ?)", (source, slug, slug.title(), NOW))
    conn.commit()


def _health(conn, source, slug):
    row = conn.execute(f"SELECT {', '.join(_HEALTH_COLS)} FROM watched_companies "
                       "WHERE source=? AND slug=?", (source, slug)).fetchone()
    return dict(zip(_HEALTH_COLS, row))


def test_run_fetch_records_each_boards_health_on_its_watchlist_row(db_path):
    conn = db.connect(db_path)
    _watch(conn, ("greenhouse", "acme"))

    def fetch_fn(source, slug, name, **kw):
        return [_posting("a", job_title="Engineer", description="x" * 2000),
                _posting("b", job_title="Engineer", description="y" * 2200),
                _posting("c", job_title="Engineer", description=""),
                _posting("d", job_title="Sales Rep")]

    pipeline.run_fetch(conn, [{"source": "greenhouse", "slug": "acme", "name": "Acme"}],
                       ["engineer"], now=NOW, fetch_fn=fetch_fn)
    assert _health(conn, "greenhouse", "acme") == {
        "last_fetched_at": NOW, "last_fetch_status": "ok", "last_fetched": 4,
        "last_kept": 2, "last_new": 2, "last_bodyless": 1, "last_detail_failed": 0, "last_desc_median": 2200}

    # A second pass: the same postings are already stored, so nothing is new.
    pipeline.run_fetch(conn, [{"source": "greenhouse", "slug": "acme", "name": "Acme"}],
                       ["engineer"], now=LATER, fetch_fn=fetch_fn)
    h = _health(conn, "greenhouse", "acme")
    assert (h["last_fetched_at"], h["last_new"], h["last_kept"]) == (LATER, 0, 2)


def test_a_failing_board_records_its_error_category_and_the_pass_goes_on(db_path):
    conn = db.connect(db_path)
    _watch(conn, ("greenhouse", "moved"), ("lever", "fine"))
    pipeline.run_fetch(conn, [{"source": "lever", "slug": "fine", "name": "Fine"}],
                       None, now=NOW, fetch_fn=lambda *a, **kw: [_posting("1", source="lever")])

    def fetch_fn(source, slug, name, **kw):
        if slug == "moved":
            raise _HTTPError(404)
        return []

    pipeline.run_fetch(conn, [{"source": "greenhouse", "slug": "moved", "name": "Moved"},
                              {"source": "lever", "slug": "fine", "name": "Fine"}],
                       None, now=LATER, fetch_fn=fetch_fn)
    assert _health(conn, "greenhouse", "moved") == {
        "last_fetched_at": LATER, "last_fetch_status": "http_404", "last_fetched": None,
        "last_kept": None, "last_new": None, "last_bodyless": None, "last_detail_failed": None, "last_desc_median": None}
    # The board after it was still fetched, and its record is this pass's (empty), not
    # the previous one's.
    assert _health(conn, "lever", "fine") == {
        "last_fetched_at": LATER, "last_fetch_status": "ok", "last_fetched": 0,
        "last_kept": 0, "last_new": 0, "last_bodyless": 0, "last_detail_failed": 0, "last_desc_median": None}


def _state(conn, slug):
    return db.board_health(conn.execute(
        "SELECT * FROM watched_companies WHERE slug=?", (slug,)).fetchone())


_REMOTE_ONLY = {"locations": ["remote", "USA"]}


def test_a_gate_discard_is_not_kept_and_not_measured(db_path):
    """A stub the location gate discards is stored as a requirements miss, returned
    un-hydrated: it is neither a kept posting nor a teaser description."""
    conn = db.connect(db_path)
    _watch(conn, ("phenom", "far"), ("phenom", "allfar"))

    def fetch_fn(source, slug, name, **kw):
        far = [_posting(f"{slug}{i}", source="phenom", location="Shanghai, China", description="")
               for i in range(5)]
        return far if slug == "allfar" else far + [_posting("ok", source="phenom", description="x" * 2000)]

    pipeline.run_fetch(conn, [{"source": "phenom", "slug": s, "name": s} for s in ("far", "allfar")],
                       None, now=NOW, fetch_fn=fetch_fn, candidate=_REMOTE_ONLY)
    far, allfar = _health(conn, "phenom", "far"), _health(conn, "phenom", "allfar")
    assert (far["last_kept"], far["last_new"], far["last_desc_median"]) == (1, 1, 2000)
    assert (allfar["last_kept"], allfar["last_desc_median"]) == (0, None)
    assert [_state(conn, "far"), _state(conn, "allfar")] == ["ok", "kept_zero"]
    assert conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0] == 11, "discards still stored"


def test_phenom_whose_hydrated_postings_all_came_back_bodyless_is_not_ok(db_path):
    """10 stubs: 4 discarded by the location gate, 6 hydrated, every one without a
    description (a failed detail or a moved selector)."""
    conn = db.connect(db_path)
    _watch(conn, ("phenom", "big"))

    def fetch_fn(source, slug, name, *, keep, **kw):
        out = []
        for i in range(10):
            stub = _posting(str(i), source="phenom", description="",
                            location="Shanghai, China" if i < 4 else "Remote")
            verdict = keep(stub)
            if verdict != "drop":
                out.append(stub)   # a discard un-hydrated; a hydrate whose detail gave nothing
        return out

    pipeline.run_fetch(conn, [{"source": "phenom", "slug": "big", "name": "Big"}], None,
                       now=NOW, fetch_fn=fetch_fn, candidate=_REMOTE_ONLY)
    h = _health(conn, "phenom", "big")
    assert (h["last_fetched"], h["last_kept"], h["last_bodyless"], h["last_detail_failed"]) == (10, 0, 6, 0)
    assert _state(conn, "big") == "bodyless"


def test_workday_whose_every_detail_get_was_throttled_reads_details_failed(db_path):
    conn = db.connect(db_path)
    _watch(conn, ("workday", "t/wd1/site"))

    def fetch_fn(source, slug, name, *, keep, now, **kw):
        for i in range(5):        # every stub passes the gate; every detail GET 429s
            keep({"external_id": None, "job_title": "Engineer", "location": "Remote"})
        return []                 # workday's _row returns None on a failed detail

    pipeline.run_fetch(conn, [{"source": "workday", "slug": "t/wd1/site", "name": "T"}], None,
                       now=NOW, fetch_fn=fetch_fn)
    h = _health(conn, "workday", "t/wd1/site")
    assert (h["last_fetched"], h["last_kept"], h["last_detail_failed"]) == (5, 0, 5)
    assert _state(conn, "t/wd1/site") == "details_failed"


class _SmartRecruitersOutage:
    """812 listed over 9 pages; every detail GET fails."""
    LIST = "https://api.smartrecruiters.com/v1/companies/Big/postings"

    def __init__(self):
        self.detail_gets = 0

    def get(self, url, params=None, timeout=None):
        from tests._helpers import FakeResponse
        if url == self.LIST:
            off = params["offset"]
            content = [{"id": f"p{i}", "name": "Engineer", "location": {"city": "Remote"}}
                       for i in range(off, min(off + 100, 812))]
            return FakeResponse({"totalFound": 812, "content": content})
        self.detail_gets += 1
        return FakeResponse(None, raise_exc=_HTTPError(503))


def test_smartrecruiters_listing_812_with_every_detail_failing_reads_details_failed(db_path):
    """Through the real adapter: listed is the list count, not what came back."""
    from ats_worker.fetch import fetch_company
    conn = db.connect(db_path)
    _watch(conn, ("smartrecruiters", "Big"))
    http = _SmartRecruitersOutage()
    pipeline.run_fetch(conn, [{"source": "smartrecruiters", "slug": "Big", "name": "Big"}], None,
                       now=NOW, fetch_fn=lambda s, sl, n, **kw: fetch_company(s, sl, n, session=http, **kw))
    h = _health(conn, "smartrecruiters", "Big")
    assert (h["last_fetched"], h["last_kept"], h["last_detail_failed"]) == (812, 0, 812)
    assert http.detail_gets == 812
    assert _state(conn, "Big") == "details_failed", "not `empty`: the board listed 812"


class _SmartRecruitersClosed(_SmartRecruitersOutage):
    """812 listed; every detail answers `active: false` (the list keeps closed postings)."""

    def get(self, url, params=None, timeout=None):
        from tests._helpers import FakeResponse
        if url == self.LIST:
            return super().get(url, params, timeout)
        self.detail_gets += 1
        return FakeResponse({"id": url.rsplit("/", 1)[1], "active": False})


def test_smartrecruiters_details_reporting_closed_are_not_details_failed(db_path):
    from ats_worker.fetch import fetch_company
    conn = db.connect(db_path)
    _watch(conn, ("smartrecruiters", "Big"))
    http = _SmartRecruitersClosed()
    pipeline.run_fetch(conn, [{"source": "smartrecruiters", "slug": "Big", "name": "Big"}], None,
                       now=NOW, fetch_fn=lambda s, sl, n, **kw: fetch_company(s, sl, n, session=http, **kw))
    h = _health(conn, "smartrecruiters", "Big")
    assert (h["last_fetched"], h["last_kept"], h["last_detail_failed"]) == (812, 0, 0)
    assert _state(conn, "Big") == "kept_zero"


@pytest.mark.parametrize("failed, state", [(6, "details_failed"), (2, "ok")])
def test_a_board_mostly_losing_its_details_is_not_healthy(db_path, failed, state):
    """10 stubs reach hydration: `failed` lose their detail, the rest are full JDs."""
    conn = db.connect(db_path)
    _watch(conn, ("workday", "t/wd1/site"))

    def fetch_fn(source, slug, name, *, keep, now, **kw):
        for i in range(10):
            keep({"external_id": None, "job_title": "Engineer", "location": "Remote"})
        return [_posting(str(i), source="workday", description="x" * 2000) for i in range(10 - failed)]

    pipeline.run_fetch(conn, [{"source": "workday", "slug": "t/wd1/site", "name": "T"}], None,
                       now=NOW, fetch_fn=fetch_fn)
    assert _health(conn, "workday", "t/wd1/site")["last_detail_failed"] == failed
    assert _state(conn, "t/wd1/site") == state


def test_a_board_whose_every_posting_came_back_bodyless_is_not_kept_zero(db_path):
    """A broken description selector is not the operator's filters keeping nothing."""
    conn = db.connect(db_path)
    _watch(conn, ("greenhouse", "broken"))
    pipeline.run_fetch(conn, [{"source": "greenhouse", "slug": "broken", "name": "Broken"}], None,
                       now=NOW, fetch_fn=lambda *a, **kw: [_posting(str(i), description="") for i in range(4)])
    row = conn.execute("SELECT * FROM watched_companies WHERE slug='broken'").fetchone()
    assert (row["last_fetched"], row["last_kept"], row["last_bodyless"]) == (4, 0, 4)
    assert db.board_health(row) == "bodyless"


def test_a_failed_health_write_after_a_good_fetch_keeps_the_board_ok(db_path, monkeypatch, capsys):
    """The postings were stored: the board is not counted failed nor recorded as an error."""
    conn = db.connect(db_path)
    _watch(conn, ("lever", "fine"))
    calls = []

    def flaky(conn, source, slug, **kw):
        calls.append(kw["status"])
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "record_board_health", flaky)
    counts: dict = {}
    inserted = pipeline.run_fetch(conn, [{"source": "lever", "slug": "fine", "name": "Fine"}], None,
                                  now=NOW, fetch_fn=lambda *a, **kw: [_posting("1", source="lever")],
                                  counts=counts)
    assert (inserted, counts["boards_failed"], calls) == (1, 0, ["ok"])
    assert "lever/fine: health not recorded" in capsys.readouterr().out


def test_a_health_write_that_fails_does_not_stop_the_pass(db_path, monkeypatch, capsys):
    """A locked database while recording one board's failure is logged; the next board
    is still fetched and stored (PRINCIPLES 6)."""
    conn = db.connect(db_path)
    _watch(conn, ("greenhouse", "moved"), ("lever", "fine"))
    real = db.record_board_health

    def flaky(conn, source, slug, **kw):
        if slug == "moved":
            raise sqlite3.OperationalError("database is locked")
        return real(conn, source, slug, **kw)

    monkeypatch.setattr(db, "record_board_health", flaky)

    def fetch_fn(source, slug, name, **kw):
        if slug == "moved":
            raise _HTTPError(404)
        return [_posting("1", source="lever")]

    inserted = pipeline.run_fetch(conn, [{"source": "greenhouse", "slug": "moved", "name": "Moved"},
                                         {"source": "lever", "slug": "fine", "name": "Fine"}],
                                  None, now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1
    assert _health(conn, "lever", "fine")["last_fetch_status"] == "ok"
    assert "greenhouse/moved: health not recorded" in capsys.readouterr().out


def test_a_stub_gate_board_counts_what_it_listed_not_what_it_returned(db_path):
    """A two-step board drops off-title stubs before their detail call, so what comes
    back understates the board. `fetched` is what it listed: 3 stubs, 2 dropped."""
    conn = db.connect(db_path)
    _watch(conn, ("phenom", "big"))

    def fetch_fn(source, slug, name, *, keep, **kw):
        stubs = [{"external_id": "1", "job_title": "Engineer"},
                 {"external_id": "2", "job_title": "Sales"},
                 {"external_id": "3", "job_title": "Chef"}]
        return [_posting(s["external_id"], source="phenom", job_title=s["job_title"])
                for s in stubs if keep(s) != "drop"]

    pipeline.run_fetch(conn, [{"source": "phenom", "slug": "big", "name": "Big"}],
                       ["engineer"], now=NOW, fetch_fn=fetch_fn)
    h = _health(conn, "phenom", "big")
    assert (h["last_fetched"], h["last_kept"], h["last_new"]) == (3, 1, 1)
