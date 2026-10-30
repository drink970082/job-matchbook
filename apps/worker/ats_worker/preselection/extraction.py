"""JD-only fact extraction contracts, source-span checks and required-YOE policy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from ats_worker.preselection.profile import CandidateProfile


class ExtractionValidationError(ValueError):
    """An extraction is malformed, unsupported or not backed by the supplied JD."""


class YoePolicyError(ValueError):
    """A required-YOE policy or alternative-applicability answer is malformed."""


_EXTRACTION_KEYS = {"schema", "coverage", "facts", "alternative_groups"}
_FACT_KEYS = {
    "id",
    "quote",
    "start",
    "end",
    "category",
    "strength",
    "experience_kind",
    "minimum_years",
    "maximum_years",
    "alternative_group_id",
}
_FACT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_CATEGORIES = {"duty", "qualification", "constraint", "experience"}
_STRENGTHS = {"required", "preferred", "unspecified", "ambiguous"}
_EXPERIENCE_KINDS = {
    "professional_relevant",
    "degree_duration",
    "unrelated_professional",
    "not_experience",
    "unknown",
}
_COVERAGE = {"complete", "incomplete", "unknown"}
_ALTERNATIVE_STATES = {
    "lower_yoe_path_applicable",
    "lower_yoe_path_inapplicable",
    "unknown",
}


@dataclass(frozen=True)
class ExtractedFact:
    id: str
    quote: str
    start: int
    end: int
    category: str
    strength: str
    experience_kind: str
    minimum_years: int | None
    maximum_years: int | None
    alternative_group_id: str | None

    def model_value(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
            "category": self.category,
            "strength": self.strength,
            "experience_kind": self.experience_kind,
            "minimum_years": self.minimum_years,
            "maximum_years": self.maximum_years,
            "alternative_group_id": self.alternative_group_id,
        }


@dataclass(frozen=True)
class AlternativeGroup:
    id: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class JdExtraction:
    coverage: str
    facts: tuple[ExtractedFact, ...]
    alternative_groups: tuple[AlternativeGroup, ...]
    jd_sha256: str

    @property
    def fact_ids(self) -> set[str]:
        return {fact.id for fact in self.facts}

    @property
    def sha256(self) -> str:
        payload = {
            "coverage": self.coverage,
            "facts": [fact.model_value() for fact in self.facts],
            "alternative_groups": [
                {"id": group.id, "fact_ids": list(group.fact_ids)}
                for group in self.alternative_groups
            ],
            "jd_sha256": self.jd_sha256,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class YoeDecision:
    action: str
    policy_version: str
    threshold_years: int
    reason: str
    evidence_fact_ids: tuple[str, ...]
    evidence_quotes: tuple[str, ...]
    candidate_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class AlternativeApplicability:
    status: str
    candidate_fact_ids: tuple[str, ...]


def _object(value: Any, keys: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExtractionValidationError(f"{path} must be an object")
    present = set(value)
    if present - keys:
        raise ExtractionValidationError(f"{path} contains an unknown field")
    if keys - present:
        raise ExtractionValidationError(f"{path} is missing a required field")
    return value


def _year_bound(value: Any, path: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ExtractionValidationError(f"{path} must be a non-negative integer or null")
    return value


def extraction_from_value(value: Any, jd_text: str) -> JdExtraction:
    """Validate a closed extractor schema and verify every quote against the JD."""
    if not isinstance(jd_text, str):
        raise ExtractionValidationError("job description must be text")
    payload = _object(value, _EXTRACTION_KEYS, "extraction")
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise ExtractionValidationError("extraction.schema must equal integer 1")
    coverage = payload["coverage"]
    if not isinstance(coverage, str) or coverage not in _COVERAGE:
        raise ExtractionValidationError("extraction.coverage is invalid")
    raw_facts = payload["facts"]
    if not isinstance(raw_facts, list):
        raise ExtractionValidationError("extraction.facts must be an array")

    facts: list[ExtractedFact] = []
    seen_fact_ids: set[str] = set()
    for index, raw in enumerate(raw_facts):
        path = f"extraction.facts[{index}]"
        item = _object(raw, _FACT_KEYS, path)
        fact_id = item["id"]
        if not isinstance(fact_id, str) or not _FACT_ID_RE.fullmatch(fact_id):
            raise ExtractionValidationError(f"{path}.id is invalid")
        if fact_id in seen_fact_ids:
            raise ExtractionValidationError("extracted fact IDs must be unique")
        seen_fact_ids.add(fact_id)
        quote, start, end = item["quote"], item["start"], item["end"]
        if not isinstance(quote, str) or not quote:
            raise ExtractionValidationError(f"{path}.quote must be non-empty text")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ExtractionValidationError(f"{path} has invalid source offsets")
        if end > len(jd_text) or jd_text[start:end] != quote:
            raise ExtractionValidationError(f"{path} quote does not match the JD source span")

        category, strength = item["category"], item["strength"]
        kind = item["experience_kind"]
        if not isinstance(category, str) or category not in _CATEGORIES:
            raise ExtractionValidationError(f"{path}.category is invalid")
        if not isinstance(strength, str) or strength not in _STRENGTHS:
            raise ExtractionValidationError(f"{path}.strength is invalid")
        if not isinstance(kind, str) or kind not in _EXPERIENCE_KINDS:
            raise ExtractionValidationError(f"{path}.experience_kind is invalid")
        minimum = _year_bound(item["minimum_years"], f"{path}.minimum_years")
        maximum = _year_bound(item["maximum_years"], f"{path}.maximum_years")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ExtractionValidationError(f"{path} has a reversed year range")
        if category == "experience":
            if kind == "not_experience":
                raise ExtractionValidationError(f"{path} experience_kind contradicts category")
        elif kind != "not_experience" or minimum is not None or maximum is not None:
            raise ExtractionValidationError(f"{path} has experience data outside an experience fact")

        group_id = item["alternative_group_id"]
        if group_id is not None and (
            not isinstance(group_id, str) or not _FACT_ID_RE.fullmatch(group_id)
        ):
            raise ExtractionValidationError(f"{path}.alternative_group_id is invalid")
        facts.append(
            ExtractedFact(
                fact_id,
                quote,
                start,
                end,
                category,
                strength,
                kind,
                minimum,
                maximum,
                group_id,
            )
        )

    raw_groups = payload["alternative_groups"]
    if not isinstance(raw_groups, list):
        raise ExtractionValidationError("extraction.alternative_groups must be an array")
    groups: list[AlternativeGroup] = []
    seen_group_ids: set[str] = set()
    assigned_fact_ids: set[str] = set()
    for index, raw in enumerate(raw_groups):
        path = f"extraction.alternative_groups[{index}]"
        group = _object(raw, {"id", "fact_ids"}, path)
        group_id, raw_ids = group["id"], group["fact_ids"]
        if not isinstance(group_id, str) or not _FACT_ID_RE.fullmatch(group_id):
            raise ExtractionValidationError(f"{path}.id is invalid")
        if group_id in seen_group_ids:
            raise ExtractionValidationError("alternative group IDs must be unique")
        seen_group_ids.add(group_id)
        if not isinstance(raw_ids, list) or len(raw_ids) < 2:
            raise ExtractionValidationError(f"{path}.fact_ids must contain at least two facts")
        if any(not isinstance(item, str) or item not in seen_fact_ids for item in raw_ids):
            raise ExtractionValidationError(f"{path}.fact_ids references an unknown fact")
        if len(set(raw_ids)) != len(raw_ids):
            raise ExtractionValidationError(f"{path}.fact_ids contains duplicates")
        if assigned_fact_ids.intersection(raw_ids):
            raise ExtractionValidationError("a fact cannot belong to multiple alternative groups")
        assigned_fact_ids.update(raw_ids)
        groups.append(AlternativeGroup(group_id, tuple(raw_ids)))

    group_membership = {
        fact_id: group.id for group in groups for fact_id in group.fact_ids
    }
    for fact in facts:
        if fact.alternative_group_id != group_membership.get(fact.id):
            raise ExtractionValidationError("alternative group membership is inconsistent")
    return JdExtraction(
        coverage,
        tuple(facts),
        tuple(groups),
        hashlib.sha256(jd_text.encode("utf-8")).hexdigest(),
    )


def evaluate_required_yoe(
    extraction: JdExtraction,
    *,
    profile: CandidateProfile,
    threshold_years: int,
    policy_version: str,
    alternative_applicability: Mapping[str, AlternativeApplicability | Mapping[str, Any]],
) -> YoeDecision:
    """Apply an explicit mandatory professional-experience floor without guessing.

    `lower_yoe_path_applicable` is a separately supported candidate-fact determination.
    Missing/unknown applicability remains unresolved and never creates an exclusion.
    """
    if type(threshold_years) is not int or threshold_years <= 0:
        raise YoePolicyError("threshold_years must be a positive integer")
    if (
        not isinstance(policy_version, str)
        or not policy_version.strip()
        or policy_version.strip() != policy_version
    ):
        raise YoePolicyError("policy_version must be non-empty")
    if not isinstance(alternative_applicability, Mapping):
        raise YoePolicyError("alternative_applicability must be a mapping")
    if not isinstance(profile, CandidateProfile):
        raise YoePolicyError("candidate profile must be validated before alternative matching")

    group_ids = {group.id for group in extraction.alternative_groups}
    normalized_applicability: dict[str, AlternativeApplicability] = {}
    known_candidate_facts = {block.id for block in profile.background}
    for group_id, raw_status in alternative_applicability.items():
        if group_id not in group_ids:
            raise YoePolicyError("alternative-applicability data does not match this extraction")
        if isinstance(raw_status, AlternativeApplicability):
            applicability = raw_status
        elif isinstance(raw_status, Mapping) and set(raw_status) == {
            "status",
            "candidate_fact_ids",
        }:
            raw_fact_ids = raw_status["candidate_fact_ids"]
            if not isinstance(raw_fact_ids, (list, tuple)):
                raise YoePolicyError("candidate_fact_ids must be an array")
            applicability = AlternativeApplicability(raw_status["status"], tuple(raw_fact_ids))
        else:
            raise YoePolicyError("alternative applicability must include status and candidate facts")
        if not isinstance(applicability.status, str) or applicability.status not in _ALTERNATIVE_STATES:
            raise YoePolicyError("alternative applicability status is invalid")
        if any(not isinstance(fact_id, str) for fact_id in applicability.candidate_fact_ids):
            raise YoePolicyError("candidate fact IDs must be text")
        if len(set(applicability.candidate_fact_ids)) != len(applicability.candidate_fact_ids):
            raise YoePolicyError("candidate fact IDs must be unique")
        if not set(applicability.candidate_fact_ids) <= known_candidate_facts:
            raise YoePolicyError("alternative refers to a fact outside the candidate background")
        if applicability.status == "lower_yoe_path_applicable" and not applicability.candidate_fact_ids:
            raise YoePolicyError("an applicable lower-YOE path requires candidate fact evidence")
        if applicability.status != "lower_yoe_path_applicable" and applicability.candidate_fact_ids:
            raise YoePolicyError("candidate fact evidence is only valid for an applicable path")
        normalized_applicability[group_id] = applicability

    def decision(
        action: str,
        reason: str,
        facts: list[ExtractedFact],
        candidate_fact_ids: tuple[str, ...] = (),
    ) -> YoeDecision:
        return YoeDecision(
            action,
            policy_version,
            threshold_years,
            reason,
            tuple(fact.id for fact in facts),
            tuple(fact.quote for fact in facts),
            candidate_fact_ids,
        )

    if extraction.coverage != "complete":
        return decision("unresolved", "extraction_coverage_incomplete_or_unknown", [])

    threshold_candidates: list[ExtractedFact] = []
    uncertain_candidates: list[ExtractedFact] = []
    for fact in extraction.facts:
        if fact.category != "experience":
            continue
        if fact.experience_kind == "professional_relevant":
            if fact.strength == "required" and fact.minimum_years is not None:
                if fact.minimum_years >= threshold_years:
                    threshold_candidates.append(fact)
            elif fact.strength == "ambiguous":
                uncertain_candidates.append(fact)
            elif (
                fact.strength == "required"
                and fact.minimum_years is None
                and (fact.maximum_years is None or fact.maximum_years > threshold_years)
            ):
                uncertain_candidates.append(fact)
        elif (
            fact.experience_kind == "unknown"
            and fact.strength == "required"
            and fact.minimum_years is not None
            and fact.minimum_years >= threshold_years
        ):
            uncertain_candidates.append(fact)

    if uncertain_candidates:
        return decision("unresolved", "experience_scope_or_floor_is_uncertain", uncertain_candidates)
    if not threshold_candidates:
        return decision("not_excluded", "no_supported_mandatory_floor_at_threshold", [])

    group_by_fact = {
        fact_id: group.id for group in extraction.alternative_groups for fact_id in group.fact_ids
    }
    remaining_blockers: list[ExtractedFact] = []
    unresolved_alternatives: list[ExtractedFact] = []
    applicable_candidate_fact_ids: set[str] = set()
    for fact in threshold_candidates:
        group_id = group_by_fact.get(fact.id)
        if group_id is None:
            remaining_blockers.append(fact)
            continue
        applicability = normalized_applicability.get(
            group_id, AlternativeApplicability("unknown", ())
        )
        if applicability.status == "lower_yoe_path_applicable":
            applicable_candidate_fact_ids.update(applicability.candidate_fact_ids)
            continue
        if applicability.status == "unknown":
            unresolved_alternatives.append(fact)
        else:
            remaining_blockers.append(fact)

    if unresolved_alternatives:
        return decision(
            "unresolved", "lower_yoe_alternative_applicability_unknown", unresolved_alternatives
        )
    if remaining_blockers:
        return decision("exclude", "supported_mandatory_professional_floor", remaining_blockers)
    return decision(
        "not_excluded",
        "applicable_lower_yoe_alternative",
        threshold_candidates,
        tuple(sorted(applicable_candidate_fact_ids)),
    )
