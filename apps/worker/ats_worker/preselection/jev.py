"""Native OpenRouter System One JEV question and response contracts.

This module keeps JEV's Choice, Noul and Score values intact. It does not adapt them
to the generic explanation/evidence contract used by other shadow transports.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any


class JevContractError(ValueError):
    """A native JEV question pack or response violates its frozen contract."""


_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SET_KEYS = {"version", "questions"}
_COMMON_QUESTION_KEYS = {"id", "type", "instructions"}
NATIVE_JEV_CONTRACT = "openrouter-systemone-native-v1"


@dataclass(frozen=True)
class NativeJevQuestion:
    id: str
    question_type: str
    instructions: str
    choice_criteria: tuple[tuple[str, str], ...] = ()
    score_criteria: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "type": self.question_type,
            "instructions": self.instructions,
        }
        if self.question_type == "choice":
            value["criteria"] = dict(self.choice_criteria)
        elif self.question_type == "score":
            value["criteria"] = list(self.score_criteria)
        return value

    def wire_value(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "type": self.question_type,
            "instructions": self.instructions,
        }
        if self.question_type == "choice":
            value["criteria"] = dict(self.choice_criteria)
        elif self.question_type == "score":
            value["criteria"] = list(self.score_criteria)
        return value


@dataclass(frozen=True)
class NativeJevQuestionSet:
    version: str
    questions: tuple[NativeJevQuestion, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "questions": [item.as_dict() for item in self.questions]}

    def canonical_json(self) -> str:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def wire_map(self) -> dict[str, dict[str, Any]]:
        return {item.id: item.wire_value() for item in self.questions}


@dataclass(frozen=True)
class ValidatedNativeJevAnswer:
    question_id: str
    question_type: str
    choice: str | None = None
    noul: int | float | None = None
    score: int | float | None = None
    legend: tuple[tuple[str, str], ...] = ()
    probabilities: tuple[tuple[str, int | float], ...] = ()
    confidence: int | float | None = None

    @property
    def value(self) -> str | int | float:
        if self.question_type == "choice":
            assert self.choice is not None
            return self.choice
        if self.question_type == "noul":
            assert self.noul is not None
            return self.noul
        assert self.score is not None
        return self.score


@dataclass(frozen=True)
class ValidatedNativeAssessment:
    answers: tuple[ValidatedNativeJevAnswer, ...]


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise JevContractError(f"{path} must be non-empty trimmed text")
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise JevContractError(f"{path} contains unsupported characters")
    return value


def _number(value: Any, path: str, *, minimum: float | None = None, maximum: float | None = None) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevContractError(f"{path} must be a finite number")
    if type(value) is int and value.bit_length() > 256:
        raise JevContractError(f"{path} exceeds the numeric size limit")
    if type(value) is float and not math.isfinite(value):
        raise JevContractError(f"{path} must be a finite number")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise JevContractError(f"{path} is outside its allowed range")
    return value


def jev_question_set_from_value(value: Any) -> NativeJevQuestionSet:
    if not isinstance(value, dict) or set(value) != _SET_KEYS:
        raise JevContractError("native JEV question set has an invalid object shape")
    version = _text(value["version"], "question_set.version")
    raw_questions = value["questions"]
    if not isinstance(raw_questions, list) or not raw_questions:
        raise JevContractError("question_set.questions must be a non-empty array")
    questions: list[NativeJevQuestion] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_questions):
        path = f"question_set.questions[{index}]"
        if not isinstance(raw, dict):
            raise JevContractError(f"{path} must be an object")
        question_type = raw.get("type")
        if not isinstance(question_type, str) or question_type not in {"choice", "noul", "score"}:
            raise JevContractError(f"{path}.type is unsupported")
        required = _COMMON_QUESTION_KEYS | ({"criteria"} if question_type in {"choice", "score"} else set())
        if set(raw) != required:
            raise JevContractError(f"{path} has an invalid object shape")
        question_id = _text(raw["id"], f"{path}.id")
        if _ID_RE.fullmatch(question_id) is None or question_id in seen:
            raise JevContractError(f"{path}.id is invalid or duplicated")
        seen.add(question_id)
        instructions = _text(raw["instructions"], f"{path}.instructions")
        if question_type == "choice":
            criteria = raw["criteria"]
            if not isinstance(criteria, dict) or not criteria:
                raise JevContractError(f"{path}.criteria must be a non-empty object")
            checked: list[tuple[str, str]] = []
            for key, description in criteria.items():
                criterion_id = _text(key, f"{path}.criteria key")
                if len(criterion_id) > 128:
                    raise JevContractError(f"{path}.criteria key is too long")
                checked.append((criterion_id, _text(description, f"{path}.criteria.{criterion_id}")))
            questions.append(NativeJevQuestion(question_id, question_type, instructions, tuple(checked)))
        elif question_type == "score":
            criteria = raw["criteria"]
            if not isinstance(criteria, list) or not criteria:
                raise JevContractError(f"{path}.criteria must be a non-empty ordered array")
            checked_values = tuple(_text(item, f"{path}.criteria[{i}]") for i, item in enumerate(criteria))
            if len(set(checked_values)) != len(checked_values):
                raise JevContractError(f"{path}.criteria contains duplicates")
            questions.append(NativeJevQuestion(question_id, question_type, instructions, score_criteria=checked_values))
        else:
            questions.append(NativeJevQuestion(question_id, question_type, instructions))
    return NativeJevQuestionSet(version, tuple(questions))


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JevContractError(f"{path} must be an object")
    return value


def _probability_distribution(value: Any, keys: set[str], path: str) -> tuple[tuple[str, int | float], ...]:
    distribution = _object(value, path)
    if set(distribution) != keys:
        raise JevContractError(f"{path} does not match the complete criteria set")
    checked = tuple((key, _number(distribution[key], f"{path}.{key}", minimum=0.0, maximum=1.0)) for key in sorted(keys))
    if not math.isclose(sum(value for _, value in checked), 1.0, rel_tol=0.0, abs_tol=0.02):
        raise JevContractError(f"{path} does not sum to one")
    return checked


def validate_jev_response(
    value: Any,
    question_set: NativeJevQuestionSet,
    *,
    expected_model: str | None = None,
) -> ValidatedNativeAssessment:
    """Validate exact native answer cardinality and all distributions/rubrics."""
    payload = _object(value, "response")
    if set(payload) - {"id", "model", "provider", "answers", "usage"}:
        raise JevContractError("response contains unsupported fields")
    served_model = _text(payload.get("model"), "response.model")
    if expected_model is not None and served_model != expected_model:
        raise JevContractError("response.model differs from the frozen resolved model")
    for optional in ("id", "provider"):
        if optional in payload:
            _text(payload[optional], f"response.{optional}")
    raw_answers = _object(payload.get("answers"), "response.answers")
    expected_ids = {question.id for question in question_set.questions}
    if set(raw_answers) != expected_ids:
        raise JevContractError("response answer IDs differ from the frozen question set")

    validated: list[ValidatedNativeJevAnswer] = []
    for question in question_set.questions:
        answer = _object(raw_answers[question.id], f"response.answers.{question.id}")
        if answer.get("type") != question.question_type:
            raise JevContractError(f"response.answers.{question.id}.type differs from its question")
        if question.question_type == "noul":
            if set(answer) != {"type", "noul"}:
                raise JevContractError(f"response.answers.{question.id} has an invalid Noul shape")
            validated.append(
                ValidatedNativeJevAnswer(question.id, "noul", noul=_number(answer["noul"], f"answers.{question.id}.noul", minimum=0.0, maximum=1.0))
            )
            continue
        if set(answer) != {"type", "choice", "probabilities", "confidence"} and question.question_type == "choice":
            raise JevContractError(f"response.answers.{question.id} has an invalid Choice shape")
        if set(answer) != {"type", "score", "legend", "probabilities", "confidence"} and question.question_type == "score":
            raise JevContractError(f"response.answers.{question.id} has an invalid Score shape")
        confidence = _number(answer["confidence"], f"answers.{question.id}.confidence", minimum=0.0, maximum=1.0)
        if question.question_type == "choice":
            choice = _text(answer["choice"], f"answers.{question.id}.choice")
            criteria = dict(question.choice_criteria)
            if choice not in criteria:
                raise JevContractError(f"answers.{question.id}.choice is outside the frozen criteria")
            probabilities = _probability_distribution(
                answer["probabilities"], set(criteria), f"answers.{question.id}.probabilities"
            )
            validated.append(
                ValidatedNativeJevAnswer(
                    question.id, "choice", choice=choice, probabilities=probabilities, confidence=confidence
                )
            )
            continue
        score = _number(answer["score"], f"answers.{question.id}.score", minimum=0.0, maximum=len(question.score_criteria) - 1)
        expected_legend = {str(i): text for i, text in enumerate(question.score_criteria)}
        legend = _object(answer["legend"], f"answers.{question.id}.legend")
        if legend != expected_legend:
            raise JevContractError(f"answers.{question.id}.legend differs from the frozen score criteria")
        probabilities = _probability_distribution(
            answer["probabilities"], set(expected_legend), f"answers.{question.id}.probabilities"
        )
        validated.append(
            ValidatedNativeJevAnswer(
                question.id,
                "score",
                score=score,
                legend=tuple((key, expected_legend[key]) for key in sorted(expected_legend)),
                probabilities=probabilities,
                confidence=confidence,
            )
        )

    _validate_native_usage(payload.get("usage"))
    return ValidatedNativeAssessment(tuple(validated))


def native_jev_journal_payload(
    question_set: NativeJevQuestionSet, response: dict[str, Any]
) -> dict[str, Any]:
    """Attach frozen contract provenance while retaining the raw provider response."""
    try:
        canonical_response = json.dumps(
            response, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise JevContractError("native JEV response cannot be canonically hashed") from exc
    return {
        "native_contract": NATIVE_JEV_CONTRACT,
        "question_set": question_set.as_dict(),
        "question_set_sha256": question_set.sha256,
        "response_sha256": hashlib.sha256(canonical_response).hexdigest(),
        "response": response,
    }


def validate_native_jev_journal_payload(
    value: Any,
    *,
    expected_question_set: NativeJevQuestionSet | None = None,
    expected_question_set_sha256: str | None = None,
    expected_model: str | None = None,
) -> ValidatedNativeAssessment:
    """Verify wrapper provenance and revalidate the complete nested native response."""
    if not isinstance(value, dict) or set(value) != {
        "native_contract", "question_set", "question_set_sha256", "response_sha256", "response"
    }:
        raise JevContractError("native JEV journal payload has an invalid wrapper shape")
    if value["native_contract"] != NATIVE_JEV_CONTRACT:
        raise JevContractError("native JEV journal payload has an unknown contract")
    question_set = jev_question_set_from_value(value["question_set"])
    if value["question_set_sha256"] != question_set.sha256:
        raise JevContractError("native JEV journal question-set hash differs from its content")
    if expected_question_set is not None and question_set.sha256 != expected_question_set.sha256:
        raise JevContractError("native JEV journal question set differs from the invocation")
    if (
        expected_question_set_sha256 is not None
        and question_set.sha256 != expected_question_set_sha256
    ):
        raise JevContractError("native JEV journal question set differs from the frozen evaluation")
    response = value["response"]
    if not isinstance(response, dict):
        raise JevContractError("native JEV journal response must be an object")
    try:
        canonical_response = json.dumps(
            response, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise JevContractError("native JEV journal response cannot be canonically hashed") from exc
    response_sha256 = value["response_sha256"]
    if not isinstance(response_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", response_sha256):
        raise JevContractError("native JEV journal response hash is invalid")
    if hashlib.sha256(canonical_response).hexdigest() != response_sha256:
        raise JevContractError("native JEV journal response differs from its retained hash")
    return validate_jev_response(response, question_set, expected_model=expected_model)


def _validate_native_usage(value: Any) -> None:
    if value is None:
        return
    usage = _object(value, "response.usage")
    allowed = {"input_tokens", "output_tokens", "cached_input_tokens", "cost"}
    if set(usage) - allowed:
        raise JevContractError("response.usage contains unsupported fields")
    for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
        if key in usage and (type(usage[key]) is not int or usage[key] < 0):
            raise JevContractError(f"response.usage.{key} must be a non-negative integer")
    if "cost" in usage:
        _number(usage["cost"], "response.usage.cost", minimum=0.0)
