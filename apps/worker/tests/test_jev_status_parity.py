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


CLOSED_CASES = json.loads((FIXTURES / "closed-stage-cases.json").read_text())["cases"]
_SCREENS = {"pass": '{"disqualified":false,"screen":{"location":{"pass":true}}}',
            "reject": '{"disqualified":true,"screen":{"degree":{"pass":false,"note":"PhD"}}}'}


def test_closed_postings_follow_the_shared_stage_cases(tmp_path):
    """list_jobs hides every closed posting by default, as the web files it only under
    the `closed` stage (tests/fixtures/closed-stage-cases.json); closed='only' lists
    exactly those, closed='all' everything."""
    conn = sqlite3.connect(bootstrap_db(tmp_path / "c.db"))
    ids: dict[str, int] = {}
    for i, case in enumerate(CLOSED_CASES, start=1):
        conn.execute("INSERT INTO job_postings (id, source, external_id, company_name, job_title, job_url, "
                     "description, created_at, source_content_revision, pipeline_status, source_state) "
                     "VALUES (?, 'greenhouse', ?, 'A', 'Eng', 'https://x', 'jd', '2026-11-01T00:00:00Z', 1, ?, ?)",
                     (i, str(i), case["pipeline_status"], case["source_state"]))
        if case["screen"]:
            conn.execute("INSERT INTO job_screenings (job_posting_id, state, result_json, backend, "
                         "evaluator_version, last_attempted_at, created_at) "
                         "VALUES (?, 'complete', ?, 'ollama', 'screen-v1', 'x', 'x')", (i, _SCREENS[case["screen"]]))
        if case["verdict"]:
            conn.execute("INSERT INTO job_jev_assessments (job_posting_id, state, verdict, policy_sha256, "
                         "source_content_revision, last_attempted_at, created_at) "
                         "VALUES (?, 'complete', ?, 'p', 1, 'x', 'x')", (i, case["verdict"]))
        ids[case["name"]] = i
    conn.commit()
    conn.close()
    repo = rr.ReadOnlyATSRepository(tmp_path / "c.db")

    def listed(**kw):
        return {row["id"] for row in repo.list_jobs(limit=100, **kw)["items"]}

    closed = {ids[c["name"]] for c in CLOSED_CASES if c["stage"] == "closed"}
    open_ = set(ids.values()) - closed
    assert listed(jev="all") == open_
    assert listed(jev="all", closed="only") == closed
    assert listed(jev="all", closed="all") == set(ids.values())
    default = repo.list_jobs(limit=100)
    assert {row["id"] for row in default["items"]} == open_ - {ids["new unknown skip"]}
    assert default["jev_filter"]["hidden_skip_count"] == 1  # the closed skip is not counted
    # The overview's keep/skip counts are the web's keep/jev_skip stages (no rejected `new`
    # rows here): a closed posting counts in neither.
    counts = {row["status"]: row["count"] for row in repo.get_ats_overview()["jev_filter_counts"]["counts"]}
    stages = [c["stage"] for c in CLOSED_CASES]
    assert (counts["keep"], counts["skip"]) == (stages.count("keep"), stages.count("jev_skip"))
    with pytest.raises(rr.QueryInputError):
        repo.list_jobs(closed="maybe")
