"""Score a job posting against the resume: a fit SCORE (injected, Claude) plus a
hard-requirements SCREEN (local Ollama).

WHY the SCREEN call stays on local Ollama rather than a hosted LLM: it runs over
every freshly fetched posting, so keeping it local keeps cost at zero and avoids
rate limits — the expensive, quality-sensitive step (fit scoring)
goes to Claude instead, via the injected `score_fit` callable built in run.py.

UP TO TWO calls per posting, from two different backends, SCREEN-gated:
  1. SCREEN — job + the candidate's hard requirements, with NO résumé -> a per-
              requirement pass/fail; `disqualified` is derived from those verdicts.
              Runs FIRST (cheap, local Ollama). Skipped when no candidate
              constraints are configured.
  2. SCORE  — fit score 0-100 + matched/missing keywords, from an injected
              `fit_fn(postings) -> list[dict]` callable (Claude/codex, batch-first).
              Only reached when the screen did NOT disqualify — a discarded posting
              never pays for a fit score. `pipeline.run_score` composes the two:
              it calls `screen_posting` per row, gates the fit call on
              `disqualified`, then `pipeline._persist_scored` normalizes each raw
              fit result via `_normalize_score` (missing "score" raises) and merges
              the screen verdict on top before persisting.
The screen call has no résumé so it can't anchor on where the candidate lives, and
its output is small (no truncation).

`http` is injected (defaults to `None`; the real `requests` module is bound only
in run.py) so tests exercise the SCREEN call's parsing with a fake transport and
zero network. Ollama wraps output in
{"response": "<json string>"} under format=json; we parse that inner string
defensively and raise ScoreError on anything unusable so the pipeline can mark one
posting failed, not abort the batch.
"""
from __future__ import annotations

import json
import re

from ats_worker.prompts import SCREEN_HEADER

from .errors import ScoreError
from .location import resolve_location
from .prompts import _candidate_block, _job_block

# How each configured hard requirement is screened. For the structured fields the
# LLM only EXTRACTS a fact about the JOB and CODE applies the candidate's
# constraint (a 4B model is unreliable at the pass/fail judgment itself — it
# mismatches degrees, can't tell a US city is "in" the USA). A skill the model
# invents as a key is ignored, so a skill gap can never disqualify.
DEGREE_RANK = {0: "none", 1: "high school", 2: "associate", 3: "bachelor's",
               4: "master's", 5: "phd"}

# Authorization is gated deterministically off the JD text, NOT the 4B model's
# offers_sponsorship guess (D1): it invents "no" from silence, and the old loose
# substring guard fired on unrelated boilerplate — "sponsor" in "company-sponsored
# sports teams" (id=986), "citizen" in an EEO "citizenship" line (id=1071). Disqualify
# ONLY when the JD literally contains one of these explicit no-sponsorship phrases,
# substring-matched over the lowercased, whitespace-collapsed description.
NO_SPONSOR_PHRASES = (
    "will not sponsor", "does not sponsor", "do not sponsor", "cannot sponsor",
    "unable to sponsor", "not able to sponsor", "no visa sponsorship", "no sponsorship",
    "without sponsorship", "not provide sponsorship", "no immigration sponsorship",
    "must be authorized to work without sponsorship",
)

# Internship/co-op detection is deterministic from the title (gated by the
# candidate's exclude_internships flag): a 4B model is unreliable on this, but the
# title makes it trivial. Whole-word so "internal"/"international"/"cooperation" never match.
_INTERN_TITLE = re.compile(r"\bintern(ship)?s?\b|\bco[\s-]?op\b", re.IGNORECASE)


