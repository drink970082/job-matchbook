"""The FREE seniority pre-ordering layer — a prioritizer, never a filter.

96% of paid fit calls come back a "no", and 54% of those are `seniority=too_junior`
(docs/PROGRESS.md, the 2026-07-30 verdict matrix). That half is reachable by a *free*
local extraction, because SCORING §4.2 measures seniority only against a bar the JD
states explicitly — a closed-vocabulary bounded extraction, which §9.1 lists as
weak-model-capable.

The shape is the one §8.1 arrived at for degree, and it is the whole design: the model
**extracts** what the posting literally states (`stated_min_years`, `stated_rank`) and
**code** compares that against the candidate. The model never decides.

What a `too_junior` verdict here does is send the row to the BACK of the score queue —
it stays `new`, observable and searchable, and a later deliberate pass still reaches it.
It is NOT a discard: these labels were learned against *Sol's verdicts, not human
labels*, so they inherit Sol's errors and are good enough to order work, not to delete
a posting (SCORING §9.3, discard-direction floors).
"""
from __future__ import annotations

import re

from .. import prompts
from .prompts import _job_block

# The closed vocabulary. Four ranks, because these are the four SCORING §4.2 counts as
# a stated seniority bar; "manager"/"director"/"VP" are a different axis and "junior"/
# "associate"/"mid-level" are not bars at all.
RANKS = ("senior", "lead", "staff", "principal")

# Years above the candidate's own experience at which a stated bar reads as a real one.
# 2 is what the 2026-07-30 run measured (P .967 / R .825 with the veto below, over 446
# rows), for a candidate at 0 years.
YEARS_MARGIN = 2
# Experience at which a JD naming one of the four ranks stops being a bar for this
# candidate. ponytail: a constant, not a config key — it only matters for a candidate
# who is themselves senior, and nothing measures it yet.
SENIOR_YEARS = 5

_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15}

# Every number written immediately before a years token, including ranges, parenthetical
# spellings and word forms: "5+ years", "three (3) years", "1-3 years", "two to four
# years", "5 yrs", "3 YOE".
_NUM = r"(?:\d{1,2}|" + "|".join(_WORDNUM) + r")"
_ONE = r"(" + _NUM + r")(?:\s*\(\s*(\d{1,2})\s*\))?"
_YEARS_RE = re.compile(
    _ONE + r"\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*" + _ONE + r"\s*(?:\+)?\s*)?"
    r"(?:\+\s*)?(?:years?|yrs?|yoe)\b", re.I)


def build_prompt(posting: dict, max_desc_chars: int) -> str:
    """The one-requirement prompt. Same skeleton as the screen call (header, list
    header, one clause, footer, job block) so both read the same way."""
    return (prompts.SENIORITY_HEADER
            + prompts.SENIORITY_LIST_HEADER + "\n"
            + prompts.SENIORITY_C_SENIORITY + "\n"
            + prompts.SENIORITY_FOOTER + "\n"
            + "\n" + _job_block(posting, max_desc_chars))


def read_entry(data) -> dict | None:
    """The `seniority` entry, or None for a blind response.

    Accepts both the wrapped `{"screen": {...}}` and the FLAT `{...}` shape, because
    the 4B drops the wrapper on roughly one call in a hundred while returning a
    complete, correct verdict — throwing those away is exactly the defect #48 fixed on
    the screen path (docs/BACKLOG.md, the blind-backend residual)."""
    if not isinstance(data, dict):
        return None
    block = data.get("screen") if isinstance(data.get("screen"), dict) else data
    if not isinstance(block, dict):
        return None
    entry = block.get("seniority")
    return entry if isinstance(entry, dict) else None


def normalize(entry) -> tuple[int | None, str | None]:
    """`(stated_min_years, stated_rank)` with the closed vocabulary enforced in CODE —
    anything outside it becomes None rather than a bar."""
    if not isinstance(entry, dict):
        return None, None
    years = entry.get("stated_min_years")
    if isinstance(years, bool):          # bool is an int in Python; a True is not a bar
        years = None
    elif isinstance(years, str):
        match = re.search(r"\d{1,2}", years)
        years = int(match.group()) if match else None
    elif isinstance(years, (int, float)):
        years = int(years)
    else:
        years = None
    rank = entry.get("stated_rank")
    rank = rank.strip().lower() if isinstance(rank, str) else None
    return years, (rank if rank in RANKS else None)


def stated_years(text: str) -> set[int]:
    """Every years-figure the text literally states."""
    out: set[int] = set()
    for match in _YEARS_RE.finditer(text):
        for group in match.groups():
            if group:
                group = group.lower()
                out.add(int(group) if group.isdigit() else _WORDNUM[group])
    return out


def clamp_years(years: int | None, job_text: str) -> int | None:
    """The keep-direction veto (SCORING §9.2, lever 4): clamp the model's number down
    to the smallest years-figure the JD literally states. Deterministic, and it can
    only ever LOWER a bar, so it cannot manufacture a demotion.

    It exists because §8.1's dominant error repeats verbatim here: on a degree-
    conditional ladder ("Master's and no experience; or Bachelor's and 3 years") the
    model reports one rung instead of the minimum across rungs. Measured 2026-07-30:
    false demotions 20 -> 7, P .921 -> .967."""
    if years is None:
        return None
    floor = stated_years(job_text)
    return min(years, min(floor)) if floor else years


def verdict(entry, *, job_text: str, years_experience: int = 0) -> str:
    """`"too_junior"` or `"match"`, decided in CODE. A blind or empty entry is a
    `match` — the keep direction, per PRINCIPLES' uncertainty policy."""
    years, rank = normalize(entry)
    years = clamp_years(years, job_text)
    if years is not None and years >= years_experience + YEARS_MARGIN:
        return "too_junior"
    if rank and years_experience < SENIOR_YEARS:
        return "too_junior"
    # ponytail: no title-token floor for the "Senior ..." titles the model returns an
    # empty object on (6 of 19 misses). That is a DISCARD-direction floor, so SCORING
    # §9.3 applies and it needs its own measurement first.
    return "match"


def assess(posting: dict, extract, *, years_experience: int = 0,
           max_desc_chars: int = 16384) -> tuple[str, dict]:
    """Run the free extraction for one posting and decide in code.

    `extract(prompt, schema) -> dict` is injected (the same callable the screen uses).
    A provider failure is a `match`: the layer is best-effort, and erring toward keep
    costs one paid call while erring toward demote costs a delay on a real job.
    """
    detail: dict = {}
    try:
        raw = extract(build_prompt(posting, max_desc_chars), {})
    except Exception as exc:  # noqa: BLE001 - any provider failure errs toward keep
        return "match", {"error": f"{type(exc).__name__}: {exc}"}
    entry = read_entry(raw)
    years, rank = normalize(entry)
    job_text = f"{posting.get('job_title', '')}\n{posting.get('description', '')}"
    clamped = clamp_years(years, job_text)
    detail = {"stated_min_years": years, "stated_rank": rank, "clamped_min_years": clamped}
    if entry is None:
        detail["blind"] = True
    return verdict(entry, job_text=job_text, years_experience=years_experience), detail
