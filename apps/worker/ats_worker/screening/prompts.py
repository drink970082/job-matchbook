"""Standalone screen prompt resources and rendering; no legacy fit prompt imports."""
from __future__ import annotations

import re
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1] / "prompts"
_SECTION = re.compile(r"^@@ +(\w+)\s*$", re.MULTILINE)

def _sections(filename: str) -> dict[str, str]:
    text = (_DIR / filename).read_text(encoding="utf-8")
    marks = list(_SECTION.finditer(text))
    out: dict[str, str] = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[mark.group(1)] = text[mark.end():end].strip("\n")
    return out

_screen = _sections("screen.txt")
SCREEN_HEADER: str = _screen["screen_header"] + "\n"
SCREEN_LIST_HEADER: str = _screen["screen_list_header"]
SCORE_C_DEGREE: str = _screen["c_degree"]
SCORE_C_AUTHORIZATION: str = _screen["c_authorization"]
SCORE_C_CLEARANCE: str = _screen["c_clearance"]
SCREEN_FOOTER: str = _screen["screen_footer"]

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
