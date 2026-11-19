"""Hard-requirements screen: extraction seam, code-decided verdicts, sponsorship
retrieval, location. No real network (injected http)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock
import pytest
import requests
from ats_worker.screening import engine as screen_engine
from ats_worker.screening import prompts as screen_prompts
from ats_worker import screening
from ats_worker.screening.errors import ModelResponseError


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeHttp:
    """Records each POST and returns canned Ollama envelopes, in order.

    screen_posting makes at most ONE Ollama call per posting: SCREEN (only
    when a candidate is configured) — the fit SCORE is a separate concern,
    scored by an injected backend adapter and normalized by
    `score._normalize_score`, never exercised via this fake. Pass one
    response (reused for every call) or several if a test drives more than
    one call.
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return FakeResponse({"response": self._responses[idx]})


def _ollama(http, **kw):
    """Build the Ollama extract for tests that assert on the HTTP request shape."""
    kw.setdefault("ollama_host", "h")
    kw.setdefault("model", "m")
    return screening.make_ollama_extract(http=http, **kw)


POSTING = {
    "job_title": "Senior Python Engineer",
    "company_name": "Acme",
    "description": "We need Python, Django, and AWS experience.",
}


# A posting whose JD ACTUALLY states a clearance bar. `_check_clearance` needs one:
# a bare `requires_clearance: true` over a JD with no clearance word is the 2026-07-27
# defect (20 of 24 live discards), and the floor now keeps such a posting. The wording
# is the real Microsoft `CTJ - Poly` shape the 4 true positives all carried.
CLEARED_POSTING = {
    **POSTING,
    "description": ("We need Python, Django, and AWS experience. Other Requirements: "
                    "Security Clearance Requirements: an active TS/SCI clearance."),
}


RESUME = "Experienced Python and Django developer."


def test_screen_posting_disqualifies_without_calling_fit():
    # screen_posting is the standalone SCREEN half: no score_fit parameter exists on
    # it at all, so it structurally cannot pay for a fit call — pipeline.run_score is
    # what gates on `disqualified` before ever calling the injected fit_fn.
    http = FakeHttp(json.dumps({"screen": {"clearance": {"requires_clearance": True}}}))
    out = screen_engine.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "none"}, num_ctx=8192)
    assert out["disqualified"] is True
    assert "screen" in out
    assert out["disqualification_reason"] == "clearance: requires security clearance"


def test_screen_parse_failure_falls_back_to_scored_not_screened():
    # A garbled SCREEN response must NOT discard the posting: the design errs toward
    # keep on garbled extraction — not disqualified, and the screen verdict is empty.
    http = FakeHttp("this is not json {{{")
    out = screen_engine.screen_posting(
        POSTING, extract=_ollama(http),
        candidate={"highest_degree": "Master's"},
    )
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert out["screen"] == {}
    assert len(http.calls) == 1                    # the (failed) SCREEN call


