"""Claude fit-scoring backend — the injected `fit_fn` `pipeline.run_score` calls
after a posting clears the SCREEN. See `ats_worker.score` for the SCREEN/SCORE
composition this backend plugs into.
"""
from __future__ import annotations

import json

from .errors import ScoreError
from .prompts import _job_block, _score_schema, _scorer_system_blocks


# --- real adapter (exercised only in Docker; never imported at module load) ---

def make_claude_scorer(api_key: str, model: str, *, profile: str = "",
                       max_tokens: int = 4096):
    """Build a `fit(postings, resumes) -> list[dict]` callable backed by Claude.

    `resumes` is the {label: text} dict of resume versions; `profile` (optional,
    run-static) is extra about-the-candidate context. Rubric + profile + all
    resumes are sent as a cached system prefix (byte-identical every call in a
    run) so only the JD is fresh; with >=2 versions the schema also demands an
    enum-constrained `recommended_resume`. `import anthropic` and the client are
    deferred to the FIRST call so importing this module — and building the scorer
    in tests — never needs the SDK.

    UNLIKE codex, this does NOT batch into one call: Claude's win is the cached
    system prefix (flat per-call marginal cost already), not fewer round-trips, so
    batching would only buy request-count savings that don't matter on metered API
    billing. `fit` just loops the existing single-JD call and returns the RAW
    parsed JSON per posting, in order; `pipeline._persist_scored` normalizes
    each one via `_normalize_score`.
    """
    cell: list = []

    def _score_one(posting: dict, resumes: dict) -> dict:
        if not cell:
            import anthropic  # lazy: only at runtime in Docker
            cell.append(anthropic.Anthropic(api_key=api_key))
        client = cell[0]
        # 0 -> no truncation (Claude has ample context); no Location line (D5 — geography
        # is the screen's job, must not move the fit score).
        job = _job_block(posting, 0, include_location=False)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=_scorer_system_blocks(resumes, profile),
            output_config={"format": {"type": "json_schema",
                                      "schema": _score_schema(list(resumes))}},
            messages=[{"role": "user", "content": job}],
        )
        text = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ScoreError(f"Claude returned non-JSON score: {text!r}") from exc
        if not isinstance(data, dict):
            raise ScoreError(f"Claude score was not a JSON object: {data!r}")
        return data

    def fit(postings: list[dict], resumes: dict) -> list[dict]:
        return [_score_one(posting, resumes) for posting in postings]

    return fit
