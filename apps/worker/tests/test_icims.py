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
DETAIL_HTML = (FIXTURES / "icims_detail.html").read_text(encoding="utf-8")


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
    the stop-on-empty-page pagination, and the detail fixture for a job URL.
    Records (url, params) per call; `list_calls`/`detail_calls` split them."""

    def __init__(self, html, detail_html=None):
        self._html = html
        self._detail = DETAIL_HTML if detail_html is None else detail_html
        self.calls: list[tuple] = []

    def get(self, url, params=None, timeout=None, **kw):
        self.calls.append((url, params))
        if "/jobs/search" not in url:
            return FakeResponse(text=self._detail)
        page = (params or {}).get("pr", 0)
        return FakeResponse(text=self._html if page == 0 else "<ul></ul>")

    @property
    def list_calls(self):
        return [c for c in self.calls if "/jobs/search" in c[0]]

    @property
    def detail_calls(self):
        return [c for c in self.calls if "/jobs/search" not in c[0]]


def test_fetch_paginates_and_targets_slug_subdomain():
    sess = _PagedSession(ICIMS_HTML)
    out = icims.fetch("careers-sig", "SIG", session=sess, timeout=20)
    assert len(out) == 2
    prs = [(p or {}).get("pr") for _, p in sess.list_calls]
    assert prs == [0, 1]              # page 0, then empty page 1, then stop
    assert all("careers-sig.icims.com" in u for u, _ in sess.list_calls)
    assert (sess.list_calls[0][1] or {}).get("in_iframe") == 1


# --- detail hydration: a PLATFORM capability, not a per-tenant recipe -----

def test_fetch_hydrates_each_posting_from_its_detail_page():
    """The search card's description is a teaser, and on some tenants absent
    entirely (MSCI lists 92 postings with none); the JD is on the job's own page."""
    sess = _PagedSession(ICIMS_HTML)
    out = icims.fetch("careers-sig", "SIG", session=sess)
    assert len(sess.detail_calls) == 2, "one detail call per posting"
    assert all(u.endswith("?in_iframe=1") for u, _ in sess.detail_calls)
    for p in out:
        assert "systematic trading desk" in p["description"]
        assert "Sign up for job alerts" not in p["description"], \
            "must select iCIMS_JobContent, not the whole page"
        assert len(p["description"]) > 500


def test_keep_drop_skips_the_detail_call_entirely():
    sess = _PagedSession(ICIMS_HTML)
    out = icims.fetch("careers-sig", "SIG", session=sess, keep=lambda p: "drop")
    assert out == [] and sess.detail_calls == []


def test_keep_discard_stores_the_posting_without_a_detail_call():
    sess = _PagedSession(ICIMS_HTML)
    out = icims.fetch("careers-sig", "SIG", session=sess, keep=lambda p: "discard")
    assert len(out) == 2 and sess.detail_calls == []


def test_a_detail_page_without_the_content_div_keeps_the_card_description():
    """A blank detail page must not cost us what the list card already gave us."""
    sess = _PagedSession(ICIMS_HTML, detail_html="<html><body>nope</body></html>")
    out = icims.fetch("careers-sig", "SIG", session=sess)
    from_cards = icims.parse_jobs(ICIMS_HTML, "SIG")
    assert [p["description"] for p in out] == [p["description"] for p in from_cards]


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
