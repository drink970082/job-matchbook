import json
from pathlib import Path

import pytest

from ats_worker.preselection.extraction import (
    ExtractionValidationError,
    YoePolicyError,
    evaluate_required_yoe,
    extraction_from_value,
)
from ats_worker.preselection.profile import profile_from_value


FIXTURE = Path(__file__).parent / "fixtures/preselection_yoe_boundaries.synthetic.json"
PROFILE_FIXTURE = Path(__file__).parent / "fixtures/preselection_profile.synthetic.json"


def candidate_profile():
    return profile_from_value(json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8")))


def _extraction_value(case):
    facts = []
    for fact in case["facts"]:
        start = case["statement"].index(fact["quote"])
        facts.append({**fact, "start": start, "end": start + len(fact["quote"])})
    return {
        "schema": 1,
        "coverage": case["coverage"],
        "facts": facts,
        "alternative_groups": case["alternative_groups"],
    }


def test_synthetic_required_yoe_boundary_truth_table_uses_supported_jd_facts():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in cases:
        extraction = extraction_from_value(_extraction_value(case), case["statement"])
        result = evaluate_required_yoe(
            extraction,
            profile=candidate_profile(),
            threshold_years=2,
            policy_version="synthetic-yoe-v1",
            alternative_applicability=case["alternative_applicability"],
        )
        assert result.action == case["expected"], case["id"]
        assert result.policy_version == "synthetic-yoe-v1"
        if result.action == "exclude":
            assert result.evidence_fact_ids
            assert result.evidence_quotes
            assert all(quote in case["statement"] for quote in result.evidence_quotes)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(candidate_context="must not reach extractor"), "unknown field"),
        (lambda value: value.update(schema=True), "integer 1"),
        (lambda value: value.update(coverage="partial"), "coverage is invalid"),
        (lambda value: value["facts"][0].update(quote="not in source"), "does not match the JD"),
        (lambda value: value["facts"][0].update(minimum_years=True), "non-negative integer"),
        (lambda value: value["facts"][0].update(minimum_years=5, maximum_years=2), "reversed year range"),
        (lambda value: value["facts"][0].update(category="duty"), "outside an experience fact"),
        (lambda value: value["facts"][0].update(alternative_group_id="missing"), "membership is inconsistent"),
    ],
)
def test_extractor_rejects_unverified_spans_and_unallowlisted_fields(mutate, message):
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value = _extraction_value(cases[0])
    mutate(value)
    with pytest.raises(ExtractionValidationError, match=message):
        extraction_from_value(value, cases[0]["statement"])


def test_yoe_policy_keeps_unknown_alternatives_unresolved_and_never_calls_them_passes():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(row for row in cases if row["id"] == "lower-yoe-alternative")
    extraction = extraction_from_value(_extraction_value(case), case["statement"])

    unresolved = evaluate_required_yoe(
        extraction,
        profile=candidate_profile(),
        threshold_years=2,
        policy_version="synthetic-yoe-v1",
        alternative_applicability={},
    )
    assert unresolved.action == "unresolved"
    assert unresolved.reason == "lower_yoe_alternative_applicability_unknown"

    applicable = evaluate_required_yoe(
        extraction,
        profile=candidate_profile(),
        threshold_years=2,
        policy_version="synthetic-yoe-v1",
        alternative_applicability=case["alternative_applicability"],
    )
    assert applicable.action == "not_excluded"
    assert applicable.candidate_fact_ids == ("work-scope",)

    inapplicable = evaluate_required_yoe(
        extraction,
        profile=candidate_profile(),
        threshold_years=2,
        policy_version="synthetic-yoe-v1",
        alternative_applicability={
            "lower-path": {"status": "lower_yoe_path_inapplicable", "candidate_fact_ids": []}
        },
    )
    assert inapplicable.action == "exclude"
    assert inapplicable.evidence_fact_ids == ("fact-1",)

    with pytest.raises(YoePolicyError, match="outside the candidate background"):
        evaluate_required_yoe(
            extraction,
            profile=candidate_profile(),
            threshold_years=2,
            policy_version="synthetic-yoe-v1",
            alternative_applicability={
                "lower-path": {
                    "status": "lower_yoe_path_applicable",
                    "candidate_fact_ids": ["not-a-profile-fact"],
                }
            },
        )

    with pytest.raises(YoePolicyError, match="does not match"):
        evaluate_required_yoe(
            extraction,
            profile=candidate_profile(),
            threshold_years=2,
            policy_version="synthetic-yoe-v1",
            alternative_applicability={"stale-group": "lower_yoe_path_applicable"},
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold_years": 0, "policy_version": "v1", "alternative_applicability": {}},
        {"threshold_years": 2, "policy_version": " ", "alternative_applicability": {}},
        {"threshold_years": 2, "policy_version": "v1", "alternative_applicability": None},
    ],
)
def test_yoe_policy_requires_explicit_version_threshold_and_applicability(kwargs):
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    extraction = extraction_from_value(_extraction_value(cases[0]), cases[0]["statement"])
    with pytest.raises(YoePolicyError):
        evaluate_required_yoe(extraction, profile=candidate_profile(), **kwargs)


def test_alternative_group_cannot_overlap_and_requires_known_fact_members():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(row for row in cases if row["id"] == "lower-yoe-alternative")
    value = _extraction_value(case)
    value["alternative_groups"].append({"id": "second", "fact_ids": ["fact-1", "fact-2"]})
    with pytest.raises(ExtractionValidationError, match="multiple alternative groups"):
        extraction_from_value(value, case["statement"])

    value = _extraction_value(case)
    value["alternative_groups"][0]["fact_ids"][1] = "unknown-fact"
    with pytest.raises(ExtractionValidationError, match="unknown fact"):
        extraction_from_value(value, case["statement"])
