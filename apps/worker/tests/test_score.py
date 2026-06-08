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
    """Records the last POST and returns a canned Ollama envelope."""

    def __init__(self, inner):
        # `inner` is the string Ollama puts in {"response": <here>}
        self._inner = inner
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse({"response": self._inner})


POSTING = {
    "job_title": "Senior Python Engineer",
    "company_name": "Acme",
    "description": "We need Python, Django, and AWS experience.",
}
RESUME = "Experienced Python and Django developer."


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


def test_candidate_constraints_reach_prompt_and_disqualify_passes_through():
    inner = json.dumps({"score": 70, "matched_keywords": [], "missing_keywords": [],
                        "reasoning": "ok", "disqualified": True,
                        "disqualification_reason": "requires a PhD"})
    http = FakeHttp(inner)
    out = score.score_posting(
        POSTING, RESUME, model="m", http=http, ollama_host="h",
        candidate={"profile": "entry level", "dealbreakers": ["requires a PhD"]},
    )
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "requires a PhD"
    body = http.calls[0][1]["json"]
    assert "requires a PhD" in body["prompt"]   # dealbreaker reached the model
    assert "disqualified" in body["prompt"]      # extra key was requested


def test_no_candidate_means_no_disqualify_block_and_defaults_false():
    http = FakeHttp(json.dumps({"score": 70}))
    out = score.score_posting(POSTING, RESUME, model="m", http=http, ollama_host="h")
    assert out["disqualified"] is False
    assert out["disqualification_reason"] == ""
    body = http.calls[0][1]["json"]
    assert "CANDIDATE CONSTRAINTS" not in body["prompt"]
    assert "disqualified" not in body["prompt"]
