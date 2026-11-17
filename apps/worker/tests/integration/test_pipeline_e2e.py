"""Integration: the real run_once screen pass over a real temp SQLite.

Only the external seams are faked: fetch (board APIs) and the screen provider call.
Everything else is real: run_once's wiring, the pipeline stages and the SQLite DB.
"""
from __future__ import annotations

import pytest

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
from ats_worker import run
from tests._helpers import bootstrap_db, make_posting

pytestmark = pytest.mark.integration


def test_a_pass_screens_new_rows_and_leaves_their_lifecycle_alone(monkeypatch, tmp_path):
    dbfile = bootstrap_db(str(tmp_path / "applications.db"))
    postings = [make_posting("keep"), make_posting("dq")]
    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda conn, companies, title_filter, *, now, **_:
                            dbmod.upsert_postings(conn, postings, now=now))
    monkeypatch.setattr(run.pipeline, "run_expire", lambda *a, **k: 0)

    def fake_screen_posting(posting, **_):
        if posting["external_id"] == "dq":
            return {"disqualified": True, "disqualification_reason": "degree: PhD",
                    "screen": {"degree": {"pass": False, "note": "PhD"}}}
        return {"disqualified": False, "disqualification_reason": "",
                "screen": {"degree": {"pass": True, "note": ""}}}

    monkeypatch.setattr(run, "screen_posting", fake_screen_posting)
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "candidate:\n  highest_degree: \"Master's\"\n")

    run.run_once(cfg, db_path=dbfile, env={"OLLAMA_HOST": "h"})

    conn = dbmod.connect(dbfile)
    rows = conn.execute(
        "SELECT p.external_id, p.pipeline_status, s.state FROM job_postings p "
        "JOIN job_screenings s ON s.job_posting_id = p.id ORDER BY p.external_id"
    ).fetchall()
    assert [(r["external_id"], r["pipeline_status"], r["state"]) for r in rows] == [
        ("dq", "new", "complete"), ("keep", "new", "complete")]
