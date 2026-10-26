"""Bounded, allowlisted read access to the application-owned ATS SQLite schema."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

from ..source_lifecycle import (SOURCE_ERROR_CATEGORIES, assessment_freshness,
                                has_embedded_screen, has_fit_assessment)


DEFAULT_BUSY_TIMEOUT_MS = 5_000
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
TEXT_CHUNK_SIZE = 16_000
MAX_SEARCH_CHARS = 200
MAX_FILTER_CHARS = 200
MAX_CURSOR_CHARS = 1_024
MAX_CURSOR_KEY_CHARS = 300
MAX_RFC3339_CHARS = 40
MAX_SCREEN_REASON_CHARS = 300
MAX_SCREEN_PROVENANCE_CHARS = 120
MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
MAX_SAFE_REVISION = 9_007_199_254_740_991

REQUIRED_TABLES = frozenset({
    "applications",
    "job_postings",
    "job_screenings",
    "status_history",
    "watched_companies",
    "feed_unresolved",
    "promotion_dismissed",
    "app_settings",
})

PIPELINE_STATUSES = frozenset({
    "new", "scored", "notified", "applied", "discarded", "failed", "removed", "expired",
})
APPLICATION_STATUSES = frozenset({
    "Applied", "Online Assessment", "Phone Screen", "Interviewing: 1st round",
    "Interviewing: 2nd round", "Interviewing: 3rd round", "Interviewing: 4th round",
    "Interviewing: 5th round", "Final Round", "Offer", "Accepted", "Rejected",
    "Withdrew", "Ghosted",
})

# This is the allowlist for all dynamic table names and primary keys. User input selects
# only an entry from this closed map; it never becomes a SQL identifier.
ENTITY_KEYS: dict[str, tuple[str, str, str]] = {
    "applications": ("applications", "id", "int"),
    "job_postings": ("job_postings", "id", "int"),
    "job_screenings": ("job_screenings", "id", "int"),
    "status_history": ("status_history", "id", "int"),
    "watched_companies": ("watched_companies", "id", "int"),
    "feed_unresolved": ("feed_unresolved", "id", "int"),
    "promotion_dismissed": ("promotion_dismissed", "id", "int"),
    "app_settings": ("app_settings", "key", "str"),
}

LIST_OMIT_FIELDS = {
    "applications": frozenset({"notes"}),
    "job_postings": frozenset({"description", "score_detail"}),
    "job_screenings": frozenset({"result_json"}),
}

SAFE_SETTING_VALUE_KEYS = frozenset({"categories"})
REDACTED = "[REDACTED]"
MALFORMED_RECIPE = "[withheld: malformed recipe cannot be safely redacted]"
UNREVIEWED_SETTING = "[withheld: setting key has no approved read policy]"

_SECRET_QUERY_KEYS = frozenset({
    "token", "accesstoken", "authtoken", "auth", "authorization", "apikey", "key",
    "secret", "clientsecret", "signature", "sig", "password", "passwd",
    "credential", "credentials", "accesskey", "jwt",
})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RFC3339_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt](?P<hour>\d{2}):(?P<minute>\d{2}):"
    r"(?P<second>\d{2})(?P<fraction>\.\d+)?(?P<zone>[Zz]|[+-]\d{2}:\d{2})$"
)
_STORED_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt ](?P<hour>\d{2}):(?P<minute>\d{2}):"
    r"(?P<second>\d{2})(?P<fraction>\.\d+)?(?P<zone>[Zz]|[+-]\d{2}:\d{2})?$"
)
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_INTEGER_KEY_RE = re.compile(r"^[1-9]\d{0,9}$")

SCREEN_OUTCOMES = (
    "not_screened", "provider_error", "disqualified", "no_disqualifier_found", "unknown",
)
_SCREEN_OUTCOME_SET = frozenset(SCREEN_OUTCOMES)
TRIAGE_STATUSES = (
    "rule_disqualified", "screen_disqualified", "candidate", "needs_review",
)
_TRIAGE_STATUS_SET = frozenset(TRIAGE_STATUSES)
_KNOWN_PIPELINE_STATUSES = frozenset(PIPELINE_STATUSES)
_ACTIVE_CANDIDATE_STATUSES = frozenset({"new", "scored", "notified"})
_SUPPORTED_SCREEN_CHECKS = frozenset({
    "location", "internships", "degree", "authorization", "clearance",
})
_DETERMINISTIC_SCREEN_CHECKS = frozenset({"location", "internships"})
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SAFE_SCREEN_JSON_SQL = "CASE WHEN json_valid(s.result_json) THEN s.result_json ELSE '{}' END"
_MAX_TIMESTAMP_CHARS = MAX_RFC3339_CHARS


def _timestamp_key(value: Any) -> tuple[int, str] | None:
    """Return exact UTC parts for a supported timestamp with an explicit zone."""
    if not isinstance(value, str) or len(value) > _MAX_TIMESTAMP_CHARS:
        return None
    match = _STORED_TIMESTAMP_RE.fullmatch(value)
    if match is None:
        return None
    zone = match.group("zone")
    if zone is None:
        return None
    zone_for_parser = "+00:00" if zone in {"Z", "z"} else zone
    base = (f"{match.group('date')}T{match.group('hour')}:{match.group('minute')}:"
            f"{match.group('second')}{zone_for_parser}")
    try:
        parsed = datetime.fromisoformat(base)
        delta = parsed.astimezone(timezone.utc) - _UTC_EPOCH
    except (ValueError, OverflowError):
        return None
    seconds = delta.days * 86_400 + delta.seconds
    fraction = (match.group("fraction") or "").lstrip(".").rstrip("0")
    return seconds, fraction


def _compare_timestamp_keys(left: tuple[int, str], right: tuple[int, str]) -> int:
    if left[0] != right[0]:
        return -1 if left[0] < right[0] else 1
    width = max(len(left[1]), len(right[1]))
    left_fraction = left[1].ljust(width, "0")
    right_fraction = right[1].ljust(width, "0")
    return (left_fraction > right_fraction) - (left_fraction < right_fraction)


def _timestamp_compare(stored: Any, bound: Any) -> int | None:
    left = _timestamp_key(stored)
    right = _timestamp_key(bound)
    return None if left is None or right is None else _compare_timestamp_keys(left, right)


def _parse_rfc3339(value: str | None, name: str) -> str | None:
    value = _bounded_text(value, name, MAX_RFC3339_CHARS, allow_empty=False)
    if value is None:
        return None
    if not _RFC3339_RE.fullmatch(value):
        raise QueryInputError(f"{name} must be an offset-aware RFC3339 instant")
    key = _timestamp_key(value)
    if key is None:
        raise QueryInputError(f"{name} must be a valid RFC3339 instant")
    seconds, fraction = key
    try:
        whole_second = _UTC_EPOCH + timedelta(seconds=seconds)
    except OverflowError:
        raise QueryInputError(f"{name} is outside the supported datetime range") from None
    canonical = whole_second.strftime("%Y-%m-%dT%H:%M:%S")
    if fraction:
        canonical += "." + fraction
    return canonical + "Z"


def _timestamp_valid(value: Any) -> int | None:
    """Return known only for persisted timestamps carrying an explicit UTC offset."""
    key = _timestamp_key(value)
    return 1 if key is not None else None


def _screen_outcome_sql() -> str:
    """SQL outcome logic shared by list filters, summaries, and overview counts."""
    result = _SAFE_SCREEN_JSON_SQL
    failed_check = (
        f"EXISTS (SELECT 1 FROM json_each({result}, '$.screen') AS screen_check "
        "WHERE screen_check.type='object' AND "
        "CASE WHEN screen_check.type='object' "
        "THEN json_type(screen_check.value, '$.pass')='false' ELSE 0 END)"
    )
    passed_check = (
        f"EXISTS (SELECT 1 FROM json_each({result}, '$.screen') AS screen_check "
        "WHERE screen_check.type='object' AND "
        "CASE WHEN screen_check.type='object' "
        "THEN json_type(screen_check.value, '$.pass')='true' ELSE 0 END)"
    )
    return f"""CASE
        WHEN s.id IS NULL THEN 'not_screened'
        WHEN s.state='provider_error' THEN 'provider_error'
        WHEN s.state!='complete' OR json_valid(s.result_json)=0 THEN 'unknown'
        WHEN json_type({result}, '$')!='object' THEN 'unknown'
        WHEN json_type({result}, '$.disqualified')='true'
             AND json_type({result}, '$.screen')='object' AND {failed_check}
            THEN 'disqualified'
        WHEN json_type({result}, '$.disqualified')='false'
             AND json_type({result}, '$.screen')='object'
             AND {passed_check} AND NOT {failed_check}
            THEN 'no_disqualifier_found'
        ELSE 'unknown'
        END"""


def _triage_check_shape_sql(result: str, supported_checks: frozenset[str]) -> str:
    """Whether every stored check is a supported, typed `{pass, note?}` record."""
    checks = ",".join(f"'{key}'" for key in sorted(supported_checks))
    return f"""json_type({result}, '$.screen')='object'
        AND NOT EXISTS (
            SELECT screen_member.key FROM json_each({result}, '$.screen') AS screen_member
            GROUP BY screen_member.key HAVING COUNT(*)>1
        )
        AND NOT EXISTS (
            SELECT 1 FROM json_each({result}, '$.screen') AS triage_check
            WHERE triage_check.type!='object'
               OR triage_check.key NOT IN ({checks})
               OR CASE WHEN triage_check.type='object'
                       THEN COALESCE(json_type(triage_check.value, '$.pass'),'missing')
                            NOT IN ('true','false') ELSE 0 END
               OR CASE WHEN triage_check.type='object'
                       THEN (json_type(triage_check.value, '$.note') IS NOT NULL
                             AND json_type(triage_check.value, '$.note')!='text')
                       ELSE 0 END
               OR CASE WHEN triage_check.type='object' THEN EXISTS (
                    SELECT 1 FROM json_each(triage_check.value) AS triage_field
                    WHERE triage_field.key NOT IN ('pass','note')
               ) ELSE 0 END
               OR CASE WHEN triage_check.type='object' THEN EXISTS (
                    SELECT triage_field.key FROM json_each(triage_check.value) AS triage_field
                    GROUP BY triage_field.key HAVING COUNT(*)>1
               ) ELSE 0 END
        )"""


def _triage_valid_result_sql(result: str, disqualified: bool) -> str:
    """Validate current standalone evidence without changing screen_outcome semantics."""
    check_shape = _triage_check_shape_sql(result, _SUPPORTED_SCREEN_CHECKS)
    root_shape = f"""(json_type({result}, '$.disqualification_reason') IS NULL
            OR json_type({result}, '$.disqualification_reason')='text')
        AND NOT EXISTS (
            SELECT triage_root_field.key FROM json_each({result}) AS triage_root_field
            GROUP BY triage_root_field.key HAVING COUNT(*)>1
        )
        AND NOT EXISTS (SELECT 1 FROM json_each({result}) AS triage_root_field
                        WHERE triage_root_field.key NOT IN
                            ('screen','disqualified','disqualification_reason'))"""
    if disqualified:
        check = "json_type(triage_check.value, '$.pass')='false'"
        flag = "'true'"
        no_failure = "1=1"
    else:
        check = "json_type(triage_check.value, '$.pass')='true'"
        flag = "'false'"
        no_failure = (
            f"NOT EXISTS (SELECT 1 FROM json_each({result}, '$.screen') AS triage_check "
            "WHERE CASE WHEN triage_check.type='object' "
            "THEN json_type(triage_check.value, '$.pass')='false' ELSE 0 END)"
        )
    return f"""s.state='complete' AND json_valid(s.result_json)=1
        AND json_type({result}, '$')='object'
        AND json_type({result}, '$.disqualified')={flag}
        AND {root_shape}
        AND {check_shape}
        AND EXISTS (SELECT 1 FROM json_each({result}, '$.screen') AS triage_check
                    WHERE CASE WHEN triage_check.type='object' THEN {check} ELSE 0 END)
        AND {no_failure}"""


def _triage_rule_only_sql(result: str) -> str:
    rule_shape = _triage_check_shape_sql(result, _DETERMINISTIC_SCREEN_CHECKS)
    return f"""{rule_shape}
        AND json_type({result}, '$.disqualified')='true'
        AND EXISTS (SELECT 1 FROM json_each({result}, '$.screen') AS triage_check
                    WHERE CASE WHEN triage_check.type='object'
                               THEN json_type(triage_check.value, '$.pass')='false' ELSE 0 END)"""


def _triage_status_sql() -> str:
    """Status predicate shared by filters and overview counts; runs before paging."""
    result = "CASE WHEN json_valid(s.result_json) THEN s.result_json ELSE '{}' END"
    legacy = "CASE WHEN json_valid(p.score_detail) THEN p.score_detail ELSE '{}' END"
    legacy_revision = f"json_extract({legacy}, '$.source_content_revision')"
    valid_screen_disqualified = _triage_valid_result_sql(result, True)
    valid_candidate = _triage_valid_result_sql(result, False)
    standalone_rule = _triage_rule_only_sql(result)
    legacy_rule = _triage_rule_only_sql(legacy)
    known_statuses = ",".join(f"'{status}'" for status in sorted(_KNOWN_PIPELINE_STATUSES))
    candidate_statuses = ",".join(f"'{status}'" for status in sorted(_ACTIVE_CANDIDATE_STATUSES))
    legacy_root_shape = f"""json_type({legacy}, '$')='object'
        AND json_type({legacy}, '$.disqualified')='true'
        AND (json_type({legacy}, '$.disqualification_reason') IS NULL
             OR json_type({legacy}, '$.disqualification_reason')='text')
        AND (json_type({legacy}, '$.source_content_revision') IS NULL
             OR json_type({legacy}, '$.source_content_revision')='null'
             OR (json_type({legacy}, '$.source_content_revision') IN ('integer','real')
                 AND {legacy_revision}>0
                 AND {legacy_revision}<={MAX_SAFE_REVISION}
                 AND {legacy_revision}=CAST({legacy_revision} AS INTEGER)))
        AND NOT EXISTS (
            SELECT legacy_field.key FROM json_each({legacy}) AS legacy_field
            GROUP BY legacy_field.key HAVING COUNT(*)>1
        )
        AND NOT EXISTS (SELECT 1 FROM json_each({legacy}) AS legacy_field
                        WHERE legacy_field.key NOT IN
                            ('screen','disqualified','disqualification_reason','source_content_revision'))"""
    return f"""CASE
        WHEN p.pipeline_status IS NULL OR p.pipeline_status NOT IN ({known_statuses})
            THEN 'needs_review'
        WHEN s.id IS NOT NULL AND ({valid_screen_disqualified})
             AND ({standalone_rule}) THEN 'rule_disqualified'
        WHEN s.id IS NOT NULL AND ({valid_screen_disqualified}) THEN 'screen_disqualified'
        WHEN s.id IS NOT NULL AND ({valid_candidate})
             AND p.pipeline_status IN ({candidate_statuses}) THEN 'candidate'
        WHEN s.id IS NULL AND p.pipeline_status='discarded'
             AND json_valid(p.score_detail)=1 AND ({legacy_root_shape})
             AND ({legacy_rule}) THEN 'rule_disqualified'
        ELSE 'needs_review'
    END"""


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None

    def reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, item in pairs:
            if key in parsed:
                raise ValueError("duplicate JSON object member")
            parsed[key] = item
        return parsed

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicate_members)
    except (TypeError, json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _triage_checks(screen: Any, supported: frozenset[str]) -> tuple[bool, bool, bool]:
    """Return (valid, has_failure, has_pass) for a typed supported screen object."""
    if not isinstance(screen, dict) or not screen:
        return False, False, False
    has_failure = False
    has_pass = False
    for key, check in screen.items():
        if key not in supported or not isinstance(check, dict):
            return False, False, False
        if type(check.get("pass")) is not bool:
            return False, False, False
        if set(check) - {"pass", "note"}:
            return False, False, False
        if "note" in check and not isinstance(check["note"], str):
            return False, False, False
        has_failure |= check["pass"] is False
        has_pass |= check["pass"] is True
    return True, has_failure, has_pass


def _standalone_triage_result(raw: Any) -> tuple[str, frozenset[str]]:
    result = _parse_json_object(raw)
    if result is None or set(result) - {"screen", "disqualified", "disqualification_reason"}:
        return "unknown", frozenset()
    if type(result.get("disqualified")) is not bool:
        return "unknown", frozenset()
    reason = result.get("disqualification_reason")
    if "disqualification_reason" in result and not isinstance(reason, str):
        return "unknown", frozenset()
    valid, has_failure, has_pass = _triage_checks(
        result.get("screen"), _SUPPORTED_SCREEN_CHECKS)
    if not valid:
        return "unknown", frozenset()
    if result["disqualified"] is True and has_failure:
        failing = frozenset(
            key for key, check in result["screen"].items() if check["pass"] is False)
        if set(result["screen"]).issubset(_DETERMINISTIC_SCREEN_CHECKS):
            return "rule_disqualified", failing
        return "disqualified", failing
    if result["disqualified"] is False and has_pass and not has_failure:
        return "candidate", frozenset()
    return "unknown", frozenset()


def _legacy_rule_disqualification(pipeline_status: Any, score_detail: Any) -> bool:
    if pipeline_status != "discarded":
        return False
    detail = _parse_json_object(score_detail)
    if detail is None or set(detail) - {
        "screen", "disqualified", "disqualification_reason", "source_content_revision",
    }:
        return False
    if detail.get("disqualified") is not True:
        return False
    reason = detail.get("disqualification_reason")
    if "disqualification_reason" in detail and not isinstance(reason, str):
        return False
    revision = detail.get("source_content_revision")
    if revision is not None and not _positive_safe_json_integer(revision):
        return False
    valid, has_failure, _ = _triage_checks(
        detail.get("screen"), _DETERMINISTIC_SCREEN_CHECKS)
    return valid and has_failure


def _positive_safe_json_integer(value: Any) -> bool:
    """Accept positive integral JSON numbers that JavaScript can represent safely."""
    if type(value) is int:
        return 0 < value <= MAX_SAFE_REVISION
    if type(value) is float:
        return math.isfinite(value) and value.is_integer() and 0 < value <= MAX_SAFE_REVISION
    return False


def job_triage_summary(pipeline_status: Any, score_detail: Any,
                       screening: dict[str, Any] | None) -> dict[str, str]:
    """Derive a bounded evidence-stage summary without changing stored screen outcomes."""
    if screening is not None:
        provenance = "job_screenings"
    elif score_detail is not None:
        provenance = "job_postings.score_detail"
    elif pipeline_status == "discarded":
        provenance = "pipeline_status"
    else:
        provenance = "none"

    def summary(status: str, reason: str) -> dict[str, str]:
        return {"status": status, "reason": reason[:MAX_SCREEN_REASON_CHARS],
                "provenance": provenance}

    if pipeline_status not in _KNOWN_PIPELINE_STATUSES:
        return summary("needs_review", "Stored lifecycle state is unrecognized.")

    if screening is not None:
        if screening.get("state") != "complete":
            return summary("needs_review", "Standalone screening did not complete successfully.")
        result_type, failing_checks = _standalone_triage_result(screening.get("result_json"))
        if result_type in {"rule_disqualified", "disqualified"}:
            if result_type == "rule_disqualified":
                failed_labels = sorted(failing_checks)
                names = " and ".join(failed_labels)
                return summary("rule_disqualified", f"Deterministic {names} rule rejected this posting.")
            return summary("screen_disqualified", "Standalone screening recorded a supported failing requirement.")
        if result_type == "candidate":
            if pipeline_status in _ACTIVE_CANDIDATE_STATUSES:
                return summary("candidate", "Standalone screening found no disqualifier; retained for fit research, not qualified.")
            return summary("needs_review", "A standalone pass conflicts with the stored lifecycle state.")
        return summary("needs_review", "Stored standalone assessment is malformed, contradictory, or unsupported.")

    if _legacy_rule_disqualification(pipeline_status, score_detail):
        detail = _parse_json_object(score_detail) or {}
        failed = sorted(key for key, check in detail["screen"].items() if check["pass"] is False)
        return summary("rule_disqualified", f"Legacy deterministic {' and '.join(failed)} rule rejected this posting.")

    detail = _parse_json_object(score_detail)
    if pipeline_status == "discarded":
        if detail is not None:
            return summary("needs_review", "Legacy fit evidence does not meet the rule-rejection contract.")
        return summary("needs_review", "Discarded lifecycle state alone does not establish a rule rejection.")
    if detail is not None:
        return summary("needs_review", "Legacy fit evidence does not establish current triage status.")
    if score_detail is not None:
        return summary("needs_review", "Stored legacy evidence is malformed or unsupported.")
    return summary("needs_review", "No standalone record or supported legacy rule rejection is stored.")


def _screen_summary(row: dict[str, Any]) -> dict[str, Any]:
    outcome = row.get("screen_outcome", "unknown")
    reason: str | None
    if outcome == "not_screened":
        reason = None
    elif outcome == "provider_error":
        reason = row.get("screening_error_message") or "Screening provider failed; retry is pending."
    elif outcome == "disqualified":
        reason = row.get("screening_reason") or "The stored checked result marks a disqualifier."
    elif outcome == "no_disqualifier_found":
        reason = "No failing typed check was stored; unchecked requirements remain unknown."
    else:
        reason = "The stored assessment is incomplete, contradictory, or not classifiable."

    def bounded_provenance(field: str) -> str | None:
        value = row.get(field)
        return value[:MAX_SCREEN_PROVENANCE_CHARS] if isinstance(value, str) else None

    assessment_time = row.get("screening_updated_at")
    if (not isinstance(assessment_time, str)
            or _timestamp_key(assessment_time) is None):
        assessment_time = None
    else:
        assessment_time = assessment_time[:MAX_RFC3339_CHARS]
    if isinstance(reason, str):
        reason = " ".join(reason.split())
        reason = _URL_IN_TEXT_RE.sub(lambda match: redact_url(match.group(0)), reason)
        reason = reason[:MAX_SCREEN_REASON_CHARS]
    else:
        reason = None
    return {
        "outcome": outcome,
        "is_advisory": True,
        "reason": reason,
        "assessment_time": assessment_time,
        "backend": bounded_provenance("screening_backend"),
        "model": bounded_provenance("screening_model"),
        "effort": bounded_provenance("screening_effort"),
        "evaluator_version": bounded_provenance("screening_evaluator_version"),
        "origin": "job_screenings" if row.get("screening_id") is not None else "none",
    }


def _positive_revision(value: Any) -> int | None:
    """Normalize positive JS-safe integer revisions; booleans and other values are unknown."""
    return value if type(value) is int and 0 < value <= MAX_SAFE_REVISION else None


def _source_lifecycle_summary(row: dict[str, Any], screening: dict[str, Any] | None = None
                              ) -> dict[str, Any]:
    """Return bounded source-state and separate fit/screen freshness metadata."""
    state = row.get("source_state")
    if state not in {"unknown", "available", "closed"}:
        state = "unknown"
    outcome = row.get("source_last_check_outcome")
    if outcome not in {"not_checked", "found", "confirmed_closed", "inconclusive"}:
        outcome = "not_checked"
    current = _positive_revision(row.get("source_content_revision"))

    detail = row.get("score_detail_parsed")
    fit_assessed = (bool(row.get("fit_assessment_available"))
                    if "fit_assessment_available" in row
                    else has_fit_assessment(row.get("score_detail")))
    fit_revision = row.get("fit_content_revision")
    if fit_revision is None and isinstance(detail, dict):
        fit_revision = detail.get("source_content_revision")
    fit_revision = _positive_revision(fit_revision)

    screen_state = ((screening or {}).get("state") or row.get("screening_state"))
    screen_revision = ((screening or {}).get("source_content_revision")
                       if screening is not None else row.get("screening_source_content_revision"))
    screen_revision = _positive_revision(screen_revision)
    standalone_exists = screening is not None or row.get("screening_id") is not None
    legacy_screen = (bool(row.get("legacy_screen_evidence_available"))
                     or has_embedded_screen(row.get("score_detail"))
                     or (isinstance(detail, dict)
                         and isinstance(detail.get("screen"), dict)))
    if standalone_exists:
        if screen_state == "provider_error":
            screen_freshness = "provider_error"
        elif screen_state == "complete":
            screen_freshness = assessment_freshness(
                assessed=True, captured_revision=screen_revision,
                current_revision=current,
            )
        else:
            screen_freshness = "unknown"
    else:
        screen_freshness = "not_assessed"

    category = row.get("source_last_check_error_category")
    if category not in SOURCE_ERROR_CATEGORIES:
        category = None

    def safe_time(field: str) -> str | None:
        value = row.get(field)
        if isinstance(value, str) and _timestamp_key(value) is not None:
            return value[:MAX_RFC3339_CHARS]
        return None

    return {
        "state": state,
        "last_seen_at": safe_time("source_last_seen_at"),
        "last_check_attempted_at": safe_time("source_last_check_attempted_at"),
        "last_checked_at": safe_time("source_last_checked_at"),
        "last_check_outcome": outcome,
        "last_check_error_category": category,
        "content_revision": current,
        "fit_freshness": assessment_freshness(
            assessed=fit_assessed, captured_revision=fit_revision,
            current_revision=current),
        "screen_freshness": screen_freshness,
        "combined_screen_freshness": assessment_freshness(
            assessed=legacy_screen, captured_revision=fit_revision,
            current_revision=current),
    }
_SOURCE_LIFECYCLE_FIELDS = (
    "source_state", "source_last_seen_at", "source_last_check_attempted_at",
    "source_last_checked_at", "source_last_check_outcome",
    "source_last_check_error_category", "source_content_hash",
    "source_content_revision", "source_content_changed_at",
)


def _strip_source_lifecycle_fields(record: dict[str, Any]) -> None:
    """Expose lifecycle metadata only through its validated bounded summary."""
    for field in _SOURCE_LIFECYCLE_FIELDS:
        record.pop(field, None)


class RepositoryError(Exception):
    """An actionable, safe-to-return repository error."""


class QueryInputError(RepositoryError):
    pass


class RecordNotFound(RepositoryError):
    pass


class DatabaseUnavailable(RepositoryError):
    pass


@dataclass(frozen=True)
class _Cursor:
    key: int | str
    extra: int | None = None


def _bounded_text(value: str | None, name: str, maximum: int, *, allow_empty: bool = True) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueryInputError(f"{name} must be text")
    if len(value) > maximum:
        raise QueryInputError(f"{name} is too long (maximum {maximum} characters)")
    if not allow_empty and not value:
        raise QueryInputError(f"{name} must not be empty")
    return value


def _positive_id(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QueryInputError(f"{name} must be a positive integer")
    return value


def _page_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise QueryInputError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return value


def _iso_date(value: str | None, name: str) -> str | None:
    value = _bounded_text(value, name, 10, allow_empty=False)
    if value is None:
        return None
    if not _DATE_RE.fullmatch(value):
        raise QueryInputError(f"{name} must be an ISO date in YYYY-MM-DD form")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise QueryInputError(f"{name} must be a real calendar date") from exc
    if parsed.isoformat() != value:
        raise QueryInputError(f"{name} must be an ISO date in YYYY-MM-DD form")
    return value


def _check_range(start: str | None, end: str | None, start_name: str, end_name: str) -> None:
    if start and end and start > end:
        raise QueryInputError(f"{start_name} must not be after {end_name}")


def _like_literal(value: str) -> str:
    return "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _secret_query_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", unquote_plus(key).lower())
    return normalized in _SECRET_QUERY_KEYS or any(
        normalized.endswith(suffix)
        for suffix in ("token", "secret", "apikey", "signature", "credential")
    )


def _redact_query(query: str) -> str:
    return urlencode([
        (key, REDACTED if _secret_query_key(key) else item)
        for key, item in parse_qsl(query, keep_blank_values=True)
    ], doseq=True)


def redact_url(value: str) -> str:
    """Replace conventional secret query values while retaining the rest of a URL."""
    try:
        parts = urlsplit(value)
        if not parts.query:
            return value
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           _redact_query(parts.query), parts.fragment))
    except (TypeError, ValueError):
        # Even an invalid authority can contain a query. Apply the same decoded-key
        # policy as valid URLs, rather than a second, incomplete regex key list.
        prefix, separator, tail = value.partition("?")
        if not separator:
            return value
        query, fragment_separator, fragment = tail.partition("#")
        return prefix + separator + _redact_query(query) + fragment_separator + fragment


def _redact_recipe(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child in value.items():
            if str(child_key).casefold() == "headers":
                if isinstance(child, dict):
                    result[child_key] = {header: REDACTED for header in child}
                elif isinstance(child, list):
                    result[child_key] = [
                        [pair[0], REDACTED] if isinstance(pair, (list, tuple)) and len(pair) >= 2
                        else REDACTED for pair in child
                    ]
                else:
                    result[child_key] = REDACTED
            else:
                result[child_key] = _redact_recipe(child, key=str(child_key))
        return result
    if isinstance(value, list):
        return [_redact_recipe(item, key=key) for item in value]
    if isinstance(value, str) and ("?" in value or key.lower() in {"url", "job_url", "application_url"}):
        return redact_url(value)
    return value


def _json_info(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {"raw": None, "parsed": None, "parse_status": "null"}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw, "parsed": None, "parse_status": "malformed"}
    return {"raw": raw, "parsed": parsed, "parse_status": "valid"}


def _recipe_info(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {"raw_redacted": None, "parsed": None, "parse_status": "null"}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw_redacted": MALFORMED_RECIPE, "parsed": None,
                "parse_status": "malformed_withheld"}
    if not isinstance(parsed, dict):
        return {"raw_redacted": MALFORMED_RECIPE, "parsed": None,
                "parse_status": "malformed_withheld"}
    safe = _redact_recipe(parsed)
    safe_json = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    return {"raw_redacted": safe_json, "parsed": safe, "parse_status": "valid_redacted"}


def _cursor_encode(scope: str, key: int | str, extra: int | None = None) -> str:
    payload = {"v": 1, "scope": scope, "key": key}
    if extra is not None:
        payload["extra"] = extra
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _filter_scope(name: str, filters: dict[str, Any]) -> str:
    """Bind a cursor to the exact filters without storing search text in the token."""
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{name}:{digest}"


def _cursor_decode(cursor: str | None, scope: str, key_kind: str,
                   *, composite: bool = False) -> _Cursor | None:
    if cursor is None:
        return None
    cursor = _bounded_text(cursor, "cursor", MAX_CURSOR_CHARS, allow_empty=False)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
        raise QueryInputError("cursor is malformed")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (ValueError, json.JSONDecodeError, TypeError, UnicodeError):
        raise QueryInputError("cursor is malformed") from None
    if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("scope") != scope:
        raise QueryInputError("cursor does not match this query")
    value = payload.get("key")
    if key_kind == "int":
        if (isinstance(value, bool) or not isinstance(value, int)
                or value <= 0 or value > MAX_SQLITE_INTEGER):
            raise QueryInputError("cursor is malformed")
    else:
        if not isinstance(value, str) or len(value) > MAX_CURSOR_KEY_CHARS:
            raise QueryInputError("cursor is malformed")
    extra = payload.get("extra")
    if composite:
        if (isinstance(extra, bool) or not isinstance(extra, int)
                or extra <= 0 or extra > MAX_SQLITE_INTEGER):
            raise QueryInputError("cursor is malformed")
    elif "extra" in payload:
        raise QueryInputError("cursor is malformed")
    return _Cursor(value, extra)


def _page(rows: list[dict[str, Any]], limit: int, scope: str,
          key_field: str, *, descending: bool, extra_field: str | None = None,
          cursor_extra: int | None = None) -> dict[str, Any]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        extra = last[extra_field] if extra_field else cursor_extra
        next_cursor = _cursor_encode(scope, last[key_field], extra)
    return {"items": items, "limit": limit, "has_more": has_more,
            "next_cursor": next_cursor, "ordering": "live keyset page; not a snapshot"}


def _safe_url_fields(record: dict[str, Any]) -> dict[str, Any]:
    for field in ("url", "job_url", "application_url"):
        value = record.get(field)
        if isinstance(value, str):
            record[field] = redact_url(value)
    return record


def _safe_full_record(entity: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _safe_url_fields(raw)
    if entity == "job_postings":
        description = record.pop("description", None)
        record["description_is_null"] = description is None
        record["description_chars"] = None if description is None else len(description)
        record["description_read_tool"] = "get_job_description"
        score_detail_info = _json_info(record.get("score_detail"))
        record["score_detail_parsed"] = score_detail_info["parsed"]
        record["score_detail_parse_status"] = score_detail_info["parse_status"]
        if record.get("pipeline_error"):
            record["pipeline_error"] = redact_url(record["pipeline_error"])
    elif entity == "applications":
        notes = record.pop("notes", None)
        record["notes_is_null"] = notes is None
        record["notes_chars"] = None if notes is None else len(notes)
        record["notes_read_tool"] = "get_application_notes"
    elif entity == "job_screenings":
        info = _json_info(record.get("result_json"))
        record["result_json_parsed"] = info["parsed"]
        record["result_json_parse_status"] = info["parse_status"]
    elif entity == "watched_companies":
        info = _recipe_info(record.get("recipe"))
        record["recipe_raw_redacted"] = info["raw_redacted"]
        record["recipe_parsed"] = info["parsed"]
        record["recipe_parse_status"] = info["parse_status"]
        record.pop("recipe", None)
    elif entity == "app_settings":
        value = record.pop("value", None)
        if record.get("key") in SAFE_SETTING_VALUE_KEYS:
            info = _json_info(value)
            record["value_raw"] = info["raw"]
            record["value_parsed"] = info["parsed"]
            record["value_parse_status"] = info["parse_status"]
            record["value_policy"] = "approved: categories vocabulary"
        else:
            record["value"] = UNREVIEWED_SETTING
            record["value_policy"] = "withheld until this setting key has an explicit policy"
    return record


def _list_record(entity: str, raw: dict[str, Any]) -> dict[str, Any]:
    omit = LIST_OMIT_FIELDS.get(entity, frozenset())
    record = {key: value for key, value in raw.items() if key not in omit}
    if "description" in raw:
        record["description_is_null"] = raw["description"] is None
        record["description_chars"] = len(raw["description"] or "")
        record["description_read_tool"] = "get_job_description"
    if "notes" in raw:
        record["notes_is_null"] = raw["notes"] is None
        record["notes_chars"] = None if raw["notes"] is None else len(raw["notes"])
        record["notes_read_tool"] = "get_application_notes"
    if "score_detail" in raw:
        record["score_detail_chars"] = None if raw["score_detail"] is None else len(raw["score_detail"])
        record["score_detail_read_tool"] = "get_ats_record"
    if "result_json" in raw:
        record["result_json_chars"] = None if raw["result_json"] is None else len(raw["result_json"])
        record["result_json_read_tool"] = "get_ats_record"
    if entity == "watched_companies":
        info = _recipe_info(raw.get("recipe"))
        record.pop("recipe", None)
        record["recipe_raw_redacted"] = info["raw_redacted"]
        record["recipe_parse_status"] = info["parse_status"]
    if entity == "app_settings":
        value = raw.get("value")
        if raw.get("key") in SAFE_SETTING_VALUE_KEYS:
            info = _json_info(value)
            record["value_raw"] = info["raw"]
            record["value_parsed"] = info["parsed"]
            record["value_parse_status"] = info["parse_status"]
        else:
            record["value"] = UNREVIEWED_SETTING
            record["value_policy"] = "withheld until this setting key has an explicit policy"
    return _safe_url_fields(record)


class ReadOnlyATSRepository:
    """An allowlisted query API over SQLite opened in read-only/query-only mode."""

    def __init__(self, db_path: str | Path | None = None, *,
                 clock: Callable[[], datetime] | None = None):
        if db_path is None:
            configured = os.environ.get("ATS_DB_PATH")
            db_path = configured or (Path(__file__).resolve().parents[4]
                                     / "apps" / "web" / "prisma" / "applications.db")
        self.db_path = Path(db_path).expanduser()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            absolute = self.db_path.resolve(strict=False)
            connection = sqlite3.connect(
                absolute.as_uri() + "?mode=ro", uri=True,
                timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000,
            )
        except (OSError, sqlite3.Error, ValueError):
            raise DatabaseUnavailable(
                "ATS database is unavailable; check ATS_DB_PATH and file permissions"
            ) from None
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
            connection.create_function(
                "ats_instant_valid", 1, _timestamp_valid, deterministic=True,
            )
            connection.create_function(
                "ats_instant_cmp", 2, _timestamp_compare, deterministic=True,
            )
            if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
                raise DatabaseUnavailable("ATS database connection is not query-only")
            present = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES.issubset(present):
                raise DatabaseUnavailable(
                    "ATS database schema is incomplete; check ATS_DB_PATH and apply the Prisma schema"
                )
            yield connection
        except RepositoryError:
            raise
        except sqlite3.Error:
            raise DatabaseUnavailable(
                "ATS database could not be read; check its schema and permissions"
            ) from None
        finally:
            connection.close()

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str) -> int:
        # `table` is always a literal from this module's closed table list.
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    @staticmethod
    def _group_counts(conn: sqlite3.Connection, table: str, column: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            f'SELECT "{column}" AS value, COUNT(*) AS count FROM "{table}" '
            f'GROUP BY "{column}" ORDER BY "{column}"'
        ).fetchall()
        known = (PIPELINE_STATUSES if table == "job_postings" else
                 APPLICATION_STATUSES if table == "applications" else
                 frozenset({"complete", "provider_error"}) if table == "job_screenings" else
                 frozenset())
        return [{"value": row["value"], "count": int(row["count"]),
                 "known": row["value"] in known} for row in rows]

    def get_ats_overview(self) -> dict[str, Any]:
        with self._connection() as conn:
            # One read snapshot keeps grouped totals internally reconcilable while the
            # worker or web app writes through WAL.
            conn.execute("BEGIN")
            generated_at = self._clock()
            if generated_at.tzinfo is None or generated_at.utcoffset() is None:
                raise RepositoryError("overview clock must return an offset-aware timestamp")
            response_generated_at = generated_at.astimezone(timezone.utc).isoformat(
                timespec="milliseconds")
            response_generated_at = response_generated_at.replace("+00:00", "Z")
            tables = {table: self._count(conn, table) for table, _, _ in ENTITY_KEYS.values()}
            posting_screens = conn.execute(
                "SELECT CASE WHEN s.id IS NULL THEN 'not_screened' ELSE s.state END AS state, "
                "COUNT(*) AS count FROM job_postings p LEFT JOIN job_screenings s "
                "ON s.job_posting_id=p.id GROUP BY state ORDER BY state"
            ).fetchall()
            outcome_counts_rows = conn.execute(
                f"SELECT {_screen_outcome_sql()} AS outcome,COUNT(*) AS count "
                "FROM job_postings p LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
                "GROUP BY outcome"
            ).fetchall()
            outcome_count_map = {row["outcome"]: int(row["count"])
                                 for row in outcome_counts_rows}
            triage_count_rows = conn.execute(
                f"SELECT {_triage_status_sql()} AS status,COUNT(*) AS count "
                "FROM job_postings p LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
                "GROUP BY status"
            ).fetchall()
            triage_count_map = {row["status"]: int(row["count"])
                                for row in triage_count_rows}
            screening_records = self._group_counts(conn, "job_screenings", "state")
            pipeline_counts = self._group_counts(conn, "job_postings", "pipeline_status")
            application_counts = self._group_counts(conn, "applications", "status")
            eligible_counts = conn.execute(
                "SELECT SUM(CASE WHEN s.id IS NULL THEN 1 ELSE 0 END) AS fresh, "
                "SUM(CASE WHEN s.id IS NOT NULL AND s.state='provider_error' "
                "THEN 1 ELSE 0 END) AS retry_eligible "
                "FROM job_postings p LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
                "WHERE p.pipeline_status='new'"
            ).fetchone()
            unknown_screening_times = int(conn.execute(
                "SELECT COUNT(*) FROM job_screenings WHERE ats_instant_valid(updated_at) IS NULL"
            ).fetchone()[0])
            return {
                "table_counts": tables,
                "pipeline_status_counts": pipeline_counts,
                "application_status_counts": application_counts,
                "screen_state_counts_by_posting": [
                    {"state": row["state"], "count": int(row["count"])}
                    for row in posting_screens
                ],
                "screening_record_state_counts": screening_records,
                "unknown_pipeline_statuses": [row["value"] for row in pipeline_counts
                                               if not row["known"]],
                "unknown_application_statuses": [row["value"] for row in application_counts
                                                  if not row["known"]],
                "standalone_screen_outcome_counts": {
                    "scope": "all job_postings",
                    "counts": [
                        {"outcome": outcome, "count": outcome_count_map.get(outcome, 0)}
                        for outcome in SCREEN_OUTCOMES
                    ],
                },
                "job_triage_counts": {
                    "scope": "all job_postings",
                    "counts": [
                        {"status": status, "count": triage_count_map.get(status, 0)}
                        for status in TRIAGE_STATUSES
                    ],
                },
                "eligible_screen_backlog": {
                    "scope": "pipeline_status=new",
                    "fresh": int(eligible_counts["fresh"] or 0),
                    "retry_eligible": int(eligible_counts["retry_eligible"] or 0),
                    "total": int(eligible_counts["fresh"] or 0)
                    + int(eligible_counts["retry_eligible"] or 0),
                },
                "unknown_screening_updated_at_count": unknown_screening_times,
                "response_generated_at": response_generated_at,
                "response_time_semantics": (
                    "query response time; not fetch completion or source freshness"
                ),
                "counts_are_live": True,
            }

    def list_jobs(self, *, search: str | None = None, source: str | None = None,
                  pipeline_status: str | None = None, screen_state: str | None = None,
                  screen_outcome: str | None = None, triage_status: str | None = None,
                  search_scope: str = "metadata",
                  created_from: str | None = None, created_to: str | None = None,
                  posted_from: str | None = None, posted_to: str | None = None,
                  screening_updated_from: str | None = None,
                  screening_updated_to: str | None = None,
                  application_id: int | None = None, limit: int = DEFAULT_PAGE_SIZE,
                  cursor: str | None = None) -> dict[str, Any]:
        limit = _page_size(limit)
        search = _bounded_text(search, "search", MAX_SEARCH_CHARS)
        source = _bounded_text(source, "source", MAX_FILTER_CHARS)
        pipeline_status = _bounded_text(pipeline_status, "pipeline_status", MAX_FILTER_CHARS)
        screen_state = _bounded_text(screen_state, "screen_state", MAX_FILTER_CHARS)
        screen_outcome = _bounded_text(screen_outcome, "screen_outcome", MAX_FILTER_CHARS)
        if screen_outcome is not None and screen_outcome not in _SCREEN_OUTCOME_SET:
            raise QueryInputError("screen_outcome must be one of the supported outcomes")
        triage_status = _bounded_text(triage_status, "triage_status", MAX_FILTER_CHARS)
        if triage_status is not None and triage_status not in _TRIAGE_STATUS_SET:
            raise QueryInputError("triage_status must be one of the supported statuses")
        search_scope = _bounded_text(search_scope, "search_scope", MAX_FILTER_CHARS,
                                     allow_empty=False) or ""
        if search_scope not in {"metadata", "all_text"}:
            raise QueryInputError("search_scope must be metadata or all_text")
        created_from, created_to = _iso_date(created_from, "created_from"), _iso_date(created_to, "created_to")
        posted_from, posted_to = _iso_date(posted_from, "posted_from"), _iso_date(posted_to, "posted_to")
        screening_updated_from = _parse_rfc3339(
            screening_updated_from, "screening_updated_from")
        screening_updated_to = _parse_rfc3339(screening_updated_to, "screening_updated_to")
        _check_range(created_from, created_to, "created_from", "created_to")
        _check_range(posted_from, posted_to, "posted_from", "posted_to")
        from_key = (_timestamp_key(screening_updated_from)
                    if screening_updated_from is not None else None)
        to_key = (_timestamp_key(screening_updated_to)
                  if screening_updated_to is not None else None)
        if from_key is not None and to_key is not None and _compare_timestamp_keys(from_key, to_key) > 0:
            raise QueryInputError(
                "screening_updated_from must not be after screening_updated_to")
        if application_id is not None:
            application_id = _positive_id(application_id, "application_id")

        filters = {"search": search, "source": source, "pipeline_status": pipeline_status,
                   "screen_state": screen_state, "screen_outcome": screen_outcome,
                   "triage_status": triage_status,
                   "search_scope": search_scope,
                   "screening_updated_from": screening_updated_from,
                   "screening_updated_to": screening_updated_to,
                   "created_from": created_from,
                   "created_to": created_to, "posted_from": posted_from,
                   "posted_to": posted_to, "application_id": application_id}
        scope = _filter_scope("jobs", filters)
        decoded = _cursor_decode(cursor, scope, "int", composite=True)
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            pattern = _like_literal(search)
            search_columns = ["p.job_title", "p.company_name", "COALESCE(p.location,'')"]
            if search_scope == "all_text":
                search_columns.append("p.description")
            clauses.append("(" + " OR ".join(
                f"{column} LIKE ? ESCAPE '!'" for column in search_columns) + ")")
            params.extend([pattern] * len(search_columns))
        for column, value in (("p.source", source), ("p.pipeline_status", pipeline_status),
                              ("p.application_id", application_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if screen_state is not None:
            clauses.append("COALESCE(s.state, 'not_screened') = ?")
            params.append(screen_state)
        if screen_outcome is not None:
            clauses.append(f"({_screen_outcome_sql()}) = ?")
            params.append(screen_outcome)
        if triage_status is not None:
            clauses.append(f"({_triage_status_sql()}) = ?")
            params.append(triage_status)
        if screening_updated_from is not None:
            clauses.append("ats_instant_cmp(s.updated_at, ?) >= 0")
            params.append(screening_updated_from)
        if screening_updated_to is not None:
            clauses.append("ats_instant_cmp(s.updated_at, ?) < 0")
            params.append(screening_updated_to)
        if created_from:
            clauses.append("substr(p.created_at, 1, 10) >= ?")
            params.append(created_from)
        if created_to:
            clauses.append("substr(p.created_at, 1, 10) <= ?")
            params.append(created_to)
        if posted_from:
            clauses.append("substr(p.posted_at, 1, 10) >= ?")
            params.append(posted_from)
        if posted_to:
            clauses.append("substr(p.posted_at, 1, 10) <= ?")
            params.append(posted_to)
        if decoded and decoded.extra is not None and decoded.key > decoded.extra:
            raise QueryInputError("cursor is malformed")

        with self._connection() as conn:
            # The first page fixes an insertion ceiling in the same read snapshot as
            # its rows; later pages retain that ceiling but remain current-state reads.
            conn.execute("BEGIN")
            ceiling = (decoded.extra if decoded else int(conn.execute(
                "SELECT COALESCE(MAX(id),0) FROM job_postings").fetchone()[0]))
            if ceiling:
                clauses.append("p.id <= ?")
                params.append(ceiling)
            if decoded:
                clauses.append("p.id < ?")
                params.append(decoded.key)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            sql = (
                "SELECT p.id,p.source,p.external_id,p.company_slug,p.company_name,p.job_title,"
                "p.location,p.job_url,p.score,p.pipeline_status,p.pipeline_error,p.attempts,"
                "p.notify_attempts,p.application_id,p.created_at,p.updated_at,p.posted_at,"
                "p.deprioritized_at,length(p.description) AS description_chars,"
                "p.source_state,p.source_last_seen_at,p.source_last_check_attempted_at,"
                "p.source_last_checked_at,p.source_last_check_outcome,"
                "p.source_last_check_error_category,p.source_content_revision,"
                "p.score_detail,"
                "CASE WHEN json_valid(p.score_detail) AND "
                "json_type(p.score_detail,'$.assessment')='object' AND "
                "length(json_extract(p.score_detail,'$.assessment'))>2 THEN 1 ELSE 0 END "
                "AS fit_assessment_available,"
                "CASE WHEN json_valid(p.score_detail) AND "
                "json_type(p.score_detail,'$.source_content_revision')='integer' "
                "THEN json_extract(p.score_detail,'$.source_content_revision') ELSE NULL END "
                "AS fit_content_revision,"
                "s.id AS screening_id,s.state AS screening_state,s.backend AS screening_backend,"
                "s.result_json AS screening_result_json,"
                "s.model AS screening_model,s.effort AS screening_effort,"
                "s.evaluator_version AS screening_evaluator_version,"
                "s.error_message AS screening_error_message,s.updated_at AS screening_updated_at,"
                "s.last_attempted_at AS screening_last_attempted_at,"
                "s.completed_at AS screening_completed_at,"
                "s.source_content_revision AS screening_source_content_revision,"
                f"{_screen_outcome_sql()} AS screen_outcome,"
                f"CASE WHEN json_valid(s.result_json) THEN CASE "
                f"WHEN json_type(s.result_json,'$.disqualification_reason')='text' "
                f"THEN substr(json_extract(s.result_json,'$.disqualification_reason'),1,"
                f"{MAX_SCREEN_REASON_CHARS + 1}) ELSE NULL END ELSE NULL END AS screening_reason,"
                "CASE WHEN json_valid(p.score_detail) THEN CASE "
                "WHEN json_type(p.score_detail,'$.screen')='object' THEN 1 ELSE 0 END "
                "ELSE 0 END AS legacy_screen_evidence_available "
                "FROM job_postings p LEFT JOIN job_screenings s ON s.job_posting_id=p.id" + where +
                " ORDER BY p.id DESC LIMIT ?"
            )
            params.append(limit + 1)
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["job_url"] = redact_url(row["job_url"])
            row["pipeline_error"] = redact_url(row["pipeline_error"]) if row["pipeline_error"] else None
            row["description_is_null"] = row["description_chars"] is None
            row["screen_summary"] = _screen_summary(row)
            screening = ({"id": row.get("screening_id"),
                          "state": row.get("screening_state"),
                          "result_json": row.get("screening_result_json")}
                         if row.get("screening_id") is not None else None)
            row["triage_summary"] = job_triage_summary(
                row.get("pipeline_status"), row.get("score_detail"), screening)
            row["source_lifecycle"] = _source_lifecycle_summary(row)
            _strip_source_lifecycle_fields(row)
            legacy_available = bool(row.pop("legacy_screen_evidence_available"))
            row["legacy_screen_evidence"] = {
                "available": legacy_available,
                "origin": "job_postings.score_detail.screen"
                if legacy_available else None,
                "read_tool": "get_job" if legacy_available else None,
            }
            row.pop("screening_updated_at", None)
            row.pop("screening_result_json", None)
            row.pop("screening_reason", None)
            row.pop("screening_error_message", None)
            row.pop("screening_source_content_revision", None)
            row.pop("fit_assessment_available", None)
            row.pop("fit_content_revision", None)
            row.pop("score_detail", None)
        page = _page(rows, limit, scope, "id", descending=True, cursor_extra=ceiling)
        page["traversal"] = {
            "id_ceiling": ceiling,
            "snapshot": False,
            "current_state": True,
            "reconciliation_guidance": (
                "Rerun overlapping assessment windows, deduplicate by source/external_id "
                "and assessment time, and periodically reconcile current inventory. "
                "Overlaps cannot recover arbitrary backdated writes or every transition."
            ),
            "assessment_time_field": "job_screenings.updated_at",
            "source_freshness": "assessment time is not source freshness",
        }
        return page

    def get_job(self, job_id: int) -> dict[str, Any]:
        job_id = _positive_id(job_id, "job_id")
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM job_postings WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise RecordNotFound("job was not found")
            result = _safe_full_record("job_postings", dict(row))
            screening = conn.execute(
                "SELECT s.*,s.id AS screening_id,s.updated_at AS screening_updated_at,"
                "s.backend AS screening_backend,s.model AS screening_model,"
                "s.effort AS screening_effort,s.evaluator_version AS screening_evaluator_version,"
                "s.source_content_revision AS screening_source_content_revision,"
                "s.error_message AS screening_error_message," + _screen_outcome_sql() + " AS screen_outcome,"
                "CASE WHEN json_valid(s.result_json) THEN CASE "
                "WHEN json_type(s.result_json,'$.disqualification_reason')='text' "
                f"THEN substr(json_extract(s.result_json,'$.disqualification_reason'),1,{MAX_SCREEN_REASON_CHARS + 1}) "
                "ELSE NULL END ELSE NULL END AS screening_reason "
                "FROM job_screenings s WHERE s.job_posting_id=?", (job_id,)
            ).fetchone()
            if screening:
                screening_row = dict(screening)
                stored_screening = {
                    key: value for key, value in screening_row.items()
                    if not key.startswith("screening_") and key != "screen_outcome"
                }
                result["screening"] = _safe_full_record("job_screenings", stored_screening)
                result["screen_summary"] = _screen_summary(screening_row)
                triage_screening = stored_screening
                lifecycle_screen = stored_screening
            else:
                result["screening"] = None
                result["screen_summary"] = _screen_summary({"screen_outcome": "not_screened"})
                triage_screening = None
                lifecycle_screen = None
            result["triage_summary"] = job_triage_summary(
                result.get("pipeline_status"), result.get("score_detail"), triage_screening)
            legacy_available = isinstance(result.get("score_detail_parsed"), dict) and isinstance(
                result["score_detail_parsed"].get("screen"), dict)
            result["legacy_screen_evidence"] = {
                "available": legacy_available,
                "origin": "job_postings.score_detail.screen" if legacy_available else None,
                "read_tool": "get_job" if legacy_available else None,
            }
            result["source_lifecycle"] = _source_lifecycle_summary(result, lifecycle_screen)
            _strip_source_lifecycle_fields(result)
            return result

    def get_job_description(self, job_id: int, *, offset: int = 0,
                            limit: int = TEXT_CHUNK_SIZE) -> dict[str, Any]:
        return self._get_text_chunk("job_postings", "id", _positive_id(job_id, "job_id"),
                                    "description", offset=offset, limit=limit)

    def list_applications(self, *, search: str | None = None, status: str | None = None,
                          category: str | None = None, applied_from: str | None = None,
                          applied_to: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
                          cursor: str | None = None) -> dict[str, Any]:
        limit = _page_size(limit)
        search = _bounded_text(search, "search", MAX_SEARCH_CHARS)
        status = _bounded_text(status, "status", MAX_FILTER_CHARS)
        category = _bounded_text(category, "category", MAX_FILTER_CHARS)
        applied_from, applied_to = _iso_date(applied_from, "applied_from"), _iso_date(applied_to, "applied_to")
        _check_range(applied_from, applied_to, "applied_from", "applied_to")
        filters = {"search": search, "status": status, "category": category,
                   "applied_from": applied_from, "applied_to": applied_to}
        scope = _filter_scope("applications", filters)
        decoded = _cursor_decode(cursor, scope, "int")
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            pattern = _like_literal(search)
            clauses.append("(a.company_name LIKE ? ESCAPE '!' OR a.job_title LIKE ? ESCAPE '!')")
            params.extend((pattern, pattern))
        if status is not None:
            clauses.append("a.status = ?")
            params.append(status)
        if category is not None:
            clauses.append("a.category = ?")
            params.append(category)
        if applied_from:
            clauses.append("a.date_applied >= ?")
            params.append(applied_from)
        if applied_to:
            clauses.append("a.date_applied <= ?")
            params.append(applied_to)
        if decoded:
            clauses.append("a.id < ?")
            params.append(decoded.key)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT a.id,a.company_name,a.job_title,a.application_url,a.date_applied,a.category,"
            "a.status,a.last_updated,length(a.notes) AS notes_chars,a.notes IS NULL AS notes_is_null,"
            "(SELECT COUNT(*) FROM job_postings p WHERE p.application_id=a.id) AS linked_job_count "
            "FROM applications a" + where + " ORDER BY a.id DESC LIMIT ?"
        )
        params.append(limit + 1)
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["application_url"] = redact_url(row["application_url"]) if row["application_url"] else None
        return _page(rows, limit, scope, "id", descending=True)

    def get_application(self, application_id: int) -> dict[str, Any]:
        application_id = _positive_id(application_id, "application_id")
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
            if row is None:
                raise RecordNotFound("application was not found")
            result = _safe_full_record("applications", dict(row))
            if isinstance(result["application_url"], str):
                result["application_url"] = redact_url(result["application_url"])
            result["linked_job_ids"] = [item[0] for item in conn.execute(
                "SELECT id FROM job_postings WHERE application_id=? ORDER BY id ASC",
                (application_id,),
            )]
            return result

    def get_application_notes(self, application_id: int, *, offset: int = 0,
                               limit: int = TEXT_CHUNK_SIZE) -> dict[str, Any]:
        return self._get_text_chunk("applications", "id", _positive_id(application_id, "application_id"),
                                    "notes", offset=offset, limit=limit)

    def list_application_history(self, application_id: int, *, limit: int = DEFAULT_PAGE_SIZE,
                                 cursor: str | None = None) -> dict[str, Any]:
        application_id = _positive_id(application_id, "application_id")
        limit = _page_size(limit)
        scope = f"history:{application_id}"
        decoded = _cursor_decode(cursor, scope, "str", composite=True)
        with self._connection() as conn:
            if conn.execute("SELECT 1 FROM applications WHERE id=?", (application_id,)).fetchone() is None:
                raise RecordNotFound("application was not found")
            where = "application_id=?"
            params: list[Any] = [application_id]
            if decoded:
                where += " AND (timestamp > ? OR (timestamp = ? AND id > ?))"
                params.extend((decoded.key, decoded.key, int(decoded.extra or 0)))
            params.append(limit + 1)
            rows = [dict(row) for row in conn.execute(
                f"SELECT id,application_id,status,timestamp FROM status_history WHERE {where} "
                "ORDER BY timestamp ASC,id ASC LIMIT ?", params,
            ).fetchall()]
        page = _page(rows, limit, scope, "timestamp", descending=False, extra_field="id")
        return page

    def list_ats_records(self, entity: str, *, limit: int = DEFAULT_PAGE_SIZE,
                         cursor: str | None = None) -> dict[str, Any]:
        if not isinstance(entity, str):
            raise QueryInputError("entity must name one of the supported ATS records")
        spec = ENTITY_KEYS.get(entity)
        if spec is None:
            raise QueryInputError("entity must name one of the supported ATS records")
        table, key_field, key_kind = spec
        limit = _page_size(limit)
        descending = key_kind == "int"
        scope = f"records:{entity}"
        decoded = _cursor_decode(cursor, scope, key_kind)
        direction = "DESC" if descending else "ASC"
        where = ""
        params: list[Any] = []
        if decoded:
            comparator = "<" if descending else ">"
            where = f" WHERE \"{key_field}\" {comparator} ?"
            params.append(decoded.key)
        params.append(limit + 1)
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(
                f'SELECT * FROM "{table}"{where} ORDER BY "{key_field}" {direction} LIMIT ?',
                params,
            ).fetchall()]
        return _page([_list_record(entity, row) for row in rows], limit, scope,
                     key_field, descending=descending)

    def get_ats_record(self, entity: str, key: str) -> dict[str, Any]:
        if not isinstance(entity, str):
            raise QueryInputError("entity must name one of the supported ATS records")
        spec = ENTITY_KEYS.get(entity)
        if spec is None:
            raise QueryInputError("entity must name one of the supported ATS records")
        table, key_field, key_kind = spec
        key = _bounded_text(key, "key", MAX_CURSOR_KEY_CHARS, allow_empty=False) or ""
        if key_kind == "int":
            if not _INTEGER_KEY_RE.fullmatch(key):
                raise QueryInputError("key must be a positive integer for this entity")
            lookup: int | str = int(key)
        else:
            lookup = key
        if entity == "job_postings":
            return self.get_job(int(lookup))
        if entity == "applications":
            return self.get_application(int(lookup))
        with self._connection() as conn:
            row = conn.execute(
                f'SELECT * FROM "{table}" WHERE "{key_field}"=?', (lookup,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"{entity} record was not found")
            return _safe_full_record(entity, dict(row))

    def _get_text_chunk(self, table: str, key_field: str, key: int, field: str,
                        *, offset: int, limit: int) -> dict[str, Any]:
        key = _positive_id(key, "record id")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 2_147_483_647:
            raise QueryInputError("offset must be a nonnegative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= TEXT_CHUNK_SIZE:
            raise QueryInputError(f"limit must be between 1 and {TEXT_CHUNK_SIZE}")
        if table == "job_postings":
            tool = "get_job_description"
        elif table == "applications":
            tool = "get_application_notes"
        else:
            raise QueryInputError("text field is not available")
        with self._connection() as conn:
            row = conn.execute(
                f'SELECT "{field}" FROM "{table}" WHERE "{key_field}"=?', (key,)
            ).fetchone()
            if row is None:
                raise RecordNotFound("record was not found")
            value = row[0]
        if value is None:
            return {"text": None, "is_null": True, "total_chars": None, "offset": offset,
                    "next_offset": None, "has_more": False, "read_tool": tool}
        if offset > len(value):
            raise QueryInputError("offset is past the end of the stored text")
        chunk = value[offset:offset + limit]
        next_offset = offset + len(chunk)
        has_more = next_offset < len(value)
        return {"text": chunk, "is_null": False, "total_chars": len(value), "offset": offset,
                "next_offset": next_offset if has_more else None, "has_more": has_more,
                "read_tool": tool}
