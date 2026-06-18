"""Unit tests for feed/resolve.py — URL -> (source, slug, external_id) | None.

The external_id MUST match what each board adapter emits (str(j["id"])), so the
caller's keep-only-surfaced-ids filter and the (source, external_id) dedup hold.
"""
from __future__ import annotations

import pytest

from ats_worker.feed import resolve


@pytest.mark.parametrize("url, expected", [
    # lever: jobs.lever.co/{slug}/{uuid}
    ("https://jobs.lever.co/acme/f7a1c2d3-0000", ("lever", "acme", "f7a1c2d3-0000")),
    ("https://jobs.lever.co/acme/f7a1c2d3-0000/apply", ("lever", "acme", "f7a1c2d3-0000")),
    # ashby: jobs.ashbyhq.com/{slug}/{uuid}; slug may be %20-encoded
    ("https://jobs.ashbyhq.com/acme/9a8b7c6d", ("ashby", "acme", "9a8b7c6d")),
    ("https://jobs.ashbyhq.com/Rose%20Rocket/c074b14e/application",
     ("ashby", "Rose Rocket", "c074b14e")),
    # greenhouse direct: boards.greenhouse.io/{slug}/jobs/{id}
    ("https://boards.greenhouse.io/acme/jobs/4012345", ("greenhouse", "acme", "4012345")),
    ("https://job-boards.greenhouse.io/acme/jobs/4012345", ("greenhouse", "acme", "4012345")),
    # smartrecruiters: jobs.smartrecruiters.com/{slug}/{id}[...] — id is 2nd segment
    ("https://jobs.smartrecruiters.com/Acme/12345", ("smartrecruiters", "Acme", "12345")),
    ("https://jobs.smartrecruiters.com/Acme/12345/some-job-slug",
     ("smartrecruiters", "Acme", "12345")),
    ("https://jobs.smartrecruiters.com/Rose%20Rocket/98765",
     ("smartrecruiters", "Rose Rocket", "98765")),
    # workday: tenant=relx, dc=wd3, site=segment before `job`; jobReqId=after last `_`
    ("https://relx.wd3.myworkdayjobs.com/en-US/relx/job/UK---London/Software-Engineer-I_R100158-2",
     ("workday", "relx/wd3/relx", "R100158-2")),
    # workday with no leading locale (site is still the segment before `job`)
    ("https://acme.wd5.myworkdayjobs.com/External/job/Boston/Engineer_R123",
     ("workday", "acme/wd5/External", "R123")),
])
def test_resolves_supported_boards(url, expected):
    assert resolve.resolve_url(url) == expected


@pytest.mark.parametrize("url", [
    None,
    "",
    # workday with NO `job` segment -> can't locate site -> None (never guess)
    "https://acme.wd5.myworkdayjobs.com/External/Engineer_R123",
    # workday whose last segment has no `_` -> no jobReqId -> None
    "https://acme.wd5.myworkdayjobs.com/External/job/Boston/Engineer",
    # workday whose last segment ends in `_` -> empty jobReqId -> None
    "https://acme.wd5.myworkdayjobs.com/External/job/Boston/Engineer_",
    # workday where `job` is the very first segment -> no site before it -> None
    "https://acme.wd5.myworkdayjobs.com/job/Boston/Engineer_R1",
    # embedded greenhouse — gh_jid but no board slug
    "https://careers.qualtrics.com/careers/job/7340628?gh_jid=7340628",
    # smartrecruiters host but missing the id segment
    "https://jobs.smartrecruiters.com/Acme",
    # greenhouse host but not a /jobs/{id} path
    "https://boards.greenhouse.io/acme",
    # lever host but missing the id segment
    "https://jobs.lever.co/acme",
])
def test_unresolvable_returns_none(url):
    assert resolve.resolve_url(url) is None


@pytest.mark.parametrize("url, host, reason", [
    ("https://acme.wd5.myworkdayjobs.com/External/job/X_R1",
     "acme.wd5.myworkdayjobs.com", "workday_deferred"),
    ("https://careers.qualtrics.com/careers/job/1?gh_jid=1",
     "careers.qualtrics.com", "embedded_greenhouse"),
    ("https://jobs.smartrecruiters.com/Acme/12345",
     "jobs.smartrecruiters.com", "unsupported_host"),
    ("", "", "unsupported_host"),
])
def test_classify_reason(url, host, reason):
    assert resolve.classify_reason(url) == (host, reason)
