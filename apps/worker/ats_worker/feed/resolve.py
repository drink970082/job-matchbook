"""Resolve a feed listing's apply URL to a board (source, slug, external_id).

A discovery feed (e.g. SimplifyJobs) gives a company + an apply URL but NO job
description. The JD only comes from the company's ATS board. So we parse the URL
back into the (source, slug, external_id) that the matching `fetch/` adapter
would emit, then reuse that adapter to pull the JD.

The external_id produced here MUST equal what the caller matches against:
  - greenhouse:     numeric job id   (fetch/greenhouse.py     -> str(j["id"]))
  - lever:          posting uuid     (fetch/lever.py          -> str(j["id"]))
  - ashby:          posting uuid     (fetch/ashby.py          -> str(j["id"]))
  - smartrecruiters posting id       (fetch/smartrecruiters.py-> str(p["id"]))

For these four the adapter emits exactly this id, so run_feed's exact-membership
filter and the (source, external_id) dedup hold. WORKDAY is special: the feed URL
exposes the per-tenant jobReqId but the adapter keys on the GUID, so we still
return the jobReqId as external_id and run_feed matches it as a SUBSTRING of the
posting's job_url (the externalUrl). The remaining unresolvable cases (embedded
greenhouse — a `gh_jid` on a custom domain has no slug; any other ATS host; a
malformed workday URL with no `job` segment) are left for the caller to record
via `classify_reason` as a next-step backlog item.
"""
from __future__ import annotations

from urllib.parse import unquote, urlparse, parse_qs

_GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",  # EU data-residency host; same path + same boards-api
}


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

    if host == "jobs.lever.co":
        # jobs.lever.co/{slug}/{uuid}[/apply]
        if len(parts) >= 2:
            return ("lever", unquote(parts[0]), parts[1])
        return None

    if host == "jobs.ashbyhq.com":
        # jobs.ashbyhq.com/{slug}/{uuid}[/application]; slug may be %20-encoded
        if len(parts) >= 2:
            return ("ashby", unquote(parts[0]), parts[1])
        return None

    if host in _GREENHOUSE_HOSTS:
        # boards.greenhouse.io/{slug}/jobs/{id}
        if len(parts) >= 3 and parts[1] == "jobs":
            return ("greenhouse", unquote(parts[0]), parts[2])
        return None

    if host == "jobs.smartrecruiters.com":
        # jobs.smartrecruiters.com/{slug}/{id}[...]; id is the 2nd path segment.
        if len(parts) >= 2:
            return ("smartrecruiters", unquote(parts[0]), parts[1])
        return None

    if host == "apply.workable.com":
        # apply.workable.com/{slug}/j/{shortcode}[/apply]
        if len(parts) >= 3 and parts[1] == "j":
            return ("workable", unquote(parts[0]), parts[2])
        return None

    if host == "jobs.jobvite.com":
        # jobs.jobvite.com/{slug}/job/{id} — id is the segment after `job`.
        if len(parts) >= 3 and parts[1] == "job":
            return ("jobvite", unquote(parts[0]), parts[2])
        return None

    if host.endswith(".oraclecloud.com"):
        return _resolve_oracle(host, parts)

    if host.endswith("myworkdayjobs.com"):
        return _resolve_workday(host, parts)

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
    """Map a *.myworkdayjobs.com feed URL to ("workday", "tenant/dc/site", jobReqId).

    Example:
      relx.wd3.myworkdayjobs.com/en-US/relx/job/UK---London/Software-Engineer-I_R100158-2
        tenant = relx (1st host label), dc = wd3 (2nd host label),
        site   = the segment immediately BEFORE the `job` segment (relx),
        jobReqId = token after the LAST `_` in the LAST path segment (R100158-2).

    Returns None if there is no `job` segment, or any required part is
    missing/empty — never guess (the caller records it via classify_reason).
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
    if not site:
        return None

    last = parts[-1]
    if "_" not in last:
        return None
    job_req_id = last.rsplit("_", 1)[-1]
    if not job_req_id:
        return None

    return ("workday", f"{tenant}/{dc}/{site}", job_req_id)


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
