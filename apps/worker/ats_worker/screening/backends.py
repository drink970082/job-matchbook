"""Screen backends — the `extract(prompt, schema) -> dict` adapters that
`screening.engine.screen_posting` consumes.

Adapters behind the SCREEN_BACKEND values (registry: ats_worker.screen_providers):
  · HTTP — ollama (see screening.engine.make_ollama_extract) and api (any
    OpenAI-compatible endpoint)
  · CLI subprocess — codex (schema written to a file, `--output-schema`), claude-code
    (schema passed inline, `--json-schema` takes JSON text and errors on a bare path —
    verified behaviorally 2026-07-23, contrary to what the flag name suggests)
  · none — no adapter at all; run.make_screener returns None

Every adapter returns the PARSED dict or raises ScoreError. Nothing here decides
whether a posting is disqualified: the model only extracts JOB facts, and
`screening.engine._screen_verdict` applies the candidate's constraint in code. A raised
ScoreError is caught by screen_posting and errs toward KEEP.

Imports of provider SDKs are deferred to the first call so importing this module —
and building an adapter in tests — never needs the SDK or a key.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

from .errors import ModelResponseError as ScoreError
from ats_worker.screen_providers import PROVIDERS

def _parse(raw: str, provider: str) -> dict:
    """Parse a provider's text response into the extraction dict, or raise."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScoreError(f"{provider} returned non-JSON screen: {raw!r}") from exc
    if not isinstance(data, dict):
        raise ScoreError(f"{provider} screen was not a JSON object: {data!r}")
    return data


_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def _strip_wrappers(text: str) -> str:
    """Drop a reasoning model's `<think>` block and a ```json fence around the reply —
    what a non-strict endpoint commonly returns instead of bare JSON."""
    text = _THINK.sub("", text or "").strip()
    m = _FENCE.match(text)
    return m.group(1) if m else text


def make_api_extract(*, base_url: str, api_key: str | None, model: str, http,
                     timeout: int = 60):
    """Screen via any OpenAI-compatible chat/completions endpoint (OpenAI, OpenRouter,
    Gemini's compatible endpoint, LM Studio, vLLM, ...) over plain `requests`. `http`
    is injected (the real `requests` module is bound only in run.py) so tests use a
    fake transport and no network. `api_key=None` sends no Authorization header (a
    keyless local server).

    Sends `response_format: json_schema` strict first. An endpoint that rejects it with
    a 400 is retried once without `response_format`, and that mode sticks for the
    rest of this extract's life so a non-strict endpoint does not pay two requests per
    posting. The prompt already asks for JSON; the reply is parsed after stripping
    `<think>` blocks and code fences. Any other HTTP error raises.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    strict = [True]

    def post(prompt, schema):
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if strict[0]:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "screen", "strict": True, "schema": schema}}
        return http.post(f"{base_url}/chat/completions", json=body, headers=headers,
                         timeout=timeout)

    def extract(prompt: str, schema: dict) -> dict:
        resp = post(prompt, schema)
        if strict[0] and resp.status_code == 400:
            strict[0] = False
            resp = post(prompt, schema)
        resp.raise_for_status()
        payload = resp.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not choices:
            raise ScoreError(f"api returned no choices: {payload!r}")
        content = (choices[0].get("message") or {}).get("content") or ""
        return _parse(_strip_wrappers(content), "api")

    return extract


# The measured expanded screen-corpus comparison picked Luna; the evaluation's effort
# provenance is unknown, so its result does not establish medium-effort quality.
DEFAULT_CODEX_SCREEN_MODEL = PROVIDERS["codex"].default_model


def _run_cli(runner, cmd, prompt, timeout, provider):
    """Shared subprocess call for the CLI-shaped backends."""
    try:
        proc = runner(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ScoreError(f"{provider} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise ScoreError(f"{provider} binary not found: {cmd[0]!r}") from exc
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip()[-400:]
        raise ScoreError(f"{provider} failed (exit {proc.returncode}): {tail}")
    return proc


def make_codex_extract(model: str = DEFAULT_CODEX_SCREEN_MODEL, *,
                       reasoning_effort: str | None = None,
                       codex_bin: str = "codex", timeout: int = 180, runner=None):
    """Screen via the Codex CLI on the operator's ChatGPT subscription.

    Runs TOOL-LESS (`--disable shell_tool`, `web_search="disabled"`) — a security
    boundary, not a tuning choice: a JD is untrusted scraped text and `codex exec` is
    natively an agent holding a shell, so a posting could otherwise ask it to read
    ~/.codex/auth.json and echo a secret into the output. Same posture as the fit
    backend. `--ephemeral` suppresses the session rollout so a JD never lands on disk;
    the screen does not capture quota usage (that rides the fit call).
    """
    runner = runner or subprocess.run

    def extract(prompt: str, schema: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = os.path.join(tmp, "schema.json")
            out_path = os.path.join(tmp, "out.json")
            with open(schema_path, "w", encoding="utf-8") as fh:
                json.dump(schema, fh)
            cmd = [codex_bin, "exec", "--model", model,
                   "--disable", "shell_tool",
                   "-c", 'web_search="disabled"',
                   *(["-c", f"model_reasoning_effort={reasoning_effort}"]
                     if reasoning_effort else []),
                   "--output-schema", schema_path,
                   "--output-last-message", out_path,
                   "--sandbox", "read-only", "--skip-git-repo-check",
                   "--ephemeral", "--color", "never", "-C", tmp, "-"]
            _run_cli(runner, cmd, prompt, timeout, "codex screen")
            try:
                with open(out_path, encoding="utf-8") as fh:
                    return _parse(fh.read(), "codex screen")
            except OSError as exc:
                raise ScoreError(f"codex screen wrote no output: {exc}") from exc

    return extract


def make_claude_code_extract(model: str | None = None, *, claude_bin: str = "claude",
                             timeout: int = 180, runner=None):
    """Screen via the Claude Code CLI on the operator's subscription.

    `--json-schema` constrains the structured output and `--output-format json` wraps
    the result; both require `--print`. The wrapper's `result` field carries the model's
    text, which is the schema-constrained JSON we want.

    `--json-schema` takes the schema INLINE (JSON text), not a file path — verified
    behaviorally 2026-07-23: `claude --print --json-schema <missing-path> ...` fails
    with "not valid JSON", not a missing-file error, despite the flag name suggesting
    otherwise. So unlike the codex adapter (which writes `--output-schema` to a temp
    file), this one passes `json.dumps(schema)` directly and needs no temp directory.
    """
    runner = runner or subprocess.run

    def extract(prompt: str, schema: dict) -> dict:
        cmd = [claude_bin, "--print",
               "--json-schema", json.dumps(schema),
               "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        proc = _run_cli(runner, cmd, prompt, timeout, "claude-code screen")
        envelope = _parse(proc.stdout, "claude-code screen")
        return _parse(str(envelope.get("result", "")), "claude-code screen")

    return extract
