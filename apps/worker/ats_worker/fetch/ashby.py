"""Ashby public job board API adapter.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
Each job exposes descriptionPlain (preferred) and descriptionHtml.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text

SOURCE = "ashby"
API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def parse_jobs(payload: dict, company_name: str) -> list[dict]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    out: list[dict] = []
    for j in jobs:
        description = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
        out.append(
            {
                "source": SOURCE,
                "external_id": str(j["id"]),
                "company_name": company_name,
                "job_title": (j.get("title") or "").strip(),
                "location": (j.get("location") or None),
                "job_url": j.get("jobUrl") or j.get("applyUrl", ""),
                "description": description.strip(),
            }
        )
    return out


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    resp = http.get(API.format(slug=slug), params={"includeCompensation": "true"},
                    timeout=timeout)
    resp.raise_for_status()
    return parse_jobs(resp.json(), company_name)
