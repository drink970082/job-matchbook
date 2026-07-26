"""Screen backends — the `extract(prompt, schema) -> dict` adapters that
`score.screen.screen_posting` consumes.

Six SCREEN_BACKEND values, three shapes:
  · HTTP + JSON schema — ollama (see score.screen.make_ollama_extract), claude-api,
    openai-api
  · CLI subprocess — codex (schema written to a file, `--output-schema`), claude-code
    (schema passed inline, `--json-schema` takes JSON text and errors on a bare path —
    verified behaviorally 2026-07-23, contrary to what the flag name suggests)
  · none — no adapter at all; run.make_screener returns None

Every adapter returns the PARSED dict or raises ScoreError. Nothing here decides
whether a posting is disqualified: the model only extracts JOB facts, and
`score.screen._screen_verdict` applies the candidate's constraint in code. A raised
ScoreError is caught by screen_posting and errs toward KEEP.

Imports of provider SDKs are deferred to the first call so importing this module —
and building an adapter in tests — never needs the SDK or a key.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

from .errors import ScoreError

# Two-to-three fields of fact extraction. Haiku is the right tier — Sonnet is wasted
# money on this shape. Override per-deploy with SCREEN_MODEL.
DEFAULT_CLAUDE_SCREEN_MODEL = "claude-haiku-4-5"


def _parse(raw: str, provider: str) -> dict:
    """Parse a provider's text response into the extraction dict, or raise."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScoreError(f"{provider} returned non-JSON screen: {raw!r}") from exc
    if not isinstance(data, dict):
        raise ScoreError(f"{provider} screen was not a JSON object: {data!r}")
    return data


def make_claude_api_extract(api_key: str, model: str = DEFAULT_CLAUDE_SCREEN_MODEL, *,
                            max_tokens: int = 1024):
    """Screen via the metered Anthropic API, schema-constrained by structured outputs
    (the same mechanism backends_claude.py already uses for the fit call).

    No prompt caching: unlike the fit call there is no large shared prefix — the
    checklist is a few hundred tokens and the JD is fresh every call.
    """
    cell: list = []

    def extract(prompt: str, schema: dict) -> dict:
        if not cell:
            import anthropic  # lazy: only at runtime
            cell.append(anthropic.Anthropic(api_key=api_key))
        msg = cell[0].messages.create(
            model=model,
            max_tokens=max_tokens,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
        return _parse(text, "claude-api")

    return extract


# Cheapest of the three frontier models ($1/$6 per MTok, 1.05M ctx) and it supports
# structured outputs. Aggregator sites claim a cheaper "nano" tier; OpenAI's own models
# page does not list one, so it is deliberately not hard-coded here.
DEFAULT_OPENAI_SCREEN_MODEL = "gpt-5.6-luna"


def make_openai_api_extract(api_key: str, model: str = DEFAULT_OPENAI_SCREEN_MODEL, *,
                            http=None, base_url: str = "https://api.openai.com/v1",
                            timeout: int = 60):
    """Screen via the metered OpenAI API over plain `requests` — no new dependency.
    `http` is injected (the real `requests` module is bound only in run.py) so tests
    exercise the parsing with a fake transport and zero network.

    Wire shape verified against current docs (2026-07-23): POST chat/completions
    with response_format={"type": "json_schema", "json_schema": {...}}, reading
    choices[0].message.content. (The newer /v1/responses endpoint nests the schema
    under text.format instead, but chat/completions remains supported and current —
    not the deprecated legacy /v1/completions.)
    """
    def extract(prompt: str, schema: dict) -> dict:
        resp = http.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "screen", "strict": True,
                                    "schema": schema},
                },
            },
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not choices:
            raise ScoreError(f"openai-api returned no choices: {payload!r}")
        return _parse(choices[0].get("message", {}).get("content", ""), "openai-api")

    return extract


# The codex screen ships on the model already trusted for fit scoring. gpt-5.6-luna is
# the cheaper candidate, but run.py rejects luna on MEASURED golden-set grounds (~3x
# looser spread) — a verdict measured on calibration-sensitive JUDGMENT, which does not
# obviously transfer to extraction. Re-measure before switching; do not assume.
DEFAULT_CODEX_SCREEN_MODEL = "gpt-5.6-sol"


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
