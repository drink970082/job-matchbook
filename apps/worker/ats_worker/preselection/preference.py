"""Versioned, profile-neutral arbitration over native JEV answers.

The policy names the role-family question IDs and Choice values; this module contains no
candidate priorities, numeric weights, eligibility rules, or runtime selection hooks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

from ats_worker.preselection.jev import (
    JevContractError,
    NativeJevQuestionSet,
    jev_question_set_from_value,
    validate_native_jev_journal_payload,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PreferenceError(ValueError):
    """A preference policy or native evidence violates the frozen contract."""


class PreferenceTier(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    ADJACENT = "adjacent"
    AVOIDED = "avoided"
    UNRESOLVED = "unresolved"


def _text(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > 128
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise PreferenceError(f"{path} must be bounded, non-empty trimmed text")
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise PreferenceError("policy cannot be canonically encoded") from exc


@dataclass(frozen=True)
class PreferencePolicy:
    """Explicit question/value mapping for one frozen native JEV question set."""

    version: str
    question_set_sha256: str
    first_target_role_ids: tuple[str, ...]
    secondary_role_ids: tuple[str, ...]
    supported_value: str
    not_supported_value: str
    unknown_value: str
    avoidance_question_id: str
    avoidance_present_value: str
    avoidance_absent_value: str
    avoidance_unclear_value: str
    engineering_question_id: str
    engineering_yes_value: str
    engineering_no_value: str
    engineering_unknown_value: str

    def validate(self, question_set: NativeJevQuestionSet) -> None:
        if not isinstance(question_set, NativeJevQuestionSet):
            raise PreferenceError("preference policy requires a validated native JEV question set")
        try:
            canonical_questions = jev_question_set_from_value(question_set.as_dict())
        except (AttributeError, JevContractError):
            raise PreferenceError("preference policy question set is malformed") from None
        if canonical_questions.sha256 != question_set.sha256:
            raise PreferenceError("preference policy question set is not canonical")
        _text(self.version, "policy version")
        if not isinstance(self.question_set_sha256, str) or _SHA256.fullmatch(self.question_set_sha256) is None:
            raise PreferenceError("policy question-set identity must be a lowercase SHA-256 digest")
        if self.question_set_sha256 != question_set.sha256:
            raise PreferenceError("policy is bound to a different question set")
        if not isinstance(self.first_target_role_ids, tuple) or not self.first_target_role_ids:
            raise PreferenceError("first-target role IDs must be a non-empty tuple")
        if not isinstance(self.secondary_role_ids, tuple) or not self.secondary_role_ids:
            raise PreferenceError("secondary role IDs must be a non-empty tuple")
        all_question_ids = (
            self.first_target_role_ids
            + self.secondary_role_ids
            + (self.avoidance_question_id, self.engineering_question_id)
        )
        if any(not isinstance(question_id, str) for question_id in all_question_ids):
            raise PreferenceError("policy question IDs must be text")
        for question_id in all_question_ids:
            _text(question_id, "policy question ID")
        if len(set(self.first_target_role_ids)) != len(self.first_target_role_ids):
            raise PreferenceError("first-target role IDs must be unique")
        if len(set(self.secondary_role_ids)) != len(self.secondary_role_ids):
            raise PreferenceError("secondary role IDs must be unique")
        if set(self.first_target_role_ids) & set(self.secondary_role_ids):
            raise PreferenceError("first-target and secondary role IDs must not overlap")
        if len(set(all_question_ids)) != len(all_question_ids):
            raise PreferenceError("role, avoidance and engineering question IDs must be distinct")

        for field in (
            self.supported_value,
            self.not_supported_value,
            self.unknown_value,
            self.avoidance_present_value,
            self.avoidance_absent_value,
            self.avoidance_unclear_value,
            self.engineering_yes_value,
            self.engineering_no_value,
            self.engineering_unknown_value,
        ):
            _text(field, "policy Choice value")
        role_values = (self.supported_value, self.not_supported_value, self.unknown_value)
        avoidance_values = (
            self.avoidance_present_value,
            self.avoidance_absent_value,
            self.avoidance_unclear_value,
        )
        engineering_values = (
            self.engineering_yes_value,
            self.engineering_no_value,
            self.engineering_unknown_value,
        )
        if len(set(role_values)) != 3 or len(set(avoidance_values)) != 3 or len(set(engineering_values)) != 3:
            raise PreferenceError("policy values within each Choice field must be distinct")

        by_id = {question.id: question for question in question_set.questions}
        role_ids = self.first_target_role_ids + self.secondary_role_ids
        for question_id in role_ids:
            question = by_id.get(question_id)
            if question is None or question.question_type != "choice":
                raise PreferenceError("role policy IDs must name frozen Choice questions")
            if set(dict(question.choice_criteria)) != set(role_values):
                raise PreferenceError("role question criteria do not exactly match policy values")
        for question_id, expected_values, label in (
            (self.avoidance_question_id, avoidance_values, "avoidance"),
            (self.engineering_question_id, engineering_values, "engineering"),
        ):
            question = by_id.get(question_id)
            if question is None or question.question_type != "choice":
                raise PreferenceError(f"{label} policy ID must name a frozen Choice question")
            if set(dict(question.choice_criteria)) != set(expected_values):
                raise PreferenceError(f"{label} question criteria do not exactly match policy values")

    @property
    def sha256(self) -> str:
        value = {
            "domain": "ats-preselection-preference-policy-v1",
            "policy": asdict(self),
        }
        return hashlib.sha256(_canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class PreferenceDecision:
    tier: PreferenceTier
    reason: str
    policy_sha256: str
    question_set_sha256: str
    response_sha256: str
    source_question_ids: tuple[str, ...]


def derive_preference(
    native_payload: Any,
    question_set: NativeJevQuestionSet,
    expected_model: str,
    policy: PreferencePolicy,
) -> PreferenceDecision:
    """Validate a native wrapper, then derive a separate tier without changing answers."""
    policy.validate(question_set)
    _text(expected_model, "expected resolved model")
    try:
        assessment = validate_native_jev_journal_payload(
            native_payload,
            expected_question_set=question_set,
            expected_question_set_sha256=policy.question_set_sha256,
            expected_model=expected_model,
        )
    except JevContractError:
        raise PreferenceError("native JEV evidence does not match the frozen policy contract") from None

    answer_map = {answer.question_id: answer.choice for answer in assessment.answers}
    preference = answer_map[policy.avoidance_question_id]
    engineering = answer_map[policy.engineering_question_id]
    first_values = {question_id: answer_map[question_id] for question_id in policy.first_target_role_ids}
    secondary_values = {question_id: answer_map[question_id] for question_id in policy.secondary_role_ids}

    if preference == policy.avoidance_present_value:
        tier, reason = PreferenceTier.AVOIDED, "primary-duty-avoidance-present"
        used = (policy.avoidance_question_id,)
    elif preference == policy.avoidance_unclear_value:
        tier, reason = PreferenceTier.UNRESOLVED, "primary-duty-avoidance-unclear"
        used = (policy.avoidance_question_id,)
    elif engineering != policy.engineering_yes_value:
        tier, reason = PreferenceTier.UNRESOLVED, "engineering-primary-not-confirmed"
        used = (policy.avoidance_question_id, policy.engineering_question_id)
    else:
        first_supported = tuple(
            question_id for question_id, value in first_values.items()
            if value == policy.supported_value
        )
        first_unknown = tuple(
            question_id for question_id, value in first_values.items()
            if value == policy.unknown_value
        )
        if first_supported:
            tier, reason = PreferenceTier.PRIMARY, "first-target-family-supported"
            used = (policy.avoidance_question_id, policy.engineering_question_id) + first_supported
        elif first_unknown:
            tier, reason = PreferenceTier.UNRESOLVED, "first-target-family-unknown"
            used = (policy.avoidance_question_id, policy.engineering_question_id) + policy.first_target_role_ids
        else:
            secondary_supported = tuple(
                question_id for question_id, value in secondary_values.items()
                if value == policy.supported_value
            )
            secondary_unknown = tuple(
                question_id for question_id, value in secondary_values.items()
                if value == policy.unknown_value
            )
            if secondary_supported:
                tier, reason = PreferenceTier.SECONDARY, "secondary-family-supported"
                used = (
                    (policy.avoidance_question_id, policy.engineering_question_id)
                    + policy.first_target_role_ids
                    + secondary_supported
                )
            elif secondary_unknown:
                tier, reason = PreferenceTier.UNRESOLVED, "secondary-family-unknown"
                used = (
                    (policy.avoidance_question_id, policy.engineering_question_id)
                    + policy.first_target_role_ids
                    + policy.secondary_role_ids
                )
            else:
                tier, reason = PreferenceTier.ADJACENT, "all-target-families-ruled-out"
                used = (
                    (policy.avoidance_question_id, policy.engineering_question_id)
                    + policy.first_target_role_ids
                    + policy.secondary_role_ids
                )

    response_sha256 = native_payload.get("response_sha256") if isinstance(native_payload, dict) else None
    if not isinstance(response_sha256, str) or _SHA256.fullmatch(response_sha256) is None:
        raise PreferenceError("validated native response hash is unavailable")
    return PreferenceDecision(
        tier=tier,
        reason=reason,
        policy_sha256=policy.sha256,
        question_set_sha256=question_set.sha256,
        response_sha256=response_sha256,
        source_question_ids=tuple(dict.fromkeys(used)),
    )
