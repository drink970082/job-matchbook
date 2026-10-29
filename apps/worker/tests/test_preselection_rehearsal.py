from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ats_worker.preselection_rehearsal import (
    FixtureReadAdapter,
    RehearsalError,
    _assessment_fixture_contract,
    _scenario_contract,
    run_synthetic_rehearsal,
)
from ats_worker.preselection_rehearsal_cli import main as rehearsal_cli_main
from ats_worker.review_batch import ReviewBatchError, build_review_batch


WORKER = Path(__file__).resolve().parents[1]
FIXTURES = WORKER / "tests" / "fixtures"
SCENARIO_PATH = FIXTURES / "preselection_rehearsal_scenario.json"
ASSESSMENT_PATH = FIXTURES / "preselection_assessment_contract.json"
POOL_PATH = FIXTURES / "review_batch_contract.json"


def _fixtures():
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in (
        SCENARIO_PATH, ASSESSMENT_PATH, POOL_PATH,
    ))


def _run_cli_with_fixtures(tmp_path, scenario, assessments, pool):
    scenario_path = tmp_path / "scenario.json"
    assessment_path = tmp_path / "assessments.json"
    pool_path = tmp_path / "pool.json"
    output_path = tmp_path / "report.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    assessment_path.write_text(json.dumps(assessments), encoding="utf-8")
    pool_path.write_text(json.dumps(pool), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, "-m", "ats_worker.preselection_rehearsal_cli",
            "--scenario", str(scenario_path),
            "--assessment-fixture", str(assessment_path),
            "--pool-fixture", str(pool_path),
            "--output", str(output_path),
        ],
        cwd=WORKER, text=True, capture_output=True, check=False,
    )
    return result, output_path


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
    assert fallback["limit"] == 10 and len(fallback["candidates"]) <= 10
    assert [item["candidate_id"] for item in fallback["candidates"]] == sorted(
        item["candidate_id"] for item in fallback["candidates"]
    )
    assert all("assessment_state" in item and "application_certainty" in item
               for item in fallback["candidates"])
    assert all("batch_evidence" in item for item in fallback["candidates"])
    assert {item["certainty"] for item in fallback["application_evidence"]} == {"exact", "probable"}
    fallback_by_id = {item["candidate_id"]: item for item in fallback["candidates"]}
    assert "current" not in fallback_by_id
    assert "applied-unlinked" not in fallback_by_id
    assert fallback["validation_status"] == "validated_current_state"
    assert fallback["recommendations_ready"] is True
    assert fallback_by_id["cross-a"]["assessment_state"] == "current"
    assert fallback_by_id["deferred"]["assessment_state"] == "stale"
    deferred_evidence = fallback_by_id["deferred"]["batch_evidence"]
    assert deferred_evidence["bucket"] == "unresolved"
    assert deferred_evidence["reason"] == "assessment_content_mismatch"
    assert deferred_evidence["source_revision"] == 1
    assert deferred_evidence["content_revision"] == 2
    assert deferred_evidence["content_identity"] == "synthetic-content-deferred-v2"
    assert deferred_evidence["selected_categories"] == ["ranked"]
    assert deferred_evidence["was_selected"] is True
    assert deferred_evidence["is_active_slot_candidate"] is False
    assert deferred_evidence["invalidation_reasons"] == ["content_changed"]
    assert fallback_by_id["unknown-source"]["source_state"] == "unknown"
    assert fallback_by_id["unknown-source"]["batch_evidence"]["bucket"] == "unresolved"
    excluded_by_id = {item["candidate_id"]: item for item in fallback["excluded_evidence"]}
    assert excluded_by_id["current"]["reason"] == "source_closed"
    assert excluded_by_id["current"]["source_state"] == "closed"
    assert excluded_by_id["applied-unlinked"]["reason"] == "confirmed_application"
    assert excluded_by_id["applied-unlinked"]["confirmed_application"] is True

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
    assert set(report["monitoring"]["limits"]) <= {
        "max_tool_calls", "max_read_chars", "max_jd_chunks", "max_unranked_candidates",
        "max_elapsed_seconds", "max_replacements", "max_queue_age_hours",
        "max_overload_count", "max_provider_cost_credits",
    }
    description_reads = report["observations"]["job_description_reads"]
    assert description_reads["selected_candidate_count"] == 4
    assert description_reads["complete_candidate_count"] == 4
    assert description_reads["error_count"] == 0
    assert all(item["complete"] and item["read_complete"]
               for item in description_reads["by_candidate"])
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


