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
