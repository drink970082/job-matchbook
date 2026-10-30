"""Provider-free grouped replay over frozen, auditable source artifacts.

The legacy pool reader remains for exploration and always marks its evidence
INCONCLUSIVE. Frozen-snapshot replay validates the supplied candidate profile, exact
rendered context, normalized source payloads, and manifest hashes, versions, counts, and
daily membership before scoring. Without an independent source roster it cannot prove
that the supplied pool had no omissions before freezing, so every frozen replay report
also marks its evidence INCONCLUSIVE.
Reports contain aggregates and hashes only; they never emit row/group identifiers or
posting/profile text.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from ats_worker.preselection.profile import (
    CandidateProfile,
    ProfileValidationError,
    PROFILE_RENDERER_VERSION,
    profile_from_value,
    render_profile,
)


class ReplayValidationError(ValueError):
    """A frozen artifact, pool, manifest or replay parameter is invalid."""


FROZEN_SNAPSHOT_SCHEMA = 1
FROZEN_INPUT_VERSION = "preselection-frozen-input-v1"
REPLAY_ALGORITHM_VERSION = "utc-day-group-and-source-identity-connected-components-v2"


@dataclass(frozen=True)
class FrozenItem:
    id: str
    group_id: str
    observed_at: datetime
    role_families: tuple[str, ...]
    label: str
    source_identity_sha256: str | None = None

    @property
    def utc_day(self) -> str:
        return self.observed_at.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class FrozenPool:
    pool_id: str
    items: tuple[FrozenItem, ...]


@dataclass(frozen=True)
class FrozenSnapshot:
    profile: CandidateProfile
    rendered_context: str
    pool: FrozenPool
    profile_sha256: str
    rendered_context_sha256: str
    source_pool_sha256: str
    manifest_sha256: str
    daily_membership_sha256: str


_POOL_KEYS = {"schema", "pool_id", "items"}
_ITEM_KEYS = {"id", "group_id", "observed_at", "role_families", "label"}
_SOURCE_ITEM_KEYS = _ITEM_KEYS | {"source_payload"}
_SNAPSHOT_KEYS = {"schema", "profile", "rendered_context", "source_pool", "manifest"}
_MANIFEST_KEYS = {"schema", "versions", "hashes", "counts", "daily_pools"}
_MANIFEST_VERSION_KEYS = {
    "frozen_input",
    "profile_schema",
    "profile_renderer",
    "source_pool_schema",
    "replay_algorithm",
}
_MANIFEST_HASH_KEYS = {
    "profile_sha256",
    "rendered_context_sha256",
    "source_pool_sha256",
}
_MANIFEST_COUNT_KEYS = {"items", "utc_days", "label_counts"}
_DAILY_MANIFEST_KEYS = {"utc_day", "item_count", "item_ids", "label_counts"}
_SOURCE_REQUIRED_TEXT_FIELDS = {
    "source",
    "external_id",
    "company_name",
    "job_title",
    "job_url",
    "description",
}
_SOURCE_NONEMPTY_TEXT_FIELDS = {"company_name", "job_title", "job_url", "description"}
_SOURCE_REQUIRED_NULLABLE_TEXT_FIELDS = {"location", "posted_at"}
_SOURCE_REQUIRED_FIELDS = _SOURCE_REQUIRED_TEXT_FIELDS | _SOURCE_REQUIRED_NULLABLE_TEXT_FIELDS
_SOURCE_POOL_COMPLETENESS_LIMITATION = "source_pool_completeness_not_independently_verifiable"
_LABELS = {"positive", "negative", "unresolved"}


def _expect_object(value: Any, keys: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayValidationError(f"{path} must be an object")
    present = set(value)
    if present - keys:
        raise ReplayValidationError(f"{path} contains an unknown field")
    if keys - present:
        raise ReplayValidationError(f"{path} is missing a required field")
    return value


def _safe_key(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ReplayValidationError(f"{path} must be non-empty trimmed text")
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ReplayValidationError(f"{path} contains a control character")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str):
        raise ReplayValidationError(f"{path} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ReplayValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    try:
        offset = parsed.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise ReplayValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or offset is None:
        raise ReplayValidationError(f"{path} must include a timezone")
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ReplayValidationError(f"{path} must be an ISO-8601 timestamp") from exc


def _canonical_json(value: Any, message: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ReplayValidationError(message) from exc


def _canonical_sha256(value: Any, message: str = "frozen artifact cannot be hashed") -> str:
    try:
        encoded = _canonical_json(value, message).encode("utf-8")
    except UnicodeError as exc:
        raise ReplayValidationError(message) from exc
    return hashlib.sha256(encoded).hexdigest()


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayValidationError("duplicate JSON object member")
        result[key] = value
    return result


def pool_from_value(value: Any) -> FrozenPool:
    """Validate the legacy closed pool schema, including unresolved labels."""
    payload = _expect_object(value, _POOL_KEYS, "pool")
    if type(payload["schema"]) is not int or payload["schema"] != 1:
        raise ReplayValidationError("pool.schema must equal integer 1")
    pool_id = _safe_key(payload["pool_id"], "pool.pool_id")
    raw_items = payload["items"]
    if not isinstance(raw_items, list) or not raw_items:
        raise ReplayValidationError("pool.items must be a non-empty array")

    items: list[FrozenItem] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_items):
        path = f"pool.items[{index}]"
        row = _expect_object(raw, _ITEM_KEYS, path)
        item_id = _safe_key(row["id"], f"{path}.id")
        if item_id in seen_ids:
            raise ReplayValidationError("pool item IDs must be unique")
        seen_ids.add(item_id)
        group_id = _safe_key(row["group_id"], f"{path}.group_id")
        observed_at = _timestamp(row["observed_at"], f"{path}.observed_at")
        roles = row["role_families"]
        if not isinstance(roles, list):
            raise ReplayValidationError(f"{path}.role_families must be an array")
        role_families = tuple(
            _safe_key(role, f"{path}.role_families[{role_index}]")
            for role_index, role in enumerate(roles)
        )
        if len(set(role_families)) != len(role_families):
            raise ReplayValidationError(f"{path}.role_families contains duplicates")
        label = row["label"]
        if not isinstance(label, str) or label not in _LABELS:
            raise ReplayValidationError(f"{path}.label must be positive, negative, or unresolved")
        items.append(FrozenItem(item_id, group_id, observed_at, role_families, label))
    return FrozenPool(pool_id, tuple(items))


def load_pool_text(source: str) -> FrozenPool:
    """Decode a legacy pool while rejecting duplicate JSON members."""
    try:
        return pool_from_value(json.loads(source, object_pairs_hook=_reject_duplicate_members))
    except ReplayValidationError:
        raise
    except (json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise ReplayValidationError("pool is not valid JSON") from exc


def _validated_source_pool(value: Any) -> tuple[FrozenPool, str]:
    raw_pool = _expect_object(value, _POOL_KEYS, "source_pool")
    if type(raw_pool["schema"]) is not int or raw_pool["schema"] != 1:
        raise ReplayValidationError("source_pool.schema must equal integer 1")
    raw_items = raw_pool["items"]
    if not isinstance(raw_items, list) or not raw_items:
        raise ReplayValidationError("source_pool.items must be a non-empty array")

    projected_items: list[dict[str, Any]] = []
    identity_hashes: list[str] = []
    for index, raw in enumerate(raw_items):
        path = f"source_pool.items[{index}]"
        row = _expect_object(raw, _SOURCE_ITEM_KEYS, path)
        source_payload = row["source_payload"]
        if not isinstance(source_payload, dict):
            raise ReplayValidationError(f"{path}.source_payload must be an object")
        missing = _SOURCE_REQUIRED_FIELDS - set(source_payload)
        if missing:
            raise ReplayValidationError(f"{path}.source_payload is missing required source fields")
        for field in _SOURCE_REQUIRED_TEXT_FIELDS:
            if not isinstance(source_payload[field], str):
                raise ReplayValidationError(f"{path}.source_payload.{field} must be text")
        for field in _SOURCE_NONEMPTY_TEXT_FIELDS:
            if not source_payload[field].strip():
                raise ReplayValidationError(
                    f"{path}.source_payload.{field} must contain non-whitespace text"
                )
        for field in _SOURCE_REQUIRED_NULLABLE_TEXT_FIELDS:
            if source_payload[field] is not None and not isinstance(source_payload[field], str):
                raise ReplayValidationError(
                    f"{path}.source_payload.{field} must be text or null"
                )
        _canonical_json(source_payload, f"{path}.source_payload is not valid JSON data")
        projected_items.append({key: row[key] for key in _ITEM_KEYS})

        source = _safe_key(source_payload["source"], f"{path}.source_payload.source")
        external_id = _safe_key(
            source_payload["external_id"], f"{path}.source_payload.external_id"
        )
        identity_json = _canonical_json(
            [source, external_id], f"{path}.source_payload identity is invalid"
        )
        identity_hash = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()
        identity_hashes.append(identity_hash)

    projected_pool = {
        "schema": raw_pool["schema"],
        "pool_id": raw_pool["pool_id"],
        "items": projected_items,
    }
    pool = pool_from_value(projected_pool)
    pool = FrozenPool(
        pool_id=pool.pool_id,
        items=tuple(
            FrozenItem(
                id=item.id,
                group_id=item.group_id,
                observed_at=item.observed_at,
                role_families=item.role_families,
                label=item.label,
                source_identity_sha256=identity_hash,
            )
            for item, identity_hash in zip(pool.items, identity_hashes, strict=True)
        ),
    )
    return pool, _canonical_sha256(raw_pool, "source_pool cannot be canonically encoded")


def _daily_membership(pool: FrozenPool) -> list[dict[str, Any]]:
    by_day: dict[str, list[FrozenItem]] = {}
    for item in pool.items:
        by_day.setdefault(item.utc_day, []).append(item)
    return [
        {
            "utc_day": day,
            "item_count": len(items),
            "item_ids": sorted(item.id for item in items),
            "label_counts": _label_counts(items),
        }
        for day, items in sorted(by_day.items())
    ]


def build_snapshot_manifest(
    profile_value: Any, rendered_context: str, source_pool_value: Any
) -> dict[str, Any]:
    """Compute a manifest from the actual supplied artifacts for freezing or validation."""
    try:
        profile = profile_from_value(profile_value)
    except ProfileValidationError as exc:
        raise ReplayValidationError(f"candidate profile is invalid: {exc}") from exc
    if not isinstance(rendered_context, str):
        raise ReplayValidationError("rendered_context must be text")
    try:
        rendered_bytes = rendered_context.encode("utf-8")
        expected_bytes = render_profile(profile).encode("utf-8")
    except UnicodeError as exc:
        raise ReplayValidationError("rendered_context is not valid UTF-8 text") from exc
    if rendered_bytes != expected_bytes:
        raise ReplayValidationError("rendered_context does not match the candidate profile renderer")

    pool, source_pool_sha256 = _validated_source_pool(source_pool_value)
    items = list(pool.items)
    return {
        "schema": 1,
        "versions": {
            "frozen_input": FROZEN_INPUT_VERSION,
            "profile_schema": profile.schema,
            "profile_renderer": PROFILE_RENDERER_VERSION,
            "source_pool_schema": 1,
            "replay_algorithm": REPLAY_ALGORITHM_VERSION,
        },
        "hashes": {
            "profile_sha256": profile.identity_sha256,
            "rendered_context_sha256": hashlib.sha256(rendered_bytes).hexdigest(),
            "source_pool_sha256": source_pool_sha256,
        },
        "counts": {
            "items": len(items),
            "utc_days": len({item.utc_day for item in items}),
            "label_counts": _label_counts(items),
        },
        "daily_pools": _daily_membership(pool),
    }


def snapshot_from_value(value: Any) -> FrozenSnapshot:
    """Validate a profile/context/source bundle against a recomputed closed manifest."""
    snapshot = _expect_object(value, _SNAPSHOT_KEYS, "snapshot")
    if type(snapshot["schema"]) is not int or snapshot["schema"] != FROZEN_SNAPSHOT_SCHEMA:
        raise ReplayValidationError("snapshot.schema is not supported")
    context = snapshot["rendered_context"]
    if not isinstance(context, str):
        raise ReplayValidationError("snapshot.rendered_context must be text")
    try:
        profile = profile_from_value(snapshot["profile"])
    except ProfileValidationError as exc:
        raise ReplayValidationError(f"snapshot.profile is invalid: {exc}") from exc

    expected_manifest = build_snapshot_manifest(snapshot["profile"], context, snapshot["source_pool"])
    manifest = _expect_object(snapshot["manifest"], _MANIFEST_KEYS, "snapshot.manifest")
    if type(manifest["schema"]) is not int or manifest["schema"] != 1:
        raise ReplayValidationError("snapshot.manifest.schema must equal integer 1")
    versions = _expect_object(manifest["versions"], _MANIFEST_VERSION_KEYS, "snapshot.manifest.versions")
    hashes = _expect_object(manifest["hashes"], _MANIFEST_HASH_KEYS, "snapshot.manifest.hashes")
    counts = _expect_object(manifest["counts"], _MANIFEST_COUNT_KEYS, "snapshot.manifest.counts")
    if _canonical_json(versions, "snapshot manifest versions are invalid") != _canonical_json(
        expected_manifest["versions"], "recomputed snapshot versions are invalid"
    ):
        raise ReplayValidationError("snapshot manifest versions do not match this replay contract")
    if hashes != expected_manifest["hashes"]:
        raise ReplayValidationError("snapshot manifest hashes do not match supplied artifacts")
    if _canonical_json(counts, "snapshot manifest counts are invalid") != _canonical_json(
        expected_manifest["counts"], "recomputed snapshot counts are invalid"
    ):
        raise ReplayValidationError("snapshot manifest counts do not match source rows")

    raw_daily = manifest["daily_pools"]
    if not isinstance(raw_daily, list):
        raise ReplayValidationError("snapshot.manifest.daily_pools must be an array")
    for index, daily in enumerate(raw_daily):
        row = _expect_object(daily, _DAILY_MANIFEST_KEYS, f"snapshot.manifest.daily_pools[{index}]")
        if (
            not isinstance(row["utc_day"], str)
            or type(row["item_count"]) is not int
            or not isinstance(row["item_ids"], list)
            or any(not isinstance(item_id, str) for item_id in row["item_ids"])
        ):
            raise ReplayValidationError("snapshot daily pool membership is malformed")
        label_counts = _expect_object(
            row["label_counts"], set(_LABELS), f"snapshot.manifest.daily_pools[{index}].label_counts"
        )
        if any(type(count) is not int or count < 0 for count in label_counts.values()):
            raise ReplayValidationError("snapshot daily label counts are malformed")
    if _canonical_json(raw_daily, "snapshot daily membership is invalid") != _canonical_json(
        expected_manifest["daily_pools"], "recomputed daily membership is invalid"
    ):
        raise ReplayValidationError("snapshot daily membership does not match source rows")

    pool, source_pool_sha256 = _validated_source_pool(snapshot["source_pool"])
    context_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    profile_hash = profile.identity_sha256
    return FrozenSnapshot(
        profile=profile,
        rendered_context=context,
        pool=pool,
        profile_sha256=profile_hash,
        rendered_context_sha256=context_hash,
        source_pool_sha256=source_pool_sha256,
        manifest_sha256=_canonical_sha256(manifest, "snapshot manifest cannot be hashed"),
        daily_membership_sha256=_canonical_sha256(
            expected_manifest["daily_pools"], "daily membership cannot be hashed"
        ),
    )


def load_snapshot_text(source: str) -> FrozenSnapshot:
    """Decode one self-contained frozen snapshot and reject duplicate JSON members."""
    try:
        return snapshot_from_value(json.loads(source, object_pairs_hook=_reject_duplicate_members))
    except ReplayValidationError:
        raise
    except (json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise ReplayValidationError("snapshot is not valid JSON") from exc


def _stable_split(
    pool: FrozenPool, seed: str, heldout_fraction: float
) -> tuple[dict[str, str], dict[str, int]]:
    """Assign whole UTC days and duplicate/template groups to development or held-out."""
    if not isinstance(seed, str) or not seed.strip():
        raise ReplayValidationError("seed must be non-empty text")
    try:
        seed_bytes = seed.encode("utf-8")
    except UnicodeEncodeError:
        raise ReplayValidationError("seed must be valid Unicode text") from None
    if isinstance(heldout_fraction, bool) or not isinstance(heldout_fraction, (int, float)):
        raise ReplayValidationError("heldout_fraction must be between 0 and 1")
    if not 0 < heldout_fraction < 1:
        raise ReplayValidationError("heldout_fraction must be between 0 and 1")

    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = find(parent[node])
        return parent[node]

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    row_nodes: list[tuple[tuple[str, str], ...]] = []
    for item in pool.items:
        day_node = ("day", item.utc_day)
        group_node = ("group", item.group_id)
        nodes = [day_node, group_node]
        if item.source_identity_sha256 is not None:
            nodes.append(("source_identity", item.source_identity_sha256))
        for node in nodes[1:]:
            union(nodes[0], node)
        row_nodes.append(tuple(nodes))

    rows_by_root: dict[tuple[str, str], list[int]] = {}
    nodes_by_root: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for index, nodes in enumerate(row_nodes):
        root = find(nodes[0])
        rows_by_root.setdefault(root, []).append(index)
        nodes_by_root.setdefault(root, set()).update(nodes)
    if len(rows_by_root) < 2:
        raise ReplayValidationError("pool needs at least two independent day/group components")

    components = list(rows_by_root)
    components.sort(
        key=lambda root: hashlib.sha256(
            seed_bytes
            + b"\0"
            + json.dumps(sorted(nodes_by_root[root]), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    heldout_count = int(len(components) * float(heldout_fraction) + 0.5)
    heldout_count = min(len(components) - 1, max(1, heldout_count))
    heldout_roots = set(components[:heldout_count])

    item_split: dict[str, str] = {}
    split_component_counts = {"development": 0, "held_out": 0}
    for root, indexes in rows_by_root.items():
        split = "held_out" if root in heldout_roots else "development"
        split_component_counts[split] += 1
        for index in indexes:
            item_split[pool.items[index].id] = split
    return item_split, split_component_counts


def _recency_order(items: list[FrozenItem]) -> list[FrozenItem]:
    return sorted(items, key=lambda item: (-item.observed_at.timestamp(), item.id))


def _role_coverage_order(items: list[FrozenItem]) -> list[FrozenItem]:
    remaining = {role for item in items for role in item.role_families}
    pool = list(items)
    ordered: list[FrozenItem] = []
    while pool:
        chosen = min(
            pool,
            key=lambda item: (
                -len(remaining.intersection(item.role_families)),
                -item.observed_at.timestamp(),
                item.id,
            ),
        )
        ordered.append(chosen)
        remaining.difference_update(chosen.role_families)
        pool.remove(chosen)
    return ordered


def _label_counts(items: list[FrozenItem]) -> dict[str, int]:
    counts = Counter(item.label for item in items)
    return {label: counts[label] for label in ("positive", "negative", "unresolved")}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _role_metrics(
    pool_items: list[FrozenItem], selected_items: list[FrozenItem]
) -> dict[str, dict[str, Any]]:
    roles = sorted({role for item in pool_items for role in item.role_families})
    metrics: dict[str, dict[str, Any]] = {}
    for index, role in enumerate(roles, start=1):
        role_pool = [item for item in pool_items if role in item.role_families]
        role_selected = [item for item in selected_items if role in item.role_families]
        positive_total = sum(item.label == "positive" for item in role_pool)
        positive_selected = sum(item.label == "positive" for item in role_selected)
        pool_counts = _label_counts(role_pool)
        metrics[f"role_{index}"] = {
            "pool_items": len(role_pool),
            "selected_items": len(role_selected),
            "label_counts": pool_counts,
            "selected_label_counts": _label_counts(role_selected),
            "label_coverage": _ratio(
                pool_counts["positive"] + pool_counts["negative"], len(role_pool)
            ),
            "positive_total": positive_total,
            "positive_selected": positive_selected,
            "positive_recall": (
                None
                if pool_counts["unresolved"]
                else _ratio(positive_selected, positive_total)
            ),
        }
    return metrics


def _baseline_results(items: list[FrozenItem], budgets: tuple[int, ...]) -> list[dict[str, Any]]:
    by_day: dict[str, list[FrozenItem]] = {}
    for item in items:
        by_day.setdefault(item.utc_day, []).append(item)
    orderers = {
        "recency": _recency_order,
        "role_coverage": _role_coverage_order,
    }
    results: list[dict[str, Any]] = []
    for baseline, order in orderers.items():
        for budget in budgets:
            selected: list[FrozenItem] = []
            daily_allocations: list[dict[str, Any]] = []
            for day, daily_items in sorted(by_day.items()):
                daily_selected = order(list(daily_items))[:budget]
                selected.extend(daily_selected)
                daily_allocations.append(
                    {
                        "utc_day": day,
                        "pool_items": len(daily_items),
                        "selected": len(daily_selected),
                        "selected_label_counts": _label_counts(daily_selected),
                    }
                )
            counts = _label_counts(selected)
            total_counts = _label_counts(items)
            positive_total = total_counts["positive"]
            positive_selected = counts["positive"]
            results.append(
                {
                    "baseline": baseline,
                    "budget": budget,
                    "budget_scope": "per_utc_day",
                    "daily_pool_count": len(by_day),
                    "selected": len(selected),
                    "selected_label_counts": counts,
                    "positive_total": positive_total,
                    "positive_selected": positive_selected,
                    "positive_recall": (
                        None
                        if total_counts["unresolved"]
                        else _ratio(positive_selected, positive_total)
                    ),
                    "role_family_metrics": _role_metrics(items, selected),
                    "daily_allocations": daily_allocations,
                }
            )
    return results


def _validated_budgets(budgets: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    normalized = tuple(budgets)
    if not normalized or any(type(budget) is not int or budget <= 0 for budget in normalized):
        raise ReplayValidationError("budgets must be a non-empty list of positive integers")
    if len(set(normalized)) != len(normalized):
        raise ReplayValidationError("budgets must not contain duplicates")
    return normalized


def _build_pool_report(
    pool: FrozenPool,
    *,
    seed: str,
    heldout_fraction: float,
    budgets: tuple[int, ...],
) -> dict[str, Any]:
    item_split, component_counts = _stable_split(pool, seed, heldout_fraction)
    fingerprint_payload = [
        {
            "id": item.id,
            "group_id": item.group_id,
            "observed_at": item.observed_at.isoformat(),
            "role_families": list(item.role_families),
            "label": item.label,
        }
        for item in pool.items
    ]
    fingerprint = _canonical_sha256(fingerprint_payload, "pool fingerprint cannot be computed")

    split_reports: dict[str, Any] = {}
    for split_name in ("development", "held_out"):
        split_items = [item for item in pool.items if item_split[item.id] == split_name]
        labels = _label_counts(split_items)
        days = {item.utc_day for item in split_items}
        split_reports[split_name] = {
            "items": len(split_items),
            "days": len(days),
            "group_components": component_counts[split_name],
            "label_counts": labels,
            "label_coverage": _ratio(labels["positive"] + labels["negative"], len(split_items)),
            "label_evidence_status": "INCONCLUSIVE" if labels["unresolved"] else "RESOLVED_LABELS",
            "role_family_metrics": _role_metrics(split_items, split_items),
            "baselines": _baseline_results(split_items, budgets),
        }

    return {
        "report_schema": 2,
        "pool_fingerprint_sha256": fingerprint,
        "item_count": len(pool.items),
        "split": {
            "algorithm": REPLAY_ALGORITHM_VERSION,
            "seed": seed,
            "heldout_fraction": float(heldout_fraction),
        },
        "budgets": list(budgets),
        "provider_calls": 0,
        "inference_cost": "not_applicable_no_provider_calls",
        "acceptance_decision": "not_recorded",
        "splits": split_reports,
    }


def build_replay_report(
    pool: FrozenPool,
    *,
    seed: str,
    heldout_fraction: float,
    budgets: tuple[int, ...] | list[int],
) -> dict[str, Any]:
    """Exploratory report for a legacy ID-only pool; evidence is always inconclusive."""
    normalized_budgets = _validated_budgets(budgets)
    if not isinstance(pool, FrozenPool):
        raise ReplayValidationError("pool must be a validated FrozenPool")
    report = _build_pool_report(
        pool,
        seed=seed,
        heldout_fraction=heldout_fraction,
        budgets=normalized_budgets,
    )
    report["evidence_status"] = "INCONCLUSIVE"
    report["evidence_limitations"] = [
        "legacy pool has no full source payloads",
        "legacy pool has no profile-to-context linkage",
        "legacy pool has no frozen daily-membership manifest",
    ]
    return report


def build_snapshot_replay_report(
    snapshot: FrozenSnapshot,
    *,
    seed: str,
    heldout_fraction: float,
    budgets: tuple[int, ...] | list[int],
) -> dict[str, Any]:
    """Build metrics only after validating all actual profile/context/source artifacts."""
    normalized_budgets = _validated_budgets(budgets)
    if not isinstance(snapshot, FrozenSnapshot):
        raise ReplayValidationError("snapshot must be a validated FrozenSnapshot")
    report = _build_pool_report(
        snapshot.pool,
        seed=seed,
        heldout_fraction=heldout_fraction,
        budgets=normalized_budgets,
    )
    unresolved = any(item.label == "unresolved" for item in snapshot.pool.items)
    report["evidence_status"] = "INCONCLUSIVE"
    report["evidence_limitations"] = [_SOURCE_POOL_COMPLETENESS_LIMITATION]
    if unresolved:
        report["evidence_limitations"].append("unresolved_labels")
    report["provenance"] = {
        "profile_version": snapshot.profile.version,
        "profile_status": snapshot.profile.status,
        "profile_sha256": snapshot.profile_sha256,
        "rendered_context_sha256": snapshot.rendered_context_sha256,
        "source_pool_sha256": snapshot.source_pool_sha256,
        "snapshot_manifest_sha256": snapshot.manifest_sha256,
        "daily_membership_sha256": snapshot.daily_membership_sha256,
        "source_items": len(snapshot.pool.items),
        "utc_days": len({item.utc_day for item in snapshot.pool.items}),
        "versions": {
            "frozen_input": FROZEN_INPUT_VERSION,
            "profile_schema": snapshot.profile.schema,
            "profile_renderer": PROFILE_RENDERER_VERSION,
            "source_pool_schema": 1,
            "replay_algorithm": REPLAY_ALGORITHM_VERSION,
        },
    }
    return report
