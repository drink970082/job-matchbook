"""SmartRecruiters public Posting API adapter.

Two-step, like workday: a cheap paged list endpoint, then ONE detail call per
posting for the description (the list payload carries only stubs). No auth.

  list:   GET https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=N
  detail: GET https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}

The list response is {totalFound, limit, offset, content:[{id, name, location, ref}]};
the detail response carries jobAd.sections.{jobDescription,qualifications,
additionalInformation}.text (HTML), which we concatenate and run through
html_to_text. The canonical apply URL is jobs.smartrecruiters.com/{slug}/{id}.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text

SOURCE = "smartrecruiters"
API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE = 100  # SmartRecruiters list page cap
# The JD sections we stitch together, in display order.
_SECTIONS = ("jobDescription", "qualifications", "additionalInformation")


def parse_listing(payload: dict) -> list[dict]:
    """The posting stubs from a list response (no description present here)."""
    return payload.get("content", []) if isinstance(payload, dict) else []


def _location(loc: dict | None) -> str | None:
    """Assemble "city, region, country" from the location object, or None."""
    loc = loc or {}
    parts = [str(loc.get(k)).strip() for k in ("city", "region", "country")
             if loc.get(k) and str(loc.get(k)).strip()]
    return ", ".join(parts) or None


def _description(detail_payload: dict) -> str:
    """Concatenate the available jobAd.sections.*.text (HTML), blank-line joined,
    then flatten to readable text."""
    sections = ((detail_payload or {}).get("jobAd") or {}).get("sections") or {}
    blobs = []
    for key in _SECTIONS:
        sec = sections.get(key) or {}
        text = sec.get("text")
        if text and str(text).strip():
            blobs.append(str(text))
    return html_to_text("\n\n".join(blobs))


def parse_job(detail_payload: dict, slug: str, company_name: str) -> dict:
    """Build one canonical posting from a detail response.

    The apply URL is synthesized from (slug, id) — jobs.smartrecruiters.com is the
    public job page; api.smartrecruiters.com is the data endpoint.
    """
    p = detail_payload or {}
    pid = str(p.get("id") or "")
    return {
        "source": SOURCE,
        "external_id": pid,
        "company_name": company_name,
        "job_title": (p.get("name") or "").strip(),
        "location": _location(p.get("location")),
        "job_url": f"https://jobs.smartrecruiters.com/{slug}/{pid}",
        "description": _description(p),
    }


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    base = API.format(slug=slug)
    out: list[dict] = []
    offset = 0
    while True:
        resp = http.get(base, params={"limit": PAGE, "offset": offset}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        stubs = parse_listing(data)
        if not stubs:
            break
        for stub in stubs:
            pid = stub.get("id")
            if not pid:
                continue
            try:
                detail = http.get(f"{base}/{pid}", timeout=timeout)
                detail.raise_for_status()
                posting = parse_job(detail.json(), slug, company_name)
            except Exception:
                continue  # skip one bad posting, don't abort the company
            if not posting["external_id"]:
                continue  # empty id would collide under (source, external_id) dedup
            out.append(posting)
        offset += PAGE
        total = data.get("totalFound")
        if isinstance(total, int) and offset >= total:
            break
    return out
