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
               if not callable(getattr(fetch.ADAPTERS.get(s), "fetch", None))]
    assert not missing, f"watchlist sources with no adapter.fetch: {missing}"


MATRIX_HEADER = "| Platform | Host(s) | Adapter | Feed router | Watchlist |"


def _cell(text: str) -> str:
    """Normalize one table cell. A guard that reds CI because someone bolded a word or
    backticked a term is worse than no guard, so the markup a legitimate docs edit adds
    is stripped before comparison: `code`, **bold**, and [label](url) -> label."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.replace("`", "").replace("**", "").strip()


def _spec_matrix() -> list[tuple[str, str]]:
    """(source, watchlist cell) per row of SPEC's source-coverage matrix.

    ponytail: the source name is the platform label's first word, lowercased and
    stripped to alnum ('Oracle Cloud HCM' -> oracle, 'Custom (recipe)' -> custom) — a
    convention, not a second mapping table. It has known limits: a platform whose source
    name is not its first word ('SAP SuccessFactors' -> sap) breaks it. That is a LOUD
    failure at the moment someone adds such a source, which is the right time to revisit
    the convention. Rows routed through another module's adapter ('via greenhouse') own
    no source name and are skipped.
    """
    text = SPEC_MD.read_text()
    assert MATRIX_HEADER in text, (
        f"source-coverage matrix header not found in {SPEC_MD}; if the columns changed, "
        f"update MATRIX_HEADER and this parser together")
    rows = []
    for line in text[text.index(MATRIX_HEADER):].splitlines()[2:]:
        line = line.strip()
        if not line.startswith("|"):
            break
        # Split on UNESCAPED pipes only: `\|` is the sole legal way to put a literal
        # pipe in a GFM cell, and Host(s) is exactly where one would appear. Splitting
        # naively shifts every later index, so the watchlist column would be read from
        # Feed router — a silently WRONG value rather than a failure.
        cells = [_cell(c) for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        assert len(cells) == 5, f"expected 5 cells, got {len(cells)}: {line}"
        if cells[2].lower().startswith("via "):
            continue
        rows.append((re.sub(r"[^a-z0-9]", "", cells[0].split()[0].lower()), cells[4]))
    return rows


def test_spec_matrix_matches_adapters():
    # Guards the Platform and Watchlist columns ONLY. Adapter, Host(s) and Feed router
    # are read by no assertion: `resolve_url` is a URL-pattern parser rather than a
    # registry, and the adapter cell's prose ('list', 'detail (`fetch_one`)') has no
    # single source of truth to compare against. Say so in SPEC too — claiming more
    # coverage than this has is how a matrix guard rots.
    rows = _spec_matrix()
    assert len(rows) == len(fetch.ADAPTERS), (
        f"parsed {len(rows)} matrix rows for {len(fetch.ADAPTERS)} adapters — a "
        f"truncated parse or a duplicate platform name")
    assert {r[0] for r in rows} == set(fetch.ADAPTERS)
    assert {r[0] for r in rows if r[1].lower().startswith("yes")} == set(config.VALID_SOURCES)


def test_low_context_threshold_matches_web():
    # The worker now names the threshold once (db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH,
    # used by both get_notifiable's SQL and pipeline.run_score's pre-fit gate); assert
    # that single constant equals the web's, rather than regexing the SQL literal.
    assert db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH == _ts_int(
        "LOW_CONTEXT_MAX_DESCRIPTION_LENGTH")
