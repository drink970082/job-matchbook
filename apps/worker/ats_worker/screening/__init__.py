"""Active standalone screening seam, independent of legacy fit scoring."""
from __future__ import annotations

from .errors import ModelResponseError

from .backends import (
    DEFAULT_CODEX_SCREEN_MODEL, make_api_extract, make_claude_code_extract,
    make_codex_extract,
)
from .engine import (
    deterministic_screen, make_ollama_extract, screen_posting,
    screen_requires_provider, sponsorship_snippets, verdict_block,
)
from .location import location_verdict, resolve_location
from .prompts import SCREEN_HEADER, SCREEN_SCHEMA

__all__ = [
    "ModelResponseError", "DEFAULT_CODEX_SCREEN_MODEL", "deterministic_screen",
    "location_verdict", "make_api_extract", "make_claude_code_extract",
    "make_codex_extract", "make_ollama_extract", "resolve_location",
    "screen_posting", "screen_requires_provider", "sponsorship_snippets",
    "verdict_block", "SCREEN_HEADER", "SCREEN_SCHEMA",
]
