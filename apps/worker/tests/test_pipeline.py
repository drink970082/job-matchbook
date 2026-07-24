"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

import json as _json

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
    # with the failure recorded on it; the sibling is unaffected.
    assert rows["1"]["pipeline_status"] == "scored"
    assert rows["1"]["attempts"] == 1
    assert "telegram" in rows["1"]["pipeline_error"]
    assert rows["2"]["pipeline_status"] == "notified"


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
    assert calls["batch"][0] == [1, 2, 3]     # tried as one batch
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
    assert calls["batch"][0] == [1, 2, 3]     # tried as one batch
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
        assert row["attempts"] == expected_attempts
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
    assert row["attempts"] == 1            # the earlier failure stays counted


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
    # attempts == 3 == RETRY_MAX_ATTEMPTS — the SAME shared counter — so it must
    # never requeue. No other code path writes pipeline_status='failed'.
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)

    def failing_notify(posting, *, token, chat_id):
        raise RuntimeError("telegram 429")

    for _ in range(3):
        pipeline.run_notify(conn, now=NOW, notify_fn=failing_notify, token="t", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["attempts"] == 3
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
