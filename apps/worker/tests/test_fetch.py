"""TDD for the fetch adapters: normalize each board API into a unified dict."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import requests

from ats_worker.fetch import ashby, greenhouse, lever, pinpoint
from ats_worker.fetch import filter_postings
from ats_worker.util import POSTING_FIELDS
from tests._helpers import FakeSession

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


# --- shape contract shared by all adapters -------------------------------

@pytest.mark.parametrize(
    "module,fixture",
    [(greenhouse, "greenhouse.json"), (lever, "lever.json"), (ashby, "ashby.json")],
)
def test_adapter_emits_canonical_fields(module, fixture):
    postings = module.parse_jobs(load(fixture), company_name="Acme")
    assert len(postings) == 2
    for p in postings:
        assert set(p.keys()) == set(POSTING_FIELDS)
        assert p["company_name"] == "Acme"
        assert isinstance(p["external_id"], str) and p["external_id"]
        assert p["job_url"].startswith("http")
        assert p["description"].strip()


# --- per-source specifics -------------------------------------------------

def test_greenhouse_parsing():
    p = greenhouse.parse_jobs(load("greenhouse.json"), company_name="Acme")[0]
    assert p["source"] == "greenhouse"
    assert p["external_id"] == "4012345"
    assert p["job_title"] == "Senior Software Engineer, Backend"
    assert p["location"] == "San Francisco, CA"
    # HTML stripped to readable text; entities resolved; tags gone.
    assert "<" not in p["description"] and ">" not in p["description"]
    assert "backend engineer" in p["description"]
    assert "Python & Go" in p["description"]


def test_lever_parsing():
    p = lever.parse_jobs(load("lever.json"), company_name="Acme")[0]
    assert p["source"] == "lever"
    assert p["external_id"] == "f7a1c2d3-0000-4444-8888-aaaabbbbcccc"
    assert p["job_title"] == "Software Engineer, Platform"
    assert p["location"] == "Remote - US"
    assert p["job_url"].endswith("aaaabbbbcccc")
    assert "Kubernetes" in p["description"]


def test_ashby_parsing():
    p = ashby.parse_jobs(load("ashby.json"), company_name="Acme")[0]
    assert p["source"] == "ashby"
    assert p["external_id"] == "9a8b7c6d-1234-5678-9012-abcdefabcdef"
    assert p["job_title"] == "Machine Learning Engineer"
    assert p["location"] == "Remote"
    # prefers descriptionPlain, but tolerates html
    assert "PyTorch" in p["description"]
    assert "<" not in p["description"]


# --- filtering ------------------------------------------------------------

def test_filter_by_keyword_matches_title():
    postings = greenhouse.parse_jobs(load("greenhouse.json"), company_name="Acme")
    kept = filter_postings(postings, ["engineer"])
    assert [p["job_title"] for p in kept] == ["Senior Software Engineer, Backend"]


def test_filter_keyword_ignores_description():
    postings = ashby.parse_jobs(load("ashby.json"), company_name="Acme")
    # "pytorch" appears only in the description of the ML role, never in a title,
    # so a title-only filter must NOT keep it.
    kept = filter_postings(postings, ["pytorch"])
    assert kept == []


def test_filter_no_criteria_keeps_all():
    postings = ashby.parse_jobs(load("ashby.json"), company_name="Acme")
    assert filter_postings(postings, None) == postings
    assert filter_postings(postings, []) == postings


def test_filter_keywords_are_case_insensitive_and_any_match():
    postings = greenhouse.parse_jobs(load("greenhouse.json"), company_name="Acme")
    kept = filter_postings(postings, ["ENGINEER", "manager"])
    assert len(kept) == 2  # "Senior Software Engineer, Backend" + "Office Manager" titles


def test_filter_drops_empty_keyword():
    # An empty-string keyword must NOT match every title (it would filter nothing).
    postings = greenhouse.parse_jobs(load("greenhouse.json"), company_name="Acme")
    assert filter_postings(postings, ["", "manager"]) == filter_postings(postings, ["manager"])


def test_filter_tolerates_none_title():
    posts = [{"job_title": None}, {"job_title": "Engineer"}]
    assert filter_postings(posts, ["engineer"]) == [{"job_title": "Engineer"}]


# --- every posting in the payload is parsed (not just [0]) ----------------

@pytest.mark.parametrize(
    "module,fixture", [(greenhouse, "greenhouse.json"), (lever, "lever.json"), (ashby, "ashby.json")],
)
def test_adapter_parses_all_postings_with_distinct_ids(module, fixture):
    # Guards against a loop bug that emits the first posting's id for every row,
    # which would silently collapse the company to one posting under dedup.
    postings = module.parse_jobs(load(fixture), company_name="Acme")
    assert len(postings) == 2
    assert len({p["external_id"] for p in postings}) == 2


# --- fetch() HTTP wrappers (URL/params/raise_for_status/company_name) -----

@pytest.mark.parametrize("module,fixture,host,params", [
    (greenhouse, "greenhouse.json", "boards-api.greenhouse.io", {"content": "true"}),
    (lever, "lever.json", "api.lever.co", {"mode": "json"}),
    (ashby, "ashby.json", "api.ashbyhq.com", {"includeCompensation": "true"}),
    (pinpoint, "pinpoint.json", "pinpointhq.com", None),
])
def test_fetch_wrapper_hits_endpoint_and_passes_company(module, fixture, host, params):
    sess = FakeSession(payload=load(fixture))
    out = module.fetch("acme", "Acme Co", session=sess, timeout=20)
    method, url, kwargs = sess.calls[0]
    assert method == "GET"
    assert "acme" in url and host in url
    if params is not None:
        assert kwargs.get("params") == params
    assert out and all(p["company_name"] == "Acme Co" for p in out)


@pytest.mark.parametrize("module", [greenhouse, lever, ashby, pinpoint])
def test_fetch_wrapper_propagates_http_error(module):
    sess = FakeSession(payload={}, raise_exc=requests.HTTPError("404"))
    with pytest.raises(requests.HTTPError):
        module.fetch("nope", "X", session=sess)
