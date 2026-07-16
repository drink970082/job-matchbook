"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

import json as _json

from ats_worker import db, pipeline
from tests._helpers import (
    NOW,
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


# --- run_score ------------------------------------------------------------

def test_run_score_only_new_and_one_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])

    def score_fn(posting):
        if posting["external_id"] == "2":
            raise RuntimeError("ollama down")
        return {"score": 90, "matched_keywords": [], "missing_keywords": [],
                "reasoning": "ok"}

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "scored"
    assert statuses["3"] == "scored"
    assert statuses["2"] == "failed"


def test_run_score_skips_non_new(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.save_score(conn, pid, score=10, score_detail={}, now=NOW)  # now 'scored'

    called = []

    def score_fn(posting):
        called.append(posting["external_id"])
        return {"score": 1}

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)
    assert called == []


# --- run_notify -----------------------------------------------------------

def test_run_notify_gates_on_threshold(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"hi": 90, "lo": 50})

    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append(posting["external_id"])

    pipeline.run_notify(conn, 75, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
    assert notified == ["hi"]

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["hi"] == "notified"
    assert statuses["lo"] == "scored"  # untouched, below threshold


def test_run_notify_advances_and_passes_token_chat(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95})

    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append((posting["external_id"], token, chat_id))

    pipeline.run_notify(conn, 75, now=NOW, notify_fn=notify_fn, token="tok", chat_id="cid")
    assert {n[0] for n in notified} == {"1", "2"}
    assert all(n[1] == "tok" and n[2] == "cid" for n in notified)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses == {"1": "notified", "2": "notified"}


def test_run_notify_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95})

    def notify_fn(posting, *, token, chat_id):
        if posting["external_id"] == "1":
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, 75, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
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

    def score_fn(posting):
        if posting["external_id"] == "1":
            return {"score": 88, "matched_keywords": [], "missing_keywords": [],
                    "reasoning": "strong", "disqualified": True,
                    "disqualification_reason": "requires a PhD"}
        return {"score": 80, "disqualified": False}

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "discarded"
    assert rows["2"]["pipeline_status"] == "scored"
    assert rows["1"]["score"] == 88  # score kept even when discarded
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["disqualified"] is True
    assert detail["disqualification_reason"] == "requires a PhD"


def test_run_score_insufficient_context_persisted(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def score_fn(posting):
        return {"score": 55, "insufficient_context": True, "disqualified": False}

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "scored"   # still scored; the UI routes it
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["insufficient_context"] is True


# --- failure bookkeeping + stage gating -----------------------------------

def test_run_score_failure_records_error_and_increments_attempts(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def score_fn(posting):
        raise RuntimeError("ollama down")

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert row["attempts"] == 1
    assert "ollama down" in row["pipeline_error"]


def test_run_score_passes_full_posting_to_scorer(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    seen = {}

    def score_fn(posting):
        seen.update(posting)
        return {"score": 50}

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)
    assert seen.get("description")   # the JD text reached the scorer, not just the id
    assert seen.get("job_title")


def test_run_score_persists_recommended_resume(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def score_fn(posting):
        base = {"score": 88, "matched_keywords": ["python"],
                "missing_keywords": [], "reasoning": "fits the swe resume best"}
        if posting["external_id"] == "1":
            base["recommended_resume"] = "swe"
        return base

    pipeline.run_score(conn, now=NOW, score_fn=score_fn)

    details = {
        r["external_id"]: _json.loads(r["score_detail"])
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert details["1"]["recommended_resume"] == "swe"
    # absent from the scorer result -> absent from the stored JSON (old shape)
    assert "recommended_resume" not in details["2"]


def test_run_notify_threshold_is_inclusive(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"edge": 75})
    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append(posting["external_id"])

    pipeline.run_notify(conn, 75, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
    assert notified == ["edge"]      # score == threshold IS notified (>= not >)


def test_run_notify_send_error_retries_then_parks_failed(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90})
    calls = []

    def notify_fn(posting, *, token, chat_id):
        calls.append(posting["external_id"])
        raise RuntimeError("telegram 429")

    # Each pass retries the still-'scored' row; the 3rd cumulative failure
    # (NOTIFY_MAX_ATTEMPTS) parks it 'failed'.
    for expected_attempts, expected_status in ((1, "scored"), (2, "scored"), (3, "failed")):
        pipeline.run_notify(conn, 75, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
        row = conn.execute("SELECT * FROM job_postings").fetchone()
        assert row["attempts"] == expected_attempts
        assert row["pipeline_status"] == expected_status
        assert "telegram" in row["pipeline_error"]
    assert calls == ["a", "a", "a"]
    # Parked rows are terminal: a further pass must not retry them.
    pipeline.run_notify(conn, 75, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
    assert calls == ["a", "a", "a"]


def test_run_notify_retry_then_success_clears_error(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90})
    sends = []

    def flaky_notify(posting, *, token, chat_id):
        sends.append(posting["external_id"])
        if len(sends) == 1:
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, 75, now=NOW, notify_fn=flaky_notify, token="t", chat_id="c")
    pipeline.run_notify(conn, 75, now=NOW, notify_fn=flaky_notify, token="t", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "notified"
    assert row["pipeline_error"] is None   # cleared on the successful send
    assert row["attempts"] == 1            # the earlier failure stays counted


def test_stages_ignore_wrong_status_rows(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["n"])                      # stays 'new'
    _seed_scored(conn, {"lo": 50, "hi": 90})   # one below, one above threshold

    notified = []
    pipeline.run_notify(
        conn, 75, now=NOW, token="x", chat_id="y",
        notify_fn=lambda p, *, token, chat_id: notified.append(p["external_id"]),
    )
    assert notified == ["hi"]         # only 'scored' >= threshold ('new' + below ignored)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["n"] == "new"
    assert statuses["lo"] == "scored"
