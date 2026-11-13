"""Pure provenance-bound disagreement guard for native JEV preference signals."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from ats_worker.preselection.jev import (
    JevContractError,
    NativeJevQuestionSet,
    jev_question_set_from_value,
    validate_native_jev_journal_payload,
)
from ats_worker.preselection.preference import (
    PreferenceDecision,
    PreferenceError,
    PreferencePolicy,
    PreferenceTier,
    derive_preference,
)
if TYPE_CHECKING:
    from ats_worker.preselection.shadow import AttemptRecord, ModelIdentity, RunBinding


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_QUESTION_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
GUARD_VERSION = "native-preference-disagreement-guard-v1"


class PreferenceGuardError(ValueError):
    """A JEV pair is incomplete, unbound, malformed or inconsistent."""


class GuardAvoidance(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AtomicAvoidanceContract:
    """Caller-declared versioned identity for the exact atomic Choice vector."""

    version: str
    question_ids: tuple[str, ...]
    question_set_sha256: str
    present_value: str = "present"
    absent_value: str = "absent"
    unknown_value: str = "unknown"

    def validate(self, question_set: NativeJevQuestionSet) -> None:
        if (
            not isinstance(self.version, str)
            or not self.version
            or self.version.strip() != self.version
            or len(self.version) > 128
        ):
            raise PreferenceGuardError("atomic contract version must be bounded trimmed text")
        if (
            not isinstance(self.question_ids, tuple)
            or len(self.question_ids) != 7
            or any(
                not isinstance(question_id, str) or _QUESTION_ID.fullmatch(question_id) is None
                for question_id in self.question_ids
            )
            or len(set(self.question_ids)) != 7
        ):
            raise PreferenceGuardError("atomic contract must declare seven unique Choice IDs")
        if not isinstance(self.question_set_sha256, str) or _SHA256.fullmatch(self.question_set_sha256) is None:
            raise PreferenceGuardError("atomic contract question-set identity must be a SHA-256 digest")
        if (self.present_value, self.absent_value, self.unknown_value) != (
            "present",
            "absent",
            "unknown",
        ):
            raise PreferenceGuardError("atomic contract values must be present, absent and unknown")
        if self.question_ids != tuple(question.id for question in question_set.questions):
            raise PreferenceGuardError("atomic question IDs differ from the declared contract")
        if self.question_set_sha256 != question_set.sha256:
            raise PreferenceGuardError("atomic question set differs from the declared contract identity")
        expected_values = {self.present_value, self.absent_value, self.unknown_value}
        for question in question_set.questions:
            if question.question_type != "choice" or set(dict(question.choice_criteria)) != expected_values:
                raise PreferenceGuardError("atomic questions must use the complete present/absent/unknown Choice set")


@dataclass(frozen=True)
class PreferenceGuardResult:
    """Advisory result with the two validated native records and their provenance."""

    base_decision: PreferenceDecision
    tier: PreferenceTier
    reason: str
    review_required: bool
    material_disagreement: bool
    compound_avoidance: GuardAvoidance
    atomic_avoidance: GuardAvoidance
    source_work_item_identity_sha256: str
    draw_number: int
    model_identity: ModelIdentity
    guard_version: str
    policy_sha256: str
    atomic_contract_version: str
    native_run_binding: RunBinding
    native_run_binding_sha256: str
    native_question_set_sha256: str
    native_response_sha256: str
    native_response_payload: dict[str, Any]
    atomic_run_binding: RunBinding
    atomic_run_binding_sha256: str
    atomic_question_set_sha256: str
    atomic_response_sha256: str
    atomic_response_payload: dict[str, Any]


def _validated_questions(value: Any, label: str) -> NativeJevQuestionSet:
    if not isinstance(value, NativeJevQuestionSet):
        raise PreferenceGuardError(f"{label} question set must be validated")
    try:
        canonical = jev_question_set_from_value(value.as_dict())
    except (AttributeError, JevContractError, TypeError, ValueError, RecursionError):
        raise PreferenceGuardError(f"{label} question set is malformed") from None
    if canonical.sha256 != value.sha256:
        raise PreferenceGuardError(f"{label} question set is not canonical")
    return canonical


def _validate_binding(
    binding: Any,
    question_set: NativeJevQuestionSet,
    label: str,
) -> tuple[RunBinding, str]:
    try:
        binding.validate()
        identity = binding.identity_sha256
        question_set_sha256 = binding.question_set_sha256
    except (AttributeError, RuntimeError, TypeError, ValueError):
        raise PreferenceGuardError(f"{label} run binding is invalid") from None
    if question_set_sha256 != question_set.sha256:
        raise PreferenceGuardError(f"{label} run binding names a different question set")
    if not isinstance(identity, str) or _SHA256.fullmatch(identity) is None:
        raise PreferenceGuardError(f"{label} run binding identity is invalid")
    return binding, identity


def _validate_record(
    record: Any,
    binding: RunBinding,
    binding_sha256: str,
    expected_model: ModelIdentity,
    expected_work_item_identity_sha256: str,
    expected_draw_number: int | None,
    label: str,
) -> tuple[AttemptRecord, int, dict[str, Any]]:
    try:
        status = record.status
        stage = record.stage
        variant = record.variant
        delivery = record.delivery
        charge = record.charge
        response_payload = record.response_payload
        attempt_id = record.attempt_id
        attempt_number = record.attempt_number
        request_identity = record.request_identity
        work_item_identity_sha256 = record.work_item_identity_sha256
        run_binding_sha256 = record.run_binding_sha256
        draw_number = record.draw_number
        provider = record.provider
        requested_model = record.requested_model
        resolved_model = record.resolved_model
    except AttributeError:
        raise PreferenceGuardError(f"{label} evidence must be a complete attempt record") from None
    if (
        status != "succeeded"
        or stage != "assess"
        or variant != "direct"
        or delivery != "completed"
        or not isinstance(charge, dict)
        or charge.get("kind") != "actual"
        or response_payload is None
    ):
        raise PreferenceGuardError(f"{label} evidence must be a succeeded direct assessment")
    if (
        type(attempt_id) is not int
        or attempt_id <= 0
        or type(attempt_number) is not int
        or attempt_number <= 0
        or not isinstance(request_identity, str)
        or _SHA256.fullmatch(request_identity) is None
        or not isinstance(work_item_identity_sha256, str)
        or _SHA256.fullmatch(work_item_identity_sha256) is None
        or work_item_identity_sha256 != expected_work_item_identity_sha256
        or run_binding_sha256 != binding_sha256
        or type(draw_number) is not int
        or draw_number <= 0
        or (expected_draw_number is not None and draw_number != expected_draw_number)
    ):
        raise PreferenceGuardError(f"{label} attempt provenance does not match the declared source and run")
    if (
        provider != expected_model.provider
        or requested_model != expected_model.requested_model
        or resolved_model != expected_model.resolved_model
    ):
        raise PreferenceGuardError(f"{label} attempt model differs from the expected model")
    if not isinstance(response_payload, dict):
        raise PreferenceGuardError(f"{label} native response payload is malformed")
    return record, draw_number, response_payload


def _atomic_avoidance(
    values: tuple[str, ...], contract: AtomicAvoidanceContract
) -> GuardAvoidance:
    if len(values) != len(contract.question_ids) or any(
        value not in {contract.present_value, contract.absent_value, contract.unknown_value}
        for value in values
    ):
        raise PreferenceGuardError("atomic response must contain all seven valid avoidance choices")
    if contract.present_value in values:
        return GuardAvoidance.PRESENT
    if contract.unknown_value in values:
        return GuardAvoidance.UNKNOWN
    return GuardAvoidance.ABSENT


def _guard_policy_sha256(
    compound_policy: PreferencePolicy,
    atomic_contract: AtomicAvoidanceContract,
) -> str:
    identity = {
        "domain": "ats-native-preference-disagreement-policy-v1",
        "guard_version": GUARD_VERSION,
        "compound_policy_sha256": compound_policy.sha256,
        "atomic_contract": {
            "version": atomic_contract.version,
            "question_ids": list(atomic_contract.question_ids),
            "question_set_sha256": atomic_contract.question_set_sha256,
            "present_value": atomic_contract.present_value,
            "absent_value": atomic_contract.absent_value,
            "unknown_value": atomic_contract.unknown_value,
        },
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_preference_guard(
    *,
    native_record: AttemptRecord,
    atomic_record: AttemptRecord,
    native_run_binding: RunBinding,
    atomic_run_binding: RunBinding,
    native_question_set: NativeJevQuestionSet,
    atomic_question_set: NativeJevQuestionSet,
    atomic_contract: AtomicAvoidanceContract,
    compound_policy: PreferencePolicy,
    expected_model: ModelIdentity,
    expected_work_item_identity_sha256: str,
) -> PreferenceGuardResult:
    """Validate two explicitly bound native JEV results and apply the keep-first rule."""
    native_questions = _validated_questions(native_question_set, "compound")
    atomic_questions = _validated_questions(atomic_question_set, "atomic")
    if not isinstance(atomic_contract, AtomicAvoidanceContract):
        raise PreferenceGuardError("an explicit atomic avoidance contract is required")
    atomic_contract.validate(atomic_questions)

    try:
        expected_model.validate()
        model_values = (
            expected_model.provider,
            expected_model.requested_model,
            expected_model.resolved_model,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        raise PreferenceGuardError("expected model identity is invalid") from None
    if any(
        not isinstance(value, str) or not value or value.strip() != value
        for value in model_values
    ):
        raise PreferenceGuardError("expected model identity is invalid")
    if (
        not isinstance(expected_work_item_identity_sha256, str)
        or _SHA256.fullmatch(expected_work_item_identity_sha256) is None
    ):
        raise PreferenceGuardError("expected source/work identity must be a lowercase SHA-256 digest")

    native_binding, native_binding_sha256 = _validate_binding(
        native_run_binding, native_questions, "compound"
    )
    atomic_binding, atomic_binding_sha256 = _validate_binding(
        atomic_run_binding, atomic_questions, "atomic"
    )
    _, draw_number, native_payload = _validate_record(
        native_record,
        native_binding,
        native_binding_sha256,
        expected_model,
        expected_work_item_identity_sha256,
        None,
        "compound",
    )
    _, atomic_draw_number, atomic_payload = _validate_record(
        atomic_record,
        atomic_binding,
        atomic_binding_sha256,
        expected_model,
        expected_work_item_identity_sha256,
        draw_number,
        "atomic",
    )
    if atomic_draw_number != draw_number:
        raise PreferenceGuardError("native draws differ")

    try:
        native_assessment = validate_native_jev_journal_payload(
            native_payload,
            expected_question_set=native_questions,
            expected_question_set_sha256=native_binding.question_set_sha256,
            expected_model=expected_model.resolved_model,
        )
        atomic_assessment = validate_native_jev_journal_payload(
            atomic_payload,
            expected_question_set=atomic_questions,
            expected_question_set_sha256=atomic_binding.question_set_sha256,
            expected_model=expected_model.resolved_model,
        )
        base_decision = derive_preference(
            native_payload,
            native_questions,
            expected_model.resolved_model,
            compound_policy,
        )
    except (JevContractError, PreferenceError, TypeError, ValueError, RecursionError):
        raise PreferenceGuardError("native response evidence does not match its frozen contract") from None

    native_answers = {answer.question_id: answer for answer in native_assessment.answers}
    try:
        compound_choice = native_answers[compound_policy.avoidance_question_id].choice
        compound_avoidance = {
            compound_policy.avoidance_present_value: GuardAvoidance.PRESENT,
            compound_policy.avoidance_absent_value: GuardAvoidance.ABSENT,
            compound_policy.avoidance_unclear_value: GuardAvoidance.UNKNOWN,
        }[compound_choice]
        atomic_choices = {answer.question_id: answer.choice for answer in atomic_assessment.answers}
        atomic_values = tuple(atomic_choices[question_id] for question_id in atomic_contract.question_ids)
    except (KeyError, TypeError):
        raise PreferenceGuardError("validated response is missing a fixed avoidance answer") from None
    atomic_avoidance = _atomic_avoidance(atomic_values, atomic_contract)

    if compound_avoidance is atomic_avoidance and compound_avoidance in {
        GuardAvoidance.PRESENT,
        GuardAvoidance.ABSENT,
    }:
        tier = base_decision.tier
        reason = f"signals-agree-{compound_avoidance.value}"
        review_required = tier is PreferenceTier.UNRESOLVED
        material_disagreement = False
    else:
        tier = PreferenceTier.UNRESOLVED
        review_required = True
        material_disagreement = {
            compound_avoidance,
            atomic_avoidance,
        } == {GuardAvoidance.PRESENT, GuardAvoidance.ABSENT}
        reason = "material-avoidance-disagreement" if material_disagreement else "ordinary-uncertainty"

    try:
        retained_native_payload = deepcopy(native_payload)
        retained_atomic_payload = deepcopy(atomic_payload)
    except (TypeError, ValueError, RecursionError):
        raise PreferenceGuardError("validated native response payload cannot be retained") from None

    return PreferenceGuardResult(
        base_decision=base_decision,
        tier=tier,
        reason=reason,
        review_required=review_required,
        material_disagreement=material_disagreement,
        compound_avoidance=compound_avoidance,
        atomic_avoidance=atomic_avoidance,
        source_work_item_identity_sha256=expected_work_item_identity_sha256,
        draw_number=draw_number,
        model_identity=expected_model,
        guard_version=GUARD_VERSION,
        policy_sha256=_guard_policy_sha256(compound_policy, atomic_contract),
        atomic_contract_version=atomic_contract.version,
        native_run_binding=native_binding,
        native_run_binding_sha256=native_binding_sha256,
        native_question_set_sha256=native_questions.sha256,
        native_response_sha256=native_payload["response_sha256"],
        native_response_payload=retained_native_payload,
        atomic_run_binding=atomic_binding,
        atomic_run_binding_sha256=atomic_binding_sha256,
        atomic_question_set_sha256=atomic_questions.sha256,
        atomic_response_sha256=atomic_payload["response_sha256"],
        atomic_response_payload=retained_atomic_payload,
    )
