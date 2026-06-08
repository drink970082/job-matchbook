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

_PROMPT_HEADER = """\
You are an expert technical recruiter. Score how well the candidate's resume \
matches the job description below.

Return ONLY a JSON object with EXACTLY these keys:
  "score": integer 0-100 (overall fit),
  "matched_keywords": list of strings (skills/requirements the resume DOES cover),
  "missing_keywords": list of strings (skills/requirements the resume LACKS),
  "reasoning": short string explaining the score.
"""

# Requested ONLY when candidate constraints are configured, so default behaviour
# (no candidate block) is unchanged.
_DISQUALIFY_KEYS = """\
  "disqualified": boolean — true ONLY if the role conflicts with a hard candidate \
constraint below,
  "disqualification_reason": short string (empty when not disqualified).
"""


def _candidate_block(candidate) -> str:
    """Render the candidate-constraints section, or '' if none configured."""
    if not candidate:
        return ""
    profile = str(candidate.get("profile") or "").strip()
    dealbreakers = [str(d) for d in (candidate.get("dealbreakers") or []) if str(d).strip()]
    if not profile and not dealbreakers:
        return ""
    lines = ["", "=== CANDIDATE CONSTRAINTS ==="]
    if profile:
        lines.append(f"Profile: {profile}")
    if dealbreakers:
        lines.append("Set disqualified=true if ANY of these apply to the role:")
        lines += [f"  - {d}" for d in dealbreakers]
    lines.append(
        "Judge the job's MEANING, not exact words (e.g. 'must be authorized to "
        "work without sponsorship' conflicts with needing sponsorship). If "
        "genuinely unclear, do NOT disqualify."
    )
    return "\n".join(lines) + "\n"


def _build_prompt(resume_text: str, posting: dict, candidate=None) -> str:
    block = _candidate_block(candidate)
    extra = _DISQUALIFY_KEYS if block else ""
    return (
        _PROMPT_HEADER + extra + block
        + f"\n=== RESUME ===\n{resume_text}\n\n"
        + f"=== JOB: {posting.get('job_title', '')} at {posting.get('company_name', '')} ===\n"
        + f"{posting.get('description', '')}\n"
    )


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
    candidate: dict | None = None,
) -> dict:
    """Ask Ollama to score `posting` against `resume_text`.

    Returns {"score": int 0-100, "matched_keywords": [...],
    "missing_keywords": [...], "reasoning": str}. Raises ScoreError on
    unparseable model output.
    """
    prompt = _build_prompt(resume_text, posting, candidate)
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
        "disqualified": bool(data.get("disqualified", False)),
        "disqualification_reason": str(data.get("disqualification_reason") or ""),
    }


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]
