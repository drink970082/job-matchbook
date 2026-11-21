"""Provider response errors raised by the screen backends, and the closed category
vocabulary a provider failure is recorded under."""
from __future__ import annotations

import re

# Every category a screen provider failure can be stored or counted as. Names the
# cause so an expired login or a stopped Ollama reads as such, never as raw text.
PROVIDER_ERROR_CATEGORIES = frozenset({
    "provider_error", "timeout", "executable_missing", "screen_error",
    "provider_auth", "provider_unreachable", "quota_exhausted",
})


class ScoreError(RuntimeError):
    """A model provider returned output that cannot be used safely. `category`, when
    the raiser knows the cause, is one of PROVIDER_ERROR_CATEGORIES."""

    def __init__(self, *args, category: str | None = None):
        super().__init__(*args)
        assert category is None or category in PROVIDER_ERROR_CATEGORIES
        self.category = category


# Keep the legacy exception's runtime name while exposing its neutral ownership.
ModelResponseError = ScoreError

_UNREACHABLE_NAMES = {"ConnectionError", "ConnectTimeout", "NewConnectionError",
                      "MaxRetryError"}
_TIMEOUT_NAMES = {"TimeoutError", "TimeoutExpired", "ReadTimeout", "Timeout"}


def _one(exc: BaseException) -> str | None:
    if isinstance(exc, ScoreError) and exc.category:
        return exc.category
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return "provider_auth"
    if status == 429:
        return "quota_exhausted"
    name = type(exc).__name__
    if name in _TIMEOUT_NAMES:
        return "timeout"
    if isinstance(exc, ConnectionError) or name in _UNREACHABLE_NAMES:
        return "provider_unreachable"
    if isinstance(exc, FileNotFoundError):
        return "executable_missing"
    return None


def provider_failure_category(exc: BaseException | None) -> str:
    """The closed category for a provider failure, walking the exception's cause chain
    (a backend wraps the transport error). Reads types and status codes only, never the
    message, which can echo job text or credentials."""
    seen = 0
    while exc is not None and seen < 10:
        category = _one(exc)
        if category:
            return category
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return "provider_error"


# Phrases, not bare words: stderr can echo prompt text, and a JD says "401(k)" and
# "sales quota". A status number only counts next to an HTTP/status/error word.
_STATUS = r"(?:http|status|error|code)[\s:/=.\d]*\b{}\b"
_CLI_QUOTA = re.compile("|".join((
    r"usage limit", r"rate[ -]limit(?:ed| exceeded| reached)?\b", r"insufficient_quota",
    r"quota (?:exceeded|exhausted)", _STATUS.format(429))))
_CLI_AUTH = re.compile("|".join((
    r"not logged in", r"please (?:log ?in|sign in)", r"login required", r"run `?\S+ login",
    r"unauthori[sz]ed", r"authentication (?:failed|required|error)",
    r"token (?:has )?expired", _STATUS.format(401))))
_CLI_TAIL_LINES = 5


def cli_failure_category(stderr: str) -> str | None:
    """Best-effort cause of a non-zero CLI exit, read from the last few stderr lines
    only (stdout carries model output, earlier stderr can echo the prompt). The markers
    are not verified against every CLI version; no match leaves the failure
    uncategorized (`provider_error`)."""
    text = "\n".join((stderr or "").strip().lower().splitlines()[-_CLI_TAIL_LINES:])
    if _CLI_QUOTA.search(text):
        return "quota_exhausted"
    if _CLI_AUTH.search(text):
        return "provider_auth"
    return None
