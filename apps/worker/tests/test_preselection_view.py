"""Behavioral tests for the provider-free assessment view projection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ats_worker.preselection_view import project_assessment_view


WORKER_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = WORKER_ROOT / "tests" / "fixtures" / "preselection_assessment_contract.json"


def test_fixture_cli_projects_current_synthetic_assessment_to_bounded_view():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ats_worker.preselection_view_cli",
            "--fixture",
            str(FIXTURE),
            "--case",
            "current_success",
        ],
        cwd=WORKER_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    view = json.loads(result.stdout)
    assert view["scope"] == "synthetic_assessment_view"
    assert view["synthetic"] is True
    assert view["assessment_state"] == "current"
    assert view["latest_attempt"]["state"] == "succeeded"
    assert view["components"] == [
        {
            "id": "seniority",
            "label": "Seniority alignment",
            "label_truncated": False,
            "score": 84,
            "jd_evidence": [
                {
                    "id": "jd-qualifications",
                    "label": "Required qualifications",
                    "label_truncated": False,
                    "excerpt": "Fabricated JD text: experience designing reliable data services.",
                    "excerpt_truncated": False,
                }
            ],
        }
    ]
    assert view["assessment_time"] == "2026-10-27T12:30:45.125Z"
    assert view["metadata"]["requested_model"] == "synthetic-requested-model"
    assert "content_digest" not in view["metadata"]
    assert "context_identity" not in view["metadata"]
    serialized = json.dumps(view)
    assert "SYNTHETIC_PRIVATE_" not in serialized
    assert "free_form_explanation" not in serialized
    assert "raw_response" not in serialized


def test_shared_fixture_cases_fail_closed_without_exposing_private_fields():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        view = project_assessment_view(case["snapshot"])
        assert view["assessment_state"] == case["expected_assessment_state"], case["name"]
        assert view["latest_attempt"]["state"] == case["expected_latest_attempt_state"], case["name"]
        assert "SYNTHETIC_PRIVATE_" not in json.dumps(view), case["name"]
        if view["assessment_state"] in {"unknown", "not_assessed"}:
            assert view["components"] == [], case["name"]
            assert view["assessment_time"] is None, case["name"]
            assert view["metadata"] is None, case["name"]

    provider_error = next(case for case in fixture["cases"]
                          if case["name"] == "current_success_with_newer_provider_error")
    preserved = project_assessment_view(provider_error["snapshot"])
    assert preserved["assessment_state"] == "current"
    assert preserved["latest_attempt"]["state"] == "provider_error"
    assert preserved["latest_attempt"]["error_category"] == "timeout"
    assert preserved["components"][0]["score"] == 84

    bounded = next(case for case in fixture["cases"]
                   if case["name"] == "bounded_display_text_is_marked")
    bounded_view = project_assessment_view(bounded["snapshot"])
    assert bounded_view["components"][0]["label_truncated"] is True
    assert len(bounded_view["components"][0]["label"]) == 120
    assert bounded_view["components"][0]["jd_evidence"][0]["excerpt_truncated"] is True
    assert len(bounded_view["components"][0]["jd_evidence"][0]["excerpt"]) == 300
    assert bounded_view["metadata"]["rubric_version_truncated"] is True
    assert bounded_view["latest_attempt"]["requested_model_truncated"] is True
    assert bounded_view["metadata"]["resolved_model_truncated"] is True
    assert bounded_view["latest_attempt"]["resolved_model_truncated"] is True
    assert bounded_view["components"][0]["jd_evidence"][0]["label_truncated"] is True

    boundary = next(case for case in fixture["cases"]
                    if case["name"] == "boundary_whitespace_truncation_remains_valid")
    boundary_view = project_assessment_view(boundary["snapshot"])
    assert boundary_view["assessment_state"] == "current"
    assert boundary_view["components"][0]["label"] == "x" * 119
    assert boundary_view["components"][0]["label_truncated"] is True

    oversized = next(case for case in fixture["cases"]
                     if case["name"] == "oversized_component_list")
    oversized_view = project_assessment_view(oversized["snapshot"])
    assert oversized_view["assessment_state"] == "unknown"
    assert oversized_view["assessment_reason"] == "too_many_components"
    assert oversized_view["components"] == []


@pytest.mark.parametrize("case_name", [
    "malformed_attempt_array_state_preserves_success",
    "malformed_attempt_object_state_preserves_success",
])
def test_fixture_cli_keeps_saved_success_when_latest_attempt_state_is_unhashable(case_name):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ats_worker.preselection_view_cli",
            "--fixture",
            str(FIXTURE),
            "--case",
            case_name,
        ],
        cwd=WORKER_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    view = json.loads(result.stdout)
    assert view["assessment_state"] == "current"
    assert view["latest_attempt"]["state"] == "unknown"
    assert view["components"][0]["score"] == 84


def test_projection_and_cli_import_without_runtime_or_provider_modules():
    code = """
import sys
import ats_worker.preselection_view
import ats_worker.preselection_view_cli
for forbidden in ('requests', 'sqlite3', 'ats_worker.run', 'ats_worker.config', 'ats_worker.score'):
    assert forbidden not in sys.modules, forbidden
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=WORKER_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
