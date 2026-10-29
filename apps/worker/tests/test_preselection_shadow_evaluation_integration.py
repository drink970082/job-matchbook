from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from ats_worker.preselection.evaluation import build_evaluation_report, evaluation_from_value
from ats_worker.preselection.extraction import extraction_from_value
from ats_worker.preselection.profile import CandidateProfile, profile_from_value, render_profile
from ats_worker.preselection.questions import QuestionSet, question_set_from_value
from ats_worker.preselection.shadow import (
    AttemptJournal,
    Charge,
    CostCeiling,
    JobEnvelope,
    ModelIdentity,
    ProviderFailure,
    ProviderReply,
    RetryPolicy,
    ShadowIntegrityError,
    ShadowLimits,
    ShadowProviderFailure,
    ShadowResumeAmbiguous,
    SystemClock,
    Usage,
    build_assessment_invocation,
    build_extraction_invocation,
    run_shadow_assessment,
)


FIXTURES = Path(__file__).parent / "fixtures"
JD = "A fictional company needs an engineer with 2+ years professional experience."
ASSESSOR = ModelIdentity("fake-provider", "synthetic-assessor", "synthetic-assessor-r1")
EXTRACTOR = ModelIdentity("fake-provider", "synthetic-extractor", "synthetic-extractor-r1")
PRICE = Charge("actual", "0.07", "SYNTHETIC-CREDIT", "fake-call", "2026-10-29", "synthetic-fixture")
ANSWERS = {
    "role_families": ["engineering"],
    "work_alignment": "moderate",
    "dimension_example": 2,
}


def _hash(value: object) -> str:
    source = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(source.encode()).hexdigest()


def _profile() -> CandidateProfile:
    value = json.loads((FIXTURES / "preselection_profile.synthetic.json").read_text())
    value["status"] = "approved"
    return profile_from_value(value)


def _questions() -> QuestionSet:
    value = json.loads((FIXTURES / "preselection_questions.synthetic.json").read_text())
    return question_set_from_value(value)


def _limits() -> ShadowLimits:
    return ShadowLimits(
        max_total_attempts=8,
        max_attempts_per_request=2,
        max_elapsed_seconds=30.0,
        cost_ceiling=CostCeiling(
            "5.00", "1.00", "SYNTHETIC-CREDIT", "fake-call", "2026-10-29", "synthetic-fixture"
        ),
    )


def _binding_value(profile: CandidateProfile, questions: QuestionSet, limits: ShadowLimits) -> dict:
    retry_policy = RetryPolicy()
    limits_identity = _hash({"limits": asdict(limits), "retry_policy": asdict(retry_policy)})
    job = JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD)
    work_item = build_assessment_invocation(
        job, profile, questions, ASSESSOR, variant="direct", draw_number=1
    ).work_item_identity_sha256
    pool_id = "a" * 64
    occurrence = _hash({"pool_id_sha256": pool_id, "work_item_identity_sha256": work_item})
    item = {
        "work_item_identity_sha256": work_item,
        "pool_id_sha256": pool_id,
        "group_id": "synthetic-group-a",
        "split": "development",
        "draw_numbers": [1],
        "observed_at": "2026-10-28T11:00:00Z",
        "label": "positive",
        "label_source": "synthetic_fixture",
        "label_evidence_sha256": "b" * 64,
        "role_families": ["engineering"],
        "field_labels": dict(ANSWERS),
        "yoe_expected_action": None,
    }
    frozen_item = {
        **item,
        "pool_occurrence_identity_sha256": occurrence,
    }
    model_values = {
        "direct": asdict(ASSESSOR),
        "extract": asdict(EXTRACTOR),
        "extracted": asdict(ASSESSOR),
    }
    run = {
        "run_id": "synthetic-composition-run-v1",
        "protocol_version": "synthetic-protocol-v1",
        "phase": "development",
        "pool_fingerprint_sha256": _hash([frozen_item]),
        "split_algorithm": "utc-day-and-group-connected-components-v1",
        "split_seed": "synthetic-seed-v1",
        "profile_sha256": profile.identity_sha256,
        "question_set_sha256": questions.sha256,
        "label_guide_sha256": "c" * 64,
        "labeling_blinded": False,
        "split_manifest_sha256": _hash(
            {
                "split_algorithm": "utc-day-and-group-connected-components-v1",
                "split_seed": "synthetic-seed-v1",
                "occurrences": [
                    {
                        "pool_occurrence_identity_sha256": occurrence,
                        "pool_id_sha256": pool_id,
                        "group_id": item["group_id"],
                        "split": item["split"],
                    }
                ],
            }
        ),
        "selection_policy_version": "synthetic-ranking-v1",
        "attempt_limits_identity_sha256": limits_identity,
        "model_identities": model_values,
        "variants": ["direct", "extracted"],
        "draw_numbers": [1],
        "budgets": [1],
        "field_ids": list(ANSWERS),
    }
    return {
        "schema": 1,
        "run": run,
        "items": [item],
        "baseline_orders": [
            {"pool_id_sha256": pool_id, "recency": [occurrence], "role_coverage": [occurrence]}
        ],
        "assessments": [],
    }


