"""Guard: board-source allowlists and the low-context threshold must not drift
across the worker (config.py / fetch), the web UI (constants.ts), and SPEC's
hand-maintained source-coverage matrix.
Mirrors test_schema_sync.py: text-parse the .ts/.md, import the Python modules.

Scoped to the genuinely-duplicated + cheaply-comparable items (Ponytail):
VALID_SOURCES, RECIPE_SOURCES, the low-context length threshold, and the SPEC
matrix. The scattered pipeline_status vocabulary and the full notify/matched
verdict-predicate SQL are NOT guarded here — see docs/PROGRESS.md.
"""
from __future__ import annotations

import re
from pathlib import Path

from ats_worker import config, fetch, db

CONSTANTS_TS = Path(__file__).parents[3] / "apps" / "web" / "src" / "lib" / "constants.ts"
SPEC_MD = Path(__file__).parents[3] / "docs" / "SPEC.md"


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


def test_watchlist_sources_can_list():
    # A watchlist source is enumerated per BOARD, so its adapter must expose `fetch`;
    # a feed-only source (oracle/jobvite) has only `fetch_one` and must stay out.
    missing = [s for s in config.VALID_SOURCES
               if not callable(getattr(fetch.ADAPTERS[s], "fetch", None))]
    assert not missing, f"watchlist sources with no adapter.fetch: {missing}"


def _spec_matrix() -> list[tuple[str, str, str]]:
    """(source, adapter cell, watchlist cell) per row of SPEC's source-coverage matrix.
    ponytail: the source name is the platform label's first word, lowercased and
    stripped to alnum ('Oracle Cloud HCM' -> oracle, 'Custom (recipe)' -> custom) —
    a convention, not a second mapping table. Rows routed through another module's
    adapter ('via greenhouse') own no source name and are skipped."""
    text = SPEC_MD.read_text()
    start = text.index("| Platform | Host(s) | Adapter | Feed router | Watchlist |")
    rows = []
    for line in text[start:].splitlines()[2:]:
        if not line.strip().startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[2].startswith("via "):
            continue
        rows.append((re.sub(r"[^a-z0-9]", "", cells[0].split()[0].lower()),
                     cells[2], cells[4]))
    return rows


def test_spec_matrix_matches_adapters():
    rows = _spec_matrix()
    assert len(rows) > 5, "SPEC source-coverage matrix failed to parse"
    assert {r[0] for r in rows} == set(fetch.ADAPTERS)
    assert {r[0] for r in rows if r[2].startswith("yes")} == set(config.VALID_SOURCES)


def test_low_context_threshold_matches_web():
    # The worker now names the threshold once (db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH,
    # used by both get_notifiable's SQL and pipeline.run_score's pre-fit gate); assert
    # that single constant equals the web's, rather than regexing the SQL literal.
    assert db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH == _ts_int(
        "LOW_CONTEXT_MAX_DESCRIPTION_LENGTH")
