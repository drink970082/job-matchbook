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
# quote-grounded LLM extraction in _check_authorization; this closed list runs after it
# and can only ADD a disqualification, never veto a model pass. Measured recall on its
# own is ~2/11 realistic phrasings, which is why it was demoted. Kept because it costs
# nothing and catches the blunt wordings even on SCREEN_BACKEND=none.
NO_SPONSOR_PHRASES = (
    "will not sponsor", "does not sponsor", "do not sponsor", "cannot sponsor",
    "unable to sponsor", "not able to sponsor", "no visa sponsorship", "no sponsorship",
    "without sponsorship", "not provide sponsorship", "no immigration sponsorship",
    "must be authorized to work without sponsorship",
)

# The EVIDENCE FLOOR for the clearance gate. `requires_clearance` is a bare boolean
# from a 4B model, and acting on it unguarded is the D1 failure class that quote
# grounding closed for `authorization` and never closed here.
#
# MEASURED 2026-07-27 over db/applications.db, not guessed: of 24 clearance discards,
# 20 were WRONG -- every one of them contains "security" (the engineering domain:
# "Senior Security Researcher", "Azure security") and NOT ONE contains a token below.
# The 4 true positives are Microsoft `CTJ - Poly` roles carrying an explicit
# "Other Requirements: Security Clearance Requirements:" block. On that data this set
# separates the two populations perfectly.
#
# This list is the MEASURED one. Widening it re-opens the false-discard direction --
# the expensive one, since a discarded row is reviewed by nobody. In particular: NOT
# bare `sci` (matches "science"/"scientist" -- it is already covered inside `ts/sci`)
# and NOT bare `poly` (matches "polyglot"/"polynomial"). A clearance bar phrased with
# none of these words is a MISS, which costs one paid fit call and reaches the human.
# `\bts` is load-bearing and was missing: with the separator optional, an unanchored
# `ts[.\s/-]?sci` matches ACROSS a word gap, so "supports scientific", "its scientific"
# and "products scientists" all ground a clearance claim — the exact `sci` trap the
# paragraph above says this list avoids. Narrowing is the safe direction: the floor only
# ever gates whether a model's `requires_clearance: true` is honoured, so a token that
# stops matching can only turn a discard into a keep.
CLEARANCE_TOKENS = re.compile(
    r"clearance|top secret|\bsecret\b|\bts[.\s/-]?sci|polygraph", re.IGNORECASE)

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
    # CODE retrieves the sponsorship evidence before the call and hands it to the model
    # to LABEL. The model is never asked to find it — see `_check_authorization`.
    snippets = sponsorship_snippets(description)
    checklist = _candidate_block(candidate, snippets)
    screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    provider_error = False
    if checklist and extract is not None:
        try:
            data = extract(SCREEN_HEADER + checklist + "\n" + job, SCREEN_SCHEMA)
            screen = _screen_verdict(data, candidate or {}, description,
                                     str(posting.get("job_title") or ""), snippets)
        except Exception as exc:  # noqa: BLE001 — err toward KEEP on any provider failure
            print(f"[screen] provider error, keeping posting unscreened: {exc}")
            screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
            provider_error = True

    # Deterministic CODE gates (intern title + location string), hoisted into a
    # shared helper so the fetch-time pre-filter applies the SAME verdict. No LLM.
    # They cost nothing and ran fine even on a provider failure, so their verdict
    # stands either way — a location-disqualified row stays disqualified.
    out = deterministic_screen(screen, posting, candidate)
    # `authorization` must ALWAYS record a verdict when the candidate configured it —
    # even when nothing was retrieved, so no clause was asked and no LLM call was made
    # at all. `merge_fallback_screen` fills only the keys the screen left ABSENT, and a
    # second model vote on a disqualification is precisely what that function is
    # documented not to be (SPEC §7.1): it would double the false-positive surface on
    # the one check where a false positive silently deletes a real job.
    # With no labels this is the closed-list floor, which is deterministic and cannot
    # invent evidence — the same reason the location gate's verdict stands here too.
    #
    # NOT on a provider error, though. The floor is deterministic in the sense that the
    # same JD gives the same answer, but it is BLUNT: a substring scan of the whole
    # description that matches `without sponsorship` inside *"or are eligible to work
    # without sponsorship, we encourage you to apply"* — an invitation. On a working
    # backend the model's labels overrule it; on a dead one nothing does, so an Ollama
    # outage would terminally discard exactly the postings this check was rebuilt to
    # stop discarding. Keeping the key ABSENT here costs nothing: `run_score` leaves a
    # provider_error row `new` instead of fit-scoring it, so `merge_fallback_screen`
    # is never reached and no second model vote can occur — the next pass screens it
    # properly. The docstring's "a failure errs toward KEEP, never toward discard" and
    # SPEC §7.1 both say this out loud.
    if candidate and str(candidate.get("work_authorization") or "").strip() \
            and not provider_error \
            and "authorization" not in out.get("screen", {}):
        passed, note = _check_authorization(candidate.get("work_authorization"),
                                            description, None, snippets)
        out.setdefault("screen", {})["authorization"] = {"pass": passed, "note": note}
        if not passed:
            prior = out.get("disqualification_reason") or ""
            reason = f"authorization: {note}"
            out["disqualified"] = True
            out["disqualification_reason"] = f"{prior}; {reason}" if prior else reason
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


