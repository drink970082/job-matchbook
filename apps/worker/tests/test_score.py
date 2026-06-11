"""TDD for Ollama-backed JD/resume scoring. No real network (injected http)."""
from __future__ import annotations

import json

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

    score_posting makes up to two calls per posting: SCORE first, then SCREEN
    (only when a candidate is configured). Pass one response (reused for every
    call) or several (call 1 = SCORE, call 2 = SCREEN, ...).
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return FakeResponse({"response": self._responses[idx]})


POSTING = {
    "job_title": "Senior Python Engineer",
    "company_name": "Acme",
    "description": "We need Python, Django, and AWS experience.",
}
RESUME = "Experienced Python and Django developer."
# A valid SCORE-call response, for tests that focus on the SCREEN call (which is
# the second call, so the first must return a usable score).
SCORE_OK = json.dumps({"score": 60, "matched_keywords": [], "missing_keywords": [],
                       "reasoning": "ok"})


def test_happy_path_returns_normalized_dict():
    inner = json.dumps({
        "score": 88,
        "matched_keywords": ["python", "django"],
        "missing_keywords": ["aws"],
        "reasoning": "Strong overlap.",
    })
    http = FakeHttp(inner)
    out = score.score_posting(
        POSTING, RESUME, model="llama3", http=http, ollama_host="http://ollama:11434"
    )
    assert out["score"] == 88
    assert out["matched_keywords"] == ["python", "django"]
    assert out["missing_keywords"] == ["aws"]
    assert out["reasoning"] == "Strong overlap."
    # Verify it hit the right endpoint with json format + no streaming.
    url, kwargs = http.calls[0]
    assert url == "http://ollama:11434/api/generate"
    body = kwargs["json"]
    assert body["format"] == "json"
    assert body["stream"] is False
    assert body["model"] == "llama3"
    # Thinking must be off, else reasoning models leave `response` empty.
    assert body["think"] is False
    # prompt embeds the resume and the JD text
    assert RESUME in body["prompt"]
    assert "Django" in body["prompt"]


