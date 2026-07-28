"""TDD for Ollama-backed JD/resume scoring. No real network (injected http)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from ats_worker import score


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
    return score.make_ollama_extract(http=http, **kw)


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


def _assessment(seniority="match", domain="match", met=None, missing=None,
                nice=None, summary="ok"):
    """A well-formed scorecard for the SCORE call's `assessment` (S2.1)."""
    return {
        "seniority": {"verdict": seniority, "note": ""},
        "domain": {"verdict": domain, "note": ""},
        "must_haves": {"met": met or [], "missing": missing or []},
        "nice_to_haves": {"missing": nice or []},
        "summary": summary,
    }


# --- _normalize_score: validates + coerces the SCORE call's raw output ----

def test_normalize_score_threads_score_and_assessment_lists():
    # _normalize_score must thread a well-formed scorecard through untouched:
    # the score value and the match/missing keyword lists it returns are
    # exactly what the scorer produced (not defaulted or coerced away).
    card = {"score": 88, "assessment": _assessment(
        met=["python", "django"], missing=["aws"], summary="Strong overlap.")}
    out = score._normalize_score(card)
    assert out["score"] == 88
    assert out["assessment"]["must_haves"]["met"] == ["python", "django"]
    assert out["assessment"]["must_haves"]["missing"] == ["aws"]
    assert out["assessment"]["summary"] == "Strong overlap."


def test_score_clamped_to_0_100():
    out = score._normalize_score({"score": 130, "assessment": _assessment()})
    assert out["score"] == 100
    out2 = score._normalize_score({"score": -5, "assessment": _assessment()})
    assert out2["score"] == 0


def test_assessment_lists_and_notes_coerced_to_defaults():
    # The scorecard's verdicts are required, but its keyword lists / notes / summary
    # coerce to empty when the model omits them (lenient — they only feed the UI).
    card = {"score": 50, "assessment": {
        "seniority": {"verdict": "match"}, "domain": {"verdict": "adjacent"},
        "must_haves": {}, "nice_to_haves": {}, "summary": None}}
    out = score._normalize_score(card)
    a = out["assessment"]
    assert a["seniority"] == {"verdict": "match", "note": ""}
    assert a["must_haves"] == {"met": [], "missing": []}
    assert a["nice_to_haves"] == {"missing": []}
    assert a["summary"] == ""


def test_absent_score_key_raises_not_silently_zero():
    # A scorer result without "score" must NOT be buried as a real 0.
    with pytest.raises(score.ScoreError):
        score._normalize_score({"assessment": _assessment()})


def test_missing_or_malformed_assessment_raises():
    # The scorecard is required and its verdicts must be in-enum — a missing assessment
    # or a bogus verdict fails loudly (the per-dimension verdicts drive ranking + audit).
    with pytest.raises(score.ScoreError):
        score._normalize_score({"score": 80})
    bad = {"score": 80, "assessment": {
        "seniority": {"verdict": "kinda"}, "domain": {"verdict": "match"},
        "must_haves": {"met": [], "missing": []}, "nice_to_haves": {"missing": []},
        "summary": ""}}
    with pytest.raises(score.ScoreError):
        score._normalize_score(bad)


def test_non_numeric_score_raises_score_error():
    with pytest.raises(score.ScoreError):
        score._normalize_score({"score": "high"})


def test_float_and_string_scores_accepted():
    out = score._normalize_score({"score": 85.7, "assessment": _assessment()})
    assert out["score"] == 86                                 # rounded
    out2 = score._normalize_score({"score": "72", "assessment": _assessment()})
    assert out2["score"] == 72


def test_assessment_keyword_coercion_tolerates_bare_string_and_nesting():
    card = {"score": 50, "assessment": {
        "seniority": {"verdict": "match"}, "domain": {"verdict": "match"},
        "must_haves": {"met": "python", "missing": [["aws", "k8s"]]},
        "nice_to_haves": {"missing": []}, "summary": ""}}
    out = score._normalize_score(card)
    assert out["assessment"]["must_haves"]["met"] == ["python"]
    assert out["assessment"]["must_haves"]["missing"] == ["aws", "k8s"]


def test_screen_posting_disqualifies_without_calling_fit():
    # screen_posting is the standalone SCREEN half: no score_fit parameter exists on
    # it at all, so it structurally cannot pay for a fit call — pipeline.run_score is
    # what gates on `disqualified` before ever calling the injected fit_fn.
    http = FakeHttp(json.dumps({"screen": {"clearance": {"requires_clearance": True}}}))
    out = score.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "none"}, num_ctx=8192)
    assert out["disqualified"] is True
    assert "screen" in out
    assert out["disqualification_reason"] == "clearance: requires security clearance"


def test_screen_parse_failure_falls_back_to_scored_not_screened():
    # A garbled SCREEN response must NOT discard the posting: the design errs toward
    # keep on garbled extraction — not disqualified, and the screen verdict is empty.
    http = FakeHttp("this is not json {{{")
    out = score.screen_posting(
        POSTING, extract=_ollama(http),
        candidate={"highest_degree": "Master's"},
    )
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert out["screen"] == {}
    assert len(http.calls) == 1                    # the (failed) SCREEN call


# --- extract seam: the injected extract(prompt, schema) -> dict callable -

