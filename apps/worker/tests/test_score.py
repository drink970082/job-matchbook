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


def _fit(score=60, **assess):
    """A canned score_fit(postings, resumes) -> list[dict] callable (batch-first,
    B1) for tests that focus on SCREEN."""
    payload = {"score": score, "assessment": _assessment(**assess)}
    return lambda postings, resume_text: [dict(payload) for _ in postings]


FIT = _fit()  # the common "score 60" fit used by SCREEN-focused tests


# --- score_fit is called, its result normalized -------------------------

def test_score_fit_result_is_normalized_and_returned():
    got = {}

    def fit(postings, resume_text):
        got["posting"], got["resume"] = postings[0], resume_text
        return [{"score": 88, "assessment": _assessment(
            met=["python", "django"], missing=["aws"], summary="Strong overlap.")}]

    out = score.score_posting(POSTING, RESUME, score_fit=fit, model="m",
                              http=FakeHttp(), ollama_host="h")
    assert out["score"] == 88
    assert out["assessment"]["must_haves"]["met"] == ["python", "django"]
    assert out["assessment"]["must_haves"]["missing"] == ["aws"]
    assert out["assessment"]["summary"] == "Strong overlap."
    assert got["posting"] is POSTING and got["resume"] == RESUME  # posting+resume handed to scorer


def test_score_clamped_to_0_100():
    out = score.score_posting(POSTING, RESUME, score_fit=_fit(130), model="m",
                              http=FakeHttp(), ollama_host="h")
    assert out["score"] == 100
    out2 = score.score_posting(POSTING, RESUME, score_fit=_fit(-5), model="m",
                               http=FakeHttp(), ollama_host="h")
    assert out2["score"] == 0


def test_assessment_lists_and_notes_coerced_to_defaults():
    # The scorecard's verdicts are required, but its keyword lists / notes / summary
    # coerce to empty when the model omits them (lenient — they only feed the UI).
    fit = lambda ps, r: [{"score": 50, "assessment": {
        "seniority": {"verdict": "match"}, "domain": {"verdict": "adjacent"},
        "must_haves": {}, "nice_to_haves": {}, "summary": None}}]
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                              score_fit=fit)
    a = out["assessment"]
    assert a["seniority"] == {"verdict": "match", "note": ""}
    assert a["must_haves"] == {"met": [], "missing": []}
    assert a["nice_to_haves"] == {"missing": []}
    assert a["summary"] == ""


def test_absent_score_key_raises_not_silently_zero():
    # A scorer that returns a dict without "score" must NOT be buried as a real 0.
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=lambda ps, r: [{"assessment": _assessment()}])


def test_missing_or_malformed_assessment_raises():
    # The scorecard is required and its verdicts must be in-enum — a missing assessment
    # or a bogus verdict fails loudly (the per-dimension verdicts drive ranking + audit).
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=lambda ps, r: [{"score": 80}])
    bad = lambda ps, r: [{"score": 80, "assessment": {
        "seniority": {"verdict": "kinda"}, "domain": {"verdict": "match"},
        "must_haves": {"met": [], "missing": []}, "nice_to_haves": {"missing": []},
        "summary": ""}}]
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=bad)


def test_non_numeric_score_raises_score_error():
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=lambda ps, r: [{"score": "high"}])


def test_float_and_string_scores_accepted():
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                              score_fit=lambda ps, r: [{"score": 85.7, "assessment": _assessment()}])
    assert out["score"] == 86                                 # rounded
    out2 = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                               score_fit=lambda ps, r: [{"score": "72", "assessment": _assessment()}])
    assert out2["score"] == 72


def test_assessment_keyword_coercion_tolerates_bare_string_and_nesting():
    fit = lambda ps, r: [{"score": 50, "assessment": {
        "seniority": {"verdict": "match"}, "domain": {"verdict": "match"},
        "must_haves": {"met": "python", "missing": [["aws", "k8s"]]},
        "nice_to_haves": {"missing": []}, "summary": ""}}]
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                              score_fit=fit)
    assert out["assessment"]["must_haves"]["met"] == ["python"]
    assert out["assessment"]["must_haves"]["missing"] == ["aws", "k8s"]


def test_score_fit_error_propagates_to_mark_failed():
    # A scorer failure must propagate out of score_posting so run_score marks the
    # posting failed (batch continues) — it must NOT be swallowed like a SCREEN error.
    def boom(posting, resume_text):
        raise score.ScoreError("claude parse failed")
    with pytest.raises(score.ScoreError):
        score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
                            score_fit=boom)


