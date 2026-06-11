"""Score a job posting against the resume using a local Ollama model.

WHY Ollama (local) rather than a hosted LLM: scoring runs over every freshly
fetched posting, so doing it on a local model keeps cost at zero and avoids
rate limits — the expensive, quality-sensitive step (tailoring) is the only one
that goes to Claude.

TWO calls per posting, on purpose. A small local model (qwen3.5:4b) is unreliable
when asked to both screen hard constraints AND score fit in one overloaded prompt
— it lets a strong fit wash out a failed constraint, and anchors location on the
résumé's home city. So we split:
  1. SCORE  — rubric + résumé + job  -> fit score 0-100 + matched/missing keywords.
  2. SCREEN — job + the candidate's hard requirements, with NO résumé -> a per-
              requirement pass/fail; `disqualified` is derived from those verdicts.
The screen call has no résumé so it can't anchor on where the candidate lives, and
each call's output is small (no truncation). Screening is skipped entirely when no
candidate constraints are configured.

`http` is injected (defaults to `requests`) so tests exercise parsing with a fake
transport and zero network. Ollama wraps output in {"response": "<json string>"}
under format=json; we parse that inner string defensively and raise ScoreError on
anything unusable so the pipeline can mark one posting failed, not abort the batch.
"""
from __future__ import annotations

import json
import re

import requests

from ats_worker.prompts import (
    SCORE_C_AUTHORIZATION,
    SCORE_C_CLEARANCE,
    SCORE_C_DEALBREAKERS,
    SCORE_C_DEGREE,
    SCORE_C_EXPERIENCE,
    SCORE_C_LOCATION,
    SCORE_HEADER,
    SCREEN_FOOTER,
    SCREEN_HEADER,
    SCREEN_LIST_HEADER,
)

# How each configured hard requirement is screened. For the structured fields the
# LLM only EXTRACTS a fact about the JOB and CODE applies the candidate's
# constraint (a 4B model is unreliable at the pass/fail judgment itself — it leaks
# senior roles, mismatches degrees, can't tell a US city is "in" the USA). Only
# `dealbreakers` (free-text the user writes) stays an LLM {pass, note}. A skill the
# model invents as a key is ignored, so a skill gap can never disqualify.
DEGREE_RANK = {0: "none", 1: "high school", 2: "associate", 3: "bachelor's",
               4: "master's", 5: "phd"}

# The 4B model tends to invent the "convenient" value for facts a JD leaves unstated
# — it guesses offers_sponsorship="no" and remote=true out of silence. We only honour
# those two claims if the posting text actually contains the relevant language; this
# can only DOWNGRADE an unsupported guess, so it never causes a wrong discard.
_SPONSOR_HINTS = ("sponsor", "visa", "citizen", "work authoriz", "authorized to work",
                  "green card", "immigration", "right to work", "eligible to work")
_REMOTE_HINTS = ("remote", "work from home", "work-from-home", "wfh", "work from anywhere",
                 "fully remote", "remotely", "location independent", "location-independent")

# Country aliases normalised so the LLM's free-form country ("United States") and
# the candidate's config ("USA") compare equal. Only the common multi-spelling
# countries need entries; everything else compares on its lowercased name.
_COUNTRY_ALIASES = {
    "us": "usa", "u.s": "usa", "u.s.a": "usa", "usa": "usa", "america": "usa",
    "united states": "usa", "united states of america": "usa", "the united states": "usa",
    "uk": "uk", "u.k": "uk", "united kingdom": "uk", "britain": "uk",
    "great britain": "uk", "england": "uk",
}


class ScoreError(RuntimeError):
    """The model returned output we could not parse into a valid score."""


def _truncate(text: str, max_chars: int) -> str:
    """Cap a board-controlled blob so it can't blow the context window.

    Ollama silently drops tokens past num_ctx; a visible marker is better than a
    half-read JD scored as if complete.
    """
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n\n…[description truncated to fit context]"
    return text


def _job_block(posting: dict, max_desc_chars: int) -> str:
    """The shared JOB section (title, company, location, description)."""
    description = _truncate(str(posting.get("description", "")), max_desc_chars)
    location = str(posting.get("location") or "").strip() or "(not specified)"
    return (
        f"=== JOB: {posting.get('job_title', '')} at {posting.get('company_name', '')} ===\n"
        f"Location: {location}\n"
        f"{description}\n"
    )


