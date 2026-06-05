"""Fetch adapters and shared post-processing for board APIs."""
from __future__ import annotations

from . import ashby, greenhouse, lever

# source name -> adapter module (each exposes parse_jobs + fetch)
ADAPTERS = {
    greenhouse.SOURCE: greenhouse,
    lever.SOURCE: lever,
    ashby.SOURCE: ashby,
}


def filter_postings(
    postings: list[dict],
    keywords: list[str] | None,
    locations: list[str] | None,
) -> list[dict]:
    """Keep postings matching ANY keyword (in title or description) AND, if
    locations are given, ANY location substring. Both checks are
    case-insensitive. A criterion that is None/empty is treated as "match all".
    """
    kws = [k.lower() for k in (keywords or []) if k]
    locs = [l.lower() for l in (locations or []) if l]

    def keep(p: dict) -> bool:
        if kws:
            haystack = f"{p.get('job_title', '')}\n{p.get('description', '')}".lower()
            if not any(k in haystack for k in kws):
                return False
        if locs:
            loc = (p.get("location") or "").lower()
            if not any(l in loc for l in locs):
                return False
        return True

    return [p for p in postings if keep(p)]


def fetch_company(source: str, slug: str, company_name: str, **kwargs) -> list[dict]:
    """Dispatch to the adapter for `source`."""
    try:
        adapter = ADAPTERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}")
    return adapter.fetch(slug, company_name, **kwargs)


__all__ = ["ADAPTERS", "filter_postings", "fetch_company", "ashby", "greenhouse", "lever"]
