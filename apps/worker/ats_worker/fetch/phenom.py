"""Phenom People careers-API adapter (JSON, plain HTTP).

Phenom powers many enterprise boards (Microsoft, Kraft Heinz, Mastercard, CVS…)
behind a shared JSON API. Two-step, like Workday: a paged search, then ONE detail
call per position for the description (the search payload carries none). The
config `slug` packs "{host}/{domain}" — the API host and the tenant's `domain`
param — e.g. "apply.careers.microsoft.com/microsoft.com", mirroring Workday's
multi-part slug so no schema change is needed.

  search: GET https://{host}/api/pcsx/search?domain={domain}&start={n}
          -> data.count (total), data.positions[] (10 per page)
  detail: GET https://{host}/api/pcsx/position_details?domain={domain}&position_id={id}
          -> data.jobDescription (HTML)
"""
from __future__ import annotations

import requests

from ats_worker.fetch._paged import paged_details
from ats_worker.util import html_to_text, is_safe_public_url, to_iso_date

SOURCE = "phenom"


def _parts(slug: str):
    host, _, domain = slug.partition("/")
    if not host or not domain:
        raise ValueError(f"phenom slug must be 'host/domain', got {slug!r}")
    # The slug's first segment IS the request host, and the config/UI slug charset
    # ([A-Za-z0-9._/-]) can't tell a careers hostname from an internal IP literal —
    # so the host is checked here, where it's known. (SPEC §11.)
    if not is_safe_public_url(f"https://{host}/"):
        raise ValueError(f"phenom slug host is not a public target: {host!r}")
    return host, domain


def _require_ok(env: dict) -> dict:
    """Phenom answers HTTP 200 with status != 200 / data == null for a bad tenant
    ('Tenant not identified'); treat that as an error, not an empty board."""
    if not isinstance(env, dict) or env.get("status") != 200:
        raise ValueError(f"phenom error response: {str(env)[:200]}")
    data = env.get("data")
    if not isinstance(data, dict):
        raise ValueError("phenom response carried no data object")
    return data


def parse_position(pos: dict, company_name: str, description: str = "") -> dict:
    """Build one canonical posting from a search position + its (optional) description."""
    locs = pos.get("locations") or []
    ts = pos.get("postedTs")
    return {
        "source": SOURCE,
        "external_id": str(pos.get("id") or ""),
        "company_name": company_name,
        "job_title": (pos.get("name") or "").strip(),
        "location": ", ".join(locs) if locs else None,
        "job_url": pos.get("publicUrl") or pos.get("positionUrl") or "",
        "description": html_to_text(description),
        # postedTs is epoch SECONDS; to_iso_date expects epoch ms, so scale up.
        "posted_at": to_iso_date(ts * 1000) if isinstance(ts, (int, float)) else None,
    }


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20, keep=None) -> list[dict]:
    """List a phenom board. `keep(stub) -> 'drop' | 'discard' | 'hydrate'` is an
    OPTIONAL fetch-cost optimization: the search stub already carries the title and
    location, which is everything the deterministic gates read, so a rejected
    posting can skip its detail GET (the dominant cost — one per position). 'drop'
    omits the posting entirely, 'discard' returns it un-hydrated (empty
    description) so the caller can still record it, 'hydrate' is the normal path.
    Any other value hydrates: a broken predicate must cost requests, never
    postings. keep=None disables the gate entirely."""
    host, domain = _parts(slug)
    search_url = f"https://{host}/api/pcsx/search"
    detail_url = f"https://{host}/api/pcsx/position_details"

    def _page(http, start):
        resp = http.get(search_url, params={"domain": domain, "start": start}, timeout=timeout)
        resp.raise_for_status()
        data = _require_ok(resp.json())
        return data.get("positions") or [], data.get("count")

    def _row(http, pos):
        pid = str(pos.get("id") or "")
        if not pid:
            return None  # no id can't dedup under (source, external_id)
        stub = parse_position(pos, company_name)  # description="" until hydrated
        if keep is not None:
            verdict = keep(stub)
            if verdict == "drop":
                return None       # never stored, no detail call
            if verdict == "discard":
                return stub       # stored un-hydrated, no detail call
        description = ""
        try:
            detail = http.get(detail_url,
                              params={"domain": domain, "position_id": pid}, timeout=timeout)
            detail.raise_for_status()
            description = _require_ok(detail.json()).get("jobDescription") or ""
        except Exception:
            pass  # one bad detail: keep the posting (search has title/loc/url), no desc
        return parse_position(pos, company_name, description)

    return paged_details(session, fetch_page=_page, build_row=_row)
