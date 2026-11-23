"""Pure helpers for source-state and assessment-freshness reporting."""
from __future__ import annotations

import hashlib
import json


SOURCE_ERROR_CATEGORIES = frozenset({
    "invalid_request", "malformed_response", "identity_mismatch", "company_mismatch",
    "invalid_active", "incomplete_content", "timeout", "connection_error",
    "http_403", "http_404", "http_410", "http_429", "http_5xx", "http_error",
    "refresh_error", "no_recheck_key",
})


def complete_assessment_inputs(posting: dict) -> bool:
    """Whether a posting has enough stable content to version an assessment."""
    return all(isinstance(posting.get(key), str) and posting[key].strip()
               for key in ("company_name", "job_title", "description"))


def assessment_input_hash(posting: dict) -> str | None:
    """Hash only the canonical content that can change an assessment."""
    if not complete_assessment_inputs(posting):
        return None
    canonical = [posting.get("company_name"), posting.get("job_title"),
                 posting.get("location"), posting.get("description")]
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def has_fit_assessment(score_detail: str | None) -> bool:
    """Treat only a non-empty assessment object as a fit assessment.

    Null, malformed JSON, legacy screen-only JSON, and malformed/empty assessment
    values do not block the unscored refresh queue.
    """
    if not score_detail:
        return False
    try:
        parsed = json.loads(score_detail)
    except (TypeError, json.JSONDecodeError):
        return False
    return (isinstance(parsed, dict) and isinstance(parsed.get("assessment"), dict)
            and bool(parsed["assessment"]))


def has_embedded_screen(score_detail: str | None) -> bool:
    """Whether legacy/combined score_detail carries a screen evidence object."""
    if not score_detail:
        return False
    try:
        parsed = json.loads(score_detail)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("screen"), dict)


def assessment_freshness(*, assessed: bool, captured_revision: int | None,
                         current_revision: int | None) -> str:
    if not assessed:
        return "not_assessed"
    if captured_revision is None or current_revision is None:
        return "unknown"
    return "current" if captured_revision == current_revision else "stale"


def observation_error_category(exc: Exception) -> str:
    """Map a transport/parse exception to a closed, non-sensitive category."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 403:
        return "http_403"
    if status == 404:
        return "http_404"
    if status == 410:
        return "http_410"
    if status == 429:
        return "http_429"
    if isinstance(status, int) and 500 <= status <= 599:
        return "http_5xx"
    if isinstance(status, int):
        return "http_error"
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "connection" in name:
        return "connection_error"
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return "malformed_response"
    return "refresh_error"


def verify_board(has_listings, source: str, slug: str, name: str) -> str | None:
    """Check a board once before it joins the watchlist (#231). None when the board lists
    at least one posting; otherwise the reason to reject it, so a wrong slug or a company
    that moved ATS never becomes a silent zero row.

    `has_listings` has `fetch.board_has_listings`' shape: it reads the board's list
    alone, never a per-posting detail call."""
    try:
        listed = has_listings(source, slug, name)
    except Exception as exc:  # noqa: BLE001 - any failure leaves the board unverified
        category = observation_error_category(exc)
        if category == "http_404":
            return "board not found (HTTP 404): check the slug, or the company moved ATS"
        return f"could not verify the board ({category}); try again later"
    if not listed:
        return "board lists no postings: check the slug, or the company moved ATS"
    return None
