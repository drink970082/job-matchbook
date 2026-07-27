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

The SCREEN call is injected as `extract(prompt, schema) -> dict` (see
`screen_posting`'s docstring) — the ENTIRE backend contract, so a non-Ollama
backend is a new callable, not a new branch here. `make_ollama_extract` builds the
default one; `http` is injected into IT (defaults to `None`; the real `requests`
module is bound only in run.py) so tests exercise the SCREEN call's parsing with a
fake transport and zero network. Ollama wraps output in
{"response": "<json string>"} under format=json; `_post` parses that inner string
defensively and raises ScoreError on anything unusable, which `screen_posting`
catches (errs toward keep) rather than letting it abort the batch.
"""
from __future__ import annotations

import json
import re

from ats_worker.prompts import SCREEN_HEADER

from .errors import ScoreError
from .location import resolve_location
from .prompts import SCREEN_SCHEMA, _candidate_block, _job_block

# How each configured hard requirement is screened. For the structured fields the
# LLM only EXTRACTS a fact about the JOB and CODE applies the candidate's
# constraint (a 4B model is unreliable at the pass/fail judgment itself — it
# mismatches degrees, can't tell a US city is "in" the USA). A skill the model
# invents as a key is ignored, so a skill gap can never disqualify.
DEGREE_RANK = {0: "none", 1: "high school", 2: "associate", 3: "bachelor's",
               4: "master's", 5: "phd"}

# The FLOOR for the sponsorship gate, not the gate itself. The primary check is the
# quote-grounded LLM extraction in _check_authorization; this closed list runs ONLY when
# the model produced no quote at all, and can only ADD a disqualification. Measured recall
# on its own is ~2/11 realistic phrasings, which is why it was demoted. Kept because it
# costs nothing and catches the blunt wordings when there is no model verdict to trust.
# It matches a substring ANYWHERE in the description with no sentence boundary, so it is
# scoped to the no-quote case AND demoted to a locator: the sentence it finds must clear
# _quote_states_refusal before it can disqualify. Both guards are load-bearing -- "eligible
# to work without sponsorship, we encourage you to apply" is an invitation, and the model
# produced no quote on it, so scoping alone still fired (IMC ids 465/490).
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


def deterministic_screen(screen: dict, posting: dict, candidate: dict | None) -> dict:
    """Apply the two CODE-only screen gates — intern/co-op title, and location string
    (resolve_location off posting['location']) — merging their verdicts into `screen`
    in place. Shared by screen_posting (after the LLM screen, preserving prior
    degree/auth/clearance reasons) and the fetch-time gate (fresh empty screen). No
    LLM. Returns `screen`."""
    if candidate and candidate.get("exclude_internships") and _is_internship(
        str(posting.get("job_title") or "")
    ):
        screen.setdefault("screen", {})["internships"] = {"pass": False, "note": "internship/co-op role"}
        prior = screen.get("disqualification_reason") or ""
        screen["disqualified"] = True
        screen["disqualification_reason"] = (
            f"{prior}; internship/co-op role" if prior else "internship/co-op role"
        )
    if candidate and candidate.get("locations"):
        passed, note = resolve_location(posting.get("location"), candidate["locations"])
        screen.setdefault("screen", {})["location"] = {"pass": passed, "note": note}
        if not passed:
            prior = screen.get("disqualification_reason") or ""
            reason = f"location: {note}" if note else "location"
            screen["disqualified"] = True
            screen["disqualification_reason"] = f"{prior}; {reason}" if prior else reason
    return screen


def screen_posting(posting: dict, *, extract=None, candidate: dict | None = None,
                   num_ctx: int = 8192) -> dict:
    """Screen `posting` against the candidate's hard requirements — the CHEAP half of
    scoring (no résumé, no paid fit call). Combines three signals into one verdict:

      1. The LLM extraction call (`extract`) reports structured JOB facts (required
         degree, sponsorship, clearance) for whatever the candidate configured; CODE
         (`_screen_verdict`) applies the candidate's constraint. Skipped entirely when
         no candidate constraints are configured OR when `extract` is None
         (SCREEN_BACKEND=none). A failure errs toward KEEP, never toward discard.
      2. A deterministic intern/co-op title check, gated by `exclude_internships`.
      3. A deterministic pycountry LOCATION gate (`resolve_location`), gated by
         `candidate["locations"]`, matched against the board's location string.

    `extract(prompt, schema) -> dict` is the ENTIRE backend contract — the one step
    that differs between ollama / codex / claude / openai / none. Build it with
    `make_ollama_extract` or `score.backends_screen.make_extract`; run.py wires it.

    Returns `{"screen": {...}, "disqualified": bool, "disqualification_reason": str}`.
    Takes no fit-scorer callable — it structurally cannot pay for the fit call.
    """
    job = _job_block(posting, num_ctx * 2)
    description = str(posting.get("description") or "")
    checklist = _candidate_block(candidate)
    screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    provider_error = False
    if checklist and extract is not None:
        try:
            data = extract(SCREEN_HEADER + checklist + "\n" + job, SCREEN_SCHEMA)
            screen = _screen_verdict(data, candidate or {}, description)
        except Exception as exc:  # noqa: BLE001 — err toward KEEP on any provider failure
            print(f"[screen] provider error, keeping posting unscreened: {exc}")
            screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
            provider_error = True

    # Deterministic CODE gates (intern title + location string), hoisted into a
    # shared helper so the fetch-time pre-filter applies the SAME verdict. No LLM.
    # They cost nothing and ran fine even on a provider failure, so their verdict
    # stands either way — a location-disqualified row stays disqualified.
    out = deterministic_screen(screen, posting, candidate)
    # Record that this posting was never actually screened. Keeping it is still the
    # right per-item call (one flaky provider must not discard the queue), but the
    # CALLER needs to tell "screened and clean" from "never screened" — paying the fit
    # backend for the latter is not keeping it, it is buying an unscreened verdict.
    # run_score reads this both to skip the paid call and to detect a dead provider.
    if provider_error:
        out["provider_error"] = True
    return out


def make_ollama_extract(*, http, ollama_host: str, model: str | None = None,
                        temperature: float = 0.0, seed: int = 0,
                        num_ctx: int = 8192, timeout: int = 180):
    """Build the `extract(prompt, schema) -> dict` callable for the local Ollama
    screen — the default backend, and the only free one.

    `schema` is accepted and ignored: this call uses Ollama's `format="json"` mode,
    which constrains output to *some* JSON object rather than to a schema. Keeping
    the parameter means every backend has one signature; the schema-enforcing
    backends use it. Behavior is byte-identical to the pre-seam call.
    """
    options = {
        "temperature": temperature,
        "seed": seed,
        "num_ctx": num_ctx,
        # Cap generation: the JSON answers are small, so this only bounds a
        # runaway (which otherwise stalls a call past the read timeout).
        "num_predict": 512,
    }

    def extract(prompt: str, schema: dict) -> dict:
        return _post(http, ollama_host, model, prompt, options=options, timeout=timeout)

    return extract


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


def _degree_stated(value) -> bool:
    """Did the model actually name a degree? Enumerates the DATA values, not the
    no-data ones.

    An earlier version listed the "I don't know" spellings ("unknown", "n/a", ...) and
    treated everything else as data. That set can never be closed -- `_degree_rank`
    returns 0 for ANY unrecognized string, so "not stated" / "unclear" / "TBD" / "N.A."
    were all `said_something=True` AND rank 0, materializing a pass badge from an
    extraction that said nothing and retiring the Stage 4 fallback exactly as the
    original defect did. The recognized-degree set IS closed (it is the enum
    `screen.txt` gives the model), so testing membership in that is the only form of
    this check that cannot rot.

    Note `none` counts as DATA: `screen.txt`'s degree clause says "Use 'none' if no
    specific degree is required", so it is a real answer, not a shrug.
    """
    if value is None:
        return False  # `_norm_simple(None)` is the STRING "none" — a real answer here
    t = _norm_simple(value)
    if not t:
        return False
    return (t == "none" or "no degree" in t
            or any(k in t for k in ("phd", "ph d", "doctora", "master", "bachelor",
                                    "associate", "high school", "diploma", "ged")))


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

    # degree/clearance are gated on the model ACTUALLY returning a VALUE, not just on
    # the candidate configuring the check. Both err toward pass on absent data, so
    # materializing the key anyway makes a ran-but-blind check byte-identical to a
    # genuinely-passed one — and `merge_fallback_screen` can then never see the gap.
    # The test is the value, not the entry dict: under a strict schema the model must
    # emit every key, so `{"required_degree": null}` is a non-empty dict that says
    # NOTHING. Reading the dict's truthiness here would silently retire the Stage 4
    # fallback the moment the schema became strict.
    # `authorization` deliberately still writes its key on an empty entry: it has an
    # independent signal (NO_SPONSOR_PHRASES over the JD) and produces a real verdict
    # with no model data at all.
    gate("degree", bool(str(candidate.get("highest_degree") or "").strip())
         and _degree_stated(entry("degree").get("required_degree")),
         *_check_degree(entry("degree"), candidate.get("highest_degree")))
    gate("authorization", bool(str(candidate.get("work_authorization") or "").strip()),
         *_check_authorization(candidate.get("work_authorization"), description,
                               entry("authorization")))
    gate("clearance", bool(str(candidate.get("security_clearance") or "").strip())
         and isinstance(entry("clearance").get("requires_clearance"), bool),
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


# POSITIVE EVIDENCE of an employer refusal or a hard authorization bar. The gate fires
# ONLY on a match here; ANY unmatched sentence keeps the posting.
#
# Inverted 2026-07-26 from the veto design (fire on any authorization word, then subtract
# off-topic / wrong-polarity / soft-preference sentences). That direction asked the author
# to anticipate every innocent English sentence containing "sponsor", "visa", "citizen" or
# "authoriz": three review rounds each turned up a category nobody had anticipated, and one
# shipped version disqualified "We offer generous personal time off". Under positive
# evidence an incomplete list yields a MISS -- one paid fit call, and the human still reads
# the JD -- instead of a wrong DISCARD, which nobody reviews. PRINCIPLES' four-way table
# calls this candidate-opportunity uncertainty: keep.
#
# Same standing rule as the vocabulary it replaces: add a pattern only together with a
# must_flag sentence in tests/fixtures/sponsorship_quotes.json that needs it, and only if
# must_keep still passes.
_SPONSORSHIP_BAR = re.compile(
    # 1. the employer refuses to sponsor: a negated auxiliary directly against "sponsor".
    #    "do not" must sit against the VERB, so "do not require sponsorship of a visa"
    #    (a TikTok invitation) does not match.
    r"\b(?:do|does|will|would|can|could|are|is|am)\s+not\s+"
    r"(?:currently\s+|presently\s+|at (?:this|the) time\s+|able to\s+|be able to\s+|"
    r"in a position to\s+)?sponsor"
    r"|\b(?:cannot|can not|can't|won't|unable to|not able to|not in a position to|"
    r"no longer)\s+(?:currently\s+)?sponsor"
    # 2. ... or refuses a sponsorship-shaped OBJECT ("we do not provide immigration
    #    sponsorship", "we cannot accept visa holders"). Short verb list, object within
    #    30 chars of it.
    r"|\b(?:(?:do|does|will|would|can|could|are|is)\s+not|cannot|can not|can't|won't|"
    r"unable to|not able to)\s+(?:currently\s+|be able to\s+|able to\s+)?"
    r"(?:provide|offer|accept|grant|extend|arrange|assist with)\w*[^.]{0,30}"
    r"(?:visa|sponsorship|immigration|work permit|h-?1b|employment authoriz\w*)"
    # 3. sponsorship stated as unavailable, in either word order
    r"|sponsor\w*\s+(?:is|are)\s+not\s+(?:currently\s+)?"
    r"(?:available|offered|provided|possible|an option|supported)"
    r"|\bno\s+(?:visa\s+|immigration\s+|work\s+)?sponsorship\b"
    # 4. a hard bar on the candidate's side. "must" is required: without it "the right to
    #    work in the UK" appears in offers just as often as in bars.
    r"|\bmust\s+(?:be|hold|have|possess|maintain)\b[^.]{0,60}"
    r"(?:citizen|permanent residen|green card|full working rights|working rights|"
    r"unrestricted[^.]{0,20}authoriz|unrestricted[^.]{0,20}authoris|"
    # "must be authorized to work without sponsorship" is a bar; "are eligible to work
    # without sponsorship, we encourage you to apply" is an invitation. Only "must"
    # separates them, which is why this object lives here and not in its own clause.
    r"without\s+(?:visa\s+|immigration\s+)?sponsorship)"
    # 5. ... including the two citizenship-bar wordings that never say "must"
    r"|citizenship\s+(?:is|are|will be)\s+(?:a\s+)?(?:strict\s+)?"
    r"(?:required|requirement|mandatory)"
    r"|requir\w*[^.]{0,60}\bbe\s+(?:an?\s+)?(?:[a-z.]+\s+)?citizen",
    re.IGNORECASE)


def _quote_states_refusal(quote) -> bool:
    """Does `quote` carry POSITIVE evidence that this employer will not sponsor, or bars
    candidates who need sponsorship? Anything unmatched KEEPS the posting.

    Guards the direction that costs the most: a false positive DISQUALIFIES a good posting
    silently -- the error 'err toward keep' exists to avoid (PRINCIPLES) -- while a miss
    costs one paid fit call and still reaches the human, who reads the JD. So the check is
    a closed list of refusal shapes rather than a broad trigger with exceptions carved out.

    Pinned by tests/fixtures/sponsorship_quotes.json -- change nothing here without
    running that corpus in both directions.
    """
    text = _norm_sentence(quote)
    return bool(text) and bool(_SPONSORSHIP_BAR.search(text))


def _norm_sentence(text) -> str:
    """Lowercase, collapse whitespace, and drop the dots of single-letter abbreviations
    ("u.s." -> "us").

    Every `_SPONSORSHIP_BAR` pattern scopes itself with `[^.]`, which a mid-sentence
    "U.S." otherwise cuts in half ("Applicants must hold U.S. Permanent Residency").
    Only single-letter tokens lose their dot, so real sentence ends still bound the
    patterns. `_sentence_with` splits on the same dots, so it must normalize identically
    or the floor hands the bar a fragment: "must be legally authorized to work in the
    U.S. without sponsorship." truncates to "without sponsorship.", which states no
    refusal, and 65 real bars across PayPal and eBay would be kept.
    """
    return re.sub(r"\b([a-z])\.", r"\1", " ".join(str(text or "").lower().split()))


def _quote_in(quote, description: str) -> bool:
    """Is `quote` actually present in the JD? Whitespace-collapsed and case-insensitive,
    matching the normalization the phrase floor already uses — that tolerates the ways a
    FAITHFUL quote legitimately differs (line wraps, casing) without tolerating invented
    text. This is what makes hallucination unable to disqualify."""
    needle = " ".join(str(quote or "").lower().split())
    if not needle:
        return False
    return needle in " ".join((description or "").lower().split())


def _check_authorization(cand_auth, description: str = "",
                         entry: dict | None = None) -> tuple[bool, str]:
    """Fail only when the candidate needs sponsorship AND the JD says it isn't offered.

    Primary check: the model returns `no_sponsorship_quote`, the verbatim JD sentence
    saying so, and CODE verifies that sentence actually appears in the description
    before acting on it. A hallucinated quote fails verification and the posting is
    KEPT — hallucination cannot disqualify anything by construction, not by trust.
    This holds on qwen3.5:4b too, so D1 needs no re-litigating.

    Second gate: the quote must state a REFUSAL (`_quote_states_refusal`). Presence
    proves the sentence is real, not that it bars this candidate — the 2026-07-25 labeled
    set caught the model quoting real-but-irrelevant agency boilerplate on 5 of 28 fires.

    Floor: NO_SPONSOR_PHRASES runs only when the model produced NO quote at all — a
    substring match with no sentence boundary is not a second opinion on a model that
    did look and quoted something else. The phrase is only a cheap way to FIND a
    candidate sentence; the sentence itself must then clear `_quote_states_refusal`,
    the same bar the model's own quote clears. That is what stops the floor from
    disqualifying on an invitation ("or are eligible to work without sponsorship, we
    encourage you to apply" — IMC ids 465/490, where the model produced no quote, so
    scoping alone left the floor firing on them). Its note carries the matched
    sentence, so a floor disqualification is inspectable rather than a bare verdict.
    """
    if not _needs_sponsorship(cand_auth):
        return True, ""
    quote = (entry or {}).get("no_sponsorship_quote")
    if _quote_in(quote, description) and _quote_states_refusal(quote):
        return False, "no visa sponsorship offered"
    if str(quote or "").strip():
        return True, ""  # the model looked and quoted; an ungrounded quote still keeps
    text = _norm_sentence(description)
    for phrase in NO_SPONSOR_PHRASES:
        if phrase not in text:
            continue
        sentence = _sentence_with(text, phrase)
        if _quote_states_refusal(sentence):
            return False, f'no visa sponsorship offered: "{sentence}"'
    return True, ""


def _sentence_with(text: str, phrase: str, cap: int = 200) -> str:
    """The sentence of `text` (normalized by `_norm_sentence`) holding `phrase`, capped at
    `cap` chars — what makes a phrase-floor disqualification reviewable by a human, and
    what the floor hands `_quote_states_refusal`.

    The excerpt WINDOWS around the phrase rather than truncating from the sentence start.
    JDs arrive with bullet lists flattened and no periods, so the "sentence" holding the
    phrase is routinely longer than the cap; truncating from the start then drops the very
    phrase the excerpt was built around, the refusal test runs on text that cannot match,
    and a real bar is kept. Measured on the live corpus: 4 genuine refusals (Optiver 692
    "we will not sponsor individuals for employment authorization", Microsoft 1716,
    eBay 9909, Workday 9936) were kept that way.
    """
    i = text.find(phrase)
    start = text.rfind(".", 0, i) + 1
    end = text.find(".", i + len(phrase))
    sentence = text[start:len(text) if end == -1 else end + 1].strip()
    if len(sentence) <= cap:
        return sentence
    j = max(0, sentence.find(phrase) - cap // 2)
    return sentence[j:j + cap].strip()


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


def merge_fallback_screen(screen: dict, card: dict, posting: dict,
                          candidate: dict | None) -> dict:
    """Consume the fit scorer's secondary hard-requirement extraction — but ONLY for
    checks the screen produced no verdict for.

    Why fallback and not a second vote: on a working screen backend a second independent
    checker doubles the false-positive surface, and a spurious "requires PhD" would
    SILENTLY DISCARD a good posting — the exact failure the err-toward-keep design
    exists to avoid. This is insurance for the gap (SCREEN_BACKEND=none, or a screen
    failure that err-toward-keep already swallowed), not redundancy.

    Sponsorship keeps the same quote verification as the screen, so a hallucinated
    quote cannot disqualify here either.

    A screen that already disqualified has nothing left to gap-fill, so it is
    returned untouched.
    """
    if not candidate or not isinstance(card, dict):
        return screen
    if screen.get("disqualified"):
        return screen
    extracted = card.get("screen")
    if not isinstance(extracted, dict):
        return screen
    already = screen.get("screen") or {}
    gaps = {k: v for k, v in extracted.items() if k not in already}
    if not gaps:
        return screen
    verdict = _screen_verdict({"screen": gaps}, candidate,
                              str(posting.get("description") or ""))
    merged = dict(already)
    merged.update({k: v for k, v in (verdict.get("screen") or {}).items() if k in gaps})
    prior = screen.get("disqualification_reason") or ""
    extra = verdict.get("disqualification_reason") or ""
    reason = "; ".join(r for r in (prior, extra) if r)
    return {
        "screen": merged,
        "disqualified": bool(screen.get("disqualified")) or bool(verdict.get("disqualified")),
        "disqualification_reason": reason,
    }


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
