"""TDD for the SmartRecruiters two-step board adapter.

Mirrors tests/test_fetch_new.py's workday style: a cheap paged list endpoint +
an N+1 detail call per posting (the list payload carries only stubs). Exercised
with an injected fake session so there's no network.
"""
from __future__ import annotations

import pytest
import requests

from ats_worker.fetch import smartrecruiters as sr
from ats_worker.util import POSTING_FIELDS

# --- canonical inline payloads --------------------------------------------

LIST_PAGE = {
    "totalFound": 2,
    "limit": 100,
    "offset": 0,
    "content": [
        {
            "id": "abc-111",
            "name": "Software Engineer",
            "location": {"city": "London", "region": "England", "country": "uk", "remote": False},
            "ref": "https://api.smartrecruiters.com/v1/companies/Acme/postings/abc-111",
        },
        {
            "id": "def-222",
            "name": "Data Scientist",
            "location": {"city": "Remote", "country": "us", "remote": True},
            "ref": "https://api.smartrecruiters.com/v1/companies/Acme/postings/def-222",
        },
    ],
}

DETAIL = {
    "abc-111": {
        "id": "abc-111",
        "name": "Software Engineer",
        "location": {"city": "London", "region": "England", "country": "uk"},
        "jobAd": {"sections": {
            "jobDescription": {"title": "Job Description",
                               "text": "<p>Build <strong>Python</strong> services.</p>"},
            "qualifications": {"title": "Qualifications",
                               "text": "<ul><li>5 years experience</li></ul>"},
            "additionalInformation": {"title": "More", "text": "<p>Visa sponsorship.</p>"},
        }},
    },
    "def-222": {
        "id": "def-222",
        "name": "Data Scientist",
        "location": {"city": "Remote", "country": "us"},
        "jobAd": {"sections": {
            "jobDescription": {"title": "Job Description", "text": "<p>Model things.</p>"},
        }},
    },
}


class _Resp:
    def __init__(self, data, *, raise_exc=None):
        self._data = data
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._data


class _FakeSession:
    """First GET (no /{id} suffix) returns the list page; the page-2 GET (offset
    advanced past totalFound) returns an empty page; detail GETs are keyed by id.
    `bad_ids` makes that posting's detail GET raise (failure isolation)."""

    def __init__(self, *, bad_ids=()):
        self._bad = set(bad_ids)
        self.gets = []

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        base = "https://api.smartrecruiters.com/v1/companies/Acme/postings"
        if url == base:  # list endpoint
            if (params or {}).get("offset", 0) == 0:
                return _Resp(LIST_PAGE)
            return _Resp({"totalFound": 2, "limit": 100, "offset": 100, "content": []})
        pid = url.rsplit("/", 1)[-1]  # detail endpoint
        if pid in self._bad:
            return _Resp(None, raise_exc=requests.HTTPError("boom"))
        return _Resp(DETAIL[pid])


# --- parse_listing --------------------------------------------------------

def test_parse_listing_extracts_stubs():
    stubs = sr.parse_listing(LIST_PAGE)
    assert len(stubs) == 2
    assert stubs[0]["id"] == "abc-111"


def test_parse_listing_handles_non_dict():
    assert sr.parse_listing(None) == []
    assert sr.parse_listing([]) == []


# --- parse_job ------------------------------------------------------------

def test_parse_job_builds_canonical():
    p = sr.parse_job(DETAIL["abc-111"], slug="Acme", company_name="Acme Corp")
    assert set(p.keys()) == set(POSTING_FIELDS)
    assert p["source"] == "smartrecruiters"
    assert p["external_id"] == "abc-111"
    assert p["company_name"] == "Acme Corp"
    assert p["job_title"] == "Software Engineer"
    # location assembled as "city, region, country"
    assert p["location"] == "London, England, uk"
    # canonical apply URL is the public jobs host, NOT the api host
    assert p["job_url"] == "https://jobs.smartrecruiters.com/Acme/abc-111"
    # description concatenates the available sections, flattened to text
    assert "Python" in p["description"]
    assert "5 years experience" in p["description"]
    assert "Visa sponsorship" in p["description"]
    assert "<" not in p["description"] and ">" not in p["description"]


