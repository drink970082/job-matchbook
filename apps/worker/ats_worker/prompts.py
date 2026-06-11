"""Load prompts from the prompts/ directory at import time.

Each stage has ONE file (tailor.txt, score.txt) split into named sections by
`@@ <name>` marker lines — `@@` is used because the prompt bodies themselves use
`=== … ===` as content delimiters, so the splitter must not collide with those.
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


_t = _sections("tailor.txt")
_s = _sections("score.txt")

# tailor (Claude API)
FABRICATION_GUARD: str = _t["guard"]            # injected inline via {guard}
BASE_PROMPT: str = _t["base"] + "\n"
FEEDBACK_PROMPT: str = _t["feedback"] + "\n"

# score (Ollama) — TWO separate calls. SCORE_HEADER drives the fit-score call
# (rubric + résumé + job); SCREEN_HEADER + the checklist drive the screening call
# (job + hard requirements, NO résumé, so it can't anchor on the candidate's
# current address).
SCORE_HEADER: str = _s["score_header"] + "\n"
SCREEN_HEADER: str = _s["screen_header"] + "\n"

# screen checklist clauses (assembled line-by-line in score.py, so these stay
# bare: the join there supplies the newlines). Each c_* clause has a single
# {value} placeholder and maps 1:1 to a "screen" key the model must return.
SCREEN_LIST_HEADER: str = _s["screen_list_header"]
SCORE_C_EXPERIENCE: str = _s["c_experience"]
SCORE_C_DEGREE: str = _s["c_degree"]
SCORE_C_AUTHORIZATION: str = _s["c_authorization"]
SCORE_C_CLEARANCE: str = _s["c_clearance"]
SCORE_C_LOCATION: str = _s["c_location"]
SCORE_C_DEALBREAKERS: str = _s["c_dealbreakers"]
SCREEN_FOOTER: str = _s["screen_footer"]
