"""The MCP read side's effective status, case by case from the fixture the web's test
reads too (tests/fixtures/effective-status-cases.json): a change to either side's rule
fails one of the two suites."""
from __future__ import annotations

import json
import sqlite3

import pytest

from ats_worker.mcp import read_repository as rr
from tests._helpers import FIXTURES, bootstrap_db

CASES = json.loads((FIXTURES / "effective-status-cases.json").read_text())["cases"]


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "p.db"
    conn = sqlite3.connect(bootstrap_db(path))
    for i, case in enumerate(CASES, start=1):
        conn.execute("INSERT INTO job_postings (id, source, external_id, company_name, job_title, job_url, "
                     "description, created_at, source_content_revision, pipeline_status, source_state, verdict) "
                     "VALUES (?, 'greenhouse', ?, 'A', ?, 'https://x', 'jd', '2026-11-01T00:00:00Z', 2, ?, ?, ?)",
                     (i, str(i), case["name"], case["pipeline_status"], case["source_state"], case["verdict"]))
        if case["override"]:
            conn.execute("INSERT INTO job_triage_overrides (job_posting_id, decision, actor, "
                         "source_content_revision, created_at) VALUES (?, ?, 'mcp', 1, 'x')",
                         (i, case["override"]))
    conn.commit()
    conn.close()
    return rr.ReadOnlyATSRepository(path)


def _titles(page):
    return {row["job_title"] for row in page["items"]}


def test_list_and_get_report_the_shared_effective_status(repo):
    rows = {row["job_title"]: row for row in repo.list_jobs(status="all", closed="all", limit=100)["items"]}
    assert {name: row["status"] for name, row in rows.items()} == {c["name"]: c["status"] for c in CASES}
    for case in CASES:
        row = rows[case["name"]]
        assert row["verdict"] == case["verdict"]
        assert repo.get_job(row["id"])["status"] == case["status"], case["name"]


def test_default_view_follows_the_shared_cases(repo):
    """A discarded posting rescued by a keep override is in the default view."""
    page = repo.list_jobs(limit=100)
    assert _titles(page) == {c["name"] for c in CASES if c["listed"]}
    assert "discarded rescued by keep" in _titles(page)
    hidden = [c for c in CASES if not c["listed"] and c["source_state"] != "closed"]
    assert page["status_filter"]["hidden_count"] == len(hidden)


@pytest.mark.parametrize("status", rr.STATUSES)
def test_status_filter_lists_exactly_that_effective_status(repo, status):
    assert _titles(repo.list_jobs(status=status, closed="all", limit=100)) == {
        c["name"] for c in CASES if c["status"] == status}


def test_closed_filter(repo):
    closed = {c["name"] for c in CASES if c["source_state"] == "closed"}
    assert _titles(repo.list_jobs(status="all", closed="only", limit=100)) == closed
    assert not closed & _titles(repo.list_jobs(status="all", limit=100))
    with pytest.raises(rr.QueryInputError):
        repo.list_jobs(closed="maybe")
    with pytest.raises(rr.QueryInputError):
        repo.list_jobs(status="stale")


def test_overview_counts_effective_status_of_open_new_postings(repo):
    counts = {row["status"]: row["count"] for row in repo.get_ats_overview()["status_counts"]["counts"]}
    open_new = [c for c in CASES if c["pipeline_status"] == "new" and c["source_state"] != "closed"]
    assert counts == {s: sum(c["status"] == s for c in open_new) for s in rr.STATUSES}


def test_profile_version_is_the_one_the_verdict_was_judged_under(tmp_path):
    path = tmp_path / "v.db"
    conn = sqlite3.connect(bootstrap_db(path))
    for i, verdict in ((1, "keep"), (2, "discarded"), (3, "pending")):
        conn.execute("INSERT INTO job_postings (id, source, external_id, company_name, job_title, job_url, "
                     "description, created_at, verdict) VALUES (?, 'greenhouse', ?, 'A', 'Eng', 'https://x', "
                     "'jd', 'x', ?)", (i, str(i), verdict))
    for i in (1, 2):
        conn.execute("INSERT INTO job_screenings (job_posting_id, state, result_json, backend, evaluator_version, "
                     "last_attempted_at, created_at, profile_version) VALUES (?, 'complete', '{}', 'ollama', "
                     "'v', 'x', 'x', 2)", (i,))
    conn.execute("INSERT INTO job_jev_assessments (job_posting_id, state, verdict, reasons_json, profile_version, "
                 "last_attempted_at, created_at) VALUES (1, 'complete', 'keep', '[\"role_match\"]', 3, 'x', 'x')")
    conn.commit()
    conn.close()
    repo = rr.ReadOnlyATSRepository(path)
    rows = {row["id"]: row for row in repo.list_jobs(status="all", limit=10)["items"]}
    assert {i: rows[i]["profile_version"] for i in rows} == {1: 3, 2: 2, 3: None}
    assert rows[1]["jev"]["reasons"] == ["role_match"]
    assert repo.get_job(1)["profile_version"] == 3
    assert "policy_sha256" not in repo.get_job(1)["jev"]