def test_screen_posting_uses_injected_extract():
    # The screen's only backend-specific step is "give me JSON from this prompt".
    seen = {}

    def extract(prompt, schema):
        seen["prompt"] = prompt
        return {"screen": {"clearance": {"requires_clearance": True}}}

    out = score.screen_posting(CLEARED_POSTING, extract=extract,
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "clearance: requires security clearance"
    assert "=== JOB:" in seen["prompt"]


def test_screen_posting_without_extract_runs_deterministic_gates_only():
    # SCREEN_BACKEND=none: no LLM call, but the intern/location gates still fire.
    posting = dict(POSTING, job_title="Software Engineering Intern")
    out = score.screen_posting(posting, extract=None,
                               candidate={"exclude_internships": True,
                                          "security_clearance": "none"})
    assert out["disqualified"] is True
    assert "internship" in out["disqualification_reason"]


def test_extract_failure_errs_toward_keep():
    # A broken provider must NEVER discard the queue.
    def extract(prompt, schema):
        raise score.ScoreError("provider down")

    out = score.screen_posting(POSTING, extract=extract,
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert out["screen"] == {}


def test_extract_failure_is_flagged_provider_error():
    # Keeping the posting is right for ONE flaky call; it is wrong to then pay to
    # fit-score it as though it had been screened. The verdict carries the fact, so
    # the caller can tell "screened and clean" from "never actually screened".
    def extract(prompt, schema):
        raise score.ScoreError("provider down")

    out = score.screen_posting(POSTING, extract=extract,
                               candidate={"highest_degree": "Master's"})
    assert out["provider_error"] is True


def test_working_extract_sets_no_provider_error():
    out = score.screen_posting(POSTING, extract=lambda p, s: {"screen": {}},
                               candidate={"highest_degree": "Master's"})
    assert "provider_error" not in out


def test_screen_backend_none_is_not_a_provider_error():
    # SCREEN_BACKEND=none has no provider to fail: the deterministic gates run alone
    # and the row is legitimately scored, exactly as documented. It must not be
    # mistaken for an outage.
    out = score.screen_posting(POSTING, extract=None,
                               candidate={"highest_degree": "Master's"})
    assert "provider_error" not in out


def test_provider_error_still_honours_the_deterministic_gates():
    # The location/intern gates are CODE, cost nothing, and ran fine. A provider
    # outage must not resurrect a posting they correctly disqualified.
    def extract(prompt, schema):
        raise score.ScoreError("provider down")

    out = score.screen_posting({**POSTING, "location": "Shanghai, China"},
                               extract=extract,
                               candidate={"highest_degree": "Master's",
                                          "locations": ["remote", "USA"]})
    assert out["provider_error"] is True
    assert out["disqualified"] is True          # deterministic gate still wins


# --- determinism / Ollama options ----------------------------------------

def test_screen_request_sends_deterministic_options():
    http = FakeHttp(_screen_resp({}))
    score.screen_posting(POSTING, extract=_ollama(http, seed=7, num_ctx=4096),
                         num_ctx=4096, candidate={"highest_degree": "Master's"})
    opts = http.calls[0][1]["json"]["options"]
    assert opts["temperature"] == 0          # deterministic by default
    assert opts["seed"] == 7
    assert opts["num_ctx"] == 4096


# --- structured identity renders constraint clauses ----------------------

def test_structured_candidate_renders_extraction_clauses_in_screen_call():
    # locations is deliberately omitted: it's a code gate now (resolve_location off
    # posting["location"]), so it renders no extraction clause in the SCREEN prompt.
    http = FakeHttp(json.dumps({"screen": {}}))
    # The authorization clause only renders when CODE retrieved something to classify,
    # so the JD has to mention sponsorship for all three clauses to appear.
    posting = dict(POSTING, description="We need Python. We cannot sponsor visas.")
    score.screen_posting(
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
        out = score.screen_posting(POSTING, extract=_ollama(http),
                                   candidate=candidate)
        assert len(http.calls) == 0, candidate
        assert out["disqualified"] is False, candidate


# --- screen: extracted facts + code gates --------------------------------

def _screen_resp(screen):
    return json.dumps({"screen": screen})


# location: gated in CODE off posting["location"] (pycountry), not the LLM screen
def test_foreign_location_disqualifies_from_board_string():
    posting = {**POSTING, "location": "Shanghai, China"}
    out = score.screen_posting(posting, extract=_ollama(FakeHttp()),
                               candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "location: on-site in China"
    assert out["screen"]["location"]["pass"] is False


def test_us_state_only_location_kept():
    posting = {**POSTING, "location": "New York, New York"}
    out = score.screen_posting(posting, extract=_ollama(FakeHttp()),
                               candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False
    assert out["screen"]["location"]["pass"] is True


def test_locations_only_candidate_makes_no_ollama_call():
    posting = {**POSTING, "location": "Sydney, Australia"}
    http = FakeHttp()
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"locations": ["remote", "USA"]})
    assert len(http.calls) == 0                               # location needs no LLM
    assert out["disqualified"] is True


def test_missing_board_location_is_kept():
    posting = {**POSTING, "location": None}
    out = score.screen_posting(posting, extract=_ollama(FakeHttp()),
                               candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False                       # err toward keep


def test_deterministic_screen_flags_intern_and_location():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    posting = {"job_title": "Data Science Intern", "location": "Shanghai, China"}
    out = score.deterministic_screen(
        base, posting, {"exclude_internships": True, "locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert out["screen"]["internships"]["pass"] is False
    assert out["screen"]["location"]["pass"] is False
    assert "internship/co-op role" in out["disqualification_reason"]
    assert "location: on-site in China" in out["disqualification_reason"]


def test_deterministic_screen_passes_clean_row():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    posting = {"job_title": "Software Engineer", "location": "New York, New York"}
    out = score.deterministic_screen(base, posting, {"locations": ["remote", "USA"]})
    assert out["disqualified"] is False


def test_deterministic_screen_noop_without_candidate():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    out = score.deterministic_screen(base, {"job_title": "Intern"}, None)
    assert out == {"screen": {}, "disqualified": False, "disqualification_reason": ""}


# degree: the LLM extracts which levels the posting NAMES plus a required/preferred
# bool; CODE takes the lowest rank and compares. The legacy single-`required_degree`
# shape below is the fit scorer's Stage 4 block, still read for the fallback path.
def test_higher_required_degree_disqualifies():
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is True
    assert "degree" in out["disqualification_reason"]


def test_lower_or_no_required_degree_passes():
    for req in ("bachelor's", "none", ""):
        http = FakeHttp(_screen_resp({"degree": {"required_degree": req}}))
        out = score.screen_posting(POSTING, extract=_ollama(http),
                                   candidate={"highest_degree": "Master's"})
        assert out["disqualified"] is False, req


def _degree_screen(levels, required, cand="Master's"):
    http = FakeHttp(_screen_resp(
        {"degree": {"degree_levels": levels, "degree_required": required}}))
    return score.screen_posting(POSTING, extract=_ollama(http),
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
        out = score.screen._screen_verdict({"screen": {"degree": entry}}, cand, "JD")
        assert "degree" not in out["screen"], entry
    # "no degree required" needs no levels — it is a real answer, not a gap.
    out = score.screen._screen_verdict(
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
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


def test_citizen_never_fails_authorization():
    http = FakeHttp(_screen_resp({"authorization": {"no_sponsorship_quote": "We do not sponsor."}}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
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
        out = score.screen_posting(posting, extract=_ollama(http),
                                   candidate={"work_authorization": "needs visa sponsorship"})
        assert out["disqualified"] is False, desc


def test_authorization_fails_only_on_explicit_no_sponsorship_phrase():
    # D1: an explicit floor phrase disqualifies even with no quote from the model — the
    # floor, not model trust, decides here.
    posting = {**POSTING, "description": "Strong team. This position offers no visa sponsorship."}
    http = FakeHttp(_screen_resp({"authorization": {}}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


# clearance: LLM extracts requires_clearance, code checks — and CODE also requires the
# JD to actually SAY so (the evidence floor; see the CLEARANCE_TOKENS block below).
def test_clearance_required_disqualifies():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True


def test_clearance_not_required_passes():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": False}}))
    out = score.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is False


# --- the clearance evidence floor (defect found 2026-07-27) ---------------
# `requires_clearance` is a bare boolean from a 4B model. Acting on it unguarded made
# 20 of 24 live discards wrong: the model reads "security" (the engineering domain) as
# the government credential. CODE now requires a clearance token in the JD or title.

def test_ungrounded_clearance_claim_keeps_the_posting():
    # THE DEFECT, pinned. Every one of the 20 wrong discards looked exactly like this:
    # "security" all over the JD, `requires_clearance: true`, and not one clearance word.
    posting = dict(POSTING, job_title="Senior Security Researcher",
                   description=("Join our security team. You will work on Azure "
                                "security, application security reviews, and secure "
                                "coding practices across the platform."))
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is False
    assert out["screen"]["clearance"]["pass"] is True


def test_clearance_grounded_in_the_title_alone_disqualifies():
    # Evidence is title OR description: the two grounded `degree` discards the same
    # 2026-07-27 query found state their bar in the title and nowhere else, so the
    # clearance floor reads both rather than the description only.
    posting = dict(POSTING, job_title="TS/SCI Cleared Systems Engineer")
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "clearance: requires security clearance"


@pytest.mark.parametrize("text", [
    "You will join our data science team and ship models.",
    "BS in Computer Science or equivalent experience required.",
    "Our Chief Scientist leads the research group.",
])
def test_science_words_do_not_ground_a_clearance_claim(text):
    # The `sci` trap: a bare `sci` token would match science/scientist/Science and
    # re-open the exact false-discard direction this floor exists to close. The set
    # spells the abbreviation as `ts/sci`, so these three keep.
    posting = dict(POSTING, description=text)
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is False


def test_fallback_screen_clearance_also_needs_evidence():
    # The fit scorer's Stage 4 extraction routes through the SAME _screen_verdict, so
    # it must not become a back door around the floor. Ungrounded -> kept.
    empty = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"clearance": {"requires_clearance": True}}}
    out = score.merge_fallback_screen(empty, card, POSTING,
                                      {"security_clearance": "none"})
    assert out["disqualified"] is False


# internships/co-op: decided deterministically from the title via the
# exclude_internships flag (a structured constraint), not by the 4B model.
def test_exclude_internships_disqualifies_intern_title():
    posting = {**POSTING, "job_title": "Software Engineer Intern"}
    http = FakeHttp(_screen_resp({}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"exclude_internships": True})
    assert out["disqualified"] is True
    assert "internship/co-op role" in out["disqualification_reason"]


def test_exclude_internships_passes_non_intern_title():
    http = FakeHttp(_screen_resp({}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"exclude_internships": True})
    assert out["disqualified"] is False


def test_intern_title_not_excluded_without_the_flag():
    # No exclude_internships -> an intern title is not auto-disqualified.
    posting = {**POSTING, "job_title": "Software Engineer Intern"}
    http = FakeHttp(_screen_resp({}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


def test_exclude_internships_only_makes_no_screen_call():
    # The flag is deterministic (title-only), so a candidate that sets ONLY it does
    # not trigger a SCREEN Ollama call.
    posting = {**POSTING, "job_title": "Backend Intern"}
    http = FakeHttp()
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"exclude_internships": True})
    assert len(http.calls) == 0
    assert out["disqualified"] is True


def test_is_internship_whole_word_matching():
    # Real intern/co-op titles match; "internal"/"international" must not.
    assert score._is_internship("Software Engineer Intern")
    assert score._is_internship("2026 Summer Internship")
    assert score._is_internship("Data Science Co-op")
    assert not score._is_internship("Internal Tools Engineer")
    assert not score._is_internship("International Sales Lead")


def test_skill_gap_and_unknown_keys_do_not_disqualify():
    # An invented key (skills) is ignored; a passing configured gate doesn't fail.
    http = FakeHttp(_screen_resp({"skills": {"pass": False, "note": "no C++"},
                                  "degree": {"required_degree": "bachelor's"}}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert "skills" not in out["screen"]


def test_unconfigured_requirement_is_not_checked():
    # Candidate sets only degree; a stray clearance extraction must be ignored.
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True},
                                  "degree": {"required_degree": "bachelor's"}}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert "clearance" not in out["screen"]


# --- transport failure (SCREEN call) --------------------------------------

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
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert out["screen"] == {}


# --- the core safety invariant: empty/garbled extraction never disqualifies --

@pytest.mark.parametrize("gate,candidate", [
    ("degree", {"highest_degree": "Master's"}),
    ("authorization", {"work_authorization": "needs visa sponsorship"}),
    ("clearance", {"security_clearance": "none"}),
])
def test_empty_extraction_per_gate_never_disqualifies(gate, candidate):
    # Each gate is CONFIGURED, but the model returns an empty fact for it. The
    # design never discards on absent data, so disqualified must be False.
    http = FakeHttp(_screen_resp({gate: {}}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate=candidate)
    assert out["disqualified"] is False, gate


def test_non_dict_gate_entry_is_treated_as_empty():
    # A garbled (non-dict) extraction for a configured gate must not crash or fail.
    http = FakeHttp(_screen_resp({"degree": "nonsense"}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


# --- numeric boundaries (off-by-one mutation killers) --------------------

def test_equal_required_degree_passes_pinning_greater_than():
    # required == candidate (master's) must PASS — pins `>` (not `>=`) in the gate.
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "master's"}}))
    out = score.screen_posting(POSTING, extract=_ollama(http),
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


# --- authorization negation + clearance holder ----------------------------

def test_candidate_not_needing_sponsorship_passes_even_if_jd_says_no():
    posting = {**POSTING, "description": "We do not offer visa sponsorship."}
    http = FakeHttp(_screen_resp(
        {"authorization": {"no_sponsorship_quote": "We do not offer visa sponsorship."}}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "no sponsorship needed"})
    assert out["disqualified"] is False


def test_candidate_holding_clearance_passes_when_role_requires_one():
    # CLEARED_POSTING so the evidence floor is SATISFIED — this pins the holder
    # short-circuit, not the floor keeping an ungrounded row by accident.
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.screen_posting(CLEARED_POSTING, extract=_ollama(http),
                               candidate={"security_clearance": "Secret"})
    assert out["disqualified"] is False


# --- multi-gate failure reason join --------------------------------------

# --- sponsorship: CODE retrieves, MODEL labels, CODE decides -------------
#
# Rewritten 2026-07-28 with the check itself. The old block tested a quote the MODEL
# retrieved and CODE classified with three regex vetoes; both halves were on the wrong
# side. There is no quote to verify any more — the model labels text the code handed it,
# so hallucination is impossible by construction rather than by an ex-post check.

_NEEDS_VISA = {"work_authorization": "needs visa sponsorship"}


def _screen_labels(labels, description):
    """Screen `description` with the model returning `labels`, one per retrieved snippet."""
    http = FakeHttp(json.dumps({"screen": {"authorization": {"sponsorship_labels": labels}}}))
    posting = dict(POSTING, description=description)
    return score.screen_posting(posting, extract=_ollama(http), candidate=_NEEDS_VISA)


def _sponsor_jd(sentence):
    return f"About the role. {sentence} Apply now."


# --- retrieval (the half that is now deterministic) ----------------------

def test_snippets_are_the_sponsor_sentence_plus_one_neighbour_each_side():
    jd = ("We build trading systems. The team is small. "
          "We do not offer visa sponsorship. You will own your work. Apply today.")
    snips = score.sponsorship_snippets(jd)
    assert len(snips) == 1
    assert snips[0] == ("The team is small. We do not offer visa sponsorship. "
                        "You will own your work.")


def test_a_bare_sentence_would_lose_its_antecedent_so_the_window_carries_it():
    # The reason the window is +/-1 and not the sentence alone: "Sponsorship is not
    # among them" is unlabelable without the sentence before it.
    jd = "We offer relocation and a signing bonus. Sponsorship is not among them."
    assert score.sponsorship_snippets(jd) == [
        "We offer relocation and a signing bonus. Sponsorship is not among them."]


def test_a_jd_that_never_says_sponsor_yields_no_snippets():
    # No snippets means no clause in the prompt and nothing to classify — the check
    # simply does not run, which is why silence keeps.
    assert score.sponsorship_snippets(
        "A normal job description with no mention of immigration status.") == []


def test_one_snippet_per_sponsor_sentence_even_when_they_are_adjacent():
    # NOT merged, deliberately. The label is about the CENTRE sentence, so merging two
    # hits forces one answer for both — and an earlier version of this function did
    # exactly that, which made live IMC rows 465/490 come back `refuses` on a paragraph
    # that refuses three named nationalities AND offers sponsorship to Ukrainians.
    # Repeating a shared neighbour costs a few hundred prompt chars; merging cost a job.
    assert score.sponsorship_snippets(
        "Intro. We sponsor visas. We also sponsor conferences. Outro.") == [
        "Intro. We sponsor visas. We also sponsor conferences.",
        "We sponsor visas. We also sponsor conferences. Outro."]
    jd = ("We sponsor a robotics team. " + "Filler sentence. " * 5
          + "We cannot sponsor work visas. We are hiring now.")
    snips = score.sponsorship_snippets(jd)
    assert len(snips) == 2
    assert "robotics" in snips[0] and "work visas" in snips[1]


def test_a_scoped_refusal_beside_an_offer_keeps_the_posting():
    # The shape that forced per-sentence snippets, reduced from IMC ids 465/490.
    jd = ("Apply today. We are unable to obtain sponsorship for candidates from certain "
          "countries. If you hold a biometric passport we can obtain sponsorship for you. "
          "Contact recruitment.")
    snips = score.sponsorship_snippets(jd)
    assert len(snips) == 2
    assert _screen_labels(["refuses", "offers"], jd)["disqualified"] is False


def test_the_abbreviation_trap_pr22_sprang_does_not_split_early():
    # PR #22's splitter stripped the dot from any single-letter token, merging
    # "based in the U.S. Citizenship is not required" into a fake citizenship bar.
    # Under this design a mis-split only widens the window — the model still reads the
    # words — but the guard is cheap and the case is a real posting.
    sents = score._sentences("Roles are based in the U.S. Sponsorship is not required. Apply.")
    assert sents[0] == "Roles are based in the U.S. Sponsorship is not required."


# --- the decision rule (the half CODE keeps) -----------------------------

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
    assert len(score.sponsorship_snippets(jd)) == 2
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
    assert _screen_labels(["refuses"] * len(score.sponsorship_snippets(hard)),
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
    assert len(score.sponsorship_snippets(jd)) == 2
    assert "without sponsorship" in jd                    # the floor WOULD match
    assert _screen_labels(["neither"], jd)["disqualified"] is False   # 1 label, 2 snippets
    assert _screen_labels(["yes", "yes"], jd)["disqualified"] is False  # off-vocabulary


def test_hallucination_cannot_disqualify_because_the_model_supplies_no_text():
    # THE security property, now structural. The model returns a label over a snippet
    # CODE retrieved; there is no channel for invented text to reach the decision.
    jd = "Great role. We welcome applicants from all backgrounds."
    assert score.sponsorship_snippets(jd) == []          # nothing retrieved...
    assert _screen_labels(["refuses"], jd)["disqualified"] is False   # ...so nothing to act on


# --- the closed-list floor -----------------------------------------------

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
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "citizen"})
    assert out["disqualified"] is False


def test_the_authorization_clause_is_omitted_when_nothing_was_retrieved():
    # No snippets -> no clause -> the model is never asked a question about text that is
    # not there. But the VERDICT is still recorded, so merge_fallback_screen sees no gap
    # and the fit scorer never gets a second vote on a disqualification (SPEC §7.1).
    http = FakeHttp(_screen_resp({}))
    posting = dict(POSTING, description="A normal JD with no mention of immigration.")
    out = score.screen_posting(posting, extract=_ollama(http),
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
    out = score.screen_posting(posting, extract=lambda p, s: pytest.fail("no call"),
                               candidate=_NEEDS_VISA)
    assert out["screen"]["authorization"]["pass"] is True
    assert out["disqualified"] is False
    # ...and the floor still stands on that no-call path.
    blunt = dict(POSTING, description="This employer does not sponsor work visas.")
    out = score.screen_posting(blunt, extract=None, candidate=_NEEDS_VISA)
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "authorization: no visa sponsorship offered"


def test_the_retrieved_snippets_are_numbered_into_the_prompt():
    http = FakeHttp(_screen_resp({}))
    posting = dict(POSTING, description=_sponsor_jd("We will not sponsor visas."))
    score.screen_posting(posting, extract=_ollama(http), candidate=_NEEDS_VISA)
    prompt = http.calls[0][1]["json"]["prompt"]
    assert "sponsorship_labels" in prompt
    assert "1. About the role. We will not sponsor visas. Apply now." in prompt


# --- the corpus, repointed at what this design actually decides ----------

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
        n = len(score.sponsorship_snippets(jd))
        if n and _screen_labels(["refuses"] * n, jd)["disqualified"]:
            leaked.append(q)
    # The off-topic and EEO shapes are no longer code's problem — they carry no `sponsor`
    # token, or the model labels them `neither`. What must still hold is that a genuine
    # OFFER can never be turned into a discard by a mislabel.
    offers = [q for q in _corpus()["must_keep"] if score._offers_sponsorship(q.lower())]
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
    retrievable = [q for q in flag if score.sponsorship_snippets(_sponsor_jd(q))]
    missed = [q for q in flag if q not in retrievable]
    assert len(retrievable) == 6 and len(missed) == 7, (
        f"the recall trade moved: {len(retrievable)} retrievable, {len(missed)} missed\n"
        + "\n".join(missed))
    # Every retrievable one must actually disqualify when the model labels it refuses.
    not_flagged = [q for q in retrievable
                   if not _screen_labels(["refuses"], _sponsor_jd(q))["disqualified"]]
    assert not not_flagged, "retrieved but not disqualified:\n" + "\n".join(not_flagged)


def test_multiple_failing_gates_join_reasons():
    posting = {**POSTING, "location": "Singapore"}
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"highest_degree": "Master's", "locations": ["USA"]})
    assert out["disqualified"] is True
    reason = out["disqualification_reason"]
    assert "degree" in reason and "location" in reason
    assert "; " in reason  # joined, not a single failure


# --- pure-function units (precise coercion coverage) ---------------------

@pytest.mark.parametrize("value", ["true", "yes", "1", "required", "TRUE", 1, True, 2.5])
def test_flag_truthy_tokens(value):
    assert score._flag(value) is True


@pytest.mark.parametrize("value", ["no", "false", "maybe", "", None, 0, False, "remote"])
def test_flag_falsy_tokens(value):
    assert score._flag(value) is False


@pytest.mark.parametrize("text,rank", [
    ("none", 0), ("no degree", 0), ("", 0),
    ("High School Diploma", 1), ("GED", 1),
    ("Associate", 2), ("Bachelor's or higher", 3),
    ("Master's", 4), ("PhD", 5), ("Doctorate", 5),
])
def test_degree_rank_ladder(text, rank):
    assert score._degree_rank(text) == rank


@pytest.mark.parametrize("auth,needs", [
    ("needs visa sponsorship", True),
    ("requires sponsorship", True),
    ("no sponsorship needed", False),
    ("without sponsorship", False),
    ("US citizen", False),
    ("permanent resident", False),
])
def test_needs_sponsorship(auth, needs):
    assert score._needs_sponsorship(auth) is needs


def test_truncate_boundary_and_disabled():
    assert score._truncate("abcde", 5) == "abcde"          # exact length: not cut
    assert "truncated" in score._truncate("abcdef", 5)     # one over: cut
    assert score._truncate("abcdef", 0) == "abcdef"        # max_chars<=0: disabled


# --- resolve_location: deterministic country gate over the board location string ---

@pytest.mark.parametrize("location,allowed,want_keep,want_note", [
    ("Shanghai, China", ["remote", "USA"], False, "on-site in China"),
    ("Amsterdam, North Holland, Netherlands", ["remote", "USA"], False, "on-site in Netherlands"),
    ("Sydney, Australia", ["remote", "USA"], False, "on-site in Australia"),
    ("London, England, United Kingdom", ["remote", "USA"], False, "on-site in United Kingdom"),
    ("Chicago, Illinois, United States", ["remote", "USA"], True, ""),
    ("New York, New York", ["remote", "USA"], True, ""),
    ("Austin, TX", ["remote", "USA"], True, ""),              # state code
    ("Atlanta, Georgia", ["remote", "USA"], True, ""),        # GA state vs GE country collision
    ("Toronto, Ontario", ["remote", "USA"], True, ""),        # subdivision, not a country -> keep (accepted leak)
    ("Remote - US", ["remote", "USA"], True, "remote"),
    ("", ["remote", "USA"], True, ""),                        # missing -> keep
    (None, ["remote", "USA"], True, ""),
    ("London, England, United Kingdom", ["New York"], False, "on-site in United Kingdom"),
    ("New York, New York", ["New York"], True, ""),           # city-restricted keeps its city
    ("Chicago, IL", ["New York"], True, ""),                  # US postal code, not Israel
    ("Sacramento, CA", ["New York"], True, ""),               # CA=California, not Canada
    ("London - United Kingdom", ["remote", "USA"], False, "on-site in United Kingdom"),  # space-dash separator
    ("Paris – France", ["remote", "USA"], False, "on-site in France"),                    # en-dash separator
    ("Winston-Salem, NC", ["remote", "USA"], True, ""),       # bare hyphen is NOT a separator
    # --- D2 repros: resolve EVERY token (city→country via geonamescache), not the last ---
    ("New York City, London, Singapore", ["remote", "USA"], True, ""),         # id=1009: NYC is US -> keep
    ("London", ["remote", "USA"], False, "on-site in United Kingdom"),         # id=324: bare foreign city -> discard
    ("Hanoi OR Ho Chi Minh City", ["remote", "USA"], False, "on-site in Viet Nam"),  # id=1071: 'OR' split + both VN
    ("London, Montreal, Singapore", ["remote", "USA"], False, "on-site in United Kingdom"),  # id=885: all foreign
    ("San Jose", ["remote", "USA"], True, ""),               # ambiguous name, US the largest match -> keep
    # --- D8 repros: an UNRESOLVED region token must not let a city token decide alone.
    # 'ON' is in no gazetteer (only US subdivisions are), so 'London, ON' used to be
    # judged by 'London'->GB — a false discard whose reason named the wrong country.
    ("London, ON", ["Canada", "USA", "remote"], True, ""),    # id=D8: Canadian London kept
    ("Tokyo, Japan", ["Canada", "USA", "remote"], False, "on-site in Japan"),  # both resolve -> still discard
    ("Toronto, ON", ["Canada", "USA", "remote"], True, ""),   # unchanged: Toronto->CA, allowed
    ("London, Ontario", ["Canada", "USA", "remote"], True, ""),  # unchanged: Ontario reads US, kept
    ("Hyderabad, TS", ["Canada", "USA", "remote"], True, ""), # accepted miss: lone city, region unresolved
])
def test_resolve_location(location, allowed, want_keep, want_note):
    passed, note = score.resolve_location(location, allowed)
    assert passed is want_keep, (location, allowed)
    assert note == want_note, (location, allowed)


def test_token_country_resolves_states_countries_and_cities():
    assert score._token_country("London") == "GB"          # foreign city (no US namesake)
    assert score._token_country("New York City") == "US"    # US city
    assert score._token_country("Chicago") == "US"
    assert score._token_country("CA") == "US"               # US state code, NOT Canada
    assert score._token_country("Georgia") == "US"          # US state, NOT the country
    assert score._token_country("China") == "CN"            # country name
    assert score._token_country("Nowhereville") is None     # unresolved


# --- real adapter: import safety ------------------------------------------

def test_make_claude_scorer_builds_without_importing_sdk():
    # The adapter must be import-safe: building it never imports anthropic (which
    # the hermetic test env lacks), so run.py can construct it before first use.
    fit = score.make_claude_scorer("sk-test", "claude-sonnet-4-6")
    assert callable(fit)


def test_job_block_omits_location_for_the_fit_score_call():
    # D5: the fit SCORE call drops the Location line so geography can't leak into the
    # fit number (location is decided by the screen gate, not the score); the SCREEN
    # call keeps it (default).
    posting = {**POSTING, "location": "Chicago, IL"}
    assert "Location: Chicago, IL" in score._job_block(posting, 0)                 # screen (default)
    assert "Location:" not in score._job_block(posting, 0, include_location=False)  # score


# --- prompts: split into score.txt (Claude) + screen.txt (Ollama) ---------

def test_prompts_split_into_two_files_without_location_clause():
    from ats_worker import prompts
    assert "hiring manager" in prompts.SCORE_HEADER.lower()      # score.txt
    assert "recruiter" in prompts.SCREEN_HEADER.lower()          # screen.txt
    assert prompts.SCORE_C_DEGREE and prompts.SCREEN_FOOTER
    assert not hasattr(prompts, "SCORE_C_LOCATION")              # location clause gone
    assert "recommended_resume" in prompts.SCORE_HEADER       # multi-resume rubric
    assert "PERSONAL PROFILE" in prompts.SCORE_HEADER         # profile block described


# --- multi-resume: schema + system-prefix helpers ---------------------------

def test_score_schema_single_resume_matches_today():
    schema = score._score_schema(["resume"])
    assert "recommended_resume" not in schema["properties"]
    assert "recommended_resume" not in schema["required"]


def test_score_schema_multi_resume_adds_enum_field():
    schema = score._score_schema(["quant_dev", "swe"])
    assert schema["properties"]["recommended_resume"] == {
        "type": "string", "enum": ["quant_dev", "swe"]}
    assert "recommended_resume" in schema["required"]
    # the base schema must stay pristine (deep-copied, not mutated)
    assert "recommended_resume" not in score._SCORE_SCHEMA["properties"]
    assert "recommended_resume" not in score._SCORE_SCHEMA["required"]


def _strict_mode_violations(node, path="$"):
    """Every object in a schema sent to OpenAI structured output must list EVERY key of
    `properties` in `required`, or the API rejects the whole request with a 400
    (invalid_json_schema) before the model runs. Yields the offenders."""
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
        # The other half of the contract, and it raises the identical 400: strict mode
        # requires additionalProperties:false on every object, not just `required`.
        if node.get("additionalProperties") is not False:
            yield f"{path}: object without additionalProperties: false"
    for key, value in node.items():
        yield from _strict_mode_violations(value, f"{path}.{key}")


def test_schema_is_strict_mode_valid():
    # The defect this pins cost a whole eval run: 66dfb65's `screen` block had
    # `properties` and no `required`, so EVERY codex fit call 400'd -- the scorer was
    # not degraded, it was dead, and only the ollama path (non-strict) still worked.
    # SCREEN_SCHEMA carried the same defect on its own code path.
    # aliased: a module-level test mirror shares this name, and hoisting the
    # import would silently make the mirror test compare production to itself.
    from ats_worker.score.backends_codex import _batch_schema as prod_batch_schema
    from ats_worker.score.prompts import SCREEN_SCHEMA
    # _batch_schema is what actually reaches `codex exec --output-schema`; the bare
    # _score_schema never does. Checking only the latter would pass while a violation
    # introduced into the `results` envelope 400s in production.
    for name, schema in (("_batch_schema", prod_batch_schema(["resume"])),
                         ("_score_schema", score._score_schema(["resume"])),
                         ("SCREEN_SCHEMA", SCREEN_SCHEMA)):
        bad = list(_strict_mode_violations(schema, name))
        assert not bad, "strict-mode violations:\n" + "\n".join(bad)


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
        out = score.screen._screen_verdict(data, cand, "JD text")
        assert "degree" not in out["screen"], f"blind degree materialized for {blank!r}"
        assert "clearance" not in out["screen"]
        assert out["disqualified"] is False

    # A real answer still materializes -- including `False`, which is a fact, not a gap.
    out = score.screen._screen_verdict(
        {"screen": {"degree": {"required_degree": "phd"},
                    "clearance": {"requires_clearance": False}}}, cand, "JD text")
    assert out["screen"]["clearance"]["pass"] is True
    assert out["screen"]["degree"]["pass"] is False   # bachelors < phd
    assert out["disqualified"] is True


def test_score_schema_carries_enum_constrained_assessment():
    # S2.1: the scorecard replaces the flat reasoning/keyword fields; verdicts are
    # enum-constrained so structured outputs enforce them.
    schema = score._score_schema(["resume"])
    # `screen` is in `required` because strict structured output has no optional keys —
    # see test_schema_is_strict_mode_valid. Its VALUE is nullable, which is what keeps
    # "a scorer with nothing to say must not fail the card" true.
    assert schema["required"] == ["assessment", "score", "insufficient_context", "screen"]
    assert schema["properties"]["insufficient_context"] == {"type": "boolean"}
    for gone in ("reasoning", "matched_keywords", "missing_keywords"):
        assert gone not in schema["properties"]
    a = schema["properties"]["assessment"]
    assert set(a["required"]) == {"seniority", "domain", "must_haves", "nice_to_haves", "summary"}
    assert a["properties"]["seniority"]["properties"]["verdict"]["enum"] == \
        ["match", "too_junior", "too_senior"]
    assert a["properties"]["domain"]["properties"]["verdict"]["enum"] == \
        ["match", "adjacent", "mismatch"]


def test_scorer_system_blocks_layout_and_cache_control():
    blocks = score._scorer_system_blocks(
        {"quant_dev": "QD text", "swe": "SWE text"}, "profile text")
    texts = [b["text"] for b in blocks]
    assert texts[0].startswith("You are a hiring manager")     # SCORE_HEADER first
    assert texts[1] == "=== PERSONAL PROFILE ===\nprofile text"
    assert texts[2] == "=== RESUME (quant_dev) ===\nQD text"   # dict order preserved
    assert texts[3] == "=== RESUME (swe) ===\nSWE text"
    # cache_control on the LAST block only — caches the whole byte-identical prefix
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in b for b in blocks[:-1])


def test_scorer_system_blocks_empty_profile_omitted():
    blocks = score._scorer_system_blocks({"resume": "text"}, "")
    assert len(blocks) == 2                                    # header + one resume
    assert blocks[1]["text"] == "=== RESUME (resume) ===\ntext"


def test_recommended_resume_passed_through_normalization():
    out = score._normalize_score(
        {"score": 80, "assessment": _assessment(), "recommended_resume": "swe"})
    assert out["recommended_resume"] == "swe"


def test_insufficient_context_normalized_true():
    out = score._normalize_score(
        {"score": 40, "assessment": _assessment(), "insufficient_context": True})
    assert out["insufficient_context"] is True


def test_insufficient_context_absent_defaults_false():
    out = score._normalize_score({"score": 40, "assessment": _assessment()})
    assert out["insufficient_context"] is False   # absent -> False (err toward scoreable)


def test_recommended_resume_absent_or_blank_is_omitted():
    out = score._normalize_score({"score": 80, "assessment": _assessment()})
    assert "recommended_resume" not in out
    out2 = score._normalize_score(
        {"score": 80, "assessment": _assessment(), "recommended_resume": "   "})
    assert "recommended_resume" not in out2


def test_make_claude_scorer_accepts_profile_kwarg():
    # Still import-safe (no anthropic at build time), now with a baked-in profile.
    fit = score.make_claude_scorer("sk-test", "claude-sonnet-5", profile="prefers quant")
    assert callable(fit)


# --- codex scorer: the ChatGPT-subscription twin (no network; subprocess mocked) ---

# The raw scorecard fields codex returns for ONE job (pre-job_ref shape); the fake
# CLI below wraps it in the batched {"results": [{"job_ref": ..., **payload}]}
# envelope the real (post-B1) CLI is asked for.
CODEX_PAYLOAD = {"assessment": {}, "score": 71, "insufficient_context": False}


def _fake_codex(payload=CODEX_PAYLOAD, job_ref=1, returncode=0, capture=None):
    """Stand in for `codex exec`: writes a single-result batch envelope,
    {"results": [{"job_ref": job_ref, **payload}]}, to the --output-last-message path
    the scorer passed — exactly the shape the real batched CLI returns for a
    one-posting call."""
    def run(cmd, **kwargs):
        if capture is not None:
            capture["cmd"] = cmd
            capture["prompt"] = kwargs.get("input", "")
            # Read the schema HERE — the scorer's TemporaryDirectory is gone by the
            # time the test body runs.
            with open(cmd[cmd.index("--output-schema") + 1], encoding="utf-8") as fh:
                capture["schema"] = json.load(fh)
        if returncode == 0:
            out = cmd[cmd.index("--output-last-message") + 1]
            with open(out, "w", encoding="utf-8") as fh:
                json.dump({"results": [{"job_ref": job_ref, **payload}]}, fh)
        return Mock(returncode=returncode, stdout="boom", stderr="")
    return run


def _batch_schema(labels: list) -> dict:
    """Mirror of make_codex_scorer's internal schema wrap (the per-element
    `_score_schema` plus an integer job_ref, wrapped in a results array) — used to
    assert on the schema the scorer hands to --output-schema."""
    element = json.loads(json.dumps(score._score_schema(labels)))
    element["properties"]["job_ref"] = {"type": "integer"}
    element["required"].append("job_ref")
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": element}},
        "required": ["results"],
        "additionalProperties": False,
    }


def test_codex_scorer_parses_the_output_file(monkeypatch):
    # The CLI writes its final message to --output-last-message; the scorer realigns
    # by job_ref and returns the parsed element (still carrying job_ref) verbatim
    # (score._normalize_score normalizes it later), same contract as Claude, just
    # batched — one scorecard per input posting, in input order.
    monkeypatch.setattr(score.subprocess, "run", _fake_codex())
    fit = score.make_codex_scorer("gpt-5.6-sol")
    got = fit([{**POSTING, "id": 1}], {"swe": "resume text"})
    assert got == [{"job_ref": 1, **CODEX_PAYLOAD}]


def test_codex_batch_size_one_matches_single_call_scorecard(monkeypatch):
    # batch_size=1 equivalence: a one-posting batch's scorecard fields are identical
    # to what today's single-call adapter produced — only the job_ref tag is new.
    monkeypatch.setattr(score.subprocess, "run", _fake_codex())
    [got] = score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}], {"swe": "resume text"})
    assert got["score"] == CODEX_PAYLOAD["score"]
    assert got["assessment"] == CODEX_PAYLOAD["assessment"]
    assert got["insufficient_context"] == CODEX_PAYLOAD["insufficient_context"]


def test_codex_scorer_sends_schema_and_prompt_without_location(monkeypatch):
    # The per-element schema handed to --output-schema must be the SAME shape Claude
    # gets (so the two backends are comparable) plus the job_ref tag, and the prompt
    # must carry the résumé but not the Location line (D5 — geography must not move
    # the fit score) — and must carry the job_ref tag for realignment.
    seen: dict = {}
    monkeypatch.setattr(score.subprocess, "run", _fake_codex(capture=seen))
    fit = score.make_codex_scorer("gpt-5.6-sol", profile="prefers quant")
    fit([{**POSTING, "location": "Chicago, IL", "id": 1}],
        {"swe": "resume text", "quant_dev": "q"})

    assert seen["schema"] == _batch_schema(["swe", "quant_dev"])
    assert "prefers quant" in seen["prompt"]
    assert "resume text" in seen["prompt"]
    assert "Location: Chicago, IL" not in seen["prompt"]
    assert "job_ref=1" in seen["prompt"]
    assert "--ephemeral" in seen["cmd"]  # a 640-row pass must not litter session files


def test_codex_scorer_runs_tool_less(monkeypatch):
    # SECURITY: a JD is untrusted scraped text and plain `codex exec` holds a shell that
    # --sandbox read-only still lets read ANY file (~/.codex/auth.json, .env) — so the
    # tools must be REMOVED, not merely discouraged. web_search defaults ON; off here too.
    seen: dict = {}
    monkeypatch.setattr(score.subprocess, "run", _fake_codex(capture=seen))
    score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}], {"swe": "r"})
    cmd = seen["cmd"]
    assert cmd[cmd.index("--disable") + 1] == "shell_tool"
    assert 'web_search="disabled"' in cmd


