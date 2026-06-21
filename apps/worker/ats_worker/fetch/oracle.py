"""Oracle Recruiting Cloud (Oracle Cloud HCM / Fusion) adapter — feed-only.

Unlike the per-board adapters, Oracle's candidate-experience API has NO public
job-LIST endpoint (recruitingCEJobRequisitions returns empty without auth), only
a per-job DETAIL endpoint. So this adapter exposes `fetch_one` (one job by its
requisition id) instead of `fetch` (list a board), and is wired into the feed's
detail-fetch path — never the watchlist (it can't enumerate a board, so it stays
out of config.VALID_SOURCES).

  detail: GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{reqId}

The slug packs "{host}/{site}" so we can rebuild both the API host (the requisition
id lives on the SAME host the apply URL came from, e.g. jpmc.fa.oraclecloud.com or
hdhe.fa.em3.oraclecloud.com) and the public CandidateExperience apply URL. The JD
is spread across three HTML fields which we stitch and flatten to text.
"""
from __future__ import annotations

import requests

from ats_worker.util import html_to_text

SOURCE = "oracle"
API = ("https://{host}/hcmRestApi/resources/latest/"
       "recruitingCEJobRequisitionDetails/{req_id}")
# JD sections in display order; ExternalDescriptionStr is the main body.
_SECTIONS = (
    "ExternalDescriptionStr",
    "ExternalResponsibilitiesStr",
    "ExternalQualificationsStr",
)


def _split_slug(slug: str) -> tuple[str, str]:
    """slug is "{host}/{site}". Returns (host, site); site may be empty."""
    host, _, site = (slug or "").partition("/")
    return host, site


def parse_job(detail_payload: dict, slug: str, external_id: str,
              company_name: str) -> dict:
    """Build one canonical posting from a requisition-detail response.

    external_id is the URL's requisition id (what the resolver surfaced and what
    we fetched by) — NOT the payload's internal RequisitionId — so dedup and
    keep-only-surfaced hold.
    """
    p = detail_payload or {}
    # The detail resource is sometimes wrapped as {items:[{...}]}.
    if isinstance(p.get("items"), list) and p["items"]:
        p = p["items"][0]
    host, site = _split_slug(slug)
    blobs = [str(p[k]) for k in _SECTIONS if p.get(k) and str(p[k]).strip()]
    return {
        "source": SOURCE,
        "external_id": str(external_id),
        "company_name": company_name,
        "job_title": (p.get("Title") or "").strip(),
        "location": (p.get("PrimaryLocation") or None),
        "job_url": (f"https://{host}/hcmUI/CandidateExperience/en/sites/"
                    f"{site}/job/{external_id}"),
        "description": html_to_text("\n\n".join(blobs)),
        "posted_at": None,
    }


def fetch_one(slug: str, external_id: str, company_name: str,
              session: requests.Session | None = None,
              timeout: int = 20) -> dict | None:
    """Fetch ONE Oracle requisition by id. Returns a canonical posting or None."""
    http = session or requests
    host, _ = _split_slug(slug)
    if not host or not external_id:
        return None
    resp = http.get(API.format(host=host, req_id=external_id), timeout=timeout)
    resp.raise_for_status()
    return parse_job(resp.json(), slug, external_id, company_name)
