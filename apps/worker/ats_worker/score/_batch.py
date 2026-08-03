"""Shared batch plumbing for the CLI fit backends (`backends_codex`,
`backends_claude_cli`).

Both backends hand a CLI a JSON Schema and get back one scorecard per posting, so both
need the same two things: the schema envelope, and the guard that realigns the returned
elements to input order. Extracted here on 2026-08-02, when the second backend landed —
duplicating them would let the two drift, and the whole point of running both is that a
disagreement means the *models* disagree, not that one adapter parses differently.
"""
from __future__ import annotations

import json

from .errors import ScoreError
from .prompts import _score_schema


def batch_schema(labels: list) -> dict:
    """The schema actually handed to the CLI — the bare `_score_schema` never is.

    Deep-copy `_score_schema`'s output so its module-level cache (`_SCORE_SCHEMA`) is
    never mutated, then wrap N per-posting elements in a `{"results":[...]}` envelope
    tagged with the `job_ref` that makes realignment possible.
    """
    element = json.loads(json.dumps(_score_schema(labels)))
    element["properties"]["job_ref"] = {"type": "integer"}
    element["required"].append("job_ref")
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": element}},
        "required": ["results"],
        "additionalProperties": False,
    }


def align_results(data, postings: list[dict], *, backend: str) -> list[dict]:
    """Realign a `{"results":[...]}` payload to INPUT ORDER by `job_ref`.

    Position is not trusted: an LLM is not guaranteed to preserve list order across N
    items. A missing, duplicate, or unknown `job_ref` raises `ScoreError` for the WHOLE
    batch — silently misattributing a score to the wrong job is worse than failing
    loudly. `backend` only names the offender in the message.
    """
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ScoreError(f"{backend} batch response missing 'results' array: {data!r}")

    ids = [posting["id"] for posting in postings]
    id_set = set(ids)
    by_ref: dict = {}
    for result in data["results"]:
        if not isinstance(result, dict):
            raise ScoreError(f"{backend} batch result was not a JSON object: {result!r}")
        ref = result.get("job_ref")
        if ref not in id_set:
            raise ScoreError(f"{backend} returned unknown job_ref {ref!r}")
        if ref in by_ref:
            raise ScoreError(f"{backend} returned duplicate job_ref {ref!r}")
        by_ref[ref] = result
    missing = [i for i in ids if i not in by_ref]
    if missing:
        raise ScoreError(f"{backend} omitted job_ref {missing[0]}")
    return [by_ref[i] for i in ids]
