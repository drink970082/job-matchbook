"""The intake funnel (#248): the shared cases the web reads too, and a recorded pass whose
figures add up with nothing unaccounted."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest

from ats_worker import config as cfgmod
from ats_worker import run
from ats_worker.mcp import read_repository as rr
from tests._helpers import FIXTURES, bootstrap_db, make_posting

CASE = json.loads((FIXTURES / "intake-funnel-cases.json").read_text())


def _seed(path):
    conn = sqlite3.connect(bootstrap_db(path))
    for r in CASE["runs"]:
        counts = r["counts"] if isinstance(r["counts"], str) else json.dumps(r["counts"])
        conn.execute("INSERT INTO worker_runs (started_at, status, fetch_only, jev_enabled, "
                     "config_json, counts_json) VALUES (?, ?, 0, 1, '{}', ?)",
                     (r["started_at"], r["status"], counts))
    for i, p in enumerate(CASE["postings"], start=1):
        conn.execute("INSERT INTO job_postings (id, source, external_id, company_name, job_title, job_url, "
                     "description, created_at, pipeline_status, source_state, verdict) "
                     "VALUES (?, 'greenhouse', ?, 'A', 'Eng', 'https://x', 'jd', ?, ?, ?, ?)",
                     (i, str(i), p["created_at"], p["pipeline_status"], p["source_state"], p["verdict"]))
        if p["screen"] is not None:
            conn.execute("INSERT INTO job_screenings (job_posting_id, state, result_json, backend, "
                         "evaluator_version, last_attempted_at, created_at) "
                         "VALUES (?, 'complete', ?, 'ollama', 'v', 'x', 'x')", (i, p["screen"]))
        if p["override"]:
            conn.execute("INSERT INTO job_triage_overrides (job_posting_id, decision, actor, "
                         "source_content_revision, created_at) VALUES (?, ?, 'mcp', 1, 'x')",
                         (i, p["override"]))
    conn.commit()
    conn.close()


def _assert_reconciles(window):
    left = window["stages"][0]["input"]
    for s in window["stages"]:
        assert s["input"] == left, s["stage"]
        assert s["output"] == s["input"] - s["removed"], s["stage"]
        left = s["output"]
    assert left == window["open"]


def test_overview_funnel_matches_the_shared_case(tmp_path):
    _seed(tmp_path / "f.db")
    clock = lambda: datetime.fromisoformat(CASE["now"])  # noqa: E731
    funnel = rr.ReadOnlyATSRepository(tmp_path / "f.db", clock=clock).get_ats_overview()["intake_funnel"]
    for window, expected in CASE["expected"].items():
        assert funnel[window] == expected
        _assert_reconciles(funnel[window])


def test_no_pass_recorded(tmp_path):
    bootstrap_db(tmp_path / "e.db")
    funnel = rr.ReadOnlyATSRepository(tmp_path / "e.db").get_ats_overview()["intake_funnel"]
    assert funnel["latest_pass"] is None
    assert (funnel["last_7_days"]["passes"], funnel["last_7_days"]["open"]) == (0, 0)


@pytest.mark.integration
def test_a_recorded_pass_reconciles_stage_by_stage(monkeypatch, tmp_path):
    """Two real passes over one board: every listing is in a named bucket, and the second
    pass, which stores nothing new, has no postings of its own."""
    listing = [make_posting("ok"), make_posting("ok2"),
               make_posting("title", job_title="Sales Manager"),
               make_posting("old", posted_at="2020-01-01"),
               make_posting("intern", job_title="Software Engineer Intern"),
               make_posting("blank", description="")]
    monkeypatch.setattr(run, "fetch_company",
                        lambda source, slug, name, **_: [dict(p) for p in listing])
    monkeypatch.setattr(run, "fetch_one_company", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "capture_usage", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "make_screener", lambda *_a, **_k: lambda prompt, schema: "{}")
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "title_filter: [engineer]\nmax_age_days: 365\n"
        "candidate:\n  exclude_internships: true\n")
    dbfile = bootstrap_db(tmp_path / "p.db")
    ticks = iter(["2026-11-23T05:00:00.000Z", "2026-11-24T05:00:00.000Z"])
    for now in ticks:
        monkeypatch.setattr(run, "_now", lambda now=now: now)
        run.run_once(cfg, db_path=dbfile, env={}, fetch_only=True)
    clock = lambda: datetime.fromisoformat(CASE["now"])  # noqa: E731
    funnel = rr.ReadOnlyATSRepository(dbfile, clock=clock).get_ats_overview()["intake_funnel"]
    both, latest = funnel["last_7_days"], funnel["latest_pass"]
    for window in (both, latest):
        _assert_reconciles(window)
        assert window["stages"][1]["reasons"]["unaccounted"] == 0
    assert latest["stages"][0]["input"] == 6 and latest["stages"][1]["output"] == 0
    assert both["stages"][0]["input"] == 12 and both["stages"][1]["output"] == 3
    assert both["stages"][3]["reasons"] == {"internships": 1}