def _extraction_payload(coverage: str) -> dict:
    quote = "2+ years professional experience"
    start = JD.index(quote)
    return {
        "schema": 1,
        "coverage": coverage,
        "facts": [
            {
                "id": "experience-floor",
                "quote": quote,
                "start": start,
                "end": start + len(quote),
                "category": "experience",
                "strength": "required",
                "experience_kind": "professional_relevant",
                "minimum_years": 2,
                "maximum_years": None,
                "alternative_group_id": None,
            }
        ],
        "alternative_groups": [],
    }


class FakeProvider:
    def __init__(self, profile: CandidateProfile, extraction_coverage: str, failure: ProviderFailure | None = None):
        self.profile = profile
        self.extraction_coverage = extraction_coverage
        self.failure = failure

    def complete(self, invocation):
        if invocation.stage == "extract_jd" and self.failure is not None:
            raise self.failure
        if invocation.stage == "extract_jd":
            payload = _extraction_payload(self.extraction_coverage)
        else:
            context = render_profile(self.profile)
            role_evidence = (
                [{"source": "fact", "fact_id": "experience-floor"}]
                if invocation.variant == "extracted"
                else [
                    {
                        "source": "jd",
                        "start": JD.index("engineer"),
                        "end": JD.index("engineer") + len("engineer"),
                        "quote": "engineer",
                    }
                ]
            )
            anchor = context.index("Interested")
            payload = {
                "answers": {
                    "role_families": {"value": ANSWERS["role_families"], "evidence": role_evidence},
                    "work_alignment": {
                        "value": ANSWERS["work_alignment"],
                        "evidence": [
                            {
                                "source": "candidate_context",
                                "start": anchor,
                                "end": anchor + len("Interested"),
                                "quote": "Interested",
                            }
                        ],
                    },
                    "dimension_example": {"value": 2, "evidence": []},
                },
                "explanation": "Synthetic answer from the offline composition fixture.",
            }
        return ProviderReply(invocation.model_identity, payload, Usage(12, 7, None), PRICE)


class MarkerFakeProvider(FakeProvider):
    def __init__(self, profile: CandidateProfile, marker_path: Path):
        super().__init__(profile, "complete")
        self.marker_path = marker_path

    def complete(self, invocation):
        self.marker_path.write_text(str(invocation.request_identity), encoding="utf-8")
        return super().complete(invocation)


