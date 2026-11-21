"""Validate a `custom`/`browser` watchlist recipe against the committed JSON Schema.

The schema is web-owned (apps/web/src/lib/recipe.schema.json, beside the TS validator
the web add path uses), the same way Prisma owns the table schema; the worker reads it
from the checkout. Entry points on this side: `fetch_company` before any request (an
invalid stored row is a per-board error the pass logs and skips), the config.yaml seed,
and onboard-board's add_watched.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "recipe.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

# One validator per recipe source: the source picks $defs.<source>.
_VALIDATORS = {
    source: Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{source}"})
    for source in ("custom", "browser")
}


def errors(source: str, recipe) -> list[str]:
    """Every schema violation as '<dotted.path>: <message>'. [] when valid, and for a
    source that takes no recipe."""
    validator = _VALIDATORS.get(source)
    if validator is None:
        return []
    out = []
    for e in sorted(validator.iter_errors(recipe), key=lambda e: list(map(str, e.path))):
        where = ".".join(str(p) for p in e.path) or "recipe"
        out.append(f"{where}: {e.message}")
    return out


def check(source: str, recipe) -> None:
    """Raise ValueError naming every violation."""
    errs = errors(source, recipe)
    if errs:
        raise ValueError(f"invalid {source} recipe: " + "; ".join(errs))
