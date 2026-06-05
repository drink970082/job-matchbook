"""Greenhouse public board API adapter.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
The `content` field is entity-escaped HTML, so we run it through html_to_text.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text

SOURCE = "greenhouse"
API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def parse_jobs(payload: dict, company_name: str) -> list[dict]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    out: list[dict] = []
    for j in jobs:
        loc = j.get("location") or {}
        out.append(
            {
                "source": SOURCE,
                "external_id": str(j["id"]),
                "company_name": company_name,
                "job_title": j.get("title", "").strip(),
                "location": (loc.get("name") or None),
                "job_url": j.get("absolute_url", ""),
                "description": html_to_text(j.get("content")),
            }
        )
    return out


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    resp = http.get(API.format(slug=slug), params={"content": "true"}, timeout=timeout)
    resp.raise_for_status()
    return parse_jobs(resp.json(), company_name)