def _assessment_outcome(value: dict, variant: str, request_identity: str, status: str = "completed") -> dict:
    item = value["items"][0]
    occurrence = _hash(
        {"pool_id_sha256": item["pool_id_sha256"], "work_item_identity_sha256": item["work_item_identity_sha256"]}
    )
    return {
        "work_item_identity_sha256": item["work_item_identity_sha256"],
        "pool_occurrence_identity_sha256": occurrence,
        "variant": variant,
        "draw_number": 1,
        "status": status,
        "request_stage": "assess",
        "request_identity_sha256": request_identity,
        "priority_rank": 1 if status == "completed" else None,
        "answers": ANSWERS if status == "completed" else {},
        "yoe_action": None if status == "completed" else "unresolved",
    }


def _extraction_outcome(value: dict, status: str, request_identity: str) -> dict:
    item = value["items"][0]
    occurrence = _hash(
        {"pool_id_sha256": item["pool_id_sha256"], "work_item_identity_sha256": item["work_item_identity_sha256"]}
    )
    return {
        "work_item_identity_sha256": item["work_item_identity_sha256"],
        "pool_occurrence_identity_sha256": occurrence,
        "variant": "extracted",
        "draw_number": 1,
        "status": status,
        "request_stage": "extract_jd",
        "request_identity_sha256": request_identity,
        "priority_rank": None,
        "answers": {},
        "yoe_action": "unresolved",
    }


def _run_call(profile, questions, provider, journal, limits, *, variant, run_binding, persist=None):
    return run_shadow_assessment(
        JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD),
        profile,
        questions,
        variant,
        ASSESSOR,
        provider,
        journal,
        limits,
        SystemClock(),
        persist or (lambda current: None),
        enabled=True,
        extraction_identity=EXTRACTOR if variant == "extracted" else None,
        run_binding=run_binding,
    )


def test_real_shadow_journal_composes_direct_and_incomplete_extraction_into_report():
    profile, questions, limits = _profile(), _questions(), _limits()
    value = _binding_value(profile, questions, limits)
    direct_request = build_assessment_invocation(
        JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD),
        profile,
        questions,
        ASSESSOR,
        variant="direct",
        draw_number=1,
    ).request_identity
    extraction_request = build_extraction_invocation(
        JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD), EXTRACTOR
    ).request_identity
    value["assessments"] = [
        _assessment_outcome(value, "direct", direct_request),
        _extraction_outcome(value, "unresolved", extraction_request),
    ]
    dataset = evaluation_from_value(value)
    journal = AttemptJournal.empty()
    snapshots: list[str] = []
    provider = FakeProvider(profile, "incomplete")

    direct = _run_call(
        profile,
        questions,
        provider,
        journal,
        limits,
        variant="direct",
        run_binding=dataset.run_binding,
        persist=lambda current: snapshots.append(current.to_json()),
    )
    extracted = _run_call(
        profile,
        questions,
        provider,
        journal,
        limits,
        variant="extracted",
        run_binding=dataset.run_binding,
        persist=lambda current: snapshots.append(current.to_json()),
    )
    journal = AttemptJournal.from_json(journal.to_json())
    report = build_evaluation_report(dataset, journal)

    assert direct.status == "completed"
    assert extracted.status == "unresolved_input"
    assert len(journal.records) == 2
    assert [record.stage for record in journal.records].count("assess") == 1
    assert [record.stage for record in journal.records].count("extract_jd") == 1
    assert all(record.run_binding_sha256 == dataset.run_binding.identity_sha256 for record in journal.records)
    pre_attempt = AttemptJournal.from_json(snapshots[0])
    assert pre_attempt.run_binding == dataset.run_binding
    assert pre_attempt.records == []
    assert report["splits"]["development"]["arms"]["extracted"]["draws"]["1"]["outcome_status_counts"] == {
        "completed": 0,
        "unresolved": 1,
        "failed": 0,
        "missing": 0,
    }
    assert report["attempt_accounting"]["run"]["attempts"] == 2
    assert report["attempt_accounting"]["extraction_coverage"]["failed_or_incomplete_extraction_attempts"] == 1


