"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

from ats_worker import db, pipeline

NOW = "2026-06-04T08:00:00.000Z"


def _posting(external_id, **over):
    base = {
        "source": "greenhouse",
        "external_id": external_id,
        "company_name": "Acme",
        "job_title": "Software Engineer",
        "location": "Remote",
        "job_url": f"https://example.com/jobs/{external_id}",
        "description": "Build things with Python.",
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
    filters = {"keywords": ["engineer"], "locations": ["remote"]}
    inserted = pipeline.run_fetch(conn, companies, filters, now=NOW, fetch_fn=fetch_fn)
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
    inserted = pipeline.run_fetch(conn, companies, {}, now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1


# --- run_score ------------------------------------------------------------

def _seed_new(conn, ids):
    db.upsert_postings(conn, [_posting(i) for i in ids], now=NOW)


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

def _seed_scored(conn, scores):
    """scores: dict external_id -> score. Leaves rows in 'scored'."""
    _seed_new(conn, list(scores))
    for r in conn.execute("SELECT id, external_id FROM job_postings").fetchall():
        db.save_score(conn, r["id"], score=scores[r["external_id"]],
                      score_detail={"missing_keywords": ["aws"]}, now=NOW)


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

def _seed_tailored(conn, ids):
    _seed_scored(conn, {i: 90 for i in ids})
    for r in conn.execute("SELECT id FROM job_postings").fetchall():
        db.save_resume(conn, r["id"], resume_tex="T",
                       resume_path=f"resumes/{r['id']}.pdf", resume_pages=1, now=NOW)


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
