"""Screen backends — the `extract(prompt, schema) -> dict` adapters that
`score.screen.screen_posting` consumes.

Six SCREEN_BACKEND values, three shapes:
  · HTTP + JSON schema — ollama (see score.screen.make_ollama_extract), claude-api,
    openai-api
  · CLI subprocess + a schema file — codex, claude-code
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
