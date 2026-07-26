"""Architecture guard: the orchestration layer must stay source-agnostic.

The worker has 11 platform adapters plus the generic custom/browser recipe
executors. Which adapter runs is decided by DATA - the watchlist row's `source`
column is looked up in `fetch.ADAPTERS` - never by the orchestration layer
naming a board. `pipeline.py` (what to do) and `db.py` (rows in/out) therefore
contain no board names at all: adding a 12th adapter must not require editing
either file. This test fails the moment someone special-cases a source there,
e.g. `if source == "greenhouse": ...`.

WHAT IT CATCHES: any board name from the derived source list appearing as a
word (or an underscore-joined word part) anywhere in the EXECUTABLE code of the
two guarded files - identifiers, string literals, imports. `if source ==
"greenhouse"`, `GREENHOUSE_SLUG`, `from .fetch import lever` all fail.

WHAT IT DOES NOT CATCH, on purpose:
  - Comments and docstrings. Prose that names a board while explaining why the
    generic path exists ("no board-list endpoint, like workday") is not
    coupling, and pipeline.py has several such comments today. They are
    stripped before the scan.
  - Source-specific behavior expressed WITHOUT the name: a magic slug, a
    per-source `if` keyed off some other attribute, or a name assembled from
    fragments. This is a cheap syntactic guard, not a proof.
  - Every other module. `fetch/__init__.py` (the dispatch table), `config.py`
    (the allowlist) and `run.py` (real-service wiring) are the layers that are
    ALLOWED to know board names - that is exactly why the pipeline does not.

The source list is DERIVED from the code (fetch.ADAPTERS, the dispatch table
itself, unioned with the config allowlists), so a newly added adapter is
covered by this test automatically, with no edit here.

Known exceptions live in ALLOWED below, each with a reason. Weaken the scan
only by adding an entry there - never by loosening the matcher.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from ats_worker import config, fetch

WORKER = Path(__file__).parents[1] / "ats_worker"

# The orchestration layer: what runs, and what is persisted. Neither may know a
# board by name.
GUARDED = ("pipeline.py", "db.py")

# Derived, not hard-coded: fetch.ADAPTERS is the dispatch table (every adapter,
# including the feed-only ones), unioned with the config allowlists in case one
# ever carries a name the table does not.
SOURCES = frozenset(fetch.ADAPTERS) | frozenset(config.VALID_SOURCES) | frozenset(
    config.RECIPE_SOURCES)

# word -> reason. Keyed by the whole identifier/literal word, per file, so the
# exception is narrow: `embedded_greenhouse` is allowed, bare `greenhouse` is
# not. Occurrence counts are deliberately NOT pinned - moving an allowed word
# around is refactoring, not new coupling.
ALLOWED: dict[str, dict[str, str]] = {
    "pipeline.py": {
        # A fail-bucket LABEL from feed.resolve.classify_reason, not adapter
        # dispatch: the reason vocabulary is {workday_deferred,
        # embedded_greenhouse, unsupported_host} and run_feed branches on it to
        # hand the URL to the INJECTED resolve_embedded_fn (real only in
        # run.py) instead of recording it unresolved. The pipeline still names
        # no adapter and imports none; it forwards a label it got from a feed
        # module. Borderline by design - if the reason vocabulary ever grows a
        # second board-named member, prefer a source-free label (e.g.
        # "slug_in_page_html") over a second entry here.
        "embedded_greenhouse": "feed unresolved-reason label, not adapter dispatch",
    },
}


def _code_words(path: Path) -> list[tuple[int, str]]:
    """Yield (lineno, word) for every word in the file's executable code.

    Comments and module/class/function docstrings are dropped - they are prose.
    Every other token counts, string literals included, since `"greenhouse"` in
    a comparison is the exact thing being forbidden.
    """
    src = path.read_text()
    docstrings = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstrings.add((body[0].value.lineno, body[0].value.col_offset))

    words: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start in docstrings:
            continue
        for word in re.findall(r"[A-Za-z0-9_]+", tok.string):
            words.append((tok.start[0], word))
    return words


def _hits(word: str) -> list[str]:
    """Source names occurring in `word` as an alnum-delimited part.

    Underscore counts as a delimiter, so `embedded_greenhouse` and
    `GREENHOUSE_SLUG` are hits; plain English that merely contains a name
    (`leverage`, `customer`, `browsers`) is not.
    """
    low = word.lower()
    return sorted(s for s in SOURCES
                  if re.search(rf"(?<![a-z0-9]){s}(?![a-z0-9])", low))


def test_no_source_specific_logic():
    # Non-vacuity: the derived list must be real, or every scan below passes for
    # free.
    assert len(SOURCES) >= 10, f"source list looks truncated: {sorted(SOURCES)}"
    assert "greenhouse" in SOURCES, sorted(SOURCES)

    violations: list[str] = []
    seen_allowed: dict[str, set[str]] = {f: set() for f in GUARDED}

    for fname in GUARDED:
        path = WORKER / fname
        assert path.exists(), f"guarded file missing: {path}"
        words = _code_words(path)
        # Non-vacuity: a file that yielded no code words would pass silently.
        assert len(words) > 100, f"{fname}: only {len(words)} code words scanned"
        allowed = ALLOWED.get(fname, {})
        for lineno, word in words:
            hits = _hits(word)
            if not hits:
                continue
            if word.lower() in allowed:
                seen_allowed[fname].add(word.lower())
                continue
            violations.append(
                f"{fname}:{lineno}: {word!r} names source(s) {hits}")

    assert not violations, (
        "the orchestration layer must not name a board source - dispatch "
        "adapters by data (the watchlist row's `source` through fetch.ADAPTERS), "
        "not by name:\n  " + "\n  ".join(violations))

    # Keep the allowlist honest: an entry that no longer matches anything is a
    # stale exception and should be deleted.
    for fname, allowed in ALLOWED.items():
        stale = sorted(set(allowed) - seen_allowed.get(fname, set()))
        assert not stale, (
            f"ALLOWED[{fname!r}] entries no longer occur in the file - delete "
            f"them: {stale}")
