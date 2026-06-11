"""Pinpoint public job board API adapter.

Endpoint: https://{slug}.pinpointhq.com/postings.json
Returns {"data": [...]}. Each posting splits its JD across several HTML sections
(`description`, `key_responsibilities`, `skills_knowledge_expertise`) which we
merge into one readable block, plus a `location` object and a hosted `url`.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text

SOURCE = "pinpoint"
API = "https://{slug}.pinpointhq.com/postings.json"

# JD sections to merge, in reading order (benefits/perks are boilerplate, skipped).
_DESC_PARTS = ("description", "key_responsibilities", "skills_knowledge_expertise")


def parse_jobs(payload: dict, company_name: str) -> list[dict]:
    jobs = payload.get("data", []) if isinstance(payload, dict) else []
    out: list[dict] = []
    for j in jobs:
        url = j.get("url") or ""
        if not url:
            continue  # m2: a linkless posting is an unclickable record; drop it
        loc = j.get("location") or {}
        location = loc.get("name") if isinstance(loc, dict) else loc
        body = "\n\n".join(j[k] for k in _DESC_PARTS if j.get(k))
        out.append(
            {
                "source": SOURCE,
                "external_id": str(j["id"]),
                "company_name": company_name,
                "job_title": (j.get("title") or "").strip(),
                "location": location or None,
                "job_url": url,
                "description": html_to_text(body),
            }
        )
    return out


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    resp = http.get(API.format(slug=slug), timeout=timeout)
    resp.raise_for_status()
    return parse_jobs(resp.json(), company_name)