def _candidate_block(candidate) -> str:
    """Render the hard-requirement checklist for the SCREEN call, or '' if nothing
    is configured. Each configured structured field becomes one clause keyed to a
    "screen" key the model returns a pass/fail verdict for (prose lives in
    prompts/score.txt). Only control flow + layout live here.
    """
    if not candidate:
        return ""
    years = candidate.get("years_experience")
    degree = str(candidate.get("highest_degree") or "").strip()
    auth = str(candidate.get("work_authorization") or "").strip()
    clearance = str(candidate.get("security_clearance") or "").strip()
    locations = [str(l) for l in (candidate.get("locations") or []) if str(l).strip()]
    dealbreakers = [str(d) for d in (candidate.get("dealbreakers") or []) if str(d).strip()]

    # The structured clauses are pure extraction instructions (the model reports a
    # JOB fact; code compares it to the candidate config), so they carry no {value}.
    # Only dealbreakers needs the candidate's list interpolated.
    clauses: list[str] = []
    if years is not None:
        clauses.append(SCORE_C_EXPERIENCE)
    if degree:
        clauses.append(SCORE_C_DEGREE)
    if auth:
        clauses.append(SCORE_C_AUTHORIZATION)
    if clearance:
        clauses.append(SCORE_C_CLEARANCE)
    if locations:
        clauses.append(SCORE_C_LOCATION)
    if dealbreakers:
        clauses.append(SCORE_C_DEALBREAKERS.format(value="; ".join(dealbreakers)))

    if not clauses:
        return ""
    lines = ["", SCREEN_LIST_HEADER, *clauses, SCREEN_FOOTER]
    return "\n".join(lines) + "\n"


def score_posting(
    posting: dict,
    resume_text: str,
    *,
    model: str,
    http=requests,
    ollama_host: str,
    timeout: int = 180,
    candidate: dict | None = None,
    temperature: float = 0.0,
    seed: int = 0,
    num_ctx: int = 8192,
) -> dict:
    """Ask Ollama to score `posting` against `resume_text` (and screen it).

    Returns {"score": int 0-100, "matched_keywords": [...],
    "missing_keywords": [...], "reasoning": str, "screen": {key: {pass, note}},
    "disqualified": bool, "disqualification_reason": str}. `disqualified` is
    DERIVED from the per-requirement screen verdicts (any fail), not taken from
    the model directly. Raises ScoreError on unparseable output.

    `temperature=0` + a fixed `seed` make results reproducible run-to-run (the
    score gates an expensive tailoring step). `num_ctx` is set explicitly because
    Ollama's small default silently truncates long JDs; the description is also
    pre-capped, and `num_predict` bounds the answer length.
    """
    options = {
        "temperature": temperature,
        "seed": seed,
        "num_ctx": num_ctx,
        # Cap generation: the JSON answers are small, so this only bounds a
        # runaway (which otherwise stalls a call past the read timeout).
        "num_predict": 512,
    }
    job = _job_block(posting, num_ctx * 2)

    # 1. SCORE — fit only (rubric + résumé + job). Always runs.
    score_prompt = SCORE_HEADER + f"\n=== RESUME ===\n{resume_text}\n\n" + job
    result = _normalize_score(
        _post(http, ollama_host, model, score_prompt, options=options, timeout=timeout)
    )

    # 2. SCREEN — hard requirements only (job + checklist, NO résumé). Skipped when
    # nothing is configured, so disqualification stays disabled.
    checklist = _candidate_block(candidate)
    if checklist:
        screen_data = _post(http, ollama_host, model, SCREEN_HEADER + checklist + "\n" + job,
                            options=options, timeout=timeout)
        description = str(posting.get("description") or "")
        result.update(_screen_verdict(screen_data, candidate or {}, description))
    else:
        result.update({"screen": {}, "disqualified": False, "disqualification_reason": ""})
    return result


