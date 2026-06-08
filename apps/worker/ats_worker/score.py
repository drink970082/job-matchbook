"""Score a job posting against the resume using a local Ollama model.

WHY Ollama (local) rather than a hosted LLM: scoring runs over every freshly
fetched posting, so doing it on a local model keeps cost at zero and avoids
rate limits — the expensive, quality-sensitive step (tailoring) is the only one
that goes to Claude.

`http` is injected (defaults to `requests`) so tests exercise the parsing and
clamping logic with a fake transport and zero network. Ollama wraps the model
output in {"response": "<json string>"} when called with format=json; we parse
that inner string defensively and raise ScoreError on anything unusable so the
pipeline can mark a single posting failed instead of aborting the batch.
"""
from __future__ import annotations

import json

import requests

_PROMPT = """\
You are an expert technical recruiter. Score how well the candidate's resume \
matches the job description below.

Return ONLY a JSON object with EXACTLY these keys:
  "score": integer 0-100 (overall fit),
  "matched_keywords": list of strings (skills/requirements the resume DOES cover),
  "missing_keywords": list of strings (skills/requirements the resume LACKS),
  "reasoning": short string explaining the score.

=== RESUME ===
{resume}

=== JOB: {title} at {company} ===
{description}
"""


class ScoreError(RuntimeError):
    """The model returned output we could not parse into a valid score."""


def score_posting(
    posting: dict,
    resume_text: str,
    *,
    model: str,
    http=requests,
    ollama_host: str,
    timeout: int = 120,
) -> dict:
    """Ask Ollama to score `posting` against `resume_text`.

    Returns {"score": int 0-100, "matched_keywords": [...],
    "missing_keywords": [...], "reasoning": str}. Raises ScoreError on
    unparseable model output.
    """
    prompt = _PROMPT.format(
        resume=resume_text,
        title=posting.get("job_title", ""),
        company=posting.get("company_name", ""),
        description=posting.get("description", ""),
    )
    resp = http.post(
        f"{ollama_host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "format": "json",
            # Disable "thinking" mode. Reasoning models (Qwen3/Qwen3.5, etc.)
            # otherwise route their output to a separate `thinking` field and
            # leave `response` EMPTY under format=json, so parsing fails on every
            # posting. Ollama ignores this flag for non-thinking models.
            "think": False,
            "stream": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    envelope = resp.json()

    inner = envelope.get("response", "") if isinstance(envelope, dict) else ""
    try:
        data = json.loads(inner)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScoreError(f"Ollama returned non-JSON response: {inner!r}") from exc
    if not isinstance(data, dict):
        raise ScoreError(f"Ollama response was not a JSON object: {data!r}")

    return _normalize(data)


def _normalize(data: dict) -> dict:
    if "score" not in data:
        # Absent score must fail loudly — burying it as 0 is indistinguishable
        # from a genuine 0 and would silently exclude the posting from tailoring.
        raise ScoreError(f"response missing required 'score': {data!r}")
    raw_score = data["score"]
    try:
        score = int(raw_score)
    except (TypeError, ValueError) as exc:
        raise ScoreError(f"score is not numeric: {raw_score!r}") from exc
    score = max(0, min(100, score))

    return {
        "score": score,
        "matched_keywords": _as_str_list(data.get("matched_keywords")),
        "missing_keywords": _as_str_list(data.get("missing_keywords")),
        "reasoning": str(data.get("reasoning") or ""),
    }


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]
