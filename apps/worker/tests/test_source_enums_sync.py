"""Guard: board-source allowlists and the low-context threshold must not drift
across the worker (config.py / fetch) and the web UI (constants.ts).
Mirrors test_schema_sync.py: text-parse the .ts, import the Python modules.

Scoped to the three genuinely-duplicated + cheaply-comparable items (Ponytail):
VALID_SOURCES, RECIPE_SOURCES, and the low-context length threshold. The scattered
pipeline_status vocabulary and the full notify/matched verdict-predicate SQL are
NOT guarded here — see docs/PROGRESS.md.
"""
from __future__ import annotations

import re
from pathlib import Path

from ats_worker import config, fetch, db

CONSTANTS_TS = Path(__file__).parents[3] / "apps" / "web" / "src" / "lib" / "constants.ts"


def _ts_array(name: str) -> list[str]:
    m = re.search(rf"export const {name}\s*=\s*\[(.*?)\]", CONSTANTS_TS.read_text(), re.S)
    assert m, f"{name} not found in constants.ts"
    return re.findall(r"'([^']+)'", m.group(1))


def _ts_int(name: str) -> int:
    m = re.search(rf"export const {name}\s*=\s*(\d+)", CONSTANTS_TS.read_text())
    assert m, f"{name} not found in constants.ts"
    return int(m.group(1))


def test_valid_sources_match_web():
    assert list(config.VALID_SOURCES) == _ts_array("VALID_SOURCES")


def test_recipe_sources_match_web_and_fetch():
    assert list(config.RECIPE_SOURCES) == _ts_array("RECIPE_SOURCES")
    assert set(config.RECIPE_SOURCES) == set(fetch.RECIPE_SOURCES)


def test_valid_sources_are_real_adapters():
    assert set(config.VALID_SOURCES) <= set(fetch.ADAPTERS)


def test_low_context_threshold_matches_web():
    src = Path(db.__file__).read_text()
    m = re.search(r"LENGTH\(TRIM\(description\)\)\s*>=\s*(\d+)", src)
    assert m, "low-context length clause not found in db.get_notifiable"
    assert int(m.group(1)) == _ts_int("LOW_CONTEXT_MAX_DESCRIPTION_LENGTH")
