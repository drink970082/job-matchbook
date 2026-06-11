"""TDD for Ollama-backed JD/resume scoring. No real network (injected http)."""
from __future__ import annotations

import json

import pytest

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
    http = FakeHttp(SCORE_OK, _screen_resp({"experience": {"min_years_required": None, "senior": True}}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h",
                              candidate={"years_experience": 1})
    assert out["disqualified"] is True


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
