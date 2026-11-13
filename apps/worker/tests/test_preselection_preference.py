"""Truth-table tests for profile-neutral JEV preference arbitration."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ats_worker.preselection.jev import jev_question_set_from_value, native_jev_journal_payload
from ats_worker.preselection.preference import (
    PreferenceError,
    PreferencePolicy,
    PreferenceTier,
    derive_preference,
)


QUESTIONS = {
    "version": "synthetic-preference-v4",
    "questions": [
        {"id": "duty_avoidance", "type": "choice", "instructions": "Synthetic duty avoidance.",
         "criteria": {"present": "Present.", "absent": "Absent.", "unclear": "Unclear."}},
        {"id": "quant_swe", "type": "choice", "instructions": "Synthetic role-family support.",
         "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."}},
        {"id": "python_quant", "type": "choice", "instructions": "Synthetic role-family support.",
         "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."}},
        {"id": "general_swe", "type": "choice", "instructions": "Synthetic role-family support.",
         "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."}},
        {"id": "engineering_primary", "type": "choice", "instructions": "Synthetic engineering duties.",
         "criteria": {"yes": "Yes.", "no": "No.", "unknown": "Unknown."}},
    ],
}
MODEL = "typesafe/jev-1.13:synthetic-canonical"


def _questions():
    return jev_question_set_from_value(QUESTIONS)


def _policy(question_set=None, **overrides):
    question_set = question_set or _questions()
    value = {
        "version": "preference-policy-synthetic-v1",
        "question_set_sha256": question_set.sha256,
        "first_target_role_ids": ("quant_swe", "python_quant"),
        "secondary_role_ids": ("general_swe",),
        "supported_value": "supported",
        "not_supported_value": "not_supported",
        "unknown_value": "unknown",
        "avoidance_question_id": "duty_avoidance",
        "avoidance_present_value": "present",
        "avoidance_absent_value": "absent",
        "avoidance_unclear_value": "unclear",
        "engineering_question_id": "engineering_primary",
        "engineering_yes_value": "yes",
        "engineering_no_value": "no",
        "engineering_unknown_value": "unknown",
    }
    value.update(overrides)
    return PreferencePolicy(**value)


def _payload(question_set, *, avoidance="absent", quant="not_supported", python="not_supported",
             general="not_supported", engineering="yes"):
    answers = {
        "duty_avoidance": avoidance,
        "quant_swe": quant,
        "python_quant": python,
        "general_swe": general,
        "engineering_primary": engineering,
    }
    raw_answers = {}
    for question in question_set.questions:
        value = answers[question.id]
        criteria = dict(question.choice_criteria)
        raw_answers[question.id] = {
            "type": "choice",
            "choice": value,
            "probabilities": {key: 1.0 if key == value else 0.0 for key in criteria},
            "confidence": 1.0,
        }
    response = {
        "id": "synthetic-native-response",
        "model": MODEL,
        "answers": raw_answers,
        "usage": {"input_tokens": 30, "output_tokens": 12, "cost": 0.0002},
    }
    return native_jev_journal_payload(question_set, response)


@pytest.mark.parametrize(
    ("answers", "expected_tier", "expected_reason"),
    [
        ({"avoidance": "present", "quant": "supported"}, PreferenceTier.AVOIDED,
         "primary-duty-avoidance-present"),
        ({"avoidance": "unclear", "quant": "supported"}, PreferenceTier.UNRESOLVED,
         "primary-duty-avoidance-unclear"),
        ({"quant": "supported"}, PreferenceTier.PRIMARY, "first-target-family-supported"),
        ({"quant": "unknown", "general": "supported"}, PreferenceTier.UNRESOLVED,
         "first-target-family-unknown"),
        ({"general": "supported"}, PreferenceTier.SECONDARY, "secondary-family-supported"),
        ({}, PreferenceTier.ADJACENT, "all-target-families-ruled-out"),
        ({"engineering": "no", "quant": "supported"}, PreferenceTier.UNRESOLVED,
         "engineering-primary-not-confirmed"),
        ({"engineering": "unknown", "general": "supported"}, PreferenceTier.UNRESOLVED,
         "engineering-primary-not-confirmed"),
        ({"general": "unknown"}, PreferenceTier.UNRESOLVED, "secondary-family-unknown"),
    ],
)
def test_derive_preference_truth_table(answers, expected_tier, expected_reason):
    question_set = _questions()
    policy = _policy(question_set)
    values = {
        "avoidance": "absent",
        "quant": "not_supported",
        "python": "not_supported",
        "general": "not_supported",
        "engineering": "yes",
    }
    values.update(answers)
    payload = _payload(
        question_set,
        avoidance=values["avoidance"],
        quant=values["quant"],
        python=values["python"],
        general=values["general"],
        engineering=values["engineering"],
    )
    original = deepcopy(payload)

    decision = derive_preference(payload, question_set, MODEL, policy)

    assert decision.tier is expected_tier
    assert decision.reason == expected_reason
    assert decision.policy_sha256 == policy.sha256
    assert decision.question_set_sha256 == question_set.sha256
    assert decision.source_question_ids
    assert payload == original
    assert "preference_question_id" not in policy.__dict__


def test_any_first_target_support_precedes_secondary_and_policy_order_is_not_a_weight():
    question_set = _questions()
    policy = _policy(question_set)
    result = derive_preference(
        _payload(question_set, quant="supported", python="supported", general="supported"),
        question_set,
        MODEL,
        policy,
    )
    reversed_policy = _policy(question_set, first_target_role_ids=("python_quant", "quant_swe"))
    reversed_result = derive_preference(
        _payload(question_set, quant="supported", python="supported", general="supported"),
        question_set,
        MODEL,
        reversed_policy,
    )
    assert result.tier is reversed_result.tier is PreferenceTier.PRIMARY
    assert result.policy_sha256 != reversed_result.policy_sha256
    assert result.source_question_ids[-2:] == ("quant_swe", "python_quant")
    assert reversed_result.source_question_ids[-2:] == ("python_quant", "quant_swe")


@pytest.mark.parametrize(
    "overrides",
    [
        {"first_target_role_ids": ()},
        {"secondary_role_ids": ()},
        {"first_target_role_ids": ("quant_swe", "general_swe")},
        {"secondary_role_ids": ("quant_swe",)},
        {"avoidance_question_id": "missing"},
        {"engineering_yes_value": "missing"},
    ],
)
def test_preference_policy_rejects_invalid_question_mappings(overrides):
    question_set = _questions()
    with pytest.raises(PreferenceError):
        _policy(question_set, **overrides).validate(question_set)


def test_preference_requires_matching_model_question_set_and_native_response():
    question_set = _questions()
    policy = _policy(question_set)
    payload = _payload(question_set)
    with pytest.raises(PreferenceError, match="native JEV evidence"):
        derive_preference(payload, question_set, "another-model", policy)
    other_questions = jev_question_set_from_value({
        "version": "other", "questions": QUESTIONS["questions"]
    })
    with pytest.raises(PreferenceError, match="different question set"):
        derive_preference(payload, other_questions, MODEL, policy)

    malformed = deepcopy(payload)
    malformed["response"]["answers"].pop("quant_swe")
    malformed = native_jev_journal_payload(question_set, malformed["response"])
    with pytest.raises(PreferenceError, match="native JEV evidence"):
        derive_preference(malformed, question_set, MODEL, policy)
