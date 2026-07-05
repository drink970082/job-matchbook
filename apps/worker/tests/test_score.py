"""TDD for Ollama-backed JD/resume scoring. No real network (injected http)."""
from __future__ import annotations

import json
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

    score_posting makes at most ONE Ollama call per posting now: SCREEN (only
    when a candidate is configured) — the fit SCORE comes from the injected
    `score_fit` callable, not Ollama. Pass one response (reused for every call)
    or several if a test drives more than one call.
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


def _fit(score=60, matched=None, missing=None, reasoning="ok"):
    """A canned score_fit(posting, resume) callable for tests that focus on SCREEN."""
    payload = {"score": score, "matched_keywords": matched or [],
               "missing_keywords": missing or [], "reasoning": reasoning}
    return lambda posting, resume_text: dict(payload)


FIT = _fit()  # the common "score 60, no keywords" fit used by SCREEN-focused tests


# --- score_fit is called, its result normalized -------------------------

def test_score_fit_result_is_normalized_and_returned():
    got = {}

    def fit(posting, resume_text):
        got["posting"], got["resume"] = posting, resume_text
        return {"score": 88, "matched_keywords": ["python", "django"],
                "missing_keywords": ["aws"], "reasoning": "Strong overlap."}

    out = score.score_posting(POSTING, RESUME, score_fit=fit, model="m",
                              http=FakeHttp(), ollama_host="h")
    assert out["score"] == 88
    assert out["matched_keywords"] == ["python", "django"]
    assert out["missing_keywords"] == ["aws"]
    assert out["reasoning"] == "Strong overlap."
    assert got["posting"] is POSTING and got["resume"] == RESUME  # posting+resume handed to scorer


def test_score_clamped_to_0_100():
    out = score.score_posting(POSTING, RESUME, score_fit=_fit(130), model="m",
                              http=FakeHttp(), ollama_host="h")
    assert out["score"] == 100
    out2 = score.score_posting(POSTING, RESUME, score_fit=_fit(-5), model="m",
                               http=FakeHttp(), ollama_host="h")
    assert out2["score"] == 0


def test_missing_keys_coerced_to_defaults():
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                              score_fit=lambda p, r: {"score": 50})
    assert out["matched_keywords"] == []
    assert out["missing_keywords"] == []
    assert out["reasoning"] == ""


def test_absent_score_key_raises_not_silently_zero():
    # A scorer that returns a dict without "score" must NOT be buried as a real 0.
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=lambda p, r: {"matched_keywords": ["python"]})


def test_non_numeric_score_raises_score_error():
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=lambda p, r: {"score": "high"})


def test_float_and_string_scores_accepted():
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                              score_fit=lambda p, r: {"score": 85.7})
    assert out["score"] == 86                                 # rounded
    out2 = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                               score_fit=lambda p, r: {"score": "72"})
    assert out2["score"] == 72


def test_keyword_coercion_tolerates_bare_string_and_nesting():
    out = score.score_posting(
        POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
        score_fit=lambda p, r: {"score": 50, "matched_keywords": "python",
                                "missing_keywords": [["aws", "k8s"]]})
    assert out["matched_keywords"] == ["python"]
    assert out["missing_keywords"] == ["aws", "k8s"]


def test_score_fit_error_propagates_to_mark_failed():
    # A scorer failure must propagate out of score_posting so run_score marks the
    # posting failed (batch continues) — it must NOT be swallowed like a SCREEN error.
    def boom(posting, resume_text):
        raise score.ScoreError("claude parse failed")
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=boom)


def test_candidate_screen_call_disqualifies_and_omits_resume():
    http = FakeHttp(
        json.dumps({"screen": {"dealbreakers": {"pass": False, "note": "requires a PhD"}}}),
    )
    out = score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={"dealbreakers": ["requires a PhD"]},
    )
    assert out["score"] == 60                       # from score_fit (FIT -> 60)
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "dealbreakers: requires a PhD"
    assert len(http.calls) == 1                      # SCREEN is now the only Ollama call
    screen_prompt = http.calls[0][1]["json"]["prompt"]
    assert "requires a PhD" in screen_prompt         # dealbreaker reached the screen
    assert '"screen"' in screen_prompt               # screen output requested
    assert RESUME not in screen_prompt               # screen never sees the résumé


def test_no_candidate_means_one_call_and_not_disqualified():
    http = FakeHttp()
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h")
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert len(http.calls) == 0                      # no SCREEN call, no SCORE call (injected)


def test_screen_parse_failure_falls_back_to_scored_not_screened():
    # A garbled SCREEN response must NOT discard the posting: the design errs toward
    # keep on garbled extraction. The already-computed fit score is retained and the
    # posting is left scored & not disqualified (so run_score won't mark it failed).
    http = FakeHttp("this is not json {{{")
    out = score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={"dealbreakers": ["no internships"]},
    )
    assert out["score"] == 60                     # from score_fit (FIT -> 60)
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert out["screen"] == {}
    assert len(http.calls) == 1                    # the (failed) SCREEN call


