"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

from ats_worker import db, pipeline
from tests._helpers import (
    NOW,
    make_posting as _posting,
    seed_new as _seed_new,
    seed_scored as _seed_scored,
    seed_tailored as _seed_tailored,
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

    pipeline.run_score(conn, "resume text", now=NOW, score_fn=score_fn)

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

    pipeline.run_score(conn, "resume", now=NOW, score_fn=score_fn)
    assert called == []


# --- run_tailor -----------------------------------------------------------

def test_run_tailor_gates_on_threshold(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"hi": 90, "lo": 50})

    tailored = []

    def tailor_fn(posting):
        tailored.append(posting["external_id"])
        return {"tex": "T", "pdf_path": "/tmp/x.pdf", "pages": 1, "ok": True}

    pipeline.run_tailor(conn, "master", 75, now=NOW, tailor_fn=tailor_fn)
    assert tailored == ["hi"]

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["hi"] == "tailored"
    assert statuses["lo"] == "scored"  # untouched, below threshold


def test_run_tailor_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90, "b": 95})

    def tailor_fn(posting):
        if posting["external_id"] == "a":
            raise RuntimeError("tectonic exploded")
        return {"tex": "T", "pdf_path": "/tmp/b.pdf", "pages": 1, "ok": True}

    pipeline.run_tailor(conn, "master", 75, now=NOW, tailor_fn=tailor_fn)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["a"] == "failed"
    assert statuses["b"] == "tailored"


# --- run_notify -----------------------------------------------------------

def test_run_notify_only_tailored_and_advances(db_path):
    conn = db.connect(db_path)
    _seed_tailored(conn, ["1", "2"])

    notified = []

    def notify_fn(posting, pdf_path, *, token, chat_id):
        notified.append((posting["external_id"], pdf_path, token, chat_id))

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="tok", chat_id="cid")
    assert {n[0] for n in notified} == {"1", "2"}
    assert all(n[2] == "tok" and n[3] == "cid" for n in notified)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses == {"1": "notified", "2": "notified"}


def test_run_notify_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_tailored(conn, ["1", "2"])

    def notify_fn(posting, pdf_path, *, token, chat_id):
        if posting["external_id"] == "1":
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "failed"
    assert statuses["2"] == "notified"


def test_run_score_disqualified_is_discarded_with_reason(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def score_fn(posting):
        if posting["external_id"] == "1":
            return {"score": 88, "matched_keywords": [], "missing_keywords": [],
                    "reasoning": "strong", "disqualified": True,
                    "disqualification_reason": "requires a PhD"}
        return {"score": 80, "disqualified": False}

    pipeline.run_score(conn, "resume", now=NOW, score_fn=score_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "discarded"
    assert rows["2"]["pipeline_status"] == "scored"
    assert rows["1"]["score"] == 88  # score kept even when discarded
    import json as _json
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["disqualified"] is True
    assert detail["disqualification_reason"] == "requires a PhD"


# --- failure bookkeeping + stage gating -----------------------------------

def test_run_score_failure_records_error_and_increments_attempts(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def score_fn(posting):
        raise RuntimeError("ollama down")

    pipeline.run_score(conn, "resume", now=NOW, score_fn=score_fn)
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

    pipeline.run_score(conn, "resume", now=NOW, score_fn=score_fn)
    assert seen.get("description")   # the JD text reached the scorer, not just the id
    assert seen.get("job_title")


def test_run_tailor_threshold_is_inclusive(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"edge": 75})
    tailored = []

    def tailor_fn(posting):
        tailored.append(posting["external_id"])
        return {"tex": "T", "pdf_path": "/tmp/x.pdf", "pages": 1, "ok": True}

    pipeline.run_tailor(conn, "master", 75, now=NOW, tailor_fn=tailor_fn)
    assert tailored == ["edge"]      # score == threshold IS tailored (>= not >)


def test_run_tailor_failure_records_attempts(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90})

    def tailor_fn(posting):
        raise RuntimeError("tectonic exploded")

    pipeline.run_tailor(conn, "master", 75, now=NOW, tailor_fn=tailor_fn)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert row["attempts"] == 1
    assert "tectonic" in row["pipeline_error"]


def test_stages_ignore_wrong_status_rows(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["n"])            # stays 'new'
    _seed_scored(conn, {"s": 50})     # 'scored' but below threshold
    _seed_tailored(conn, ["t"])       # 'tailored'

    tailored = []
    pipeline.run_tailor(conn, "m", 75, now=NOW,
                        tailor_fn=lambda p: tailored.append(p["external_id"]))
    assert tailored == []             # nothing 'scored' >= 75

    notified = []
    pipeline.run_notify(
        conn, now=NOW, token="x", chat_id="y",
        notify_fn=lambda p, pdf, *, token, chat_id: notified.append(p["external_id"]),
    )
    assert notified == ["t"]          # only the 'tailored' row


def test_run_notify_passes_resume_path(db_path):
    conn = db.connect(db_path)
    _seed_tailored(conn, ["1"])
    seen = {}

    def notify_fn(posting, pdf_path, *, token, chat_id):
        seen["pdf"] = pdf_path

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="t", chat_id="c")
    assert seen["pdf"] and seen["pdf"].endswith(".pdf")
