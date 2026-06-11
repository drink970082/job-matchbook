"""TDD for the added board adapters: pinpoint and workday.

Mirrors tests/test_fetch.py's contract style. pinpoint follows the standard
single-payload `parse_jobs` contract; workday is two-step (a cheap list endpoint
+ an N+1 detail call per posting), so it's exercised separately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from ats_worker.fetch import pinpoint, workday
from ats_worker.util import POSTING_FIELDS

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


# --- shared shape contract (single-payload adapters) ----------------------

@pytest.mark.parametrize("module,fixture", [(pinpoint, "pinpoint.json")])
def test_adapter_emits_canonical_fields(module, fixture):
    postings = module.parse_jobs(load(fixture), company_name="Acme")
    assert len(postings) == 2
    for p in postings:
        assert set(p.keys()) == set(POSTING_FIELDS)
        assert p["company_name"] == "Acme"
        assert isinstance(p["external_id"], str) and p["external_id"]
        assert p["job_url"].startswith("http")
        assert p["description"].strip()
        assert "<" not in p["description"] and ">" not in p["description"]


# --- pinpoint -------------------------------------------------------------

def test_pinpoint_parsing():
    p = pinpoint.parse_jobs(load("pinpoint.json"), company_name="Wolverine")[0]
    assert p["source"] == "pinpoint"
    assert p["external_id"] == "445793"
    assert p["job_title"] == "Quantitative Analyst"
    assert p["location"] == "Chicago, IL"
    assert p["job_url"] == "https://careers.example.com/en/postings/71814bfd-aaaa"
    # description merges the JD sections (overview + responsibilities + skills)
    assert "systematic trading" in p["description"]
    assert "Backtest signals" in p["description"]
    assert "C++" in p["description"]


# --- workday (two-step: list then per-posting detail) ---------------------

def test_workday_parse_listing_extracts_stubs():
    stubs = workday.parse_listing(load("workday_list.json"))
    assert len(stubs) == 2
    assert stubs[0]["externalPath"] == "/job/Boston/Quantitative-Developer_R1433"


def test_workday_parse_job_builds_canonical():
    p = workday.parse_job(load("workday_detail.json"), company_name="Arrowstreet")
    assert set(p.keys()) == set(POSTING_FIELDS)
    assert p["source"] == "workday"
    # globally-unique GUID, not the per-tenant reqId (dedup is by (source, external_id))
    assert p["external_id"] == "11628fe60202100110ab9934d5870000"
    assert p["job_title"] == "Quantitative Developer"
    assert p["location"] == "Boston"
    assert p["job_url"].startswith("http")
    assert "quantitative developer" in p["description"]
    assert "<" not in p["description"]


def test_workday_parse_job_falls_back_to_reqid_when_no_guid():
    # No globally-unique `id` in the detail: fall back to jobReqId rather than
    # emitting an empty external_id (which would collide under dedup).
    detail = {"jobPostingInfo": {
        "jobReqId": "R999", "title": "X", "location": "NYC",
        "externalUrl": "https://x.wd5.myworkdayjobs.com/s/job/X_R999",
        "jobDescription": "<p>d</p>",
    }}
    assert workday.parse_job(detail, "Co")["external_id"] == "R999"


def test_pinpoint_location_string_or_null():
    payload = {"data": [
        {"id": "1", "title": "A", "url": "https://x/1", "description": "d", "location": "Remote"},
        {"id": "2", "title": "B", "url": "https://x/2", "description": "d", "location": None},
    ]}
    out = pinpoint.parse_jobs(payload, "Co")
    assert out[0]["location"] == "Remote"   # bare string passes through
    assert out[1]["location"] is None       # null -> None


def test_workday_slug_must_have_three_parts():
    with pytest.raises(ValueError):
        workday.fetch("justtenant", "X", session=object())


def test_workday_fetch_pages_and_enriches_via_detail():
    # Inject a fake transport to exercise the real pagination + N+1 detail flow
    # without network (the adapter already takes a `session` for this).
    list_payload = load("workday_list.json")
    detail_payload = load("workday_detail.json")

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeSession:
        def __init__(self):
            self.posts = []
            self.gets = []

        def post(self, url, json=None, headers=None, timeout=None):
            self.posts.append((url, json))
            if json["offset"] == 0:
                return FakeResp(list_payload)
            return FakeResp({"total": 2, "jobPostings": []})

        def get(self, url, headers=None, timeout=None):
            self.gets.append(url)
            return FakeResp(detail_payload)

    sess = FakeSession()
    out = workday.fetch("arrowstreetcapital/wd5/Campus_Careers", "Arrowstreet", session=sess)

    assert len(out) == 2  # one canonical posting per listing row, enriched via detail
    assert all(set(p.keys()) == set(POSTING_FIELDS) for p in out)
    assert "arrowstreetcapital.wd5.myworkdayjobs.com" in sess.posts[0][0]
    assert sess.gets[0].endswith(
        "/wday/cxs/arrowstreetcapital/Campus_Careers/job/Boston/Quantitative-Developer_R1433"
    )


# --- workday pagination + failure-isolation fakes -------------------------
#
# A configurable fake transport for the multi-page tests. `pages` is the list
# of list-endpoint responses returned in order of POST (keyed by request order,
# not offset, so a test can model whatever total/stub combo it wants). Detail
# GETs are SYNTHESIZED per requested path so every posting carries a distinct,
# globally-unique `id` (otherwise dedup/count assertions would be meaningless).


class _Resp:
    def __init__(self, data, *, raise_exc=None):
        self._data = data
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._data


def _stubs(paths):
    """Build jobPostings stubs from a list of externalPath suffixes."""
    return [{"title": f"Job {p}", "externalPath": p, "locationsText": "Boston"} for p in paths]


class _PagedSession:
    """Returns the configured list `pages` in POST order; synthesizes details.

    `pages` is a list of (total, [externalPath, ...]) tuples. `bad_detail_paths`
    holds paths whose detail GET should raise (per-detail failure isolation).
    """

    def __init__(self, pages, *, bad_detail_paths=()):
        self._pages = pages
        self._bad = set(bad_detail_paths)
        self.posts = []
        self.gets = []

    def post(self, url, json=None, headers=None, timeout=None):
        idx = len(self.posts)
        self.posts.append((url, json))
        total, paths = self._pages[idx] if idx < len(self._pages) else (0, [])
        return _Resp({"total": total, "jobPostings": _stubs(paths)})

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        for p in self._bad:
            if url.endswith(p):
                return _Resp(None, raise_exc=requests.HTTPError("boom"))
        # Synthesize a distinct detail payload keyed off the requested path so
        # each posting's external_id (the GUID) is unique.
        return _Resp({
            "jobPostingInfo": {
                "id": f"guid{abs(hash(url)) % (10**12)}",
                "title": "Synthesized Role",
                "location": "Boston",
                "externalUrl": "https://x.wd5.myworkdayjobs.com" + url.split(".com")[-1],
                "jobDescription": "<p>role at " + url + "</p>",
            }
        })


def test_workday_fetch_paginates_two_full_pages():
    # M1+M2+M3: total=25; page 1 (offset=0) -> 20 stubs, page 2 (offset=20) -> 5.
    # The buggy terminator (`offset >= (total or 0)` after `offset += PAGE`) is
    # fine here only because total is a real int; the real regression this
    # guards is that the second POST happens at all (existing test never did 2
    # *full* list POSTs) and that all 25 rows are enriched.
    page1 = (25, [f"/job/a/Role-{i}" for i in range(20)])
    page2 = (25, [f"/job/b/Role-{i}" for i in range(20, 25)])
    sess = _PagedSession([page1, page2])

    out = workday.fetch("acme/wd5/Careers", "Acme", session=sess)

    assert len(out) == 25
    # exactly two list POSTs (page 1 full, page 2 the remainder)
    list_posts = [p for p in sess.posts]
    assert len(list_posts) == 2
    assert list_posts[0][1]["offset"] == 0
    assert list_posts[1][1]["offset"] == 20  # M2: offset advanced by stub count
    # every external_id distinct -> dedup-safe
    assert len({p["external_id"] for p in out}) == 25


def test_workday_fetch_continues_when_total_is_null():
    # M1: total absent/null must NOT stop after page 1. Terminate only on an
    # empty page. Page 1 returns 3 stubs (total=None), page 2 returns 0.
    page1 = (None, ["/job/a/R1", "/job/a/R2", "/job/a/R3"])
    page2 = (None, [])
    sess = _PagedSession([page1, page2])

    out = workday.fetch("acme/wd5/Careers", "Acme", session=sess)

    assert len(out) == 3  # all stubs fetched, not just page 1
    assert len(sess.posts) == 2  # second POST happened to discover the empty page


def test_workday_fetch_short_nonfinal_page_does_not_skip_rows():
    # M2: a short non-final page (pages of 15 with total=40) must not skip rows.
    # If offset advanced by PAGE(20) instead of len(stubs)(15), page 2 would
    # request offset=20 and silently skip rows 15-19.
    page1 = (40, [f"/job/a/R{i}" for i in range(15)])
    page2 = (40, [f"/job/b/R{i}" for i in range(15, 30)])
    page3 = (40, [f"/job/c/R{i}" for i in range(30, 40)])
    sess = _PagedSession([page1, page2, page3])

    out = workday.fetch("acme/wd5/Careers", "Acme", session=sess)

    assert len(out) == 40
    assert [p[1]["offset"] for p in sess.posts] == [0, 15, 30]


def test_workday_fetch_isolates_per_detail_failure():
    # m1: one posting's detail GET raising (404/500) must SKIP that posting and
    # still return the rest of the company (no whole-fetch abort).
    page1 = (2, ["/job/good/R1", "/job/bad/R2"])
    sess = _PagedSession([page1], bad_detail_paths=["/job/bad/R2"])

    out = workday.fetch("acme/wd5/Careers", "Acme", session=sess)

    assert len(out) == 1  # the good posting survives the bad one
    assert sess.gets[-1].endswith("/job/bad/R2")  # the bad detail was attempted


def test_workday_fetch_skips_empty_external_id():
    # m3: a parsed posting with empty external_id (no id, no jobReqId) must be
    # skipped so two such rows don't collide under (source, external_id) dedup.
    class _IdlessSession:
        def __init__(self):
            self.posts = []
            self.gets = []

        def post(self, url, json=None, headers=None, timeout=None):
            self.posts.append((url, json))
            if json["offset"] == 0:
                return _Resp({"total": 2, "jobPostings": _stubs(["/job/a/R1", "/job/a/R2"])})
            return _Resp({"total": 2, "jobPostings": []})

        def get(self, url, headers=None, timeout=None):
            self.gets.append(url)
            if url.endswith("/job/a/R1"):
                # has a real GUID
                return _Resp({"jobPostingInfo": {"id": "GUID1", "title": "Good",
                                                 "location": "Boston",
                                                 "externalUrl": "https://x.com/a",
                                                 "jobDescription": "<p>good</p>"}})
            # missing both id and jobReqId -> external_id == ""
            return _Resp({"jobPostingInfo": {"title": "Bad", "location": "Boston",
                                             "externalUrl": "https://x.com/b",
                                             "jobDescription": "<p>bad</p>"}})

    sess = _IdlessSession()
    out = workday.fetch("acme/wd5/Careers", "Acme", session=sess)

    assert len(out) == 1
    assert out[0]["external_id"] == "GUID1"
    assert all(p["external_id"] for p in out)  # none empty


# --- pinpoint linkless skip -----------------------------------------------

def test_pinpoint_skips_linkless_postings():
    # m2: a posting with no usable `url` violates the job_url contract (others
    # assert startswith http) and writes an unclickable record -> drop it.
    postings = pinpoint.parse_jobs(load("pinpoint_linkless.json"), company_name="Acme")
    assert len(postings) == 1  # only the linked posting kept
    assert all(p["job_url"].startswith("http") for p in postings)
    assert postings[0]["external_id"] == "100"
