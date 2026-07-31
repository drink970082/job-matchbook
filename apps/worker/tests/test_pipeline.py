"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

import json as _json
import sqlite3
import time

import pytest

from ats_worker import db, pipeline, score
from tests._helpers import (
    LATER,
    NOW,
    bootstrap_db,
    make_posting as _posting,
    seed_new as _seed_new,
    seed_scored as _seed_scored,
)


# A JD that actually STATES a clearance bar. `score._check_clearance` needs one before
# it will honour `requires_clearance: true` — an ungrounded claim is the 2026-07-27
# defect and is now kept. Long enough to clear the thin-JD gate and reach the fit call.
_CLEARED_DESC = ("Build backend services in Python and Go across data pipelines. " * 3
                 + "Other Requirements: Security Clearance Requirements: this role "
                   "requires an active TS/SCI clearance with polygraph.")


def _assessment(**over):
    """A minimally-valid fit assessment scorecard — passes score._normalize_score's
    enum checks (seniority/domain verdicts) so a fit_fn fake's card doesn't itself
    raise ScoreError before run_score's fallback logic is what's under test."""
    base = {
        "seniority": {"verdict": "match", "note": ""},
        "domain": {"verdict": "match", "note": ""},
        "must_haves": {"met": [], "missing": []},
        "nice_to_haves": {"missing": []},
        "summary": "",
    }
    base.update(over)
    return base


def _card(**over):
    """A minimally-valid fit scorecard (score + assessment) — the shape a real
    fit_fn returns, for tests that don't care about the score value itself."""
    base = {"score": 80, "assessment": _assessment()}
    base.update(over)
    return base


def _seeded_conn(tmp_path, rows: int):
    """A fresh, connected DB seeded with `rows` 'new' postings titled row-1..row-N
    (1-indexed, so a test can pick one out by name) with a realistic (long-enough)
    description that clears the low-context gate and reaches the fit scorer."""
    conn = db.connect(bootstrap_db(tmp_path / "applications.db"))
    postings = [_posting(str(i), job_title=f"row-{i}") for i in range(1, rows + 1)]
    db.upsert_postings(conn, postings, now=NOW)
    return conn


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

    def fetch_fn(source, slug, name):
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


# --- run_score ------------------------------------------------------------

def test_run_score_only_new_and_one_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])

    # The failure is a screen-stage error (e.g. Ollama down) — one bad SCREEN
    # call must not abort the pass; the other two rows still get scored.
    def screen_fn(posting):
        if posting["external_id"] == "2":
            raise RuntimeError("ollama down")
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 90, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "scored"
    assert statuses["3"] == "scored"
    assert statuses["2"] == "failed"


def test_run_score_limit_caps_rows_scored(db_path):
    # Operator quota control: limit=N screens/scores only N 'new' rows; the rest
    # stay 'new' for a later pass. The paid scorer is what limit protects.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3", "4", "5"])
    scored = []

    def screen_fn(posting):
        scored.append(posting["external_id"])
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 90, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn, limit=2)
    assert len(scored) == 2
    assert len(db.get_by_status(conn, "new")) == 3
    assert len(db.get_by_status(conn, "scored")) == 2


def test_run_score_summary_reports_the_whole_queue_not_just_the_capped_slice(db_path,
                                                                             capsys):
    # `left 'new'` used to be computed as len(rows) - done over the SLICE, so a capped
    # pass always printed "0 left 'new'" — on the daemon, six times a day, while
    # thousands of rows waited. A queue that is not draining must not read as drained.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3", "4", "5"])
    pipeline.run_score(conn, now=NOW, limit=2,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=lambda ps: [{"score": 90, "assessment": _assessment()}
                                          for _ in ps])
    out = capsys.readouterr().out
    assert "then 2 row(s):" in out           # the cap is what the pass PAID for
    assert "0 unreached" in out             # nothing in the slice was skipped
    assert "3 left 'new'" in out            # and the rest of the queue is visible


def test_run_score_limit_takes_the_newest_rows_not_the_oldest(db_path):
    # The half of --score-limit that decides whether running on a schedule is worth
    # anything: a bounded pass must reach the postings discovered THIS pass, not chew
    # the back of a backlog that a job found today would sit behind for weeks.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3", "4", "5"])
    scored = []

    def screen_fn(posting):
        scored.append(posting["external_id"])
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 90, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn, limit=2)
    assert sorted(scored) == ["4", "5"]
    assert sorted(r["external_id"] for r in db.get_by_status(conn, "new")) \
        == ["1", "2", "3"]


def test_run_score_reaches_a_retried_row_inside_the_cap(db_path):
    # The other half of the ordering, and the one "newest id first" gets WRONG:
    # run_retry requeues a 'failed' row to 'new' keeping its ORIGINAL id, and SPEC
    # §7.1 promises it is rescored THAT SAME pass. Under plain id DESC an old failed
    # row sorts behind the whole backlog and a capped pass never reaches it — the
    # retry budget would burn down without a single retry being attempted.
    conn = db.connect(db_path)
    _seed_new(conn, ["old-failed", "2", "3", "4", "5"])
    db.mark_failed(conn, 1, error="screen blew up", now=NOW)
    assert pipeline.run_retry(conn, now=LATER) == 1
    scored = []

    def screen_fn(posting):
        scored.append(posting["external_id"])
        return {"disqualified": False}

    pipeline.run_score(conn, now=LATER, limit=2, screen_fn=screen_fn,
                       fit_fn=lambda ps: [{"score": 90, "assessment": _assessment()}
                                          for _ in ps])
    # the requeued row is FIRST (touched this pass), then the newest untouched id
    assert scored == ["old-failed", "5"]


def test_run_score_max_id_selects_the_low_ids_the_cap_cannot_reach(db_path):
    # The recovery selector (PROGRESS queue item 2). --score-limit bounds the SPEND
    # from the newest end; it can never name the OLDEST rows, which is exactly where a
    # --rescreen-discarded recovery target sits: requeue_discarded stamps updated_at on
    # every discard at once, so they tie and break by id DESC, and the wrongly-discarded
    # rows are among the lowest ids in that tied set. max_id selects from the other end.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3", "4", "5"])
    scored = []

    def screen_fn(posting):
        scored.append(posting["external_id"])
        return {"disqualified": False}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [{"score": 90, "assessment": _assessment()}
                                          for _ in ps],
                       max_id=2)
    # ids 1-2 only, and still newest-first WITHIN the selection
    assert scored == ["2", "1"]
    assert sorted(r["external_id"] for r in db.get_by_status(conn, "new")) \
        == ["3", "4", "5"]


def test_run_score_max_id_applies_before_the_limit(db_path):
    # Order matters and only one order is useful: select the id range, THEN bound the
    # spend inside it. Limit-then-select would hand the cap to the newest rows and
    # filter them all away, so the pass would score nothing while looking bounded.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3", "4", "5"])
    scored = []

    def screen_fn(posting):
        scored.append(posting["external_id"])
        return {"disqualified": False}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [{"score": 90, "assessment": _assessment()}
                                          for _ in ps],
                       max_id=3, limit=2)
    assert scored == ["3", "2"]


def _dq(reason, **checks):
    """A screen verdict shaped the way _screen_verdict/deterministic_screen build one:
    per-check entries AND the joined reason string."""
    return {"screen": {k: {"pass": v, "note": ""} for k, v in checks.items()},
            "disqualified": True, "disqualification_reason": reason}


def test_a_degree_only_fail_is_confirmed_by_the_strong_model_not_discarded(db_path):
    # PROGRESS queue item 3. The 4B reads a soft degree bar as hard on a handful of rows
    # and the posting is DELETED — reviewed by nobody. Routing turns each into one paid
    # fit call, where the strong model's own extraction is arbitrated by the same CODE.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    fit_calls = []

    def fit_fn(postings):
        fit_calls.append(len(postings))
        # The strong model says no degree is required -> the row survives.
        return [{"score": 88, "assessment": _assessment(),
                 "screen": {"degree": {"required_degree": None}}} for _ in postings]

    pipeline.run_score(conn, now=NOW,
                       screen_fn=lambda p: _dq("degree: requires a PhD", degree=False),
                       fit_fn=fit_fn, candidate={"highest_degree": "bachelor"})
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "scored"
    assert fit_calls == [1]                       # it DID reach the paid scorer
    detail = _json.loads(row["score_detail"])
    assert detail["needs_confirmation"] == ["degree"]   # and says why it got there


