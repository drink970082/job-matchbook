"""Project an explicit synthetic assessment snapshot into a bounded display view.

This module has no provider, profile, filesystem, database, or environment wiring.
Only this module's caller can supply a snapshot, and only allowlisted display values
leave the projection.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any


VIEW_SCHEMA_VERSION = 1
VIEW_SCOPE = "synthetic_assessment_view"
MAX_COMPONENTS = 32
MAX_JD_EVIDENCE = 32
MAX_DISPLAY_LABEL_CHARS = 120
MAX_JD_EXCERPT_CHARS = 300
MAX_SAFE_JSON_REVISION = 9_007_199_254_740_991
MAX_TIMESTAMP_CHARS = 40

_IDENTITY_KEYS = frozenset({
    "source_revision",
    "content_digest",
    "context_identity",
    "question_version",
    "rubric_version",
    "policy_version",
    "prompt_version",
    "result_schema_version",
    "input_variant",
    "provider",
    "requested_model",
    "resolved_model",
})
_DISPLAY_IDENTITY_KEYS = (
    "question_version",
    "rubric_version",
    "policy_version",
    "prompt_version",
    "result_schema_version",
    "input_variant",
    "provider",
    "requested_model",
    "resolved_model",
)
_COMPONENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_OFFSET_TIMESTAMP = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})[Tt ]"
    r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]+))?"
    r"(?P<zone>[Zz]|(?P<sign>[+-])(?P<offset_hour>[0-9]{2}):(?P<offset_minute>[0-9]{2}))$"
)
_ATTEMPT_STATES = frozenset({"succeeded", "provider_error"})
_ERROR_CATEGORIES = frozenset({
    "timeout", "connection_error", "rate_limited", "provider_unavailable",
    "invalid_response", "unknown_error",
})


def _record(value: Any) -> bool:
    return isinstance(value, dict)


def _positive_safe_revision(value: Any) -> bool:
    """Match the existing positive JavaScript-safe JSON revision contract."""
    if type(value) is int:
        return 0 < value <= MAX_SAFE_JSON_REVISION
    if type(value) is float:
        return math.isfinite(value) and value.is_integer() and 0 < value <= MAX_SAFE_JSON_REVISION
    return False


def _opaque_identity_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 512 and "\x00" not in value


def _display_text(value: Any, limit: int) -> tuple[str, bool] | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or any(not char.isprintable() for char in cleaned):
        return None
    shortened = len(cleaned) > limit
    display = cleaned[:limit].rstrip() if shortened else cleaned
    return display, shortened


def _valid_offset_timestamp(value: Any) -> bool:
    """Accept the strict offset-aware timestamp shape shared with the web reader."""
    if not isinstance(value, str) or not value or len(value) > MAX_TIMESTAMP_CHARS:
        return False
    match = _OFFSET_TIMESTAMP.fullmatch(value)
    if match is None:
        return False

    try:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second = int(match.group("second"))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not 0 <= second <= 59:
            return False
        date(year, month, day)

        zone = match.group("zone")
        if zone in {"Z", "z"}:
            offset = timedelta(0)
        else:
            offset_hour = int(match.group("offset_hour"))
            offset_minute = int(match.group("offset_minute"))
            total_minutes = offset_hour * 60 + offset_minute
            if total_minutes >= 24 * 60:
                return False
            if match.group("sign") == "-":
                total_minutes *= -1
            offset = timedelta(minutes=total_minutes)
        datetime(year, month, day, hour, minute, second, tzinfo=timezone(offset)).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return False
    return True


def _identity(value: Any) -> dict[str, Any] | None:
    if not _record(value):
        return None
    variant = value.get("input_variant")
    expected_keys = _IDENTITY_KEYS | ({"extractor_version"} if variant == "extracted" else set())
    if set(value) != expected_keys:
        return None
    if not _opaque_identity_text(variant):
        return None
    if not _positive_safe_revision(value.get("source_revision")):
        return None
    if not _opaque_identity_text(value.get("content_digest")):
        return None
    if not _opaque_identity_text(value.get("context_identity")):
        return None
    for key in _DISPLAY_IDENTITY_KEYS:
        text = _display_text(value.get(key), 512)
        if text is None or text[0] != value[key]:
            return None
    if variant == "extracted":
        text = _display_text(value.get("extractor_version"), 512)
        if text is None or text[0] != value["extractor_version"]:
            return None
    return value


def _display_identity(identity: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"source_revision": identity["source_revision"]}
    for key in _DISPLAY_IDENTITY_KEYS:
        displayed = _display_text(identity[key], MAX_DISPLAY_LABEL_CHARS)
        assert displayed is not None
        result[key] = displayed[0]
        if displayed[1]:
            result[f"{key}_truncated"] = True
    if identity["input_variant"] == "extracted":
        displayed = _display_text(identity["extractor_version"], MAX_DISPLAY_LABEL_CHARS)
        assert displayed is not None
        result["extractor_version"] = displayed[0]
        if displayed[1]:
            result["extractor_version_truncated"] = True
    return result


def _unknown_view(reason: str, latest_attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": VIEW_SCHEMA_VERSION,
        "scope": VIEW_SCOPE,
        "synthetic": True,
        "assessment_state": "unknown",
        "assessment_reason": reason,
        "latest_attempt": latest_attempt,
        "assessment_time": None,
        "metadata": None,
        "components": [],
    }


def _unknown_attempt() -> dict[str, Any]:
    return {
        "state": "unknown",
        "attempted_at": None,
        "provider": None,
        "provider_truncated": False,
        "requested_model": None,
        "requested_model_truncated": False,
        "resolved_model": None,
        "resolved_model_truncated": False,
        "error_category": None,
    }


def _latest_attempt(value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "state": "not_attempted",
            "attempted_at": None,
            "provider": None,
            "provider_truncated": False,
            "requested_model": None,
            "requested_model_truncated": False,
            "resolved_model": None,
            "resolved_model_truncated": False,
            "error_category": None,
        }
    if not _record(value):
        return _unknown_attempt()
    state = value.get("state")
    if not isinstance(state, str) or state not in _ATTEMPT_STATES:
        return _unknown_attempt()
    attempted_at = value.get("attempted_at")
    text_fields: dict[str, str] = {}
    truncation_fields: dict[str, bool] = {}
    for key in ("provider", "requested_model", "resolved_model"):
        parsed = _display_text(value.get(key), MAX_DISPLAY_LABEL_CHARS)
        if parsed is None:
            return _unknown_attempt()
        text_fields[key] = parsed[0]
        truncation_fields[f"{key}_truncated"] = parsed[1]

    if not _valid_offset_timestamp(attempted_at):
        return _unknown_attempt()
    category = value.get("error_category")
    if state == "provider_error":
        category = category if isinstance(category, str) and category in _ERROR_CATEGORIES else "unknown_error"
    else:
        category = None
    return {
        "state": state,
        "attempted_at": attempted_at,
        **text_fields,
        **truncation_fields,
        "error_category": category,
    }


def _source_evidence(value: Any) -> dict[str, dict[str, Any]] | None:
    if value is None:
        return {}
    if not isinstance(value, list) or len(value) > MAX_JD_EVIDENCE:
        return None
    evidence: dict[str, dict[str, Any]] = {}
    for item in value:
        if not _record(item):
            return None
        evidence_id = item.get("id")
        if (not isinstance(evidence_id, str) or not _COMPONENT_ID.fullmatch(evidence_id)
                or evidence_id in evidence):
            return None
        label = _display_text(item.get("label"), MAX_DISPLAY_LABEL_CHARS)
        excerpt = _display_text(item.get("excerpt"), MAX_JD_EXCERPT_CHARS)
        if label is None or excerpt is None:
            return None
        evidence[evidence_id] = {
            "id": evidence_id,
            "label": label[0],
            "label_truncated": label[1],
            "excerpt": excerpt[0],
            "excerpt_truncated": excerpt[1],
        }
    return evidence


def _components(value: Any, source: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not value or len(value) > MAX_COMPONENTS or source is None:
        return None
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    evidence_reference_count = 0
    for item in value:
        if not _record(item):
            return None
        component_id = item.get("id")
        label = _display_text(item.get("label"), MAX_DISPLAY_LABEL_CHARS)
        score = item.get("score")
        score_valid = (type(score) is int and 0 <= score <= 100) or (
            type(score) is float and math.isfinite(score) and 0 <= score <= 100)
        if (not isinstance(component_id, str) or not _COMPONENT_ID.fullmatch(component_id)
                or component_id in seen or label is None
                or not score_valid):
            return None
        evidence_ids = item.get("evidence_ids", [])
        if (not isinstance(evidence_ids, list) or len(evidence_ids) > MAX_JD_EVIDENCE
                or any(not isinstance(ref, str) or ref not in source for ref in evidence_ids)
                or len(set(evidence_ids)) != len(evidence_ids)):
            return None
        evidence_reference_count += len(evidence_ids)
        if evidence_reference_count > MAX_JD_EVIDENCE:
            return None
        seen.add(component_id)
        result.append({
            "id": component_id,
            "label": label[0],
            "label_truncated": label[1],
            "score": score,
            "jd_evidence": [source[ref] for ref in evidence_ids],
        })
    return result


def project_assessment_view(snapshot: Any) -> dict[str, Any]:
    """Return a display-safe view, failing closed to `unknown` on invalid evidence."""
    if not _record(snapshot):
        return _unknown_view("malformed_snapshot", _unknown_attempt())
    if snapshot.get("schema_version") != 1 or type(snapshot.get("schema_version")) is not int:
        return _unknown_view("unsupported_schema", _unknown_attempt())
    if snapshot.get("synthetic") is not True:
        return _unknown_view("non_synthetic_input", _unknown_attempt())
    attempt = _latest_attempt(snapshot.get("latest_attempt"))

    expected = _identity(snapshot.get("expected_identity"))
    if expected is None:
        return _unknown_view("invalid_expected_identity", attempt)

    success = snapshot.get("last_success")
    if success is None:
        return {
            "schema_version": VIEW_SCHEMA_VERSION,
            "scope": VIEW_SCOPE,
            "synthetic": True,
            "assessment_state": "not_assessed",
            "assessment_reason": None,
            "latest_attempt": attempt,
            "assessment_time": None,
            "metadata": None,
            "components": [],
        }
    if not _record(success):
        return _unknown_view("malformed_success", attempt)

    captured = _identity(success.get("captured_identity"))
    if captured is None:
        return _unknown_view("invalid_captured_identity", attempt)
    if not _valid_offset_timestamp(success.get("assessed_at")):
        return _unknown_view("invalid_assessment_time", attempt)
    if isinstance(success.get("components"), list) and len(success["components"]) > MAX_COMPONENTS:
        return _unknown_view("too_many_components", attempt)
    if isinstance(snapshot.get("jd_source"), list) and len(snapshot["jd_source"]) > MAX_JD_EVIDENCE:
        return _unknown_view("too_many_jd_evidence", attempt)

    evidence = _source_evidence(snapshot.get("jd_source"))
    components = _components(success.get("components"), evidence)
    if components is None:
        return _unknown_view("invalid_assessment_payload", attempt)

    state = "current" if captured == expected else "stale"
    return {
        "schema_version": VIEW_SCHEMA_VERSION,
        "scope": VIEW_SCOPE,
        "synthetic": True,
        "assessment_state": state,
        "assessment_reason": None if state == "current" else "identity_mismatch",
        "latest_attempt": attempt,
        "assessment_time": success["assessed_at"],
        "metadata": _display_identity(captured),
        "components": components,
    }
