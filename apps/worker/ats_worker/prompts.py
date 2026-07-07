"""Load prompts from the prompts/ directory at import time.

The scoring stage has TWO files (score.txt, screen.txt), each split into named
sections by `@@ <name>` marker lines — `@@` is used because the prompt bodies
themselves use `=== … ===` as content delimiters, so the splitter must not
collide with those.
"""
from __future__ import annotations

import re
from pathlib import Path

_DIR = Path(__file__).parent / "prompts"
_SECTION = re.compile(r"^@@ +(\w+)\s*$", re.MULTILINE)


def _sections(filename: str) -> dict[str, str]:
    """Split a prompt file into {section_name: body}.

    Each body is stripped of the blank lines separating sections; callers below
    restore a trailing newline where the assembled prompt needs one.
    """
    text = (_DIR / filename).read_text(encoding="utf-8")
    marks = list(_SECTION.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1)] = text[m.end():end].strip("\n")
    return out


_score = _sections("score.txt")
_screen = _sections("screen.txt")

# TWO calls, two backends, two files. SCORE_HEADER (score.txt) drives the fit-score
# call (rubric + résumé + job), sent to Claude. SCREEN_HEADER + the checklist
# (screen.txt) drive the hard-requirements call (job + requirements, NO résumé),
# sent to local Ollama. Location is NOT in the screen prompt — it is gated in code
# off the board's location field (see score.resolve_location).
SCORE_HEADER: str = _score["score_header"] + "\n"
SCREEN_HEADER: str = _screen["screen_header"] + "\n"

# screen checklist clauses (assembled line-by-line in score.py, so these stay bare:
# the join there supplies the newlines). Each maps 1:1 to a "screen" key.
SCREEN_LIST_HEADER: str = _screen["screen_list_header"]
SCORE_C_DEGREE: str = _screen["c_degree"]
SCORE_C_AUTHORIZATION: str = _screen["c_authorization"]
SCORE_C_CLEARANCE: str = _screen["c_clearance"]
SCORE_C_DEALBREAKERS: str = _screen["c_dealbreakers"]
SCREEN_FOOTER: str = _screen["screen_footer"]