def test_score_clamped_to_0_100():
    http = FakeHttp(json.dumps({"score": 130}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")
    assert out["score"] == 100
    http2 = FakeHttp(json.dumps({"score": -5}))
    out2 = score.score_posting(POSTING, RESUME, model="m", http=http2, ollama_host="h")
    assert out2["score"] == 0


def test_missing_keys_coerced_to_defaults():
    http = FakeHttp(json.dumps({"score": 50}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")
    assert out["matched_keywords"] == []
    assert out["missing_keywords"] == []
    assert out["reasoning"] == ""


def test_malformed_inner_json_raises_score_error():
    http = FakeHttp("this is not json {{{")
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


def test_non_numeric_score_raises_score_error():
    http = FakeHttp(json.dumps({"score": "high"}))
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


def test_absent_score_key_raises_not_silently_zero():
    # A model that returns valid JSON but omits "score" must NOT be buried as a
    # real 0 (below threshold, never tailored, indistinguishable from a true 0).
    http = FakeHttp(json.dumps({"matched_keywords": ["python"], "reasoning": "ok"}))
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


def test_candidate_screen_call_disqualifies_and_omits_resume():
    http = FakeHttp(
        SCORE_OK,
        json.dumps({"screen": {"dealbreakers": {"pass": False, "note": "requires a PhD"}}}),
    )
    out = score.score_posting(
        POSTING, RESUME, model="m", http=http, ollama_host="h",
        candidate={"dealbreakers": ["requires a PhD"]},
    )
    assert out["score"] == 60                       # from the SCORE call
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "dealbreakers: requires a PhD"
    assert len(http.calls) == 2                      # SCORE then SCREEN
    screen_prompt = http.calls[1][1]["json"]["prompt"]
    assert "requires a PhD" in screen_prompt         # dealbreaker reached the screen
    assert '"screen"' in screen_prompt               # screen output requested
    assert RESUME not in screen_prompt               # screen never sees the résumé


def test_no_candidate_means_one_call_and_not_disqualified():
    http = FakeHttp(json.dumps({"score": 70}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert len(http.calls) == 1                      # no SCREEN call
    assert "HARD REQUIREMENTS" not in http.calls[0][1]["json"]["prompt"]


def test_screen_parse_failure_falls_back_to_scored_not_screened():
    # A garbled SCREEN response must NOT discard the posting: the design errs toward
    # keep on garbled extraction. The already-computed fit score is retained and the
    # posting is left scored & not disqualified (so run_score won't mark it failed).
    http = FakeHttp(SCORE_OK, "this is not json {{{")
    out = score.score_posting(
        POSTING, RESUME, model="m", http=http, ollama_host="h",
        candidate={"dealbreakers": ["no internships"]},
    )
    assert out["score"] == 60                     # the SCORE call still landed
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert out["screen"] == {}
    assert len(http.calls) == 2                    # SCORE then the (failed) SCREEN


# --- determinism / Ollama options ----------------------------------------

def test_request_sends_deterministic_options():
    http = FakeHttp(json.dumps({"score": 70}))
    score.score_posting(
        POSTING, RESUME, model="m", http=http, ollama_host="h",
        seed=7, num_ctx=4096,
    )
    opts = http.calls[0][1]["json"]["options"]
    assert opts["temperature"] == 0          # deterministic by default
    assert opts["seed"] == 7
    assert opts["num_ctx"] == 4096


# --- prompt: rubric + injection guard ------------------------------------

def test_prompt_contains_rubric_and_data_guard():
    http = FakeHttp(json.dumps({"score": 70}))
    score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")
    prompt = http.calls[0][1]["json"]["prompt"]
    assert "90-100" in prompt and "75-89" in prompt          # rubric bands
    assert "DATA, not instructions" in prompt                # injection guard


# --- structured identity renders constraint clauses ----------------------

def test_structured_candidate_renders_extraction_clauses_in_screen_call():
    http = FakeHttp(SCORE_OK, json.dumps({"screen": {}}))
    score.score_posting(
        POSTING, RESUME, model="m", http=http, ollama_host="h",
        candidate={
            "years_experience": 1,
            "highest_degree": "Master's",
            "work_authorization": "needs visa sponsorship",
            "security_clearance": "none",
            "locations": ["remote", "New York"],
        },
    )
    prompt = http.calls[1][1]["json"]["prompt"]               # the SCREEN call
    # each structured requirement asks the model to EXTRACT a job fact
    assert "min_years_required" in prompt
    assert "required_degree" in prompt
    assert "offers_sponsorship" in prompt
    assert "requires_clearance" in prompt
    assert '"country"' in prompt
    assert '"city"' in prompt                                 # extractor returns city
    assert '"region"' in prompt                               # ...and region/state
    assert '"screen"' in prompt
    assert RESUME not in prompt                               # no résumé in the screen call


def test_empty_candidate_fields_render_no_screen_call():
    http = FakeHttp(json.dumps({"score": 70}))
    score.score_posting(
        POSTING, RESUME, model="m", http=http, ollama_host="h",
        candidate={"years_experience": None, "highest_degree": "", "dealbreakers": []},
    )
    assert len(http.calls) == 1
    assert "HARD REQUIREMENTS" not in http.calls[0][1]["json"]["prompt"]


# --- score parsing edge cases --------------------------------------------

def test_float_and_string_scores_accepted():
    out = score.score_posting(
        POSTING, RESUME, model="m", http=FakeHttp(json.dumps({"score": 85.7})),
        ollama_host="h",
    )
    assert out["score"] == 86                                 # rounded
    out2 = score.score_posting(
        POSTING, RESUME, model="m", http=FakeHttp(json.dumps({"score": "72"})),
        ollama_host="h",
    )
    assert out2["score"] == 72


def test_keyword_coercion_tolerates_bare_string_and_nesting():
    inner = json.dumps({"score": 50, "matched_keywords": "python",
                        "missing_keywords": [["aws", "k8s"]]})
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(inner),
                              ollama_host="h")
    assert out["matched_keywords"] == ["python"]
    assert out["missing_keywords"] == ["aws", "k8s"]


# --- screen: extracted facts + code gates --------------------------------

def _screen_resp(screen):
    return json.dumps({"screen": screen})


# location: LLM extracts country/remote, code checks membership
def test_foreign_location_disqualifies():
    http = FakeHttp(SCORE_OK, _screen_resp({"location": {"country": "Singapore", "remote": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["score"] == 60                                 # from the SCORE call
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "location: on-site in Singapore"


def test_us_city_passes_location_via_extracted_country():
    # The core regression: an on-site US role must PASS against allowed "USA" — the
    # model extracts "United States", code normalises it to match "USA".
    http = FakeHttp(SCORE_OK, _screen_resp({"location": {"country": "United States", "remote": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False
    assert out["screen"]["location"]["pass"] is True


def test_remote_role_passes_location_when_jd_says_remote():
    posting = {**POSTING, "description": "This is a fully remote position."}
    http = FakeHttp(SCORE_OK, _screen_resp({"location": {"country": "Singapore", "remote": True}}))
    out = score.score_posting(posting, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False


def test_candidate_city_matches_city_field_and_keeps_role():
    # Candidate allows "New York"; an extracted city of "New York" must keep the
    # role even though the candidate token isn't a country.
    http = FakeHttp(SCORE_OK, _screen_resp(
        {"location": {"city": "New York", "region": "New York", "country": "United States",
                      "remote": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["New York"]})
    assert out["disqualified"] is False
    assert out["screen"]["location"]["pass"] is True


def test_candidate_city_discards_other_city():
    # Candidate allows only "New York"; a London role must be discarded — tokens
    # match against the posting's location fields, not loosely against everything.
    http = FakeHttp(SCORE_OK, _screen_resp(
        {"location": {"city": "London", "region": "England", "country": "United Kingdom",
                      "remote": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["New York"]})
    assert out["disqualified"] is True
    assert "location" in out["disqualification_reason"]


def test_candidate_country_still_matches_via_alias():
    # Country aliasing is preserved: "USA" still keeps a US role even when a
    # non-matching city is also extracted.
    http = FakeHttp(SCORE_OK, _screen_resp(
        {"location": {"city": "Austin", "region": "Texas", "country": "United States",
                      "remote": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["USA"]})
    assert out["disqualified"] is False


def test_remote_claim_ignored_when_jd_never_mentions_remote():
    # The model loves to mark on-site foreign roles remote=true; if the JD never
    # mentions remote, we don't trust it, so the foreign country fails.
    http = FakeHttp(SCORE_OK, _screen_resp({"location": {"country": "Singapore", "remote": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert "on-site in Singapore" in out["disqualification_reason"]


# degree: LLM extracts required_degree, code compares rank
def test_higher_required_degree_disqualifies():
    http = FakeHttp(SCORE_OK, _screen_resp({"degree": {"required_degree": "phd"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is True
    assert "degree" in out["disqualification_reason"]


def test_lower_or_no_required_degree_passes():
    for req in ("bachelor's", "none", ""):
        http = FakeHttp(SCORE_OK, _screen_resp({"degree": {"required_degree": req}}))
        out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                                  candidate={"highest_degree": "Master's"})
        assert out["disqualified"] is False, req


# experience: LLM extracts min_years_required + senior, code compares to candidate
def test_too_senior_experience_disqualifies():
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": 5, "senior": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is True
    assert "experience" in out["disqualification_reason"]


def test_modest_experience_passes():
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": 3, "senior": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is False


def test_senior_title_disqualifies_experience():
    # Early-career (years=1): a Senior title screens the candidate out.
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": None, "senior": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is True


def test_senior_title_does_not_disqualify_experienced_candidate():
    # An experienced candidate (years=8) is NOT screened out of a senior role just
    # because the title is senior — they plausibly qualify.
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": None, "senior": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 8})
    assert out["disqualified"] is False


def test_senior_title_does_not_disqualify_when_years_unknown():
    # Unknown candidate experience: a senior title alone must not disqualify (safe
    # direction — don't discard on absent data).
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": None, "senior": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": None, "highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert "experience" not in out["screen"]


# authorization: LLM extracts offers_sponsorship, code checks against candidate need
def test_no_sponsorship_disqualifies_when_jd_says_so():
    posting = {**POSTING, "description": "We do not offer visa sponsorship for this role."}
    http = FakeHttp(SCORE_OK, _screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(posting, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


def test_sponsorship_no_ignored_when_jd_silent():
    # The model invents "no" from silence; if the JD never mentions sponsorship/visa,
    # we don't trust it (treat as unknown -> pass).
    http = FakeHttp(SCORE_OK, _screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is False


def test_unknown_sponsorship_passes():
    http = FakeHttp(SCORE_OK, _screen_resp({"authorization": {"offers_sponsorship": "unknown"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is False


def test_citizen_never_fails_authorization():
    http = FakeHttp(SCORE_OK, _screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "US citizen"})
    assert out["disqualified"] is False


# clearance: LLM extracts requires_clearance, code checks
def test_clearance_required_disqualifies():
    http = FakeHttp(SCORE_OK, _screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"security_clearance": "none"})
    assert out["disqualified"] is True


def test_clearance_not_required_passes():
    http = FakeHttp(SCORE_OK, _screen_resp({"clearance": {"requires_clearance": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"security_clearance": "none"})
    assert out["disqualified"] is False


# dealbreakers: stays an LLM pass/fail
def test_dealbreaker_fail_disqualifies():
    http = FakeHttp(SCORE_OK, _screen_resp({"dealbreakers": {"pass": False, "note": "internship role"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"dealbreakers": ["no internships"]})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "dealbreakers: internship role"


def test_passed_fails_only_on_explicit_negative_token():
    # Fail ONLY on an explicit false/no/0; everything else (incl. None and any
    # unrecognized value) passes — the safe direction, matching the other gates.
    for ok in ("maybe", "", None, "pass", "yes", "true", 1, True):
        assert score._passed(ok) is True, repr(ok)
    for bad in ("no", "false", "0", False, 0):
        assert score._passed(bad) is False, repr(bad)


def test_unrecognized_dealbreaker_verdict_does_not_disqualify():
    # An LLM dealbreaker verdict that isn't a clean true/false (here "maybe") must
    # NOT disqualify — err toward keep on a garbled judgment.
    http = FakeHttp(SCORE_OK, _screen_resp({"dealbreakers": {"pass": "maybe", "note": "unclear"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"dealbreakers": ["no internships"]})
    assert out["disqualified"] is False


def test_skill_gap_and_unknown_keys_do_not_disqualify():
    # An invented key (skills) is ignored; a passing experience fact doesn't fail.
    http = FakeHttp(SCORE_OK, _screen_resp({"skills": {"pass": False, "note": "no C++"},
                                            "experience": {"min_years_required": 2, "senior": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is False
    assert "skills" not in out["screen"]


def test_unconfigured_requirement_is_not_checked():
    # Candidate sets only experience; a stray degree extraction must be ignored.
    http = FakeHttp(SCORE_OK, _screen_resp({"degree": {"required_degree": "phd"},
                                            "experience": {"min_years_required": 2, "senior": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is False
    assert "degree" not in out["screen"]


# --- context truncation guard --------------------------------------------

def test_long_description_is_truncated():
    big = "word " * 20000                                     # ~100k chars
    posting = {**POSTING, "description": big}
    http = FakeHttp(json.dumps({"score": 70}))
    score.score_posting(posting, RESUME, model="m", http=http, ollama_host="h",
                        num_ctx=2048)
    prompt = http.calls[0][1]["json"]["prompt"]
    assert "[description truncated to fit context]" in prompt
    assert len(prompt) < len(big)                             # actually shortened


def test_long_resume_is_truncated():
    # A huge résumé must not push the JD out of the context window — cap it too.
    big_resume = "skill " * 20000                             # ~120k chars
    http = FakeHttp(json.dumps({"score": 70}))
    score.score_posting(POSTING, big_resume, model="m", http=http, ollama_host="h",
                        num_ctx=2048)
    prompt = http.calls[0][1]["json"]["prompt"]
    assert "[resume truncated to fit context]" in prompt
    assert len(prompt) < len(big_resume)                     # actually shortened
    assert "Django" in prompt                                # JD still present


# --- transport / envelope failures (the realistic production failure modes) --

class _RawHttp:
    """Returns a RAW Ollama envelope (or raises) so the SCORE call's transport
    and envelope-parsing branches are exercised (FakeHttp always wraps in a valid
    {"response": ...} and never raises)."""

    def __init__(self, envelope=None, *, raise_exc=None):
        self._envelope = envelope
        self._raise_exc = raise_exc
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        raise_exc, env = self._raise_exc, self._envelope

        class _Resp:
            def raise_for_status(self):
                if raise_exc is not None:
                    raise raise_exc

            def json(self):
                return env

        return _Resp()


def test_raise_for_status_error_bubbles_up():
    http = _RawHttp(raise_exc=requests.HTTPError("ollama 500"))
    with pytest.raises(requests.HTTPError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


def test_envelope_missing_response_key_raises_score_error():
    http = _RawHttp({"done": True})  # no "response" -> inner "" -> unparseable
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


def test_envelope_not_a_dict_raises_score_error():
    http = _RawHttp("not an object")
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


def test_empty_completion_raises_score_error():
    http = _RawHttp({"response": ""})  # the empty-completion (think-mode) failure
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")


# --- the core safety invariant: empty/garbled extraction never disqualifies --

@pytest.mark.parametrize("gate,candidate", [
    ("experience", {"years_experience": 1}),
    ("degree", {"highest_degree": "Master's"}),
    ("authorization", {"work_authorization": "needs visa sponsorship"}),
    ("clearance", {"security_clearance": "none"}),
    ("location", {"locations": ["USA"]}),
])
def test_empty_extraction_per_gate_never_disqualifies(gate, candidate):
    # Each gate is CONFIGURED, but the model returns an empty fact for it. The
    # design never discards on absent data, so disqualified must be False.
    http = FakeHttp(SCORE_OK, _screen_resp({gate: {}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate=candidate)
    assert out["disqualified"] is False, gate


def test_non_dict_gate_entry_is_treated_as_empty():
    # A garbled (non-dict) extraction for a configured gate must not crash or fail.
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": "nonsense"}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is False


# --- numeric boundaries (off-by-one mutation killers) --------------------

@pytest.mark.parametrize("years,disq", [(4, True), (5, False)])
def test_senior_title_years_threshold_boundary(years, disq):
    # SENIOR_TITLE_MIN_YEARS = 5: below it a senior title disqualifies, at/above passes.
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"senior": True, "min_years_required": None}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": years})
    assert out["disqualified"] is disq


def test_experience_gap_of_three_passes_pinning_the_four_year_threshold():
    # gap = min_req - cand = 4 - 1 = 3, which is < 4, so it must PASS (pins `>= 4`).
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": 4, "senior": False}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is False


def test_equal_required_degree_passes_pinning_greater_than():
    # required == candidate (master's) must PASS — pins `>` (not `>=`) in the gate.
    http = FakeHttp(SCORE_OK, _screen_resp({"degree": {"required_degree": "master's"}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


# --- authorization negation + clearance holder ----------------------------

def test_candidate_not_needing_sponsorship_passes_even_if_jd_says_no():
    posting = {**POSTING, "description": "We do not offer visa sponsorship."}
    http = FakeHttp(SCORE_OK, _screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(posting, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "no sponsorship needed"})
    assert out["disqualified"] is False


def test_candidate_holding_clearance_passes_when_role_requires_one():
    http = FakeHttp(SCORE_OK, _screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"security_clearance": "Secret"})
    assert out["disqualified"] is False


# --- multi-gate failure reason join --------------------------------------

def test_multiple_failing_gates_join_reasons():
    http = FakeHttp(SCORE_OK, _screen_resp({
        "degree": {"required_degree": "phd"},
        "location": {"country": "Singapore", "remote": False},
    }))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's", "locations": ["USA"]})
    assert out["disqualified"] is True
    reason = out["disqualification_reason"]
    assert "degree" in reason and "location" in reason
    assert "; " in reason  # joined, not a single failure


# --- pure-function units (precise coercion coverage) ---------------------

@pytest.mark.parametrize("value", ["true", "yes", "1", "remote", "required", "TRUE", 1, True, 2.5])
def test_flag_truthy_tokens(value):
    assert score._flag(value) is True


@pytest.mark.parametrize("value", ["no", "false", "maybe", "", None, 0, False])
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