def test_screen_posting_uses_injected_extract():
    # The screen's only backend-specific step is "give me JSON from this prompt".
    seen = {}

    def extract(prompt, schema):
        seen["prompt"] = prompt
        return {"screen": {"clearance": {"requires_clearance": True}}}

    out = screen_engine.screen_posting(CLEARED_POSTING, extract=extract,
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "clearance: requires security clearance"
    assert "=== JOB:" in seen["prompt"]


def test_screen_posting_without_extract_runs_deterministic_gates_only():
    # SCREEN_BACKEND=none: no LLM call, but the intern/location gates still fire.
    posting = dict(POSTING, job_title="Software Engineering Intern")
    out = screen_engine.screen_posting(posting, extract=None,
                               candidate={"exclude_internships": True,
                                          "security_clearance": "none"})
    assert out["disqualified"] is True
    assert "internship" in out["disqualification_reason"]


def test_extract_failure_errs_toward_keep():
    # A broken provider must NEVER discard the queue.
    def extract(prompt, schema):
        raise ModelResponseError("provider down")

    out = screen_engine.screen_posting(POSTING, extract=extract,
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert out["screen"] == {}


def test_extract_failure_is_flagged_provider_error():
    # Keeping the posting is right for ONE flaky call; it is wrong to then pay to
    # fit-score it as though it had been screened. The verdict carries the fact, so
    # the caller can tell "screened and clean" from "never actually screened".
    def extract(prompt, schema):
        raise ModelResponseError("provider down")

    out = screen_engine.screen_posting(POSTING, extract=extract,
                               candidate={"highest_degree": "Master's"})
    assert out["provider_error"] is True


def test_working_extract_sets_no_provider_error():
    out = screen_engine.screen_posting(POSTING, extract=lambda p, s: {"screen": {}},
                               candidate={"highest_degree": "Master's"})
    assert "provider_error" not in out


@pytest.mark.parametrize("blind", [
    {"nonsense": 1},                    # valid JSON, no verdict anywhere
    {"screen": "pass"},                 # `screen` present but not an object
    {"screen": None},                   # the schema-legal way to say nothing
    ["screen"],                         # not even a dict
    "screen",
])
def test_a_blind_response_is_a_provider_error_not_a_verdict(blind):
    # A backend that answers with no usable verdict looks HEALTHY: degree and clearance
    # suppress themselves on absent data, so the sponsorship phrase floor is the only
    # surviving check and it discards on a substring the model never condemned — while
    # the breaker records a success, so the degraded mode never trips it and walks the
    # whole backlog. Realistic trigger is a wrong `--model` tag or a non-instruct model.
    jd = ("If you are eligible to work without sponsorship, we encourage you to apply. "
          "We build low-latency trading systems.")
    out = screen_engine.screen_posting({**POSTING, "description": jd},
                               extract=lambda p, s: blind,
                               candidate={"work_authorization": "requires H-1B sponsorship"})
    assert out["provider_error"] is True
    assert out["disqualified"] is False
    assert "authorization" not in out["screen"]


def test_the_flat_shape_is_a_verdict_and_is_honoured():
    # OBSERVED, not hypothetical: `make eval-screen` hit this on a live qwen3.5:4b run
    # (2026-07-29), roughly 1 call in 100 -- the model drops the `screen` wrapper and
    # returns the requirement keys at the top level, carrying a COMPLETE and correct
    # verdict. Reading it as silence threw that verdict away, and once a blind response
    # became a provider_error it aborted the eval outright on the first occurrence.
    # A SOLE PhD bar, because `degree_levels` takes min(rank): the response actually seen
    # was `["phd", "master's"]`, which correctly does NOT bar a Master's candidate.
    flat = {"degree": {"degree_levels": ["phd"], "degree_required": True},
            "clearance": {"requires_clearance": False}}
    out = screen_engine.screen_posting(POSTING, extract=lambda p, s: flat,
                               candidate={"highest_degree": "Master's",
                                          "security_clearance": "none"})
    assert "provider_error" not in out
    # The verdict is USED, not merely tolerated: a PhD bar disqualifies a Master's.
    assert out["disqualified"] is True
    assert out["screen"]["degree"]["pass"] is False
    assert out["screen"]["clearance"]["pass"] is True


def test_the_observed_flat_response_is_kept_not_discarded():
    # The exact payload from the 2026-07-29 eval run. `["phd", "master's"]` under min(rank)
    # is a master's bar, so a Master's candidate passes -- and the point is that the row is
    # SCREENED and kept, rather than deferred as a provider error.
    seen = {"degree": {"degree_levels": ["phd", "master's"], "degree_required": True},
            "clearance": {"requires_clearance": False}}
    out = screen_engine.screen_posting(POSTING, extract=lambda p, s: seen,
                               candidate={"highest_degree": "Master's",
                                          "security_clearance": "none"})
    assert "provider_error" not in out
    assert out["disqualified"] is False
    assert out["screen"]["degree"]["pass"] is True


def test_the_flat_shape_and_the_schema_shape_agree():
    # One reader for both shapes, so they cannot drift apart.
    inner = {"degree": {"degree_levels": ["phd"], "degree_required": True}}
    candidate = {"highest_degree": "Master's"}
    flat = screen_engine.screen_posting(POSTING, extract=lambda p, s: inner, candidate=candidate)
    nested = screen_engine.screen_posting(POSTING, extract=lambda p, s: {"screen": inner},
                                 candidate=candidate)
    assert flat == nested


def test_an_empty_screen_object_is_a_verdict_and_keeps_the_floor():
    # The deliberate residual, and the line the narrow scope is drawn on: a well-formed
    # but empty `screen` dict is a backend that ANSWERED. The floor still runs, so a JD
    # that says so outright is caught with no model data. Widening the blind check to
    # cover this would contradict the four tests that pin the floor.
    jd = "We will not sponsor employment visas for this position."
    out = screen_engine.screen_posting({**POSTING, "description": jd},
                               extract=lambda p, s: {"screen": {}},
                               candidate={"work_authorization": "requires H-1B sponsorship"})
    assert "provider_error" not in out
    assert out["disqualified"] is True


def test_screen_backend_none_is_not_a_provider_error():
    # SCREEN_BACKEND=none has no provider to fail: the deterministic gates run alone
    # and the row is legitimately scored, exactly as documented. It must not be
    # mistaken for an outage.
    out = screen_engine.screen_posting(POSTING, extract=None,
                               candidate={"highest_degree": "Master's"})
    assert "provider_error" not in out


def test_a_deterministically_disqualified_row_never_reaches_the_provider():
    # The location/intern gates are CODE, cost nothing, and their verdict is terminal —
    # so they run FIRST and the model is never called. A provider outage cannot
    # resurrect a posting they disqualified, because the provider is not consulted.
    # This is also the cost fix: 37% of the live `new` queue died on these gates, and
    # each one first bought a ~1.5s GPU call for nothing (2026-07-31).
    calls = []

    def extract(prompt, schema):
        calls.append(prompt)
        raise ModelResponseError("provider down")

    out = screen_engine.screen_posting({**POSTING, "location": "Shanghai, China"},
                               extract=extract,
                               candidate={"highest_degree": "Master's",
                                          "locations": ["remote", "USA"]})
    assert calls == []                          # the whole point: no model call
    assert out["disqualified"] is True          # deterministic gate still wins
    assert "provider_error" not in out          # nothing was attempted, nothing failed


def test_a_provider_error_never_disqualifies_on_the_sponsorship_phrase_floor():
    # The "authorization always records a verdict" block runs the closed-list floor when
    # no labels arrived — correct for SCREEN_BACKEND=none, WRONG on a dead provider. The
    # floor is a substring scan of the whole description that matches "without
    # sponsorship" inside *"or are eligible to work without sponsorship, we encourage you
    # to apply"* — an invitation. On a working backend the model's labels overrule it; on
    # a dead one nothing does, so an Ollama outage would TERMINALLY discard exactly the
    # postings retrieve-then-classify was built to stop discarding (`run_score` honours a
    # disqualification even on the provider_error path, writing status `discarded`).
    # The docstring's "a failure errs toward KEEP, never toward discard" and SPEC §7.1
    # both say so; the code did not.
    def extract(prompt, schema):
        raise ModelResponseError("provider down")

    jd = ("If you are eligible to work without sponsorship, we encourage you to apply. "
          "We build low-latency trading systems.")
    out = screen_engine.screen_posting({**POSTING, "description": jd}, extract=extract,
                               candidate={"work_authorization": "requires H-1B sponsorship"})
    assert out["provider_error"] is True
    assert out["disqualified"] is False
    # The key stays ABSENT rather than recording a pass: the row is left `new`, so
    # nothing downstream reads it and the next pass screens it properly.
    assert "authorization" not in out["screen"]


def test_screen_backend_none_still_records_the_authorization_floor_verdict():
    # The counterpart the fix must not break. With no provider there is no outage — the
    # floor IS the intended whole verdict, and dropping it here would silently retire
    # the only sponsorship signal SCREEN_BACKEND=none has.
    jd = "We will not sponsor employment visas for this position."
    out = screen_engine.screen_posting({**POSTING, "description": jd}, extract=None,
                               candidate={"work_authorization": "requires H-1B sponsorship"})
    assert "provider_error" not in out
    assert out["disqualified"] is True
    assert out["screen"]["authorization"]["pass"] is False


def test_screen_request_sends_deterministic_options():
    http = FakeHttp(_screen_resp({}))
    screen_engine.screen_posting(POSTING, extract=_ollama(http, seed=7, num_ctx=4096),
                         num_ctx=4096, candidate={"highest_degree": "Master's"})
    opts = http.calls[0][1]["json"]["options"]
    assert opts["temperature"] == 0          # deterministic by default
    assert opts["seed"] == 7
    assert opts["num_ctx"] == 4096


def test_structured_candidate_renders_extraction_clauses_in_screen_call():
    # locations is deliberately omitted: it's a code gate now (resolve_location off
    # posting["location"]), so it renders no extraction clause in the SCREEN prompt.
    http = FakeHttp(json.dumps({"screen": {}}))
    # The authorization clause only renders when CODE retrieved something to classify,
    # so the JD has to mention sponsorship for all three clauses to appear.
    posting = dict(POSTING, description="We need Python. We cannot sponsor visas.")
    screen_engine.screen_posting(
        posting, extract=_ollama(http),
        candidate={
            "highest_degree": "Master's",
            "work_authorization": "needs visa sponsorship",
            "security_clearance": "none",
        },
    )
    prompt = http.calls[0][1]["json"]["prompt"]                # the SCREEN call
    # each structured requirement asks the model to EXTRACT a job fact — degree asks for
    # the LEVELS the posting names plus a required/preferred bool, never for a "minimum",
    # which is a judgment CODE makes by taking the lowest rank.
    assert "degree_levels" in prompt
    assert "degree_required" in prompt
    assert "sponsorship_labels" in prompt
    assert "requires_clearance" in prompt
    assert '"screen"' in prompt
    assert RESUME not in prompt                               # no résumé in the screen call


def test_empty_candidate_fields_render_no_screen_call():
    # No candidate at all, or a candidate with only blank/empty fields configured —
    # either way there's no checklist to screen against, so no Ollama call is made
    # and nothing is disqualified.
    for candidate in (None, {"highest_degree": "", "locations": []}):
        http = FakeHttp()
        out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                                   candidate=candidate)
        assert len(http.calls) == 0, candidate
        assert out["disqualified"] is False, candidate


def _screen_resp(screen):
    return json.dumps({"screen": screen})


# location: gated in CODE off posting["location"] (pycountry), not the LLM screen
def test_foreign_location_disqualifies_from_board_string():
    posting = {**POSTING, "location": "Shanghai, China"}
    out = screen_engine.screen_posting(posting, extract=_ollama(FakeHttp()),
                               candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "location: on-site in China"
    assert out["screen"]["location"]["pass"] is False


def test_us_state_only_location_kept():
    posting = {**POSTING, "location": "New York, New York"}
    out = screen_engine.screen_posting(posting, extract=_ollama(FakeHttp()),
                               candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False
    assert out["screen"]["location"]["pass"] is True


def test_locations_only_candidate_makes_no_ollama_call():
    posting = {**POSTING, "location": "Sydney, Australia"}
    http = FakeHttp()
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"locations": ["remote", "USA"]})
    assert len(http.calls) == 0                               # location needs no LLM
    assert out["disqualified"] is True


def test_missing_board_location_is_kept():
    posting = {**POSTING, "location": None}
    out = screen_engine.screen_posting(posting, extract=_ollama(FakeHttp()),
                               candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False                       # err toward keep


def test_deterministic_screen_flags_intern_and_location():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    posting = {"job_title": "Data Science Intern", "location": "Shanghai, China"}
    out = screen_engine.deterministic_screen(
        base, posting, {"exclude_internships": True, "locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert out["screen"]["internships"]["pass"] is False
    assert out["screen"]["location"]["pass"] is False
    assert "internship/co-op role" in out["disqualification_reason"]
    assert "location: on-site in China" in out["disqualification_reason"]


def test_deterministic_screen_passes_clean_row():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    posting = {"job_title": "Software Engineer", "location": "New York, New York"}
    out = screen_engine.deterministic_screen(base, posting, {"locations": ["remote", "USA"]})
    assert out["disqualified"] is False


def test_deterministic_screen_noop_without_candidate():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    out = screen_engine.deterministic_screen(base, {"job_title": "Intern"}, None)
    assert out == {"screen": {}, "disqualified": False, "disqualification_reason": ""}


# degree: the LLM extracts which levels the posting NAMES plus a required/preferred
# bool; CODE takes the lowest rank and compares. The legacy single-`required_degree`
# shape below is the fit scorer's Stage 4 block, still read for the fallback path.
def test_higher_required_degree_disqualifies():
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is True
    assert "degree" in out["disqualification_reason"]


def test_lower_or_no_required_degree_passes():
    for req in ("bachelor's", "none", ""):
        http = FakeHttp(_screen_resp({"degree": {"required_degree": req}}))
        out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                                   candidate={"highest_degree": "Master's"})
        assert out["disqualified"] is False, req


def _degree_screen(levels, required, cand="Master's"):
    http = FakeHttp(_screen_resp(
        {"degree": {"degree_levels": levels, "degree_required": required}}))
    return screen_engine.screen_posting(POSTING, extract=_ollama(http),
                                candidate={"highest_degree": cand})


def test_degree_levels_take_the_lowest_not_the_highest():
    # THE DEFECT, pinned. `make eval-screen` measured 9 of 38 live degree discards wrong
    # because the model was asked for "the minimum" and returned the highest level it
    # saw. It now lists the levels and CODE takes the lowest, so every one of these
    # keeps a candidate holding a Master's.
    for levels in (["phd", "master's"],                       # "PhD, or Master's degree"
                   ["master's", "phd"],                       # "Ms or PhD" — order-free
                   ["phd", "master's", "bachelor's"],         # Microsoft's ladder
                   ["phd", "none"]):                          # "PhD or equivalent"
        assert _degree_screen(levels, True)["disqualified"] is False, levels
    # A genuine sole-PhD bar still disqualifies — the fix must not gut the check.
    out = _degree_screen(["phd"], True)
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "degree: requires phd"


def test_a_merely_preferred_degree_is_not_a_bar():
    # "PhD strongly preferred" / "DESIRABLE CANDIDATES: Ph.D. candidates" — the posting
    # names a level but does not require it, so there is nothing to disqualify on.
    out = _degree_screen(["phd"], False)
    assert out["disqualified"] is False
    assert out["screen"]["degree"]["pass"] is True


def test_unrecognized_degree_levels_are_dropped_not_ranked():
    # `_degree_rank` returns 0 for any unrecognized string, so counting one as a level
    # would silently read as "none required" — a pass badge from a shrug. They are
    # dropped; a list with nothing recognized in it leaves no bar at all.
    assert _degree_screen(["phd", "unknown"], True)["disqualified"] is True
    assert _degree_screen(["TBD", "not stated"], True)["disqualified"] is False


def test_blind_degree_levels_leave_a_gap_for_the_fallback():
    # The new shape has two ways to say nothing, and both must record NO verdict so
    # merge_fallback_screen still sees the gap: a null/garbled `degree_required`, and a
    # `degree_required: true` with no recognized level to compare against.
    cand = {"highest_degree": "Master's"}
    for entry in ({"degree_levels": ["phd"], "degree_required": None},
                  {"degree_levels": None, "degree_required": "yes-ish"},
                  {"degree_levels": [], "degree_required": True},
                  {"degree_levels": ["unclear"], "degree_required": True}):
        out = screen_engine._screen_verdict({"screen": {"degree": entry}}, cand, "JD")
        assert "degree" not in out["screen"], entry
    # "no degree required" needs no levels — it is a real answer, not a gap.
    out = screen_engine._screen_verdict(
        {"screen": {"degree": {"degree_levels": [], "degree_required": False}}}, cand, "JD")
    assert out["screen"]["degree"]["pass"] is True


# authorization: these exercise the NO_SPONSOR_PHRASES floor specifically — the model's
# response carries no "authorization" key, so `_quote_in` sees no quote and the verdict
# falls through to the phrase floor. The quote-grounded PRIMARY path (and the
# no-quote/silent-JD -> kept invariant) has its own "quote-grounded sponsorship" section
# further below.
def test_no_sponsorship_disqualifies_when_jd_says_so():
    posting = {**POSTING, "description": "We will not sponsor visas for this role."}
    http = FakeHttp(_screen_resp({"authorization": {}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


def test_citizen_never_fails_authorization():
    http = FakeHttp(_screen_resp({"authorization": {"no_sponsorship_quote": "We do not sponsor."}}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"work_authorization": "US citizen"})
    assert out["disqualified"] is False


def test_authorization_ignores_sponsor_boilerplate():
    # D1 repro: a JD mentioning 'sponsor'/'citizen' only in boilerplate must NOT
    # disqualify. Tower matched "sponsor" in "company-sponsored sports teams" (id=986);
    # WorldQuant matched "citizen" in the EEO line (id=1071). Neither the phrase floor
    # nor a (here-absent) quote should fire on boilerplate mentions.
    for desc in (
        "We field company-sponsored sports teams and a great engineering culture.",
        "EEO: we do not discriminate on citizenship, national origin, disability, or age.",
    ):
        posting = {**POSTING, "description": desc}
        http = FakeHttp(_screen_resp({"authorization": {}}))
        out = screen_engine.screen_posting(posting, extract=_ollama(http),
                                   candidate={"work_authorization": "needs visa sponsorship"})
        assert out["disqualified"] is False, desc


def test_authorization_fails_only_on_explicit_no_sponsorship_phrase():
    # D1: an explicit floor phrase disqualifies even with no quote from the model — the
    # floor, not model trust, decides here.
    posting = {**POSTING, "description": "Strong team. This position offers no visa sponsorship."}
    http = FakeHttp(_screen_resp({"authorization": {}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


# clearance: LLM extracts requires_clearance, code checks — and CODE also requires the
# JD to actually SAY so (the evidence floor; see the CLEARANCE_TOKENS block below).
def test_clearance_required_disqualifies():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = screen_engine.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True


def test_clearance_not_required_passes():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": False}}))
    out = screen_engine.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is False


def test_ungrounded_clearance_claim_keeps_the_posting():
    # THE DEFECT, pinned. Every one of the 20 wrong discards looked exactly like this:
    # "security" all over the JD, `requires_clearance: true`, and not one clearance word.
    posting = dict(POSTING, job_title="Senior Security Researcher",
                   description=("Join our security team. You will work on Azure "
                                "security, application security reviews, and secure "
                                "coding practices across the platform."))
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is False
    assert out["screen"]["clearance"]["pass"] is True


def test_clearance_grounded_in_the_title_alone_disqualifies():
    # Evidence is title OR description: the two grounded `degree` discards the same
    # 2026-07-27 query found state their bar in the title and nowhere else, so the
    # clearance floor reads both rather than the description only.
    posting = dict(POSTING, job_title="TS/SCI Cleared Systems Engineer")
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "clearance: requires security clearance"


@pytest.mark.parametrize("text", [
    "You will join our data science team and ship models.",
    "BS in Computer Science or equivalent experience required.",
    "Our Chief Scientist leads the research group.",
    # The three phrasings above all happen to put a non-`ts` word before "sci". These
    # three do not, and every one of them matched `ts[.\s/-]?sci` before the `\b`:
    # the separator is optional, so the pattern spanned the word gap in "supporTS
    # SCIentific". One live posting (id 4899, "how OpenAI supports scientists and life
    # sciences organizations") was grounding a clearance claim on it.
    "The platform supports scientific computing at scale.",
    "Microsoft and its scientific partners collaborate on this.",
    "You will work with our products scientists every week.",
])
def test_science_words_do_not_ground_a_clearance_claim(text):
    # The `sci` trap: a bare `sci` token would match science/scientist/Science and
    # re-open the exact false-discard direction this floor exists to close. The set
    # spells the abbreviation as `ts/sci`, so these three keep.
    posting = dict(POSTING, description=text)
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is False


# internships/co-op: decided deterministically from the title via the
# exclude_internships flag (a structured constraint), not by the 4B model.
def test_exclude_internships_disqualifies_intern_title():
    posting = {**POSTING, "job_title": "Software Engineer Intern"}
    http = FakeHttp(_screen_resp({}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"exclude_internships": True})
    assert out["disqualified"] is True
    assert "internship/co-op role" in out["disqualification_reason"]


def test_exclude_internships_passes_non_intern_title():
    http = FakeHttp(_screen_resp({}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"exclude_internships": True})
    assert out["disqualified"] is False


def test_intern_title_not_excluded_without_the_flag():
    # No exclude_internships -> an intern title is not auto-disqualified.
    posting = {**POSTING, "job_title": "Software Engineer Intern"}
    http = FakeHttp(_screen_resp({}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


def test_exclude_internships_only_makes_no_screen_call():
    # The flag is deterministic (title-only), so a candidate that sets ONLY it does
    # not trigger a SCREEN Ollama call.
    posting = {**POSTING, "job_title": "Backend Intern"}
    http = FakeHttp()
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"exclude_internships": True})
    assert len(http.calls) == 0
    assert out["disqualified"] is True


def test_is_internship_whole_word_matching():
    # Real intern/co-op titles match; "internal"/"international" must not.
    assert screen_engine._is_internship("Software Engineer Intern")
    assert screen_engine._is_internship("2026 Summer Internship")
    assert screen_engine._is_internship("Data Science Co-op")
    assert not screen_engine._is_internship("Internal Tools Engineer")
    assert not screen_engine._is_internship("International Sales Lead")


def test_skill_gap_and_unknown_keys_do_not_disqualify():
    # An invented key (skills) is ignored; a passing configured gate doesn't fail.
    http = FakeHttp(_screen_resp({"skills": {"pass": False, "note": "no C++"},
                                  "degree": {"required_degree": "bachelor's"}}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert "skills" not in out["screen"]


def test_unconfigured_requirement_is_not_checked():
    # Candidate sets only degree; a stray clearance extraction must be ignored.
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True},
                                  "degree": {"required_degree": "bachelor's"}}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert "clearance" not in out["screen"]


def _raw_http(envelope=None, *, raise_exc=None):
    """An http stub whose POST returns a RAW Ollama envelope (or raises), so the
    SCREEN call's transport branch is exercised (FakeHttp always wraps in a valid
    {"response": ...} and never raises)."""
    resp = Mock()
    resp.raise_for_status.side_effect = raise_exc
    resp.json.return_value = envelope
    http = Mock()
    http.post.return_value = resp
    return http


def test_screen_transport_failure_errs_toward_keep():
    # A transport-level failure on the real Ollama-backed extract (e.g. Ollama
    # unreachable) must ALSO err toward keep, same as a parse failure — screen_posting
    # catches ANY extract failure, not just ScoreError (see
    # test_extract_failure_errs_toward_keep for the same invariant via a hand-rolled
    # extract). Before the extract seam this propagated instead; now the backend
    # contract is "extract raised", full stop — screen_posting doesn't distinguish
    # transport failures from parse failures, so neither can discard the posting.
    http = _raw_http(raise_exc=requests.HTTPError("ollama 500"))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert out["screen"] == {}


@pytest.mark.parametrize("gate,candidate", [
    ("degree", {"highest_degree": "Master's"}),
    ("authorization", {"work_authorization": "needs visa sponsorship"}),
    ("clearance", {"security_clearance": "none"}),
])
def test_empty_extraction_per_gate_never_disqualifies(gate, candidate):
    # Each gate is CONFIGURED, but the model returns an empty fact for it. The
    # design never discards on absent data, so disqualified must be False.
    http = FakeHttp(_screen_resp({gate: {}}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate=candidate)
    assert out["disqualified"] is False, gate


def test_non_dict_gate_entry_is_treated_as_empty():
    # A garbled (non-dict) extraction for a configured gate must not crash or fail.
    http = FakeHttp(_screen_resp({"degree": "nonsense"}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


def test_equal_required_degree_passes_pinning_greater_than():
    # required == candidate (master's) must PASS — pins `>` (not `>=`) in the gate.
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "master's"}}))
    out = screen_engine.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


def test_candidate_not_needing_sponsorship_passes_even_if_jd_says_no():
    posting = {**POSTING, "description": "We do not offer visa sponsorship."}
    http = FakeHttp(_screen_resp(
        {"authorization": {"no_sponsorship_quote": "We do not offer visa sponsorship."}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "no sponsorship needed"})
    assert out["disqualified"] is False


def test_candidate_holding_clearance_passes_when_role_requires_one():
    # CLEARED_POSTING so the evidence floor is SATISFIED — this pins the holder
    # short-circuit, not the floor keeping an ungrounded row by accident.
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = screen_engine.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "Secret"})
    assert out["disqualified"] is False


_NEEDS_VISA = {"work_authorization": "needs visa sponsorship"}


def _screen_labels(labels, description):
    """Screen `description` with the model returning `labels`, one per retrieved snippet."""
    http = FakeHttp(json.dumps({"screen": {"authorization": {"sponsorship_labels": labels}}}))
    posting = dict(POSTING, description=description)
    return screen_engine.screen_posting(posting, extract=_ollama(http), candidate=_NEEDS_VISA)


def _sponsor_jd(sentence):
    return f"About the role. {sentence} Apply now."


def test_snippets_are_the_sponsor_sentence_plus_one_neighbour_each_side():
    jd = ("We build trading systems. The team is small. "
          "We do not offer visa sponsorship. You will own your work. Apply today.")
    snips = screen_engine.sponsorship_snippets(jd)
    assert len(snips) == 1
    assert snips[0] == ("The team is small. We do not offer visa sponsorship. "
                        "You will own your work.")


def test_a_bare_sentence_would_lose_its_antecedent_so_the_window_carries_it():
    # The reason the window is +/-1 and not the sentence alone: "Sponsorship is not
    # among them" is unlabelable without the sentence before it.
    jd = "We offer relocation and a signing bonus. Sponsorship is not among them."
    assert screen_engine.sponsorship_snippets(jd) == [
        "We offer relocation and a signing bonus. Sponsorship is not among them."]


def test_a_jd_that_never_says_sponsor_yields_no_snippets():
    # No snippets means no clause in the prompt and nothing to classify — the check
    # simply does not run, which is why silence keeps.
    assert screen_engine.sponsorship_snippets(
        "A normal job description with no mention of immigration status.") == []


def test_one_snippet_per_sponsor_sentence_even_when_they_are_adjacent():
    # NOT merged, deliberately. The label is about the CENTRE sentence, so merging two
    # hits forces one answer for both — and an earlier version of this function did
    # exactly that, which made live IMC rows 465/490 come back `refuses` on a paragraph
    # that refuses three named nationalities AND offers sponsorship to Ukrainians.
    # Repeating a shared neighbour costs a few hundred prompt chars; merging cost a job.
    assert screen_engine.sponsorship_snippets(
        "Intro. We sponsor visas. We also sponsor conferences. Outro.") == [
        "Intro. We sponsor visas. We also sponsor conferences.",
        "We sponsor visas. We also sponsor conferences. Outro."]
    jd = ("We sponsor a robotics team. " + "Filler sentence. " * 5
          + "We cannot sponsor work visas. We are hiring now.")
    snips = screen_engine.sponsorship_snippets(jd)
    assert len(snips) == 2
    assert "robotics" in snips[0] and "work visas" in snips[1]


def test_a_scoped_refusal_beside_an_offer_keeps_the_posting():
    # The shape that forced per-sentence snippets, reduced from IMC ids 465/490.
    jd = ("Apply today. We are unable to obtain sponsorship for candidates from certain "
          "countries. If you hold a biometric passport we can obtain sponsorship for you. "
          "Contact recruitment.")
    snips = screen_engine.sponsorship_snippets(jd)
    assert len(snips) == 2
    assert _screen_labels(["refuses", "offers"], jd)["disqualified"] is False


def test_the_abbreviation_trap_pr22_sprang_does_not_split_early():
    # PR #22's splitter stripped the dot from any single-letter token, merging
    # "based in the U.S. Citizenship is not required" into a fake citizenship bar.
    # Under this design a mis-split only widens the window — the model still reads the
    # words — but the guard is cheap and the case is a real posting.
    sents = screen_engine._sentences("Roles are based in the U.S. Sponsorship is not required. Apply.")
    assert sents[0] == "Roles are based in the U.S. Sponsorship is not required."


def test_a_refuses_label_disqualifies():
    out = _screen_labels(["refuses"], _sponsor_jd("We will not sponsor visas for this role."))
    assert out["disqualified"] is True
    assert "sponsorship" in out["disqualification_reason"]


@pytest.mark.parametrize("label", ["neither", "offers"])
def test_a_non_refusal_label_keeps(label):
    out = _screen_labels([label], _sponsor_jd("Visa sponsorship is available for this role."))
    assert out["disqualified"] is False


def test_an_offer_anywhere_outranks_a_refusal():
    # The two only co-occur when a posting is describing WHO it can sponsor, and a
    # wrongly-deleted opportunity is the expensive error. Offer wins.
    jd = ("Intro. We sponsor Skilled Worker visas. " + "Filler. " * 4
          + "We do not sponsor interns. Outro.")
    assert len(screen_engine.sponsorship_snippets(jd)) == 2
    assert _screen_labels(["offers", "refuses"], jd)["disqualified"] is False


def test_the_offers_veto_overrules_a_refuses_label_but_never_creates_one():
    # _OFFERS_SPONSORSHIP survives DEMOTED: keep-direction only. A model that labels a
    # plain offer "refuses" is overruled...
    jd = _sponsor_jd("Visa sponsorship is available for this position.")
    assert _screen_labels(["refuses"], jd)["disqualified"] is False
    # ...but the veto cannot invent a disqualification out of a "neither".
    assert _screen_labels(["neither"], jd)["disqualified"] is False


def test_a_preference_is_vetoed_too_because_the_classifier_calls_it_a_refusal():
    # The design note predicted a classifier would make all three regex vetoes
    # unnecessary. Two of them, yes; this one no — `make eval-screen` caught the 4B
    # labelling this exact TikTok sentence `refuses` on 3 live rows, all three draws.
    # A preference is not a bar: the candidate can still apply.
    jd = _sponsor_jd("Our Company will be prioritizing applicants who have a current "
                     "right to work in Singapore, and do not require sponsorship of a visa.")
    assert _screen_labels(["refuses"], jd)["disqualified"] is False
    # It is keep-direction only: it cannot turn a real refusal into a keep just because
    # the word "prefer" appears far from the sponsorship clause.
    hard = _sponsor_jd("We prefer candidates based in London. We will not sponsor visas.")
    assert _screen_labels(["refuses"] * len(screen_engine.sponsorship_snippets(hard)),
                          hard)["disqualified"] is True


def test_a_refusal_is_not_vetoed_by_a_negated_offer_verb():
    # "we do not PROVIDE sponsorship" must not read as an offer just because it contains
    # the offer verb — the negation sits immediately before it.
    jd = _sponsor_jd("Please note that we do not provide immigration sponsorship for this position.")
    assert _screen_labels(["refuses"], jd)["disqualified"] is True


@pytest.mark.parametrize("labels", [
    [],                       # model said nothing
    ["refuses", "refuses"],   # more labels than snippets
    ["yes"],                  # off-vocabulary
    None,                     # key absent entirely
])
def test_unusable_labels_drop_the_check_rather_than_guessing(labels):
    # A count or vocabulary mismatch means the model answered a different question. The
    # check is dropped and the posting KEPT — the phrasing here is a genuine refusal the
    # closed-list floor does NOT carry, so nothing else can rescue it. That is the
    # intended trade: a miss costs one paid fit call, a false discard costs the job.
    jd = _sponsor_jd("Sponsorship for this role is unavailable.")
    assert _screen_labels(labels, jd)["disqualified"] is False, labels


def test_label_case_and_whitespace_are_normalized():
    jd = _sponsor_jd("We will not sponsor visas for this role.")
    assert _screen_labels(["  Refuses "], jd)["disqualified"] is True


def test_a_miscounted_answer_does_not_fall_through_to_the_floor():
    # Both long-standing IMC false positives (ids 465/490) came from exactly this path:
    # the 4B returned ONE label for three snippets, the check was dropped, the closed
    # list then scanned the WHOLE description, and "without sponsorship" matched inside
    # an invitation to apply. A model that returned labels answered the question — a bad
    # count is not silence, and must not re-enable the ungated gate this design replaces.
    jd = _sponsor_jd("If you are eligible to work without sponsorship, we encourage you "
                     "to apply. We also sponsor conferences.")
    assert len(screen_engine.sponsorship_snippets(jd)) == 2
    assert "without sponsorship" in jd                    # the floor WOULD match
    assert _screen_labels(["neither"], jd)["disqualified"] is False   # 1 label, 2 snippets
    assert _screen_labels(["yes", "yes"], jd)["disqualified"] is False  # off-vocabulary


def test_an_empty_label_array_against_retrieved_snippets_is_a_bad_count_not_silence():
    # `sponsorship_labels` is `["array", "null"]` in SCREEN_SCHEMA, so `[]` is a legal
    # answer and a plausible 4B one. It was read as silence because `[]` is falsy, which
    # sent it to the closed-list floor — re-opening the exact IMC false positive the
    # design closes, on a JD the floor matches for the wrong reason. `test_unusable_
    # labels_drop_the_check_rather_than_guessing` covers `[]` too but on a JD carrying NO
    # floor phrase, so it passed either way; this one pins the direction that costs a job.
    jd = _sponsor_jd("If you are eligible to work without sponsorship, we encourage you "
                     "to apply. We also sponsor conferences.")
    assert len(screen_engine.sponsorship_snippets(jd)) == 2       # a question WAS asked...
    assert "without sponsorship" in jd                    # ...and the floor WOULD match
    assert _screen_labels([], jd)["disqualified"] is False


def test_an_empty_label_array_with_nothing_retrieved_still_reaches_the_floor():
    # The other side of the same line, and why the guard is `answered AND snippets`
    # rather than bare `answered`. With no snippet there was no question to answer, so
    # `[]` is the correct empty answer and the floor is the whole verdict — the
    # documented silence path (SPEC §7.1), not a bad count.
    # This pins a CONTRACT, not a currently-live path: every NO_SPONSOR_PHRASES entry
    # contains "sponsor", so retrieval always yields a snippet for any JD the floor could
    # match, and the two branches agree today. It stops mattering the moment the closed
    # list gains a phrase without that word — at which point bare `answered` would retire
    # the floor silently. Called directly because this check is not re-exported.
    jd = "We will not sponsor employment visas for this position."
    entry = {"sponsorship_labels": []}
    assert screen_engine._check_authorization("requires H-1B sponsorship", jd, entry, []) \
        == (False, "no visa sponsorship offered")


def test_hallucination_cannot_disqualify_because_the_model_supplies_no_text():
    # THE security property, now structural. The model returns a label over a snippet
    # CODE retrieved; there is no channel for invented text to reach the decision.
    jd = "Great role. We welcome applicants from all backgrounds."
    assert screen_engine.sponsorship_snippets(jd) == []          # nothing retrieved...
    assert _screen_labels(["refuses"], jd)["disqualified"] is False   # ...so nothing to act on


def test_the_phrase_floor_runs_only_when_no_labels_arrived():
    # SCREEN_BACKEND=none, a garbled response, or the fit scorer's Stage 4 shape.
    jd = "This employer does not sponsor applicants for work visas."
    assert _screen_labels(None, jd)["disqualified"] is True


def test_the_floor_never_vetoes_a_model_keep():
    # The floor can only ADD a disqualification. A blunt phrase the model labelled
    # "offers" must not be resurrected by the closed list.
    jd = "We can sponsor, but note we have no sponsorship for contract roles."
    assert _screen_labels(["offers"], jd)["disqualified"] is False


def test_a_silent_jd_is_kept():
    out = _screen_labels(None, "A normal job description with no mention of immigration status.")
    assert out["disqualified"] is False


def test_candidate_not_needing_sponsorship_is_never_gated():
    http = FakeHttp(json.dumps(
        {"screen": {"authorization": {"sponsorship_labels": ["refuses"]}}}))
    posting = dict(POSTING, description="We will not sponsor.")
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "citizen"})
    assert out["disqualified"] is False


def test_the_authorization_clause_is_omitted_when_nothing_was_retrieved():
    # No snippets -> no clause -> the model is never asked a question about text that is
    # not there. But the VERDICT is still recorded, so merge_fallback_screen sees no gap
    # and the fit scorer never gets a second vote on a disqualification (SPEC §7.1).
    http = FakeHttp(_screen_resp({}))
    posting = dict(POSTING, description="A normal JD with no mention of immigration.")
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={**_NEEDS_VISA, "highest_degree": "Master's"})
    prompt = http.calls[0][1]["json"]["prompt"]
    # Assert on the CLAUSE, not the key: the header's worked example names every key.
    assert "- authorization:" not in prompt        # nothing to classify, so nothing asked
    assert "- degree:" in prompt                   # the other clauses are unaffected
    assert out["screen"]["authorization"]["pass"] is True


def test_authorization_records_a_verdict_even_with_no_llm_call_at_all():
    # Sponsorship is the ONLY configured requirement and the JD never says "sponsor", so
    # the checklist is empty and no call is made. The verdict must still be recorded:
    # merge_fallback_screen fills only ABSENT keys, and letting the fit scorer supply a
    # second opinion on a disqualification is what SPEC §7.1 forbids.
    posting = dict(POSTING, description="A normal JD with no mention of immigration.")
    out = screen_engine.screen_posting(posting, extract=lambda p, s: pytest.fail("no call"),
                               candidate=_NEEDS_VISA)
    assert out["screen"]["authorization"]["pass"] is True
    assert out["disqualified"] is False
    # ...and the floor still stands on that no-call path.
    blunt = dict(POSTING, description="This employer does not sponsor work visas.")
    out = screen_engine.screen_posting(blunt, extract=None, candidate=_NEEDS_VISA)
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "authorization: no visa sponsorship offered"


def test_the_retrieved_snippets_are_numbered_into_the_prompt():
    http = FakeHttp(_screen_resp({}))
    posting = dict(POSTING, description=_sponsor_jd("We will not sponsor visas."))
    screen_engine.screen_posting(posting, extract=_ollama(http), candidate=_NEEDS_VISA)
    prompt = http.calls[0][1]["json"]["prompt"]
    assert "sponsorship_labels" in prompt
    assert "1. About the role. We will not sponsor visas. Apply now." in prompt


def _corpus():
    return json.loads((Path(__file__).parent / "fixtures" /
                       "sponsorship_quotes.json").read_text())


def test_every_must_keep_sentence_survives_the_code_path():
    # A wrong answer here SILENTLY DISCARDS A REAL JOB, so it stays the direction that
    # matters. Under this design most must_keep sentences are never even retrieved (no
    # `sponsor` token); the rest reach the model as `neither`/`offers` and keep. The
    # adversarial case is a model that labels every one of them "refuses" — only the
    # keep-direction offers-veto stands between that and a deleted job, so that is what
    # this asserts.
    leaked = []
    for q in _corpus()["must_keep"]:
        jd = _sponsor_jd(q)
        n = len(screen_engine.sponsorship_snippets(jd))
        if n and _screen_labels(["refuses"] * n, jd)["disqualified"]:
            leaked.append(q)
    # The off-topic and EEO shapes are no longer code's problem — they carry no `sponsor`
    # token, or the model labels them `neither`. What must still hold is that a genuine
    # OFFER can never be turned into a discard by a mislabel.
    offers = [q for q in _corpus()["must_keep"] if screen_engine._offers_sponsorship(q.lower())]
    assert len(offers) >= 8, "the offers-veto corpus shrank"
    assert not [q for q in offers if q in leaked], (
        "a genuine offer was disqualified:\n" + "\n".join(leaked))


def test_the_narrowed_vocabulary_names_exactly_which_bars_it_gives_up():
    # `sponsor` alone is the retrieval vocabulary, and that is a MEASURED narrowing: every
    # false positive on this path ever recorded came from `citizen`/`visa`/`authoriz`/
    # `right to work`. The cost is real and is stated here rather than hidden: a bar that
    # never says "sponsor" is not retrieved, so it is a MISS — one paid fit call, and the
    # posting reaches the human. This pins the SIZE of that trade so it cannot grow
    # silently, in either direction.
    flag = _corpus()["must_flag"]
    retrievable = [q for q in flag if screen_engine.sponsorship_snippets(_sponsor_jd(q))]
    missed = [q for q in flag if q not in retrievable]
    assert len(retrievable) == 6 and len(missed) == 7, (
        f"the recall trade moved: {len(retrievable)} retrievable, {len(missed)} missed\n"
        + "\n".join(missed))
    # Every retrievable one must actually disqualify when the model labels it refuses.
    not_flagged = [q for q in retrievable
                   if not _screen_labels(["refuses"], _sponsor_jd(q))["disqualified"]]
    assert not not_flagged, "retrieved but not disqualified:\n" + "\n".join(not_flagged)


def test_multiple_failing_gates_join_reasons():
    # Both of these are deterministic, so both run before any model call and both
    # reasons are recorded. (A model-derived reason can no longer JOIN a deterministic
    # one: the deterministic gate short-circuits the call — see the test below.)
    posting = {**POSTING, "location": "Singapore",
               "job_title": "Software Engineering Intern"}
    out = screen_engine.screen_posting(posting, extract=None,
                               candidate={"locations": ["USA"],
                                          "exclude_internships": True})
    assert out["disqualified"] is True
    reason = out["disqualification_reason"]
    assert "internship" in reason and "location" in reason
    assert "; " in reason  # joined, not a single failure


def test_a_deterministic_gate_short_circuits_the_model_reason():
    # A row failing BOTH a deterministic gate and a model-derived one now reports only
    # the deterministic reason, because the model was never asked. The outcome for the
    # row is identical (discarded); what is given up is extra detail on a dead row.
    posting = {**POSTING, "location": "Singapore"}
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    out = screen_engine.screen_posting(posting, extract=_ollama(http),
                               candidate={"highest_degree": "Master's",
                                          "locations": ["USA"]})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "location: on-site in Singapore"
    assert http.calls == []          # no GPU call bought for an already-dead row


@pytest.mark.parametrize("value", ["true", "yes", "1", "required", "TRUE", 1, True, 2.5])
def test_flag_truthy_tokens(value):
    assert screen_engine._flag(value) is True


@pytest.mark.parametrize("value", ["no", "false", "maybe", "", None, 0, False, "remote"])
def test_flag_falsy_tokens(value):
    assert screen_engine._flag(value) is False


@pytest.mark.parametrize("text,rank", [
    ("none", 0), ("no degree", 0), ("", 0),
    ("High School Diploma", 1), ("GED", 1),
    ("Associate", 2), ("Bachelor's or higher", 3),
    ("Master's", 4), ("PhD", 5), ("Doctorate", 5),
])
def test_degree_rank_ladder(text, rank):
    assert screen_engine._degree_rank(text) == rank


@pytest.mark.parametrize("auth,needs", [
    ("needs visa sponsorship", True),
    ("requires sponsorship", True),
    ("no sponsorship needed", False),
    ("without sponsorship", False),
    ("US citizen", False),
    ("permanent resident", False),
])
def test_needs_sponsorship(auth, needs):
    assert screen_engine._needs_sponsorship(auth) is needs


def test_truncate_boundary_and_disabled():
    assert screen_prompts._truncate("abcde", 5) == "abcde"          # exact length: not cut
    assert "truncated" in screen_prompts._truncate("abcdef", 5)     # one over: cut
    assert screen_prompts._truncate("abcdef", 0) == "abcdef"        # max_chars<=0: disabled


def test_job_block_omits_location_for_the_fit_score_call():
    # D5: the fit SCORE call drops the Location line so geography can't leak into the
    # fit number (location is decided by the screen gate, not the score); the SCREEN
    # call keeps it (default).
    posting = {**POSTING, "location": "Chicago, IL"}
    assert "Location: Chicago, IL" in screen_prompts._job_block(posting, 0)                 # screen (default)
    assert "Location:" not in screen_prompts._job_block(posting, 0, include_location=False)  # score


def test_blind_screen_entry_still_leaves_a_gap_for_the_fallback():
    # Under the strict schema the model MUST emit every key, so a blind check arrives
    # as {"required_degree": None} -- a non-empty dict that says nothing. Gating on the
    # dict's truthiness would mark it "passed" and silently retire the Stage 4 fallback.
    cand = {"highest_degree": "bachelors", "security_clearance": "none"}
    # null, blank AND "unknown" all mean the model said nothing. screen.txt instructs it
    # to answer "unknown" for an unstated fact, and _check_degree/_degree_rank already
    # treat blank and "unknown" as no-data -- so a gate testing only `is not None` would
    # record them as a genuine PASS and retire the fallback through a different empty
    # value than the one it was written for.
    # The no-data spellings are OPEN-ENDED, which is why the check enumerates the
    # recognized DEGREE values instead. `_degree_rank` returns 0 for every string below,
    # so a gate that accepted them as data would materialize a pass from a shrug.
    for blank in (None, "", "   ", "unknown", "not specified", "N/A", "N.A.",
                  "not stated", "not mentioned", "unclear", "TBD", "varies", "?"):
        data = {"screen": {"degree": {"required_degree": blank},
                           "clearance": {"requires_clearance": None}}}
        out = screen_engine._screen_verdict(data, cand, "JD text")
        assert "degree" not in out["screen"], f"blind degree materialized for {blank!r}"
        assert "clearance" not in out["screen"]
        assert out["disqualified"] is False

    # A real answer still materializes -- including `False`, which is a fact, not a gap.
    out = screen_engine._screen_verdict(
        {"screen": {"degree": {"required_degree": "phd"},
                    "clearance": {"requires_clearance": False}}}, cand, "JD text")
    assert out["screen"]["clearance"]["pass"] is True
    assert out["screen"]["degree"]["pass"] is False   # bachelors < phd
    assert out["disqualified"] is True


def test_authorization_still_ruled_when_the_model_returns_no_entry():
    # The carve-out: unlike degree/clearance, authorization has an independent signal
    # (NO_SPONSOR_PHRASES over the JD), so it produces a real verdict with no model
    # data and must keep writing its key.
    posting = dict(POSTING, description="We do not sponsor work visas.")
    out = screen_engine.screen_posting(posting, extract=lambda p, s: {"screen": {}},
                               candidate={"work_authorization": "needs visa sponsorship"})
    assert out["screen"]["authorization"]["pass"] is False
    assert out["disqualified"] is True


def _strict_mode_violations(node, path="$"):
    """Every object in a schema sent to OpenAI-style structured output must list EVERY key
    of `properties` in `required` and set additionalProperties:false, or the API rejects
    the whole request with a 400 before the model runs. Yields the offenders."""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _strict_mode_violations(item, f"{path}[{i}]")
        return
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict):
        missing = set(props) - set(node.get("required") or [])
        if missing:
            yield f"{path}: properties {sorted(missing)} not in required"
        if node.get("additionalProperties") is not False:
            yield f"{path}: object without additionalProperties: false"
    for key, value in node.items():
        yield from _strict_mode_violations(value, f"{path}.{key}")


def test_screen_schema_is_strict_mode_valid():
    # SCREEN_SCHEMA reaches `codex exec --output-schema` and the api backend's
    # strict json_schema; a missing `required` key 400s every call on those backends.
    bad = list(_strict_mode_violations(screen_prompts.SCREEN_SCHEMA, "SCREEN_SCHEMA"))
    assert not bad, "strict-mode violations:\n" + "\n".join(bad)


# #206: contract / part-time / temporary, decided from the title like internships.
@pytest.mark.parametrize("title,hit", [
    ("Software Engineer (Contract)", True),
    ("Backend Engineer - Contractor", True),
    ("Part-Time Data Analyst", True),
    ("Part time Barista", True),
    ("Temporary Accountant", False),        # leading words other than Part-Time/C2H keep
    ("Contract-to-Hire QA Engineer", True),
    ("Data Analyst, Part-Time", True),
    ("QA Engineer - 6 Month Contract", True),
    ("Nurse (Per Diem)", True),
    ("Research Assistant (Fixed-Term)", True),
    ("Associate - Seasonal", True),
    ("Engineer: Contract", True),
    ("Engineer -Contract", True),
    ("Engineer - Contract (6 months)", True),
    ("Engineer, Payments - Contract", True),
    ("Designer [Temp]", True),
    # Err toward keep: jobs ABOUT contracts, and ambiguous leading words.
    ("Contract Manager", False),
    ("Contracts Specialist", False),
    ("Smart Contract Engineer", False),
    ("Solidity Smart Contract Auditor", False),
    ("Contract Negotiation Specialist", False),
    ("Contract Manufacturing Engineer", False),
    ("Contractor Relations Manager", False),
    ("Contractor Safety Coordinator", False),
    ("Temp Control Technician", False),
    ("Analyst (Contract Compliance)", False),
    ("Engineer (Contract Lifecycle Management)", False),
    ("Engineer (Temporary Housing)", False),
    ("Manager (Part-Time Programs)", False),
    ("Seasonal Forecasting Scientist", False),
    ("Freelance Platform Engineer", False),
    ("Fixed Term Contracts Analyst", False),
    ("Per Diem Program Manager", False),
    ("Full-time or Part-time Nurse", False),
    ("Software Engineer", False),
    ("Template Engineer", False),
    ("Full-Time Software Engineer", False),
    ("Senior Engineer - Platform", False),
])
def test_is_non_fulltime_title(title, hit):
    assert screen_engine._is_non_fulltime(title) is hit


def test_exclude_contract_disqualifies_without_a_screen_call():
    http = FakeHttp()
    out = screen_engine.screen_posting({**POSTING, "job_title": "Engineer (Contract)"},
                                       extract=_ollama(http), candidate={"exclude_contract": True})
    assert len(http.calls) == 0
    assert out["disqualified"] is True
    assert "contract/part-time/temporary role" in out["disqualification_reason"]


def test_contract_title_kept_without_the_flag():
    out = screen_engine.deterministic_screen(
        {"screen": {}, "disqualified": False, "disqualification_reason": ""},
        {**POSTING, "job_title": "Engineer (Contract)"}, {"exclude_internships": True})
    assert out["disqualified"] is False
