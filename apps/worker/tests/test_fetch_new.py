"""TDD for the added board adapters: pinpoint and workday.

Mirrors tests/test_fetch.py's contract style. pinpoint follows the standard
single-payload `parse_jobs` contract; workday is two-step (a cheap list endpoint
+ an N+1 detail call per posting), so it's exercised separately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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