@pytest.mark.parametrize(
    ("delivery", "outcome_status", "exception_type"),
    [
        ("unknown", "unresolved", ShadowResumeAmbiguous),
        ("not_sent", "failed", ShadowProviderFailure),
    ],
)
def test_real_shadow_journal_preserves_failed_or_ambiguous_extraction_cost(
    delivery, outcome_status, exception_type
):
    profile, questions, limits = _profile(), _questions(), _limits()
    value = _binding_value(profile, questions, limits)
    job = JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD)
    extraction_request = build_extraction_invocation(job, EXTRACTOR).request_identity
    value["assessments"] = [_extraction_outcome(value, outcome_status, extraction_request)]
    dataset = evaluation_from_value(value)
    failure = ProviderFailure(
        error_code="synthetic_extraction_failure",
        retryable=False,
        delivery=delivery,
        model_identity=EXTRACTOR,
        usage=Usage(9, 2, None),
        charge=PRICE,
    )
    provider = FakeProvider(profile, "complete", failure)
    journal = AttemptJournal.empty()
    with pytest.raises(exception_type):
        _run_call(profile, questions, provider, journal, limits, variant="extracted", run_binding=dataset.run_binding)

    journal = AttemptJournal.from_json(journal.to_json())
    report = build_evaluation_report(dataset, journal)
    record = journal.records[0]
    assert record.stage == "extract_jd"
    assert record.status == ("ambiguous" if delivery == "unknown" else "failed")
    assert record.usage["input_tokens"] == 9
    assert record.charge["kind"] == "actual"
    assert record.charge["amount"] == "0.07"
    assert report["attempt_accounting"]["run"]["unknown_charge_attempts"] == 0
    assert report["attempt_accounting"]["run"]["reported_usage"]["input_tokens"]["reported_total"] == 9
    assert report["splits"]["development"]["arms"]["extracted"]["draws"]["1"]["outcome_status_counts"][outcome_status] == 1


def test_real_shadow_journal_composes_successful_extracted_arm():
    profile, questions, limits = _profile(), _questions(), _limits()
    value = _binding_value(profile, questions, limits)
    job = JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD)
    extraction = build_extraction_invocation(job, EXTRACTOR)
    frozen_extraction = extraction_from_value(_extraction_payload("complete"), JD)
    assess = build_assessment_invocation(
        job, profile, questions, ASSESSOR, variant="extracted", extraction=frozen_extraction, draw_number=1
    )
    value["assessments"] = [_assessment_outcome(value, "extracted", assess.request_identity)]
    dataset = evaluation_from_value(value)
    journal = AttemptJournal.empty()

    result = _run_call(
        profile,
        questions,
        FakeProvider(profile, "complete"),
        journal,
        limits,
        variant="extracted",
        run_binding=dataset.run_binding,
    )
    report = build_evaluation_report(dataset, AttemptJournal.from_json(journal.to_json()))

    assert result.status == "completed"
    assert result.request_identity == assess.request_identity
    assert [record.stage for record in journal.records] == ["extract_jd", "assess"]
    assert journal.records[0].request_identity == extraction.request_identity
    assert report["splits"]["development"]["arms"]["extracted"]["draws"]["1"]["outcome_status_counts"]["completed"] == 1


