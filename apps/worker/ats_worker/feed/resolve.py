"""Resolve a feed listing's apply URL to a board (source, slug, external_id).

A discovery feed (e.g. SimplifyJobs) gives a company + an apply URL but NO job
description. The JD only comes from the company's ATS board. So we parse the URL
back into the (source, slug, external_id) that the matching `fetch/` adapter
would emit, then reuse that adapter to pull the JD.

The (source, slug, external_id) produced here drives one of run_feed's two ingest
shapes:
  - BOARD sources list the whole board and keep the exact surfaced external_id:
      greenhouse (numeric job id), lever (uuid), ashby (uuid).
  - DETAIL sources fetch ONLY the surfaced id (no whole-board fetch):
      smartrecruiters (posting id -> /postings/{id}),
      workday (the job's externalPath, "/job/..." -> the CXS per-job endpoint; the
        adapter still emits the GUID as external_id, so it dedups with the watchlist),
      oracle (slug packs host/site), jobvite.
The remaining unresolvable cases (embedded greenhouse — a `gh_jid` on a custom
domain has no slug, handled by an enriching I/O resolver outside this module; any
other ATS host; a workday URL with no `job` segment) are left for the caller to
record via `classify_reason` as a next-step backlog item.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse, parse_qs

from ..config import VALID_SOURCES

_GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",  # EU data-residency host; same path + same boards-api
}

# Hosts whose apply URL has a FIXED shape, as a table rather than six near-identical
# branches — the shapes differ only in whether a marker segment sits between the slug
# and the id, and a hand-written branch per host is where a missing `unquote` or an
# off-by-one path index gets copy-pasted in.
#
#   value (source, None)     ->  {slug}/{external_id}
#   value (source, "marker") ->  {slug}/{marker}/{external_id}
#
# The slug is always segment 0 and always unquoted: Ashby and SmartRecruiters both
# surface %20-encoded company names. Per-host shapes, for the reader:
#
#   jobs.lever.co/{slug}/{uuid}[/apply]
#   jobs.ashbyhq.com/{slug}/{uuid}[/application]
#   jobs.smartrecruiters.com/{slug}/{id}[/{title-slug}]
#   apply.workable.com/{slug}/j/{shortcode}[/apply]
#   jobs.jobvite.com/{slug}/job/{id}
#   boards.greenhouse.io/{slug}/jobs/{id}   (and the two other greenhouse hosts)
_FIXED_SHAPE_HOSTS: dict[str, tuple[str, str | None]] = {
    "jobs.lever.co": ("lever", None),
    "jobs.ashbyhq.com": ("ashby", None),
    "jobs.smartrecruiters.com": ("smartrecruiters", None),
    "apply.workable.com": ("workable", "j"),
    "jobs.jobvite.com": ("jobvite", "job"),
    **{h: ("greenhouse", "jobs") for h in _GREENHOUSE_HOSTS},
}


def _resolve_fixed_shape(
    entry: tuple[str, str | None], parts: list[str]
) -> tuple[str, str, str] | None:
    """Apply one `_FIXED_SHAPE_HOSTS` entry to a path, or None.

    None when the path is too short, or the marker segment is absent — a partial
    match is something the caller records, never an id we fabricate. That is what
    turns `boards.greenhouse.io/embed/job_app?token=…` (a job id with no board slug)
    into an unresolved row rather than a wrong one.
    """
    source, marker = entry
    if marker is None:
        return (source, unquote(parts[0]), parts[1]) if len(parts) >= 2 else None
    if len(parts) >= 3 and parts[1] == marker:
        return (source, unquote(parts[0]), parts[2])
    return None


def _path_parts(parsed) -> list[str]:
    return [p for p in parsed.path.split("/") if p]


def resolve_url(url: str | None) -> tuple[str, str, str] | None:
    """Return (source, slug, external_id) for a resolvable board URL, else None.

    Pure, no I/O. None means "not resolvable in v1" — the caller records it.
    """
    if not url:
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    parts = _path_parts(p)

    entry = _FIXED_SHAPE_HOSTS.get(host)
    if entry is not None:
        return _resolve_fixed_shape(entry, parts)

    # Oracle and Workday are NOT fixed-shape: both pack multiple path segments into
    # the slug, so each keeps its own resolver.
    if host.endswith(".oraclecloud.com"):
        return _resolve_oracle(host, parts)

    if host.endswith("myworkdayjobs.com"):
        return _resolve_workday(host, parts)

    return None


# --- board URLs (no job id needed) -----------------------------------------
# `resolve_board` widens the shapes above to board URLs, for the sources a watchlist row
# can hold. The web's lib/board-url.ts is the same resolver in TypeScript; every case of
# tests/fixtures/board-url-cases.json runs through both. onboard-board's probe.py calls it.

# Board hosts that carry no job URL the feed resolves, and boards named by a subdomain.
_BOARD_ONLY_HOSTS = {"careers.smartrecruiters.com": "smartrecruiters"}
_SUBDOMAIN_HOSTS = {"pinpointhq.com": "pinpoint", "icims.com": "icims"}
# A first path segment that is a route on that source's hosts, not a company slug.
_ROUTE_SEGMENT = {"greenhouse": "embed", "workable": "j", "smartrecruiters": "oneclick-ui"}
_LOCALE = re.compile(r"[a-z]{2}(-[A-Za-z]{2})?")
_SLUG = re.compile(r"[A-Za-z0-9._-]+")
# Ashby and SmartRecruiters name boards by company name: single inner spaces allowed.
_SPACED_SLUG = re.compile(r"[A-Za-z0-9._-]+( [A-Za-z0-9._-]+)*")
_SPACED_SOURCES = {"ashby", "smartrecruiters"}


def resolve_board(url: str | None) -> tuple[str, str] | None:
    """(source, slug) for a board or job URL on a platform a watchlist row can hold, else
    None (a recipe site, a feed-only source, a slug the watchlist rejects). Pure."""
    try:
        p = urlparse((url or "").strip())
        host = (p.hostname or "").lower()
    except ValueError:
        return None
    if p.scheme not in ("http", "https"):
        return None
    parts = _path_parts(p)

    def board(source: str, slug: str) -> tuple[str, str] | None:
        ok = (_SPACED_SLUG if source in _SPACED_SOURCES else _SLUG).fullmatch(slug)
        if not ok or ".." in slug or slug.lower() == _ROUTE_SEGMENT.get(source):
            return None
        return (source, slug)

    source = _FIXED_SHAPE_HOSTS.get(host, (_BOARD_ONLY_HOSTS.get(host),))[0]
    if source is not None:
        if source not in VALID_SOURCES:  # feed-only (jobvite): no board to list
            return None
        if source == "greenhouse" and parts[:1] == ["embed"]:
            # boards.greenhouse.io/embed/job_board?for=acme names the board in the query.
            return board(source, parse_qs(p.query).get("for", [""])[0])
        return board(source, unquote(parts[0])) if parts else None

    for suffix, sub_source in _SUBDOMAIN_HOSTS.items():
        if host.endswith("." + suffix):
            sub = host[: -len(suffix) - 1]
            return board(sub_source, sub) if sub != "www" and "." not in sub else None

    # {tenant}.{dc}.myworkdayjobs.com/[locale/]{site}[/job/...]: the site is the segment
    # before `job` (as _resolve_workday), else the first non-locale segment.
    if host.endswith(".myworkdayjobs.com"):
        labels = host.split(".")
        if len(labels) < 4 or not labels[0] or not labels[1]:
            return None
        job = parts.index("job") if "job" in parts else -1
        site = parts[job - 1] if job > 0 else next((s for s in parts if not _LOCALE.fullmatch(s)), "")
        if _LOCALE.fullmatch(site) or site.lower() == "wday" or board("workday", site) is None:
            return None
        return ("workday", f"{labels[0]}/{labels[1]}/{site}")
    return None


def _resolve_oracle(host: str, parts: list[str]) -> tuple[str, str, str] | None:
    """Map an Oracle CandidateExperience URL to ("oracle", "{host}/{site}", reqId).

    Example:
      jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210706680
        host  = jpmc.fa.oraclecloud.com (kept whole — the detail API lives on it),
        site  = the segment after `sites` (CX_1001),
        reqId = the segment after the LAST `job` (210706680).

    Returns None if the `sites`/`job` segments or their ids are missing — the
    detail fetch needs both, so never guess (the caller records it).
    """
    if "sites" not in parts or "job" not in parts:
        return None
    site_idx = parts.index("sites")
    job_idx = len(parts) - 1 - parts[::-1].index("job")  # last `job` segment
    if site_idx + 1 >= len(parts) or job_idx + 1 >= len(parts):
        return None
    site, req_id = parts[site_idx + 1], parts[job_idx + 1]
    if not site or not req_id:
        return None
    return ("oracle", f"{host}/{site}", req_id)


def _resolve_workday(host: str, parts: list[str]) -> tuple[str, str, str] | None:
    """Map a *.myworkdayjobs.com feed URL to ("workday", "tenant/dc/site", externalPath).

    Example:
      relx.wd3.myworkdayjobs.com/en-US/relx/job/UK---London/Software-Engineer-I_R100158-2
        tenant = relx (1st host label), dc = wd3 (2nd host label),
        site   = the segment immediately BEFORE the `job` segment (relx),
        externalPath = "/job/UK---London/Software-Engineer-I_R100158-2" — everything
                       from `job` on, which is exactly what the CXS per-job detail
                       endpoint takes. So the feed fetches ONLY this job (workday's
                       `fetch_one`), not the whole board. The adapter still emits the
                       GUID as external_id, so it dedups with the watchlist.

    Returns None if there is no `job` segment, no site segment before it, or no job
    path after it — never guess (the caller records it via classify_reason).
    """
    labels = host.split(".")
    if len(labels) < 2 or not labels[0] or not labels[1]:
        return None
    tenant, dc = labels[0], labels[1]

    if "job" not in parts:
        return None
    job_idx = parts.index("job")
    if job_idx == 0:  # no segment before `job` to use as the site
        return None
    site = parts[job_idx - 1]
    if not site or job_idx + 1 >= len(parts):  # need a site AND a job path after `job`
        return None

    external_path = "/" + "/".join(parts[job_idx:])  # /job/.../<title>_<reqId>
    return ("workday", f"{tenant}/{dc}/{site}", external_path)


def classify_reason(url: str | None) -> tuple[str, str]:
    """Return (host, reason) for an unresolvable URL — the fail-bucket label.

    reason ∈ {workday_deferred, embedded_greenhouse, unsupported_host}.
    """
    if not url:
        return ("", "unsupported_host")
    try:
        p = urlparse(url)
    except ValueError:
        return ("", "unsupported_host")
    host = (p.hostname or "").lower()
    if host.endswith("myworkdayjobs.com"):
        return (host, "workday_deferred")
    if "gh_jid" in parse_qs(p.query or ""):
        # Greenhouse embedded on a custom careers domain: we have the job id but
        # not the board slug, so we can't call boards-api. Next-step item.
        return (host, "embedded_greenhouse")
    return (host, "unsupported_host")