def test_codex_scorer_pins_effort_and_verbosity(monkeypatch):
    # Both MUST be sent explicitly: codex's default reasoning level is server-controlled
    # (models_cache.json is etag-fetched) and was seen flipping low->medium->low, which
    # would change scoring behavior mid-batch with no code change. Pinning is the defense.
    seen: dict = {}
    monkeypatch.setattr(score.subprocess, "run", _fake_codex(capture=seen))
    score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}], {"swe": "r"})
    assert "model_reasoning_effort=low" in seen["cmd"]
    assert "model_verbosity=low" in seen["cmd"]


def test_codex_scorer_raises_on_nonzero_exit_never_a_zero_score(monkeypatch):
    # A dead cron (e.g. codex purged auth.json) must fail the posting LOUDLY — a
    # swallowed error would silently score the whole queue 0 and look like a real pass.
    monkeypatch.setattr(score.subprocess, "run", _fake_codex(returncode=1))
    fit = score.make_codex_scorer("gpt-5.6-sol")
    with pytest.raises(score.ScoreError, match="exit 1"):
        fit([{**POSTING, "id": 1}], {"swe": "resume text"})


def test_codex_scorer_raises_when_output_is_not_json(monkeypatch):
    def run(cmd, **kwargs):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("I couldn't score this.")
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    fit = score.make_codex_scorer("gpt-5.6-sol")
    with pytest.raises(score.ScoreError, match="non-JSON"):
        fit([{**POSTING, "id": 1}], {"swe": "resume text"})