# --- determinism / Ollama options ----------------------------------------

def test_screen_request_sends_deterministic_options():
    http = FakeHttp(_screen_resp({}))
    score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                        seed=7, num_ctx=4096, candidate={"highest_degree": "Master's"})
    opts = http.calls[0][1]["json"]["options"]
    assert opts["temperature"] == 0          # deterministic by default
    assert opts["seed"] == 7
    assert opts["num_ctx"] == 4096


# --- structured identity renders constraint clauses ----------------------

def test_structured_candidate_renders_extraction_clauses_in_screen_call():
    http = FakeHttp(json.dumps({"screen": {}}))
    score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={
            "highest_degree": "Master's",
            "work_authorization": "needs visa sponsorship",
            "security_clearance": "none",
            "locations": ["remote", "New York"],
        },
    )
    prompt = http.calls[0][1]["json"]["prompt"]                # the SCREEN call
    # each structured requirement asks the model to EXTRACT a job fact
    assert "required_degree" in prompt
    assert "offers_sponsorship" in prompt
    assert "requires_clearance" in prompt
    assert '"country"' in prompt
    assert '"city"' in prompt                                 # extractor returns city
    assert '"region"' in prompt                               # ...and region/state
    assert '"screen"' in prompt
    assert RESUME not in prompt                               # no résumé in the screen call


def test_empty_candidate_fields_render_no_screen_call():
    http = FakeHttp()
    score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={"years_experience": None, "highest_degree": "", "dealbreakers": []},
    )
    assert len(http.calls) == 0


# --- screen: extracted facts + code gates --------------------------------

def _screen_resp(screen):
    return json.dumps({"screen": screen})


