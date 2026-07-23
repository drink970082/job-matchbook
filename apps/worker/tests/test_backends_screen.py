"""Screen backends: the six `extract(prompt, schema) -> dict` adapters."""
import json
import sys
import types

import pytest

from ats_worker.score import backends_screen
from ats_worker.score.errors import ScoreError


def _fake_anthropic(captured, text='{"screen": {}}'):
    """A stand-in `anthropic` module. The real SDK is never imported in tests."""
    mod = types.ModuleType("anthropic")

    class _Messages:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            block = types.SimpleNamespace(type="text", text=text)
            return types.SimpleNamespace(content=[block])

    class Anthropic:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _Messages()

    mod.Anthropic = Anthropic
    return mod


def test_claude_api_extract_returns_parsed_json(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(captured))
    extract = backends_screen.make_claude_api_extract("sk-test")
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    assert captured["model"] == "claude-haiku-4-5"
    assert captured["api_key"] == "sk-test"
    # The schema must actually constrain the response, not just ride along.
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["output_config"]["format"]["schema"] == {"type": "object"}


def test_claude_api_extract_raises_score_error_on_non_json(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic",
                        _fake_anthropic({}, text="not json {{{"))
    extract = backends_screen.make_claude_api_extract("sk-test")
    with pytest.raises(ScoreError):
        extract("p", {})


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResp(self._payload, self._status)


def test_openai_api_extract_returns_parsed_json():
    http = _FakeHttp({"choices": [{"message": {"content": '{"screen": {}}'}}]})
    extract = backends_screen.make_openai_api_extract("sk-oa", http=http)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    assert http.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    body = http.calls[0]["json"]
    assert body["model"] == "gpt-5.6-luna"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer sk-oa"
    assert body["response_format"]["type"] == "json_schema"


def test_openai_api_extract_raises_score_error_on_empty_choices():
    http = _FakeHttp({"choices": []})
    extract = backends_screen.make_openai_api_extract("sk-oa", http=http)
    with pytest.raises(ScoreError):
        extract("p", {})


def test_openai_api_extract_raises_score_error_on_non_json():
    http = _FakeHttp({"choices": [{"message": {"content": "not json {{{"}}]})
    extract = backends_screen.make_openai_api_extract("sk-oa", http=http)
    with pytest.raises(ScoreError):
        extract("p", {})