def test_the_strong_model_can_still_confirm_the_bar_and_discard(db_path):
    # Routing must not become "keep everything": when the strong model's extraction
    # agrees a higher degree is required, CODE re-applies the candidate's constraint and
    # the row lands 'discarded' exactly as before — just one paid call later.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(
        conn, now=NOW,
        screen_fn=lambda p: _dq("degree: requires a doctorate", degree=False),
        fit_fn=lambda ps: [{"score": 70, "assessment": _assessment(),
                            "screen": {"degree": {"required_degree": "phd"}}}
                           for _ in ps],
        candidate={"highest_degree": "bachelor"})
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "discarded"
    detail = _json.loads(row["score_detail"])
    # The reason is REGENERATED from the strong model's extraction, not the 4B string the
    # demotion cleared ("requires a doctorate"). That is the point of clearing the verdict
    # rather than flipping it: what lands in the DB is the confirming model's answer.
    assert detail["disqualification_reason"] == "degree: requires phd"
    assert detail["needs_confirmation"] == ["degree"]   # provenance survives the discard


def test_a_location_fail_alongside_degree_is_still_discarded_free(db_path):
    # The routing is scoped to the two SEMANTIC checks a 4B gets wrong. location and
    # internships are deterministic CODE gates with no model judgment in them, so a row
    # failing one of those must never buy a paid call to re-litigate it.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])
    fit_calls = []

    def screen_fn(posting):
        if posting["external_id"] == "1":
            return _dq("degree: requires a PhD; location: on-site in Canada",
                       degree=False, location=False)
        return _dq("internship/co-op role", internships=False)

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: fit_calls.append(len(ps)) or [_card() for _ in ps],
                       candidate={"highest_degree": "bachelor"})
    assert sorted(r["external_id"] for r in db.get_by_status(conn, "discarded")) == ["1", "2"]
    assert fit_calls == []


def test_a_disqualification_with_no_per_check_verdicts_is_not_routed(db_path):
    # The conservative default. A screen that reports `disqualified` without per-check
    # entries gives nothing to classify — routing it would mean paying for every
    # disqualification whose shape we cannot read. Stays free and terminal.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    fit_calls = []
    pipeline.run_score(conn, now=NOW,
                       screen_fn=lambda p: {"disqualified": True,
                                            "disqualification_reason": "requires a PhD"},
                       fit_fn=lambda ps: fit_calls.append(len(ps)) or [_card() for _ in ps],
                       candidate={"highest_degree": "bachelor"})
    assert db.get_by_status(conn, "discarded")[0]["external_id"] == "1"
    assert fit_calls == []


def test_the_fallback_cannot_overturn_a_check_the_screen_already_answered(db_path):
    # The defect routing newly exposed. merge_fallback_screen only runs when the screen
    # left a GAP, and until now nothing cleared one — so nobody noticed that
    # _screen_verdict re-rules every CONFIGURED check, not just the gap keys. With no
    # entry and no snippets, `authorization` falls through to the blunt NO_SPONSOR_PHRASES
    # substring floor: the exact path that produced both long-standing IMC false
    # positives. Result was a row discarded on `authorization` while its own score_detail
    # recorded authorization as PASSING — and the paid call that had just kept it thrown
    # away. Only the cleared check may rule here.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    # The screen passed authorization on real model labels; degree is the only failure.
    screen = {"screen": {"degree": {"pass": False, "note": "requires a PhD"},
                         "authorization": {"pass": True, "note": ""}},
              "disqualified": True, "disqualification_reason": "degree: requires a PhD"}
    conn.execute(
        "UPDATE job_postings SET description=? WHERE external_id='1'",
        # carries a NO_SPONSOR_PHRASES substring inside an INVITATION to apply
        ["We welcome all backgrounds. If you are eligible to work without sponsorship, "
         "we encourage you to apply. " + "Build trading systems. " * 20],
    )
    pipeline.run_score(
        conn, now=NOW, screen_fn=lambda p: screen,
        fit_fn=lambda ps: [{"score": 91, "assessment": _assessment(),
                            "screen": {"degree": {"required_degree": None}}} for _ in ps],
        candidate={"highest_degree": "bachelor", "work_authorization": "needs sponsorship"})
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    detail = _json.loads(row["score_detail"])
    assert row["pipeline_status"] == "scored"
    assert detail["screen"]["authorization"]["pass"] is True
    assert "disqualification_reason" not in detail


def test_a_thin_jd_demotion_is_not_counted_as_a_confirmation(db_path, capsys):
    # A demoted row below the low-context threshold takes the thin-JD path, which spends
    # NO fit call — so nothing confirms the cleared check. Counting it would inflate the
    # one number on the line that is supposed to mean "this cost quota".
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    conn.execute("UPDATE job_postings SET description='too thin' WHERE external_id='1'")
    fit_calls = []
    pipeline.run_score(conn, now=NOW,
                       screen_fn=lambda p: _dq("degree: requires a PhD", degree=False),
                       fit_fn=lambda ps: fit_calls.append(len(ps)) or [_card() for _ in ps],
                       candidate={"highest_degree": "bachelor"})
    out = capsys.readouterr().out
    assert fit_calls == []
    assert "1 thin-JD (no fit call)" in out
    assert "0 sent for confirmation" in out
    # The marker still rides along — it names a confirmation the row STILL NEEDS, which
    # is true, and the row is held under Low-context for a human either way.
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert _json.loads(row["score_detail"])["needs_confirmation"] == ["degree"]


def test_a_confirming_row_is_not_double_counted_in_the_pass_accounting(db_path, capsys):
    # `done` must count each row exactly once. Adding `confirming` to it drives
    # `unreached` NEGATIVE, and no existing accounting test has a confirming row in it.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(conn, now=NOW,
                       screen_fn=lambda p: _dq("degree: requires a PhD", degree=False),
                       fit_fn=lambda ps: [_card() for _ in ps],
                       candidate={"highest_degree": "bachelor"})
    out = capsys.readouterr().out
    assert "1 sent for confirmation" in out
    assert "0 unreached" in out


def test_a_routed_row_reports_as_confirming_not_as_screen_discarded(db_path, capsys):
    # The summary line is the only per-pass signal. A routed row is a quota-SPENDING
    # outcome, so counting it as 'screen-discarded' (which means "cost nothing") would
    # hide exactly the number this feature moves.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(conn, now=NOW,
                       screen_fn=lambda p: _dq("clearance: requires a clearance",
                                               clearance=False),
                       fit_fn=lambda ps: [_card() for _ in ps],
                       candidate={"security_clearance": "none"})
    out = capsys.readouterr().out
    assert "0 screen-discarded" in out
    assert "1 sent for confirmation" in out


def test_run_score_thin_jd_skips_paid_fit(db_path):
    # A screen-surviving JD shorter than the low-context threshold must NOT reach the
    # paid fit scorer — it's marked scored + insufficient_context directly, since the
    # UI/notify gate would hold it back anyway. Saves a Codex message per thin JD.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting("thin", description="Too short.")], now=NOW)

    def screen_fn(posting):
        return {"disqualified": False, "screen": {}}

    def fit_fn(postings):
        raise AssertionError("thin JD must not reach the paid fit scorer")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    row = db.get_by_status(conn, "scored")[0]
    assert row["external_id"] == "thin"
    assert _json.loads(row["score_detail"])["insufficient_context"] is True
    # and it is held back from notify (below the low-context length bar)
    assert db.get_notifiable(conn) == []


