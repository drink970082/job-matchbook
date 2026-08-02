"""ats_worker.score: fit-scoring package for one job posting — a hard-requirements
SCREEN (local Ollama) plus a fit SCORE (injected, Claude/codex). This module is a
pure re-export shim; the real code lives in the submodules: `score.screen`
(SCREEN/SCORE composition, `screen_posting`, normalization, screen rules),
`score.location` (the deterministic location gate), `score.prompts` (prompt +
schema assembly), `score.usage` (quota telemetry), `score._batch` (the schema
envelope and job_ref realignment the CLI backends share), and the three fit-scoring
backends: `score.backends_codex` (codex CLI, subscription),
`score.backends_claude_cli` (Claude Code CLI, subscription) and
`score.backends_claude` (Anthropic SDK, metered).
"""
from __future__ import annotations

import subprocess  # re-exported so tests can monkeypatch score.subprocess.run

from .backends_claude import make_claude_scorer  # noqa: F401  (re-export)
from .backends_claude_cli import make_claude_cli_scorer  # noqa: F401  (re-export)
from .backends_codex import make_codex_scorer  # noqa: F401  (re-export)
from .errors import ScoreError  # noqa: F401  (re-export)
from .location import resolve_location, _token_country  # noqa: F401  (re-export)
from .prompts import (  # noqa: F401  (re-export)
    _SCORE_SCHEMA,
    SCREEN_SCHEMA,
    _job_block,
    _score_schema,
    _scorer_system_blocks,
    _scorer_system_sections,
    _truncate,
)
from .screen import (  # noqa: F401  (re-export)
    _degree_rank,
    _flag,
    _is_internship,
    _needs_sponsorship,
    _normalize_score,
    _offers_sponsorship,
    _sentences,
    demote_for_confirmation,
    deterministic_screen,
    make_ollama_extract,
    merge_fallback_screen,
    screen_posting,
    sponsorship_snippets,
)
from .usage import (  # noqa: F401  (re-export)
    _claude_limits,
    _epoch,
    capture_usage,
    fetch_claude_usage,
    fetch_codex_usage,
)