def test_candidate_screen_call_disqualifies_and_omits_resume():
    # A screen disqualification (here: the role requires a clearance the candidate
    # lacks) gates the paid fit call and never puts the résumé in the screen prompt.
    http = FakeHttp(
        json.dumps({"screen": {"clearance": {"requires_clearance": True}}}),
    )
    out = score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={"security_clearance": "none"},
    )
    assert out["score"] == 0                         # gated: disqualified -> no Claude fit call
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "clearance: requires security clearance"
    assert len(http.calls) == 1                      # SCREEN is now the only Ollama call
    screen_prompt = http.calls[0][1]["json"]["prompt"]
    assert '"screen"' in screen_prompt               # screen output requested
    assert RESUME not in screen_prompt               # screen never sees the résumé


def test_screen_posting_disqualifies_without_calling_fit():
    # screen_posting is the standalone SCREEN half: no score_fit parameter exists on
    # it at all, so it structurally cannot pay for a fit call — score_posting is what
    # gates on `disqualified` before ever touching score_fit.
    http = FakeHttp(json.dumps({"screen": {"clearance": {"requires_clearance": True}}}))
    out = score.screen_posting(POSTING, http=http, ollama_host="h", model="m",
                               candidate={"security_clearance": "none"}, num_ctx=8192)
    assert out["disqualified"] is True
    assert "screen" in out
    assert out["disqualification_reason"] == "clearance: requires security clearance"


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
        candidate={"highest_degree": "Master's"},
    )
    assert out["score"] == 60                     # from score_fit (FIT -> 60)
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    assert out["screen"] == {}
    assert len(http.calls) == 1                    # the (failed) SCREEN call


def test_screen_gates_the_paid_score_call():
    # The reorder: SCREEN runs first and GATES the fit score. A disqualified posting
    # SKIPS the injected (paid) Claude scorer entirely (score 0, no fit); a posting
    # that passes the screen still calls it. (Uses degree as the vehicle — location
    # is now a code gate, exercised separately.)
    disq = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    fit = Mock(return_value=[{"score": 90, "assessment": _assessment()}])
    out = score.score_posting(POSTING, RESUME, score_fit=fit, model="m", http=disq,
                              ollama_host="h", candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is True and out["score"] == 0
    fit.assert_not_called()                        # gate skipped the paid call

    ok = FakeHttp(_screen_resp({"degree": {"required_degree": "bachelor's"}}))
    fit2 = Mock(return_value=[{"score": 90, "assessment": _assessment()}])
    out2 = score.score_posting(POSTING, RESUME, score_fit=fit2, model="m", http=ok,
                               ollama_host="h", candidate={"highest_degree": "Master's"})
    assert out2["disqualified"] is False and out2["score"] == 90
    fit2.assert_called_once()                      # passed the screen -> scored


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
    # locations is deliberately omitted: it's a code gate now (resolve_location off
    # posting["location"]), so it renders no extraction clause in the SCREEN prompt.
    http = FakeHttp(json.dumps({"screen": {}}))
    score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={
            "highest_degree": "Master's",
            "work_authorization": "needs visa sponsorship",
            "security_clearance": "none",
        },
    )
    prompt = http.calls[0][1]["json"]["prompt"]                # the SCREEN call
    # each structured requirement asks the model to EXTRACT a job fact
    assert "required_degree" in prompt
    assert "offers_sponsorship" in prompt
    assert "requires_clearance" in prompt
    assert '"screen"' in prompt
    assert RESUME not in prompt                               # no résumé in the screen call


def test_empty_candidate_fields_render_no_screen_call():
    http = FakeHttp()
    score.score_posting(
        POSTING, RESUME, score_fit=FIT, model="m", http=http, ollama_host="h",
        candidate={"highest_degree": "", "locations": []},
    )
    assert len(http.calls) == 0


# --- screen: extracted facts + code gates --------------------------------

def _screen_resp(screen):
    return json.dumps({"screen": screen})


# location: gated in CODE off posting["location"] (pycountry), not the LLM screen
def test_foreign_location_disqualifies_from_board_string():
    posting = {**POSTING, "location": "Shanghai, China"}
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m",
                              http=FakeHttp(), ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert out["score"] == 0                                  # gated: no Claude call
    assert out["disqualification_reason"] == "location: on-site in China"
    assert out["screen"]["location"]["pass"] is False


def test_us_state_only_location_kept():
    posting = {**POSTING, "location": "New York, New York"}
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m",
                              http=FakeHttp(), ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False
    assert out["score"] == 60                                 # kept -> Claude (FIT) scored
    assert out["screen"]["location"]["pass"] is True


