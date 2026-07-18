"""Fetch adapters and shared post-processing for board APIs."""
from __future__ import annotations

from . import (ashby, greenhouse, icims, jobvite, lever, oracle, phenom,
               pinpoint, smartrecruiters, workable, workday)

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
    oracle.SOURCE: oracle,
    jobvite.SOURCE: jobvite,
}

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


def fetch_company(source: str, slug: str, company_name: str, **kwargs) -> list[dict]:
    """Dispatch to the per-board adapter for `source` (lists a whole board)."""
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}")
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
    "ADAPTERS", "DETAIL_SOURCES", "filter_postings",
    "fetch_company", "fetch_one_company",
    "ashby", "greenhouse", "lever", "workday", "pinpoint", "smartrecruiters",
    "workable", "icims", "phenom", "oracle", "jobvite",
]
