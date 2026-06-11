"""Integration: the real run_once status machine over a real temp SQLite.

Only the four external seams are faked — fetch (board APIs), score (Ollama),
tailor (Claude+tectonic), notify (Telegram). Everything else is real: run_once's
wiring, the pipeline stages, and the SQLite DB. This exercises the full
new -> scored -> (discarded|tailored) -> notified loop and the failure/discard
routing across stages, which the per-stage unit tests can't assert together.
"""
from __future__ import annotations

import json

import pytest

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
from ats_worker import run
from tests._helpers import bootstrap_db, make_posting

pytestmark = pytest.mark.integration

ENV = {"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
       "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"}


def _cfg():
    return cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\nthreshold: 75\n"
    )


def _run(monkeypatch, tmp_path, *, postings, score_fn):
    """Run the real run_once with canned postings + a fake scorer. Tailor raises
    only when the JD contains the marker 'BOOM' (for failure-isolation tests);
    notify just records the external_ids it was asked to send. Returns
    (db_path, notified_ids)."""
    dbfile = bootstrap_db(str(tmp_path / "applications.db"))

    def fake_run_fetch(conn, companies, title_filter, *, now, **_):
        return dbmod.upsert_postings(conn, postings, now=now)

    def fake_tailor(master, jd, missing, *, claude, compile_pdf, count_pages,
                    max_rounds, out_dir):
        if "BOOM" in jd:
            raise RuntimeError("tectonic exploded")
        return {"tex": "T", "pdf_path": f"{out_dir}/resume.pdf", "pages": 1, "ok": True}

    notified: list[str] = []
    monkeypatch.setattr(run.pipeline, "run_fetch", fake_run_fetch)
    monkeypatch.setattr(run, "score_posting", lambda posting, resume, **kw: score_fn(posting))
    monkeypatch.setattr(run, "make_claude", lambda *a, **k: (lambda p: "tex"))
    monkeypatch.setattr(run, "tailor_resume", fake_tailor)
    monkeypatch.setattr(run, "notify_posting",
                        lambda posting, pdf, *, token, chat_id: notified.append(posting["external_id"]))

    run.run_once(_cfg(), db_path=dbfile, resume_text="r", master_tex="m",
                 env=ENV, resume_dir=str(tmp_path / "resumes"))
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
        return {"score": 50} if eid == "low" else {"score": 90}

    dbfile, notified = _run(monkeypatch, tmp_path, postings=postings, score_fn=score_fn)
    assert _statuses(dbfile) == {"dq": "discarded", "low": "scored", "hi": "notified"}
    assert notified == ["hi"]   # only the above-threshold posting is tailored+notified


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
    assert row["score"] == 70
    detail = json.loads(row["score_detail"])
    assert detail["disqualification_reason"] == "no visa sponsorship"
    assert notified == []


def test_tailor_failure_isolated_across_postings(monkeypatch, tmp_path):
    postings = [make_posting("ok", description="clean jd"),
                make_posting("bad", description="BOOM jd")]

    dbfile, notified = _run(monkeypatch, tmp_path, postings=postings,
                            score_fn=lambda p: {"score": 90})
    status = _statuses(dbfile)
    assert status["ok"] == "notified"
    assert status["bad"] == "failed"          # tailor raised; row isolated, not aborting the batch
    assert notified == ["ok"]
    conn = dbmod.connect(dbfile)
    bad = conn.execute("SELECT * FROM job_postings WHERE external_id='bad'").fetchone()
    assert bad["attempts"] == 1 and "tectonic" in bad["pipeline_error"]