# location: LLM extracts country/remote, code checks membership
def test_foreign_location_disqualifies():
    http = FakeHttp(_screen_resp({"location": {"country": "Singapore", "remote": False}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["score"] == 60                                 # from score_fit (FIT -> 60)
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "location: on-site in Singapore"


def test_us_city_passes_location_via_extracted_country():
    # The core regression: an on-site US role must PASS against allowed "USA" — the
    # model extracts "United States", code normalises it to match "USA".
    http = FakeHttp(_screen_resp({"location": {"country": "United States", "remote": False}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False
    assert out["screen"]["location"]["pass"] is True


def test_remote_role_passes_location_when_jd_says_remote():
    posting = {**POSTING, "description": "This is a fully remote position."}
    http = FakeHttp(_screen_resp({"location": {"country": "Singapore", "remote": True}}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False


def test_candidate_city_matches_city_field_and_keeps_role():
    # Candidate allows "New York"; an extracted city of "New York" must keep the
    # role even though the candidate token isn't a country.
    http = FakeHttp(_screen_resp(
        {"location": {"city": "New York", "region": "New York", "country": "United States",
                      "remote": False}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["New York"]})
    assert out["disqualified"] is False
    assert out["screen"]["location"]["pass"] is True


def test_candidate_city_discards_other_city():
    # Candidate allows only "New York"; a London role must be discarded — tokens
    # match against the posting's location fields, not loosely against everything.
    http = FakeHttp(_screen_resp(
        {"location": {"city": "London", "region": "England", "country": "United Kingdom",
                      "remote": False}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["New York"]})
    assert out["disqualified"] is True
    assert "location" in out["disqualification_reason"]


def test_candidate_country_still_matches_via_alias():
    # Country aliasing is preserved: "USA" still keeps a US role even when a
    # non-matching city is also extracted.
    http = FakeHttp(_screen_resp(
        {"location": {"city": "Austin", "region": "Texas", "country": "United States",
                      "remote": False}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["USA"]})
    assert out["disqualified"] is False


def test_remote_claim_ignored_when_jd_never_mentions_remote():
    # The model loves to mark on-site foreign roles remote=true; if the JD never
    # mentions remote, we don't trust it, so the foreign country fails.
    http = FakeHttp(_screen_resp({"location": {"country": "Singapore", "remote": True}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert "on-site in Singapore" in out["disqualification_reason"]


# degree: LLM extracts required_degree, code compares rank
def test_higher_required_degree_disqualifies():
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is True
    assert "degree" in out["disqualification_reason"]


def test_lower_or_no_required_degree_passes():
    for req in ("bachelor's", "none", ""):
        http = FakeHttp(_screen_resp({"degree": {"required_degree": req}}))
        out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                                  candidate={"highest_degree": "Master's"})
        assert out["disqualified"] is False, req


# authorization: LLM extracts offers_sponsorship, code checks against candidate need
def test_no_sponsorship_disqualifies_when_jd_says_so():
    posting = {**POSTING, "description": "We do not offer visa sponsorship for this role."}
    http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


def test_sponsorship_no_ignored_when_jd_silent():
    # The model invents "no" from silence; if the JD never mentions sponsorship/visa,
    # we don't trust it (treat as unknown -> pass).
    http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is False


def test_unknown_sponsorship_passes():
    http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "unknown"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is False


def test_citizen_never_fails_authorization():
    http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "US citizen"})
    assert out["disqualified"] is False


# clearance: LLM extracts requires_clearance, code checks
def test_clearance_required_disqualifies():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"security_clearance": "none"})
    assert out["disqualified"] is True


def test_clearance_not_required_passes():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": False}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"security_clearance": "none"})
    assert out["disqualified"] is False


# dealbreakers: stays an LLM pass/fail
def test_dealbreaker_fail_disqualifies():
    http = FakeHttp(_screen_resp({"dealbreakers": {"pass": False, "note": "internship role"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
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
    http = FakeHttp(_screen_resp({"dealbreakers": {"pass": "maybe", "note": "unclear"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"dealbreakers": ["no internships"]})
    assert out["disqualified"] is False


# internships/co-op: decided deterministically from the title via the
# exclude_internships flag (a structured constraint), not by the 4B model.
def test_exclude_internships_disqualifies_intern_title():
    posting = {**POSTING, "job_title": "Software Engineer Intern"}
    http = FakeHttp(_screen_resp({}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"exclude_internships": True})
    assert out["disqualified"] is True
    assert "internship/co-op role" in out["disqualification_reason"]


def test_exclude_internships_passes_non_intern_title():
    http = FakeHttp(_screen_resp({}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"exclude_internships": True})
    assert out["disqualified"] is False


def test_intern_title_not_excluded_without_the_flag():
    # No exclude_internships -> an intern title is not auto-disqualified.
    posting = {**POSTING, "job_title": "Software Engineer Intern"}
    http = FakeHttp(_screen_resp({}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is False


def test_exclude_internships_only_makes_no_screen_call():
    # The flag is deterministic (title-only), so a candidate that sets ONLY it does
    # not trigger a SCREEN Ollama call.
    posting = {**POSTING, "job_title": "Backend Intern"}
    http = FakeHttp()
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
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
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert "skills" not in out["screen"]


def test_unconfigured_requirement_is_not_checked():
    # Candidate sets only degree; a stray clearance extraction must be ignored.
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True},
                                  "degree": {"required_degree": "bachelor's"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
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


def test_screen_http_error_bubbles_up():
    # A transport error on the SCREEN Ollama call propagates (marks the posting
    # failed -> retried), unlike a *parse* failure which is swallowed toward keep.
    http = _raw_http(raise_exc=requests.HTTPError("ollama 500"))
    with pytest.raises(requests.HTTPError):
        score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http,
                            ollama_host="h", candidate={"highest_degree": "Master's"})


# --- the core safety invariant: empty/garbled extraction never disqualifies --

@pytest.mark.parametrize("gate,candidate", [
    ("degree", {"highest_degree": "Master's"}),
    ("authorization", {"work_authorization": "needs visa sponsorship"}),
    ("clearance", {"security_clearance": "none"}),
    ("location", {"locations": ["USA"]}),
])
def test_empty_extraction_per_gate_never_disqualifies(gate, candidate):
    # Each gate is CONFIGURED, but the model returns an empty fact for it. The
    # design never discards on absent data, so disqualified must be False.
    http = FakeHttp(_screen_resp({gate: {}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate=candidate)
    assert out["disqualified"] is False, gate


def test_non_dict_gate_entry_is_treated_as_empty():
    # A garbled (non-dict) extraction for a configured gate must not crash or fail.
    http = FakeHttp(_screen_resp({"degree": "nonsense"}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


# --- numeric boundaries (off-by-one mutation killers) --------------------

def test_equal_required_degree_passes_pinning_greater_than():
    # required == candidate (master's) must PASS — pins `>` (not `>=`) in the gate.
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "master's"}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False


# --- authorization negation + clearance holder ----------------------------

def test_candidate_not_needing_sponsorship_passes_even_if_jd_says_no():
    posting = {**POSTING, "description": "We do not offer visa sponsorship."}
    http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "no"}}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"work_authorization": "no sponsorship needed"})
    assert out["disqualified"] is False


def test_candidate_holding_clearance_passes_when_role_requires_one():
    http = FakeHttp(_screen_resp({"clearance": {"requires_clearance": True}}))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
                              candidate={"security_clearance": "Secret"})
    assert out["disqualified"] is False


# --- multi-gate failure reason join --------------------------------------

def test_multiple_failing_gates_join_reasons():
    http = FakeHttp(_screen_resp({
        "degree": {"required_degree": "phd"},
        "location": {"country": "Singapore", "remote": False},
    }))
    out = score.score_posting(POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
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


# --- real adapter: import safety ------------------------------------------

def test_make_claude_scorer_builds_without_importing_sdk():
    # The adapter must be import-safe: building it never imports anthropic (which
    # the hermetic test env lacks), so run.py can construct it before first use.
    fit = score.make_claude_scorer("sk-test", "claude-sonnet-4-6")
    assert callable(fit)
