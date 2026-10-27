"""Compatibility facade for the legacy fit scorer and active screen APIs.

Fit exports are resolved only when requested. Importing this package, its neutral
exception module, or a screen compatibility export must not load fit backends or the
legacy fit prompts. Explicit legacy callers keep the historical names and monkeypatch
seams.
"""
from __future__ import annotations

import importlib
import subprocess  # re-exported so tests can monkeypatch score.subprocess.run
from typing import Any


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "make_claude_scorer": ("backends_claude", "make_claude_scorer"),
    "make_claude_cli_scorer": ("backends_claude_cli", "make_claude_cli_scorer"),
    "make_codex_scorer": ("backends_codex", "make_codex_scorer"),
    "ScoreError": ("errors", "ScoreError"),
    "resolve_location": ("screening.location", "resolve_location"),
    "_token_country": ("screening.location", "_token_country"),
    "_SCORE_SCHEMA": ("prompts", "_SCORE_SCHEMA"),
    "SCREEN_SCHEMA": ("screening.prompts", "SCREEN_SCHEMA"),
    "_job_block": ("screening.prompts", "_job_block"),
    "_score_schema": ("prompts", "_score_schema"),
    "_scorer_system_blocks": ("prompts", "_scorer_system_blocks"),
    "_scorer_system_sections": ("prompts", "_scorer_system_sections"),
    "_truncate": ("screening.prompts", "_truncate"),
    "_degree_rank": ("screening.engine", "_degree_rank"),
    "_flag": ("screening.engine", "_flag"),
    "_is_internship": ("screening.engine", "_is_internship"),
    "_needs_sponsorship": ("screening.engine", "_needs_sponsorship"),
    "_normalize_score": ("screen", "_normalize_score"),
    "_offers_sponsorship": ("screening.engine", "_offers_sponsorship"),
    "_sentences": ("screening.engine", "_sentences"),
    "demote_for_confirmation": ("screen", "demote_for_confirmation"),
    "deterministic_screen": ("screening.engine", "deterministic_screen"),
    "make_ollama_extract": ("screening", "make_ollama_extract"),
    "merge_fallback_screen": ("screen", "merge_fallback_screen"),
    "screen_posting": ("screening.engine", "screen_posting"),
    "screen_requires_provider": ("screening.engine", "screen_requires_provider"),
    "sponsorship_snippets": ("screening.engine", "sponsorship_snippets"),
    "_claude_limits": ("usage", "_claude_limits"),
    "_epoch": ("usage", "_epoch"),
    "capture_usage": ("usage", "capture_usage"),
    "fetch_claude_usage": ("usage", "fetch_claude_usage"),
    "fetch_codex_usage": ("usage", "fetch_codex_usage"),
}

# Match the public names exposed by the former eager re-export module. Underscored
# compatibility names remain accessible explicitly, as they were before the facade.
__all__ = [
    "subprocess",
    "make_claude_scorer",
    "make_claude_cli_scorer",
    "make_codex_scorer",
    "ScoreError",
    "resolve_location",
    "SCREEN_SCHEMA",
    "demote_for_confirmation",
    "deterministic_screen",
    "make_ollama_extract",
    "merge_fallback_screen",
    "screen_posting",
    "screen_requires_provider",
    "sponsorship_snippets",
    "capture_usage",
    "fetch_claude_usage",
    "fetch_codex_usage",
]


def __getattr__(name: str) -> Any:
    """Load one compatibility export without importing unrelated fit resources."""
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    import_name = (
        f"ats_worker.{module_name}"
        if module_name == "screening" or module_name.startswith("screening.")
        else f"{__name__}.{module_name}"
    )
    module = importlib.import_module(import_name)
    value = getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