def test_codex_batch_duplicate_job_ref_raises(monkeypatch):
    # Two results claiming the SAME job_ref is exactly the misalignment the guard
    # exists to catch — it must fail the WHOLE batch loudly rather than silently
    # pick one and pair a score with the wrong job.
    def run(cmd, **kw):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w") as fh:
            json.dump({"results": [
                {"job_ref": 1, "score": 80, "assessment": {}, "insufficient_context": False},
                {"job_ref": 1, "score": 10, "assessment": {}, "insufficient_context": False}]}, fh)
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    with pytest.raises(score.ScoreError, match="job_ref"):
        score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}], {"swe": "r"})


def test_codex_batch_unknown_job_ref_raises(monkeypatch):
    # A job_ref that names no input posting must also fail the whole batch — it's
    # exactly as unsafe to trust as a missing or duplicate one.
    def run(cmd, **kw):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w") as fh:
            json.dump({"results": [
                {"job_ref": 1, "score": 80, "assessment": {}, "insufficient_context": False},
                {"job_ref": 99, "score": 10, "assessment": {}, "insufficient_context": False}]}, fh)
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    with pytest.raises(score.ScoreError, match="job_ref"):
        score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}], {"swe": "r"})


def test_both_backends_share_one_prompt_prefix():
    # The shared sections are what keep a prompt edit landing on both backends; if
    # these drift, a Claude-vs-codex band comparison is measuring the prompt, not the model.
    resumes = {"swe": "resume text"}
    sections = score._scorer_system_sections(resumes, "prefers quant")
    blocks = score._scorer_system_blocks(resumes, "prefers quant")
    assert [b["text"] for b in blocks] == sections


