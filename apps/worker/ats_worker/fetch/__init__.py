"""Fetch adapters and shared post-processing for board APIs."""
from __future__ import annotations

import re
from datetime import date

from . import (ashby, browser, custom, greenhouse, icims, jobvite, lever, oracle,
               phenom, pinpoint, smartrecruiters, workable, workday)

# source name -> adapter module. Per-BOARD adapters expose `fetch` (list a board);
# per-LISTING adapters expose `fetch_one` (one job by id, for boards with no public
# list endpoint). Some sources are feed-only (per-listing) and so stay out of
# config.VALID_SOURCES — they can't be enumerated as a watchlist company.
ADAPTERS = {
    greenhouse.SOURCE: greenhouse,
    lever.SOURCE: lever,
    ashby.SOURCE: ashby,
    workday.SOURCE: workday,
    pinpoint.SOURCE: pinpoint,
    smartrecruiters.SOURCE: smartrecruiters,
    workable.SOURCE: workable,
    icims.SOURCE: icims,
    phenom.SOURCE: phenom,
    custom.SOURCE: custom,
    browser.SOURCE: browser,
    oracle.SOURCE: oracle,
    jobvite.SOURCE: jobvite,
}

# Sources whose fetch takes a declarative `recipe` kwarg (custom + browser). The
# dispatcher passes `recipe` only to these — plain adapters would reject the kwarg.
RECIPE_SOURCES = frozenset({"custom", "browser"})

# Sources whose fetch accepts a `keep` stub-gate predicate — the two-step (N+1)
# adapters where skipping a per-item detail call is the dominant saving. Passed
# only to these; every other adapter's fetch would reject the kwarg. `workday`
# honours ONLY the 'drop' verdict: its list stub carries no GUID, so a STORED stub
# would key on jobReqId and could double-insert — but a dropped one is never
# stored, so it has no id to reconcile (see the 2026-07-21 stub-gate design).
STUB_GATE_SOURCES = frozenset({"phenom", "workday", "icims"})

# Of those, the ones whose fetch also accepts `now`: workday's list stub dates
# itself in relative prose ("Posted 30+ Days Ago"), so parse_stub needs the
# injected clock to turn it into a date the max-age gate can read. Every other
# stub-gate adapter's fetch would reject the kwarg. Declared here, next to the
# dispatch table, so the orchestration layer selects by membership instead of
# naming a board (test_no_source_specific_logic).
STUB_GATE_NOW_SOURCES = frozenset({"workday"})

# Sources fetched ONE job at a time (no public board-list endpoint), via
# adapter.fetch_one. The feed's detail-fetch path routes these.
DETAIL_SOURCES = frozenset(s for s, m in ADAPTERS.items() if hasattr(m, "fetch_one"))


def filter_postings(postings: list[dict], title_filter: list[str] | None) -> list[dict]:
    """Keep postings whose TITLE contains ANY keyword (case-insensitive).
    None/empty keeps everything.

    This is only a cheap coarse pre-filter to avoid scoring obviously-irrelevant
    roles; the LLM scorer does the real relevance judging. Title-only (not
    description) on purpose — matching the description makes common words like
    "engineer" match almost every JD, which filters nothing. Geography is handled
    semantically by the scorer via candidate.locations, not here.
    """
    kws = [k.lower() for k in (title_filter or []) if k]
    if not kws:
        return list(postings)
    return [
        p for p in postings
        if any(k in (p.get("job_title") or "").lower() for k in kws)
    ]


def _too_old(posted_at, now, max_age_days: int) -> bool:
    """True only when posted_at is a parseable date strictly older than max_age_days.
    A null/empty/unparseable date or max_age_days<=0 is never 'too old' (err toward keep)."""
    if not max_age_days or not posted_at:
        return False
    try:
        posted = date.fromisoformat(str(posted_at)[:10])
        today = date.fromisoformat(str(now)[:10])
    except ValueError:
        return False  # unparseable -> keep
    return (today - posted).days > max_age_days


