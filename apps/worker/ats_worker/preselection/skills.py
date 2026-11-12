"""Exact-source skill evidence comparison for isolated native JEV assessments.

This module derives a bounded, per-requirement evidence report from a frozen sidecar.
It does not estimate overall fit, rank jobs, infer eligibility, or change raw answers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
from ats_worker.preselection.profile import (
    CandidateProfile,
    ProfileValidationError,
    profile_from_value,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_QUESTION_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SUPPORT_VALUES = {"direct", "transferable", "not_evidenced", "unknown"}
_OBLIGATIONS = {"required", "preferred", "unclear"}
_CENTRALITIES = {"central", "supporting", "unclear"}
_MAX_REQUIREMENTS = 5
_MAX_PROFILE_REFS_PER_REQUIREMENT = 8
_MAX_SPAN_TEXT = 4096
_MAX_JD_TEXT = 1_000_000
_MAX_POLICY_BYTES = 64 * 1024


class SkillEvidenceError(ValueError):
    """A skill evidence policy, source span, profile reference or response is invalid."""


def _text(
    value: Any,
    path: str,
    *,
    maximum: int = 128,
    allow_whitespace: bool = False,
    allow_controls: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or (not allow_whitespace and value.strip() != value)
        or (not allow_controls and any(ord(char) < 32 for char in value))
        or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise SkillEvidenceError(f"{path} must be bounded, non-empty valid text")
    return value


def _sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SkillEvidenceError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        result = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise SkillEvidenceError("skill policy cannot be canonically encoded") from exc
    if len(result) > _MAX_POLICY_BYTES:
        raise SkillEvidenceError("skill policy exceeds its canonical size limit")
    return result


def _validate_span(text: str, quote: Any, start: Any, end: Any, path: str) -> None:
    _text(
        quote,
        f"{path}.quote",
        maximum=_MAX_SPAN_TEXT,
        allow_whitespace=True,
        allow_controls=True,
    )
    if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > len(text):
        raise SkillEvidenceError(f"{path} offsets are invalid")
    if text[start:end] != quote:
        raise SkillEvidenceError(f"{path} quote does not match the exact source span")


@dataclass(frozen=True)
class ProfileEvidenceRef:
    block_id: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class SkillRequirement:
    question_id: str
    quote: str
    start: int
    end: int
    obligation: str
    centrality: str
    profile_evidence: tuple[ProfileEvidenceRef, ...] = ()


@dataclass(frozen=True)
class SkillEvidencePolicy:
    version: str
    question_set_sha256: str
    profile_sha256: str
    jd_sha256: str
    requirements: tuple[SkillRequirement, ...]

    def validate(
        self,
        question_set: NativeJevQuestionSet,
        jd_text: str,
        profile: CandidateProfile,
    ) -> None:
        if not isinstance(question_set, NativeJevQuestionSet):
            raise SkillEvidenceError("policy requires a validated native JEV question set")
        try:
            canonical_questions = jev_question_set_from_value(question_set.as_dict())
        except (AttributeError, JevContractError):
            raise SkillEvidenceError("policy question set is malformed") from None
        if canonical_questions.sha256 != question_set.sha256:
            raise SkillEvidenceError("policy question set is not canonical")
        _text(self.version, "policy.version", maximum=64)
        _sha256(self.question_set_sha256, "policy.question_set_sha256")
        _sha256(self.profile_sha256, "policy.profile_sha256")
        _sha256(self.jd_sha256, "policy.jd_sha256")
        if self.question_set_sha256 != question_set.sha256:
            raise SkillEvidenceError("policy question-set hash differs from the frozen questions")
        if not isinstance(jd_text, str) or not jd_text or len(jd_text) > _MAX_JD_TEXT:
            raise SkillEvidenceError("full job description is missing or outside its text bound")
        try:
            jd_sha = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            raise SkillEvidenceError("job description contains invalid Unicode") from None
        if jd_sha != self.jd_sha256:
            raise SkillEvidenceError("job description differs from its frozen hash")
        if not isinstance(profile, CandidateProfile):
            raise SkillEvidenceError("policy requires a validated candidate profile")
        try:
            verified_profile = profile_from_value({
                "schema": profile.schema,
                "version": profile.version,
                "as_of": profile.as_of,
                "status": profile.status,
                "background": [asdict(block) for block in profile.background],
                "preferences": [asdict(block) for block in profile.preferences],
            })
        except (AttributeError, TypeError, ProfileValidationError):
            raise SkillEvidenceError("candidate profile is malformed") from None
        if verified_profile.identity_sha256 != profile.identity_sha256:
            raise SkillEvidenceError("candidate profile is not canonical")
        if profile.status != "approved":
            raise SkillEvidenceError("skill evidence requires the frozen approved profile")
        if profile.identity_sha256 != self.profile_sha256:
            raise SkillEvidenceError("candidate profile differs from its frozen hash")
        if not isinstance(self.requirements, tuple) or not self.requirements:
            raise SkillEvidenceError("policy must select one or more requirements")
        if len(self.requirements) > _MAX_REQUIREMENTS:
            raise SkillEvidenceError("policy exceeds the per-job requirement limit")

        background = {block.id: block.text for block in profile.background}
        questions = {question.id: question for question in question_set.questions}
        expected_question_ids: set[str] = set()
        seen_spans: set[tuple[int, int]] = set()
        for index, requirement in enumerate(self.requirements):
            path = f"policy.requirements[{index}]"
            if not isinstance(requirement, SkillRequirement):
                raise SkillEvidenceError(f"{path} has an unsupported value")
            question_id = _text(requirement.question_id, f"{path}.question_id")
            if _QUESTION_ID.fullmatch(question_id) is None or question_id in expected_question_ids:
                raise SkillEvidenceError(f"{path}.question_id is invalid or duplicated")
            expected_question_ids.add(question_id)
            _validate_span(jd_text, requirement.quote, requirement.start, requirement.end, path)
            span = (requirement.start, requirement.end)
            if span in seen_spans:
                raise SkillEvidenceError("policy contains a duplicate JD source span")
            seen_spans.add(span)
            if not isinstance(requirement.obligation, str) or requirement.obligation not in _OBLIGATIONS:
                raise SkillEvidenceError(f"{path}.obligation is unsupported")
            if not isinstance(requirement.centrality, str) or requirement.centrality not in _CENTRALITIES:
                raise SkillEvidenceError(f"{path}.centrality is unsupported")
            if not isinstance(requirement.profile_evidence, tuple):
                raise SkillEvidenceError(f"{path}.profile_evidence must be a tuple")
            if len(requirement.profile_evidence) > _MAX_PROFILE_REFS_PER_REQUIREMENT:
                raise SkillEvidenceError(f"{path}.profile_evidence exceeds its reference limit")
            # The same exact source passage may support independent requirements. Only
            # duplicate references within this one requirement are ambiguous/redundant.
            seen_profile_refs: set[tuple[str, int, int, str]] = set()
            question = questions.get(question_id)
            if question is None or question.question_type != "choice":
                raise SkillEvidenceError(f"{path} must bind a frozen Choice question")
            if set(dict(question.choice_criteria)) != _SUPPORT_VALUES:
                raise SkillEvidenceError(f"{path} question criteria differ from the support contract")
            for ref_index, reference in enumerate(requirement.profile_evidence):
                ref_path = f"{path}.profile_evidence[{ref_index}]"
                if not isinstance(reference, ProfileEvidenceRef):
                    raise SkillEvidenceError(f"{ref_path} has an unsupported value")
                block_id = _text(reference.block_id, f"{ref_path}.block_id", maximum=64)
                block_text = background.get(block_id)
                if block_text is None:
                    raise SkillEvidenceError(f"{ref_path} must name a background block")
                _validate_span(block_text, reference.quote, reference.start, reference.end, ref_path)
                ref_identity = (block_id, reference.start, reference.end, reference.quote)
                if ref_identity in seen_profile_refs:
                    raise SkillEvidenceError("policy contains a duplicate profile evidence reference")
                seen_profile_refs.add(ref_identity)
        if set(questions) != expected_question_ids:
            raise SkillEvidenceError("question pack must contain exactly the selected requirement questions")
        _canonical_json(asdict(self))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_json({
            "domain": "ats-preselection-skill-evidence-policy-v1",
            "policy": asdict(self),
        })).hexdigest()


@dataclass(frozen=True)
class SkillRequirementEvidence:
    question_id: str
    quote: str
    start: int
    end: int
    obligation: str
    centrality: str
    support: str
    core_status: str
    profile_evidence: tuple[ProfileEvidenceRef, ...]


@dataclass(frozen=True)
class SkillEvidenceReport:
    summary: str
    coverage: str
    provenance: str
    policy_sha256: str
    question_set_sha256: str
    profile_sha256: str
    jd_sha256: str
    response_sha256: str
    model_identity: str
    selected_requirement_ids: tuple[str, ...]
    explicit_core_requirement_ids: tuple[str, ...]
    unverified_core_requirement_ids: tuple[str, ...]
    unresolved_requirement_ids: tuple[str, ...]
    referenced_profile_block_ids: tuple[str, ...]
    requirements: tuple[SkillRequirementEvidence, ...]


def derive_skill_evidence(
    native_payload: Any,
    question_set: NativeJevQuestionSet,
    expected_model: str,
    jd_text: str,
    profile: CandidateProfile,
    policy: SkillEvidencePolicy,
) -> SkillEvidenceReport:
    """Revalidate frozen sources and native answers, then derive bounded requirement evidence."""
    policy.validate(question_set, jd_text, profile)
    _text(expected_model, "expected resolved model", maximum=256)
    try:
        assessment = validate_native_jev_journal_payload(
            native_payload,
            expected_question_set=question_set,
            expected_question_set_sha256=policy.question_set_sha256,
            expected_model=expected_model,
        )
    except JevContractError:
        raise SkillEvidenceError("native JEV response differs from the frozen evidence contract") from None
    answers = {answer.question_id: answer.choice for answer in assessment.answers}
    response_sha = native_payload.get("response_sha256") if isinstance(native_payload, dict) else None
    response_sha = _sha256(response_sha, "response_sha256")

    results: list[SkillRequirementEvidence] = []
    explicit_core_ids: list[str] = []
    unverified_core_ids: list[str] = []
    unresolved_ids: list[str] = []
    profile_block_ids: list[str] = []
    has_unresolved_core = False

    for requirement in policy.requirements:
        support = answers[requirement.question_id]
        refs = requirement.profile_evidence
        explicit_core = requirement.obligation == "required" and requirement.centrality == "central"
        possible_core = (
            (requirement.obligation == "required" and requirement.centrality == "unclear")
            or (
                requirement.obligation == "unclear"
                and requirement.centrality in {"central", "unclear"}
            )
        )
        if explicit_core:
            explicit_core_ids.append(requirement.question_id)
        positive_without_profile_trace = support in {"direct", "transferable"} and not refs
        if positive_without_profile_trace:
            # Preserve the model's raw label while withholding a positive comparison that
            # cannot be traced to any supplied background evidence.
            core_status = "unresolved"
            unresolved_ids.append(requirement.question_id)
            if explicit_core or possible_core:
                has_unresolved_core = True
        elif explicit_core:
            if support in {"transferable", "not_evidenced"}:
                core_status = "core_requirement_unverified"
                unverified_core_ids.append(requirement.question_id)
            elif support == "unknown":
                core_status = "unresolved"
                has_unresolved_core = True
                unresolved_ids.append(requirement.question_id)
            else:
                core_status = "core_evidence_supported"
        elif possible_core:
            core_status = "unresolved"
            has_unresolved_core = True
            unresolved_ids.append(requirement.question_id)
        else:
            core_status = "not_core_requirement"
        if support == "unknown" and requirement.question_id not in unresolved_ids:
            # Unknown remains visible on preferred/supporting requirements too, but it
            # does not change core status or the summary unless the fact may be core.
            unresolved_ids.append(requirement.question_id)
        results.append(SkillRequirementEvidence(
            question_id=requirement.question_id,
            quote=requirement.quote,
            start=requirement.start,
            end=requirement.end,
            obligation=requirement.obligation,
            centrality=requirement.centrality,
            support=support,
            core_status=core_status,
            profile_evidence=refs,
        ))
        profile_block_ids.extend(reference.block_id for reference in refs)

    if unverified_core_ids:
        summary = "core_requirement_unverified"
    elif has_unresolved_core:
        summary = "unresolved"
    elif explicit_core_ids:
        summary = "core_evidence_supported"
    else:
        summary = "no_explicit_core_requirement"

    return SkillEvidenceReport(
        summary=summary,
        coverage="selected_requirements_only",
        provenance="operator_proxy_not_gold",
        policy_sha256=policy.sha256,
        question_set_sha256=question_set.sha256,
        profile_sha256=profile.identity_sha256,
        jd_sha256=policy.jd_sha256,
        response_sha256=response_sha,
        model_identity=expected_model,
        selected_requirement_ids=tuple(item.question_id for item in policy.requirements),
        explicit_core_requirement_ids=tuple(explicit_core_ids),
        unverified_core_requirement_ids=tuple(unverified_core_ids),
        unresolved_requirement_ids=tuple(unresolved_ids),
        referenced_profile_block_ids=tuple(dict.fromkeys(profile_block_ids)),
        requirements=tuple(results),
    )
