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
  2. SCORE  — fit score 0-100 + matched/missing keywords, from the injected
              `score_fit(posting, resumes)` callable (Claude). Only reached
              when the screen did NOT disqualify — a discarded posting never pays
              for a fit score. Result normalized here (missing "score" raises).
The screen call has no résumé so it can't anchor on where the candidate lives, and
its output is small (no truncation).

`http` is injected (defaults to `requests`) so tests exercise the SCREEN call's
parsing with a fake transport and zero network. Ollama wraps output in
{"response": "<json string>"} under format=json; we parse that inner string
defensively and raise ScoreError on anything unusable so the pipeline can mark one
posting failed, not abort the batch.
"""
from __future__ import annotations

import json
import re

import pycountry
import requests

from ats_worker.prompts import (
    SCORE_C_AUTHORIZATION,
    SCORE_C_CLEARANCE,
    SCORE_C_DEGREE,
    SCORE_HEADER,
    SCREEN_FOOTER,
    SCREEN_HEADER,
    SCREEN_LIST_HEADER,
)

# How each configured hard requirement is screened. For the structured fields the
# LLM only EXTRACTS a fact about the JOB and CODE applies the candidate's
# constraint (a 4B model is unreliable at the pass/fail judgment itself — it
# mismatches degrees, can't tell a US city is "in" the USA). A skill the model
# invents as a key is ignored, so a skill gap can never disqualify.
DEGREE_RANK = {0: "none", 1: "high school", 2: "associate", 3: "bachelor's",
               4: "master's", 5: "phd"}

# The 4B model tends to invent remote=true out of silence. We only honour that guess
# when the LOCATION STRING actually says remote (see resolve_location); this can only
# DOWNGRADE an unsupported guess, so it never causes a wrong discard.
_REMOTE_HINTS = ("remote", "work from home", "work-from-home", "wfh", "work from anywhere",
                 "fully remote", "remotely", "location independent", "location-independent")

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

# Country aliases normalised so the LLM's free-form country ("United States") and
# the candidate's config ("USA") compare equal. Only the common multi-spelling
# countries need entries; everything else compares on its lowercased name.
_COUNTRY_ALIASES = {
    "us": "usa", "u.s": "usa", "u.s.a": "usa", "usa": "usa", "america": "usa",
    "united states": "usa", "united states of america": "usa", "the united states": "usa",
    "uk": "uk", "u.k": "uk", "united kingdom": "uk", "britain": "uk",
    "great britain": "uk", "england": "uk",
}

# US subdivisions (states + territories), built once at import. Used to KEEP a US
# role whose location string names only a state ("New York, New York", "Austin, TX")
# and to win the state/country name collision ("Atlanta, Georgia": Georgia is a US
# state AND a country — the state reading wins when the candidate allows USA).
_US_STATE_NAMES = {s.name.lower() for s in pycountry.subdivisions if s.country_code == "US"}
_US_STATE_CODES = {s.code.split("-")[1] for s in pycountry.subdivisions if s.country_code == "US"}


class ScoreError(RuntimeError):
    """The model returned output we could not parse into a valid score."""


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
    },
    "required": ["assessment", "score"],
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


def _scorer_system_blocks(resumes: dict, profile: str = "") -> list[dict]:
    """System-prefix blocks for the Claude fit call: rubric header, optional
    personal profile, then one block per labeled resume version. cache_control
    goes on the LAST block so the whole prefix — byte-identical every call in a
    run — is cached once (per-posting marginal cost stays flat)."""
    blocks: list[dict] = [{"type": "text", "text": SCORE_HEADER}]
    if str(profile or "").strip():
        blocks.append({"type": "text", "text": f"=== PERSONAL PROFILE ===\n{profile}"})
    for label, text in resumes.items():
        blocks.append({"type": "text", "text": f"=== RESUME ({label}) ===\n{text}"})
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


def _candidate_block(candidate) -> str:
    """Render the hard-requirement checklist for the SCREEN call, or '' if nothing
    is configured. Each configured structured field becomes one clause keyed to a
    "screen" key the model returns a pass/fail verdict for (prose lives in
    prompts/screen.txt). Only control flow + layout live here.
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
    if auth:
        clauses.append(SCORE_C_AUTHORIZATION)
    if clearance:
        clauses.append(SCORE_C_CLEARANCE)

    if not clauses:
        return ""
    lines = ["", SCREEN_LIST_HEADER, *clauses, SCREEN_FOOTER]
    return "\n".join(lines) + "\n"


