"""The screen provider registry: one row per SCREEN_BACKEND value.

Stdlib-only at import time so `doctor` can list the rows on a checkout whose deps are
missing; each `build` imports its adapter lazily. Adding a provider = one row here
plus its adapter in `screening.backends` plus tests.

Backends: two subscription CLIs (`codex`, `claude-code`), the local free default
(`ollama`, native /api/chat so `num_ctx` and thinking-off still apply), one generic
OpenAI-compatible `api` backend for every hosted vendor (OpenAI, OpenRouter, Gemini,
LM Studio, vLLM, ...), and `none` (deterministic gates only).

AUTO-DETECTION MUST NEVER SELECT A PAID BACKEND: the default stays `ollama` and the
operator opts in to anything else explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_API_BASE_URL = "https://api.openai.com/v1"

# Retired values -> what replaces them; `run.main` fails startup with this hint.
RETIRED = {"openai-api": "api", "claude-api": "api (e.g. via OpenRouter)"}


@dataclass(frozen=True)
class Provider:
    name: str
    # (env, http, model, effort, num_ctx) -> extract callable, or None for `none`
    build: Callable
    default_model: str | None
    paid: bool
    doctor_hint: str          # what the backend needs, shown by `doctor`
    quota: bool = False       # has a subscription usage fetcher (usage._FETCHERS)
    effort: bool = False      # honours --screen-effort
    model_required: bool = False


def _ollama(env, http, model, effort, num_ctx):
    from .screening import make_ollama_extract
    return make_ollama_extract(http=http, model=model, num_ctx=num_ctx,
                               ollama_host=env.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST))


def _codex(env, http, model, effort, num_ctx):
    from .screening import make_codex_extract
    if effort is None:
        return make_codex_extract(model)
    return make_codex_extract(model, reasoning_effort=effort)


def _claude_code(env, http, model, effort, num_ctx):
    from .screening import make_claude_code_extract
    return make_claude_code_extract(model)


def _api(env, http, model, effort, num_ctx):
    from .screening import make_api_extract
    return make_api_extract(
        base_url=(env.get("SCREEN_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/"),
        api_key=env.get("SCREEN_API_KEY") or None, model=model, http=http)


PROVIDERS: dict[str, Provider] = {p.name: p for p in (
    Provider("ollama", _ollama, "qwen3.5:4b", paid=False,
             doctor_hint="a running Ollama (OLLAMA_HOST)"),
    Provider("codex", _codex, "gpt-5.6-luna", paid=False, quota=True, effort=True,
             doctor_hint="the codex CLI, logged in (ChatGPT subscription)"),
    Provider("claude-code", _claude_code, None, paid=False, quota=True,
             doctor_hint="the claude CLI, logged in (Claude subscription)"),
    Provider("api", _api, None, paid=True, model_required=True,
             doctor_hint="SCREEN_MODEL, plus SCREEN_API_BASE_URL (default OpenAI) and "
                         "SCREEN_API_KEY (omit for a keyless local server)"),
    Provider("none", lambda *_: None, None, paid=False,
             doctor_hint="nothing (deterministic gates only; LOW RECALL on sponsorship)"),
)}
