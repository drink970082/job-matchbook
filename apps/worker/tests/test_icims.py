"""iCIMS adapter: parse server-rendered cards + paginate `pr` until empty."""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from ats_worker.fetch import icims
from ats_worker.util import POSTING_FIELDS
from tests._helpers import FakeResponse

FIXTURES = Path(__file__).parent / "fixtures"
ICIMS_HTML = (FIXTURES / "icims.html").read_text(encoding="utf-8")


def test_parse_jobs_extracts_cards():
    jobs = icims.parse_jobs(ICIMS_HTML, "SIG")
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["source"] == "icims"
    assert j["external_id"] == "10966"
    assert j["company_name"] == "SIG"
    assert j["job_title"] == "Accounting Internship: Summer 2027"
    assert j["job_url"] == (
        "https://careers-sig.icims.com/jobs/10966/"
        "accounting-internship%3a-summer-2027/job"
    )
    assert "?in_iframe" not in j["job_url"]
    assert j["location"] is None      # the SIG board carries no location field
    assert j["posted_at"] is None
    assert "accounting" in j["description"].lower()


def test_parse_jobs_empty_or_cardless_html():
    assert icims.parse_jobs("", "X") == []
    assert icims.parse_jobs("<html><body>no cards</body></html>", "X") == []


class _PagedSession:
    """Serve the fixture page for pr=0 and an empty page afterwards, to exercise
    the stop-on-empty-page pagination. Records (url, params) per call."""

    def __init__(self, html):
        self._html = html
        self.calls: list[tuple] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        page = (params or {}).get("pr", 0)
        return FakeResponse(text=self._html if page == 0 else "<ul></ul>")


def test_fetch_paginates_and_targets_slug_subdomain():
    sess = _PagedSession(ICIMS_HTML)
    out = icims.fetch("careers-sig", "SIG", session=sess, timeout=20)
    assert len(out) == 2
    prs = [(p or {}).get("pr") for _, p in sess.calls]
    assert prs == [0, 1]              # page 0, then empty page 1, then stop
    assert all("careers-sig.icims.com" in u for u, _ in sess.calls)
    assert (sess.calls[0][1] or {}).get("in_iframe") == 1


def test_fetch_stops_when_a_page_repeats():
    # A board that clamps `pr` and re-serves the last page must not loop forever:
    # the same payload every call yields no NEW ids on page 1 -> stop.
    class _RepeatSession:
        def get(self, url, params=None, timeout=None):
            return FakeResponse(text=ICIMS_HTML)

    out = icims.fetch("careers-sig", "SIG", session=_RepeatSession())
    assert len(out) == 2


def test_fetch_propagates_http_error():
    class _BoomSession:
        def get(self, url, **kw):
            return FakeResponse(raise_exc=requests.HTTPError("500"))

    with pytest.raises(requests.HTTPError):
        icims.fetch("careers-sig", "SIG", session=_BoomSession())