def test_unknown_monitoring_value_is_not_echoed_by_the_cli(tmp_path, capsys):
    scenario, assessments, pool = _fixtures()
    secret = "SYNTHETIC_PRIVATE_CONTEXT_DO_NOT_ECHO"
    scenario["monitoring"]["limits"]["raw_response"] = {"nested": secret}

    with pytest.raises(RehearsalError):
        run_synthetic_rehearsal(scenario, assessments, pool)

    result, output_path = _run_cli_with_fixtures(tmp_path, scenario, assessments, pool)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "invalid synthetic rehearsal input or output\n"
    assert secret not in result.stdout + result.stderr
    assert not output_path.exists()


def test_malformed_pool_candidate_fails_through_bounded_cli_validation(tmp_path):
    scenario, assessments, pool = _fixtures()
    pool["candidates"].append({})

    with pytest.raises(ReviewBatchError, match="candidate record is incomplete"):
        run_synthetic_rehearsal(scenario, assessments, pool)

    result, output_path = _run_cli_with_fixtures(tmp_path, scenario, assessments, pool)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "invalid synthetic rehearsal input or output\n"
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in result.stderr
    assert not output_path.exists()


def test_unscoped_requisition_evidence_stays_ambiguous_across_sources():
    scenario, assessments, pool = _fixtures()
    del pool["applications"][0]["source_id"]
    other_source = deepcopy(next(
        candidate for candidate in pool["candidates"]
        if candidate["candidate_id"] == "applied-unlinked"
    ))
    other_source.update({
        "candidate_id": "other-source-same-req",
        "source_id": "board-other",
        "posting_identity": "posting-other-source-same-req",
        "content_identity": "content-other-source-same-req-v1",
        "provenance": ["source-row-other-source-same-req"],
    })
    pool["candidates"].append(other_source)
    batch = build_review_batch(pool)
    adapter = FixtureReadAdapter(
        _scenario_contract(scenario), _assessment_fixture_contract(assessments), pool, batch,
    )

    record_by_id = {item["candidate_id"]: item for item in batch["candidate_records"]}
    for candidate_id in ("applied-unlinked", "other-source-same-req"):
        assert record_by_id[candidate_id]["bucket"] == "unresolved"
        assert record_by_id[candidate_id]["reason"] == "application_identity_ambiguous"
        evidence = adapter.list_applications(candidate_id)
        assert evidence[0]["certainty"] == "ambiguous"
        assert evidence[0]["suppresses_candidate"] is False


def test_fallback_fails_closed_when_current_revalidation_is_incomplete():
    scenario, assessments, pool = _fixtures()
    pool["policy"]["max_revalidation_work"] = 1

    report = run_synthetic_rehearsal(scenario, assessments, pool)

    fallback = report["observations"]["fallback"]
    assert fallback["validation_status"] == "unverified"
    assert fallback["recommendations_ready"] is False
    assert fallback["candidates"] == []
    assert fallback["excluded_evidence"] == []
    cases = {item["name"]: item["status"] for item in report["cases"]}
    assert cases["local_unranked_fallback"] == "failed"


@pytest.mark.parametrize(
    ("state", "expected_status", "expected_source_present", "expected_read_complete", "expected_error"),
    [
        ("missing", "missing", False, False, "fixture_missing"),
        ("empty", "empty", True, True, None),
        ("partial", "incomplete", True, False, "timeout"),
    ],
)
def test_selected_job_description_completeness_is_per_candidate_and_visible(
    tmp_path, state, expected_status, expected_source_present, expected_read_complete, expected_error,
):
    scenario, assessments, pool = _fixtures()
    scenario["job_description_chunk_size"] = 32
    if state == "missing":
        del scenario["job_descriptions"]["similar-b"]
    elif state == "empty":
        scenario["job_descriptions"]["similar-b"] = ""
    else:
        scenario["job_description_read_failures"] = {
            "similar-b": {"after_chunks": 1, "error_category": "timeout"},
        }

    result, output_path = _run_cli_with_fixtures(tmp_path, scenario, assessments, pool)

    assert result.returncode == 0, result.stderr
    report = json.loads(output_path.read_text(encoding="utf-8"))
    evidence = {
        item["candidate_id"]: item
        for item in report["observations"]["job_description_reads"]["by_candidate"]
    }["similar-b"]
    assert evidence["status"] == expected_status
    assert evidence["source_present"] is expected_source_present
    assert evidence["read_complete"] is expected_read_complete
    assert evidence["complete"] is False
    assert evidence["error_category"] == expected_error
    cases = {item["name"]: item["status"] for item in report["cases"]}
    assert cases["multi_page_multi_chunk"] == "failed"
    assert any(status == "failed" for status in cases.values())


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
