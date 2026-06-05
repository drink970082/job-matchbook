"""Lever public postings API adapter.

Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
Returns a JSON array. `descriptionPlain` is already plain text.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text

SOURCE = "lever"
API = "https://api.lever.co/v0/postings/{slug}"


def parse_jobs(payload: list, company_name: str) -> list[dict]:
    jobs = payload if isinstance(payload, list) else []
    out: list[dict] = []
    for j in jobs:
        categories = j.get("categories") or {}
        description = j.get("descriptionPlain") or html_to_text(j.get("description"))
        out.append(
            {
                "source": SOURCE,
                "external_id": str(j["id"]),
                "company_name": company_name,
                "job_title": (j.get("text") or "").strip(),
                "location": (categories.get("location") or None),
                "job_url": j.get("hostedUrl") or j.get("applyUrl", ""),
                "description": description.strip(),
            }
        )
    return out


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    resp = http.get(API.format(slug=slug), params={"mode": "json"}, timeout=timeout)
    resp.raise_for_status()
    return parse_jobs(resp.json(), company_name)
