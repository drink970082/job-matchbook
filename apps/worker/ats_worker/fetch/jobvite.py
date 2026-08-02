"""Jobvite career-site adapter — feed-only (per-listing).

Jobvite has no public job-LIST JSON API, but every public job page embeds a
schema.org JobPosting as JSON-LD. So this adapter exposes `fetch_one` (one job by
id) for the feed's detail-fetch path; it is NOT watchlist-capable.

  page: GET https://jobs.jobvite.com/{slug}/job/{id}
        -> <script type="application/ld+json"> {"@type":"JobPosting", ...} </script>
"""
from __future__ import annotations

import json
import re

import requests

from ats_worker.util import html_to_text, join_present, to_iso_date

SOURCE = "jobvite"
PAGE = "https://jobs.jobvite.com/{slug}/job/{id}"
_LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _job_posting_ld(html_text: str) -> dict | None:
    """Return the first JSON-LD block whose @type is JobPosting, else None."""
    for m in _LDJSON_RE.finditer(html_text or ""):
        try:
            data = json.loads(m.group(1).strip())
        except (ValueError, TypeError):
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if isinstance(obj, dict) and "JobPosting" in str(obj.get("@type", "")):
                return obj
    return None


def _location(ld: dict) -> str | None:
    """First jobLocation's "locality, region, country", or None."""
    locs = ld.get("jobLocation")
    for loc in (locs if isinstance(locs, list) else [locs]):
        addr = (loc or {}).get("address") if isinstance(loc, dict) else None
        if isinstance(addr, dict):
            joined = join_present(
                addr, ("addressLocality", "addressRegion", "addressCountry"))
            if joined:
                return joined
    return None


def parse_page(html_text: str, slug: str, external_id: str,
               company_name: str) -> dict | None:
    """Build one canonical posting from a job page's JSON-LD, or None if absent."""
    ld = _job_posting_ld(html_text)
    if ld is None:
        return None
    return {
        "source": SOURCE,
        "external_id": str(external_id),
        "company_name": company_name,
        "job_title": (ld.get("title") or "").strip(),
        "location": _location(ld),
        "job_url": PAGE.format(slug=slug, id=external_id),
        "description": html_to_text(ld.get("description")),
        "posted_at": to_iso_date(ld.get("datePosted")),
    }


def fetch_one(slug: str, external_id: str, company_name: str,
              session: requests.Session | None = None,
              timeout: int = 20) -> dict | None:
    http = session or requests
    if not slug or not external_id:
        return None
    resp = http.get(PAGE.format(slug=slug, id=external_id), timeout=timeout)
    resp.raise_for_status()
    return parse_page(resp.text, slug, external_id, company_name)