def _screen_verdict(data: dict, candidate: dict, description: str = "",
                    title: str = "", snippets: list[str] | None = None) -> dict:
    """Decide disqualification from the SCREEN call's extracted JOB facts.

    For each configured structured requirement the LLM only EXTRACTED a fact about
    the job; here CODE applies the candidate's constraint (degree rank, sponsorship,
    clearance). This takes the unreliable pass/fail judgment off a 4B model entirely.
    (Location is NOT gated here — it is a deterministic pycountry gate applied
    in `screen_posting`; see `resolve_location`.) A requirement the candidate didn't
    configure is skipped, and a key the model invents (e.g. "skills") is ignored, so a
    skill gap can never disqualify. On missing/garbled extraction each checker errs
    toward PASS (don't discard on absent data).

    `title` joins `description` as the clearance check's EVIDENCE. Both are needed:
    the 2026-07-27 repro matched over both, and the two grounded `degree` discards
    the same query found (Jump Trading, "Campus AI Researcher, PhD/Postdoc") state
    their bar in the TITLE and nowhere else.
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
         and _degree_extracted(entry("degree")),
         *_check_degree(entry("degree"), candidate.get("highest_degree")))
    gate("authorization", bool(str(candidate.get("work_authorization") or "").strip()),
         *_check_authorization(candidate.get("work_authorization"), description,
                               entry("authorization"), snippets))
    gate("clearance", bool(str(candidate.get("security_clearance") or "").strip())
         and isinstance(entry("clearance").get("requires_clearance"), bool),
         *_check_clearance(entry("clearance"), candidate.get("security_clearance"),
                           f"{description}\n{title}"))

    return {
        "screen": clean,
        "disqualified": bool(failures),
        "disqualification_reason": "; ".join(failures),
    }


def _check_degree(entry: dict, cand_degree) -> tuple[bool, str]:
    """Fail only when the role requires a higher degree than the candidate holds.

    The model EXTRACTS which levels the posting names and whether any of them is
    actually required; CODE takes the LOWEST and compares. It used to be handed one
    "minimum" the model had chosen — a judgment, and `make eval-screen` measured the 4B
    getting it wrong on 9 of 38 live discards ("PhD, or Master's degree" and "PhD
    strongly preferred" both read as a hard PhD bar). Picking the smallest number out of
    a list is arithmetic; asking a 4B for it was the mistake.

    Reads BOTH shapes. The fit scorer's Stage 4 block still emits the old single
    `required_degree` and is left alone deliberately (see the SCREEN_SCHEMA comment):
    it runs on a strong model, and editing `score.txt` costs two quota-spending
    `score_eval` runs.
    """
    if "degree_levels" in entry or "degree_required" in entry:
        if not _flag(entry.get("degree_required")):
            return True, ""      # preferred / desirable / equivalence accepted -> no bar
        ranks = [_degree_rank(v) for v in _as_str_list(entry.get("degree_levels"))
                 if _degree_stated(v)]
        if not ranks:
            return True, ""
        req_rank = min(ranks)
    else:                        # legacy single-value shape (the fit scorer's fallback)
        required = entry.get("required_degree")
        if required is None or not str(required).strip():
            return True, ""
        req_rank = _degree_rank(required)
    if req_rank > _degree_rank(cand_degree):
        return False, f"requires {DEGREE_RANK.get(req_rank, 'a higher degree')}"
    return True, ""


def _degree_extracted(entry: dict) -> bool:
    """Did the model actually ANSWER the degree question?

    A blind extraction must record no verdict at all, so `merge_fallback_screen` can
    still see the gap — materializing a pass badge from an extraction that said nothing
    is the original 2026-07-23 defect. `degree_required` must be a real bool (the same
    closed test `clearance` uses); when it says a degree IS required, at least one
    RECOGNIZED level has to come with it, or there is nothing to compare against.
    `degree_required: false` needs no levels — "no degree required" is a real answer.

    Falls back to the legacy single-value test for the fit scorer's Stage 4 shape.
    """
    if "degree_levels" in entry or "degree_required" in entry:
        required = entry.get("degree_required")
        if not isinstance(required, bool):
            return False
        return (not required
                or any(_degree_stated(v) for v in _as_str_list(entry.get("degree_levels"))))
    return _degree_stated(entry.get("required_degree"))


# --- sponsorship: CODE retrieves, the MODEL classifies, CODE decides ------
#
# The inverse of what shipped before 2026-07-28. The model used to do RETRIEVAL (read
# 16K chars, find the sentence, copy it verbatim) and code did CLASSIFICATION (three
# regex vetoes deciding whether that sentence was a refusal). Both halves were on the
# wrong side: retrieval on a keyword is trivially deterministic, and regexes are bad at
# stance. Three rounds of whack-a-mole, PR #22's five false positives, and the screen
# eval's 8-of-16 recall (on rows whose refusal sentence was IN the text handed to the
# model) were all measuring that mismatch.
#
# Hallucination is now structurally impossible rather than checked for: the model
# returns a LABEL over text the code handed it, never text of its own. That is stronger
# than the `_quote_in` verification it replaces, and free rather than a second step.

# Sentence splitting, with an abbreviation guard. PR #22 sprang this trap already: its
# `_norm_sentence` stripped the dot from any single-letter token, merging "must be based
# in the U.S. Citizenship is not required" into a fake citizenship bar.
#
# ponytail: a mask-and-split over a ~20-item list, not nltk/spacy. The ceiling is real —
# an abbreviation not on the list ends a sentence early, and "U.S. Citizenship" stays
# merged — but under this design the splitter only sets the WINDOW. A bad split yields a
# slightly wider snippet, never a wrong verdict, because the classifier reads the text
# either way. Upgrade only if a real posting shows a split changing a LABEL.
_ABBREVS = ("U.S.A.", "U.S.", "U.K.", "Inc.", "Ltd.", "Corp.", "Co.", "Ph.D.", "e.g.",
            "i.e.", "etc.", "Mr.", "Mrs.", "Ms.", "Dr.", "Jr.", "Sr.", "vs.", "No.",
            "St.", "approx.")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# The retrieval vocabulary is `sponsor` ALONE, and that narrowing is measured rather than
# assumed. Every false positive ever recorded on this path came from a word that is not
# "sponsor": `citizen` (EEO boilerplate, "a good citizen in our monorepo", "senior
# citizens"), `visa` (the payment network), `authoriz` (OAuth/RBAC), `right to work`
# ("...in an environment where"). The 72-of-156 authorization discards with no `sponsor`
# token looked like bars this would lose; they are historical damage, all dated before
# the 2026-07-25 relevance gate, and the genuine non-`sponsor` bars among them are
# foreign on-site roles `resolve_location` rejects independently.
_SPONSOR = re.compile(r"sponsor", re.IGNORECASE)


def _sentences(text) -> list[str]:
    """Split `text` into sentences without letting a known abbreviation end one."""
    t = " ".join(str(text or "").split())
    for a in _ABBREVS:                    # mask the dots so they can't end a sentence
        t = t.replace(a, a.replace(".", "\0"))
    return [s.replace("\0", ".") for s in _SENTENCE_END.split(t) if s.strip()]


def sponsorship_snippets(description) -> list[str]:
    """Every sentence naming `sponsor`, plus one neighbour each side.

    The window is +/-1 sentence, NOT the paragraph and not the whole JD. A bare sentence
    loses its antecedent ("Sponsorship is not among them.") while "paragraph" is
    unbounded and degenerates to the whole JD on exactly the postings where scoping would
    have helped. +/-1 is ~400 chars and gives a pronoun its referent.

    ONE SNIPPET PER `sponsor` SENTENCE, and overlapping windows are allowed to repeat a
    shared neighbour. An earlier version merged adjacent hits to avoid the repetition,
    and that was a real defect: the label is about the CENTRE sentence, so merging two
    hits forces the model to answer for both at once. Live rows 465/490 are the proof —
    one IMC paragraph refuses sponsorship for three named nationalities *and* offers it
    to Ukrainian applicants, and merged it could only come back `refuses`, silently
    deleting a posting the candidate can apply to. Per-sentence labels let "any `offers`
    keeps" see the offer. Repeating a neighbour costs a few hundred prompt chars.
    """
    sents = _sentences(description)
    return [" ".join(sents[max(0, i - 1):i + 2])
            for i, s in enumerate(sents) if _SPONSOR.search(s)]


# A snippet that OFFERS sponsorship must never disqualify. DEMOTED 2026-07-28 to a
# keep-direction veto only: it can overturn a model `refuses` label, never produce one.
# Quote grounding fixed invented *text*, never inverted *meaning*, and "Visa sponsorship
# is available" is the most valuable line in a JD for a candidate who needs it.
#
# These patterns are deliberately TIGHT rather than gated by a sentence-wide negation
# search. An earlier version asked "does it look like an offer AND contain no negation
# anywhere?", which fails on the exact shape offers are written in -- "available for
# candidates who do NOT already have the right to work", "sponsorship; NO relocation".
# Negation is evidence of a negation, not of a refusal. Instead each pattern requires the
# affirmative verb to sit directly against the sponsorship word, so "sponsorship is not
# available" and "we are not able to sponsor" simply do not match.
_OFFERS_SPONSORSHIP = re.compile(
    r"sponsor\w*\s+(?:is|are)\s+(?:available|offered|provided|possible)"
    r"|sponsorship available"
    r"|\b(?:we|they)\s+(?:can|will|do|are happy to|are willing to|are able to|"
    r"are pleased to)\s+sponsor"
    r"|\b(?:offers?|offering|provides?|providing)\s+(?:full\s+|uk\s+|us\s+)?"
    r"(?:visa\s+|immigration\s+)?sponsorship"
    r"|open to sponsor|eligible for sponsorship|will consider sponsor|\bwe sponsor\b",
    re.IGNORECASE)

_NEGATION = re.compile(r"\b(?:not|never|cannot|can't|won't|unable|no)\b|n't", re.IGNORECASE)

# A soft PREFERENCE is not a bar: the candidate can still apply, so discarding on one is
# a lost opportunity. RESTORED 2026-07-28 as a keep-direction veto after the inversion
# measured worse without it — the design note predicted all three regex vetoes would
# become unnecessary once a classifier read the sentence, and for the off-topic and
# wrong-polarity shapes that held, but not for this one. `make eval-screen` caught the
# 4B labelling "Our Company will be prioritizing applicants who have a current right to
# work in Singapore, and do not require sponsorship of a visa" as `refuses` on 3 live
# TikTok rows, all three draws. Like `_OFFERS_SPONSORSHIP` it can only overturn a
# refusal, never produce one. Scoped to the sponsorship clause rather than the whole
# sentence, so a hard bar that happens to list a "plus" elsewhere still disqualifies.
_PREFERENCE_ONLY = re.compile(
    r"(?:prioritiz\w*|prefer\w*|ideally)[^.]{0,80}"
    r"(?:sponsor|visa|right to work|work authoriz|work authoris)",
    re.IGNORECASE)

_SPONSORSHIP_LABELS = ("refuses", "offers", "neither")


def _not_really_a_refusal(text: str) -> bool:
    """Keep-direction vetoes over a snippet the model labelled `refuses`.

    Both can only overturn a refusal, never create one, so a wrong veto costs one paid
    fit call while the error it prevents silently deletes a job.
    """
    return _offers_sponsorship(text) or bool(_PREFERENCE_ONLY.search(text))


def _offers_sponsorship(text: str) -> bool:
    """Does this snippet affirmatively OFFER sponsorship?

    A negation IMMEDIATELY before the offer verb makes it a refusal ("we do not PROVIDE
    immigration sponsorship"). Scoped to the 14 chars before the match, not to the
    sentence: offers routinely carry a negation elsewhere ("available for candidates who
    do not already have the right to work"). Negation is evidence of a negation, not of
    a refusal.
    """
    offer = _OFFERS_SPONSORSHIP.search(text)
    if not offer:
        return False
    return not _NEGATION.search(text[max(0, offer.start() - 14):offer.start()])


def _check_authorization(cand_auth, description: str = "",
                         entry: dict | None = None,
                         snippets: list[str] | None = None) -> tuple[bool, str]:
    """Fail only when the candidate needs sponsorship AND the JD refuses it.

    RETRIEVE-THEN-CLASSIFY (2026-07-28). CODE retrieved the `sponsor` sentences
    (`sponsorship_snippets`) and put them in the prompt; the model returned one label per
    snippet; CODE decides here. Any `offers` KEEPS — an offer anywhere outranks a refusal,
    because the two only co-occur when the posting is describing who it can sponsor.
    Otherwise any `refuses` discards. Silence keeps.

    **Hallucination is structurally impossible, not verified against.** The model labels
    text the code handed it; it never supplies text. That retires `_quote_in` rather than
    strengthening it, and `_OFF_TOPIC_QUOTE` with it — an EEO line is simply `neither` to
    a classifier, so no pattern has to anticipate every innocent sentence in English.

    Two regex vetoes survive, both DEMOTED to keep-direction only (`_not_really_a_refusal`):
    a `refuses` label on a snippet that plainly OFFERS, or that is only a PREFERENCE, is
    overruled. Neither can create a disqualification. The design note expected all three
    old vetoes to become unnecessary once a classifier read the sentence; `_OFF_TOPIC_QUOTE`
    did, and these two did not — measured, not assumed.

    Every uncertainty resolves toward KEEP, because a discarded row is reviewed by nobody
    while a miss costs one paid fit call and reaches the human: a label count that does
    not match the snippet count means the model answered a different question, so the
    check is dropped.

    Floor: `NO_SPONSOR_PHRASES` runs only when the model returned NO labels at all —
    `SCREEN_BACKEND=none`, a provider error, or the fit scorer's Stage 4 shape. Silence
    and a miscounted answer are deliberately NOT the same thing: a model that returned
    labels answered the question, and letting a bad *count* fall through to a blunt
    substring scan of the whole description is where BOTH long-standing IMC false
    positives came from (`without sponsorship` matching inside *"or are eligible to work
    without sponsorship, we encourage you to apply"* — an invitation). The floor can only
    ever ADD a disqualification, never veto a model pass.
    """
    if not _needs_sponsorship(cand_auth):
        return True, ""
    snippets = list(snippets or [])
    raw = (entry or {}).get("sponsorship_labels")
    labels = [str(v).strip().lower() for v in _as_str_list(raw)]
    # "The model answered" is NOT the same as "labels is non-empty". `sponsorship_labels`
    # is `["array", "null"]` in SCREEN_SCHEMA, so `[]` is a legal answer and a very
    # plausible 4B one ("none of these are about sponsorship") — and it is a COUNT
    # MISMATCH whenever a snippet was retrieved, not silence. Reading it as silence sent
    # it to the floor, which is the one path the whole retrieve-then-classify design
    # exists to close.
    answered = bool(labels) or isinstance(raw, list)
    if labels and len(labels) == len(snippets) and all(
            v in _SPONSORSHIP_LABELS for v in labels):
        pairs = list(zip(labels, snippets))
        if any(v == "offers" for v, _ in pairs):
            return True, ""
        refusals = [s for v, s in pairs if v == "refuses"]
        if refusals and not all(_not_really_a_refusal(s.lower()) for s in refusals):
            return False, "no visa sponsorship offered"
        return True, ""
    if answered and snippets:
        # The model DID answer, just not in a usable shape (wrong count, off-vocabulary,
        # or an empty array against a non-empty snippet list). That is not the same as
        # silence, and it must not fall through to the floor: both long-standing IMC
        # false positives came from exactly this path, where a miscounted answer let the
        # closed list scan the whole description and match "without sponsorship" inside
        # an invitation to apply.
        # `and snippets` is load-bearing: with NOTHING retrieved there is no question to
        # have answered, so `[]` is the correct empty answer and the floor is the whole
        # verdict — that is the documented silence path, not a bad count.
        return True, ""
    # NOTE, and it is an OPEN DESIGN FORK rather than an oversight (PROGRESS, SCREEN):
    # a live-but-blind response — `sponsorship_labels: null`, the key missing, or no
    # `screen` object at all — reaches this floor and can discard, and it is NOT flagged
    # `provider_error`. Four tests pin that on purpose: the floor is meant to be an
    # INDEPENDENT deterministic signal, like the location gate, so a JD that literally
    # says "we do not sponsor work visas" is still caught with no model data. The
    # counter-argument is that a blind backend then discards on a substring the model
    # never condemned, and scores as a circuit-breaker success while doing it. Deciding
    # it is the operator's call, not this function's.
    text = " ".join((description or "").lower().split())
    if any(phrase in text for phrase in NO_SPONSOR_PHRASES):
        return False, "no visa sponsorship offered"
    return True, ""


def _check_clearance(entry: dict, cand_clearance, evidence: str = "") -> tuple[bool, str]:
    """Fail only when the candidate has no clearance, the role requires one, AND the
    JD text actually says so.

    `evidence` is the JD description plus the job title, and the `CLEARANCE_TOKENS`
    check over it is the EVIDENCE FLOOR: a bare `requires_clearance: true` with no
    clearance word anywhere in the posting is the model conflating the engineering
    domain ("security") with the government credential, measured at 20 of 24 live
    discards. Defaults to `""` so an un-threaded caller KEEPS rather than discards --
    this guard can only turn a discard into a keep, never the reverse.
    """
    if _norm_simple(cand_clearance) not in ("", "none"):
        return True, ""  # candidate holds a clearance -> assume sufficient
    if _flag(entry.get("requires_clearance")) and CLEARANCE_TOKENS.search(evidence or ""):
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


# The two checks a local 4B is measurably unreliable on, and the ONLY two that may be
# routed to the strong model instead of terminally discarding. Both are semantic reads of
# prose the model has to interpret. Everything else that can disqualify is deterministic
# CODE — the location gazetteer, the intern/co-op title regex, the sponsorship phrase
# floor — where re-litigating the verdict on a paid call buys nothing, because no model
# produced it in the first place.
_CONFIRMABLE_CHECKS = frozenset({"degree", "clearance"})


def demote_for_confirmation(screen: dict) -> dict | None:
    """Turn a degree/clearance-ONLY disqualification into a keep that carries a
    `needs_confirmation` marker, or return None to leave the discard alone.

    The measured problem: the 4B's false-discard rate is **83% for clearance** and
    **24% for degree**, and a discarded posting is reviewed by nobody, so a wrong verdict
    silently deletes a real job. Volume is small — degree/clearance-only discards were 30
    of 3,262 — so each one buys a single paid fit call instead (docs/PROGRESS.md item 3).

    The failing verdicts are **removed** rather than flipped to pass. That is what makes
    this a re-check and not an override: `merge_fallback_screen` fills only the checks the
    screen left ABSENT, so clearing them is exactly how the fit scorer's own Stage 4
    extraction gets to answer, with the same CODE arbitration applying the candidate's
    constraint. Flipping them to `pass` would materialize a verdict nothing produced —
    the 2026-07-23 blind-check-as-pass defect, in a new place.

    Returns None (leave it discarded) when any failing check is outside
    `_CONFIRMABLE_CHECKS`, and when the verdict carries no per-check entries at all: an
    unreadable disqualification shape is not evidence that the disqualification is wrong,
    and routing it would mean paying for every discard whose shape we cannot classify.
    """
    checks = screen.get("screen")
    if not isinstance(checks, dict):
        return None
    failed = [k for k, v in checks.items()
              if isinstance(v, dict) and not v.get("pass")]
    if not failed or not _CONFIRMABLE_CHECKS.issuperset(failed):
        return None
    return {
        "screen": {k: v for k, v in checks.items() if k not in failed},
        "disqualified": False,
        "disqualification_reason": "",
        "needs_confirmation": sorted(failed),
    }


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
                              str(posting.get("description") or ""),
                              str(posting.get("job_title") or ""))
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
