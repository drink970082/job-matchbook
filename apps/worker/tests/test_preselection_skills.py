"""Synthetic source-span and native-answer tests for bounded skill evidence reports."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from ats_worker.preselection.jev import jev_question_set_from_value, native_jev_journal_payload
from ats_worker.preselection.profile import profile_from_value
from ats_worker.preselection.skills import (
    ProfileEvidenceRef,
    SkillEvidenceError,
    SkillEvidencePolicy,
    SkillRequirement,
    derive_skill_evidence,
)


MODEL = "typesafe/jev-1.13:synthetic-skills"
JD = "🌐 Duties include Java or C++; Kubernetes is preferred. Design distributed systems. Python is helpful."
QUESTION_VALUES = {"direct", "transferable", "not_evidenced", "unknown"}
QUESTION_IDS = ("mandatory_alt", "preferred_tool", "unclear_core", "supporting_python")
QUESTION_SET_VALUE = {
    "version": "synthetic-skill-sidecar-v1",
    "questions": [
        {
            "id": question_id,
            "type": "choice",
            "instructions": "Classify the synthetic evidence for this one requirement.",
            "criteria": {value: f"Synthetic {value} support." for value in QUESTION_VALUES},
        }
        for question_id in QUESTION_IDS
    ],
}
PROFILE_VALUE = {
    "schema": 1,
    "version": "synthetic-skills-profile-v1",
    "as_of": "2026-11-11",
    "status": "approved",
    "background": [
        {"id": "engineering-history", "text": "Built Java and Python systems; deployed Kubernetes."},
        {"id": "cpp-history", "text": "Built C++ tools for a synthetic project."},
    ],
    "preferences": [{"id": "work-preferences", "text": "Avoid on-call operations."}],
}


def _context(*, obligation_overrides=None, centrality_overrides=None, refs_override=None):
    question_set = jev_question_set_from_value(deepcopy(QUESTION_SET_VALUE))
    profile = profile_from_value(deepcopy(PROFILE_VALUE))
    default_refs = {
        "mandatory_alt": (ProfileEvidenceRef("engineering-history", "Built Java", 0, 10),),
        "preferred_tool": (),
        "unclear_core": (ProfileEvidenceRef("engineering-history", "Built Java", 0, 10),),
        "supporting_python": (ProfileEvidenceRef("engineering-history", "Python systems", 15, 29),),
    }
    if refs_override:
        default_refs.update(refs_override)
    obligations = {
        "mandatory_alt": "required",
        "preferred_tool": "preferred",
        "unclear_core": "unclear",
        "supporting_python": "required",
    }
    centralities = {
        "mandatory_alt": "central",
        "preferred_tool": "central",
        "unclear_core": "central",
        "supporting_python": "supporting",
    }
    obligations.update(obligation_overrides or {})
    centralities.update(centrality_overrides or {})
    quote_values = {
        "mandatory_alt": "Java or C++",
        "preferred_tool": "Kubernetes",
        "unclear_core": "Design distributed systems",
        "supporting_python": "Python",
    }
    requirements = tuple(
        SkillRequirement(
            question_id=question_id,
            quote=quote_values[question_id],
            start=JD.index(quote_values[question_id]),
            end=JD.index(quote_values[question_id]) + len(quote_values[question_id]),
            obligation=obligations[question_id],
            centrality=centralities[question_id],
            profile_evidence=default_refs[question_id],
        )
        for question_id in QUESTION_IDS
    )
    policy = SkillEvidencePolicy(
        version="synthetic-skill-policy-v1",
        question_set_sha256=question_set.sha256,
        profile_sha256=profile.identity_sha256,
        jd_sha256=hashlib.sha256(JD.encode("utf-8")).hexdigest(),
        requirements=requirements,
    )
    return question_set, profile, policy


def _payload(question_set, answers):
    raw_answers = {}
    for question in question_set.questions:
        selected = answers[question.id]
        criteria = dict(question.choice_criteria)
        raw_answers[question.id] = {
            "type": "choice",
            "choice": selected,
            "probabilities": {value: (1.0 if value == selected else 0.0) for value in criteria},
            "confidence": 1.0,
        }
    response = {
        "id": "synthetic-skill-response",
        "model": MODEL,
        "answers": raw_answers,
        "usage": {"input_tokens": 100, "output_tokens": 50, "cost": 0.0002},
    }
    return native_jev_journal_payload(question_set, response)


def _answers(**overrides):
    values = {
        "mandatory_alt": "direct",
        "preferred_tool": "not_evidenced",
        "unclear_core": "direct",
        "supporting_python": "not_evidenced",
    }
    values.update(overrides)
    return values


def _derive(answers=None, *, context=None, native_payload=None, jd_text=JD, profile=None):
    question_set, frozen_profile, policy = context or _context()
    return derive_skill_evidence(
        native_payload if native_payload is not None else _payload(question_set, answers or _answers()),
        question_set,
        MODEL,
        jd_text,
        profile if profile is not None else frozen_profile,
        policy,
    )


def test_report_keeps_one_alternative_clause_atomic_and_provenance_selected_only():
    report = _derive()
    first = report.requirements[0]
    assert report.selected_requirement_ids == QUESTION_IDS
    assert first.quote == "Java or C++"
    assert first.start == JD.index("Java or C++")
    assert first.end - first.start == len(first.quote)
    assert first.profile_evidence[0] == ProfileEvidenceRef("engineering-history", "Built Java", 0, 10)
    assert report.coverage == "selected_requirements_only"
    assert report.provenance == "operator_proxy_not_gold"
    assert report.summary == "unresolved"
    assert report.unresolved_requirement_ids == ("unclear_core",)
    assert report.explicit_core_requirement_ids == ("mandatory_alt",)


@pytest.mark.parametrize("support", ["transferable", "not_evidenced"])
def test_only_required_central_non_direct_support_creates_unverified_core(support):
    report = _derive(_answers(mandatory_alt=support))
    assert report.summary == "core_requirement_unverified"
    assert report.unverified_core_requirement_ids == ("mandatory_alt",)
    assert report.unresolved_requirement_ids == ("unclear_core",)


def test_known_core_gap_does_not_hide_unresolved_requirement_ids():
    report = _derive(_answers(mandatory_alt="not_evidenced", unclear_core="unknown"))
    assert report.summary == "core_requirement_unverified"
    assert report.unverified_core_requirement_ids == ("mandatory_alt",)
    assert report.unresolved_requirement_ids == ("unclear_core",)


def test_unknown_core_support_is_unresolved_and_not_a_gap():
    context = _context(centrality_overrides={"unclear_core": "supporting"})
    report = _derive(_answers(mandatory_alt="unknown"), context=context)
    assert report.summary == "unresolved"
    assert report.unverified_core_requirement_ids == ()
    assert report.unresolved_requirement_ids == ("mandatory_alt",)


def test_unclear_obligation_or_centrality_is_unresolved_not_a_gap():
    context = _context(
        obligation_overrides={"unclear_core": "required"},
        centrality_overrides={"unclear_core": "unclear"},
    )
    report = _derive(
        _answers(unclear_core="not_evidenced"),
        context=context,
    )
    assert report.summary == "unresolved"
    assert report.unverified_core_requirement_ids == ()
    assert report.unresolved_requirement_ids == ("unclear_core",)


def test_core_supported_requires_explicit_core_and_no_possible_core_unknown():
    context = _context(
        obligation_overrides={"unclear_core": "preferred"},
        centrality_overrides={"supporting_python": "supporting"},
    )
    report = _derive(_answers(), context=context)
    assert report.summary == "core_evidence_supported"
    assert report.explicit_core_requirement_ids == ("mandatory_alt",)
    assert report.unresolved_requirement_ids == ()


def test_preferred_and_supporting_non_direct_answers_do_not_make_core_gaps():
    context = _context(
        obligation_overrides={"mandatory_alt": "preferred", "unclear_core": "preferred"},
        centrality_overrides={"supporting_python": "supporting"},
    )
    report = _derive(
        _answers(mandatory_alt="not_evidenced", unclear_core="transferable"),
        context=context,
    )
    assert report.summary == "no_explicit_core_requirement"
    assert report.explicit_core_requirement_ids == ()
    assert report.unverified_core_requirement_ids == ()


def test_unknown_preferred_and_supporting_facts_remain_visible_without_changing_summary():
    context = _context(
        obligation_overrides={"unclear_core": "preferred"},
        centrality_overrides={"supporting_python": "supporting"},
    )
    report = _derive(
        _answers(preferred_tool="unknown", unclear_core="unknown", supporting_python="unknown"),
        context=context,
    )
    assert report.summary == "core_evidence_supported"
    assert report.unresolved_requirement_ids == (
        "preferred_tool",
        "unclear_core",
        "supporting_python",
    )
    assert report.requirements[1].core_status == "not_core_requirement"
    assert report.requirements[3].core_status == "not_core_requirement"


def test_supporting_required_fact_does_not_create_core_gap():
    context = _context(centrality_overrides={"mandatory_alt": "supporting", "unclear_core": "supporting"})
    report = _derive(_answers(mandatory_alt="not_evidenced"), context=context)
    assert report.summary == "no_explicit_core_requirement"
    assert report.unverified_core_requirement_ids == ()


def test_no_explicit_core_is_not_reported_as_a_confirmed_pass():
    context = _context(
        obligation_overrides={"mandatory_alt": "preferred", "unclear_core": "preferred"},
        centrality_overrides={"supporting_python": "supporting"},
    )
    report = _derive(context=context)
    assert report.summary == "no_explicit_core_requirement"
    assert report.summary != "core_evidence_supported"


def test_positive_answer_without_profile_trace_is_unresolved_not_all_clear():
    context = _context(
        obligation_overrides={"unclear_core": "preferred"},
        centrality_overrides={"supporting_python": "supporting"},
        refs_override={
            "mandatory_alt": (),
            "preferred_tool": (),
            "unclear_core": (ProfileEvidenceRef("engineering-history", "Built Java", 0, 10),),
            "supporting_python": (),
        },
    )
    report = _derive(
        _answers(
            mandatory_alt="direct",
            preferred_tool="transferable",
            unclear_core="not_evidenced",
            supporting_python="not_evidenced",
        ),
        context=context,
    )
    assert report.summary == "unresolved"
    assert report.requirements[0].support == "direct"
    assert report.requirements[0].core_status == "unresolved"
    assert report.requirements[1].support == "transferable"
    assert report.requirements[1].core_status == "unresolved"
    assert report.unresolved_requirement_ids == ("mandatory_alt", "preferred_tool")


def test_not_evidenced_without_profile_trace_remains_a_gap_not_inability():
    context = _context(refs_override={"mandatory_alt": ()})
    report = _derive(_answers(mandatory_alt="not_evidenced"), context=context)
    assert report.summary == "core_requirement_unverified"
    assert report.requirements[0].support == "not_evidenced"
    assert report.requirements[0].core_status == "core_requirement_unverified"


def test_same_profile_source_reference_can_support_separate_requirements():
    shared_ref = ProfileEvidenceRef("engineering-history", "Python systems", 15, 29)
    question_set, profile, policy = _context(
        refs_override={"mandatory_alt": (shared_ref,), "supporting_python": (shared_ref,)}
    )
    report = derive_skill_evidence(
        _payload(question_set, _answers()), question_set, MODEL, JD, profile, policy
    )
    assert report.requirements[0].profile_evidence == (shared_ref,)
    assert report.requirements[3].profile_evidence == (shared_ref,)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda policy: replace(policy, jd_sha256="0" * 64),
        lambda policy: replace(policy, profile_sha256="0" * 64),
        lambda policy: replace(policy, question_set_sha256="0" * 64),
        lambda policy: replace(policy, requirements=policy.requirements[:-1]),
        lambda policy: replace(policy, requirements=(policy.requirements[0],) * 2),
        lambda policy: replace(
            policy,
            requirements=(replace(policy.requirements[0], quote="not source text"),) + policy.requirements[1:],
        ),
        lambda policy: replace(
            policy,
            requirements=(replace(policy.requirements[0], start=True),) + policy.requirements[1:],
        ),
        lambda policy: replace(
            policy,
            requirements=(replace(policy.requirements[0], obligation="maybe"),) + policy.requirements[1:],
        ),
        lambda policy: replace(policy, version="bad\nversion"),
        lambda policy: replace(
            policy,
            requirements=(replace(policy.requirements[0], question_id="bad\nid"),) + policy.requirements[1:],
        ),
    ],
)
def test_policy_rejects_changed_hashes_extra_missing_or_invalid_facts(mutate):
    question_set, profile, policy = _context()
    altered = mutate(policy)
    with pytest.raises(SkillEvidenceError):
        derive_skill_evidence(_payload(question_set, _answers()), question_set, MODEL, JD, profile, altered)


def test_report_rejects_changed_jd_profile_model_questions_and_native_answers():
    question_set, profile, policy = _context()
    payload = _payload(question_set, _answers())
    with pytest.raises(SkillEvidenceError, match="job description differs"):
        derive_skill_evidence(payload, question_set, MODEL, JD + " Additional text.", profile, policy)
    altered_profile = profile_from_value({
        **PROFILE_VALUE,
        "background": [{"id": "engineering-history", "text": "Changed synthetic background."}],
    })
    with pytest.raises(SkillEvidenceError, match="candidate profile differs"):
        derive_skill_evidence(payload, question_set, MODEL, JD, altered_profile, policy)
    with pytest.raises(SkillEvidenceError, match="native JEV response"):
        derive_skill_evidence(payload, question_set, "another-model", JD, profile, policy)
    incomplete = deepcopy(payload["response"])
    incomplete["answers"].pop("mandatory_alt")
    incomplete_payload = native_jev_journal_payload(question_set, incomplete)
    with pytest.raises(SkillEvidenceError, match="native JEV response"):
        derive_skill_evidence(incomplete_payload, question_set, MODEL, JD, profile, policy)


@pytest.mark.parametrize(
    "bad_reference",
    [
        ProfileEvidenceRef("work-preferences", "Avoid on-call", 0, 15),
        ProfileEvidenceRef("engineering-history", "not in source", 0, 14),
        ProfileEvidenceRef("missing-block", "Built Java", 0, 10),
        ProfileEvidenceRef("engineering-history", "Built Java", True, 10),
    ],
)
def test_profile_references_must_be_exact_and_background_only(bad_reference):
    question_set, profile, policy = _context(refs_override={"mandatory_alt": (bad_reference,)})
    with pytest.raises(SkillEvidenceError):
        derive_skill_evidence(_payload(question_set, _answers()), question_set, MODEL, JD, profile, policy)


def test_duplicate_profile_references_and_question_mismatches_are_rejected():
    question_set, profile, policy = _context(
        refs_override={"mandatory_alt": (
            ProfileEvidenceRef("engineering-history", "Built Java", 0, 10),
            ProfileEvidenceRef("engineering-history", "Built Java", 0, 10),
        )}
    )
    with pytest.raises(SkillEvidenceError, match="duplicate profile"):
        derive_skill_evidence(_payload(question_set, _answers()), question_set, MODEL, JD, profile, policy)

    other_questions = jev_question_set_from_value({"version": "other", "questions": QUESTION_SET_VALUE["questions"]})
    with pytest.raises(SkillEvidenceError, match="question-set hash"):
        derive_skill_evidence(_payload(question_set, _answers()), other_questions, MODEL, JD, profile, policy)


def test_raw_native_wrapper_is_unchanged_and_report_carries_all_frozen_identities():
    question_set, profile, policy = _context()
    payload = _payload(question_set, _answers())
    original = deepcopy(payload)
    report = derive_skill_evidence(payload, question_set, MODEL, JD, profile, policy)
    assert payload == original
    assert report.policy_sha256 == policy.sha256
    assert report.question_set_sha256 == question_set.sha256
    assert report.profile_sha256 == profile.identity_sha256
    assert report.jd_sha256 == policy.jd_sha256
    assert report.response_sha256 == payload["response_sha256"]
    assert report.referenced_profile_block_ids == ("engineering-history",)


def test_empty_profile_references_are_permitted_without_completeness_claim():
    question_set, profile, policy = _context(refs_override={
        "mandatory_alt": (),
        "preferred_tool": (),
        "unclear_core": (),
        "supporting_python": (),
    })
    report = derive_skill_evidence(_payload(question_set, _answers()), question_set, MODEL, JD, profile, policy)
    assert report.summary == "unresolved"
    assert report.requirements[0].profile_evidence == ()
    assert report.referenced_profile_block_ids == ()
    assert report.coverage == "selected_requirements_only"
    assert report.provenance == "operator_proxy_not_gold"
    assert report.explicit_core_requirement_ids == ("mandatory_alt",)
    assert "mandatory_alt" in report.unresolved_requirement_ids