# --- B1: fit scorer is batch-first (list in, list out) --------------------

def test_codex_batch_returns_one_scorecard_per_posting_in_order(monkeypatch):
    def run(cmd, **kw):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w") as fh:
            json.dump({"results": [
                {"job_ref": 2, "score": 40, "assessment": {}, "insufficient_context": False},
                {"job_ref": 1, "score": 80, "assessment": {}, "insufficient_context": False}]}, fh)
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    fit = score.make_codex_scorer("gpt-5.6-sol")
    got = fit([{**POSTING, "id": 1}, {**POSTING, "id": 2}], {"swe": "r"})
    assert [g["score"] for g in got] == [80, 40]          # realigned by job_ref, input order


def test_codex_batch_missing_job_ref_raises(monkeypatch):
    def run(cmd, **kw):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w") as fh:
            json.dump({"results": [{"job_ref": 1, "score": 80, "assessment": {}, "insufficient_context": False}]}, fh)
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    with pytest.raises(score.ScoreError, match="job_ref"):
        score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}, {**POSTING, "id": 2}], {"swe": "r"})


# --- codex quota-usage capture (usage_path + _capture_usage, rollout-based) -------

def _rollout_line(used, window, resets, secondary=None, plan="plus"):
    """One codex session-rollout event carrying a rate_limits record (the rollout is
    the ONLY place codex records it — `--json` stdout does not; see _capture_usage)."""
    rl = {"limit_id": "codex", "plan_type": plan,
          "primary": {"used_percent": used, "window_minutes": window, "resets_at": resets},
          "secondary": secondary}
    return json.dumps({"type": "event_msg", "payload": {"rate_limits": rl}})