def screen_posting(
    posting: dict,
    *,
    http=None,
    ollama_host: str,
    model: str | None = None,
    candidate: dict | None = None,
    temperature: float = 0.0,
    seed: int = 0,
    num_ctx: int = 8192,
    timeout: int = 180,
) -> dict:
    """Screen `posting` against the candidate's hard requirements — the CHEAP, local
    half of scoring (Ollama, no résumé, no paid fit call). Combines three signals
    into one verdict:

      1. The Ollama SCREEN call (`http`/`ollama_host`/`model`) extracts structured
         JOB facts (required degree, sponsorship, clearance) for whatever the
         candidate configured; CODE (`_screen_verdict`) applies the candidate's
         constraint. Skipped entirely when no candidate constraints are configured.
         A parse failure errs toward KEEP (not disqualified), never toward discard.
      2. A deterministic intern/co-op title check, gated by `exclude_internships`.
      3. A deterministic pycountry LOCATION gate (`resolve_location`), gated by
         `candidate["locations"]`, matched against the board's location string.

    Returns `{"screen": {...per-requirement verdicts...}, "disqualified": bool,
    "disqualification_reason": str}`. Takes no fit-scorer callable — it structurally
    cannot call the (paid) fit scorer; `pipeline.run_score` composes this and decides
    whether `disqualified` gates out the fit call.
    """
    options = {
        "temperature": temperature,
        "seed": seed,
        "num_ctx": num_ctx,
        # Cap generation: the JSON answers are small, so this only bounds a
        # runaway (which otherwise stalls a call past the read timeout).
        "num_predict": 512,
    }

    # SCREEN — hard requirements only (job + checklist, NO résumé), the CHEAP
    # local call. Skipped when nothing is configured. A parse failure must NOT
    # discard the posting (or fail the row) — the design errs toward keep — so it
    # falls back to not-screened / not-disqualified.
    job = _job_block(posting, num_ctx * 2)
    description = str(posting.get("description") or "")
    checklist = _candidate_block(candidate)
    if checklist:
        try:
            screen_data = _post(http, ollama_host, model, SCREEN_HEADER + checklist + "\n" + job,
                                options=options, timeout=timeout)
            screen = _screen_verdict(screen_data, candidate or {}, description)
        except ScoreError:
            screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    else:
        screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    # Deterministic intern/co-op exclusion — title-only (free, no LLM), so it runs
    # even when no SCREEN call was made. The 4B model is unreliable here; the title
    # is a clean signal. Merges a hard fail into the screen verdict.
    if candidate and candidate.get("exclude_internships") and _is_internship(
        str(posting.get("job_title") or "")
    ):
        screen.setdefault("screen", {})["internships"] = {"pass": False, "note": "internship/co-op role"}
        prior = screen.get("disqualification_reason") or ""
        screen["disqualified"] = True
        screen["disqualification_reason"] = (
            f"{prior}; internship/co-op role" if prior else "internship/co-op role"
        )

    # Deterministic LOCATION gate — matched in CODE against the board's location
    # string (posting["location"]) via pycountry, NOT the LLM. Runs when the
    # candidate configured allowed locations; merged into the screen verdict like
    # the internship check above.
    if candidate and candidate.get("locations"):
        passed, note = resolve_location(posting.get("location"), candidate["locations"])
        screen.setdefault("screen", {})["location"] = {"pass": passed, "note": note}
        if not passed:
            prior = screen.get("disqualification_reason") or ""
            reason = f"location: {note}" if note else "location"
            screen["disqualified"] = True
            screen["disqualification_reason"] = f"{prior}; {reason}" if prior else reason

    return screen


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


_SENIORITY_VERDICTS = frozenset(("match", "too_junior", "too_senior"))
_DOMAIN_VERDICTS = frozenset(("match", "adjacent", "mismatch"))


def _normalize_score(data: dict) -> dict:
    """Validate the SCORE call's output: both `score` and a well-formed `assessment`
    scorecard are required, and both fail loudly — a missing score buried as 0 would
    silently exclude the posting from notification, and a malformed assessment means the
    model didn't produce the per-dimension verdicts the ranking + audit depend on (S2.1)."""
    if "score" not in data:
        raise ScoreError(f"response missing required 'score': {data!r}")
    out = {
        "score": _coerce_score(data["score"]),
        "assessment": _normalize_assessment(data.get("assessment")),
        # Lenient: absent/garbled -> False (err toward scoreable), matching the gates.
        "insufficient_context": bool(data.get("insufficient_context")),
    }
    recommended = str(data.get("recommended_resume") or "").strip()
    if recommended:
        out["recommended_resume"] = recommended
    return out


def _normalize_assessment(value) -> dict:
    """Validate + coerce the scorecard. The seniority/domain verdicts must be in-enum
    (raise ScoreError otherwise — they drive D3's seniority floor and the ranking); the
    keyword lists and summary are coerced leniently since they only feed the UI."""
    if not isinstance(value, dict):
        raise ScoreError(f"score missing required 'assessment' object: {value!r}")

    def _verdict(key, allowed):
        entry = value.get(key)
        if not isinstance(entry, dict):
            raise ScoreError(f"assessment.{key} must be an object: {entry!r}")
        verdict = str(entry.get("verdict") or "")
        if verdict not in allowed:
            raise ScoreError(
                f"assessment.{key}.verdict {verdict!r} not one of {sorted(allowed)}")
        return {"verdict": verdict, "note": str(entry.get("note") or "")}

    must = value.get("must_haves") if isinstance(value.get("must_haves"), dict) else {}
    nice = value.get("nice_to_haves") if isinstance(value.get("nice_to_haves"), dict) else {}
    return {
        "seniority": _verdict("seniority", _SENIORITY_VERDICTS),
        "domain": _verdict("domain", _DOMAIN_VERDICTS),
        "must_haves": {"met": _as_str_list(must.get("met")),
                       "missing": _as_str_list(must.get("missing"))},
        "nice_to_haves": {"missing": _as_str_list(nice.get("missing"))},
        "summary": str(value.get("summary") or ""),
    }


