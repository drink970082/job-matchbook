"""Legacy fit schema/builders plus compatibility exports for screen rendering.

The provider-neutral screening package owns active screen prompt resources, schema and
rendering. This module retains the fit schema/system-prefix builders used by `score/`.
"""
from __future__ import annotations

import json

from ats_worker.prompts import (
    SCORE_C_AUTHORIZATION,
    SCORE_C_CLEARANCE,
    SCORE_C_DEGREE,
    SCORE_HEADER,
)
from ats_worker.screening.prompts import (
    SCREEN_FOOTER, SCREEN_HEADER, SCREEN_LIST_HEADER, SCREEN_SCHEMA,
    _candidate_block, _job_block, _truncate,
)

# Structured-output schema for the Claude fit score. The `assessment` scorecard comes
# first so the model works through the per-dimension verdicts BEFORE committing to a
# number (replacing the old prose `reasoning` blob + flat keyword lists — S2.1). The
# seniority/domain verdicts are enum-constrained so structured outputs enforce them; the
# split must_haves/nice_to_haves make a missing "plus" skill visibly cheaper than a
# missing core one (D4), and a seniority gap is a first-class field, not buried in prose
# (D3). (Structured outputs reject numeric bounds, so `score` is a bare integer — the
# 0-100 clamp lives in _coerce_score.)
_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "seniority": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["match", "too_junior", "too_senior"]},
                "note": {"type": "string"},
            },
            "required": ["verdict", "note"],
            "additionalProperties": False,
        },
        "domain": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["match", "adjacent", "mismatch"]},
                "note": {"type": "string"},
            },
            "required": ["verdict", "note"],
            "additionalProperties": False,
        },
        "must_haves": {
            "type": "object",
            "properties": {
                "met": {"type": "array", "items": {"type": "string"}},
                "missing": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["met", "missing"],
            "additionalProperties": False,
        },
        "nice_to_haves": {
            "type": "object",
            "properties": {
                "missing": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["missing"],
            "additionalProperties": False,
        },
        "summary": {"type": "string"},
    },
    "required": ["seniority", "domain", "must_haves", "nice_to_haves", "summary"],
    "additionalProperties": False,
}
_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment": _ASSESSMENT_SCHEMA,
        "score": {"type": "integer"},
        # True when the JD is too thin/boilerplate to score with confidence; routes the
        # row to the low-context bucket regardless of the (still-required) score.
        "insufficient_context": {"type": "boolean"},
        # Fallback hard-requirement extraction, consumed ONLY where the screen produced
        # nothing (SCREEN_BACKEND=none, or a swallowed screen failure).
        # STRICT-MODE SHAPE, and it is not optional to get right: OpenAI structured
        # output rejects the whole request (HTTP 400 invalid_json_schema) unless EVERY
        # object lists EVERY one of its properties in `required`. There is no such thing
        # as an optional key. "Omitted" is therefore expressed as an explicit null —
        # `screen` is object-or-null, and each leaf value is nullable — which is what
        # keeps "a scorer that has nothing to say must not fail the card" true.
        "screen": {
            "type": ["object", "null"],
            "properties": {
                "degree": {
                    "type": "object",
                    "properties": {"required_degree": {"type": ["string", "null"]}},
                    "required": ["required_degree"],
                    "additionalProperties": False,
                },
                "authorization": {
                    "type": "object",
                    "properties": {"no_sponsorship_quote": {"type": ["string", "null"]}},
                    "required": ["no_sponsorship_quote"],
                    "additionalProperties": False,
                },
                "clearance": {
                    "type": "object",
                    "properties": {"requires_clearance": {"type": ["boolean", "null"]}},
                    "required": ["requires_clearance"],
                    "additionalProperties": False,
                },
            },
            "required": ["degree", "authorization", "clearance"],
            "additionalProperties": False,
        },
    },
    "required": ["assessment", "score", "insufficient_context", "screen"],
    "additionalProperties": False,
}


def _score_schema(labels: list) -> dict:
    """Structured-output schema for the fit call. With >=2 resume versions the
    model must also pick `recommended_resume`, enum-constrained to the actual
    labels so it can never name a nonexistent version; with one version the
    field is omitted (byte-identical to single-resume behavior)."""
    schema = json.loads(json.dumps(_SCORE_SCHEMA))  # deep copy; base stays pristine
    if len(labels) >= 2:
        schema["properties"]["recommended_resume"] = {
            "type": "string", "enum": list(labels)}
        schema["required"].append("recommended_resume")
    return schema


def _scorer_system_sections(resumes: dict, profile: str = "") -> list[str]:
    """The system prefix for the fit call, backend-agnostic: rubric header, optional
    personal profile, then one section per labeled resume version. Claude sends these
    as separate cached blocks; codex joins them into one prompt. Shared so a prompt
    edit lands on BOTH backends at once and a score stays comparable across them.
    """
    sections = [SCORE_HEADER]
    if str(profile or "").strip():
        sections.append(f"=== PERSONAL PROFILE ===\n{profile}")
    sections.extend(f"=== RESUME ({label}) ===\n{text}" for label, text in resumes.items())
    return sections


def _scorer_system_blocks(resumes: dict, profile: str = "") -> list[dict]:
    """System-prefix blocks for the Claude fit call. cache_control goes on the LAST
    block so the whole prefix — byte-identical every call in a run — is cached once
    (per-posting marginal cost stays flat)."""
    blocks: list[dict] = [{"type": "text", "text": s}
                          for s in _scorer_system_sections(resumes, profile)]
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks



# Screen schema and rendering are owned by ats_worker.screening.prompts.
