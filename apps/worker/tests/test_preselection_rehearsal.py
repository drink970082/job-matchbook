from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ats_worker.preselection_rehearsal import RehearsalError, run_synthetic_rehearsal
from ats_worker.preselection_rehearsal_cli import main as rehearsal_cli_main


WORKER = Path(__file__).resolve().parents[1]
FIXTURES = WORKER / "tests" / "fixtures"
SCENARIO_PATH = FIXTURES / "preselection_rehearsal_scenario.json"
ASSESSMENT_PATH = FIXTURES / "preselection_assessment_contract.json"
POOL_PATH = FIXTURES / "review_batch_contract.json"


def _fixtures():
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in (
        SCENARIO_PATH, ASSESSMENT_PATH, POOL_PATH,
    ))


def test_explicit_cli_composes_real_assessment_and_batch_modules(tmp_path):
    output = tmp_path / "rehearsal-report.json"
    result = subprocess.run(
        [
            sys.executable, "-m", "ats_worker.preselection_rehearsal_cli",
            "--scenario", str(SCENARIO_PATH),
            "--assessment-fixture", str(ASSESSMENT_PATH),
            "--pool-fixture", str(POOL_PATH),
            "--output", str(output),
        ],
        cwd=WORKER,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["scope"] == "synthetic_rehearsal"
    assert report["synthetic"] is True
    assert report["modules"] == {
        "assessment_view": 1,
        "review_batch": 1,
        "rehearsal": 1,
    }
    assert report["observations"]["batch"]["pages_read"] == 2
    assert report["observations"]["batch"]["due_retry_count"] == 1
    assert report["observations"]["batch"]["deferred_count"] == 1
    assert report["observations"]["job_description_reads"]["chunk_count"] >= 6
    assert report["observations"]["job_description_reads"]["multi_chunk_count"] >= 2
    assert report["observations"]["job_description_reads"]["characters_read"] <= 1024

    assessments = report["observations"]["assessments"]
    states = {item["assessment_state"] for item in assessments}
    assert {"current", "stale", "unknown"} <= states
    assert any(item["latest_attempt_state"] == "provider_error" for item in assessments)
    assert any(item["case_name"] == "late_result_for_older_content"
               and item["assessment_state"] == "stale" for item in assessments)

    probes = {item["outcome"]: item for item in report["observations"]["source_probes"]}
    assert probes["empty"]["error_category"] is None
    assert probes["unavailable"]["error_category"] == "timeout"
    applications = report["observations"]["applications"]
    exact = next(item for item in applications if item["candidate_id"] == "applied-unlinked")
    probable = next(item for item in applications if item["candidate_id"] == "similar-a")
    assert exact["certainty"] == "exact" and exact["suppresses_candidate"] is True
    assert probable["certainty"] == "probable" and probable["suppresses_candidate"] is False

    revalidation = report["observations"]["revalidation"]
    assert revalidation["invalidations"] >= 2
    assert revalidation["replacement_count"] == 1
    assert revalidation["unfilled_slots"] >= 1
    assert report["observations"]["queue"]["overloaded"] is True
    assert report["observations"]["queue"]["oldest_age_hours"] > 24
    assert "queue_age_limit_exceeded" in report["monitoring_breaches"]
    assert "elapsed_time_limit_exceeded" in report["monitoring_breaches"]

    repeated = report["observations"]["repeated_day"]
    assert repeated["same_content_revision"] is True
    assert repeated["first_occurrence_id"] != repeated["next_occurrence_id"]
    fallback = report["observations"]["fallback"]
    assert fallback["ranking_enabled"] is False
    assert fallback["limit"] == 3 and len(fallback["candidates"]) <= 3
    assert [item["candidate_id"] for item in fallback["candidates"]] == sorted(
        item["candidate_id"] for item in fallback["candidates"]
    )
    assert all("assessment_state" in item and "application_certainty" in item
               for item in fallback["candidates"])
    assert all("batch_evidence" in item for item in fallback["candidates"])
    assert {item["certainty"] for item in fallback["application_evidence"]} == {"exact", "probable"}

    cases = {item["name"]: item["status"] for item in report["cases"]}
    assert cases["multi_page_multi_chunk"] == "passed"
    assert cases["empty_vs_unavailable_source"] == "passed"
    assert cases["bounded_revalidation"] == "passed"
    assert cases["provider_outage_and_private_input"] == "passed"
    assert report["live_gates"]["scheduled_access"] == "not_exercised"
    assert report["live_gates"]["provider_quality_and_price"] == "not_recorded"
    assert report["live_gates"]["assessment_go"] == "not_exercised"
    assert report["observations"]["resource_status"]["actual_provider_cost"] == "unknown"
    assert "max_provider_cost_credits" in report["monitoring"]["unknown_limits"]
    serialized = json.dumps(report)
    assert "SYNTHETIC_PRIVATE_" not in serialized
    assert "Fabricated description" not in serialized
    assert "Synthetic JD:" not in serialized


def test_missing_monitoring_limit_is_reported_unknown_without_a_default():
    scenario, assessments, pool = _fixtures()
    del scenario["monitoring"]["limits"]["max_queue_age_hours"]

    report = run_synthetic_rehearsal(scenario, assessments, pool)

    assert "max_queue_age_hours" in report["monitoring"]["unknown_limits"]
    assert "queue_age_limit_exceeded" not in report["monitoring_breaches"]
    assert report["observations"]["queue"]["oldest_age_hours"] > 0


def test_rehearsal_cli_requires_distinct_explicit_output_path(tmp_path):
    result = subprocess.run(
        [
            sys.executable, "-m", "ats_worker.preselection_rehearsal_cli",
            "--scenario", str(SCENARIO_PATH),
            "--assessment-fixture", str(ASSESSMENT_PATH),
            "--pool-fixture", str(POOL_PATH),
            "--output", str(SCENARIO_PATH),
        ],
        cwd=WORKER,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert SCENARIO_PATH.read_text(encoding="utf-8").startswith("{")
    assert str(SCENARIO_PATH) not in result.stderr
    assert "invalid" in result.stderr


def test_consumer_import_does_not_need_runtime_or_private_data_modules():
    script = """
import builtins
original_import = builtins.__import__
forbidden = ("sqlite3", "requests", "ats_worker.run", "ats_worker.config", "ats_worker.score")
def guarded_import(name, *args, **kwargs):
    if any(name == item or name.startswith(item + ".") for item in forbidden):
        raise AssertionError("forbidden dependency imported")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import ats_worker.preselection_rehearsal
import ats_worker.preselection_rehearsal_cli
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKER,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_direct_cli_main_writes_only_to_the_explicit_report_path(tmp_path, capsys):
    output = tmp_path / "direct-report.json"

    result = rehearsal_cli_main([
        "--scenario", str(SCENARIO_PATH),
        "--assessment-fixture", str(ASSESSMENT_PATH),
        "--pool-fixture", str(POOL_PATH),
        "--output", str(output),
    ])

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["scope"] == "synthetic_rehearsal"
    assert capsys.readouterr().out == "synthetic rehearsal report written\n"


def test_direct_cli_read_errors_do_not_echo_fixture_paths(tmp_path, capsys):
    missing = tmp_path / "missing-fixture.json"
    output = tmp_path / "report.json"

    result = rehearsal_cli_main([
        "--scenario", str(missing),
        "--assessment-fixture", str(ASSESSMENT_PATH),
        "--pool-fixture", str(POOL_PATH),
        "--output", str(output),
    ])

    assert result == 2
    error = capsys.readouterr().err
    assert error == "invalid synthetic rehearsal input or output\n"
    assert str(missing) not in error
    assert not output.exists()


def test_explicit_call_and_read_bounds_fail_closed_without_defaults():
    scenario, assessments, pool = _fixtures()
    scenario["monitoring"]["limits"]["max_tool_calls"] = 1
    with pytest.raises(RehearsalError, match="tool call bound"):
        run_synthetic_rehearsal(scenario, assessments, pool)

    scenario, assessments, pool = _fixtures()
    scenario["monitoring"]["limits"]["max_read_chars"] = 100
    with pytest.raises(RehearsalError, match="read character bound"):
        run_synthetic_rehearsal(scenario, assessments, pool)


def test_monitoring_replacement_limit_must_match_the_explicit_batch_policy():
    scenario, assessments, pool = _fixtures()
    scenario["monitoring"]["limits"]["max_replacements"] = 0

    with pytest.raises(RehearsalError, match="replacement limits must agree"):
        run_synthetic_rehearsal(scenario, assessments, pool)