def _fake_sessions(monkeypatch, tmp_path):
    sess = tmp_path / "sessions"
    sess.mkdir(exist_ok=True)
    monkeypatch.setattr(score.usage, "_sessions_dir", lambda: str(sess))
    return sess


def _write_rollout(sess, lines, name="rollout-x.jsonl"):
    p = sess / name
    p.write_text("\n".join(lines))
    return p


def test_capture_usage_reads_rollout_and_deletes_it(tmp_path, monkeypatch):
    sess = _fake_sessions(monkeypatch, tmp_path)
    roll = _write_rollout(sess, [json.dumps({"type": "other"}),
                                 _rollout_line(32.0, 10080, 1784839672)])
    path = str(tmp_path / "codex_usage.json")
    score._capture_usage(path, since_mtime=0.0)
    snap = json.loads((tmp_path / "codex_usage.json").read_text())
    assert snap["plan_type"] == "plus"
    assert snap["limits"] == [
        {"key": "primary", "used_percent": 32.0, "window_minutes": 10080, "resets_at": 1784839672}]
    assert not roll.exists()                                 # rollout deleted after capture
    # atomic write leaves no tmp behind, whatever its (now per-call-unique) name
    assert not list(tmp_path.glob("codex_usage.json*.tmp"))


def test_capture_usage_latest_line_wins_and_includes_secondary(tmp_path, monkeypatch):
    sess = _fake_sessions(monkeypatch, tmp_path)
    secondary = {"used_percent": 5.0, "window_minutes": 300, "resets_at": 111}
    _write_rollout(sess, [_rollout_line(10.0, 10080, 1),                        # stale
                          _rollout_line(40.0, 10080, 2, secondary=secondary)])  # freshest wins
    path = str(tmp_path / "u.json")
    score._capture_usage(path, 0.0)
    by_key = {l["key"]: l for l in json.loads((tmp_path / "u.json").read_text())["limits"]}
    assert by_key["primary"]["used_percent"] == 40.0
    assert by_key["secondary"]["window_minutes"] == 300