def score_posting(
    posting: dict,
    resumes,
    *,
    score_fit,
    http=requests,
    ollama_host: str,
    model: str | None = None,
    timeout: int = 180,
    candidate: dict | None = None,
    temperature: float = 0.0,
    seed: int = 0,
    num_ctx: int = 8192,
) -> dict:
    """Screen `posting` against the candidate's hard requirements, then fit-SCORE it.

    SCREEN runs FIRST and GATES the fit score: the local Ollama screen (hard
    requirements, NO résumé — `http`/`ollama_host`/`model`) plus the deterministic
    intern/co-op title check derive `disqualified`; when it's True we return score 0
    WITHOUT calling the (paid) Claude scorer, since a disqualified posting is
    discarded regardless of fit. When it passes, the injected
    `score_fit(posting, resumes) -> dict` (Claude, built in run.py) is called and
    normalized here (a missing `score` raises ScoreError). `resumes` is the
    `{label: text}` dict of resume versions — score_posting itself never reads it
    (pure pass-through). The SCREEN call is skipped
    when no candidate constraints are configured, and a SCREEN parse failure errs
    toward keep (not disqualified). Raises ScoreError on an unusable fit result.
    """
    options = {
        "temperature": temperature,
        "seed": seed,
        "num_ctx": num_ctx,
        # Cap generation: the JSON answers are small, so this only bounds a
        # runaway (which otherwise stalls a call past the read timeout).
        "num_predict": 512,
    }

    # 1. SCREEN — hard requirements only (job + checklist, NO résumé), the CHEAP
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

    # GATE — a disqualified posting is discarded regardless of fit, so SKIP the paid
    # Claude SCORE. Record score 0 (no fit assessed) + the screen verdict; run_score
    # routes it to 'discarded' with the reason.
    if screen["disqualified"]:
        return {"score": 0, **screen}  # fit skipped -> no assessment (discarded row)

    # 2. SCORE — passed the screen, so pay for the Claude fit score (injected).
    # Normalized here (missing score -> raise).
    result = _normalize_score(score_fit(posting, resumes))
    result.update(screen)
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
    (Location is NOT gated here — it is a deterministic pycountry gate in
    `score_posting`; see `resolve_location`.) A requirement the candidate didn't
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

def _mentions(description: str, hints: tuple[str, ...]) -> bool:
    """True if the JD text contains any of `hints` (used to sanity-check the model's
    sponsorship/remote guesses against the source)."""
    t = (description or "").lower()
    return any(h in t for h in hints)


def _is_internship(title: str) -> bool:
    """Whole-word intern/internship/co-op match on the job title."""
    return bool(_INTERN_TITLE.search(title or ""))


def _norm_simple(value) -> str:
    """Lowercase, drop punctuation, collapse spaces — for loose token matching."""
    return " ".join(str(value).strip().lower().replace("-", " ").replace(".", " ").split())


def _norm_loc(value) -> str:
    """Normalise a country for comparison, folding common multi-spellings
    (United States == USA == US)."""
    t = " ".join(str(value).strip().lower().replace(".", "").split())
    return _COUNTRY_ALIASES.get(t, t)


def _is_us_state(token: str) -> bool:
    """True if `token` is a US state/territory name ('California') or 2-letter code ('CA')."""
    t = token.strip()
    return t.lower() in _US_STATE_NAMES or t.upper() in _US_STATE_CODES


def _country_code(token: str) -> str | None:
    """ISO alpha-2 for a country name/code token ('China'->'CN', 'USA'->'US'), else None."""
    try:
        return pycountry.countries.lookup(token.strip()).alpha_2
    except LookupError:
        return None


_CITY_INDEX: dict[str, str] | None = None


def _city_index() -> dict[str, str]:
    """Lazy geonamescache index: lowercased city name -> ISO alpha-2 of the
    HIGHEST-POPULATION city with that name. Built once (~32k cities, a few MB) on first
    use — fine for the batch worker. No US bias: a tiny US namesake (Paris TX, Amsterdam
    NY) must NOT override the world city it shares a name with, or clearly-foreign
    postings would leak through the gate."""
    global _CITY_INDEX
    if _CITY_INDEX is None:
        import geonamescache  # heavy data payload — deferred to first location gate
        idx: dict[str, str] = {}
        best: dict[str, int] = {}
        for c in geonamescache.GeonamesCache().get_cities().values():
            name = c["name"].lower()
            pop = c.get("population") or 0
            if name not in best or pop > best[name]:
                best[name] = pop
                idx[name] = c["countrycode"]
        _CITY_INDEX = idx
    return _CITY_INDEX


def _token_country(token: str) -> str | None:
    """ISO alpha-2 for a single location token, or None if unresolved. US state (name
    or 2-letter code) wins FIRST — so 'CA'->US not Canada, 'Georgia'->US not the country
    — then a country name/code (pycountry), then a city via geonamescache."""
    t = (token or "").strip()
    if not t:
        return None
    if _is_us_state(t):
        return "US"
    code = _country_code(t)
    if code:
        return code
    return _city_index().get(t.lower())


