"""Screen backends: the `extract(prompt, schema) -> dict` adapters."""
import json
import types

import pytest

from ats_worker.screening import backends as backends_screen
from ats_worker.screening.errors import ModelResponseError as ScoreError


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
    """Answers each post with the next (payload, status) in `replies`."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        payload, status = self._replies.pop(0)
        return _FakeResp(payload, status)


def _ok(content):
    return ({"choices": [{"message": {"content": content}}]}, 200)


def _api(http, **kw):
    kw.setdefault("base_url", "https://api.openai.com/v1")
    return backends_screen.make_api_extract(api_key=kw.pop("api_key", "sk-x"),
                                            model=kw.pop("model", "m-1"), http=http, **kw)


def test_api_extract_sends_strict_schema_and_parses():
    http = _FakeHttp(_ok('{"screen": {}}'))
    assert _api(http)("the prompt", {"type": "object"}) == {"screen": {}}
    call = http.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-x"
    assert call["json"]["model"] == "m-1"
    fmt = call["json"]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == {"type": "object"}


def test_api_extract_reaches_any_base_url_without_a_key():
    http = _FakeHttp(_ok('{"a": 1}'))
    extract = _api(http, base_url="http://localhost:1234/v1", api_key=None)
    assert extract("p", {}) == {"a": 1}
    assert http.calls[0]["url"] == "http://localhost:1234/v1/chat/completions"
    assert "Authorization" not in http.calls[0]["headers"]


def test_api_extract_falls_back_once_when_strict_schema_is_rejected():
    # An endpoint that rejects json_schema with a 400 is retried without
    # response_format; the fallback sticks for later calls (no doubled requests).
    http = _FakeHttp(({"error": "response_format unsupported"}, 400),
                     _ok('{"a": 1}'), _ok('{"b": 2}'))
    extract = _api(http)
    assert extract("p", {"type": "object"}) == {"a": 1}
    assert "response_format" in http.calls[0]["json"]
    assert "response_format" not in http.calls[1]["json"]
    assert extract("p", {"type": "object"}) == {"b": 2}
    assert len(http.calls) == 3 and "response_format" not in http.calls[2]["json"]


def test_api_extract_a_400_that_survives_the_retry_raises_and_keeps_strict():
    # A 400 with another cause (over-long prompt, bad model) must not silently switch
    # the rest of the pass to non-strict.
    http = _FakeHttp(({"error": "context_length_exceeded"}, 400), ({"error": "x"}, 400),
                     _ok('{"a": 1}'))
    extract = _api(http)
    with pytest.raises(RuntimeError):
        extract("p", {})
    assert extract("p", {}) == {"a": 1}
    assert "response_format" in http.calls[2]["json"]


def test_api_extract_other_http_errors_raise():
    http = _FakeHttp(({"error": "nope"}, 401))
    with pytest.raises(RuntimeError):
        _api(http)("p", {})


def test_api_extract_tolerates_think_tags_and_fences():
    raw = '<think>let me see</think>\nHere you go:\n```json\n{"a": 1}\n```'
    assert _api(_FakeHttp(_ok(raw)))("p", {}) == {"a": 1}


@pytest.mark.parametrize("payload", [{"choices": []},
                                     {"choices": [{"message": {"content": "no {{"}}]}])
def test_api_extract_raises_score_error_on_unusable_reply(payload):
    with pytest.raises(ScoreError):
        _api(_FakeHttp((payload, 200)))("p", {})


def _fake_runner(stdout="", returncode=0, writes=None):
    """Stand in for subprocess.run. `writes` maps a flag to the JSON written to the
    path that follows it, emulating a CLI that writes its result to a file."""
    calls = []

    def run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        for flag, payload in (writes or {}).items():
            path = cmd[cmd.index(flag) + 1]
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(payload)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    run.calls = calls
    return run


def test_codex_extract_reads_the_output_file():
    runner = _fake_runner(writes={"--output-last-message": '{"screen": {}}'})
    extract = backends_screen.make_codex_extract(runner=runner)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    cmd = runner.calls[0]["cmd"]
    # Tool-less is a SECURITY boundary, not a tuning choice: a JD is untrusted text
    # and codex exec is natively an agent holding a shell.
    assert "--disable" in cmd and "shell_tool" in cmd
    assert 'web_search="disabled"' in cmd
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--ephemeral" in cmd
    assert "--output-schema" in cmd


def test_codex_extract_pins_reasoning_effort_only_when_selected():
    runner = _fake_runner(writes={"--output-last-message": '{"screen": {}}'})
    extract = backends_screen.make_codex_extract(
        "gpt-5.6-luna", reasoning_effort="medium", runner=runner)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    cmd = runner.calls[0]["cmd"]
    assert cmd[cmd.index("-c") + 1] == 'web_search="disabled"'
    effort_idx = cmd.index("model_reasoning_effort=medium")
    assert cmd[effort_idx - 1] == "-c"


def test_codex_extract_raises_on_nonzero_exit():
    extract = backends_screen.make_codex_extract(runner=_fake_runner(returncode=1))
    with pytest.raises(ScoreError, match="codex"):
        extract("p", {})


def test_codex_extract_raises_when_no_output_written():
    # `writes=None` (the default): the fake runner exits 0 but never writes the
    # out file, exercising the "err toward keep, don't swallow" guard around the
    # --output-last-message read.
    extract = backends_screen.make_codex_extract(runner=_fake_runner(returncode=0))
    with pytest.raises(ScoreError, match="codex screen wrote no output"):
        extract("p", {})


def test_claude_code_extract_parses_stdout_json():
    runner = _fake_runner(stdout=json.dumps({"result": '{"screen": {}}'}))
    extract = backends_screen.make_claude_code_extract(runner=runner)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    cmd = runner.calls[0]["cmd"]
    assert "--print" in cmd
    assert "--json-schema" in cmd
    assert "--output-format" in cmd and "json" in cmd
    # --json-schema takes the schema INLINE, not a file path (verified behaviorally
    # 2026-07-23: a missing-path argument fails as "not valid JSON", not a missing-file
    # error) — so the argument right after the flag must be the JSON text itself.
    schema_arg = cmd[cmd.index("--json-schema") + 1]
    assert json.loads(schema_arg) == {"type": "object"}
