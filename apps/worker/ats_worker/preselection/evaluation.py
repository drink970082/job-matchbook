"""Offline, aggregate-only evaluation reports for an explicitly frozen preselection run.

The input contains pseudonymous work-item hashes, human labels and validated outcomes.
This module does not call models, choose thresholds, or record a GO decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import itertools
import json
import math
import re
import statistics
from typing import Any

from ats_worker.preselection.shadow import AttemptJournal, AttemptRecord, RunBinding


class EvaluationValidationError(ValueError):
    """A frozen evaluation cohort, result set or attempt journal is inconsistent."""


_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_FIELD_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_VARIANTS = {"direct", "extracted"}
_LABELS = {"positive", "negative", "unresolved"}
_SPLITS = {"development", "held_out"}
_ACTIONS = {"exclude", "not_excluded", "unresolved"}
_RUN_KEYS = {
    "run_id",
    "protocol_version",
    "phase",
    "pool_fingerprint_sha256",
    "split_algorithm",
    "split_seed",
    "profile_sha256",
    "question_set_sha256",
    "label_guide_sha256",
    "labeling_blinded",
    "split_manifest_sha256",
    "selection_policy_version",
    "attempt_limits_identity_sha256",
    "model_identities",
    "variants",
    "draw_numbers",
    "budgets",
    "field_ids",
}
_ITEM_KEYS = {
    "work_item_identity_sha256",
    "pool_id_sha256",
    "group_id",
    "split",
    "draw_numbers",
    "observed_at",
    "label",
    "label_source",
    "label_evidence_sha256",
    "role_families",
    "field_labels",
    "yoe_expected_action",
}
_OUTCOME_KEYS = {
    "work_item_identity_sha256",
    "pool_occurrence_identity_sha256",
    "variant",
    "draw_number",
    "status",
    "request_stage",
    "request_identity_sha256",
    "priority_rank",
    "answers",
    "yoe_action",
}
_TOP_KEYS = {"schema", "run", "items", "baseline_orders", "assessments"}


@dataclass(frozen=True)
class EvaluationItem:
    work_item_identity_sha256: str
    pool_occurrence_identity_sha256: str
    pool_id_sha256: str
    group_id: str
    split: str
    draw_numbers: tuple[int, ...]
    observed_at: datetime
    label: str
    label_source: str
    label_evidence_sha256: str
    role_families: tuple[str, ...]
    field_labels: dict[str, Any]
    yoe_expected_action: str | None


@dataclass(frozen=True)
class AssessmentOutcome:
    work_item_identity_sha256: str
    pool_occurrence_identity_sha256: str
    variant: str
    draw_number: int
    status: str
    request_stage: str
    request_identity_sha256: str | None
    priority_rank: int | None
    answers: dict[str, Any]
    yoe_action: str | None


@dataclass(frozen=True)
class EvaluationInput:
    run: dict[str, Any]
    items: tuple[EvaluationItem, ...]
    baseline_ranks: dict[str, dict[str, dict[str, int]]]
    assessments: tuple[AssessmentOutcome, ...]
    manifest_sha256: str
    run_binding: RunBinding
    source_json: str = field(repr=False)


def _object(value: Any, keys: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise EvaluationValidationError(f"{path} has an invalid object shape")
    return value


def _text(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise EvaluationValidationError(f"{path} must be non-empty trimmed text")
    return value


def _sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise EvaluationValidationError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _pool_occurrence_identity(pool_id: str, work_item: str) -> str:
    return _canonical_sha256(
        {"pool_id_sha256": pool_id, "work_item_identity_sha256": work_item}
    )


def _timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationValidationError(f"{path} must be a timezone-aware ISO-8601 timestamp")
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        offset = parsed.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise EvaluationValidationError(f"{path} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or offset is None:
        raise EvaluationValidationError(f"{path} must include a timezone")
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise EvaluationValidationError(f"{path} must be a timezone-aware ISO-8601 timestamp") from exc


def _answer_value(value: Any, path: str) -> Any:
    if isinstance(value, str):
        return _text(value, path)
    if type(value) is int:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        checked = [_text(item, f"{path}[]") for item in value]
        if len(set(checked)) != len(checked):
            raise EvaluationValidationError(f"{path} contains duplicate values")
        return checked
    raise EvaluationValidationError(f"{path} must be a finite scalar or unique string array")


def _model_identity(value: Any, path: str) -> dict[str, str]:
    identity = _object(value, {"provider", "requested_model", "resolved_model"}, path)
    return {key: _text(identity[key], f"{path}.{key}") for key in identity}


def verified_execution_inputs(dataset: EvaluationInput) -> tuple[dict[str, Any], tuple[EvaluationItem, ...]]:
    """Recheck mutable/derived validated inputs against the retained frozen binding."""
    if not isinstance(dataset, EvaluationInput):
        raise EvaluationValidationError("validated frozen cohort required")
    # Snapshot nested dictionaries/lists before hashing and using execution declarations.
    import copy
    run, items = copy.deepcopy((dataset.run, dataset.items))
    try:
        binding = _execution_binding(run, items)
        if binding != dataset.run_binding:
            raise EvaluationValidationError("frozen cohort content differs from its run binding")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise EvaluationValidationError("frozen cohort content differs from its run binding") from exc
    return run, items


def _execution_binding(run, items) -> RunBinding:
    frozen_items = [
        {
            "work_item_identity_sha256": item.work_item_identity_sha256,
            "pool_occurrence_identity_sha256": item.pool_occurrence_identity_sha256,
            "pool_id_sha256": item.pool_id_sha256,
            "group_id": item.group_id,
            "split": item.split,
            "draw_numbers": list(item.draw_numbers),
            "observed_at": item.observed_at.isoformat().replace("+00:00", "Z"),
            "label": item.label,
            "label_source": item.label_source,
            "label_evidence_sha256": item.label_evidence_sha256,
            "role_families": list(item.role_families),
            "field_labels": item.field_labels,
            "yoe_expected_action": item.yoe_expected_action,
        }
        for item in sorted(items, key=lambda row: row.pool_occurrence_identity_sha256)
    ]
    computed_pool_fingerprint = _canonical_sha256(frozen_items)
    computed_split_manifest = _canonical_sha256(
        {
            "split_algorithm": run["split_algorithm"],
            "split_seed": run["split_seed"],
            "occurrences": [
                {
                    "pool_occurrence_identity_sha256": item["pool_occurrence_identity_sha256"],
                    "pool_id_sha256": item["pool_id_sha256"],
                    "group_id": item["group_id"],
                    "split": item["split"],
                }
                for item in frozen_items
            ],
        }
    )
    if run["pool_fingerprint_sha256"] != computed_pool_fingerprint:
        raise EvaluationValidationError("run pool fingerprint differs from validated frozen items")
    if run["split_manifest_sha256"] != computed_split_manifest:
        raise EvaluationValidationError("run split manifest differs from validated frozen groups and pools")
    declaration = dict(run)
    for key in ("variants", "draw_numbers", "budgets", "field_ids"):
        declaration[key] = list(declaration[key])
    return RunBinding(
        run_id=run["run_id"],
        run_declaration_sha256=_canonical_sha256(declaration),
        profile_sha256=run["profile_sha256"],
        question_set_sha256=run["question_set_sha256"],
        pool_fingerprint_sha256=computed_pool_fingerprint,
        split_manifest_sha256=computed_split_manifest,
    )



def evaluation_from_value(value: Any) -> EvaluationInput:
    """Validate a closed, pseudonymous evaluation-input format."""
    payload = _object(value, _TOP_KEYS, "evaluation")
    try:
        manifest_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EvaluationValidationError("evaluation manifest cannot be canonically encoded") from exc
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise EvaluationValidationError("evaluation.schema must equal integer 1")

    raw_run = _object(payload["run"], _RUN_KEYS, "evaluation.run")
    run = {key: raw_run[key] for key in _RUN_KEYS}
    for key in (
        "run_id",
        "protocol_version",
        "split_algorithm",
        "split_seed",
        "selection_policy_version",
    ):
        run[key] = _text(run[key], f"evaluation.run.{key}")
    for key in (
        "pool_fingerprint_sha256",
        "profile_sha256",
        "question_set_sha256",
        "label_guide_sha256",
        "split_manifest_sha256",
        "attempt_limits_identity_sha256",
    ):
        run[key] = _sha256(run[key], f"evaluation.run.{key}")
    if not isinstance(run["phase"], str) or run["phase"] not in {"pilot", "development", "held_out"}:
        raise EvaluationValidationError("evaluation.run.phase is invalid")

    variants = run["variants"]
    if (
        not isinstance(variants, list)
        or not variants
        or any(not isinstance(variant, str) or variant not in _VARIANTS for variant in variants)
        or len(set(variants)) != len(variants)
    ):
        raise EvaluationValidationError("evaluation.run.variants is invalid")
    run["variants"] = tuple(variants)
    if set(variants) != _VARIANTS:
        raise EvaluationValidationError("evaluation.run must declare both direct and extracted arms")

    def positive_integers(raw: Any, path: str) -> tuple[int, ...]:
        if (
            not isinstance(raw, list)
            or not raw
            or any(type(value) is not int or value <= 0 for value in raw)
            or len(set(raw)) != len(raw)
        ):
            raise EvaluationValidationError(f"{path} must contain unique positive integers")
        return tuple(sorted(raw))

    run["draw_numbers"] = positive_integers(run["draw_numbers"], "evaluation.run.draw_numbers")
    run["budgets"] = positive_integers(run["budgets"], "evaluation.run.budgets")
    if not isinstance(run["labeling_blinded"], bool):
        raise EvaluationValidationError("evaluation.run.labeling_blinded must be boolean")
    field_ids = run["field_ids"]
    if (
        not isinstance(field_ids, list)
        or not field_ids
        or any(not isinstance(field_id, str) or _FIELD_ID_RE.fullmatch(field_id) is None for field_id in field_ids)
        or len(set(field_ids)) != len(field_ids)
    ):
        raise EvaluationValidationError("evaluation.run.field_ids is invalid")
    run["field_ids"] = tuple(field_ids)

    expected_models = set(variants)
    if "extracted" in variants:
        expected_models.add("extract")
    raw_models = _object(run["model_identities"], expected_models, "evaluation.run.model_identities")
    run["model_identities"] = {
        variant: _model_identity(raw_models[variant], f"evaluation.run.model_identities.{variant}")
        for variant in sorted(expected_models)
    }

    raw_items = payload["items"]
    if not isinstance(raw_items, list) or not raw_items:
        raise EvaluationValidationError("evaluation.items must be a non-empty array")
    items: list[EvaluationItem] = []
    seen_occurrences: set[str] = set()
    group_splits: dict[str, set[str]] = {}
    pool_splits: dict[str, set[str]] = {}
    work_item_splits: dict[str, set[str]] = {}
    for index, raw_item in enumerate(raw_items):
        path = f"evaluation.items[{index}]"
        row = _object(raw_item, _ITEM_KEYS, path)
        work_item = _sha256(row["work_item_identity_sha256"], f"{path}.work_item_identity_sha256")
        pool_id = _sha256(row["pool_id_sha256"], f"{path}.pool_id_sha256")
        occurrence = _pool_occurrence_identity(pool_id, work_item)
        if occurrence in seen_occurrences:
            raise EvaluationValidationError("evaluation pool-occurrence identities must be unique")
        seen_occurrences.add(occurrence)
        group_id = _text(row["group_id"], f"{path}.group_id")
        split = row["split"]
        if not isinstance(split, str) or split not in _SPLITS:
            raise EvaluationValidationError(f"{path}.split is invalid")
        group_splits.setdefault(group_id, set()).add(split)
        pool_splits.setdefault(pool_id, set()).add(split)
        work_item_splits.setdefault(work_item, set()).add(split)
        item_draws = positive_integers(row["draw_numbers"], f"{path}.draw_numbers")
        if not set(item_draws) <= set(run["draw_numbers"]) or run["draw_numbers"][0] not in item_draws:
            raise EvaluationValidationError(f"{path}.draw_numbers must include the initial draw and use declared draws")
        observed_at = _timestamp(row["observed_at"], f"{path}.observed_at")
        label = row["label"]
        if not isinstance(label, str) or label not in _LABELS:
            raise EvaluationValidationError(f"{path}.label is invalid")
        label_source = row["label_source"]
        allowed_sources = {"human_single", "human_adjudicated", "human_unresolved", "synthetic_fixture"}
        if not isinstance(label_source, str) or label_source not in allowed_sources:
            raise EvaluationValidationError(f"{path}.label_source must identify human review")
        if label == "unresolved" and label_source not in {
            "human_single",
            "human_unresolved",
            "human_adjudicated",
            "synthetic_fixture",
        }:
            raise EvaluationValidationError(f"{path}.unresolved label source is invalid")
        if label != "unresolved" and label_source == "human_unresolved":
            raise EvaluationValidationError(f"{path}.resolved label cannot use human_unresolved source")
        label_evidence = _sha256(row["label_evidence_sha256"], f"{path}.label_evidence_sha256")
        role_families = row["role_families"]
        if not isinstance(role_families, list):
            raise EvaluationValidationError(f"{path}.role_families is invalid")
        role_families = [_text(role, f"{path}.role_families[]") for role in role_families]
        if len(set(role_families)) != len(role_families):
            raise EvaluationValidationError(f"{path}.role_families contains duplicates")
        field_labels = row["field_labels"]
        if not isinstance(field_labels, dict) or not set(field_labels) <= set(field_ids):
            raise EvaluationValidationError(f"{path}.field_labels has unknown or invalid fields")
        checked_labels = {
            field_id: _answer_value(label_value, f"{path}.field_labels.{field_id}")
            for field_id, label_value in field_labels.items()
        }
        yoe_expected = row["yoe_expected_action"]
        if yoe_expected is not None and (
            not isinstance(yoe_expected, str) or yoe_expected not in _ACTIONS
        ):
            raise EvaluationValidationError(f"{path}.yoe_expected_action is invalid")
        items.append(
            EvaluationItem(
                work_item,
                occurrence,
                pool_id,
                group_id,
                split,
                item_draws,
                observed_at,
                label,
                label_source,
                label_evidence,
                tuple(role_families),
                checked_labels,
                yoe_expected,
            )
        )
    if any(len(splits) > 1 for splits in group_splits.values()):
        raise EvaluationValidationError("a shared group cannot cross development and held-out splits")
    if any(len(splits) > 1 for splits in pool_splits.values()):
        raise EvaluationValidationError("a complete daily pool cannot cross development and held-out splits")
    if any(len(splits) > 1 for splits in work_item_splits.values()):
        raise EvaluationValidationError("a stable work item cannot cross development and held-out splits")
    label_sources = {item.label_source for item in items}
    if "synthetic_fixture" in label_sources:
        if label_sources != {"synthetic_fixture"} or run["labeling_blinded"]:
            raise EvaluationValidationError("synthetic fixtures must be isolated and cannot claim human blinding")
    elif not run["labeling_blinded"]:
        raise EvaluationValidationError("human labels must be attested as blind to assessment outputs")

    run_binding = _execution_binding(run, items)

    items_by_occurrence = {item.pool_occurrence_identity_sha256: item for item in items}
    pool_work_items: dict[str, set[str]] = {}
    for item in items:
        pool_work_items.setdefault(item.pool_id_sha256, set()).add(item.pool_occurrence_identity_sha256)
    raw_baseline_orders = payload["baseline_orders"]
    if not isinstance(raw_baseline_orders, list) or not raw_baseline_orders:
        raise EvaluationValidationError("evaluation.baseline_orders must cover the frozen daily pools")
    baseline_ranks: dict[str, dict[str, dict[str, int]]] = {}
    daily_brief_pools: set[str] = set()
    for index, raw_order in enumerate(raw_baseline_orders):
        path = f"evaluation.baseline_orders[{index}]"
        if not isinstance(raw_order, dict) or not {"pool_id_sha256", "recency", "role_coverage"} <= set(raw_order):
            raise EvaluationValidationError(f"{path} is missing required baseline orders")
        if set(raw_order) - {"pool_id_sha256", "recency", "role_coverage", "daily_brief"}:
            raise EvaluationValidationError(f"{path} contains an unknown baseline")
        pool_id = _sha256(raw_order["pool_id_sha256"], f"{path}.pool_id_sha256")
        if pool_id not in pool_work_items or pool_id in baseline_ranks:
            raise EvaluationValidationError(f"{path} references an unknown or duplicate daily pool")
        baseline_ranks[pool_id] = {}
        expected_items = pool_work_items[pool_id]
        for name in ("recency", "role_coverage", "daily_brief"):
            if name not in raw_order:
                continue
            order = raw_order[name]
            if not isinstance(order, list):
                raise EvaluationValidationError(f"{path}.{name} must be an array of pseudonymous item hashes")
            checked_order = [_sha256(occurrence, f"{path}.{name}[{row_index}]") for row_index, occurrence in enumerate(order)]
            if len(set(checked_order)) != len(checked_order) or not set(checked_order) <= expected_items:
                raise EvaluationValidationError(f"{path}.{name} contains duplicate or foreign pool occurrences")
            if name in {"recency", "role_coverage"} and set(checked_order) != expected_items:
                raise EvaluationValidationError(f"{path}.{name} must rank every occurrence in the complete daily pool")
            if name == "daily_brief":
                daily_brief_pools.add(pool_id)
            baseline_ranks[pool_id][name] = {
                occurrence: rank for rank, occurrence in enumerate(checked_order, start=1)
            }
    if set(baseline_ranks) != set(pool_work_items):
        raise EvaluationValidationError("baseline orders must cover every frozen daily pool")
    if daily_brief_pools and daily_brief_pools != set(pool_work_items):
        raise EvaluationValidationError("Daily Brief baseline must be supplied for every daily pool or none")
    items_by_pool: dict[str, list[EvaluationItem]] = {}
    for item in items:
        items_by_pool.setdefault(item.pool_id_sha256, []).append(item)
    for pool_id, pool_items in items_by_pool.items():
        recency_order = sorted(
            pool_items,
            key=lambda item: (-item.observed_at.timestamp(), item.pool_occurrence_identity_sha256),
        )
        expected_recency = [item.pool_occurrence_identity_sha256 for item in recency_order]
        supplied_recency = sorted(
            baseline_ranks[pool_id]["recency"], key=baseline_ranks[pool_id]["recency"].get
        )
        if supplied_recency != expected_recency:
            raise EvaluationValidationError("recency baseline order differs from the frozen timestamps")
        remaining = {role for item in pool_items for role in item.role_families}
        pending = list(pool_items)
        expected_role_coverage = []
        while pending:
            chosen = min(
                pending,
                key=lambda item: (
                    -len(remaining.intersection(item.role_families)),
                    -item.observed_at.timestamp(),
                    item.pool_occurrence_identity_sha256,
                ),
            )
            expected_role_coverage.append(chosen.pool_occurrence_identity_sha256)
            remaining.difference_update(chosen.role_families)
            pending.remove(chosen)
        supplied_role_coverage = sorted(
            baseline_ranks[pool_id]["role_coverage"],
            key=baseline_ranks[pool_id]["role_coverage"].get,
        )
        if supplied_role_coverage != expected_role_coverage:
            raise EvaluationValidationError("role-coverage baseline order differs from frozen features")

    raw_assessments = payload["assessments"]
    if not isinstance(raw_assessments, list):
        raise EvaluationValidationError("evaluation.assessments must be an array")
    assessments: list[AssessmentOutcome] = []
    seen_outcomes: set[tuple[str, str, int]] = set()
    known_occurrences = set(items_by_occurrence)
    for index, raw_outcome in enumerate(raw_assessments):
        path = f"evaluation.assessments[{index}]"
        row = _object(raw_outcome, _OUTCOME_KEYS, path)
        work_item = _sha256(row["work_item_identity_sha256"], f"{path}.work_item_identity_sha256")
        occurrence = _sha256(
            row["pool_occurrence_identity_sha256"], f"{path}.pool_occurrence_identity_sha256"
        )
        item = items_by_occurrence.get(occurrence)
        variant = row["variant"]
        draw = row["draw_number"]
        if (
            occurrence not in known_occurrences
            or item is None
            or item.work_item_identity_sha256 != work_item
            or not isinstance(variant, str)
            or variant not in variants
            or type(draw) is not int
            or draw not in run["draw_numbers"]
        ):
            raise EvaluationValidationError(f"{path} references an undeclared item, variant or draw")
        if draw not in item.draw_numbers:
            raise EvaluationValidationError(f"{path} references a draw not planned for this pool occurrence")
        unique_key = (occurrence, variant, draw)
        if unique_key in seen_outcomes:
            raise EvaluationValidationError("duplicate assessment outcome for a pool occurrence, variant and draw")
        seen_outcomes.add(unique_key)
        status = row["status"]
        if not isinstance(status, str) or status not in {"completed", "unresolved", "failed"}:
            raise EvaluationValidationError(f"{path}.status is invalid")
        request_stage = row["request_stage"]
        if not isinstance(request_stage, str) or request_stage not in {"assess", "extract_jd"}:
            raise EvaluationValidationError(f"{path}.request_stage is invalid")
        if request_stage == "extract_jd" and (variant != "extracted" or status == "completed"):
            raise EvaluationValidationError(f"{path} extraction-stage outcome must be unresolved or failed in the extracted arm")
        request_identity = row["request_identity_sha256"]
        if request_identity is not None:
            request_identity = _sha256(request_identity, f"{path}.request_identity_sha256")
        else:
            raise EvaluationValidationError(f"{path} outcome requires a journal request identity")
        rank = row["priority_rank"]
        answers = row["answers"]
        if status == "completed":
            if request_stage != "assess" or type(rank) is not int or rank <= 0:
                raise EvaluationValidationError(f"{path} completed result lacks request identity or valid rank")
            if not isinstance(answers, dict) or set(answers) != set(field_ids):
                raise EvaluationValidationError(f"{path}.answers must exactly match declared field IDs")
            checked_answers = {
                field_id: _answer_value(answer, f"{path}.answers.{field_id}")
                for field_id, answer in answers.items()
            }
        else:
            if rank is not None or answers != {}:
                raise EvaluationValidationError(f"{path} unresolved/failed result cannot carry a rank or answers")
            checked_answers = {}
        yoe_action = row["yoe_action"]
        if yoe_action is not None and (not isinstance(yoe_action, str) or yoe_action not in _ACTIONS):
            raise EvaluationValidationError(f"{path}.yoe_action is invalid")
        if status != "completed" and yoe_action not in {None, "unresolved"}:
            raise EvaluationValidationError(f"{path} unresolved/failed result cannot assert a YOE action")
        assessments.append(
            AssessmentOutcome(
                work_item,
                occurrence,
                variant,
                draw,
                status,
                request_stage,
                request_identity,
                rank,
                checked_answers,
                yoe_action,
            )
        )

    pool_sizes: dict[str, int] = {}
    item_by_occurrence: dict[str, EvaluationItem] = {}
    for item in items:
        pool_sizes[item.pool_id_sha256] = pool_sizes.get(item.pool_id_sha256, 0) + 1
        item_by_occurrence[item.pool_occurrence_identity_sha256] = item
    ranks_by_arm: dict[tuple[str, str, int], set[int]] = {}
    for outcome in assessments:
        if outcome.priority_rank is None:
            continue
        item = item_by_occurrence[outcome.pool_occurrence_identity_sha256]
        if outcome.priority_rank > pool_sizes[item.pool_id_sha256]:
            raise EvaluationValidationError("priority rank exceeds its frozen daily-pool size")
        ranks = ranks_by_arm.setdefault((item.pool_id_sha256, outcome.variant, outcome.draw_number), set())
        if outcome.priority_rank in ranks:
            raise EvaluationValidationError("priority ranks must have deterministic tie breaks within each draw")
        ranks.add(outcome.priority_rank)
    if run["phase"] == "held_out" and not any(item.split == "held_out" for item in items):
        raise EvaluationValidationError("held-out phase requires a held-out cohort")
    if run["phase"] == "development" and not any(item.split == "development" for item in items):
        raise EvaluationValidationError("development phase requires a development cohort")

    return EvaluationInput(run, tuple(items), baseline_ranks, tuple(assessments), manifest_sha256, run_binding,
                           manifest_bytes.decode("utf-8"))


def load_evaluation_text(source: str) -> EvaluationInput:
    """Decode an evaluation input while rejecting duplicate JSON members."""
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvaluationValidationError("duplicate JSON object member")
            result[key] = value
        return result

    try:
        return evaluation_from_value(json.loads(source, object_pairs_hook=reject_duplicates))
    except EvaluationValidationError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise EvaluationValidationError("evaluation input is not valid JSON") from exc


def _canonical(value: Any) -> str:
    if isinstance(value, list):
        value = sorted(value, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _wilson_interval(successes: int, total: int) -> dict[str, float] | None:
    """Return a descriptive 95% Wilson interval; this is not a GO threshold."""
    if total <= 0:
        return None
    z = 1.959963984540054
    observed = successes / total
    denominator = 1 + z * z / total
    center = (observed + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(observed * (1 - observed) / total + z * z / (4 * total * total)) / denominator
    return {"lower": round(max(0.0, center - margin), 6), "upper": round(min(1.0, center + margin), 6)}


def _label_counts(items: list[EvaluationItem]) -> dict[str, int]:
    return {label: sum(item.label == label for item in items) for label in ("positive", "negative", "unresolved")}


def _label_source_counts(items: list[EvaluationItem]) -> dict[str, int]:
    sources = sorted({item.label_source for item in items})
    return {source: sum(item.label_source == source for item in items) for source in sources}


def _role_metrics(items: list[EvaluationItem], selected: list[EvaluationItem]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    roles = sorted({role for item in items for role in item.role_families})
    selected_hashes = {item.pool_occurrence_identity_sha256 for item in selected}
    for role in roles:
        role_items = [item for item in items if role in item.role_families]
        positive = sum(item.label == "positive" for item in role_items)
        selected_positive = sum(
            item.label == "positive" and item.pool_occurrence_identity_sha256 in selected_hashes
            for item in role_items
        )
        result[role] = {
            "items": len(role_items),
            "positive_items": positive,
            "positive_selected": selected_positive,
            "positive_recall": _ratio(selected_positive, positive),
        }
    return result


def _budget_metrics(
    items: list[EvaluationItem],
    outcome_by_item: dict[str, AssessmentOutcome],
    budgets: tuple[int, ...],
) -> list[dict[str, Any]]:
    positive_total = sum(item.label == "positive" for item in items)
    rows: list[dict[str, Any]] = []
    for budget in budgets:
        selected = [
            item
            for item in items
            if (outcome := outcome_by_item.get(item.pool_occurrence_identity_sha256)) is not None
            and outcome.status == "completed"
            and outcome.priority_rank is not None
            and outcome.priority_rank <= budget
        ]
        labels = _label_counts(selected)
        selected_occurrences = {item.pool_occurrence_identity_sha256 for item in selected}
        unselected_items = [item for item in items if item.pool_occurrence_identity_sha256 not in selected_occurrences]
        unselected_reasons = {
            "ranked_beyond_budget": 0,
            "unresolved_assessment": 0,
            "failed_assessment": 0,
            "missing_outcome": 0,
        }
        for item in unselected_items:
            outcome = outcome_by_item.get(item.pool_occurrence_identity_sha256)
            if outcome is None:
                unselected_reasons["missing_outcome"] += 1
            elif outcome.status == "unresolved":
                unselected_reasons["unresolved_assessment"] += 1
            elif outcome.status == "failed":
                unselected_reasons["failed_assessment"] += 1
            else:
                unselected_reasons["ranked_beyond_budget"] += 1
        unselected_labels = _label_counts(unselected_items)
        resolved_selected = labels["positive"] + labels["negative"]
        rows.append(
            {
                "budget": budget,
                "selected_items": len(selected),
                "selected_label_counts": labels,
                "unselected_items": len(unselected_items),
                "unselected_label_counts": unselected_labels,
                "unselected_reason_counts": unselected_reasons,
                "positive_total": positive_total,
                "positive_selected": labels["positive"],
                "positive_misses": positive_total - labels["positive"],
                "positive_recall": _ratio(labels["positive"], positive_total),
                "positive_recall_wilson_95": _wilson_interval(labels["positive"], positive_total),
                "precision_on_resolved_selected": _ratio(labels["positive"], resolved_selected),
                "role_family_metrics": _role_metrics(items, selected),
            }
        )
    return rows


def _baseline_budget_metrics(
    items: list[EvaluationItem],
    ranks_by_pool: dict[str, dict[str, int]],
    budgets: tuple[int, ...],
) -> list[dict[str, Any]]:
    positive_total = sum(item.label == "positive" for item in items)
    rows = []
    for budget in budgets:
        selected = [
            item
            for item in items
            if ranks_by_pool.get(item.pool_id_sha256, {}).get(item.pool_occurrence_identity_sha256, budget + 1)
            <= budget
        ]
        labels = _label_counts(selected)
        selected_ids = {item.pool_occurrence_identity_sha256 for item in selected}
        unselected_labels = _label_counts(
            [item for item in items if item.pool_occurrence_identity_sha256 not in selected_ids]
        )
        resolved_selected = labels["positive"] + labels["negative"]
        rows.append(
            {
                "budget_per_daily_pool": budget,
                "selected_items": len(selected),
                "selected_label_counts": labels,
                "unselected_items": len(items) - len(selected),
                "unselected_label_counts": unselected_labels,
                "positive_total": positive_total,
                "positive_selected": labels["positive"],
                "positive_misses": positive_total - labels["positive"],
                "positive_recall": _ratio(labels["positive"], positive_total),
                "positive_recall_wilson_95": _wilson_interval(labels["positive"], positive_total),
                "precision_on_resolved_selected": _ratio(labels["positive"], resolved_selected),
                "role_family_metrics": _role_metrics(items, selected),
            }
        )
    return rows


def _field_metrics(
    items: list[EvaluationItem], outcome_by_item: dict[str, AssessmentOutcome], field_ids: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for field_id in field_ids:
        labeled = [item for item in items if field_id in item.field_labels]
        correct = 0
        answered = 0
        missing = 0
        for item in labeled:
            outcome = outcome_by_item.get(item.pool_occurrence_identity_sha256)
            if outcome is None or outcome.status != "completed" or field_id not in outcome.answers:
                missing += 1
            else:
                answered += 1
                if _canonical(outcome.answers[field_id]) == _canonical(item.field_labels[field_id]):
                    correct += 1
        metrics[field_id] = {
            "labeled_items": len(labeled),
            "answered_items": answered,
            "unanswered_items": missing,
            "correct": correct,
            "incorrect": answered - correct,
            "accuracy_including_unanswered": _ratio(correct, len(labeled)),
            "accuracy_when_answered": _ratio(correct, answered),
        }
    return metrics


def _yoe_metrics(
    items: list[EvaluationItem], outcome_by_item: dict[str, AssessmentOutcome]
) -> dict[str, Any]:
    labeled = [item for item in items if item.yoe_expected_action is not None]
    correct = 0
    false_exclusions = 0
    answered = 0
    for item in labeled:
        outcome = outcome_by_item.get(item.pool_occurrence_identity_sha256)
        if outcome is None or outcome.status != "completed" or outcome.yoe_action is None:
            continue
        answered += 1
        correct += outcome.yoe_action == item.yoe_expected_action
        false_exclusions += (
            outcome.yoe_action == "exclude"
            and item.yoe_expected_action in {"not_excluded", "unresolved"}
        )
    return {
        "labeled_items": len(labeled),
        "answered_items": answered,
        "unanswered_items": len(labeled) - answered,
        "correct": correct,
        "false_exclusions": false_exclusions,
        "accuracy_including_unanswered": _ratio(correct, len(labeled)),
    }


def _jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return round(len(left & right) / len(union), 6) if union else None


def _stability_metrics(
    items: list[EvaluationItem],
    outcomes_by_draw: dict[int, dict[str, AssessmentOutcome]],
    budgets: tuple[int, ...],
) -> list[dict[str, Any]]:
    result = []
    for budget in budgets:
        overlaps: list[float] = []
        empty_union_pairs = 0
        for left_draw, right_draw in itertools.combinations(sorted(outcomes_by_draw), 2):
            for pool_id in sorted({item.pool_id_sha256 for item in items}):
                pool_items = {
                    item.pool_occurrence_identity_sha256
                    for item in items
                    if item.pool_id_sha256 == pool_id
                    and left_draw in item.draw_numbers
                    and right_draw in item.draw_numbers
                }
                if not pool_items:
                    continue

                def selected(draw: int) -> set[str]:
                    return {
                    occurrence
                        for occurrence, outcome in outcomes_by_draw[draw].items()
                        if occurrence in pool_items
                        and outcome.status == "completed"
                        and outcome.priority_rank is not None
                        and outcome.priority_rank <= budget
                    }

                overlap = _jaccard(selected(left_draw), selected(right_draw))
                if overlap is None:
                    empty_union_pairs += 1
                else:
                    overlaps.append(overlap)
        result.append(
            {
                "budget": budget,
                "pool_draw_pairs": len(overlaps) + empty_union_pairs,
                "measured_nonempty_pairs": len(overlaps),
                "empty_selection_pairs": empty_union_pairs,
                "scope": "predeclared repeated-item overlap; not population stability",
                "mean_top_budget_jaccard": round(sum(overlaps) / len(overlaps), 6) if overlaps else None,
                "minimum_top_budget_jaccard": min(overlaps) if overlaps else None,
                "maximum_top_budget_jaccard": max(overlaps) if overlaps else None,
            }
        )
    return result


def _cost_summary(records: list[AttemptRecord]) -> dict[str, Any]:
    usage_fields = ("input_tokens", "output_tokens", "cached_input_tokens")
    usage = {}
    for field in usage_fields:
        known = [record.usage[field] for record in records if record.usage[field] is not None]
        usage[field] = {"reported_total": sum(known), "unknown_attempts": len(records) - len(known)}
    price_totals: dict[tuple[str, str, str, str, str], Decimal] = {}
    unknown_charges = 0
    for record in records:
        charge = record.charge
        if charge["kind"] == "unknown":
            unknown_charges += 1
            continue
        key = (
            str(charge["kind"]),
            str(charge["currency"]),
            str(charge["billing_unit"]),
            str(charge["rate_date"]),
            str(charge["rate_source"]),
        )
        price_totals[key] = price_totals.get(key, Decimal(0)) + Decimal(str(charge["amount"]))
    success_count = sum(record.stage == "assess" and record.status == "succeeded" for record in records)
    work_items = {record.work_item_identity_sha256 for record in records}
    successful_work_items = {
        record.work_item_identity_sha256
        for record in records
        if record.stage == "assess" and record.status == "succeeded"
    }
    return {
        "attempts": len(records),
        "successful_assessments": success_count,
        "unique_work_items_with_attempts": len(work_items),
        "unique_work_items_with_successful_assessment": len(successful_work_items),
        "retry_attempts": sum(record.retry_of is not None for record in records),
        "attempt_status_counts": {
            status: sum(record.status == status for record in records)
            for status in sorted({record.status for record in records})
        },
        "attempts_by_stage": {
            stage: sum(record.stage == stage for record in records)
            for stage in sorted({record.stage for record in records})
        },
        "elapsed_ms_known_total": sum(
            record.elapsed_ms for record in records if record.elapsed_ms is not None
        ),
        "elapsed_reported_attempts": sum(record.elapsed_ms is not None for record in records),
        "elapsed_unknown_attempts": sum(record.elapsed_ms is None for record in records),
        "reported_usage": usage,
        "charge_totals": [
            {
                "kind": kind,
                "currency": currency,
                "billing_unit": unit,
                "rate_date": rate_date,
                "rate_source": source,
                "amount": str(amount),
            }
            for (kind, currency, unit, rate_date, source), amount in sorted(price_totals.items())
        ],
        "unknown_charge_attempts": unknown_charges,
        "cost_reserve_attempts": sum(record.reserved_charge is not None for record in records),
        "circuit_breaker_attempts": sum(record.circuit_breaker for record in records),
        "reported_actual_amount_per_successful_assessment": [
            {
                "currency": currency,
                "billing_unit": unit,
                "rate_date": rate_date,
                "rate_source": source,
                "amount": str(amount / success_count),
                "successful_assessments": success_count,
            }
            for (kind, currency, unit, rate_date, source), amount in sorted(price_totals.items())
            if kind == "actual" and success_count
        ],
        "reported_actual_amount_per_work_item_with_attempts": [
            {
                "currency": currency,
                "billing_unit": unit,
                "rate_date": rate_date,
                "rate_source": source,
                "amount": str(amount / len(work_items)),
                "work_items_with_attempts": len(work_items),
            }
            for (kind, currency, unit, rate_date, source), amount in sorted(price_totals.items())
            if kind == "actual" and work_items
        ],
    }


def _per_work_item_cost_distribution(records: list[AttemptRecord]) -> dict[str, Any]:
    per_item: dict[str, list[AttemptRecord]] = {}
    for record in records:
        per_item.setdefault(record.work_item_identity_sha256, []).append(record)
    priced_by_rate: dict[tuple[str, str, str, str, str], dict[str, Decimal]] = {}
    for work_item, item_records in per_item.items():
        for record in item_records:
            charge = record.charge
            if charge["kind"] not in {"actual", "estimate"}:
                continue
            key = (
                str(charge["kind"]),
                str(charge["currency"]),
                str(charge["billing_unit"]),
                str(charge["rate_date"]),
                str(charge["rate_source"]),
            )
            item_totals = priced_by_rate.setdefault(key, {})
            item_totals[work_item] = item_totals.get(work_item, Decimal(0)) + Decimal(str(charge["amount"]))
    attempt_counts = [len(item_records) for item_records in per_item.values()]
    return {
        "work_items_with_attempts": len(per_item),
        "work_items_with_unknown_charge": sum(
            any(record.charge["kind"] == "unknown" for record in item_records)
            for item_records in per_item.values()
        ),
        "work_items_with_estimated_charge": sum(
            any(record.charge["kind"] == "estimate" for record in item_records)
            for item_records in per_item.values()
        ),
        "attempts_per_work_item": {
            "minimum": min(attempt_counts) if attempt_counts else None,
            "mean": round(statistics.mean(attempt_counts), 6) if attempt_counts else None,
            "median": statistics.median(attempt_counts) if attempt_counts else None,
            "maximum": max(attempt_counts) if attempt_counts else None,
        },
        "reported_amounts_by_kind_and_rate": [
            {
                "kind": kind,
                "currency": currency,
                "billing_unit": unit,
                "rate_date": rate_date,
                "rate_source": source,
                "work_items_with_reported_amount": len(values),
                "reported_total": str(sum(values.values(), Decimal(0))),
                "mean_per_work_item_with_reported_amount": str(
                    sum(values.values(), Decimal(0)) / len(values)
                ),
                "minimum_per_work_item": str(min(values.values())),
                "maximum_per_work_item": str(max(values.values())),
            }
            for (kind, currency, unit, rate_date, source), values in sorted(priced_by_rate.items())
            if values
        ],
    }


def _attempt_accounting(dataset: EvaluationInput, journal: AttemptJournal) -> dict[str, Any]:
    records = journal.records
    by_arm = {
        "direct": [record for record in records if record.variant == "direct"],
        "extracted": [record for record in records if record.variant in {"extract", "extracted"}],
    }
    successful_request_ids = {
        record.request_identity
        for record in records
        if record.stage == "assess" and record.status == "succeeded"
    }
    extraction_records = [record for record in records if record.stage == "extract_jd"]
    extracted_work_items = {record.work_item_identity_sha256 for record in extraction_records}
    successful_extraction_items = {
        record.work_item_identity_sha256
        for record in extraction_records
        if record.status == "succeeded"
        and isinstance(record.response_payload, dict)
        and record.response_payload.get("coverage") == "complete"
    }
    per_success = {
        variant: [
            record
            for record in records
            if record.stage == "assess"
            and record.variant == variant
            and record.request_identity in successful_request_ids
        ]
        for variant in dataset.run["variants"]
    }
    return {
        "run": _cost_summary(records),
        "extraction_coverage": {
            "work_items_with_extraction_attempts": len(extracted_work_items),
            "work_items_with_successful_extraction": len(successful_extraction_items),
            "failed_or_incomplete_extraction_attempts": sum(
                record.status != "succeeded"
                or not isinstance(record.response_payload, dict)
                or record.response_payload.get("coverage") != "complete"
                for record in extraction_records
            ),
        },
        "per_arm_including_extraction": {
            variant: _cost_summary(arm_records)
            for variant, arm_records in by_arm.items()
            if variant in dataset.run["variants"]
        },
        "per_work_item_cost_distribution": {
            variant: _per_work_item_cost_distribution(arm_records)
            for variant, arm_records in by_arm.items()
            if variant in dataset.run["variants"]
        },
        "attempts_for_successful_assessment_requests": {
            variant: _cost_summary(success_records)
            for variant, success_records in per_success.items()
        },
        "per_stage": {
            stage: _cost_summary([record for record in records if record.stage == stage])
            for stage in sorted({record.stage for record in records})
        },
        "per_draw_assessment_only": {
            str(draw): _cost_summary(
                [record for record in records if record.stage == "assess" and record.draw_number == draw]
            )
            for draw in dataset.run["draw_numbers"]
        },
        "per_arm_draw_assessment_only": {
            variant: {
                str(draw): _cost_summary(
                    [
                        record
                        for record in records
                        if record.stage == "assess"
                        and record.variant == variant
                        and record.draw_number == draw
                    ]
                )
                for draw in dataset.run["draw_numbers"]
            }
            for variant in dataset.run["variants"]
        },
        "promotion_decision": "not_recorded_by_metric_tool",
    }


def _recorded_answer_values(record: AttemptRecord, field_ids: tuple[str, ...]) -> dict[str, Any]:
    payload = record.response_payload
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise EvaluationValidationError("successful assessment journal response has no typed answers object")
    raw_answers = payload["answers"]
    if set(raw_answers) != set(field_ids):
        raise EvaluationValidationError("successful assessment journal answer IDs differ from the frozen question set")
    values: dict[str, Any] = {}
    for field_id in field_ids:
        answer = raw_answers[field_id]
        if not isinstance(answer, dict) or "value" not in answer or not isinstance(answer.get("evidence"), list):
            raise EvaluationValidationError("successful assessment journal answer violates the typed answer shape")
        values[field_id] = _answer_value(answer["value"], f"attempt_journal.response_payload.answers.{field_id}.value")
    return values


def build_evaluation_report(dataset: EvaluationInput, journal: AttemptJournal) -> dict[str, Any]:
    """Join outcomes to the validated #111 journal and report aggregate evidence only."""
    if not isinstance(dataset, EvaluationInput) or not isinstance(journal, AttemptJournal):
        raise EvaluationValidationError("validated evaluation input and AttemptJournal are required")
    # Reparse the retained canonical manifest so every reported field is checked,
    # including labels, baseline ranks and outcomes outside the execution binding.
    try:
        snapshot = load_evaluation_text(dataset.source_json)
        if snapshot != dataset:
            raise EvaluationValidationError("frozen report inputs differ from their manifest")
    except (ValueError, TypeError, AttributeError) as exc:
        raise EvaluationValidationError("frozen report inputs differ from their manifest") from exc
    dataset = snapshot
    import copy
    journal = copy.deepcopy(journal)
    run = dataset.run
    if journal.limits_identity_sha256 != run["attempt_limits_identity_sha256"]:
        raise EvaluationValidationError("attempt journal limits identity differs from the frozen run")
    if journal.run_binding != dataset.run_binding:
        raise EvaluationValidationError("attempt journal run provenance differs from the frozen declarations")

    work_item_hashes = {item.work_item_identity_sha256 for item in dataset.items}
    outcomes = {
        (outcome.pool_occurrence_identity_sha256, outcome.variant, outcome.draw_number): outcome
        for outcome in dataset.assessments
    }
    assessment_requests_by_slot: dict[tuple[str, str, int], set[str]] = {}
    records_by_request: dict[tuple[str, str], list[AttemptRecord]] = {}
    extraction_requests_by_item: dict[str, set[str]] = {}
    complete_extractions: set[str] = set()
    for record in journal.records:
        if record.work_item_identity_sha256 not in work_item_hashes:
            raise EvaluationValidationError("attempt journal contains a work item outside the frozen cohort")
        if record.run_binding_sha256 != dataset.run_binding.identity_sha256:
            raise EvaluationValidationError("attempt journal contains an attempt from a different frozen run")
        expected_variant = record.variant
        if record.variant == "extract":
            if "extracted" not in run["variants"]:
                raise EvaluationValidationError("attempt journal contains extraction outside the declared arms")
            expected_model_variant = "extract"
        else:
            if record.variant not in run["variants"]:
                raise EvaluationValidationError("attempt journal contains an undeclared variant")
            expected_model_variant = expected_variant
        expected_model = run["model_identities"][expected_model_variant]
        if (
            record.provider != expected_model["provider"]
            or record.requested_model != expected_model["requested_model"]
            or record.resolved_model != expected_model["resolved_model"]
        ):
            raise EvaluationValidationError("attempt journal provider/model identity differs from the frozen run")
        if record.stage == "assess":
            if record.draw_number not in run["draw_numbers"]:
                raise EvaluationValidationError("attempt journal contains an undeclared assessment draw")
            slot = (record.work_item_identity_sha256, record.variant, record.draw_number)
            assessment_requests_by_slot.setdefault(slot, set()).add(record.request_identity)
        elif record.stage == "extract_jd" and record.variant != "extract":
            raise EvaluationValidationError("attempt journal extraction stage has an invalid variant")
        records_by_request.setdefault((record.request_identity, record.stage), []).append(record)
        if record.stage == "extract_jd":
            extraction_requests_by_item.setdefault(record.work_item_identity_sha256, set()).add(record.request_identity)
            if (
                record.status == "succeeded"
                and isinstance(record.response_payload, dict)
                and record.response_payload.get("coverage") == "complete"
            ):
                complete_extractions.add(record.work_item_identity_sha256)
    if any(len(requests) != 1 for requests in assessment_requests_by_slot.values()):
        raise EvaluationValidationError("a frozen item, arm and draw has more than one assessment identity")
    if any(len(requests) != 1 for requests in extraction_requests_by_item.values()):
        raise EvaluationValidationError("a frozen item has more than one extraction identity")
    if any(
        record.variant == "extracted" and record.work_item_identity_sha256 not in complete_extractions
        for record in journal.records
        if record.stage == "assess"
    ):
        raise EvaluationValidationError("an extracted assessment has no successful shared JD extraction")
    for outcome in dataset.assessments:
        matching = records_by_request.get(
            (outcome.request_identity_sha256, outcome.request_stage), []
        )
        expected_variant = "extract" if outcome.request_stage == "extract_jd" else outcome.variant
        expected_draw = None if outcome.request_stage == "extract_jd" else outcome.draw_number
        if not matching or any(
            record.work_item_identity_sha256 != outcome.work_item_identity_sha256
            or record.variant != expected_variant
            or record.draw_number != expected_draw
            for record in matching
        ):
            raise EvaluationValidationError("evaluation outcome does not match its journal request identity")
        final_status = matching[-1].status
        if outcome.request_stage == "extract_jd":
            final = matching[-1]
            if outcome.status == "completed":
                raise EvaluationValidationError("extraction-stage outcome cannot claim completed assessment")
            if final.status == "succeeded":
                coverage = (
                    final.response_payload.get("coverage")
                    if isinstance(final.response_payload, dict)
                    else None
                )
                if coverage in {None, "complete"}:
                    raise EvaluationValidationError("extraction-stage outcome requires incomplete extraction")
                if outcome.status != "unresolved":
                    raise EvaluationValidationError("incomplete extraction must remain unresolved")
            elif outcome.status == "unresolved" and final_status not in {
                "started",
                "ambiguous",
                "retryable_failure",
                "failed",
                "integrity_failure",
                "budget_stop",
            }:
                raise EvaluationValidationError("unresolved extraction outcome has no terminal journal evidence")
            elif outcome.status == "failed" and final_status not in {
                "failed",
                "integrity_failure",
                "budget_stop",
                "retryable_failure",
            }:
                raise EvaluationValidationError("failed extraction outcome does not match its journal attempt")
            continue
        if outcome.status == "completed" and final_status != "succeeded":
            raise EvaluationValidationError("completed outcome has no final successful attempt")
        if outcome.status == "completed":
            recorded = _recorded_answer_values(matching[-1], run["field_ids"])
            if any(_canonical(recorded[key]) != _canonical(outcome.answers[key]) for key in run["field_ids"]):
                raise EvaluationValidationError("evaluation answers differ from the successful attempt response")
        if outcome.status == "unresolved" and final_status not in {"started", "succeeded", "ambiguous"}:
            raise EvaluationValidationError("unresolved outcome must link to a success or ambiguous delivery")
        if outcome.status == "failed" and final_status not in {
            "failed",
            "integrity_failure",
            "budget_stop",
            "retryable_failure",
        }:
            raise EvaluationValidationError("failed outcome does not match a terminal failed attempt")

    split_reports: dict[str, Any] = {}
    for split in ("development", "held_out"):
        split_items = [item for item in dataset.items if item.split == split]
        if not split_items:
            continue
        labels = _label_counts(split_items)
        pool_ids = {item.pool_id_sha256 for item in split_items}
        baseline_reports: dict[str, Any] = {}
        for baseline_name in ("recency", "role_coverage", "daily_brief"):
            if not all(baseline_name in dataset.baseline_ranks[pool_id] for pool_id in pool_ids):
                continue
            baseline_reports[baseline_name] = {
                "budget_basis": "same declared final-review budget per complete daily pool",
                "cost_accounting": (
                    "not included in the provider attempt journal; reconcile actual ChatGPT workflow resource use separately"
                    if baseline_name == "daily_brief"
                    else "deterministic offline baseline; zero provider calls"
                ),
                "budgets": _baseline_budget_metrics(
                    split_items,
                    {
                        pool_id: {
                            occurrence: rank
                            for occurrence, rank in dataset.baseline_ranks[pool_id][baseline_name].items()
                            if occurrence in {item.pool_occurrence_identity_sha256 for item in split_items}
                        }
                        for pool_id in pool_ids
                    },
                    run["budgets"],
                ),
            }
        arm_reports: dict[str, Any] = {}
        for variant in run["variants"]:
            draw_reports: dict[str, Any] = {}
            outcomes_by_draw: dict[int, dict[str, AssessmentOutcome]] = {}
            for draw in run["draw_numbers"]:
                planned_items = [item for item in split_items if draw in item.draw_numbers]
                planned_hashes = {item.pool_occurrence_identity_sha256 for item in planned_items}
                full_pool_plan = all(
                    all(draw in item.draw_numbers for item in split_items if item.pool_id_sha256 == pool_id)
                    for pool_id in {item.pool_id_sha256 for item in split_items}
                )
                current = {
                    occurrence: outcome
                    for (occurrence, result_variant, result_draw), outcome in outcomes.items()
                    if result_variant == variant
                    and result_draw == draw
                    and occurrence in planned_hashes
                }
                outcomes_by_draw[draw] = current
                status_counts = {
                    "completed": sum(outcome.status == "completed" for outcome in current.values()),
                    "unresolved": sum(outcome.status == "unresolved" for outcome in current.values()),
                    "failed": sum(outcome.status == "failed" for outcome in current.values()),
                    "missing": len(planned_items) - len(current),
                }
                draw_reports[str(draw)] = {
                    "expected_assessments": len(planned_items),
                    "assessment_scope": "full_daily_pools" if full_pool_plan else "predeclared_repeated_subset",
                    "population_recall_reportable": full_pool_plan,
                    "outcome_status_counts": status_counts,
                    "assessment_coverage": _ratio(status_counts["completed"], len(planned_items)),
                    "budgets": _budget_metrics(planned_items, current, run["budgets"]),
                    "field_metrics": _field_metrics(planned_items, current, run["field_ids"]),
                    "required_yoe_metrics": _yoe_metrics(planned_items, current),
                }
            arm_reports[variant] = {
                "draws": draw_reports,
                "top_budget_stability": _stability_metrics(split_items, outcomes_by_draw, run["budgets"]),
            }
        split_reports[split] = {
            "items": len(split_items),
            "daily_pools": len({item.pool_id_sha256 for item in split_items}),
            "group_count": len({item.group_id for item in split_items}),
            "label_counts": labels,
            "label_coverage": _ratio(labels["positive"] + labels["negative"], len(split_items)),
            "label_source_counts": _label_source_counts(split_items),
            "role_families": sorted({role for item in split_items for role in item.role_families}),
            "baselines": baseline_reports,
            "arms": arm_reports,
        }

    return {
        "report_schema": 1,
        "run": {
            "run_id": run["run_id"],
            "protocol_version": run["protocol_version"],
            "phase": run["phase"],
            "pool_fingerprint_sha256": run["pool_fingerprint_sha256"],
            "split_algorithm": run["split_algorithm"],
            "split_seed_sha256": hashlib.sha256(
                b"preselection-evaluation-split-seed-v1\0" + run["split_seed"].encode("utf-8")
            ).hexdigest(),
            "profile_sha256": run["profile_sha256"],
            "question_set_sha256": run["question_set_sha256"],
            "label_guide_sha256": run["label_guide_sha256"],
            "split_manifest_sha256": run["split_manifest_sha256"],
            "selection_policy_version": run["selection_policy_version"],
            "labeling_blinded": run["labeling_blinded"],
            "attempt_limits_identity_sha256": run["attempt_limits_identity_sha256"],
            "run_binding_sha256": dataset.run_binding.identity_sha256,
            "evaluation_manifest_sha256": dataset.manifest_sha256,
            "attempt_journal_sha256": hashlib.sha256(journal.to_json().encode("utf-8")).hexdigest(),
            "model_identities": run["model_identities"],
            "variants": list(run["variants"]),
            "draw_numbers": list(run["draw_numbers"]),
            "budgets": list(run["budgets"]),
            "field_ids": list(run["field_ids"]),
            "baseline_orders_sha256": hashlib.sha256(
                json.dumps(
                    {
                        pool_id: {
                            name: sorted(ranks.items())
                            for name, ranks in sorted(pool_orders.items())
                        }
                        for pool_id, pool_orders in sorted(dataset.baseline_ranks.items())
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        },
        "metric_definitions": {
            "recall_denominator": "all positive-labeled items in the reported split, including missing or failed assessments",
            "budget_scope": "priority ranks are per daily pool among items planned for that draw; full-pool recall requires every pool item to be planned",
            "precision_denominator": "positive plus negative labels among selected items; unresolved selected labels are excluded and counted separately",
            "confidence_interval": "descriptive two-sided 95% Wilson interval, unadjusted for grouped or repeated observations",
            "decision_rule": "this report contains no promotion threshold and never records GO",
            "workload_identity": "pool_occurrence_identity_sha256 defines per-pool metric rows; stable work-item identity defines cached requests and provider-attempt cost",
        },
        "cohort": {
            "items": len(dataset.items),
            "pool_occurrences": len(dataset.items),
            "unique_work_items": len({item.work_item_identity_sha256 for item in dataset.items}),
            "groups": len({item.group_id for item in dataset.items}),
            "label_counts": _label_counts(list(dataset.items)),
            "label_source_counts": _label_source_counts(list(dataset.items)),
            "label_coverage": _ratio(
                sum(item.label in {"positive", "negative"} for item in dataset.items), len(dataset.items)
            ),
            "label_evidence_status": (
                "synthetic_fixture_only"
                if all(item.label_source == "synthetic_fixture" for item in dataset.items)
                else "human_labels_blinded_to_assessments"
            ),
        },
        "splits": split_reports,
        "attempt_accounting": _attempt_accounting(dataset, journal),
        "decision": {
            "status": "not_recorded",
            "owner": "orchestrator",
            "reason": "metrics do not authorize a pilot, GO, or production rollout",
        },
    }
