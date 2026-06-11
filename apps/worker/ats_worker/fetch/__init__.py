"""Fetch adapters and shared post-processing for board APIs."""
from __future__ import annotations

from . import ashby, greenhouse, lever

# source name -> adapter module (each exposes parse_jobs + fetch)
ADAPTERS = {
    greenhouse.SOURCE: greenhouse,
    lever.SOURCE: lever,
    ashby.SOURCE: ashby,
}


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
    """Dispatch to the adapter for `source`."""
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}")
    return adapter.fetch(slug, company_name, **kwargs)


__all__ = ["ADAPTERS", "filter_postings", "fetch_company", "ashby", "greenhouse", "lever"]
