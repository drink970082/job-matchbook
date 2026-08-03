"""Workable public widget API adapter.

  list: GET https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true

One call returns every published job for the account, each with its HTML
description, so this is a per-BOARD adapter (watchlist-capable) like
greenhouse/lever — it exposes `fetch`, not `fetch_one`.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text, join_present

SOURCE = "workable"
API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


def _location(job: dict) -> str | None:
    """Assemble "city, state, country" from the job's flat location fields."""
    return join_present(job, ("city", "state", "country"))


def parse_jobs(payload: dict, slug: str, company_name: str) -> list[dict]:
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    out: list[dict] = []
    for j in jobs:
        code = str(j.get("shortcode") or "")
        if not code:
            continue  # empty id would collide under (source, external_id) dedup
        out.append({
            "source": SOURCE,
            "external_id": code,
            "company_name": company_name,
            "job_title": (j.get("title") or "").strip(),
            "location": _location(j),
            "job_url": f"https://apply.workable.com/{slug}/j/{code}",
            "description": html_to_text(j.get("description")),
            "posted_at": None,
        })
    return out


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    resp = http.get(API.format(slug=slug), params={"details": "true"}, timeout=timeout)
    resp.raise_for_status()
    return parse_jobs(resp.json(), slug, company_name)
