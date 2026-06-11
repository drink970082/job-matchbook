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

from ats_worker.util import html_to_text

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
    }


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    tenant, dc, site = _parts(slug)
    http = session or requests
    cxs = _CXS.format(tenant=tenant, dc=dc, site=site)
    out: list[dict] = []
    offset = 0
    while True:
        resp = http.post(
            cxs + "/jobs",
            json={"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": ""},
            headers=_JSON, timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        stubs = parse_listing(data)
        for stub in stubs:
            try:
                detail = http.get(cxs + stub["externalPath"], headers=_JSON, timeout=timeout)
                detail.raise_for_status()
                posting = parse_job(detail.json(), company_name)
            except Exception:
                continue  # m1: skip one bad posting, don't abort the company
            if not posting["external_id"]:
                continue  # m3: empty id would collide under (source, external_id) dedup
            out.append(posting)
        # M2: advance by rows actually returned so a short page never skips rows.
        offset += len(stubs)
        # M1: terminate on an empty page OR an honest total we've reached; never
        # on `total or 0` (a null/absent total must not stop us after page 1).
        total = data.get("total")
        if not stubs or (isinstance(total, int) and offset >= total):
            break
    return out
