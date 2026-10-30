"""Strict allowlisted candidate profile validation and deterministic rendering.

This module has no legacy scorer, resume, provider, or environment dependencies. The
rendered context is never truncated; callers may use an injected tokenizer to measure it
against a review budget before any provider request is designed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable
import unicodedata


class ProfileValidationError(ValueError):
    """The profile does not satisfy the allowlisted input contract."""


@dataclass(frozen=True)
class ProfileBlock:
    id: str
    text: str


@dataclass(frozen=True)
class CandidateProfile:
    schema: int
    version: str
    as_of: str
    status: str
    background: tuple[ProfileBlock, ...]
    preferences: tuple[ProfileBlock, ...]

    def canonical_json(self) -> str:
        """Return stable JSON while preserving the declared block order."""
        payload = {
            "schema": self.schema,
            "version": self.version,
            "as_of": self.as_of,
            "status": self.status,
            "background": [vars(block) for block in self.background],
            "preferences": [vars(block) for block in self.preferences],
        }
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


_TOP_LEVEL_KEYS = {"schema", "version", "as_of", "status", "background", "preferences"}
_BLOCK_KEYS = {"id", "text"}
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
PROFILE_RENDERER_VERSION = "candidate-context-v1"


def _object_without_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileValidationError("duplicate JSON object member")
        result[key] = value
    return result


def _expect_object(value: Any, required: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileValidationError(f"{path} must be an object")
    keys = set(value)
    if keys - required:
        raise ProfileValidationError(f"{path} contains an unknown field")
    if required - keys:
        raise ProfileValidationError(f"{path} is missing a required field")
    return value


def _valid_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ProfileValidationError(f"{path} must be non-empty trimmed text")
    if any(separator in value for separator in ("\n", "\r", "\u2028", "\u2029")):
        raise ProfileValidationError(f"{path} must be one paragraph")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise ProfileValidationError(f"{path} contains a control character")
    return value


def _blocks(value: Any, path: str, seen_ids: set[str]) -> tuple[ProfileBlock, ...]:
    if not isinstance(value, list):
        raise ProfileValidationError(f"{path} must be an array")
    blocks: list[ProfileBlock] = []
    for index, raw_block in enumerate(value):
        block_path = f"{path}[{index}]"
        block = _expect_object(raw_block, _BLOCK_KEYS, block_path)
        block_id = block["id"]
        if not isinstance(block_id, str) or not _ID_RE.fullmatch(block_id):
            raise ProfileValidationError(f"{block_path}.id is invalid")
        if block_id in seen_ids:
            raise ProfileValidationError("profile block IDs must be unique")
        seen_ids.add(block_id)
        blocks.append(ProfileBlock(block_id, _valid_text(block["text"], f"{block_path}.text")))
    return tuple(blocks)


def profile_from_value(value: Any) -> CandidateProfile:
    """Validate an already-decoded JSON value against the exact allowlist."""
    payload = _expect_object(value, _TOP_LEVEL_KEYS, "profile")

    schema = payload["schema"]
    if type(schema) is not int or schema != 1:
        raise ProfileValidationError("profile.schema must equal integer 1")

    version = payload["version"]
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ProfileValidationError("profile.version is invalid")

    as_of = payload["as_of"]
    if not isinstance(as_of, str) or not _DATE_RE.fullmatch(as_of):
        raise ProfileValidationError("profile.as_of must be YYYY-MM-DD")
    try:
        if date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError
    except ValueError as exc:
        raise ProfileValidationError("profile.as_of is not a calendar date") from exc

    status = payload["status"]
    if not isinstance(status, str) or status not in {"draft", "approved"}:
        raise ProfileValidationError("profile.status must be draft or approved")

    seen_ids: set[str] = set()
    background = _blocks(payload["background"], "profile.background", seen_ids)
    preferences = _blocks(payload["preferences"], "profile.preferences", seen_ids)
    return CandidateProfile(schema, version, as_of, status, background, preferences)


def load_profile_text(source: str) -> CandidateProfile:
    """Decode JSON while rejecting duplicate members, then validate the allowlist."""
    try:
        value = json.loads(source, object_pairs_hook=_object_without_duplicate_members)
    except ProfileValidationError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProfileValidationError("profile is not valid JSON") from exc
    return profile_from_value(value)


def load_profile(path: str) -> CandidateProfile:
    """Read one explicitly named UTF-8 JSON profile; no directory search or fallback."""
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProfileValidationError("profile file could not be read as UTF-8") from exc
    return load_profile_text(source)


def render_profile(profile: CandidateProfile) -> str:
    """Render all approved profile text in declared order, without lossy truncation."""
    background = "\n".join(block.text for block in profile.background)
    preferences = "\n".join(block.text for block in profile.preferences)
    return f"AS OF {profile.as_of}\nBACKGROUND\n{background}\nSEARCH\n{preferences}\n"


def measure_context(
    rendered_context: str,
    token_counter: Callable[[str], int],
    soft_limit: int = 2_000,
) -> dict[str, int | bool]:
    """Measure with an injected counter and report overflow without changing input."""
    if not callable(token_counter):
        raise TypeError("token_counter must be callable")
    if type(soft_limit) is not int or soft_limit <= 0:
        raise ValueError("soft_limit must be a positive integer")
    count = token_counter(rendered_context)
    if type(count) is not int or count < 0:
        raise ValueError("token_counter must return a non-negative integer")
    return {"token_count": count, "soft_limit": soft_limit, "over_budget": count > soft_limit}