def _coerce_score(raw) -> int:
    """Accept int, float, or numeric string (85 / 85.7 / "85"); clamp to 0-100.

    A non-numeric score (e.g. "high") is unusable and raises, rather than being
    silently buried as a 0 that would exclude the posting from notification.
    """
    try:
        value = round(float(raw))
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"score is not numeric: {raw!r}") from exc
    return max(0, min(100, value))


def _screen_verdict(data: dict, candidate: dict, description: str = "") -> dict:
    """Decide disqualification from the SCREEN call's extracted JOB facts.

    For each configured structured requirement the LLM only EXTRACTED a fact about
    the job; here CODE applies the candidate's constraint (degree rank, sponsorship,
    clearance). This takes the unreliable pass/fail judgment off a 4B model entirely.
    (Location is NOT gated here — it is a deterministic pycountry gate applied
    in `screen_posting`; see `resolve_location`.) A requirement the candidate didn't
    configure is skipped, and a key the model invents (e.g. "skills") is ignored, so a
    skill gap can never disqualify. On missing/garbled extraction each checker errs
    toward PASS (don't discard on absent data).
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

    gate("degree", bool(str(candidate.get("highest_degree") or "").strip()),
         *_check_degree(entry("degree"), candidate.get("highest_degree")))
    gate("authorization", bool(str(candidate.get("work_authorization") or "").strip()),
         *_check_authorization(candidate.get("work_authorization"), description))
    gate("clearance", bool(str(candidate.get("security_clearance") or "").strip()),
         *_check_clearance(entry("clearance"), candidate.get("security_clearance")))

    return {
        "screen": clean,
        "disqualified": bool(failures),
        "disqualification_reason": "; ".join(failures),
    }


def _check_degree(entry: dict, cand_degree) -> tuple[bool, str]:
    """Fail only when the role requires a higher degree than the candidate holds."""
    required = entry.get("required_degree")
    if required is None or not str(required).strip():
        return True, ""
    req_rank = _degree_rank(required)
    if req_rank > _degree_rank(cand_degree):
        return False, f"requires {DEGREE_RANK.get(req_rank, str(required))}"
    return True, ""


def _check_authorization(cand_auth, description: str = "") -> tuple[bool, str]:
    """Fail only when the candidate needs sponsorship AND the JD literally states it
    won't sponsor. The 4B model's offers_sponsorship guess is NOT consulted — it
    invents "no" from silence, and 'unknown' (the JD is silent) passes. We trust only
    an explicit no-sponsorship PHRASE in the JD text (D1); the whitespace-collapse
    keeps a phrase matching across line wraps."""
    if not _needs_sponsorship(cand_auth):
        return True, ""
    text = " ".join((description or "").lower().split())
    if any(phrase in text for phrase in NO_SPONSOR_PHRASES):
        return False, "no visa sponsorship offered"
    return True, ""


def _check_clearance(entry: dict, cand_clearance) -> tuple[bool, str]:
    """Fail only when the candidate has no clearance and the role requires one."""
    if _norm_simple(cand_clearance) not in ("", "none"):
        return True, ""  # candidate holds a clearance -> assume sufficient
    if _flag(entry.get("requires_clearance")):
        return False, "requires security clearance"
    return True, ""


# --- value coercion helpers ----------------------------------------------

def _is_internship(title: str) -> bool:
    """Whole-word intern/internship/co-op match on the job title."""
    return bool(_INTERN_TITLE.search(title or ""))


def _norm_simple(value) -> str:
    """Lowercase, drop punctuation, collapse spaces — for loose token matching."""
    return " ".join(str(value).strip().lower().replace("-", " ").replace(".", " ").split())


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
    """Truthy for real bools, 1/0, and the strings true/yes/1/required."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "required"}
    return False


def _as_str_list(value) -> list[str]:
    """Coerce the model's keyword field to a flat list of strings.

    Tolerates a bare string (wrapped) and one level of nesting (flattened) so a
    slightly-off shape doesn't silently drop keywords that the UI
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
