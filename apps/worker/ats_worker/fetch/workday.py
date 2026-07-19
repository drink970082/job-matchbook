"""Workday public "CXS" job board adapter.

Two-step, unlike the other adapters: a cheap paged list endpoint, then ONE
detail call per posting for the description (the list payload carries none). The
config `slug` packs the three identifiers Workday needs as "tenant/dc/site",
e.g. "arrowstreetcapital/wd5/Campus_Careers".

  list:   POST {host}/wday/cxs/{tenant}/{site}/jobs   body {appliedFacets,limit,offset,searchText}
  detail: GET  {host}/wday/cxs/{tenant}/{site}{externalPath}
  host:   https://{tenant}.{dc}.myworkdayjobs.com
"""
from __future__ import annotations

import requests

from ats_worker.fetch._paged import paged_details
from ats_worker.util import html_to_text, to_iso_date

SOURCE = "workday"
_CXS = "https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
_JSON = {"Content-Type": "application/json"}
PAGE = 20  # Workday hard-caps the list page size at 20


def _parts(slug: str):
    bits = slug.split("/")
    if len(bits) != 3 or not all(bits):
        raise ValueError(f"workday slug must be 'tenant/datacenter/site', got {slug!r}")
    return bits  # tenant, dc, site


def parse_listing(payload: dict) -> list[dict]:
    """The job stubs from a CXS list response (description NOT present here)."""
    return payload.get("jobPostings", []) if isinstance(payload, dict) else []


def parse_job(detail_payload: dict, company_name: str) -> dict:
    """Build one canonical posting from a CXS detail response."""
    info = (detail_payload or {}).get("jobPostingInfo", {})
    return {
        "source": SOURCE,
        # GUID, not the per-tenant jobReqId: dedup is by (source, external_id),
        # so the id must be unique across all workday tenants.
        "external_id": str(info.get("id") or info.get("jobReqId") or ""),
        "company_name": company_name,
        "job_title": (info.get("title") or "").strip(),
        "location": info.get("location") or None,
        "job_url": info.get("externalUrl", ""),
        "description": html_to_text(info.get("jobDescription")),
        "posted_at": to_iso_date(info.get("startDate")),
    }


def fetch_one(slug: str, external_id: str, company_name: str,
              session: requests.Session | None = None,
              timeout: int = 20) -> dict | None:
    """Fetch ONE job by its external path (the `/job/...` segment the feed URL
    carries). The feed routes Workday here so it pulls only the surfaced jobs —
    listing the whole board (N+1, sometimes thousands of jobs) just to keep the
    1-2 the feed wants is the dominant feed cost. parse_job emits the GUID as the
    external_id, so it still dedups with the watchlist. fetch() lists the board."""
    if not slug or not external_id:
        return None
    tenant, dc, site = _parts(slug)
    http = session or requests
    cxs = _CXS.format(tenant=tenant, dc=dc, site=site)
    resp = http.get(cxs + external_id, headers=_JSON, timeout=timeout)
    resp.raise_for_status()
    return parse_job(resp.json(), company_name)


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    tenant, dc, site = _parts(slug)
    cxs = _CXS.format(tenant=tenant, dc=dc, site=site)

    def _page(http, offset):
        resp = http.post(
            cxs + "/jobs",
            json={"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": ""},
            headers=_JSON, timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return parse_listing(data), data.get("total")

    def _row(http, stub):
        # m1: skip one bad posting, don't abort the company. (m3: an empty
        # external_id — no id, no jobReqId — is skipped by paged_details.)
        try:
            detail = http.get(cxs + stub["externalPath"], headers=_JSON, timeout=timeout)
            detail.raise_for_status()
            return parse_job(detail.json(), company_name)
        except Exception:
            return None

    return paged_details(session, fetch_page=_page, build_row=_row)
