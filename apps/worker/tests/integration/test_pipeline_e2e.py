"""Integration: the real run_once status machine over a real temp SQLite.

Only the three external seams are faked — fetch (board APIs), score (Ollama+
Claude), notify (Telegram). Everything else is real: run_once's wiring, the
pipeline stages, and the SQLite DB. This exercises the full
new -> scored -> (discarded|notified) loop and the failure/discard routing
across stages, which the per-stage unit tests can't assert together.
"""
from __future__ import annotations

import json

import pytest

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
from ats_worker import run
from tests._helpers import LONG_DESC, bootstrap_db, make_posting

pytestmark = pytest.mark.integration

ENV = {"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "test_token",
       "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"}

# The notify gate is now the fit verdicts (db.get_notifiable), not the score —
# a score_fn result needs both dimensions 'match' to be notifiable.
_MATCH_MATCH_ASSESSMENT = {"seniority": {"verdict": "match"}, "domain": {"verdict": "match"}}


def _cfg():
    return cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
    )


def _run(monkeypatch, tmp_path, *, postings, score_fn, passes=1):
    """Run the real run_once with canned postings + a fake scorer, SPLIT into the
    screen_fn/fit_fn halves run_score now consumes. Each test's `score_fn(posting)`
    still returns ONE merged dict (screen + fit fields together) for convenience:
      - screen_posting is faked to surface just the disqualification half (so no
        Ollama call happens) — `run.screen_posting` calls `score_fn(posting)` and
        returns its disqualified/disqualification_reason/screen fields.
      - the fit backend is faked via `run.make_scorer` (so no real Claude/codex
        backend is built) — fit_fn returns `score_fn(posting)` UNCHANGED as the raw
        card for each survivor; pipeline.run_score normalizes it same as a real
        backend's card would be.
    A posting screened out as disqualified never reaches the fit half — matching
    the new run_score's phase order.

    notify raises only when the JD contains the marker 'BOOM' (for failure-isolation
    tests); otherwise it records the external_ids it was asked to send. `passes` runs
    run_once repeatedly over the SAME db (the scheduler's cadence), which is how
    the notify retry path is exercised. Returns (db_path, notified_ids)."""
    dbfile = bootstrap_db(str(tmp_path / "applications.db"))

    def fake_run_fetch(conn, companies, title_filter, *, now, **_):
        return dbmod.upsert_postings(conn, postings, now=now)

    notified: list[str] = []

    def fake_notify(posting, *, token, chat_id):
        if "BOOM" in posting["description"]:
            raise RuntimeError("telegram 429")
        notified.append(posting["external_id"])

    def fake_screen_posting(posting, **kw):
        result = score_fn(posting)
        return {
            "disqualified": result.get("disqualified", False),
            "disqualification_reason": result.get("disqualification_reason", ""),
            "screen": result.get("screen", {}),
        }

    monkeypatch.setattr(run.pipeline, "run_fetch", fake_run_fetch)
    monkeypatch.setattr(run, "screen_posting", fake_screen_posting)
    monkeypatch.setattr(
        run, "make_scorer",
        lambda backend, **kw: (lambda postings, resumes: [score_fn(p) for p in postings]),
    )
    monkeypatch.setattr(run, "notify_posting", fake_notify)

    for _ in range(passes):
        run.run_once(_cfg(), db_path=dbfile, resumes={"resume": "r"}, env=ENV)
    return dbfile, notified


def _statuses(dbfile):
    conn = dbmod.connect(dbfile)
    return {r["external_id"]: r["pipeline_status"]
            for r in conn.execute("SELECT * FROM job_postings").fetchall()}


def test_full_status_machine(monkeypatch, tmp_path):
    postings = [make_posting("dq"), make_posting("low"), make_posting("hi")]

    def score_fn(posting):
        eid = posting["external_id"]
        if eid == "dq":
            return {"score": 88, "disqualified": True, "disqualification_reason": "needs PhD"}
        if eid == "low":
            # A structurally-valid assessment (required by score._normalize_score,
            # which run_score now calls on every fit card) whose verdict pair is
            # NOT both 'match' -> still 'scored', still not notifiable.
            return {"score": 50, "assessment": {"seniority": {"verdict": "match"},
                                                "domain": {"verdict": "adjacent"}}}
        return {"score": 90, "assessment": _MATCH_MATCH_ASSESSMENT}

    dbfile, notified = _run(monkeypatch, tmp_path, postings=postings, score_fn=score_fn)
    assert _statuses(dbfile) == {"dq": "discarded", "low": "scored", "hi": "notified"}
    assert notified == ["hi"]   # only the match/match-verdict posting is notified


def test_disqualified_routing_keeps_reason(monkeypatch, tmp_path):
    postings = [make_posting("dq")]

    def score_fn(posting):
        return {"score": 70, "disqualified": True,
                "disqualification_reason": "no visa sponsorship",
                "screen": {"authorization": {"pass": False, "note": "x"}}}

    dbfile, notified = _run(monkeypatch, tmp_path, postings=postings, score_fn=score_fn)
    conn = dbmod.connect(dbfile)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "discarded"
    # A disqualified posting is screened out before the fit phase runs (that's the
    # whole point of screening first) -> persisted with score 0, not a fit score.
    assert row["score"] == 0
    detail = json.loads(row["score_detail"])
    assert detail["disqualification_reason"] == "no visa sponsorship"
    assert notified == []


def test_notify_failure_isolated_across_postings(monkeypatch, tmp_path):
    postings = [make_posting("ok", description=LONG_DESC),
                make_posting("bad", description="BOOM " + LONG_DESC)]

    dbfile, notified = _run(monkeypatch, tmp_path, postings=postings,
                            score_fn=lambda p: {"score": 90, "assessment": _MATCH_MATCH_ASSESSMENT})
    status = _statuses(dbfile)
    assert status["ok"] == "notified"
    assert status["bad"] == "scored"          # send error is transient: kept for a next-pass retry
    assert notified == ["ok"]
    conn = dbmod.connect(dbfile)
    bad = conn.execute("SELECT * FROM job_postings WHERE external_id='bad'").fetchone()
    assert bad["notify_attempts"] == 1 and "telegram" in bad["pipeline_error"]


def test_notify_retry_exhausts_to_failed_without_double_alert(monkeypatch, tmp_path):
    postings = [make_posting("ok", description=LONG_DESC),
                make_posting("bad", description="BOOM " + LONG_DESC)]

    # Three scheduler passes over one db: the failing send is retried each pass
    # and parks 'failed' on the 3rd (NOTIFY_MAX_ATTEMPTS) cumulative failure.
    dbfile, notified = _run(monkeypatch, tmp_path, postings=postings,
                            score_fn=lambda p: {"score": 90, "assessment": _MATCH_MATCH_ASSESSMENT},
                            passes=3)
    status = _statuses(dbfile)
    assert status["bad"] == "failed"          # retry budget spent -> parked, visible in Failed tab
    assert status["ok"] == "notified"
    assert notified == ["ok"]                 # alerted exactly once across all passes
    conn = dbmod.connect(dbfile)
    bad = conn.execute("SELECT * FROM job_postings WHERE external_id='bad'").fetchone()
    assert bad["notify_attempts"] == 3
