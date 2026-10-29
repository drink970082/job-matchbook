"""Pure, provider-free fixed review-batch preparation and replay contracts.

All inputs are caller-supplied synthetic records. This module owns no database,
filesystem, network, profile, provider, runtime configuration, or scheduling wiring.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


SCHEMA_VERSION = 1
BATCH_SCOPE = "synthetic_review_batch"
MAX_POLICY_CANDIDATES = 10_000
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]*$")
_OFFSET_TIMESTAMP = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})[Tt ]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<zone>[Zz]|(?P<sign>[+-])(?P<offset_hour>\d{2}):(?P<offset_minute>\d{2}))$"
)
_NANOSECONDS_PER_SECOND = 1_000_000_000
_CANDIDATE_KINDS = frozenset({"newly_retained", "newly_assessed", "deferred", "retry", "historic"})
_BUCKETS = ("ranked", "audit", "unresolved")
_POLICY_KEYS = frozenset({
    "version", "recipe_id", "k", "ranked_slots", "audit_slots", "unresolved_slots",
    "tie_rule", "seed", "page_size", "service_age_hours", "service_slots",
    "role_coverage_slots", "overload_threshold", "retry_max_overdue_hours", "max_candidate_count",
    "max_replacements", "max_revalidation_work", "max_elapsed_seconds",
    "redistribution_order",
})
_CANDIDATE_REQUIRED = frozenset({
    "candidate_id", "source_id", "posting_identity", "requisition_id",
    "source_revision", "content_revision", "content_identity", "assessment_version",
    "assessment_state", "assessment_content_revision", "eligibility_state", "yoe_state",
    "source_state", "confirmed_application", "manual_terminal", "kind",
    "first_eligible_at", "deferred_at", "retry_due_at", "priority_order",
    "role_family_ids", "group_ids", "title", "company", "provenance",
})


class ReviewBatchError(ValueError):
    """A malformed or unsupported synthetic batch contract."""


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text(value: Any, *, allow_empty: bool = False, limit: int = 512) -> bool:
    return (isinstance(value, str) and len(value) <= limit and
            (allow_empty or bool(value.strip())) and bool(_SAFE_TEXT.fullmatch(value)))


def _integer(value: Any, *, minimum: int = 0, maximum: int = 10_000_000) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _instant(value: Any) -> int:
    if not _text(value, limit=40):
        raise ReviewBatchError("invalid timestamp")
    match = _OFFSET_TIMESTAMP.fullmatch(value)
    if match is None:
        raise ReviewBatchError("invalid timestamp")
    fraction = match.group("fraction") or ""
    if len(fraction) > 9:
        raise ReviewBatchError("timestamp precision exceeds nanoseconds")
    try:
        if match.group("zone") in {"Z", "z"}:
            offset = timezone.utc
        else:
            offset_hour = int(match.group("offset_hour"))
            offset_minute = int(match.group("offset_minute"))
            if offset_hour >= 24 or offset_minute >= 60:
                raise ValueError("invalid offset")
            offset_delta = timedelta(hours=offset_hour, minutes=offset_minute)
            if match.group("sign") == "-":
                offset_delta = -offset_delta
            offset = timezone(offset_delta)
        parsed = datetime(
            int(match.group("year")), int(match.group("month")), int(match.group("day")),
            int(match.group("hour")), int(match.group("minute")), int(match.group("second")),
            tzinfo=offset,
        ).astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ReviewBatchError("invalid timestamp") from exc
    seconds = calendar.timegm(parsed.utctimetuple())
    nanos = int(fraction.ljust(9, "0")) if fraction else 0
    return seconds * _NANOSECONDS_PER_SECOND + nanos


def _iso(value: int) -> str:
    seconds, nanos = divmod(value, _NANOSECONDS_PER_SECOND)
    instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    fraction = f".{nanos:09d}".rstrip("0") if nanos else ""
    return (f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}T"
            f"{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}{fraction}Z")


def _record(value: Any) -> bool:
    return isinstance(value, dict)


def _policy(value: Any) -> dict[str, Any]:
    if not _record(value) or set(value) != _POLICY_KEYS:
        raise ReviewBatchError("policy must provide the complete explicit contract")
    if not _text(value["version"]) or value["recipe_id"] != "synthetic_age_service_redistribute_v1":
        raise ReviewBatchError("unsupported policy")
    if value["tie_rule"] != "priority_then_occurrence_id":
        raise ReviewBatchError("unsupported tie rule")
    integer_bounds = {
        "k": (0, 10_000), "ranked_slots": (0, 10_000), "audit_slots": (0, 10_000),
        "unresolved_slots": (0, 10_000), "seed": (0, 2**31 - 1),
        "page_size": (1, 200), "service_age_hours": (0, 24 * 365),
        "service_slots": (0, 10_000), "role_coverage_slots": (0, 10_000),
        "overload_threshold": (1, 10_000), "retry_max_overdue_hours": (1, 24 * 365),
        "max_candidate_count": (1, MAX_POLICY_CANDIDATES),
        "max_replacements": (0, 10_000), "max_revalidation_work": (0, MAX_POLICY_CANDIDATES),
        "max_elapsed_seconds": (0, 24 * 60 * 60),
    }
    for key, (minimum, maximum) in integer_bounds.items():
        if not _integer(value[key], minimum=minimum, maximum=maximum):
            raise ReviewBatchError("policy contains invalid bounds")
    if value["k"] != value["ranked_slots"] + value["audit_slots"] + value["unresolved_slots"]:
        raise ReviewBatchError("policy allocations must sum to K")
    if value["service_slots"] > value["ranked_slots"]:
        raise ReviewBatchError("policy service allocation exceeds ranked slots")
    if value["role_coverage_slots"] > value["ranked_slots"] - value["service_slots"]:
        raise ReviewBatchError("policy role coverage allocation exceeds ranked slots")
    order = value["redistribution_order"]
    if (not isinstance(order, list) or len(order) != len(_BUCKETS) or
            any(not isinstance(item, str) for item in order) or len(set(order)) != len(_BUCKETS) or
            set(order) != set(_BUCKETS)):
        raise ReviewBatchError("policy redistribution order is invalid")
    return dict(value)


def _safe_list(value: Any, *, limit: int, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ReviewBatchError(f"invalid {label}")
    if any(not _text(item, limit=256) for item in value) or len(set(value)) != len(value):
        raise ReviewBatchError(f"invalid {label}")
    return list(value)


def _validate_candidate(value: Any) -> dict[str, Any]:
    if not _record(value) or not _CANDIDATE_REQUIRED.issubset(value):
        raise ReviewBatchError("candidate record is incomplete")
    if not _text(value["candidate_id"], limit=128) or not _text(value["source_id"], limit=128):
        raise ReviewBatchError("candidate identity is invalid")
    if not _text(value["posting_identity"], limit=256) or not _text(value["content_identity"], limit=512):
        raise ReviewBatchError("candidate identity is invalid")
    requisition_id = value["requisition_id"]
    if requisition_id is not None and not _text(requisition_id, limit=256):
        raise ReviewBatchError("candidate requisition identity is invalid")
    for key in ("source_revision", "content_revision"):
        if not _integer(value[key], minimum=1, maximum=9_007_199_254_740_991):
            raise ReviewBatchError("candidate revision is invalid")
    assessment_revision = value["assessment_content_revision"]
    if assessment_revision is not None and not _integer(
            assessment_revision, minimum=1, maximum=9_007_199_254_740_991):
        raise ReviewBatchError("assessment revision is invalid")
    if value["priority_order"] is not None and not _integer(value["priority_order"], maximum=10_000_000):
        raise ReviewBatchError("candidate priority order is invalid")
    if type(value["confirmed_application"]) is not bool or type(value["manual_terminal"]) is not bool:
        raise ReviewBatchError("candidate state is invalid")
    if not isinstance(value["kind"], str) or value["kind"] not in _CANDIDATE_KINDS:
        raise ReviewBatchError("candidate kind is invalid")
    for key in ("assessment_version", "assessment_state", "eligibility_state", "yoe_state", "source_state"):
        if value[key] is not None and not _text(value[key], limit=128):
            raise ReviewBatchError("candidate state is invalid")
    role_ids = _safe_list(value["role_family_ids"], limit=64, label="role family IDs")
    group_ids = _safe_list(value["group_ids"], limit=128, label="group IDs")
    provenance = _safe_list(value["provenance"], limit=128, label="provenance")
    for key in ("title", "company"):
        if value[key] is not None and not _text(value[key], allow_empty=True, limit=512):
            raise ReviewBatchError("candidate display source is invalid")
    first_instant = _try_instant(value["first_eligible_at"])
    deferred_instant = _try_instant(value["deferred_at"]) if value["deferred_at"] is not None else None
    retry_instant = _try_instant(value["retry_due_at"]) if value["retry_due_at"] is not None else None
    return {
        **value,
        "requisition_id": requisition_id,
        "role_family_ids": role_ids,
        "group_ids": group_ids,
        "provenance": provenance,
        "first_eligible_at": _iso(first_instant) if first_instant is not None else None,
        "deferred_at": _iso(deferred_instant) if deferred_instant is not None else None,
        "retry_due_at": _iso(retry_instant) if retry_instant is not None else None,
        "first_eligible_instant": first_instant,
        "deferred_instant": deferred_instant,
        "retry_due_instant": retry_instant,
    }


def _try_instant(value: Any) -> int | None:
    try:
        return _instant(value)
    except ReviewBatchError:
        return None


def _confirmed_applications(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20_000:
        raise ReviewBatchError("application evidence is invalid")
    result = []
    for application in value:
        if not _record(application) or not {"application_id", "confirmed", "posting_id", "requisition_id"}.issubset(application):
            raise ReviewBatchError("application evidence is invalid")
        if not _text(application["application_id"], limit=128) or type(application["confirmed"]) is not bool:
            raise ReviewBatchError("application evidence is invalid")
        for key in ("posting_id", "requisition_id"):
            if application[key] is not None and not _text(application[key], limit=256):
                raise ReviewBatchError("application evidence is invalid")
        result.append(application)
    return result


def _window(value: Any, now: int) -> dict[str, Any]:
    required = {"resume_from", "cutoff_at", "include_historic_backfill"}
    if not _record(value) or not required.issubset(value) or type(value["include_historic_backfill"]) is not bool:
        raise ReviewBatchError("window contract is invalid")
    resume_from = _instant(value["resume_from"])
    cutoff = _instant(value["cutoff_at"])
    if resume_from >= cutoff or now < cutoff:
        raise ReviewBatchError("window interval is invalid")
    return {
        "resume_from": _iso(resume_from),
        "cutoff_at": _iso(cutoff),
        "include_historic_backfill": value["include_historic_backfill"],
        "_resume_instant": resume_from,
        "_cutoff_instant": cutoff,
    }


def _fixture(value: Any) -> dict[str, Any]:
    if not _record(value) or value.get("schema_version") != SCHEMA_VERSION or type(value.get("schema_version")) is not int:
        raise ReviewBatchError("unsupported fixture schema")
    if value.get("synthetic") is not True:
        raise ReviewBatchError("fixture must be explicitly synthetic")
    if not _text(value.get("pool_id"), limit=128):
        raise ReviewBatchError("pool identity is invalid")
    policy = _policy(value.get("policy"))
    now = _instant(value.get("now"))
    window = _window(value.get("window"), now)
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > policy["max_candidate_count"]:
        raise ReviewBatchError("candidate pool exceeds explicit cap")
    normalized = [_validate_candidate(item) for item in candidates]
    candidate_ids = [item["candidate_id"] for item in normalized]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ReviewBatchError("candidate IDs must be unique")
    candidate_id_set = set(candidate_ids)
    source_by_id = {item["candidate_id"]: item["source_id"] for item in normalized}
    applications = _confirmed_applications(value.get("applications"))
    duplicate_evidence = value.get("duplicate_evidence")
    if not isinstance(duplicate_evidence, list) or len(duplicate_evidence) > len(normalized) * 2:
        raise ReviewBatchError("duplicate evidence is invalid")
    for item in duplicate_evidence:
        if (not _record(item) or item.get("kind") != "cross_source_corroboration" or
                not _text(item.get("evidence_id"), limit=128)):
            raise ReviewBatchError("duplicate evidence is invalid")
        refs = item.get("candidate_ids")
        if (not isinstance(refs, list) or len(refs) < 2 or len(refs) > 128 or
                any(not isinstance(ref, str) or ref not in candidate_id_set for ref in refs) or
                len(set(refs)) != len(refs)):
            raise ReviewBatchError("duplicate evidence is invalid")
        sources = {source_by_id[ref] for ref in refs}
        if len(sources) < 2:
            raise ReviewBatchError("cross-source evidence must name different sources")
    return {
        "pool_id": value["pool_id"], "now": _iso(now), "_now_instant": now,
        "window": window, "policy": policy, "candidates": normalized,
        "applications": applications, "duplicate_evidence": duplicate_evidence,
    }


def _application_matches(candidate: dict[str, Any], applications: list[dict[str, Any]]) -> bool:
    return bool(candidate["confirmed_application"]) or any(
        app["confirmed"] and (
            app["posting_id"] is not None and app["posting_id"] == candidate["posting_identity"] or
            app["requisition_id"] is not None and app["requisition_id"] == candidate["requisition_id"]
        )
        for app in applications
    )


def _occurrence_id(pool_id: str, candidate: dict[str, Any]) -> str:
    value = [pool_id, candidate["posting_identity"], candidate["source_revision"]]
    return "occ_" + _digest(value)[:24]


def _captured_versions(candidate: dict[str, Any], application: bool) -> dict[str, Any]:
    keys = (
        "source_id", "posting_identity", "requisition_id", "source_revision",
        "content_revision", "content_identity", "assessment_version",
        "assessment_state", "assessment_content_revision", "eligibility_state", "yoe_state",
        "source_state", "priority_order", "kind", "first_eligible_at", "deferred_at",
        "retry_due_at", "role_family_ids", "group_ids", "provenance",
    )
    return {**{key: candidate[key] for key in keys},
            "confirmed_application": application,
            "manual_terminal": candidate["manual_terminal"]}


def _classify(candidate: dict[str, Any], fixture: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    window = fixture["window"]
    now = fixture["_now_instant"]
    cutoff = window["_cutoff_instant"]
    resume = window["_resume_instant"]
    kind = candidate["kind"]
    first = candidate["first_eligible_instant"]

    if kind in {"newly_retained", "newly_assessed"}:
        if first is None:
            return "unresolved", "invalid_first_eligible_time", False
        if first < resume:
            return None, "before_resume_interval", True
        if first >= cutoff:
            return None, "outside_cutoff_interval", True
    elif kind == "deferred":
        deferred = candidate["deferred_instant"]
        if deferred is None:
            return "unresolved", "invalid_deferred_time", False
        if deferred >= cutoff:
            return None, "deferred_after_cutoff", True
    elif kind == "retry":
        due = candidate["retry_due_instant"]
        if due is None:
            return "unresolved", "invalid_retry_due_time", False
        if due >= cutoff or due > now:
            return None, "retry_not_due", True
        overdue_limit = fixture["policy"]["retry_max_overdue_hours"] * 60 * 60 * _NANOSECONDS_PER_SECOND
        if now - due > overdue_limit:
            return "unresolved", "retry_overdue_threshold_exceeded", False
    elif kind == "historic":
        if not window["include_historic_backfill"]:
            return None, "historic_backfill_not_enabled", True
        if first is None:
            return "unresolved", "invalid_first_eligible_time", False
        if first >= cutoff:
            return None, "outside_cutoff_interval", True

    application = _application_matches(candidate, fixture["applications"])
    if application:
        return None, "confirmed_application", True
    if candidate["manual_terminal"]:
        return None, "manual_terminal", True
    if candidate["source_state"] == "closed":
        return None, "source_closed", True

    if candidate["source_state"] not in {"open", "closed", "unknown"}:
        return "unresolved", "unknown_source_state", False
    if candidate["source_state"] == "unknown":
        return "unresolved", "unknown_source_state", False
    if candidate["yoe_state"] == "exclude":
        return None, "yoe_excluded", True
    if candidate["assessment_state"] != "current":
        return "unresolved", "assessment_not_current", False
    if candidate["assessment_content_revision"] != candidate["content_revision"]:
        return "unresolved", "assessment_content_mismatch", False
    if not _text(candidate["assessment_version"], limit=128):
        return "unresolved", "assessment_version_missing", False
    if candidate["eligibility_state"] == "ineligible":
        return None, "eligibility_excluded", True
    if candidate["eligibility_state"] != "eligible":
        return "unresolved", "eligibility_unknown", False
    if candidate["yoe_state"] != "pass":
        return "unresolved", "yoe_unknown", False
    if candidate["priority_order"] is None:
        return "unresolved", "priority_order_missing", False
    if first is None:
        return "unresolved", "invalid_first_eligible_time", False
    return "ranked", None, False


def _stable_key(row: dict[str, Any]) -> tuple[int, str]:
    return (row["priority_order"] if row["priority_order"] is not None else 2**31, row["occurrence_id"])


def priority_order(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order by caller-supplied priority, then a stable occurrence identity."""
    return sorted(candidates, key=_stable_key)