class _FlakyWriteConn:
    """Wraps a real connection and fails the COMMIT for chosen posting ids -- the
    SQLITE_BUSY-past-busy_timeout shape, where the UPDATE has already executed."""

    def __init__(self, conn, fail_ids):
        self._conn = conn
        self._fail_ids = set(fail_ids)
        self._pending = None

    def execute(self, sql, *args, **kw):
        params = args[0] if args else {}
        self._pending = params.get("id") if isinstance(params, dict) else None
        return self._conn.execute(sql, *args, **kw)

    def commit(self):
        if self._pending in self._fail_ids:
            raise sqlite3.OperationalError("database is locked")
        return self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_an_unwritable_free_gate_discard_stays_new_and_says_so(db_path, capsys):
    # Containment: one row the sweep cannot write must not abort the pass, must not
    # consume a budget slot, and must genuinely stay 'new' -- db._update commits after
    # executing, so without a rollback the failed UPDATE rides along on the NEXT row's
    # commit and the row would be discarded while the warning claimed otherwise.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [
        _posting("dead1", job_title="dead1", location="Bengaluru, India"),
        _posting("dead2", job_title="dead2", location="Shanghai, China"),
    ], now=NOW)
    ids = sorted(r["id"] for r in db.get_by_status(conn, "new"))
    tally = {"free": 0}
    # Fail the row the sweep visits FIRST (it walks newest-first, so that is the higher
    # id), so a real row follows it and the durable bug is in play: without the
    # rollback, the NEXT row's commit adopts this row's pending UPDATE.
    wrapped = _FlakyWriteConn(conn, fail_ids=[ids[1]])

    survivors = pipeline._sweep_free_gates(
        wrapped, db.get_by_status(conn, "new", newest_first=True),
        candidate={"locations": ["remote", "USA"]}, now=NOW, tally=tally)

    assert survivors == []                    # neither row survives the gate
    assert tally["free"] == 1                 # only the row that actually wrote is counted
    # Read COMMITTED state through a second connection: the sweep's own connection can
    # see its uncommitted UPDATE, which is exactly how the first version of this passed
    # while writing the row anyway.
    fresh = db.connect(db_path)
    states = {r["id"]: r["pipeline_status"]
              for r in fresh.execute("SELECT id, pipeline_status FROM job_postings")}
    assert states[ids[1]] == "new"            # the failed one really did stay 'new'
    assert states[ids[0]] == "discarded"
    assert "1 free-gate discard(s) could not be written" in capsys.readouterr().out


def test_a_systemic_sweep_write_failure_fails_loud_instead_of_retrying_forever(db_path):
    # A failure every row shares is not a per-item verdict: an unknown-column ValueError
    # or a json.dumps TypeError would otherwise be swallowed once per row, every pass,
    # forever. Same breaker signature the screen and fit phases watch for.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting(f"d{i}", job_title=f"d{i}", location="Shanghai, China")
                              for i in range(pipeline._BREAKER_LIMIT + 2)], now=NOW)
    ids = [r["id"] for r in db.get_by_status(conn, "new")]
    wrapped = _FlakyWriteConn(conn, fail_ids=ids)

    with pytest.raises(sqlite3.OperationalError):
        pipeline._sweep_free_gates(
            wrapped, db.get_by_status(conn, "new", newest_first=True),
            candidate={"locations": ["remote", "USA"]}, now=NOW, tally={"free": 0})


def test_the_free_gates_do_not_consume_the_score_limit(db_path, capsys):
    # `--score-limit` is a QUOTA budget, and a location/intern discard spends no quota:
    # no model call, no paid call. Charging it a budget slot stalled the live pipeline
    # on 2026-07-31 — `requeue_discarded` had put 3,800 location discards back in `new`,
    # where they sort AHEAD of fresh intake, so every pass spent its whole cap
    # re-killing them for free, fit-scored nothing, and had ~16 days to go before it
    # would reach a posting discovered that day.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [
        _posting("dead1", job_title="dead1", location="Bengaluru, India"),
        _posting("dead2", job_title="dead2", location="Shanghai, China"),
        _posting("live", job_title="live", location="Remote"),
    ], now=NOW)
    screened, fit_calls = [], []

    def screen_fn(posting):
        screened.append(posting["job_title"])
        return {"disqualified": False, "screen": {}, "disqualification_reason": ""}

    def fit_fn(postings):
        fit_calls.append([p["job_title"] for p in postings])
        return [_card() for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn, limit=1,
                       candidate={"locations": ["remote", "USA"]})

    # The two dead rows never reached the screen, and the ONE budget slot bought the
    # live row instead of being eaten by a free discard.
    assert screened == ["live"]
    assert fit_calls == [["live"]]
    assert {r["external_id"] for r in db.get_by_status(conn, "discarded")} == {"dead1", "dead2"}
    assert [r["external_id"] for r in db.get_by_status(conn, "scored")] == ["live"]
    assert "2 free-gate discarded (unbudgeted)" in capsys.readouterr().out


def test_run_score_always_prints_a_summary(db_path, capsys):
    # run_score used to print NOTHING on success, so a pass that did work and a pass
    # with nothing to do were indistinguishable at the terminal — a working run read as
    # a failure (2026-07-26). One line, always, with the counts that matter: `fit` is
    # what spent quota, `left 'new'` is what a breaker or abort did not reach.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [
        _posting("dq", job_title="dq"),                       # screen-disqualified
        _posting("thin", job_title="thin", description="Too short."),   # no fit call
        _posting("ok", job_title="ok"),                       # fit-scored
    ], now=NOW)

    def screen_fn(posting):
        dq = posting["job_title"] == "dq"
        return {"disqualified": dq, "screen": {}, "disqualification_reason": ""}

    fit_calls = []

    def fit_fn(postings):
        fit_calls.append(len(postings))
        return [_card() for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)

    out = capsys.readouterr().out
    assert "then 3 row(s):" in out
    assert "1 screen-discarded" in out
    assert "1 thin-JD (no fit call)" in out
    assert "1 fit-scored" in out
    assert "0 failed" in out
    assert "0 left 'new'" in out
    assert fit_calls == [1]        # only the substantial JD was paid for


def test_run_score_summary_counts_rows_a_breaker_never_reached(tmp_path, capsys):
    # A tripped fit breaker leaves the untouched remainder 'new'. The summary must say
    # so rather than under-reporting the pass as if those rows never existed — that is
    # the difference between "nothing to do" and "the backend is down".
    conn = _seeded_conn(tmp_path, 6)

    def screen_fn(posting):
        return {"disqualified": False, "screen": {}}

    def fit_fn(postings):
        raise score.ScoreError("backend down")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn, batch_size=1)

    out = capsys.readouterr().out
    assert "then 6 row(s):" in out
    unreached = int(out.split("failed, ")[1].split(" unreached")[0])
    failed = int(out.split("confirmation, ")[1].split(" failed")[0])
    assert failed + unreached == 6  # every row accounted for, none double-counted
    assert unreached > 0            # the breaker stopped short of the whole backlog
    # `left 'new'` is the DB truth, which for an uncapped pass equals the unreached
    # remainder; the capped case is pinned separately.
    assert f"{unreached} left 'new'" in out