def _country_name(code: str) -> str:
    """Human country name for an ISO alpha-2 code (used in the discard reason)."""
    c = pycountry.countries.get(alpha_2=code)
    return c.name if c else code


def resolve_location(location_str, allowed_locations) -> tuple[bool, str]:
    """Decide keep/discard for a posting's board `location` string against the
    candidate's `allowed_locations`, in CODE (no LLM). Errs toward KEEP: discards
    only when the string clearly resolves to a disallowed country.

    Order:
      (A) missing location -> keep.
      (B) remote: if 'remote' is allowed and the LOCATION STRING says remote -> keep.
          (Keyed off the board location field, NOT the JD prose, so a JD that merely
          says 'not remote' can't false-match.)
      (C) direct match: an allowed entry equals a location token, with country
          aliasing via _norm_loc (allowed 'USA' matches token 'United States'; an
          allowed city/state matches that token).
      (D) US-state precedence: a US-state token keeps when USA is allowed (also
          settles the Georgia state-vs-country collision).
      (E) foreign: resolve EVERY token to a country (city->country via geonamescache,
          highest-population match), not just the last. Keep if any token is US (the
          operator is US-based; this also keeps the IL/CA/GA postal codes, read as US
          states, not Israel/Canada/Gabon) or an allowed country; discard only when
          >=1 token resolves and none are allowed, naming the first foreign country.
      (F) nothing resolved -> keep (err toward keep, as today).
    """
    if not location_str or not str(location_str).strip():
        return True, ""                                                      # (A)
    allowed_norm = {_norm_loc(a) for a in allowed_locations if str(a).strip()}
    allowed_codes = set()
    for a in allowed_locations:
        if _norm_loc(a) == "remote":
            continue
        code = _country_code(str(a))
        if code:
            allowed_codes.add(code)
    if "remote" in allowed_norm and _mentions(str(location_str), _REMOTE_HINTS):  # (B)
        return True, "remote"
    # Split on board separators — commas, slashes, ' or '/' OR ' (case-insensitive, so
    # "Hanoi OR Ho Chi Minh City" splits), and a SPACE-padded dash ("London - United
    # Kingdom", en/em too); a bare hyphen ("Winston-Salem") is NOT a separator, so
    # intra-token hyphens survive.
    tokens = [t for t in re.split(r"[,/;|]| or | +[-–—]+ +", str(location_str), flags=re.I)
              if t.strip()]
    if allowed_norm & {_norm_loc(t) for t in tokens}:                        # (C)
        return True, ""
    if "usa" in allowed_norm and any(_is_us_state(t) for t in tokens):       # (D)
        return True, ""
    # (E) resolve EVERY token, not just the last. Keep if any is US or an allowed
    # country; discard only when >=1 resolves and none are allowed.
    resolved = [(t, _token_country(t)) for t in tokens]
    codes = [c for _, c in resolved if c]
    if not codes:
        return True, ""                                                      # (F)
    keep_codes = allowed_codes | {"US"}  # ponytail: US always keep-worthy (US-based operator + postal guard)
    if any(c in keep_codes for c in codes):
        return True, ""
    token, code = next((t, c) for t, c in resolved if c and c not in keep_codes)
    return False, f"on-site in {_country_name(code)}"


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


# --- real adapter (exercised only in Docker; never imported at module load) ---

def make_claude_scorer(api_key: str, model: str, *, profile: str = "",
                       max_tokens: int = 4096):
    """Build a `score_fit(posting, resumes) -> dict` callable backed by Claude.

    `resumes` is the {label: text} dict of resume versions; `profile` (optional,
    run-static) is extra about-the-candidate context. Rubric + profile + all
    resumes are sent as a cached system prefix (byte-identical every call in a
    run) so only the JD is fresh; with >=2 versions the schema also demands an
    enum-constrained `recommended_resume`. `import anthropic` and the client are
    deferred to the FIRST call so importing this module — and building the scorer
    in tests — never needs the SDK. Returns the RAW parsed JSON; score_posting
    normalizes it.
    """
    cell: list = []

    def score_fit(posting: dict, resumes: dict) -> dict:
        if not cell:
            import anthropic  # lazy: only at runtime in Docker
            cell.append(anthropic.Anthropic(api_key=api_key))
        client = cell[0]
        # 0 -> no truncation (Claude has ample context); no Location line (D5 — geography
        # is the screen's job, must not move the fit score).
        job = _job_block(posting, 0, include_location=False)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=_scorer_system_blocks(resumes, profile),
            output_config={"format": {"type": "json_schema",
                                      "schema": _score_schema(list(resumes))}},
            messages=[{"role": "user", "content": job}],
        )
        text = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ScoreError(f"Claude returned non-JSON score: {text!r}") from exc
        if not isinstance(data, dict):
            raise ScoreError(f"Claude score was not a JSON object: {data!r}")
        return data

    return score_fit
