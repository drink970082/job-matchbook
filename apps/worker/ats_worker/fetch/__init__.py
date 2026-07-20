"""Fetch adapters and shared post-processing for board APIs."""
from __future__ import annotations

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


def prefilter_postings(postings, *, title_filter=None, title_exclude=None,
                       max_age_days=0, now=None):
    """Fetch-time coarse pre-filter (deterministic, no LLM). Drops a posting when it
    fails the positive title keep-list, its title contains a title_exclude keyword,
    or its posted_at is older than max_age_days (null/unparseable posted_at kept).
    Title matching is case-insensitive and title-only, like filter_postings."""
    kept = filter_postings(postings, title_filter)
    excl = [k.lower() for k in (title_exclude or []) if k]
    out = []
    for p in kept:
        title = (p.get("job_title") or "").lower()
        if any(k in title for k in excl):
            continue
        if _too_old(p.get("posted_at"), now, max_age_days):
            continue
        out.append(p)
    return out


def fetch_company(source: str, slug: str, company_name: str, *,
                  recipe: dict | None = None, **kwargs) -> list[dict]:
    """Dispatch to the per-board adapter for `source` (lists a whole board).

    `recipe` is forwarded only to the recipe-driven executors (custom/browser);
    plain adapters don't accept it, so it's dropped for them."""
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}")
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
    "ADAPTERS", "DETAIL_SOURCES", "filter_postings", "prefilter_postings",
    "fetch_company", "fetch_one_company",
    "ashby", "greenhouse", "lever", "workday", "pinpoint", "smartrecruiters",
    "workable", "icims", "phenom", "custom", "browser", "oracle", "jobvite",
]
