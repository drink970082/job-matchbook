"""Compose the synthetic assessment view and review batch through fixture reads only.

This module accepts all state as arguments. It has no runtime, provider, database,
profile, resume, configuration, network, or scheduling dependencies.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any

from .preselection_view import VIEW_SCHEMA_VERSION, project_assessment_view
from .review_batch import (
    SCHEMA_VERSION as REVIEW_BATCH_SCHEMA_VERSION,
    build_review_batch,
    page_review_batch,
    revalidate_review_batch,
)


REHEARSAL_SCHEMA_VERSION = 1
REHEARSAL_SCOPE = "synthetic_rehearsal"
MAX_FIXTURE_BYTES = 1_000_000
MAX_SCENARIO_CANDIDATES = 10_000
MAX_JD_CHARS = 10_000
MAX_JD_CHUNK_SIZE = 512
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ERROR_CATEGORIES = frozenset({
    "timeout", "connection_error", "rate_limited", "provider_unavailable",
    "invalid_response", "unknown_error", "fixture_missing",
})
_REQUIRED_RUN_LIMITS = frozenset({
    "max_tool_calls", "max_read_chars", "max_jd_chunks", "max_unranked_candidates",
    "max_elapsed_seconds", "max_replacements",
})
_OPTIONAL_MONITORING_LIMITS = frozenset({
    "max_queue_age_hours", "max_overload_count", "max_provider_cost_credits",
})
_REVALIDATION_FIELDS = frozenset({
    "source_revision", "content_revision", "content_identity", "source_state",
    "confirmed_application", "manual_terminal", "eligibility_state", "yoe_state",
    "assessment_state", "assessment_content_revision",
})


class RehearsalError(ValueError):
    """A malformed fixture, policy, or bounded rehearsal request."""


def _record(value: Any) -> bool:
    return isinstance(value, dict)


def _integer(value: Any, *, minimum: int = 0, maximum: int = 1_000_000) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _safe_text(value: Any, *, maximum: int = MAX_JD_CHARS) -> bool:
    return (isinstance(value, str) and len(value) <= maximum
            and all(character.isprintable() for character in value))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _scenario_contract(value: Any) -> dict[str, Any]:
    if (not _record(value) or value.get("fixture_schema_version") != 1
            or type(value.get("fixture_schema_version")) is not int
            or value.get("synthetic") is not True
            or not _identifier(value.get("scenario_id"))):
        raise RehearsalError("invalid synthetic rehearsal scenario")
    clock = value.get("clock")
    monitoring = value.get("monitoring")
    if (not _record(clock) or not _integer(clock.get("elapsed_seconds"), maximum=86_400)
            or not _record(monitoring)
            or not _integer(monitoring.get("cadence_seconds"), minimum=1, maximum=86_400)):
        raise RehearsalError("invalid synthetic monitoring contract")
    limits = monitoring.get("limits")
    if not _record(limits) or not _REQUIRED_RUN_LIMITS.issubset(limits):
        raise RehearsalError("explicit rehearsal bounds are required")
    limit_ranges = {
        "max_tool_calls": (1, 500), "max_read_chars": (1, 1_000_000),
        "max_jd_chunks": (1, 1000), "max_unranked_candidates": (1, 200),
        "max_elapsed_seconds": (0, 86_400), "max_replacements": (0, 10_000),
    }
    for key, (minimum, maximum) in limit_ranges.items():
        if not _integer(limits.get(key), minimum=minimum, maximum=maximum):
            raise RehearsalError("invalid explicit rehearsal bound")
    for key in _OPTIONAL_MONITORING_LIMITS:
        if key in limits and limits[key] is not None and not _integer(limits[key]):
            raise RehearsalError("invalid optional monitoring limit")

    bindings = value.get("assessment_bindings")
    if not _record(bindings) or len(bindings) > 128:
        raise RehearsalError("invalid assessment case bindings")
    if any(not _identifier(candidate_id) or not _identifier(case_name)
           for candidate_id, case_name in bindings.items()):
        raise RehearsalError("invalid assessment case binding")

    descriptions = value.get("job_descriptions")
    if not _record(descriptions) or len(descriptions) > 128:
        raise RehearsalError("invalid synthetic job descriptions")
    if any(not _identifier(candidate_id) or not _safe_text(text)
           for candidate_id, text in descriptions.items()):
        raise RehearsalError("invalid synthetic job description")
    chunk_size = value.get("job_description_chunk_size")
    if not _integer(chunk_size, minimum=1, maximum=MAX_JD_CHUNK_SIZE):
        raise RehearsalError("invalid synthetic chunk size")

    probes = value.get("source_probes")
    if not isinstance(probes, list) or len(probes) > 32:
        raise RehearsalError("invalid source probe fixture")
    for probe in probes:
        if (not _record(probe) or not _identifier(probe.get("source_id"))
                or not isinstance(probe.get("outcome"), str)
                or probe.get("outcome") not in {"empty", "unavailable"}):
            raise RehearsalError("invalid source probe fixture")
        category = probe.get("error_category")
        if probe["outcome"] == "empty":
            if category is not None:
                raise RehearsalError("empty source probe cannot have an error")
        elif not isinstance(category, str) or category not in _ERROR_CATEGORIES:
            raise RehearsalError("unavailable source probe needs an error category")

    probable = value.get("probable_applications")
    if not isinstance(probable, list) or len(probable) > 100:
        raise RehearsalError("invalid probable application fixtures")
    for item in probable:
        if (not _record(item) or not _identifier(item.get("application_id"))
                or not _identifier(item.get("candidate_id"))
                or item.get("certainty") != "probable"):
            raise RehearsalError("invalid probable application fixture")

    additions = value.get("additional_candidates", [])
    if not isinstance(additions, list) or len(additions) > 100:
        raise RehearsalError("invalid additional candidate fixtures")
    changes = value.get("revalidation_changes")
    if not _record(changes) or len(changes) > 100:
        raise RehearsalError("invalid revalidation change fixtures")
    for candidate_id, update in changes.items():
        if (not _identifier(candidate_id) or not _record(update) or not update
                or not set(update).issubset(_REVALIDATION_FIELDS)):
            raise RehearsalError("invalid revalidation change fixture")
    elapsed = value.get("revalidation_elapsed_seconds")
    if not _integer(elapsed, maximum=86_400):
        raise RehearsalError("invalid revalidation elapsed time")

    repeat = value.get("repeat_day")
    if (not _record(repeat) or not _identifier(repeat.get("pool_id"))
            or not _identifier(repeat.get("candidate_id"))
            or _parse_timestamp(repeat.get("now")) is None
            or not _record(repeat.get("window"))):
        raise RehearsalError("invalid repeated day fixture")
    fallback_limit = value.get("fallback_candidate_limit")
    if (not _integer(fallback_limit, minimum=1, maximum=200)
            or fallback_limit > limits["max_unranked_candidates"]):
        raise RehearsalError("fallback limit exceeds explicit bound")
    faults = value.get("simulated_faults")
    if (not _record(faults)
            or not isinstance(faults.get("provider_state"), str)
            or faults.get("provider_state") not in {"circuit_open", "available"}
            or not isinstance(faults.get("provider_error_category"), str)
            or faults.get("provider_error_category") not in _ERROR_CATEGORIES
            or not isinstance(faults.get("private_input_access"), str)
            or faults.get("private_input_access") not in {"available", "unavailable"}
            or not isinstance(faults.get("private_input_error_category"), str)
            or faults.get("private_input_error_category") not in _ERROR_CATEGORIES):
        raise RehearsalError("invalid simulated fault fixture")
    return value


class FixtureReadAdapter:
    """Small read-tool-shaped adapter backed only by caller-supplied fixtures."""

    def __init__(self, scenario: dict[str, Any], assessment_fixture: dict[str, Any],
                 pool_fixture: dict[str, Any], batch: dict[str, Any]):
        self._scenario = scenario
        self._assessment_fixture = assessment_fixture
        self._pool_fixture = pool_fixture
        self._batch = batch
        self._limits = scenario["monitoring"]["limits"]
        self.tool_calls = 0
        self.calls_by_tool: dict[str, int] = {}
        self.read_characters = 0
        self.jd_chunks = 0
        self.multi_chunk_candidates = 0
        self._chunk_counts: dict[str, int] = {}
        self.assessment_views: dict[str, dict[str, Any]] = {}
        self._case_by_name = {
            case["name"]: case for case in assessment_fixture["cases"]
        }
        self._candidates_by_id = {
            item["candidate_id"]: item for item in pool_fixture["candidates"]
        }

    def _count(self, tool_name: str) -> None:
        if self.tool_calls >= self._limits["max_tool_calls"]:
            raise RehearsalError("synthetic tool call bound exceeded")
        self.tool_calls += 1
        self.calls_by_tool[tool_name] = self.calls_by_tool.get(tool_name, 0) + 1

    def list_jobs(self, cursor: str | None = None) -> dict[str, Any]:
        self._count("list_jobs")
        return page_review_batch(self._batch, cursor)

    def get_assessment(self, candidate_id: str) -> dict[str, Any]:
        self._count("get_assessment")
        case_name = self._scenario["assessment_bindings"].get(candidate_id, "current_success")
        case = self._case_by_name.get(case_name)
        if case is None:
            raise RehearsalError("assessment fixture case is missing")
        view = project_assessment_view(case.get("snapshot"))
        self.assessment_views[candidate_id] = view
        latest = view["latest_attempt"]
        return {
            "candidate_id": candidate_id,
            "case_name": case_name,
            "assessment_state": view["assessment_state"],
            "assessment_reason": view["assessment_reason"],
            "latest_attempt_state": latest["state"],
            "error_category": latest["error_category"],
        }

    def get_job_description(self, candidate_id: str, offset: int) -> dict[str, Any]:
        self._count("get_job_description")
        text = self._scenario["job_descriptions"].get(candidate_id, "")
        size = self._scenario["job_description_chunk_size"]
        chunk = text[offset:offset + size]
        if self.read_characters + len(chunk) > self._limits["max_read_chars"]:
            raise RehearsalError("synthetic read character bound exceeded")
        if chunk:
            self.read_characters += len(chunk)
            self.jd_chunks += 1
            self._chunk_counts[candidate_id] = self._chunk_counts.get(candidate_id, 0) + 1
            if self.jd_chunks > self._limits["max_jd_chunks"]:
                raise RehearsalError("synthetic JD chunk bound exceeded")
        next_offset = offset + len(chunk)
        return {
            "chunk": chunk,
            "next_offset": next_offset,
            "has_more": next_offset < len(text),
        }

    def finish_description_reads(self) -> None:
        self.multi_chunk_candidates = sum(count > 1 for count in self._chunk_counts.values())

    def list_applications(self, candidate_id: str) -> list[dict[str, Any]]:
        self._count("list_applications")
        candidate = self._candidates_by_id.get(candidate_id)
        if candidate is None:
            candidate = next((item for item in self._scenario.get("additional_candidates", [])
                              if item.get("candidate_id") == candidate_id), None)
        if candidate is None:
            return []
        exact: list[dict[str, Any]] = []
        for application in self._pool_fixture.get("applications", []):
            if (application.get("confirmed") is True and (
                    application.get("posting_id") is not None
                    and application["posting_id"] == candidate.get("posting_identity")
                    or application.get("requisition_id") is not None
                    and application["requisition_id"] == candidate.get("requisition_id"))):
                exact.append({
                    "candidate_id": candidate_id,
                    "application_id": application["application_id"],
                    "certainty": "exact",
                    "confirmed": True,
                    "suppresses_candidate": True,
                })
        probable = [
            {
                "candidate_id": candidate_id,
                "application_id": item["application_id"],
                "certainty": "probable",
                "confirmed": False,
                "suppresses_candidate": False,
            }
            for item in self._scenario.get("probable_applications", [])
            if item["candidate_id"] == candidate_id
        ]
        return exact + probable

    def probe_source(self, probe: dict[str, Any]) -> dict[str, Any]:
        self._count("probe_source")
        return {
            "source_id": probe["source_id"],
            "outcome": probe["outcome"],
            "error_category": probe.get("error_category"),
            "synthetic": True,
        }

    def list_unranked_candidates(self, limit: int) -> list[dict[str, Any]]:
        self._count("list_unranked_candidates")
        rows = sorted(self._batch["candidate_records"], key=lambda row: row["candidate_id"])
        return rows[:limit]


def _assessment_fixture_contract(value: Any) -> dict[str, Any]:
    if (not _record(value) or value.get("fixture_schema_version") != 1
            or type(value.get("fixture_schema_version")) is not int
            or value.get("synthetic") is not True or not isinstance(value.get("cases"), list)
            or len(value["cases"]) > 32):
        raise RehearsalError("invalid synthetic assessment fixture")
    names: set[str] = set()
    for case in value["cases"]:
        if (not _record(case) or not _identifier(case.get("name"))
                or case["name"] in names or "snapshot" not in case):
            raise RehearsalError("invalid synthetic assessment case")
        names.add(case["name"])
    return value


def _pool_with_additions(pool_fixture: Any, scenario: dict[str, Any]) -> dict[str, Any]:
    if (not _record(pool_fixture) or pool_fixture.get("schema_version") != 1
            or type(pool_fixture.get("schema_version")) is not int
            or pool_fixture.get("synthetic") is not True
            or not isinstance(pool_fixture.get("candidates"), list)
            or not _record(pool_fixture.get("policy"))):
        raise RehearsalError("invalid synthetic candidate pool")
    pool = deepcopy(pool_fixture)
    existing = {item.get("candidate_id") for item in pool["candidates"] if _record(item)}
    for candidate in scenario.get("additional_candidates", []):
        if not _record(candidate) or not _identifier(candidate.get("candidate_id")):
            raise RehearsalError("invalid additional candidate")
        if candidate["candidate_id"] in existing:
            raise RehearsalError("duplicate additional candidate")
        pool["candidates"].append(deepcopy(candidate))
        existing.add(candidate["candidate_id"])
    if len(pool["candidates"]) > MAX_SCENARIO_CANDIDATES:
        raise RehearsalError("synthetic candidate limit exceeded")
    return pool


def _apply_revalidation_changes(pool_fixture: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    changed = deepcopy(pool_fixture)
    rows = {item["candidate_id"]: item for item in changed["candidates"]}
    for candidate_id, update in scenario["revalidation_changes"].items():
        candidate = rows.get(candidate_id)
        if candidate is None:
            raise RehearsalError("revalidation candidate is missing")
        candidate.update(deepcopy(update))
    return changed


def _case(name: str, observed: bool, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if observed else "failed",
        "observed": detail or {},
    }


def run_synthetic_rehearsal(scenario_value: Any, assessment_fixture_value: Any,
                            pool_fixture_value: Any) -> dict[str, Any]:
    """Run one deterministic fixture rehearsal and return a private-safe report."""
    scenario = _scenario_contract(scenario_value)
    assessment_fixture = _assessment_fixture_contract(assessment_fixture_value)
    pool_fixture = _pool_with_additions(pool_fixture_value, scenario)
    replacement_limit = scenario["monitoring"]["limits"]["max_replacements"]
    if replacement_limit != pool_fixture.get("policy", {}).get("max_replacements"):
        raise RehearsalError("monitoring and batch replacement limits must agree")
    case_names = {case["name"] for case in assessment_fixture["cases"]}
    if any(case_name not in case_names for case_name in scenario["assessment_bindings"].values()):
        raise RehearsalError("assessment fixture binding is missing")
    if any(item["candidate_id"] not in {row["candidate_id"] for row in pool_fixture["candidates"]}
           for item in scenario["probable_applications"]):
        raise RehearsalError("probable application candidate is missing")

    batch = build_review_batch(pool_fixture)
    adapter = FixtureReadAdapter(scenario, assessment_fixture, pool_fixture, batch)
    pages: list[dict[str, Any]] = []
    page_items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = adapter.list_jobs(cursor)
        pages.append({"start": page["start"], "end": page["end"], "item_count": len(page["items"])})
        page_items.extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
        if len(pages) >= 200:
            raise RehearsalError("synthetic page bound exceeded")

    assessments: dict[str, dict[str, Any]] = {}
    for item in page_items:
        candidate_id = item["candidate"]["candidate_id"]
        if candidate_id not in assessments:
            assessments[candidate_id] = adapter.get_assessment(candidate_id)

    for item in page_items:
        candidate_id = item["candidate"]["candidate_id"]
        offset = 0
        while True:
            chunk = adapter.get_job_description(candidate_id, offset)
            offset = chunk["next_offset"]
            if not chunk["has_more"]:
                break
    adapter.finish_description_reads()

    application_candidate_ids = {item["candidate_id"] for item in pool_fixture["candidates"]}
    application_candidate_ids.update(item["candidate_id"] for item in scenario["probable_applications"])
    applications = [
        application
        for candidate_id in sorted(application_candidate_ids)
        for application in adapter.list_applications(candidate_id)
    ]
    probes = [adapter.probe_source(probe) for probe in scenario["source_probes"]]

    revalidation_pool = _apply_revalidation_changes(pool_fixture, scenario)
    revalidated = revalidate_review_batch(
        batch, revalidation_pool, elapsed_seconds=scenario["revalidation_elapsed_seconds"]
    )
    revalidation_report = revalidated["report"]

    repeat_config = scenario["repeat_day"]
    repeated_pool = deepcopy(pool_fixture)
    repeated_pool["pool_id"] = repeat_config["pool_id"]
    repeated_pool["now"] = repeat_config["now"]
    repeated_pool["window"] = deepcopy(repeat_config["window"])
    repeated = build_review_batch(repeated_pool)
    repeated_id = repeat_config["candidate_id"]
    first_row = next((row for row in batch["candidate_records"]
                      if row["candidate_id"] == repeated_id), None)
    next_row = next((row for row in repeated["candidate_records"]
                     if row["candidate_id"] == repeated_id), None)
    if first_row is None or next_row is None:
        raise RehearsalError("repeated day candidate is not in both fixture pools")

    fallback_limit = scenario["fallback_candidate_limit"]
    fallback_rows = adapter.list_unranked_candidates(fallback_limit)
    for row in fallback_rows:
        candidate_id = row["candidate_id"]
        if candidate_id not in assessments:
            assessments[candidate_id] = adapter.get_assessment(candidate_id)
    applications_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for evidence in applications:
        applications_by_candidate.setdefault(evidence["candidate_id"], []).append(evidence)
    slots_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for slot in batch["slots"]:
        slots_by_candidate.setdefault(slot["candidate_id"], []).append(slot)
    fallback_candidates = [
        {
            "candidate_id": row["candidate_id"],
            "assessment_state": assessments[row["candidate_id"]]["assessment_state"],
            "application_certainty": max(
                (item["certainty"] for item in applications_by_candidate.get(row["candidate_id"], [])),
                key=lambda certainty: {"none": 0, "probable": 1, "exact": 2}[certainty],
                default="none",
            ),
            "batch_evidence": {
                "occurrence_id": row["occurrence_id"],
                "selected_categories": sorted({slot["category"] for slot in
                                                slots_by_candidate.get(row["candidate_id"], [])}),
                "was_selected": row["candidate_id"] in slots_by_candidate,
            },
        }
        for row in fallback_rows
    ]

    now = _parse_timestamp(batch["now"])
    ages: list[tuple[str, float]] = []
    if now is not None:
        for candidate in pool_fixture["candidates"]:
            eligible = _parse_timestamp(candidate.get("first_eligible_at"))
            if eligible is not None:
                ages.append((candidate["candidate_id"], max(0.0, (now - eligible).total_seconds() / 3600)))
    oldest_age = max((age for _, age in ages), default=0.0)
    age_limit = scenario["monitoring"]["limits"].get("max_queue_age_hours")
    aged_candidates = sorted(candidate_id for candidate_id, age in ages
                             if age_limit is not None and age > age_limit)
    overload_count = batch["report"]["available_count"] + batch["report"]["unresolved_count"]
    overload_limit = scenario["monitoring"]["limits"].get("max_overload_count")
    policy_overloaded = batch["report"]["overloaded"]

    monitoring_breaches: list[str] = []
    limits = scenario["monitoring"]["limits"]
    if scenario["clock"]["elapsed_seconds"] > limits["max_elapsed_seconds"]:
        monitoring_breaches.append("elapsed_time_limit_exceeded")
    if age_limit is not None and aged_candidates:
        monitoring_breaches.append("queue_age_limit_exceeded")
    if overload_limit is not None and overload_count > overload_limit:
        monitoring_breaches.append("overload_limit_exceeded")
    if (limits["max_replacements"] is not None
            and revalidation_report["replacement_entries"] > limits["max_replacements"]):
        monitoring_breaches.append("replacement_limit_exceeded")

    fault_config = scenario["simulated_faults"]
    assessment_states = {item["assessment_state"] for item in assessments.values()}
    has_provider_error = any(item["latest_attempt_state"] == "provider_error"
                             for item in assessments.values())
    exact_application_seen = any(item["certainty"] == "exact" and item["suppresses_candidate"]
                                 for item in applications)
    probable_application_seen = any(item["certainty"] == "probable" and not item["suppresses_candidate"]
                                    for item in applications)
    empty_probe_seen = any(item["outcome"] == "empty" and item["error_category"] is None for item in probes)
    unavailable_probe_seen = any(item["outcome"] == "unavailable" and item["error_category"]
                                 for item in probes)
    checks = [
        _case("multi_page_multi_chunk", len(pages) >= 2 and adapter.multi_chunk_candidates >= 2, {
            "pages": len(pages), "chunks": adapter.jd_chunks,
            "multi_chunk_candidates": adapter.multi_chunk_candidates,
        }),
        _case("empty_vs_unavailable_source", empty_probe_seen and unavailable_probe_seen, {
            "empty_probe_count": sum(item["outcome"] == "empty" for item in probes),
            "unavailable_probe_count": sum(item["outcome"] == "unavailable" for item in probes),
        }),
        _case("assessment_states_and_late_result", {"current", "stale", "unknown"} <= assessment_states
              and has_provider_error and any(item["case_name"] == "late_result_for_older_content"
                                             and item["assessment_state"] == "stale"
                                             for item in assessments.values()), {
            "states_seen": sorted(assessment_states), "provider_error_seen": has_provider_error,
        }),
        _case("exact_and_probable_application_identity", exact_application_seen and probable_application_seen, {
            "exact_suppressed": exact_application_seen, "probable_suppressed": False,
        }),
        _case("bounded_revalidation", revalidation_report["invalidations"] >= 2
              and revalidation_report["replacement_entries"] <= limits["max_replacements"]
              and revalidation_report["unfilled_slots"] >= 1, {
            "invalidations": revalidation_report["invalidations"],
            "replacement_count": revalidation_report["replacement_entries"],
            "unfilled_slots": revalidation_report["unfilled_slots"],
        }),
        _case("age_and_overload_monitoring", policy_overloaded and oldest_age > 0, {
            "overloaded": policy_overloaded, "overload_count": overload_count,
            "oldest_age_hours": round(oldest_age, 3),
        }),
        _case("provider_outage_and_private_input", fault_config["provider_state"] == "circuit_open"
              and fault_config["private_input_access"] == "unavailable", {
            "simulation_only": True, "provider_call_count": 0, "private_input_read_attempted": False,
        }),
        _case("local_unranked_fallback", len(fallback_candidates) <= fallback_limit
              and [item["candidate_id"] for item in fallback_candidates]
              == sorted(item["candidate_id"] for item in fallback_candidates), {
            "ranking_enabled": False, "candidate_count": len(fallback_candidates),
        }),
        _case("repeated_day_occurrence_identity", first_row["occurrence_id"] != next_row["occurrence_id"]
              and first_row["source_revision"] == next_row["source_revision"]
              and first_row["content_revision"] == next_row["content_revision"], {
            "candidate_id": repeated_id, "same_source_revision": True,
            "same_content_revision": True,
        }),
    ]
    error_categories = {
        category for category in (
            *(item.get("error_category") for item in probes),
            *(item.get("error_category") for item in assessments.values()),
            fault_config.get("provider_error_category"), fault_config.get("private_input_error_category"),
        ) if category is not None
    }
    unknown_limits = sorted(
        name for name in _OPTIONAL_MONITORING_LIMITS
        if limits.get(name) is None
    )

    return {
        "schema_version": REHEARSAL_SCHEMA_VERSION,
        "scope": REHEARSAL_SCOPE,
        "synthetic": True,
        "scenario_id": scenario["scenario_id"],
        "modules": {
            "assessment_view": VIEW_SCHEMA_VERSION,
            "review_batch": REVIEW_BATCH_SCHEMA_VERSION,
            "rehearsal": REHEARSAL_SCHEMA_VERSION,
        },
        "fixture_versions": {
            "scenario": scenario["fixture_schema_version"],
            "assessment": assessment_fixture["fixture_schema_version"],
            "candidate_pool": pool_fixture["schema_version"],
            "review_policy": pool_fixture["policy"]["version"],
        },
        "clock": {
            "now": batch["now"],
            "cutoff_at": batch["window"]["cutoff_at"],
            "elapsed_seconds": scenario["clock"]["elapsed_seconds"],
            "time_source": "injected_fixture",
        },
        "monitoring": {
            "cadence_seconds": scenario["monitoring"]["cadence_seconds"],
            "limits": deepcopy(limits),
            "unknown_limits": unknown_limits,
            "breaches": list(monitoring_breaches),
        },
        "monitoring_breaches": monitoring_breaches,
        "error_categories": sorted(error_categories),
        "observations": {
            "batch": {
                "batch_id": batch["batch_id"],
                "pool_id": batch["pool_id"],
                "pages_read": len(pages),
                "pages": pages,
                "slot_count": len(batch["slots"]),
                "available_count": batch["report"]["available_count"],
                "unresolved_count": batch["report"]["unresolved_count"],
                "excluded_count": batch["report"]["excluded_count"],
                "due_retry_count": batch["report"]["due_retry_count"],
                "deferred_count": batch["report"]["deferred_count"],
                "provider_calls": batch["report"]["provider_calls"],
                "actually_read": "unknown",
                "delivered": "unknown",
            },
            "tool_calls": {
                "count": adapter.tool_calls,
                "by_tool": dict(sorted(adapter.calls_by_tool.items())),
            },
            "job_description_reads": {
                "chunk_count": adapter.jd_chunks,
                "characters_read": adapter.read_characters,
                "multi_chunk_count": adapter.multi_chunk_candidates,
                "chunk_size": scenario["job_description_chunk_size"],
            },
            "assessments": [assessments[key] for key in sorted(assessments)],
            "applications": sorted(applications, key=lambda item: (item["candidate_id"], item["certainty"])),
            "source_probes": probes,
            "queue": {
                "overloaded": policy_overloaded,
                "overload_count": overload_count,
                "oldest_age_hours": round(oldest_age, 3),
                "aged_candidate_ids": aged_candidates,
                "age_limit_hours": age_limit if age_limit is not None else "unknown",
                "overload_limit": overload_limit if overload_limit is not None else "unknown",
            },
            "revalidation": {
                "invalidations": revalidation_report["invalidations"],
                "replacement_count": revalidation_report["replacement_entries"],
                "unfilled_slots": revalidation_report["unfilled_slots"],
                "revalidation_work": revalidation_report["revalidation_work"],
                "time_cap_reached": revalidation_report["time_cap_reached"],
                "elapsed_seconds": scenario["revalidation_elapsed_seconds"],
                "max_replacements": batch["policy"]["max_replacements"],
            },
            "repeated_day": {
                "candidate_id": repeated_id,
                "first_occurrence_id": first_row["occurrence_id"],
                "next_occurrence_id": next_row["occurrence_id"],
                "same_content_revision": first_row["content_revision"] == next_row["content_revision"],
                "same_content_identity": first_row["content_identity"] == next_row["content_identity"],
                "limitation": "synthetic pool membership does not establish daily delivery or reading",
            },
            "simulated_faults": {
                "provider": {
                    "state": fault_config["provider_state"],
                    "error_category": fault_config["provider_error_category"],
                    "simulation_only": True,
                },
                "private_input_access": {
                    "state": fault_config["private_input_access"],
                    "error_category": fault_config["private_input_error_category"],
                    "read_attempted": False,
                    "simulation_only": True,
                },
            },
            "fallback": {
                "ranking_enabled": False,
                "order": "stable_candidate_id",
                "limit": fallback_limit,
                "candidates": fallback_candidates,
                "application_evidence": sorted(
                    applications, key=lambda item: (item["candidate_id"], item["certainty"])
                ),
            },
            "resource_status": {
                "provider_call_count": 0,
                "actual_provider_cost": "unknown",
                "live_provider_price": "not_recorded",
                "read_acknowledgement": "unknown",
                "delivery_acknowledgement": "unknown",
            },
        },
        "cases": checks,
        "live_gates": {
            "scheduled_access": "not_exercised",
            "provider_quality_and_price": "not_recorded",
            "assessment_go": "not_exercised",
            "read_and_delivery_acknowledgements": "not_recorded",
            "production_fallback_or_rollback": "not_exercised",
        },
    }