def test_run_score_substantial_jd_reaches_fit(db_path):
    # The complement: a JD at/over the threshold DOES go to the fit scorer.
    conn = db.connect(db_path)
    long_desc = "x" * db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH
    db.upsert_postings(conn, [_posting("full", description=long_desc)], now=NOW)
    calls = []

    def screen_fn(posting):
        return {"disqualified": False, "screen": {}}

    def fit_fn(postings):
        calls.append(len(postings))
        return [{"score": 80, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    assert calls == [1]  # the substantial JD reached the paid scorer
    assert db.get_by_status(conn, "scored")[0]["external_id"] == "full"


def test_run_score_skips_non_new(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.save_score(conn, pid, score=10, score_detail={}, now=NOW)  # now 'scored'

    called = []

    def screen_fn(posting):
        called.append(posting["external_id"])
        return {"disqualified": False}

    def fit_fn(postings):
        raise AssertionError("fit must not run — there are no 'new' rows")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    assert called == []


# --- run_notify -----------------------------------------------------------

# A save_score detail whose seniority + domain verdicts are both 'match' —
# db.get_notifiable's notify gate. Shared by every run_notify test below that
# just needs "this row is notifiable" without caring about the verdict values.
_MATCH_MATCH = {"assessment": {"seniority": {"verdict": "match"},
                               "domain": {"verdict": "match"}}}


def test_run_notify_pings_only_verdict_matches(db_path):
    conn = db.connect(db_path)

    def add(ext_id, sen, dom):
        db.upsert_postings(conn, [_posting(ext_id)], now=NOW)
        row = conn.execute(
            "SELECT id FROM job_postings WHERE external_id=?", (ext_id,)
        ).fetchone()
        db.save_score(conn, row["id"], score=50, now=NOW, status="scored",
                      score_detail={"assessment": {"seniority": {"verdict": sen},
                                                    "domain": {"verdict": dom}}})

    add("hi", "match", "match")       # ping
    add("lo", "match", "adjacent")    # no ping (below the verdict bar)

    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append(posting["external_id"])

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
    assert notified == ["hi"]

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["hi"] == "notified"
    assert statuses["lo"] == "scored"  # untouched, not a match/match verdict pair


def test_run_notify_advances_and_passes_token_chat(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95}, detail=_MATCH_MATCH)

    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append((posting["external_id"], token, chat_id))

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="tok", chat_id="cid")
    assert {n[0] for n in notified} == {"1", "2"}
    assert all(n[1] == "tok" and n[2] == "cid" for n in notified)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses == {"1": "notified", "2": "notified"}


def test_run_notify_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95}, detail=_MATCH_MATCH)

    def notify_fn(posting, *, token, chat_id):
        if posting["external_id"] == "1":
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    # A send error is transient: the row stays 'scored' for a next-pass retry,
    # with the failure recorded on it; the sibling is unaffected. The charge lands
    # on notify_attempts (delivery's own budget), NOT the shared score `attempts`.
    assert rows["1"]["pipeline_status"] == "scored"
    assert rows["1"]["notify_attempts"] == 1
    assert rows["1"]["attempts"] == 0
    assert "telegram" in rows["1"]["pipeline_error"]
    assert rows["2"]["pipeline_status"] == "notified"


def test_notify_budget_survives_prior_score_hiccups(db_path):
    # ORCH defect: `attempts` used to be shared, so score hiccups pre-spent the
    # notify retry budget. A row that already burned 2 SCORE attempts (recovered
    # via run_retry) must still get its full NOTIFY_MAX_ATTEMPTS notify tries — the
    # two budgets are unrelated failure domains.
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    pid = conn.execute("SELECT id FROM job_postings").fetchone()["id"]
    # Simulate two prior score failures that scoring already recovered from.
    conn.execute("UPDATE job_postings SET attempts=2 WHERE id=?", (pid,))
    conn.commit()

    sends = {"n": 0}

    def failing_notify(posting, *, token, chat_id):
        sends["n"] += 1
        raise RuntimeError("telegram timeout")   # transient, not systemic auth

    # It is entitled to 3 notify tries; the first notify failure must NOT park it.
    pipeline.run_notify(conn, now=NOW, notify_fn=failing_notify, token="t", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert sends["n"] == 1
    assert row["pipeline_status"] == "scored"     # still retryable, not parked failed
    assert row["notify_attempts"] == 1
    assert row["attempts"] == 2                    # scoring's counter left as-is


def test_run_notify_auth_error_circuit_breaks_without_charging(db_path):
    # NOTIFY data-loss defect: a wrong/expired bot token (401) is a SYSTEMIC channel
    # fault, not a per-posting one. It must circuit-break the whole pass — every
    # matched row left 'scored', ZERO notify_attempts spent — instead of convicting
    # each posting and, after NOTIFY_MAX_ATTEMPTS passes, destroying finished matches.
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95, "3": 80}, detail=_MATCH_MATCH)

    class _Resp:
        status_code = 401

    class _AuthError(RuntimeError):
        response = _Resp()

    sends = {"n": 0}

    def notify_fn(posting, *, token, chat_id):
        sends["n"] += 1
        raise _AuthError("401 Unauthorized: bot token is invalid")

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="tok", chat_id="c")
    rows = list(conn.execute("SELECT * FROM job_postings").fetchall())
    assert sends["n"] == 1                                  # stopped after the first send
    assert all(r["pipeline_status"] == "scored" for r in rows)   # nothing parked
    assert all(r["notify_attempts"] == 0 for r in rows)          # no budget spent
    assert all(r["attempts"] == 0 for r in rows)


def test_run_notify_circuit_breaks_after_consecutive_failures(db_path):
    # Backstop for a systemic failure that does NOT announce itself as auth (e.g. the
    # Telegram host is unreachable, every send times out): after the shared breaker's
    # limit of consecutive failures with ZERO deliveries, stop the pass so the bleed
    # is bounded rather than charging every remaining matched row.
    conn = db.connect(db_path)
    ids = {str(i): 50 for i in range(1, 9)}       # 8 matched rows
    _seed_scored(conn, ids, detail=_MATCH_MATCH)

    sends = {"n": 0}

    def failing_notify(posting, *, token, chat_id):
        sends["n"] += 1
        raise RuntimeError("connection timed out")   # not auth -> classifier passes it

    pipeline.run_notify(conn, now=NOW, notify_fn=failing_notify, token="t", chat_id="c")
    # Tripped at the breaker limit — not all 8 rows were attempted.
    assert sends["n"] == pipeline._BREAKER_LIMIT
    charged = conn.execute(
        "SELECT COUNT(*) FROM job_postings WHERE notify_attempts > 0"
    ).fetchone()[0]
    assert charged == pipeline._BREAKER_LIMIT     # the remainder left untouched


def test_run_score_disqualified_is_discarded_with_reason(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def screen_fn(posting):
        if posting["external_id"] == "1":
            return {"disqualified": True, "disqualification_reason": "requires a PhD"}
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 80, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "discarded"
    assert rows["2"]["pipeline_status"] == "scored"
    # A disqualified posting never reaches the fit scorer (screened out before
    # the fit phase even runs) — so it's persisted with score 0, not a fit score.
    assert rows["1"]["score"] == 0
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["disqualified"] is True
    assert detail["disqualification_reason"] == "requires a PhD"


def test_run_score_insufficient_context_persisted(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def screen_fn(posting):
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 55, "insufficient_context": True, "assessment": _assessment()}
                for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "scored"   # still scored; the UI routes it
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["insufficient_context"] is True


# --- failure bookkeeping + stage gating -----------------------------------

def test_run_score_failure_records_error_and_increments_attempts(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def screen_fn(posting):
        raise RuntimeError("ollama down")

    def fit_fn(postings):
        raise AssertionError("fit must not run — the screen failed")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert row["attempts"] == 1
    assert "ollama down" in row["pipeline_error"]


def test_run_score_passes_full_posting_to_scorer(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    seen = {}

    def screen_fn(posting):
        return {"disqualified": False}

    def fit_fn(postings):
        seen.update(postings[0])
        return [{"score": 50, "assessment": _assessment()}]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    assert seen.get("description")   # the JD text reached the scorer, not just the id
    assert seen.get("job_title")


def test_run_score_persists_recommended_resume(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def screen_fn(posting):
        return {"disqualified": False}

    def fit_fn(postings):
        out = []
        for p in postings:
            card = {"score": 88, "assessment": _assessment()}
            if p["external_id"] == "1":
                card["recommended_resume"] = "swe"
            out.append(card)
        return out

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)

    details = {
        r["external_id"]: _json.loads(r["score_detail"])
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert details["1"]["recommended_resume"] == "swe"
    # absent from the scorer result -> absent from the stored JSON (old shape)
    assert "recommended_resume" not in details["2"]


def test_run_score_batches_survivors_and_falls_back_on_batch_error(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])
    calls = {"batch": [], "single": 0}

    def fit_fn(postings):
        ids = [p["id"] for p in postings]
        calls["batch"].append(ids)
        if len(ids) > 1:
            raise score.ScoreError("batch parse failed")      # force fallback
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=fit_fn)
    assert sorted(calls["batch"][0]) == [1, 2, 3]   # tried as one batch (queue is newest-first)
    assert calls["single"] == 3               # fell back to singles
    assert len(db.get_by_status(conn, "scored")) == 3


def test_run_score_falls_back_on_non_scoreerror_batch_failure(db_path):
    # A transient NON-ScoreError from the batch call (e.g. make_claude_scorer lets an
    # anthropic.RateLimitError from client.messages.create() propagate — it only
    # wraps json.loads in ScoreError) must ALSO trigger the singles fallback, not
    # escape run_score and abort every remaining chunk + skip run_notify. The
    # batch-level catch is `except Exception`, not `except ScoreError`, to cover this.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])
    calls = {"batch": [], "single": 0}

    def fit_fn(postings):
        ids = [p["id"] for p in postings]
        calls["batch"].append(ids)
        if len(ids) > 1:
            raise RuntimeError("api down")          # NON-ScoreError -> must still fall back
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=fit_fn)
    assert sorted(calls["batch"][0]) == [1, 2, 3]   # tried as one batch (queue is newest-first)
    assert calls["single"] == 3               # fell back to singles despite RuntimeError
    # Every survivor still processed to 'scored' — the pass was NOT aborted.
    assert len(db.get_by_status(conn, "scored")) == 3


def test_run_score_falls_back_when_batch_returns_short(db_path):
    # A backend that returns FEWER cards than postings without raising must not
    # zip-misalign and orphan the tail — it falls back to singles so all score.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])
    calls = {"single": 0}

    def fit_fn(postings):
        if len(postings) > 1:
            return [{"score": 70, "assessment": _assessment()}]   # short by 2
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()}]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)
    assert calls["single"] == 3
    assert len(db.get_by_status(conn, "scored")) == 3


