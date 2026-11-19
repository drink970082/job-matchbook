"""The MCP read side's effective JEV status, case by case from the fixture the web's
test reads too (tests/fixtures/jev-status-cases.json): a change to either side's rule
fails one of the two suites."""
from __future__ import annotations

import json
import sqlite3

import pytest

from ats_worker.mcp import read_repository as rr
from tests._helpers import FIXTURES, bootstrap_db

CASES = json.loads((FIXTURES / "jev-status-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_effective_jev_status_matches_the_shared_cases(tmp_path, case):
    conn = sqlite3.connect(bootstrap_db(tmp_path / "p.db"))
    conn.execute("INSERT INTO job_postings (id, source, external_id, company_name, job_title, job_url, "
                 "description, created_at, source_content_revision) VALUES (1, 'greenhouse', '1', 'A', "
                 "'Eng', 'https://x', 'jd', '2026-11-01T00:00:00Z', ?)", (case["posting_revision"],))
    if case["current_policy"] is not None:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('jev_current_policy_sha256', ?)",
                     (case["current_policy"],))
    a = case["assessment"]
    if a:
        conn.execute("INSERT INTO job_jev_assessments (job_posting_id, state, verdict, policy_sha256, "
                     "source_content_revision, last_attempted_at, created_at) VALUES (1, ?, ?, ?, ?, 'x', 'x')",
                     (a["state"], a["verdict"], a["policy_sha256"], a["source_content_revision"]))
    o = case["override"]
    if o:
        conn.execute("INSERT INTO job_triage_overrides (job_posting_id, decision, actor, "
                     "source_content_revision, created_at) VALUES (1, ?, 'mcp', ?, 'x')",
                     (o["decision"], o["source_content_revision"]))
    status, model = conn.execute(
        f"SELECT {rr._jev_status_sql()}, {rr._jev_model_status_sql()} FROM job_postings p"
        f"{rr._JEV_JOIN} WHERE p.id=1").fetchone()
    assert (status, model) == (case["status"], case["model_status"])