def _post(http, ollama_host: str, model: str, prompt: str, *, options: dict, timeout: int) -> dict:
    """One Ollama /api/generate call, returning the parsed JSON object."""
    resp = http.post(
        f"{ollama_host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "format": "json",
            # Disable "thinking" mode. Reasoning models (Qwen3/Qwen3.5, etc.)
            # otherwise route output to a separate `thinking` field and leave
            # `response` EMPTY under format=json, so parsing fails on every posting.
            "think": False,
            "stream": False,
            # Keep the model resident between the two calls per posting and across
            # the batch, so it isn't unloaded+reloaded (the main cause of stalls).
            "keep_alive": "10m",
            "options": options,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    envelope = resp.json()
    inner = envelope.get("response", "") if isinstance(envelope, dict) else ""
    try:
        data = json.loads(inner)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScoreError(f"Ollama returned non-JSON response: {inner!r}") from exc
    if not isinstance(data, dict):
        raise ScoreError(f"Ollama response was not a JSON object: {data!r}")
    return data


def _normalize_score(data: dict) -> dict:
    """Validate the SCORE call's output (score is required)."""
    if "score" not in data:
        # Absent score must fail loudly — burying it as 0 is indistinguishable
        # from a genuine 0 and would silently exclude the posting from tailoring.
        raise ScoreError(f"response missing required 'score': {data!r}")
    return {
        "score": _coerce_score(data["score"]),
        "matched_keywords": _as_str_list(data.get("matched_keywords")),
        "missing_keywords": _as_str_list(data.get("missing_keywords")),
        "reasoning": str(data.get("reasoning") or ""),
    }


def _coerce_score(raw) -> int:
    """Accept int, float, or numeric string (85 / 85.7 / "85"); clamp to 0-100.

    A non-numeric score (e.g. "high") is unusable and raises, rather than being
    silently buried as a 0 that would exclude the posting from tailoring.
    """
    try:
        value = round(float(raw))
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"score is not numeric: {raw!r}") from exc
    return max(0, min(100, value))


def _screen_verdict(data: dict, candidate: dict, description: str = "") -> dict:
    """Decide disqualification from the SCREEN call's extracted JOB facts.

    For each configured structured requirement the LLM only EXTRACTED a fact about
    the job; here CODE applies the candidate's constraint (degree rank, years gap,
    sponsorship, clearance, location membership). This takes the unreliable pass/fail
    judgment off a 4B model entirely. `dealbreakers` is the one exception — free-text
    the user writes, so it stays an LLM {pass, note}. A requirement the candidate
    didn't configure is skipped, and a key the model invents (e.g. "skills") is
    ignored, so a skill gap can never disqualify. On missing/garbled extraction each
    checker errs toward PASS (don't discard on absent data).
    """
    screen = data.get("screen") if isinstance(data.get("screen"), dict) else {}
    clean: dict = {}
    failures: list[str] = []

    def gate(key, configured, passed, note):
        if not configured:
            return
        clean[key] = {"pass": passed, "note": note}
        if not passed:
            failures.append(f"{key}: {note}" if note else key)

    entry = lambda k: screen.get(k) if isinstance(screen.get(k), dict) else {}

    gate("experience", candidate.get("years_experience") is not None,
         *_check_experience(entry("experience"), candidate.get("years_experience")))
    gate("degree", bool(str(candidate.get("highest_degree") or "").strip()),
         *_check_degree(entry("degree"), candidate.get("highest_degree")))
    gate("authorization", bool(str(candidate.get("work_authorization") or "").strip()),
         *_check_authorization(entry("authorization"),
                               candidate.get("work_authorization"), description))
    gate("clearance", bool(str(candidate.get("security_clearance") or "").strip()),
         *_check_clearance(entry("clearance"), candidate.get("security_clearance")))
    gate("location", bool(candidate.get("locations")),
         *_check_location(entry("location"), candidate.get("locations") or [], description))

    # dealbreakers: free-text, so the LLM keeps the pass/fail judgment here.
    if candidate.get("dealbreakers"):
        db = entry("dealbreakers")
        passed = _passed(db.get("pass"))
        note = str(db.get("note") or "").strip()
        gate("dealbreakers", True, passed, note)

    return {
        "screen": clean,
        "disqualified": bool(failures),
        "disqualification_reason": "; ".join(failures),
    }


def _check_experience(entry: dict, cand_years) -> tuple[bool, str]:
    """Fail a clearly-too-senior role: a Senior/Staff/Principal/Lead title, or a
    required minimum at least 4 years beyond the candidate's experience."""
    cand = _to_num(cand_years) or 0.0
    if _flag(entry.get("senior")):
        return False, "senior-level role"
    min_req = _to_num(entry.get("min_years_required"))
    if min_req is not None and min_req - cand >= 4:
        return False, f"requires ~{_fmt_num(min_req)}+ years"
    return True, ""


def _check_degree(entry: dict, cand_degree) -> tuple[bool, str]:
    """Fail only when the role requires a higher degree than the candidate holds."""
    required = entry.get("required_degree")
    if required is None or not str(required).strip():
        return True, ""
    req_rank = _degree_rank(required)
    if req_rank > _degree_rank(cand_degree):
        return False, f"requires {DEGREE_RANK.get(req_rank, str(required))}"
    return True, ""