def test_run_score_persists_disqualified_without_fit(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(
        conn, now=NOW, batch_size=10,
        screen_fn=lambda p: {"disqualified": True, "disqualification_reason": "x"},
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("fit must not run")),
    )
    assert db.get_by_status(conn, "discarded")[0]["id"] == 1


def test_run_score_scorer_fallback_disqualifies_lands_discarded(db_path):
    # The screen produced NO verdict for this row (e.g. SCREEN_BACKEND=none); only
    # the fit scorer's fallback extraction catches the hard requirement. It must
    # land 'discarded' — not 'scored' — even though the (paid) fit call already ran.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"], description=_CLEARED_DESC)

    def screen_fn(posting):
        return {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    def fit_fn(postings):
        return [{"score": 90, "assessment": _assessment(),
                 "screen": {"clearance": {"requires_clearance": True}}}
                for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn,
                       candidate={"security_clearance": "none"})

    assert db.get_by_status(conn, "scored") == []
    row = db.get_by_status(conn, "discarded")[0]
    assert row["external_id"] == "1"
    assert row["score"] == 0
    detail = _json.loads(row["score_detail"])
    assert detail["disqualified"] is True
    assert "clearance" in detail["disqualification_reason"]


def test_run_score_fallback_single_failure_is_isolated(db_path):
    # The batch fails (forcing the single-item fallback); within that fallback,
    # ONE posting's single fit_fn call still fails — it alone is marked 'failed',
    # its batch-mate is still scored.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def fit_fn(postings):
        if len(postings) > 1:
            raise score.ScoreError("batch parse failed")
        posting = postings[0]
        if posting["external_id"] == "1":
            raise RuntimeError("codex exec failed for this one JD")
        return [{"score": 70, "assessment": _assessment()}]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "failed"
    assert statuses["2"] == "scored"


def test_run_score_singles_fallback_not_reissued_at_batch_size_one(db_path):
    # SCORE defect (2): at batch_size=1 a chunk IS one posting, so the singles
    # fallback would re-issue fit_fn([posting]) with byte-identical args to the
    # batch call that just failed — a guaranteed-to-fail second call that only
    # doubles the cost. The len(chunk) > 1 guard skips it: exactly ONE call.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    calls = {"n": 0}

    def fit_fn(postings):
        calls["n"] += 1
        raise score.ScoreError("codex exec failed (exit 1): not logged in")

    pipeline.run_score(conn, now=NOW, batch_size=1,
                       screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)
    assert calls["n"] == 1                       # NOT re-issued as a single
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert "not logged in" in row["pipeline_error"]


def test_run_score_dead_fit_backend_circuit_breaks_leaving_rows_new(db_path):
    # SCORE defect (1): a dead fit backend (every call fails, zero successes) must
    # NOT convict the whole queue. After _BREAKER_LIMIT failures the pass aborts,
    # leaving the untouched remainder 'new' (recoverable) instead of marking 3,985
    # rows 'failed' and burning their retry budget on an outage. score_workers=1
    # makes consumption order deterministic.
    import time
    conn = db.connect(db_path)
    rows = [str(i) for i in range(1, 21)]        # 20 new rows
    _seed_new(conn, rows)
    calls = {"n": 0}

    def fit_fn(postings):
        calls["n"] += 1
        time.sleep(0.01)                          # realistic: a dead backend fails slowly,
        raise score.ScoreError("codex exec failed (exit 1): not logged in")

    pipeline.run_score(conn, now=NOW, batch_size=1, score_workers=1,
                       screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)

    # Tripped at the limit: exactly that many rows charged (the trip is checked after
    # each consumed chunk), the untouched remainder left 'new' — recoverable, not a
    # terminally-dead queue. Pending calls are cancelled, so spend is bounded too.
    assert len(db.get_by_status(conn, "failed")) == pipeline._BREAKER_LIMIT
    assert len(db.get_by_status(conn, "new")) == 20 - pipeline._BREAKER_LIMIT
    assert calls["n"] < 20                        # not every row's fit call was spent


def test_run_score_keyboard_interrupt_cancels_pending_keeps_done(db_path):
    # ORCH defect (1): Ctrl-C during the paid fit phase must (a) stop launching new
    # fit calls — the pending chunks are cancelled, not drained — and (b) keep the
    # work already finished, persisted on the calling thread as it completed. Old
    # ThreadPoolExecutor.__exit__ drained the whole queue (uninterruptible) and lost
    # finished-but-unwritten results. score_workers=1 makes ordering deterministic.
    import time
    conn = db.connect(db_path)
    # Seeded in reverse: run_score reads the 'new' queue newest-id-first, so this puts
    # "1".."4" through the scorer in that order and the assertions below stay readable.
    _seed_new(conn, ["4", "3", "2", "1"])
    called = []

    def fit_fn(postings):
        ext = postings[0]["external_id"]
        if ext == "1":
            return [{"score": 90, "assessment": _assessment()}]
        if ext == "2":
            time.sleep(0.05)             # let row "1" persist first, keep the worker busy
            raise KeyboardInterrupt
        called.append(ext)
        time.sleep(0.05)                 # "3" may be the in-flight call at abort time;
        return [{"score": 90, "assessment": _assessment()}]   # "4" is queued behind it

    with pytest.raises(KeyboardInterrupt):
        pipeline.run_score(conn, now=NOW, batch_size=1, score_workers=1,
                           screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "scored"     # finished work kept, not discarded on abort
    assert statuses["2"] == "new"        # the interrupted chunk never persisted
    assert statuses["3"] == "new"        # in-flight at abort: not consumed, not persisted
    # The queued backlog past the in-flight call is CANCELLED, not drained: its fit
    # call is never spent (old code shutdown(wait=True) would have run all of them).
    assert statuses["4"] == "new"
    assert "4" not in called


# --- run_score concurrency -------------------------------------------------

def test_run_score_screens_concurrently(tmp_path):
    # The screen calls must overlap; the DB writes must not.
    import threading
    conn = _seeded_conn(tmp_path, rows=6)
    inflight, peak, lock = 0, [0], threading.Lock()

    def screen_fn(posting):
        nonlocal inflight
        with lock:
            inflight += 1
            peak[0] = max(peak[0], inflight)
        time.sleep(0.05)
        with lock:
            inflight -= 1
        return {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=4)
    assert peak[0] > 1, "screen calls did not overlap"


def test_run_score_preserves_write_order_and_row_association(tmp_path):
    # A pool must not mis-associate a screen verdict with the wrong posting.
    conn = _seeded_conn(tmp_path, rows=5)

    def screen_fn(posting):
        # Disqualify exactly one known row. Make its call slower than the rest so
        # its future completes OUT of submission order — proving row-association
        # is keyed by submission order, not completion order (a broken
        # as_completed-based impl would otherwise often still pass by luck).
        dq = posting["job_title"] == "row-3"
        if dq:
            time.sleep(0.05)
        return {"screen": {}, "disqualified": dq,
                "disqualification_reason": "test" if dq else ""}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=4)
    discarded = [dict(r)["job_title"] for r in db.get_by_status(conn, "discarded")]
    assert discarded == ["row-3"]


def test_run_score_screen_failure_fails_only_its_own_row(tmp_path):
    conn = _seeded_conn(tmp_path, rows=3)

    def screen_fn(posting):
        if posting["job_title"] == "row-1":
            raise RuntimeError("provider blew up")
        return {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=4)
    assert [dict(r)["job_title"] for r in db.get_by_status(conn, "failed")] == ["row-1"]
    # One row's screen failure must not abort the pass for the others.
    scored_titles = {dict(r)["job_title"] for r in db.get_by_status(conn, "scored")}
    assert scored_titles == {"row-2", "row-3"}


def test_run_notify_send_error_retries_then_parks_failed(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    calls = []

    def notify_fn(posting, *, token, chat_id):
        calls.append(posting["external_id"])
        raise RuntimeError("telegram 429")

    # Each pass retries the still-'scored' row; the 3rd cumulative failure
    # (NOTIFY_MAX_ATTEMPTS) parks it 'failed'.
    for expected_attempts, expected_status in ((1, "scored"), (2, "scored"), (3, "failed")):
        pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
        row = conn.execute("SELECT * FROM job_postings").fetchone()
        assert row["notify_attempts"] == expected_attempts
        assert row["pipeline_status"] == expected_status
        assert "telegram" in row["pipeline_error"]
    assert calls == ["a", "a", "a"]
    # Parked rows are terminal: a further pass must not retry them.
    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
    assert calls == ["a", "a", "a"]


def test_run_notify_retry_then_success_clears_error(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    sends = []

    def flaky_notify(posting, *, token, chat_id):
        sends.append(posting["external_id"])
        if len(sends) == 1:
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, now=NOW, notify_fn=flaky_notify, token="test_token", chat_id="c")
    pipeline.run_notify(conn, now=NOW, notify_fn=flaky_notify, token="test_token", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "notified"
    assert row["pipeline_error"] is None   # cleared on the successful send
    assert row["notify_attempts"] == 1     # the earlier send failure stays counted


def test_run_notify_scrubs_token_from_recorded_and_printed_error(db_path, capsys):
    # requests embeds the request URL (which carries the bot token) in its exception
    # text; run_notify writes str(exc) into pipeline_error (shown in the web Failed
    # bucket) and prints it — the token must never reach either sink.
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    token = "123456789:AAExampleSecretBotToken"

    def notify_fn(posting, *, token, chat_id):
        raise RuntimeError(
            "HTTPSConnectionPool: Max retries exceeded with url: "
            f"https://api.telegram.org/bot{token}/sendMessage")

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token=token, chat_id="c")

    err = conn.execute("SELECT pipeline_error FROM job_postings").fetchone()["pipeline_error"]
    assert token not in err and "***" in err
    out = capsys.readouterr().out
    assert token not in out and "***" in out


def test_stages_ignore_wrong_status_rows(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["n"])                                  # stays 'new'
    _seed_scored(conn, {"hi": 90}, detail=_MATCH_MATCH)      # match/match -> notifiable
    _seed_scored(conn, {"lo": 50}, detail={                 # not match/match -> ignored
        "assessment": {"seniority": {"verdict": "match"}, "domain": {"verdict": "adjacent"}},
    })

    notified = []
    pipeline.run_notify(
        conn, now=NOW, token="x", chat_id="y",
        notify_fn=lambda p, *, token, chat_id: notified.append(p["external_id"]),
    )
    assert notified == ["hi"]         # only 'scored' + match/match ('new' + non-matching ignored)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["n"] == "new"
    assert statuses["lo"] == "scored"


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
            db.save_score(conn, r["id"], score=80, score_detail={}, now=NOW,
                          status=status)


def _statuses(conn):
    return {r["external_id"]: r["pipeline_status"]
            for r in conn.execute("SELECT * FROM job_postings").fetchall()}


@pytest.mark.parametrize("status", [404, 410])
def test_run_expire_marks_gone_listings_expired(db_path, status):
    conn = db.connect(db_path)
    _seed_live(conn, ["dead"])

    def fetch_one(source, slug, ext, name):
        raise _HTTPError(status)

    assert pipeline.run_expire(conn, now=LATER, detail_fetch_fn=fetch_one) == 1
    assert _statuses(conn)["dead"] == "expired"


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
    assert row["pipeline_status"] == "scored"
    assert row["updated_at"] == NOW      # untouched, so it's re-checked next pass


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


def test_run_expire_zero_budget_checks_nothing(db_path):
    conn = db.connect(db_path)
    _seed_live(conn, ["x"])
    assert pipeline.run_expire(
        conn, now=LATER, limit=0,
        detail_fetch_fn=lambda *a: (_ for _ in ()).throw(AssertionError("no fetch"))) == 0


def test_run_expire_ignores_board_sources_and_dead_statuses(db_path):
    # Only live (scored|notified) rows from per-LISTING sources are re-checked:
    # a board source has no per-job endpoint, and 'new'/'discarded' rows aren't
    # in the operator's queue.
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


# --- run_retry --------------------------------------------------------------

def test_run_retry_requeues_then_caps_at_retry_max_attempts(db_path):
    # A row that keeps failing SCREEN: each run_score pass parks it 'failed'
    # (attempts+1); run_retry requeues it to 'new' while attempts < RETRY_MAX_ATTEMPTS
    # (3) so it's rescored next pass. On the 3rd cumulative failure the cap is hit
    # and run_retry requeues NOTHING — permanently parked.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def screen_fn(posting):
        raise RuntimeError("ollama down")

    def fit_fn(postings):
        raise AssertionError("fit must not run — the screen failed")

    for expected_attempts in (1, 2, 3):
        pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
        row = conn.execute("SELECT * FROM job_postings").fetchone()
        assert row["attempts"] == expected_attempts
        assert row["pipeline_status"] == "failed"

        requeued = pipeline.run_retry(conn, now=NOW)
        if expected_attempts < pipeline.RETRY_MAX_ATTEMPTS:
            assert requeued == 1
            assert conn.execute(
                "SELECT pipeline_status FROM job_postings"
            ).fetchone()[0] == "new"
        else:
            assert requeued == 0    # cap hit — the 3rd failure never comes back
            assert conn.execute(
                "SELECT pipeline_status FROM job_postings"
            ).fetchone()[0] == "failed"


def test_run_retry_does_not_requeue_notify_exhausted_rows(db_path):
    # A row parked 'failed' via the NOTIFY_MAX_ATTEMPTS-th notify send failure has
    # notify_attempts == 3 — its OWN budget, separate from score `attempts` — so it
    # must still never requeue: run_retry guards on both counters. No other code
    # path writes pipeline_status='failed' from the notify side.
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)

    def failing_notify(posting, *, token, chat_id):
        raise RuntimeError("telegram 429")   # transient/per-row, not systemic auth

    for _ in range(3):
        pipeline.run_notify(conn, now=NOW, notify_fn=failing_notify, token="t", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["notify_attempts"] == 3
    assert row["attempts"] == 0          # scoring's budget is untouched by notify
    assert row["pipeline_status"] == "failed"

    requeued = pipeline.run_retry(conn, now=LATER)
    assert requeued == 0
    assert conn.execute(
        "SELECT pipeline_status FROM job_postings"
    ).fetchone()[0] == "failed"


def test_run_retry_recovery_clears_pipeline_error_keeps_attempts(db_path):
    # fail once -> requeue -> the retry SCREEN survives and fit_fn succeeds ->
    # 'scored', pipeline_error cleared (None), attempts preserved at 1 (not reset).
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def failing_screen(posting):
        raise RuntimeError("ollama down")

    pipeline.run_score(
        conn, now=NOW, screen_fn=failing_screen,
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert row["attempts"] == 1
    assert row["pipeline_error"]

    requeued = pipeline.run_retry(conn, now=LATER)
    assert requeued == 1

    def ok_screen(posting):
        return {"disqualified": False}

    def ok_fit(postings):
        return [{"score": 90, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=LATER, screen_fn=ok_screen, fit_fn=ok_fit)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "scored"
    assert row["pipeline_error"] is None     # no stale error survives a recovery
    assert row["attempts"] == 1              # the earlier failure stays counted


def test_run_retry_sets_updated_at_to_passed_now(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.mark_failed(conn, pid, error="boom", now=NOW)

    requeued = pipeline.run_retry(conn, now=LATER)
    assert requeued == 1
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "new"
    assert row["updated_at"] == LATER


# --- dead screen provider ---------------------------------------------------

def test_run_score_never_pays_to_fit_score_an_unscreened_row(db_path):
    # The screen erring toward KEEP is right for one flaky call, but paying the fit
    # backend for a row that was never actually screened is not "keeping" it — the
    # hard-requirement gate simply didn't run. The row stays 'new' (recoverable, free)
    # and the next pass screens it properly.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])
    fit_calls = []

    def screen_fn(posting):
        if posting["external_id"] == "1":
            return {"screen": {}, "disqualified": False, "provider_error": True}
        return {"screen": {}, "disqualified": False}

    def fit_fn(postings):
        fit_calls.extend(p["external_id"] for p in postings)
        return [_card() for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    status = {r["external_id"]: r["pipeline_status"]
              for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert status["1"] == "new"        # untouched, costs nothing, retried next pass
    assert status["2"] == "scored"
    assert fit_calls == ["2"]          # the unscreened row never reached the scorer
    assert conn.execute(
        "SELECT attempts FROM job_postings WHERE external_id='1'").fetchone()[0] == 0


def test_run_score_provider_error_still_discards_on_a_deterministic_gate(db_path):
    # The CODE gates ran fine even though the LLM screen didn't. A row they
    # disqualified is still terminal — it must not be resurrected as 'new'.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(
        conn, now=NOW,
        screen_fn=lambda p: {"screen": {"location": {"pass": False}},
                             "disqualified": True,
                             "disqualification_reason": "location: Shanghai",
                             "provider_error": True},
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert conn.execute(
        "SELECT pipeline_status FROM job_postings").fetchone()[0] == "discarded"


def test_run_score_screen_breaker_aborts_and_says_so(db_path, capsys):
    # The assertion that actually pins the breaker. The sibling test below checks only
    # that rows stay 'new'/attempts=0 -- which is ALSO true with no breaker at all, since
    # every provider_error row hits `continue` regardless (verified: stubbing the trip
    # check out leaves the whole suite green). The abort announcement is the one
    # observable the breaker uniquely produces, and an unannounced abort is itself the
    # defect -- rows keep attempts=0 and never reach the Failed tab, so a silent abort
    # looks exactly like a pass with nothing to do.
    conn = db.connect(db_path)
    _seed_new(conn, [str(i) for i in range(pipeline._BREAKER_LIMIT + 5)])
    pipeline.run_score(
        conn, now=NOW,
        screen_fn=lambda p: {"screen": {}, "disqualified": False, "provider_error": True},
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("fit must not run")),
        screen_workers=1,
    )
    assert "screen backend appears down" in capsys.readouterr().out


def test_screen_breaker_counts_raised_failures_too(db_path):
    # A backend whose failure mode RAISES is as systemic as one returning the flag.
    # Uncounted, an outage marks every row `failed` (attempts+1) and three passes park
    # the backlog terminal -- the "a morning out and the queue is gone" outcome the
    # breaker exists to prevent. Rows past the limit must stay untouched at attempts=0.
    conn = db.connect(db_path)
    n = pipeline._BREAKER_LIMIT + 5
    _seed_new(conn, [str(i) for i in range(n)])

    def screen_fn(posting):
        raise RuntimeError("connection refused")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("no fit")),
                       screen_workers=1)
    rows = conn.execute("SELECT pipeline_status, attempts FROM job_postings").fetchall()
    untouched = [r for r in rows if r["pipeline_status"] == "new" and r["attempts"] == 0]
    assert untouched, "breaker never aborted; every row was marked failed"


def test_run_score_circuit_breaks_a_dead_screen_provider(db_path):
    # A dead screen provider is SYSTEMIC, not per-item: without a breaker the whole
    # backlog is silently left unscreened. Trip after _BREAKER_LIMIT consecutive
    # provider errors with zero successes and leave the remainder 'new'.
    conn = db.connect(db_path)
    ids = [str(i) for i in range(pipeline._BREAKER_LIMIT + 5)]
    _seed_new(conn, ids)
    screened = []

    def screen_fn(posting):
        screened.append(posting["external_id"])
        return {"screen": {}, "disqualified": False, "provider_error": True}

    pipeline.run_score(
        conn, now=NOW, screen_fn=screen_fn,
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("fit must not run")),
        screen_workers=1,
    )
    # NOT asserted: how many screen calls were made. The pool is filled up front (so
    # consumption stays in submission order), so already-queued calls can race ahead of
    # the trip with instant fakes; the breaker cancels the rest, which on a real
    # provider — seconds per call — stops most of the backlog. What IS guaranteed is
    # below: nothing was persisted, nothing was spent, everything is recoverable.
    rows = conn.execute("SELECT pipeline_status, attempts FROM job_postings").fetchall()
    assert {r["pipeline_status"] for r in rows} == {"new"}   # all recoverable
    assert {r["attempts"] for r in rows} == {0}              # no budget burned


def test_run_score_one_screen_success_disarms_the_breaker(db_path):
    # A flaky-but-alive provider must never trip it: one success this pass is proof
    # the backend is up, so the remaining errors ride the per-item keep policy.
    conn = db.connect(db_path)
    ids = [str(i) for i in range(pipeline._BREAKER_LIMIT + 3)]
    _seed_new(conn, ids)
    # The queue is newest-id-first, so the last-seeded row is screened first — that is
    # where the one good call has to sit for the breaker to see a success before it
    # counts _BREAKER_LIMIT consecutive failures.
    first_screened = ids[-1]

    def screen_fn(posting):
        if posting["external_id"] == first_screened:
            return {"screen": {}, "disqualified": False}      # one good call
        return {"screen": {}, "disqualified": False, "provider_error": True}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=1)
    status = [r["pipeline_status"]
              for r in conn.execute("SELECT * FROM job_postings").fetchall()]
    assert status.count("scored") == 1        # only the genuinely screened row
    assert status.count("new") == len(ids) - 1


# --- scorer provenance ------------------------------------------------------

_META = {"backend": "codex", "model": "gpt-5.6-sol", "scorer_version": "2026-07-24"}


def test_run_score_stamps_provenance_only_on_fit_scored_rows(db_path):
    # Row '1' is screen-disqualified and row '2' is too thin to fit-score: NEITHER
    # spends a fit call, so stamping them with a backend/model would claim a scorer
    # produced a verdict it never saw. Only row '3' — the one the fit backend
    # actually scored — carries provenance.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "3"])
    _seed_new(conn, ["2"], description="too thin to score")

    def screen_fn(posting):
        if posting["external_id"] == "1":
            return {"disqualified": True, "disqualification_reason": "requires a PhD"}
        return {"disqualified": False}

    def fit_fn(postings):
        return [_card() for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn,
                       scorer_meta=_META)
    detail = {r["external_id"]: _json.loads(r["score_detail"])
              for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert detail["3"]["backend"] == "codex"
    assert detail["3"]["model"] == "gpt-5.6-sol"
    assert detail["3"]["scorer_version"] == "2026-07-24"
    assert "backend" not in detail["1"]      # screen-discarded, no fit call
    assert "backend" not in detail["2"]      # low-context, fit call skipped


def test_run_score_omits_provenance_when_no_scorer_meta(db_path):
    # scorer_meta is optional (the pipeline stays pure + injected): with none passed,
    # score_detail keeps its pre-provenance shape byte for byte.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(conn, now=NOW,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=lambda ps: [_card() for _ in ps])
    detail = _json.loads(conn.execute("SELECT * FROM job_postings").fetchone()["score_detail"])
    assert set(detail) == {"assessment"}


def test_run_score_stamps_provenance_on_fallback_disqualified_rows(db_path):
    # The fit scorer's fallback extraction can disqualify a row AFTER the fit call
    # ran (merge_fallback_screen). That call was paid for, so the row is provenance-
    # stamped like any other fit-scored row — it is exactly the kind of verdict an
    # operator re-selects after a score.txt edit.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"], description=_CLEARED_DESC)
    card = _card(screen={"clearance": {"requires_clearance": True}})

    pipeline.run_score(
        conn, now=NOW,
        screen_fn=lambda p: {"screen": {}, "disqualified": False,
                             "disqualification_reason": ""},
        fit_fn=lambda ps: [card for _ in ps],
        candidate={"security_clearance": "none"}, scorer_meta=_META)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "discarded"
    assert _json.loads(row["score_detail"])["backend"] == "codex"


# --- rescreen discarded -----------------------------------------------------

def test_requeue_discarded_returns_rows_to_new_for_a_later_screen(db_path):
    # A 'discarded' row is terminal — run_retry only requeues 'failed' — so a
    # candidate-config fix (locations, degree, work_authorization) would otherwise
    # leave every posting frozen under the old rule, false discards included.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    strict = lambda p: {"disqualified": True, "disqualification_reason": "requires a PhD"}
    pipeline.run_score(conn, now=NOW, screen_fn=strict,
                       fit_fn=lambda ps: [_card() for _ in ps])
    assert conn.execute("SELECT pipeline_status FROM job_postings").fetchone()[0] == "discarded"

    assert db.requeue_discarded(conn, LATER)[0] == 1
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "new"
    assert row["updated_at"] == LATER
    assert row["attempts"] == 0          # a discard burned no score budget

    pipeline.run_score(conn, now=LATER, screen_fn=lambda p: {"disqualified": False},
                       fit_fn=lambda ps: [_card() for _ in ps])
    assert conn.execute("SELECT pipeline_status FROM job_postings").fetchone()[0] == "scored"


def test_requeue_discarded_leaves_un_hydrated_stub_discards_alone(db_path):
    # Stub-gate discards are stored with description='' on purpose (run_fetch exempts
    # them from the bodyless drop) because they never reach the scorer. Requeueing one
    # DESTROYS it: it becomes 'new', the thin-JD gate parks it 'scored' at score 0, and
    # upsert_postings is ON CONFLICT DO NOTHING so no later pass ever back-fills the JD.
    # The rows the flag exists to rescue are exactly the ones it must not touch.
    conn = db.connect(db_path)
    conn.execute(
        "INSERT INTO job_postings (source, external_id, job_title, company_name, "
        "job_url, description, pipeline_status, attempts, created_at, updated_at) "
        "VALUES ('phenom','stub','Engineer','Acme','https://x/1','','discarded',0,?,?)",
        (NOW, NOW))
    conn.commit()

    assert db.requeue_discarded(conn, LATER)[0] == 0
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "discarded", "un-hydrated stub was requeued"

    # A hydrated discard on the same table still comes back, so the guard is a filter,
    # not a blanket refusal.
    conn.execute("UPDATE job_postings SET description='A real job description.'")
    conn.commit()
    assert db.requeue_discarded(conn, LATER)[0] == 1


def test_requeue_discarded_leaves_every_other_status_alone(db_path):
    # Only 'discarded' comes back. A 'scored'/'notified' row must never be re-screened
    # (it would re-notify), and 'failed' has its own budgeted path via run_retry.
    conn = db.connect(db_path)
    _seed_new(conn, ["new"])
    _seed_scored(conn, {"scored": 80})
    _seed_new(conn, ["failed"])
    pid = conn.execute(
        "SELECT id FROM job_postings WHERE external_id='failed'").fetchone()[0]
    db.mark_failed(conn, pid, error="boom", now=NOW)

    assert db.requeue_discarded(conn, LATER)[0] == 0
    status = {r["external_id"]: r["pipeline_status"]
              for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert status == {"new": "new", "scored": "scored", "failed": "failed"}


def test_a_row_the_current_filters_would_refuse_is_swept_free(db_path, capsys):
    # prefilter_postings runs at INGEST only, so a row that entered before its filter
    # existed keeps its place in the queue and buys a PAID fit call on a posting the
    # operator's own config refuses. Measured 2026-07-31 over the live queue: 206 of the
    # 5,941 rows that survive the deterministic gates. (max_age_days is deliberately NOT
    # re-applied -- an age refusal is unrecoverable; see run.py and docs/BACKLOG.md.)
    conn = db.connect(db_path)
    db.upsert_postings(conn, [
        _posting("stale", job_title="Sales Representative"),
        _posting("ok", job_title="Software Engineer"),
    ], now=NOW)
    fit_calls = []

    def stale_fn(posting):        # the string run.py actually produces
        return ("prefilter: title refused by the current filters"
                if "Sales" in posting["job_title"] else None)

    pipeline.run_score(conn, now=NOW, fit_fn=lambda ps: fit_calls.append(ps) or
                       [_card() for _ in ps],
                       screen_fn=lambda p: {"disqualified": False, "screen": {},
                                            "disqualification_reason": ""},
                       candidate={"locations": ["remote", "USA"]},
                       stale_fn=stale_fn, limit=5)

    assert [p["job_title"] for p in fit_calls[0]] == ["Software Engineer"]
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings")}
    assert rows["stale"]["pipeline_status"] == "discarded"
    assert "title refused by the current filters" in rows["stale"]["score_detail"]
    # the verdict MERGES: the passing location evidence this row already earned survives,
    # which is what --rescreen-discarded needs when it sends real discards back through.
    assert '"location"' in rows["stale"]["score_detail"]
    assert "1 free-gate discarded (unbudgeted)" in capsys.readouterr().out


def test_the_stale_check_never_runs_on_a_row_a_gate_already_killed(db_path):
    # Ordering matters for the recorded reason: a location kill is the real one, and
    # re-labelling it "prefilter" would lose why the row actually went.
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting("x", job_title="Sales Rep",
                                       location="Shanghai, China")], now=NOW)
    seen = []
    pipeline.run_score(conn, now=NOW, fit_fn=lambda ps: [_card() for _ in ps],
                       screen_fn=lambda p: {"disqualified": False, "screen": {},
                                            "disqualification_reason": ""},
                       candidate={"locations": ["remote", "USA"]},
                       stale_fn=lambda p: seen.append(p) or "prefilter: refused",
                       limit=5)
    assert seen == []
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert "location:" in row["score_detail"] and "prefilter" not in row["score_detail"]


def test_no_stale_predicate_leaves_every_row_alone(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [_posting("a", job_title="Sales Rep")], now=NOW)
    pipeline.run_score(conn, now=NOW, fit_fn=lambda ps: [_card() for _ in ps],
                       screen_fn=lambda p: {"disqualified": False, "screen": {},
                                            "disqualification_reason": ""}, limit=5)
    assert db.get_by_status(conn, "scored")
