"""Legacy fit scorer. Screening lives in `ats_worker.screening`, quota telemetry in
`ats_worker.usage`.

Fit exports are resolved only when requested: importing this package or its neutral
exception module must not load fit backends or the legacy fit prompts.
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
    "_SCORE_SCHEMA": ("prompts", "_SCORE_SCHEMA"),
    "_score_schema": ("prompts", "_score_schema"),
    "_scorer_system_blocks": ("prompts", "_scorer_system_blocks"),
    "_scorer_system_sections": ("prompts", "_scorer_system_sections"),
    "_normalize_score": ("screen", "_normalize_score"),
    "demote_for_confirmation": ("screen", "demote_for_confirmation"),
    "merge_fallback_screen": ("screen", "merge_fallback_screen"),
}

# Public submodule attributes, loaded on first access rather than with the package.
_LAZY_SUBMODULES = {
    name: name
    for name in (
        "backends_claude",
        "backends_claude_cli",
        "backends_codex",
        "errors",
        "prompts",
        "screen",
    )
}

# Match the public names exposed by the former eager re-export module. Underscored
# compatibility names remain accessible explicitly, as they were before the facade.
__all__ = [
    "subprocess",
    "backends_claude",
    "backends_claude_cli",
    "backends_codex",
    "errors",
    "prompts",
    "screen",
    "make_claude_scorer",
    "make_claude_cli_scorer",
    "make_codex_scorer",
    "ScoreError",
    "demote_for_confirmation",
    "merge_fallback_screen",
]


def __getattr__(name: str) -> Any:
    """Load one compatibility export without importing unrelated fit resources."""
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f"{__name__}.{_LAZY_SUBMODULES[name]}")
        globals()[name] = module
        return module
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS) | set(_LAZY_SUBMODULES))