def _check_authorization(entry: dict, cand_auth, description: str = "") -> tuple[bool, str]:
    """Fail only when the candidate needs sponsorship and the role explicitly won't
    provide it. 'unknown' (the JD is silent) passes — most JDs don't mention it. A
    model "no" is only trusted if the JD actually mentions sponsorship/authorization
    (the model otherwise invents "no" from silence)."""
    if not _needs_sponsorship(cand_auth):
        return True, ""
    offers = _norm_simple(entry.get("offers_sponsorship"))
    explicit_no = offers in (
        "no", "none", "false", "no sponsorship", "not offered", "without sponsorship",
    )
    if explicit_no and _mentions(description, _SPONSOR_HINTS):
        return False, "no visa sponsorship offered"
    return True, ""


def _check_clearance(entry: dict, cand_clearance) -> tuple[bool, str]:
    """Fail only when the candidate has no clearance and the role requires one."""
    if _norm_simple(cand_clearance) not in ("", "none"):
        return True, ""  # candidate holds a clearance -> assume sufficient
    if _flag(entry.get("requires_clearance")):
        return False, "requires security clearance"
    return True, ""


def _check_location(
    entry: dict, allowed_locations: list, description: str = ""
) -> tuple[bool, str]:
    """Pass if the role is remote (and remote is allowed) OR its country is an allowed
    location. The LLM did the geography (city → country); this is exact membership, so
    a US city always matches an allowed 'USA'. A model remote=true is only trusted if
    the JD actually mentions remote work (the model otherwise marks on-site foreign
    roles remote). Missing country → pass."""
    allowed = {_norm_loc(l) for l in allowed_locations if str(l).strip()}
    country = str(entry.get("country") or "").strip()
    remote = _flag(entry.get("remote")) and _mentions(description, _REMOTE_HINTS)
    if "remote" in allowed and remote:
        return True, f"{country} (remote)" if country else "remote"
    if not country:
        return True, ""
    if _norm_loc(country) in allowed:
        return True, country
    return False, f"on-site in {country}"


# --- value coercion helpers ----------------------------------------------

def _to_num(value) -> float | None:
    """First number in the value (so '5+', '3-5', 5, '5 years' all work), or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(m.group()) if m else None


def _fmt_num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _mentions(description: str, hints: tuple[str, ...]) -> bool:
    """True if the JD text contains any of `hints` (used to sanity-check the model's
    sponsorship/remote guesses against the source)."""
    t = (description or "").lower()
    return any(h in t for h in hints)


def _norm_simple(value) -> str:
    """Lowercase, drop punctuation, collapse spaces — for loose token matching."""
    return " ".join(str(value).strip().lower().replace("-", " ").replace(".", " ").split())


def _norm_loc(value) -> str:
    """Normalise a country for comparison, folding common multi-spellings
    (United States == USA == US)."""
    t = " ".join(str(value).strip().lower().replace(".", "").split())
    return _COUNTRY_ALIASES.get(t, t)


def _degree_rank(value) -> int:
    """Rank a degree name (substring match, so 'Bachelor's or higher' -> 3)."""
    t = _norm_simple(value)
    if not t or "none" in t or "no degree" in t:
        return 0
    if "phd" in t or "ph d" in t or "doctora" in t:
        return 5
    if "master" in t:
        return 4
    if "bachelor" in t:
        return 3
    if "associate" in t:
        return 2
    if "high school" in t or "diploma" in t or "ged" in t:
        return 1
    return 0


def _needs_sponsorship(value) -> bool:
    """True if the candidate's work_authorization indicates they need sponsorship."""
    t = _norm_simple(value)
    if "sponsor" not in t:
        return False  # citizen / permanent resident / authorized
    if any(x in t for x in ("no sponsor", "without sponsor", "not need", "dont need", "no visa")):
        return False
    return True


def _flag(value) -> bool:
    """Truthy for real bools, 1/0, and the strings true/yes/1/remote/required."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "remote", "required"}
    return False


def _passed(value) -> bool:
    """Interpret a dealbreakers `pass` field. Missing (None) → pass (benefit of the
    doubt — never disqualify on absent data); everything except false/no/0 is a pass."""
    if value is None:
        return True
    return _flag(value) or (isinstance(value, str) and value.strip().lower() == "pass")


def _as_str_list(value) -> list[str]:
    """Coerce the model's keyword field to a flat list of strings.

    Tolerates a bare string (wrapped) and one level of nesting (flattened) so a
    slightly-off shape doesn't silently drop keywords that downstream tailoring
    relies on.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if isinstance(v, list):
            out += [str(x) for x in v]
        else:
            out.append(str(v))
    return out