def test_locations_only_candidate_makes_no_ollama_call():
    posting = {**POSTING, "location": "Sydney, Australia"}
    http = FakeHttp()
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http,
                              ollama_host="h", candidate={"locations": ["remote", "USA"]})
    assert len(http.calls) == 0                               # location needs no LLM
    assert out["disqualified"] is True


def test_missing_board_location_is_kept():
    posting = {**POSTING, "location": None}
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m",
                              http=FakeHttp(), ollama_host="h",
                              candidate={"locations": ["remote", "USA"]})
    assert out["disqualified"] is False                       # err toward keep


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
    posting = {**POSTING, "description": "We will not sponsor visas for this role."}
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


def test_authorization_ignores_sponsor_boilerplate():
    # D1 repro: a JD mentioning 'sponsor'/'citizen' only in boilerplate must NOT
    # disqualify. Tower matched "sponsor" in "company-sponsored sports teams" (id=986);
    # WorldQuant matched "citizen" in the EEO line (id=1071). The 4B model even invents
    # offers_sponsorship='no' from silence — it must be ignored; only an explicit
    # no-sponsorship phrase in the JD text disqualifies.
    for desc in (
        "We field company-sponsored sports teams and a great engineering culture.",
        "EEO: we do not discriminate on citizenship, national origin, disability, or age.",
    ):
        posting = {**POSTING, "description": desc}
        http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "no"}}))
        out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http,
                                  ollama_host="h",
                                  candidate={"work_authorization": "needs visa sponsorship"})
        assert out["disqualified"] is False, desc


def test_authorization_fails_only_on_explicit_no_sponsorship_phrase():
    # D1: an explicit phrase disqualifies even when the model guessed 'unknown' —
    # the phrase gate, not the 4B verdict, decides.
    posting = {**POSTING, "description": "Strong team. This position offers no visa sponsorship."}
    http = FakeHttp(_screen_resp({"authorization": {"offers_sponsorship": "unknown"}}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http,
                              ollama_host="h",
                              candidate={"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is True


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
                              candidate={"highest_degree": "Master's"})
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
    posting = {**POSTING, "location": "Singapore"}
    http = FakeHttp(_screen_resp({"degree": {"required_degree": "phd"}}))
    out = score.score_posting(posting, RESUME, score_fit=FIT, model="m", http=http,
                              ollama_host="h",
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


def test_score_schema_carries_enum_constrained_assessment():
    # S2.1: the scorecard replaces the flat reasoning/keyword fields; verdicts are
    # enum-constrained so structured outputs enforce them.
    schema = score._score_schema(["resume"])
    assert schema["required"] == ["assessment", "score", "insufficient_context"]
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
    out = score.score_posting(
        POSTING, {"quant_dev": "q", "swe": "s"}, model="m", http=FakeHttp(),
        ollama_host="h",
        score_fit=lambda ps, r: [{"score": 80, "assessment": _assessment(),
                                  "recommended_resume": "swe"}])
    assert out["recommended_resume"] == "swe"


def test_insufficient_context_normalized_true():
    out = score.score_posting(
        POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
        score_fit=lambda ps, r: [{"score": 40, "assessment": _assessment(),
                                  "insufficient_context": True}])
    assert out["insufficient_context"] is True


def test_insufficient_context_absent_defaults_false():
    out = score.score_posting(
        POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
        score_fit=lambda ps, r: [{"score": 40, "assessment": _assessment()}])
    assert out["insufficient_context"] is False   # absent -> False (err toward scoreable)


def test_recommended_resume_absent_or_blank_is_omitted():
    out = score.score_posting(POSTING, RESUME, model="m", http=FakeHttp(),
                              ollama_host="h",
                              score_fit=lambda ps, r: [{"score": 80, "assessment": _assessment()}])
    assert "recommended_resume" not in out
    out2 = score.score_posting(
        POSTING, RESUME, model="m", http=FakeHttp(), ollama_host="h",
        score_fit=lambda ps, r: [{"score": 80, "assessment": _assessment(),
                                  "recommended_resume": "   "}])
    assert "recommended_resume" not in out2


def test_score_fit_receives_the_resumes_dict():
    got = {}
    resumes = {"quant_dev": "QD", "swe": "SWE"}

    def fit(postings, r):
        got["resumes"] = r
        return [{"score": 70, "assessment": _assessment()}]

    score.score_posting(POSTING, resumes, score_fit=fit, model="m",
                        http=FakeHttp(), ollama_host="h")
    assert got["resumes"] is resumes


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
    # (score_posting normalizes), same contract as Claude, just batched — one
    # scorecard per input posting, in input order.
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
    monkeypatch.setattr(score, "_sessions_dir", lambda: str(sess))
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
    assert not (tmp_path / "codex_usage.json.tmp").exists()  # atomic write, no tmp left


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
