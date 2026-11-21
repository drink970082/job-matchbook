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

import re
from datetime import date, timedelta
from urllib.parse import urlparse

import requests

from ats_worker.fetch._paged import paged_details
from ats_worker.util import html_to_text, is_safe_public_url, to_iso_date

SOURCE = "workday"
_CXS = "https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
_JSON = {"Content-Type": "application/json"}
PAGE = 20  # Workday hard-caps the list page size at 20

# The list stub's only date is prose: "Posted 30+ Days Ago" / "Posted 5 Days Ago".
# Match just that English "N[+] Day(s) Ago" form; the number is a LOWER bound on age
# ("30+" means at least 30). Anything else (Today/Yesterday, other locales/wording)
# yields no age, so posted_at stays None and the max-age gate keeps the posting —
# a mis-parse can never silently drop a good one.
_AGE_DAYS = re.compile(r"(\d+)\s*\+?\s*days?\s+ago", re.I)


def _stub_age_days(prose) -> int | None:
    m = _AGE_DAYS.search(prose or "")
    return int(m.group(1)) if m else None


def _parts(slug: str):
    bits = slug.split("/")
    if len(bits) != 3 or not all(bits):
        raise ValueError(f"workday slug must be 'tenant/datacenter/site', got {slug!r}")
    # The `.myworkdayjobs.com` suffix is hardcoded, so today no slug can build an
    # internal host; guard the BUILT url anyway so that holds if the slug charset
    # ever loosens (a '#' would truncate the suffix). (SPEC §11.)
    if not is_safe_public_url(_CXS.format(tenant=bits[0], dc=bits[1], site=bits[2])):
        raise ValueError(f"workday slug builds an unsafe host: {slug!r}")
    return bits  # tenant, dc, site


def parse_listing(payload: dict) -> list[dict]:
    """The job stubs from a CXS list response (description NOT present here)."""
    return payload.get("jobPostings", []) if isinstance(payload, dict) else []


def parse_stub(stub: dict, company_name: str, now=None) -> dict:
    """A PARTIAL posting from a list stub — only what the deterministic fetch-cost
    gate reads (title + location + date). Deliberately carries no `external_id`: the
    GUID lives in the detail payload, so this shape must never be stored as a row.

    `postedOn` is relative prose ("Posted 30+ Days Ago"). Given `now` (the injected
    clock), a parseable age becomes an ISO date `now - age` so the max-age gate can
    drop a stale stub before its detail call. Unparseable prose (or no `now`) leaves
    posted_at None, which the gate keeps — so a mis-parse never drops a good posting."""
    age = _stub_age_days(stub.get("postedOn"))
    posted_at = None
    if now is not None and age is not None:
        posted_at = (date.fromisoformat(str(now)[:10]) - timedelta(days=age)).isoformat()
    return {
        "source": SOURCE,
        "company_name": company_name,
        "job_title": (stub.get("title") or "").strip(),
        "location": stub.get("locationsText") or None,
        "posted_at": posted_at,
    }


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


def recheck_id(row) -> str | None:
    """The key run_expire hands fetch_one for a STORED row: the `/job/...` external
    path, read off the stored job_url (the detail's `externalUrl`, which ends in the
    same path the list stub's `externalPath` carries). The stored external_id is the
    GUID, a different id space that fetch_one cannot use. None when the url has no
    `/job/<something>` on a Workday host — the row is then skipped, never guessed."""
    url = urlparse(row["job_url"] or "")
    host = (url.hostname or "").lower()
    if not host.endswith((".myworkdayjobs.com", ".myworkdaysite.com")):
        return None
    parts = url.path.split("/")
    if "job" not in parts:
        return None
    tail = [p for p in parts[parts.index("job") + 1:] if p]
    if not tail or any(p in (".", "..") for p in tail):
        return None   # a dot segment would resolve to another endpoint on the host
    return "/job/" + "/".join(tail)


def fetch_one(slug: str, external_id: str, company_name: str,
              session: requests.Session | None = None,
              timeout: int = 20) -> dict | None:
    """Fetch ONE job by its external path (the `/job/...` segment the feed URL
    carries; for a stored row, `recheck_id`). The feed routes Workday here so it pulls only the surfaced jobs —
    listing the whole board (N+1, sometimes thousands of jobs) just to keep the
    1-2 the feed wants is the dominant feed cost. parse_job emits the GUID as the
    external_id, so it still dedups with the watchlist. fetch() lists the board."""
    if not slug or not external_id:
        return None
    if not external_id.startswith("/job/"):
        # A GUID (the stored external_id) would build "<cxs><guid>", which serves the
        # HTML career page with a 200 — a check that can never say "gone" (#266).
        raise ValueError(f"workday fetch_one takes an external path '/job/...', "
                         f"got {external_id!r}")
    tenant, dc, site = _parts(slug)
    http = session or requests
    cxs = _CXS.format(tenant=tenant, dc=dc, site=site)
    resp = http.get(cxs + external_id, headers=_JSON, timeout=timeout)
    resp.raise_for_status()
    return parse_job(resp.json(), company_name)


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20, keep=None, now=None) -> list[dict]:
    """List a workday board. `keep(stub) -> 'drop' | ...` is an OPTIONAL fetch-cost
    gate: the list stub already carries the title, so a title/age-rejected posting
    can skip its detail GET (the dominant cost — one per posting on boards that run
    to thousands).

    Unlike phenom, ONLY 'drop' is honoured. 'discard' would store an un-hydrated
    stub, but a workday stub has no GUID — `parse_job` takes external_id from the
    detail payload — so the row would key on jobReqId and a later hydration would
    insert a SECOND row under the GUID. Every non-'drop' verdict therefore falls
    through and hydrates, which is also the fail-open path for a broken predicate."""
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
        if keep is not None and keep(parse_stub(stub, company_name, now)) == "drop":
            return None       # never stored, no detail call, no id to reconcile
        try:
            detail = http.get(cxs + stub["externalPath"], headers=_JSON, timeout=timeout)
            detail.raise_for_status()
            return parse_job(detail.json(), company_name)
        except Exception:
            return None

    return paged_details(session, fetch_page=_page, build_row=_row)
