"""TDD for the fetch adapters: normalize each board API into a unified dict."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats_worker.fetch import ashby, greenhouse, lever
from ats_worker.fetch import filter_postings
from ats_worker.util import POSTING_FIELDS

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
    kept = filter_postings(postings, keywords=["engineer"], locations=None)
    assert [p["job_title"] for p in kept] == ["Senior Software Engineer, Backend"]


def test_filter_by_location_substring():
    postings = lever.parse_jobs(load("lever.json"), company_name="Acme")
    kept = filter_postings(postings, keywords=None, locations=["remote"])
    assert len(kept) == 1
    assert kept[0]["location"] == "Remote - US"


def test_filter_keyword_also_searches_description():
    postings = ashby.parse_jobs(load("ashby.json"), company_name="Acme")
    # "pytorch" only appears in the description of the ML role.
    kept = filter_postings(postings, keywords=["pytorch"], locations=None)
    assert len(kept) == 1
    assert kept[0]["job_title"] == "Machine Learning Engineer"


def test_filter_no_criteria_keeps_all():
    postings = ashby.parse_jobs(load("ashby.json"), company_name="Acme")
    assert filter_postings(postings, keywords=None, locations=None) == postings


def test_filter_keywords_are_case_insensitive_and_any_match():
    postings = greenhouse.parse_jobs(load("greenhouse.json"), company_name="Acme")
    kept = filter_postings(postings, keywords=["ENGINEER", "manager"], locations=None)
    assert len(kept) == 2  # one matches engineer, one matches manager