def exclude_matcher(title_exclude):
    """WORD-boundary matcher for `title_exclude`, or None when the list is empty.

    Deliberately NOT the substring rule `filter_postings` uses, and the asymmetry is
    measured (11,675 titles, 2026-08-02). The POSITIVE filter needs substring as a
    stemmer: `quant` catches 436 titles where a word match catches 40, and the 396
    "Quantitative ..." rows it would lose are the whole point of this tool ("research"
    -> "Researcher" is 265 more, "engineer" -> "Engineering" 747). The EXCLUDE list
    needs the opposite — precision. 13 of the 15 keys shipped before this change matched
    identically either way; `intern` was the exception, and it was eating
    "International Sector Analyst" and "Software Developer - Internal Compute Frameworks
    (Python)", which is a tier-2 target. Word matching also unlocks the short tokens a
    substring rule cannot safely carry: `sr` (else SRAM, SRE), `ios` (BIOS, Biosciences,
    Portfolios), `ii`, `vp`, `lead` (Leadership).

    The trade: a key no longer stems, so an operator wanting "robotics" must say
    "robotics" and not rely on "robot", and internships need both `intern` and
    `internship`. That is the intended direction — an exclude that over-reaches is
    invisible, because the posting it wrongly ate never appears anywhere to be noticed.

    Lookarounds rather than `\\b`: a key ending in punctuation ("co-op", "ai/ml") has no
    word boundary after its final character, so `\\b` would never match it at all.
    """
    keys = [k.strip().lower() for k in (title_exclude or []) if k and k.strip()]
    if not keys:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
                      re.IGNORECASE)


def prefilter_postings(postings, *, title_filter=None, title_exclude=None,
                       max_age_days=0, now=None):
    """Fetch-time coarse pre-filter (deterministic, no LLM). Drops a posting when it
    fails the positive title keep-list, its title carries a title_exclude keyword as a
    WHOLE WORD (see `exclude_matcher` — the keep-list is substring, this is not), or its
    posted_at is older than max_age_days (null/unparseable posted_at kept). Title
    matching is case-insensitive and title-only, like filter_postings."""
    kept = filter_postings(postings, title_filter)
    excl = exclude_matcher(title_exclude)
    out = []
    for p in kept:
        title = p.get("job_title") or ""
        if excl is not None and excl.search(title):
            continue
        if _too_old(p.get("posted_at"), now, max_age_days):
            continue
        out.append(p)
    return out


def fetch_company(source: str, slug: str, company_name: str, *,
                  recipe: dict | None = None, keep=None, **kwargs) -> list[dict]:
    """Dispatch to the per-board adapter for `source` (lists a whole board).

    `recipe` is forwarded only to the recipe-driven executors (custom/browser) and
    `keep` only to the stub-gate adapters; plain adapters accept neither, so each
    is dropped for them."""
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}")
    if keep is not None and source in STUB_GATE_SOURCES:
        kwargs["keep"] = keep
    if source in RECIPE_SOURCES:
        return adapter.fetch(slug, company_name, recipe=recipe, **kwargs)
    return adapter.fetch(slug, company_name, **kwargs)


def fetch_one_company(source: str, slug: str, external_id: str,
                      company_name: str, **kwargs) -> dict | None:
    """Dispatch to the per-listing adapter for `source` (one job by id)."""
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}")
    if not hasattr(adapter, "fetch_one"):
        raise ValueError(f"source {source!r} has no per-listing fetch_one")
    return adapter.fetch_one(slug, external_id, company_name, **kwargs)


__all__ = [
    "ADAPTERS", "DETAIL_SOURCES", "STUB_GATE_SOURCES", "STUB_GATE_NOW_SOURCES",
    "filter_postings", "prefilter_postings",
    "fetch_company", "fetch_one_company",
    "ashby", "greenhouse", "lever", "workday", "pinpoint", "smartrecruiters",
    "workable", "icims", "phenom", "custom", "browser", "oracle", "jobvite",
]
