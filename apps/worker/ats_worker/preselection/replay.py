"""Provider-free grouped frozen-pool replay with aggregate-only reporting.

The input contains pseudonymous identity/group keys, timestamps, role-family labels and
explicit positive/negative/unresolved labels. It accepts no JD or candidate-profile text,
does not call a scorer, and never emits row or group identifiers in its report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


class ReplayValidationError(ValueError):
    """The frozen pool or replay parameters are malformed or insufficient to split."""


@dataclass(frozen=True)
class FrozenItem:
    id: str
    group_id: str
    observed_at: datetime
    role_families: tuple[str, ...]
    label: str

    @property
    def utc_day(self) -> str:
        return self.observed_at.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class FrozenPool:
    pool_id: str
    items: tuple[FrozenItem, ...]


_POOL_KEYS = {"schema", "pool_id", "items"}
_ITEM_KEYS = {"id", "group_id", "observed_at", "role_families", "label"}
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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayValidationError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def pool_from_value(value: Any) -> FrozenPool:
    """Validate a closed frozen-pool schema, including explicit unresolved labels."""
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
    """Decode a JSON pool while rejecting duplicate object members."""
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReplayValidationError("duplicate JSON object member")
            result[key] = value
        return result

    try:
        return pool_from_value(json.loads(source, object_pairs_hook=reject_duplicates))
    except ReplayValidationError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise ReplayValidationError("pool is not valid JSON") from exc


def _stable_split(
    pool: FrozenPool, seed: str, heldout_fraction: float
) -> tuple[dict[str, str], dict[str, int]]:
    """Assign whole UTC days and duplicate/template groups to development or held-out."""
    if not isinstance(seed, str) or not seed.strip():
        raise ReplayValidationError("seed must be non-empty text")
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

    row_nodes: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for item in pool.items:
        day_node = ("day", item.utc_day)
        group_node = ("group", item.group_id)
        union(day_node, group_node)
        row_nodes.append((day_node, group_node))

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
            (seed + "\0" + json.dumps(sorted(nodes_by_root[root]), separators=(",", ":"))).encode()
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
    for role in roles:
        role_pool = [item for item in pool_items if role in item.role_families]
        role_selected = [item for item in selected_items if role in item.role_families]
        positive_total = sum(item.label == "positive" for item in role_pool)
        positive_selected = sum(item.label == "positive" for item in role_selected)
        pool_counts = _label_counts(role_pool)
        metrics[role] = {
            "pool_items": len(role_pool),
            "selected_items": len(role_selected),
            "label_counts": pool_counts,
            "selected_label_counts": _label_counts(role_selected),
            "label_coverage": _ratio(
                pool_counts["positive"] + pool_counts["negative"], len(role_pool)
            ),
            "positive_total": positive_total,
            "positive_selected": positive_selected,
            "positive_recall": _ratio(positive_selected, positive_total),
        }
    return metrics


def _baseline_results(items: list[FrozenItem], budgets: tuple[int, ...]) -> list[dict[str, Any]]:
    baseline_orders = {
        "recency": _recency_order(items),
        "role_coverage": _role_coverage_order(items),
    }
    results: list[dict[str, Any]] = []
    for baseline, ordered in baseline_orders.items():
        for budget in budgets:
            selected = ordered[:budget]
            counts = _label_counts(selected)
            positive_total = sum(item.label == "positive" for item in items)
            positive_selected = counts["positive"]
            results.append(
                {
                    "baseline": baseline,
                    "budget": budget,
                    "selected": len(selected),
                    "selected_label_counts": counts,
                    "positive_total": positive_total,
                    "positive_selected": positive_selected,
                    "positive_recall": _ratio(positive_selected, positive_total),
                    "role_family_metrics": _role_metrics(items, selected),
                }
            )
    return results


def build_replay_report(
    pool: FrozenPool,
    *,
    seed: str,
    heldout_fraction: float,
    budgets: tuple[int, ...] | list[int],
) -> dict[str, Any]:
    """Build deterministic split/baseline metrics; thresholds and PASS are omitted."""
    normalized_budgets = tuple(budgets)
    if not normalized_budgets or any(
        type(budget) is not int or budget <= 0 for budget in normalized_budgets
    ):
        raise ReplayValidationError("budgets must be a non-empty list of positive integers")
    if len(set(normalized_budgets)) != len(normalized_budgets):
        raise ReplayValidationError("budgets must not contain duplicates")
    if not isinstance(pool, FrozenPool):
        raise ReplayValidationError("pool must be a validated FrozenPool")

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
    fingerprint_json = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(fingerprint_json.encode()).hexdigest()

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
            "role_family_metrics": _role_metrics(split_items, split_items),
            "baselines": _baseline_results(split_items, normalized_budgets),
        }

    return {
        "report_schema": 1,
        "pool_fingerprint_sha256": fingerprint,
        "item_count": len(pool.items),
        "split": {
            "algorithm": "utc-day-and-group-connected-components-v1",
            "seed": seed,
            "heldout_fraction": float(heldout_fraction),
        },
        "budgets": list(normalized_budgets),
        "provider_calls": 0,
        "inference_cost": "not_applicable_no_provider_calls",
        "splits": split_reports,
    }
