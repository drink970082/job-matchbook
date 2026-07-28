"""Prompt + schema assembly for the SCREEN and SCORE calls: the structured-output
schema for the Claude/codex fit call, the shared system-prefix builders, and the
JOB/candidate text blocks both backends render into their prompts. Pure string/dict
assembly — no I/O, no backend-specific client code (that stays in score/__init__.py).
"""
from __future__ import annotations

import json

from ats_worker.prompts import (
    SCORE_C_AUTHORIZATION,
    SCORE_C_CLEARANCE,
    SCORE_C_DEGREE,
    SCORE_HEADER,
    SCREEN_FOOTER,
    SCREEN_LIST_HEADER,
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


def _truncate(text: str, max_chars: int, label: str = "description") -> str:
    """Cap a blob so it can't blow the context window.

    Ollama silently drops tokens past num_ctx; a visible marker is better than a
    half-read JD (or résumé) scored as if complete. `label` names what was cut so a
    truncated résumé and a truncated JD are distinguishable in the prompt.
    """
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + f"\n\n…[{label} truncated to fit context]"
    return text


def _job_block(posting: dict, max_desc_chars: int, *, include_location: bool = True) -> str:
    """The shared JOB section (title, company, [location], description). The fit SCORE
    call passes include_location=False so geography can't leak into the fit number — the
    same role posted per city should score identically; location is decided by the screen
    gate, not the score (D5). The SCREEN call keeps the line (default)."""
    description = _truncate(str(posting.get("description", "")), max_desc_chars)
    header = f"=== JOB: {posting.get('job_title', '')} at {posting.get('company_name', '')} ===\n"
    location_line = ""
    if include_location:
        location = str(posting.get("location") or "").strip() or "(not specified)"
        location_line = f"Location: {location}\n"
    return f"{header}{location_line}{description}\n"


def _candidate_block(candidate, sponsorship_snippets=()) -> str:
    """Render the hard-requirement checklist for the SCREEN call, or '' if nothing
    is configured. Each configured structured field becomes one clause keyed to a
    "screen" key the model returns a fact under (prose lives in prompts/screen.txt).
    Only control flow + layout live here.

    `sponsorship_snippets` are the `sponsor` sentences CODE already retrieved from the
    JD. They are rendered numbered under the authorization clause, and the model labels
    them — it is never asked to find them. With **no snippets the clause is omitted
    entirely**: there is nothing to classify, so asking would only invite an answer
    about text that is not there.
    """
    if not candidate:
        return ""
    degree = str(candidate.get("highest_degree") or "").strip()
    auth = str(candidate.get("work_authorization") or "").strip()
    clearance = str(candidate.get("security_clearance") or "").strip()

    # The structured clauses are pure extraction instructions (the model reports a
    # JOB fact; code compares it to the candidate config), so they carry no {value}.
    clauses: list[str] = []
    if degree:
        clauses.append(SCORE_C_DEGREE)
    if auth and sponsorship_snippets:
        numbered = "\n".join(f"  {n}. {s}"
                             for n, s in enumerate(sponsorship_snippets, 1))
        clauses.append(SCORE_C_AUTHORIZATION + "\n" + numbered)
    if clearance:
        clauses.append(SCORE_C_CLEARANCE)

    if not clauses:
        return ""
    lines = ["", SCREEN_LIST_HEADER, *clauses, SCREEN_FOOTER]
    return "\n".join(lines) + "\n"


# Structured-output schema for the SCREEN extraction. STRICT: every field is `required`,
# because OpenAI structured output has no optional keys and rejects the whole request
# otherwise. Absence is spelled as an explicit null. (It was permissive until 2026-07-26;
# a config with only `highest_degree` set no longer returns just `degree`.)
#
# The safety argument moved with it: a schema-enforcing backend (openai-api / codex / claude-code / claude-api) must answer
# all three fact groups even when `_candidate_block` asked about one. Absence is now
# spelled as an explicit null. What actually prevents a wrong disqualification is CODE,
# not schema permissiveness: `_screen_verdict` gates each check on the candidate having
# configured it AND on the model having named a recognized value (`_degree_stated` /
# an actual bool), and sponsorship labels are only honoured when their count matches the
# snippet count CODE supplied. The default ollama backend ignores the schema entirely (format=json
# constrains output to *some* object), so on it a blind check still arrives as an omitted
# key — which is why the value test, not a null test, is the one that holds everywhere.
# Those value tests enumerate the RECOGNIZED values, never the no-data spellings: the
# latter set is open-ended ("not stated", "TBD", "unclear", ...) and cannot be closed.
#
# `degree` asks for a LIST of levels plus a required/preferred bool, not for a single
# "minimum" — changed 2026-07-28 because the old shape asked the 4B for a JUDGMENT and it
# reliably got it wrong. Measured by `make eval-screen`: 9 of 38 live degree discards were
# false, the model reading "PhD, or Master's degree" and "PhD strongly preferred" as a hard
# PhD bar, all three draws agreeing. Two rounds of prompt wording moved the count to 4 and
# then 7 without converging. Listing the levels named is an EXTRACTION; taking the lowest
# is arithmetic CODE does — the same split every other check here already uses, and the
# reason `_check_degree` stopped being a comparison against one model-chosen value.
#
# The fit scorer's Stage 4 block (`_score_schema` above) deliberately still emits the old
# `required_degree`, and `_check_degree` reads BOTH. That block runs on a strong model,
# where the minimum is a judgment it can make; changing it would edit `score.txt`, whose
# gate is two consecutive quota-spending `score_eval` runs — a real cost for no measured
# benefit.
SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "screen": {
            "type": "object",
            "properties": {
                "degree": {
                    "type": "object",
                    "properties": {
                        "degree_levels": {"type": ["array", "null"],
                                          "items": {"type": "string"}},
                        "degree_required": {"type": ["boolean", "null"]},
                    },
                    "required": ["degree_levels", "degree_required"],
                    "additionalProperties": False,
                },
                "authorization": {
                    "type": "object",
                    "properties": {
                        # One label per numbered snippet CODE supplied, in order. The
                        # enum is enforced in `_check_authorization` rather than here:
                        # the default ollama backend ignores the schema entirely, so a
                        # code-side check is the only one that holds on every backend.
                        "sponsorship_labels": {"type": ["array", "null"],
                                               "items": {"type": "string",
                                                         "enum": ["refuses", "offers",
                                                                  "neither"]}},
                    },
                    "required": ["sponsorship_labels"],
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
    "required": ["screen"],
    "additionalProperties": False,
}
