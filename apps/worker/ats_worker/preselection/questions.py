"""Versioned typed question sets and strict assessment-response validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any


class QuestionContractError(ValueError):
    """A question set or provider answer violates its declared contract."""


_QUESTION_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_QUESTION_TYPES = {"enum", "multi_enum", "number"}
_QUESTION_SET_KEYS = {"version", "questions"}
_QUESTION_KEYS = {
    "enum": {"id", "prompt", "type", "allowed_values"},
    "multi_enum": {"id", "prompt", "type", "allowed_values"},
    "number": {"id", "prompt", "type", "minimum", "maximum"},
}


@dataclass(frozen=True)
class QuestionSpec:
    id: str
    prompt: str
    answer_type: str
    allowed_values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "prompt": self.prompt,
            "type": self.answer_type,
        }
        if self.answer_type in {"enum", "multi_enum"}:
            result["allowed_values"] = list(self.allowed_values)
        else:
            result["minimum"] = self.minimum
            result["maximum"] = self.maximum
        return result


@dataclass(frozen=True)
class QuestionSet:
    version: str
    questions: tuple[QuestionSpec, ...]

    def canonical_json(self) -> str:
        return json.dumps(
            {"version": self.version, "questions": [q.as_dict() for q in self.questions]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def answer_schema(self) -> dict[str, Any]:
        """Build a strict JSON schema from this caller-supplied versioned question set."""
        properties: dict[str, Any] = {}
        for question in self.questions:
            if question.answer_type == "enum":
                value_schema: dict[str, Any] = {
                    "type": "string",
                    "enum": list(question.allowed_values),
                }
            elif question.answer_type == "multi_enum":
                value_schema = {
                    "type": "array",
                    "items": {"type": "string", "enum": list(question.allowed_values)},
                    "uniqueItems": True,
                }
            else:
                value_schema = {
                    "type": "number",
                    "minimum": question.minimum,
                    "maximum": question.maximum,
                }
            properties[question.id] = {
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "evidence"],
                "properties": {
                    "value": value_schema,
                    "evidence": {"type": "array", "items": {"type": "object"}},
                },
            }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["answers", "explanation"],
            "properties": {
                "answers": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [q.id for q in self.questions],
                    "properties": properties,
                },
                "explanation": {"type": "string", "minLength": 1},
            },
        }


@dataclass(frozen=True)
class ValidatedAnswer:
    question_id: str
    value: str | float | list[str]
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ValidatedAssessment:
    answers: tuple[ValidatedAnswer, ...]
    explanation: str


def _object(value: Any, allowed: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QuestionContractError(f"{path} must be an object")
    present = set(value)
    if present - allowed:
        raise QuestionContractError(f"{path} contains an unknown field")
    if allowed - present:
        raise QuestionContractError(f"{path} is missing a required field")
    return value


def question_set_from_value(value: Any) -> QuestionSet:
    payload = _object(value, _QUESTION_SET_KEYS, "question_set")
    version = payload["version"]
    if not isinstance(version, str) or not version.strip() or version.strip() != version:
        raise QuestionContractError("question_set.version must be non-empty trimmed text")
    raw_questions = payload["questions"]
    if not isinstance(raw_questions, list) or not raw_questions:
        raise QuestionContractError("question_set.questions must be a non-empty array")

    questions: list[QuestionSpec] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_questions):
        path = f"question_set.questions[{index}]"
        if not isinstance(raw, dict):
            raise QuestionContractError(f"{path} must be an object")
        answer_type = raw.get("type")
        if not isinstance(answer_type, str) or answer_type not in _QUESTION_TYPES:
            raise QuestionContractError(f"{path}.type is unsupported")
        question = _object(raw, _QUESTION_KEYS[answer_type], path)
        question_id = question["id"]
        if not isinstance(question_id, str) or not _QUESTION_ID_RE.fullmatch(question_id):
            raise QuestionContractError(f"{path}.id is invalid")
        if question_id in seen_ids:
            raise QuestionContractError("question IDs must be unique")
        seen_ids.add(question_id)
        prompt = question["prompt"]
        if not isinstance(prompt, str) or not prompt.strip() or prompt.strip() != prompt:
            raise QuestionContractError(f"{path}.prompt must be non-empty trimmed text")

        if answer_type in {"enum", "multi_enum"}:
            values = question["allowed_values"]
            if not isinstance(values, list) or not values:
                raise QuestionContractError(f"{path}.allowed_values must be a non-empty array")
            if any(not isinstance(item, str) or not item.strip() or item.strip() != item for item in values):
                raise QuestionContractError(f"{path}.allowed_values contains an invalid value")
            if len(set(values)) != len(values):
                raise QuestionContractError(f"{path}.allowed_values contains duplicates")
            questions.append(QuestionSpec(question_id, prompt, answer_type, tuple(values)))
        else:
            minimum, maximum = question["minimum"], question["maximum"]
            if (
                isinstance(minimum, bool)
                or not isinstance(minimum, (int, float))
                or not math.isfinite(minimum)
                or isinstance(maximum, bool)
                or not isinstance(maximum, (int, float))
                or not math.isfinite(maximum)
                or minimum > maximum
            ):
                raise QuestionContractError(f"{path} requires finite ordered numeric bounds")
            questions.append(QuestionSpec(question_id, prompt, answer_type, (), float(minimum), float(maximum)))
    return QuestionSet(version, tuple(questions))


def _quote_reference(
    value: Any,
    *,
    variant: str,
    job_description: str,
    candidate_context: str,
    fact_ids: set[str],
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QuestionContractError(f"{path} must be an object")
    source = value.get("source")
    if source == "fact":
        reference = _object(value, {"source", "fact_id"}, path)
        fact_id = reference["fact_id"]
        if variant != "extracted" or not isinstance(fact_id, str) or fact_id not in fact_ids:
            raise QuestionContractError(f"{path} references an unavailable fact")
        return reference
    reference = _object(value, {"source", "start", "end", "quote"}, path)
    start, end, quote = reference["start"], reference["end"], reference["quote"]
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise QuestionContractError(f"{path} has invalid source offsets")
    if not isinstance(quote, str) or not quote:
        raise QuestionContractError(f"{path}.quote must be non-empty text")
    if source == "jd" and variant == "direct":
        source_text = job_description
    elif source == "candidate_context":
        source_text = candidate_context
    else:
        raise QuestionContractError(f"{path}.source is unavailable in this assessment variant")
    if end > len(source_text) or source_text[start:end] != quote:
        raise QuestionContractError(f"{path} does not match its source span")
    return reference


def validate_assessment_payload(
    value: Any,
    question_set: QuestionSet,
    *,
    variant: str,
    job_description: str,
    candidate_context: str,
    fact_ids: set[str] | None = None,
) -> ValidatedAssessment:
    """Validate exact question cardinality, typed values and input-backed evidence."""
    if variant not in {"direct", "extracted"}:
        raise QuestionContractError("variant must be direct or extracted")
    payload = _object(value, {"answers", "explanation"}, "assessment")
    explanation = payload["explanation"]
    if not isinstance(explanation, str) or not explanation.strip() or explanation.strip() != explanation:
        raise QuestionContractError("assessment.explanation must be non-empty trimmed text")
    answers_obj = payload["answers"]
    expected_ids = {question.id for question in question_set.questions}
    if not isinstance(answers_obj, dict):
        raise QuestionContractError("assessment.answers must be an object")
    if set(answers_obj) != expected_ids:
        raise QuestionContractError("assessment answer IDs do not match the question set")

    validated: list[ValidatedAnswer] = []
    available_fact_ids = fact_ids or set()
    for question in question_set.questions:
        answer = _object(
            answers_obj[question.id], {"value", "evidence"}, f"assessment.answers.{question.id}"
        )
        raw_value = answer["value"]
        if question.answer_type == "enum":
            if not isinstance(raw_value, str) or raw_value not in question.allowed_values:
                raise QuestionContractError(f"answer {question.id} is outside its allowed values")
            checked_value: str | float | list[str] = raw_value
        elif question.answer_type == "multi_enum":
            if not isinstance(raw_value, list) or any(
                not isinstance(item, str) or item not in question.allowed_values for item in raw_value
            ):
                raise QuestionContractError(f"answer {question.id} is outside its allowed values")
            if len(set(raw_value)) != len(raw_value):
                raise QuestionContractError(f"answer {question.id} contains duplicate values")
            checked_value = list(raw_value)
        else:
            if (
                isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float))
                or not math.isfinite(raw_value)
                or raw_value < question.minimum
                or raw_value > question.maximum
            ):
                raise QuestionContractError(f"answer {question.id} is outside its finite numeric range")
            checked_value = float(raw_value)

        evidence = answer["evidence"]
        if not isinstance(evidence, list):
            raise QuestionContractError(f"answer {question.id}.evidence must be an array")
        checked_evidence = tuple(
            _quote_reference(
                reference,
                variant=variant,
                job_description=job_description,
                candidate_context=candidate_context,
                fact_ids=available_fact_ids,
                path=f"assessment.answers.{question.id}.evidence[{index}]",
            )
            for index, reference in enumerate(evidence)
        )
        validated.append(ValidatedAnswer(question.id, checked_value, checked_evidence))
    return ValidatedAssessment(tuple(validated), explanation)