def test_real_shadow_rejects_profile_or_questions_that_differ_from_bound_run_before_transport():
    profile, questions, limits = _profile(), _questions(), _limits()
    value = _binding_value(profile, questions, limits)
    extraction_request = build_extraction_invocation(
        JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD), EXTRACTOR
    ).request_identity
    value["assessments"] = [_extraction_outcome(value, "unresolved", extraction_request)]
    binding = evaluation_from_value(value).run_binding

    changed_profile_value = json.loads((FIXTURES / "preselection_profile.synthetic.json").read_text())
    changed_profile_value["status"] = "approved"
    changed_profile_value["background"][0]["text"] = "A different synthetic background."
    changed_profile = profile_from_value(changed_profile_value)
    journal = AttemptJournal.empty()
    provider = FakeProvider(profile, "complete")

    with pytest.raises(ShadowIntegrityError, match="candidate profile differs"):
        _run_call(changed_profile, questions, provider, journal, limits, variant="extracted", run_binding=binding)
    assert journal.records == []

    changed_questions_value = json.loads((FIXTURES / "preselection_questions.synthetic.json").read_text())
    changed_questions_value["version"] = "synthetic-questions-v2"
    changed_questions = question_set_from_value(changed_questions_value)
    with pytest.raises(ShadowIntegrityError, match="question set differs"):
        _run_call(profile, changed_questions, provider, journal, limits, variant="extracted", run_binding=binding)
    assert journal.records == []


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("changed_input", ["profile", "questions"])
def test_bound_journal_rejects_changed_inputs_when_binding_argument_is_omitted(
    tmp_path, resume, changed_input
):
    profile, questions, limits = _profile(), _questions(), _limits()
    dataset = evaluation_from_value(_binding_value(profile, questions, limits))
    journal = AttemptJournal.empty()
    assert journal.bind_run(dataset.run_binding)

    if resume:
        _run_call(
            profile,
            questions,
            FakeProvider(profile, "complete"),
            journal,
            limits,
            variant="direct",
            run_binding=None,
        )
        journal = AttemptJournal.from_json(journal.to_json())

    if changed_input == "profile":
        profile_value = json.loads((FIXTURES / "preselection_profile.synthetic.json").read_text())
        profile_value["status"] = "approved"
        profile_value["background"][0]["text"] = "A different fabricated backend-engineering career."
        actual_profile = profile_from_value(profile_value)
        actual_questions = questions
        expected_message = "candidate profile differs"
    else:
        questions_value = json.loads((FIXTURES / "preselection_questions.synthetic.json").read_text())
        questions_value["version"] = "synthetic-questions-v2"
        actual_profile = profile
        actual_questions = question_set_from_value(questions_value)
        expected_message = "question set differs"

    before = journal.to_json()
    persisted: list[str] = []
    marker = tmp_path / f"provider-called-{resume}-{changed_input}"
    provider = MarkerFakeProvider(actual_profile, marker)
    with pytest.raises(ShadowIntegrityError, match=expected_message):
        run_shadow_assessment(
            JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD),
            actual_profile,
            actual_questions,
            "direct",
            ASSESSOR,
            provider,
            journal,
            limits,
            SystemClock(),
            lambda current: persisted.append(current.to_json()),
            enabled=True,
        )

    assert not marker.exists()
    assert persisted == []
    assert journal.to_json() == before


def test_bound_journal_can_reuse_success_on_resume_without_binding_argument(tmp_path):
    profile, questions, limits = _profile(), _questions(), _limits()
    dataset = evaluation_from_value(_binding_value(profile, questions, limits))
    journal = AttemptJournal.empty()
    journal.bind_run(dataset.run_binding)
    first = _run_call(
        profile,
        questions,
        FakeProvider(profile, "complete"),
        journal,
        limits,
        variant="direct",
        run_binding=None,
    )
    resumed_journal = AttemptJournal.from_json(journal.to_json())
    marker = tmp_path / "must-not-call-provider"
    provider = MarkerFakeProvider(profile, marker)

    resumed = run_shadow_assessment(
        JobEnvelope("Synthetic Co", "Junior Engineer", "Remote", JD),
        profile,
        questions,
        "direct",
        ASSESSOR,
        provider,
        resumed_journal,
        limits,
        SystemClock(),
        lambda current: None,
        enabled=True,
    )

    assert resumed.status == "completed"
    assert resumed.assessment_from_cache is True
    assert not marker.exists()
    assert len(resumed_journal.records) == 1
