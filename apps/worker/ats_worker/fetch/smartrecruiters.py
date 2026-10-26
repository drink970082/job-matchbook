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

from ats_worker.fetch._paged import paged_details
from ats_worker.util import html_to_text, join_present

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
    return join_present(loc or {}, ("city", "region", "country"))


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
        "posted_at": None,
    }


def fetch_one(slug: str, external_id: str, company_name: str,
              session: requests.Session | None = None,
              timeout: int = 20) -> dict | None:
    """Fetch ONE posting by id. The feed routes SmartRecruiters here so it pulls
    only the surfaced jobs — a big board (e.g. 1500 postings) would otherwise cost
    a per-job detail call EACH (N+1) just to keep the 1-2 the feed wants. The
    watchlist still uses fetch() to enumerate the whole board."""
    http = session or requests
    if not slug or not external_id:
        return None
    resp = http.get(f"{API.format(slug=slug)}/{external_id}", timeout=timeout)
    resp.raise_for_status()
    return parse_job(resp.json(), slug, company_name)


def fetch_one_observation(slug: str, external_id: str, company_name: str,
                          session: requests.Session | None = None,
                          timeout: int = 20) -> dict:
    """Fetch and classify one exact-ID source observation for the lifecycle pilot.

    This intentionally remains separate from ``fetch_one``: normal feed ingestion
    keeps its canonical shape and does not persist source-specific API metadata. The
    lifecycle caller gets the state and canonical content from this same response.
    Transport and JSON decoding errors are allowed through for safe classification by
    the refresh stage.
    """
    http = session or requests
    if not slug or not external_id:
        return {"state": "unknown", "error_category": "invalid_request"}
    resp = http.get(f"{API.format(slug=slug)}/{external_id}", timeout=timeout,
                    allow_redirects=False)
    status = getattr(resp, "status_code", None)
    if isinstance(status, int) and 300 <= status < 400:
        return {"state": "unknown", "error_category": "http_error"}
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return {"state": "unknown", "error_category": "malformed_response"}

    returned_id = payload.get("id")
    if not isinstance(returned_id, (str, int)) or str(returned_id) != str(external_id):
        return {"state": "unknown", "error_category": "identity_mismatch"}
    company = payload.get("company")
    if isinstance(company, dict) and company.get("identifier") is not None:
        identifier = company.get("identifier")
        if not isinstance(identifier, str) or identifier != slug:
            return {"state": "unknown", "error_category": "company_mismatch"}
    elif company is not None and not isinstance(company, dict):
        return {"state": "unknown", "error_category": "malformed_response"}

    active = payload.get("active")
    if not isinstance(active, bool):
        return {"state": "unknown", "error_category": "invalid_active"}
    if active is False:
        return {"state": "closed", "error_category": None}

    job_ad = payload.get("jobAd")
    sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
    description_section = sections.get("jobDescription") if isinstance(sections, dict) else None
    core_description = (description_section.get("text")
                        if isinstance(description_section, dict) else None)
    if (not isinstance(payload.get("name"), str) or not payload["name"].strip()
            or not isinstance(core_description, str) or not core_description.strip()):
        return {"state": "unknown", "error_category": "incomplete_content"}
    if not html_to_text(core_description).strip():
        return {"state": "unknown", "error_category": "incomplete_content"}

    posting = parse_job(payload, slug, company_name)
    if not posting["job_title"].strip() or not posting["description"].strip():
        return {"state": "unknown", "error_category": "incomplete_content"}
    return {"state": "available", "posting": posting, "error_category": None}


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    base = API.format(slug=slug)

    def _page(http, offset):
        resp = http.get(base, params={"limit": PAGE, "offset": offset}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return parse_listing(data), data.get("totalFound")

    def _row(http, stub):
        pid = stub.get("id")
        if not pid:
            return None  # id-less stub: no detail GET
        try:
            detail = http.get(f"{base}/{pid}", timeout=timeout)
            detail.raise_for_status()
            return parse_job(detail.json(), slug, company_name)
        except Exception:
            return None  # skip one bad posting, don't abort the company

    return paged_details(session, fetch_page=_page, build_row=_row)