def test_parse_job_partial_location_and_sections():
    p = sr.parse_job(DETAIL["def-222"], slug="Acme", company_name="Acme")
    # only city + country present -> "city, country"
    assert p["location"] == "Remote, us"
    assert p["description"] == "Model things."


def test_parse_job_empty_location_is_none():
    p = sr.parse_job({"id": "x", "name": "Role", "jobAd": {"sections": {}}},
                     slug="Acme", company_name="Acme")
    assert p["location"] is None
    assert p["description"] == ""
    assert p["job_url"] == "https://jobs.smartrecruiters.com/Acme/x"


# --- fetch_one (feed path: only the surfaced id, never the whole board) ----

def test_fetch_one_fetches_only_the_surfaced_posting():
    sess = _FakeSession()
    p = sr.fetch_one("Acme", "abc-111", "Acme Corp", session=sess)
    assert p["external_id"] == "abc-111"
    assert p["job_title"] == "Software Engineer"
    assert "Python" in p["description"]
    # exactly ONE detail GET — the list endpoint (the N+1 whole-board cost) is never hit
    assert sess.gets == [
        ("https://api.smartrecruiters.com/v1/companies/Acme/postings/abc-111", None)]


def test_fetch_one_missing_id_returns_none_without_fetching():
    sess = _FakeSession()
    assert sr.fetch_one("Acme", "", "Acme Corp", session=sess) is None
    assert sess.gets == []


# --- fetch (two-step) -----------------------------------------------------

def test_fetch_pages_and_enriches_via_detail():
    sess = _FakeSession()
    out = sr.fetch("Acme", "Acme Corp", session=sess)

    assert len(out) == 2
    assert all(set(p.keys()) == set(POSTING_FIELDS) for p in out)
    ids = {p["external_id"] for p in out}
    assert ids == {"abc-111", "def-222"}
    urls = {p["job_url"] for p in out}
    assert "https://jobs.smartrecruiters.com/Acme/abc-111" in urls
    # first GET is the list endpoint with limit/offset params
    assert sess.gets[0][0] == "https://api.smartrecruiters.com/v1/companies/Acme/postings"
    assert sess.gets[0][1] == {"limit": 100, "offset": 0}
    # a detail GET was made per posting
    detail_gets = [u for (u, _) in sess.gets if u.endswith(("abc-111", "def-222"))]
    assert len(detail_gets) == 2


def test_fetch_isolates_a_bad_detail():
    sess = _FakeSession(bad_ids=["def-222"])
    out = sr.fetch("Acme", "Acme Corp", session=sess)
    # the good posting survives the bad detail GET
    assert len(out) == 1
    assert out[0]["external_id"] == "abc-111"


def test_fetch_terminates_on_empty_content():
    """A list page with empty content stops pagination immediately."""
    class _EmptySession:
        def __init__(self):
            self.gets = []

        def get(self, url, params=None, timeout=None):
            self.gets.append(url)
            return _Resp({"totalFound": 0, "limit": 100, "offset": 0, "content": []})

    sess = _EmptySession()
    out = sr.fetch("Acme", "Acme Corp", session=sess)
    assert out == []
    assert len(sess.gets) == 1  # only the one list GET; no details


def test_fetch_skips_stub_without_id():
    class _Sess:
        def __init__(self):
            self.gets = []

        def get(self, url, params=None, timeout=None):
            self.gets.append(url)
            base = "https://api.smartrecruiters.com/v1/companies/Acme/postings"
            if url == base and (params or {}).get("offset", 0) == 0:
                return _Resp({"totalFound": 2, "limit": 100, "offset": 0, "content": [
                    {"id": "", "name": "No Id"},
                    {"id": "ok-1", "name": "Has Id", "jobAd": {"sections": {}}},
                ]})
            if url == base:
                return _Resp({"totalFound": 2, "content": []})
            return _Resp({"id": "ok-1", "name": "Has Id",
                          "location": {"city": "NYC"}, "jobAd": {"sections": {}}})

    sess = _Sess()
    out = sr.fetch("Acme", "Acme", session=sess)
    assert len(out) == 1
    assert out[0]["external_id"] == "ok-1"
    # no detail GET was made for the id-less stub (only list + the ok-1 detail)
    detail_gets = [u for u in sess.gets if u.endswith("ok-1")]
    assert len(detail_gets) == 1