def test_capture_usage_ignores_rollouts_older_than_since_mtime(tmp_path, monkeypatch):
    import os
    sess = _fake_sessions(monkeypatch, tmp_path)
    old = _write_rollout(sess, [_rollout_line(99.0, 10080, 1)])
    os.utime(old, (1000, 1000))                          # stamp it in the past
    path = str(tmp_path / "u.json")
    score._capture_usage(path, since_mtime=5000.0)       # cutoff newer than the rollout
    assert not (tmp_path / "u.json").exists()            # nothing new -> no snapshot
    assert old.exists()                                  # a pre-existing rollout is NOT deleted


def test_capture_usage_no_rollout_never_raises(tmp_path, monkeypatch):
    sess = _fake_sessions(monkeypatch, tmp_path)
    score._capture_usage(str(tmp_path / "none.json"), 0.0)   # empty sessions dir
    assert not (tmp_path / "none.json").exists()
    # an unwritable snapshot path must also be swallowed, never raised
    _write_rollout(sess, [_rollout_line(1.0, 1, 1)])
    score._capture_usage("/nonexistent-dir/deep/none.json", 0.0)


def test_codex_scorer_captures_usage_and_drops_ephemeral(monkeypatch, tmp_path):
    sess = _fake_sessions(monkeypatch, tmp_path)
    usage = str(tmp_path / "codex_usage.json")
    seen = {}
    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"results": [{"job_ref": 1, **CODEX_PAYLOAD}]}, fh)
        _write_rollout(sess, [_rollout_line(32.0, 10080, 999)])  # codex's rollout for this call
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    score.make_codex_scorer("gpt-5.6-sol", usage_path=usage)([{**POSTING, "id": 1}], {"swe": "r"})
    assert "--ephemeral" not in seen["cmd"]  # capturing -> rollout must be written, not suppressed
    assert "--json" not in seen["cmd"]
    written = json.loads((tmp_path / "codex_usage.json").read_text())
    assert written["limits"][0]["used_percent"] == 32.0
    assert not (sess / "rollout-x.jsonl").exists()  # rollout cleaned up after capture