def oldest_first(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serve older pending entries first, using priority and identity for ties."""
    def key(row: dict[str, Any]) -> tuple[int, int, str]:
        instant = _try_instant(row.get("first_eligible_at")) or 2**100
        priority = row.get("priority_order")
        return instant, priority if priority is not None else 2**31, row["occurrence_id"]
    return sorted(candidates, key=key)


def greedy_role_coverage(candidates: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Greedily cover the broadest and rarest caller-supplied role families."""
    pool = list(candidates)
    if not _integer(limit, maximum=10_000):
        raise ReviewBatchError("role coverage limit is invalid")
    frequencies: dict[str, int] = {}
    for row in pool:
        for role in row.get("role_family_ids", []):
            frequencies[role] = frequencies.get(role, 0) + 1
    uncovered = set(frequencies)
    selected: list[dict[str, Any]] = []
    while pool and len(selected) < limit:
        def key(row: dict[str, Any]) -> tuple[float, int, int, str]:
            new_roles = set(row.get("role_family_ids", [])) & uncovered
            rare_coverage = sum(1.0 / frequencies[role] for role in new_roles)
            return (-rare_coverage, -len(new_roles), *_stable_key(row))
        chosen = min(pool, key=key)
        pool.remove(chosen)
        selected.append(chosen)
        uncovered.difference_update(chosen.get("role_family_ids", []))
    return selected


def uniform_audit_sample(candidates: Iterable[dict[str, Any]], sample_size: int, *, seed: int) -> tuple[list[str], list[str], float]:
    """Sample without replacement from a frozen frame and report its probability."""
    rows = sorted(candidates, key=lambda row: row["occurrence_id"])
    if not _integer(sample_size, maximum=10_000) or not _integer(seed, maximum=2**31 - 1):
        raise ReviewBatchError("audit sample parameters are invalid")
    frame = [row["occurrence_id"] for row in rows]
    size = min(sample_size, len(frame))
    sample = random.Random(seed).sample(frame, size) if size else []
    probability = (size / len(frame)) if frame else 0.0
    return frame, sample, probability


def _is_aged(row: dict[str, Any], now: int, age_hours: int) -> bool:
    if row["kind"] not in {"deferred", "retry"}:
        return False
    first = _try_instant(row["first_eligible_at"])
    return first is not None and now - first >= age_hours * 60 * 60 * _NANOSECONDS_PER_SECOND


def _ranked_sequence(rows: list[dict[str, Any]], fixture: dict[str, Any], *, overloaded: bool) -> list[dict[str, Any]]:
    policy = fixture["policy"]
    remaining = list(rows)
    selected: list[dict[str, Any]] = []
    if overloaded and policy["service_slots"]:
        aged = [row for row in remaining if _is_aged(row, fixture["_now_instant"], policy["service_age_hours"])]
        served = oldest_first(aged)[:policy["service_slots"]]
        selected.extend(served)
        served_ids = {row["candidate_id"] for row in served}
        remaining = [row for row in remaining if row["candidate_id"] not in served_ids]
    covered = greedy_role_coverage(remaining, policy["role_coverage_slots"])
    selected.extend(covered)
    covered_ids = {row["candidate_id"] for row in covered}
    remaining = [row for row in remaining if row["candidate_id"] not in covered_ids]
    selected.extend(priority_order(remaining))
    return selected


def _candidate_view(candidate: dict[str, Any], bucket: str, reason: str | None, application: bool,
                    pool_id: str, duplicate_ids: list[str] | None = None,
                    duplicate_review_flags: list[str] | None = None,
                    duplicate_evidence_ids: list[str] | None = None,
                    provenance: list[str] | None = None, group_ids: list[str] | None = None) -> dict[str, Any]:
    occurrence_id = _occurrence_id(pool_id, candidate)
    return {
        "candidate_id": candidate["candidate_id"],
        "occurrence_id": occurrence_id,
        "source_id": candidate["source_id"],
        "posting_identity": candidate["posting_identity"],
        "requisition_id": candidate["requisition_id"],
        "source_revision": candidate["source_revision"],
        "content_revision": candidate["content_revision"],
        "content_identity": candidate["content_identity"],
        "assessment_version": candidate["assessment_version"],
        "assessment_state": candidate["assessment_state"],
        "assessment_content_revision": candidate["assessment_content_revision"],
        "eligibility_state": candidate["eligibility_state"],
        "yoe_state": candidate["yoe_state"],
        "source_state": candidate["source_state"],
        "priority_order": candidate["priority_order"],
        "kind": candidate["kind"],
        "first_eligible_at": candidate["first_eligible_at"],
        "deferred_at": candidate["deferred_at"],
        "retry_due_at": candidate["retry_due_at"],
        "role_family_ids": list(candidate["role_family_ids"]),
        "group_ids": sorted(group_ids if group_ids is not None else candidate["group_ids"]),
        "provenance": sorted(provenance if provenance is not None else candidate["provenance"]),
        "bucket": bucket,
        "reason": reason,
        "confirmed_application": application,
        "manual_terminal": candidate["manual_terminal"],
        "collapsed_candidate_ids": sorted(duplicate_ids or []),
        "duplicate_review_flags": sorted(set(duplicate_review_flags or [])),
        "duplicate_evidence_ids": sorted(set(duplicate_evidence_ids or [])),
        "captured_input_versions": _captured_versions(candidate, application),
    }


def _similarity_flags(candidates: list[dict[str, Any]]) -> dict[str, set[str]]:
    flags: dict[str, set[str]] = {row["candidate_id"]: set() for row in candidates}
    normalized: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        title = " ".join((row.get("title") or "").lower().split())
        company = " ".join((row.get("company") or "").lower().split())
        if title and company:
            normalized.setdefault(title + "\0" + company, []).append(row)
    for group in normalized.values():
        if len(group) > 1:
            for row in group:
                flags[row["candidate_id"]].add("title_company_similarity")
    return flags


def _duplicate_groups(candidates: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    parent = {row["candidate_id"]: row["candidate_id"] for row in candidates}

    def root(candidate_id: str) -> str:
        while parent[candidate_id] != candidate_id:
            parent[candidate_id] = parent[parent[candidate_id]]
            candidate_id = parent[candidate_id]
        return candidate_id

    def join(left: str, right: str) -> None:
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    exact: dict[tuple[str, str], list[str]] = {}
    for row in candidates:
        requisition = row["requisition_id"]
        if requisition:
            exact.setdefault((row["source_id"], requisition), []).append(row["candidate_id"])
    for ids in exact.values():
        for other in ids[1:]:
            join(ids[0], other)
    for item in evidence:
        ids = item["candidate_ids"]
        for other in ids[1:]:
            join(ids[0], other)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        grouped.setdefault(root(row["candidate_id"]), []).append(row)
    return [sorted(group, key=lambda row: row["candidate_id"]) for group in grouped.values()]


def _analyze(value: Any) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    fixture = _fixture(value)
    excluded: list[dict[str, Any]] = []
    classified: list[dict[str, Any]] = []
    application_flags: dict[str, bool] = {}
    for candidate in fixture["candidates"]:
        application_flags[candidate["candidate_id"]] = _application_matches(candidate, fixture["applications"])
        bucket, reason, omit = _classify(candidate, fixture)
        if omit:
            excluded.append({"candidate_id": candidate["candidate_id"], "reason": reason})
            continue
        classified.append((candidate, bucket, reason, application_flags[candidate["candidate_id"]]))

    classified_by_id = {row[0]["candidate_id"]: row for row in classified}
    candidates = [row[0] for row in classified]
    flags = _similarity_flags(candidates)
    records: list[dict[str, Any]] = []
    for group in _duplicate_groups(candidates, fixture["duplicate_evidence"]):
        representative = group[0]
        buckets = {classified_by_id[row["candidate_id"]][1] for row in group}
        if len(buckets) > 1:
            bucket = "unresolved"
            reason = "duplicate_state_conflict"
        else:
            bucket = next(iter(buckets))
            reason = classified_by_id[representative["candidate_id"]][2]
        member_ids = {row["candidate_id"] for row in group}
        merged_flags = set().union(*(flags[row_id] for row_id in member_ids))
        evidence_ids = [item["evidence_id"] for item in fixture["duplicate_evidence"]
                        if member_ids.intersection(item["candidate_ids"])]
        provenance = sorted({item for row in group for item in row["provenance"]})
        group_ids = sorted({item for row in group for item in row["group_ids"]})
        collapsed = sorted(member_ids - {representative["candidate_id"]})
        records.append(_candidate_view(
            representative, bucket, reason, application_flags[representative["candidate_id"]],
            fixture["pool_id"], collapsed, list(merged_flags), evidence_ids, provenance, group_ids,
        ))
    records.sort(key=lambda row: row["occurrence_id"])
    return fixture, records, excluded


def _allocation_targets(rows: list[dict[str, Any]], unresolved: list[dict[str, Any]], policy: dict[str, Any],
                        fixture: dict[str, Any]) -> tuple[Any, ...]:
    overloaded = len(rows) + len(unresolved) > policy["overload_threshold"]
    ranked_order = _ranked_sequence(rows, fixture, overloaded=overloaded)
    unresolved_order = oldest_first(unresolved)
    ranked_count = min(policy["ranked_slots"], len(ranked_order))
    unresolved_count = min(policy["unresolved_slots"], len(unresolved_order))
    audit_frame = ranked_order[ranked_count:]
    audit_count = min(policy["audit_slots"], len(audit_frame))
    initial = {"ranked": ranked_count, "audit": audit_count, "unresolved": unresolved_count}
    targets = dict(initial)
    total = policy["k"]
    while sum(targets.values()) < total:
        changed = False
        for category in policy["redistribution_order"]:
            capacity = {
                "ranked": len(ranked_order) - targets["ranked"] - targets["audit"],
                "audit": len(ranked_order) - targets["ranked"] - targets["audit"],
                "unresolved": len(unresolved_order) - targets["unresolved"],
            }[category]
            if capacity > 0:
                targets[category] += 1
                changed = True
                break
        if not changed:
            break
    ranked_count = targets["ranked"]
    audit_count = targets["audit"]
    unresolved_count = targets["unresolved"]
    ranked_selected = ranked_order[:ranked_count]
    frozen_audit_frame = ranked_order[ranked_count:]
    if audit_count > len(frozen_audit_frame):
        audit_count = len(frozen_audit_frame)
        targets["audit"] = audit_count
    frame_ids, sample_ids, probability = uniform_audit_sample(
        frozen_audit_frame, audit_count, seed=policy["seed"]
    )
    audit_rows = {row["occurrence_id"]: row for row in frozen_audit_frame}
    audit_selected = [audit_rows[item] for item in sample_ids]
    unresolved_selected = unresolved_order[:unresolved_count]
    return (ranked_selected, unresolved_selected, frame_ids, initial, targets,
            total - sum(targets.values()), audit_selected, probability)


def build_review_batch(snapshot: Any) -> dict[str, Any]:
    """Build a fixed deterministic selection from an explicit synthetic fixture."""
    fixture, records, excluded = _analyze(snapshot)
    policy = fixture["policy"]
    eligible = [row for row in records if row["bucket"] == "ranked"]
    unresolved = [row for row in records if row["bucket"] == "unresolved"]
    ranked, unresolved_selected, audit_frame_ids, initial, effective, unfilled, audit_selected, probability = (
        _allocation_targets(eligible, unresolved, policy, fixture)
    )
    slots: list[dict[str, Any]] = []
    selected_rows = {
        "ranked": ranked,
        "audit": audit_selected,
        "unresolved": unresolved_selected,
    }
    for category in ("ranked", "audit", "unresolved"):
        for row in selected_rows[category]:
            slots.append({
                "slot_id": f"slot_{len(slots) + 1:04d}",
                "category": category,
                "candidate_id": row["candidate_id"],
                "occurrence_id": row["occurrence_id"],
                "invalidated": None,
                "replacement": None,
            })
    # The order is frozen once and never changes during paging or revalidation.
    ordered_slots = list(slots)
    all_candidates = {row["candidate_id"]: row for row in records}
    policy_id = _digest(policy)
    public_window = {key: value for key, value in fixture["window"].items() if not key.startswith("_")}
    snapshot_id = _digest({
        "pool_id": fixture["pool_id"], "window": public_window,
        "policy_id": policy_id,
        "versions": sorted((row["candidate_id"], row["captured_input_versions"]) for row in records),
    })
    batch_id = _digest({"pool_id": fixture["pool_id"], "snapshot_id": snapshot_id})[:32]
    initial_total = sum(initial.values())
    report = {
        "input_candidate_count": len(fixture["candidates"]),
        "included_occurrence_count": len(records),
        "available_count": len(eligible),
        "unresolved_count": len(unresolved),
        "excluded_count": len(excluded),
        "excluded_reason_counts": {
            reason: sum(item["reason"] == reason for item in excluded)
            for reason in sorted({item["reason"] for item in excluded})
        },
        "deferred_count": sum(row["kind"] == "deferred" for row in records),
        "due_retry_count": sum(row["kind"] == "retry" for row in records),
        "collapsed_duplicates": sum(len(row["collapsed_candidate_ids"]) for row in records),
        "possible_duplicate_review_count": sum(bool(row["duplicate_review_flags"]) for row in records),
        "overloaded": len(eligible) + len(unresolved) > policy["overload_threshold"],
        "total_slots": policy["k"],
        "initial_selections": initial,
        "effective_allocations": effective,
        "redistributed_slots": {key: max(0, effective[key] - initial[key]) for key in _BUCKETS},
        "initial_selected_count": initial_total,
        "replacement_entries": 0,
        "invalidations": 0,
        "active_slots": len(slots),
        "unfilled_slots": unfilled,
        "audit_frame_size": len(audit_frame_ids),
        "audit_inclusion_probability": probability,
        "provider_calls": 0,
        "actually_read": "unknown",
        "delivered": "unknown",
        "downstream_cost": "unknown",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": BATCH_SCOPE,
        "synthetic": True,
        "pool_id": fixture["pool_id"],
        "now": fixture["now"],
        "window": public_window,
        "policy": policy,
        "policy_id": policy_id,
        "batch_id": batch_id,
        "snapshot_id": snapshot_id,
        "candidate_records": records,
        "entries": all_candidates,
        "excluded": sorted(excluded, key=lambda row: (row["reason"], row["candidate_id"])),
        "audit_frame_ids": audit_frame_ids,
        "audit_selected_ids": [row["occurrence_id"] for row in audit_selected],
        "ordered_slot_ids": [row["slot_id"] for row in ordered_slots],
        "slots": slots,
        "report": report,
    }


def _cursor(batch: dict[str, Any], start: int) -> str:
    size = batch["policy"]["page_size"]
    end = min(start + size, len(batch["slots"]))
    scope = _digest([batch["batch_id"], batch["snapshot_id"], size, start, end])[:20]
    return f"rb1.{batch['batch_id']}.{start}.{scope}"


def page_review_batch(batch: Any, cursor: str | None = None) -> dict[str, Any]:
    """Return one frozen page; repeated cursors are deterministic and idempotent."""
    if (not _record(batch) or batch.get("scope") != BATCH_SCOPE or batch.get("synthetic") is not True or
            not isinstance(batch.get("slots"), list) or not _record(batch.get("policy"))):
        raise ReviewBatchError("invalid batch state")
    size = batch["policy"].get("page_size")
    if not _integer(size, minimum=1, maximum=200):
        raise ReviewBatchError("invalid batch page size")
    start = 0
    if cursor is not None:
        if not isinstance(cursor, str) or len(cursor) > 128:
            raise ReviewBatchError("invalid cursor")
        parts = cursor.split(".") if isinstance(cursor, str) else []
        if len(parts) != 4 or parts[0] != "rb1" or parts[1] != batch.get("batch_id"):
            raise ReviewBatchError("invalid cursor")
        try:
            start = int(parts[2])
        except ValueError as exc:
            raise ReviewBatchError("invalid cursor") from exc
        if start <= 0 or start >= len(batch["slots"]):
            raise ReviewBatchError("invalid cursor")
        if _cursor(batch, start) != cursor:
            raise ReviewBatchError("invalid cursor")
    end = min(start + size, len(batch["slots"]))
    scope = _digest([batch["batch_id"], batch["snapshot_id"], size, start, end])[:20]
    entries = batch.get("entries", {})
    items = []
    for slot in batch["slots"][start:end]:
        current = slot.get("replacement") or entries.get(slot.get("candidate_id"))
        items.append({
            "slot_id": slot["slot_id"],
            "category": slot["category"],
            "candidate": current,
            "invalidated": slot.get("invalidated"),
            "replacement": slot.get("replacement"),
        })
    next_cursor = _cursor(batch, end) if end < len(batch["slots"]) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "synthetic_review_batch_page",
        "synthetic": True,
        "batch_id": batch["batch_id"],
        "snapshot_id": batch["snapshot_id"],
        "page_scope": scope,
        "start": start,
        "end": end,
        "items": items,
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
        "actually_read": "unknown",
        "delivered": "unknown",
    }


def _invalidation_reason(original: dict[str, Any], current: dict[str, Any] | None,
                         excluded_reason: str | None = None) -> str | None:
    if current is None:
        if excluded_reason is not None:
            return excluded_reason
        return "missing_from_current_pool"
    old = original["captured_input_versions"]
    new = current["captured_input_versions"]
    if old["source_revision"] != new["source_revision"]:
        return "source_revision_changed"
    if old["content_revision"] != new["content_revision"] or old["content_identity"] != new["content_identity"]:
        return "content_changed"
    if current["source_state"] == "closed":
        return "source_closed"
    if current["confirmed_application"]:
        return "confirmed_application"
    if current["manual_terminal"]:
        return "manual_terminal"
    if current["bucket"] != original["bucket"]:
        return current.get("reason") or "eligibility_changed"
    if old != new:
        return "captured_input_changed"
    return None


def revalidate_review_batch(batch: Any, current_snapshot: Any, *, elapsed_seconds: int) -> dict[str, Any]:
    """Invalidate changed frozen entries and annotate bounded same-category replacements."""
    if not _record(batch) or batch.get("scope") != BATCH_SCOPE or batch.get("synthetic") is not True:
        raise ReviewBatchError("invalid batch state")
    if not _integer(elapsed_seconds, maximum=24 * 60 * 60):
        raise ReviewBatchError("elapsed time is invalid")
    current_fixture, current_records, current_excluded = _analyze(current_snapshot)
    if current_fixture["pool_id"] != batch.get("pool_id") or _digest(current_fixture["policy"]) != batch.get("policy_id"):
        raise ReviewBatchError("revalidation identity changed")
    current_by_id = {row["candidate_id"]: row for row in current_records}
    excluded_by_id = {row["candidate_id"]: row["reason"] for row in current_excluded}
    entries = dict(batch["entries"])
    slots = [dict(slot) for slot in batch["slots"]]
    used_candidate_ids: set[str] = set()
    invalidations = 0
    replacement_count = 0
    work = 0
    cap_reached = elapsed_seconds > batch["policy"]["max_elapsed_seconds"]
    invalidated_candidate_ids: set[str] = set()

    for slot in slots:
        original = entries.get(slot["candidate_id"])
        current = current_by_id.get(slot["candidate_id"])
        reason = _invalidation_reason(original or {}, current, excluded_by_id.get(slot["candidate_id"]))
        if reason is None:
            slot["invalidated"] = None
            slot["replacement"] = None
            used_candidate_ids.add(slot["candidate_id"])
            continue
        slot["invalidated"] = {"candidate_id": slot["candidate_id"], "reason": reason}
        slot["replacement"] = None
        invalidations += 1
        invalidated_candidate_ids.add(slot["candidate_id"])

        if cap_reached or replacement_count >= batch["policy"]["max_replacements"]:
            continue
        target_category = slot["category"]
        candidate_bucket = "unresolved" if target_category == "unresolved" else "ranked"
        candidates = [
            row for row in current_records
            if row["bucket"] == candidate_bucket and row["candidate_id"] not in used_candidate_ids and
            row["candidate_id"] not in invalidated_candidate_ids and
            row["candidate_id"] not in {other["candidate_id"] for other in slots if other["invalidated"] is None}
        ]
        if target_category == "audit":
            frozen = set(batch["audit_frame_ids"])
            candidates = [row for row in candidates if row["occurrence_id"] in frozen]
            candidates.sort(key=lambda row: row["occurrence_id"])
        elif target_category == "ranked":
            candidates = priority_order(candidates)
        else:
            candidates = oldest_first(candidates)
        replacement = None
        for row in candidates:
            if work >= batch["policy"]["max_revalidation_work"]:
                break
            work += 1
            if row["candidate_id"] in used_candidate_ids:
                continue
            replacement = row
            break
        if replacement is not None and work <= batch["policy"]["max_revalidation_work"]:
            slot["replacement"] = {
                **replacement,
                "replacement_for_slot_id": slot["slot_id"],
                "replaces_occurrence_id": slot["occurrence_id"],
            }
            used_candidate_ids.add(replacement["candidate_id"])
            replacement_count += 1

    updated = dict(batch)
    updated["entries"] = entries
    updated["slots"] = slots
    report = dict(batch["report"])
    report.update({
        "invalidations": invalidations,
        "replacement_entries": replacement_count,
        "active_slots": sum(slot["replacement"] is not None or slot["invalidated"] is None for slot in slots),
        "unfilled_slots": report["total_slots"] - sum(slot["replacement"] is not None or slot["invalidated"] is None for slot in slots),
        "revalidation_work": work,
        "work_cap_reached": work >= batch["policy"]["max_revalidation_work"] and invalidations > replacement_count,
        "time_cap_reached": cap_reached,
        "observed_elapsed_seconds": elapsed_seconds,
    })
    updated["report"] = report
    return updated


def summary(batch: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded public synthetic report, excluding candidate text and state maps."""
    slot_categories = {category: sum(slot["category"] == category for slot in batch["slots"])
                       for category in _BUCKETS}
    invalidated = [slot for slot in batch["slots"] if slot["invalidated"]]
    replaced = [slot for slot in batch["slots"] if slot["replacement"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": BATCH_SCOPE,
        "synthetic": True,
        "pool_id": batch["pool_id"],
        "now": batch["now"],
        "window": batch["window"],
        "policy": batch["policy"],
        "policy_id": batch["policy_id"],
        "batch_id": batch["batch_id"],
        "snapshot_id": batch["snapshot_id"],
        "report": batch["report"],
        "excluded_sample": batch["excluded"][:32],
        "excluded_sample_truncated": len(batch["excluded"]) > 32,
        "slot_count": len(batch["slots"]),
        "slot_counts_by_category": slot_categories,
        "invalidated_sample": [{
            "slot_id": slot["slot_id"],
            "candidate_id": slot["invalidated"]["candidate_id"],
            "reason": slot["invalidated"]["reason"],
        } for slot in invalidated[:32]],
        "invalidated_sample_truncated": len(invalidated) > 32,
        "replacement_sample": [{
            "slot_id": slot["slot_id"],
            "candidate_id": slot["replacement"]["candidate_id"],
            "occurrence_id": slot["replacement"]["occurrence_id"],
            "replaces_occurrence_id": slot["replacement"]["replaces_occurrence_id"],
        } for slot in replaced[:32]],
        "replacement_sample_truncated": len(replaced) > 32,
        "slot_preview": [{
            "slot_id": slot["slot_id"],
            "category": slot["category"],
            "candidate_id": slot["candidate_id"],
            "occurrence_id": slot["occurrence_id"],
            "invalidated": slot["invalidated"],
            "replacement": ({
                "candidate_id": slot["replacement"]["candidate_id"],
                "occurrence_id": slot["replacement"]["occurrence_id"],
                "replacement_for_slot_id": slot["replacement"]["replacement_for_slot_id"],
                "replaces_occurrence_id": slot["replacement"]["replaces_occurrence_id"],
            } if slot["replacement"] else None),
        } for slot in batch["slots"][:32]],
        "slot_preview_truncated": len(batch["slots"]) > 32,
    }