def test_codex_scorer_keeps_ephemeral_without_usage_path(monkeypatch):
    # The eval/test path (no usage_path) keeps --ephemeral, its exact gated call.
    seen = {}
    monkeypatch.setattr(score.subprocess, "run", _fake_codex(capture=seen))
    score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}], {"swe": "r"})
    assert "--ephemeral" in seen["cmd"]
    assert "--json" not in seen["cmd"]


def test_capture_usage_skips_delete_when_concurrent_rollout_present(tmp_path, monkeypatch):
    sess = _fake_sessions(monkeypatch, tmp_path)
    ours = _write_rollout(sess, [_rollout_line(32.0, 10080, 1)], name="rollout-a.jsonl")
    theirs = _write_rollout(sess, [_rollout_line(5.0, 300, 2)], name="rollout-b.jsonl")
    score._capture_usage(str(tmp_path / "u.json"), since_mtime=0.0)
    assert ours.exists() and theirs.exists()   # ambiguous -> delete nothing


def test_codex_scorer_cleans_rollout_on_failure(monkeypatch, tmp_path):
    sess = _fake_sessions(monkeypatch, tmp_path)
    def run(cmd, **kw):
        _write_rollout(sess, [_rollout_line(1.0, 1, 1)])   # rollout written, then fail
        return Mock(returncode=1, stdout="boom", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    with pytest.raises(score.ScoreError):
        score.make_codex_scorer("gpt-5.6-sol", usage_path=str(tmp_path / "u.json"))(
            [{**POSTING, "id": 1}], {"swe": "r"})
    assert not (sess / "rollout-x.jsonl").exists()   # résumé prompt not left on disk


# --- scorer fallback screen check ----------------------------------------

def test_fallback_screen_used_when_screen_produced_nothing():
    # SCREEN_BACKEND=none: the screen has no verdict, so the scorer's extraction is
    # the ONLY check. It must be consumed.
    empty = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"clearance": {"requires_clearance": True}}}
    out = score.merge_fallback_screen(empty, card, CLEARED_POSTING,
                                      {"security_clearance": "none"})
    assert out["disqualified"] is True


def test_fallback_screen_ignored_when_screen_already_ruled():
    # On a working backend the screen wins. A second independent checker would double
    # the false-positive surface, and a spurious "requires PhD" silently discards a
    # good posting — the exact failure err-toward-keep exists to avoid.
    ruled = {"screen": {"clearance": {"pass": True, "note": ""}},
             "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"clearance": {"requires_clearance": True}}}
    out = score.merge_fallback_screen(ruled, card, POSTING,
                                      {"security_clearance": "none"})
    assert out["disqualified"] is False


def test_fallback_sponsorship_quote_is_verified_too():
    empty = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"authorization": {"no_sponsorship_quote": "We never sponsor."}}}
    posting = dict(POSTING, description="A perfectly normal JD.")
    out = score.merge_fallback_screen(empty, card, posting,
                                      {"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is False   # hallucinated quote -> keep, same as the screen


def test_fallback_screen_returns_untouched_when_screen_already_disqualified():
    # A screen that already disqualified has nothing left to gap-fill — and must not
    # be handed to _screen_verdict at all, whose recompute could produce a different
    # (or emptied) reason. This is the function's own guard, independent of any
    # caller precondition.
    screen = {"screen": {"degree": {"pass": False, "note": "requires master's"}},
              "disqualified": True, "disqualification_reason": "degree: requires master's"}
    card = {"screen": {"clearance": {"requires_clearance": True}}}
    out = score.merge_fallback_screen(screen, card, POSTING,
                                      {"highest_degree": "Bachelor's", "security_clearance": "none"})
    assert out is screen or out == screen
    assert out["screen"]["degree"] == {"pass": False, "note": "requires master's"}
    assert out["disqualified"] is True


def test_fallback_screen_fills_a_check_the_screen_returned_no_data_for():
    # The screen RAN but the model returned nothing for `degree`. gate() used to
    # materialize degree{pass:True} anyway (each _check_* errs toward pass on absent
    # data), making a ran-but-blind check byte-identical to a genuinely-passed one --
    # so merge_fallback_screen's `k not in already` gap test could never see it, and
    # the fallback only ever reached a whole-backend absence.
    candidate = {"highest_degree": "Bachelor's", "work_authorization": "citizen",
                 "security_clearance": "none"}
    screen = score.screen_posting(POSTING, candidate=candidate,
                                  extract=lambda p, s: {"screen": {"authorization": {}}})
    card = {"screen": {"degree": {"required_degree": "phd"}}}
    out = score.merge_fallback_screen(screen, card, POSTING, candidate)
    assert out["disqualified"] is True
    assert out["screen"]["degree"]["pass"] is False


def test_authorization_still_ruled_when_the_model_returns_no_entry():
    # The carve-out: unlike degree/clearance, authorization has an independent signal
    # (NO_SPONSOR_PHRASES over the JD), so it produces a real verdict with no model
    # data and must keep writing its key.
    posting = dict(POSTING, description="We do not sponsor work visas.")
    out = score.screen_posting(posting, extract=lambda p, s: {"screen": {}},
                               candidate={"work_authorization": "needs visa sponsorship"})
    assert out["screen"]["authorization"]["pass"] is False
    assert out["disqualified"] is True


def test_fallback_screen_preserves_already_ruled_nongap_check():
    # clearance is already ruled (a distinctive note the recompute would not produce);
    # degree is the only genuine gap. The ruled clearance entry must survive verbatim
    # -- not be overwritten by _screen_verdict's recomputation of the whole card,
    # which would evaluate clearance too (candidate holds no clearance -> requires
    # clearance -> {"pass": False, ...}, an entirely different verdict from the
    # marker below).
    screen = {"screen": {"clearance": {"pass": True, "note": "MARKER-not-recomputed"}},
              "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"clearance": {"requires_clearance": True},
                       "degree": {"required_degree": "phd"}}}
    out = score.merge_fallback_screen(screen, card, POSTING,
                                      {"security_clearance": "none", "highest_degree": "Bachelor's"})
    assert out["screen"]["clearance"] == {"pass": True, "note": "MARKER-not-recomputed"}
    assert "degree" in out["screen"]   # the real gap was filled
    assert out["screen"]["degree"]["pass"] is False   # PhD required, candidate holds Bachelor's
