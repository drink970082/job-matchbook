"""TDD for the fetch adapters: normalize each board API into a unified dict."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import requests

from ats_worker.fetch import ashby, greenhouse, lever, phenom, pinpoint
from ats_worker.fetch import (STUB_GATE_SOURCES, fetch_company, filter_postings,
                              prefilter_postings)
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


# --- fetch_company dispatcher ---------------------------------------------

def test_fetch_company_dispatches_to_the_right_adapter():
    sess = FakeSession(payload=load("greenhouse.json"))
    out = fetch_company("greenhouse", "acme", "Acme", session=sess)
    assert out and all(p["source"] == "greenhouse" for p in out)


def test_fetch_company_unknown_source_raises():
    with pytest.raises(ValueError, match="unknown source"):
        fetch_company("monster", "x", "X")


def test_fetch_company_forwards_keep_to_a_stub_gate_source(monkeypatch):
    seen = {}

    def fake_fetch(slug, company_name, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(phenom, "fetch", fake_fetch)
    gate = lambda stub: "hydrate"  # noqa: E731
    fetch_company("phenom", "apply.example.com/example.com", "Example", keep=gate)
    assert seen.get("keep") is gate


def test_fetch_company_omits_keep_for_a_plain_adapter(monkeypatch):
    # A plain adapter's fetch takes no `keep`; passing one must not reach it.
    # This strict double has no **kwargs, so a leaked kwarg raises TypeError.
    def strict_fetch(slug, company_name):
        return []

    monkeypatch.setattr(greenhouse, "fetch", strict_fetch)
    assert fetch_company("greenhouse", "acme", "Acme", keep=lambda stub: "drop") == []


def test_stub_gate_sources_is_exactly_the_two_step_adapters():
    # Pinned deliberately: `keep` is only safe for adapters that accept the kwarg
    # AND can honour a verdict without breaking their dedup key. Adding a source
    # here without wiring its fetch raises TypeError on every board it owns.
    # `icims` joined when it gained a detail step: its search card already carries
    # the id, title and location, so a 'drop'/'discard' verdict is decidable from the
    # stub and costs no dedup key (unlike workday's GUID-less stub, which is why that
    # one honours 'drop' only). `custom`/`browser` joined for the same reason once a
    # recipe could carry a `detail:` block — for a recipe with none, `keep` is inert.
    assert STUB_GATE_SOURCES == frozenset(
        {"phenom", "workday", "icims", "custom", "browser"})


# --- fetch_one_company dispatcher (per-listing detail sources) -------------

def test_fetch_one_company_dispatches_to_detail_adapter():
    from ats_worker.fetch import fetch_one_company
    sess = FakeSession(payload={"Title": "Role", "ExternalDescriptionStr": "x"})
    p = fetch_one_company("oracle", "host.fa.oraclecloud.com/CX", "123", "Co", session=sess)
    assert p["source"] == "oracle" and p["external_id"] == "123"


def test_fetch_one_company_unknown_source_raises():
    from ats_worker.fetch import fetch_one_company
    with pytest.raises(ValueError, match="unknown source"):
        fetch_one_company("monster", "x", "1", "X")


def test_fetch_one_company_non_detail_source_raises():
    # greenhouse is per-board (no fetch_one) -> explicit error, not AttributeError.
    from ats_worker.fetch import fetch_one_company
    with pytest.raises(ValueError, match="no per-listing"):
        fetch_one_company("greenhouse", "acme", "1", "X")


# --- per-adapter posted_at capture ----------------------------------------

def test_greenhouse_captures_posted_at():
    payload = {"jobs": [{"id": 1, "title": "X", "absolute_url": "http://x",
                         "content": "y", "first_published": "2026-04-17T05:58:03-04:00"}]}
    assert greenhouse.parse_jobs(payload, company_name="Acme")[0]["posted_at"] == "2026-04-17"


def test_lever_captures_posted_at():
    payload = [{"id": "1", "text": "X", "hostedUrl": "http://x",
                "descriptionPlain": "y", "createdAt": 1553186035299}]
    assert lever.parse_jobs(payload, company_name="Acme")[0]["posted_at"] == "2019-03-21"


def test_ashby_captures_posted_at():
    payload = {"jobs": [{"id": "1", "title": "X", "jobUrl": "http://x",
                         "descriptionPlain": "y", "publishedAt": "2024-03-04T14:29:08.532+00:00"}]}
    assert ashby.parse_jobs(payload, company_name="Acme")[0]["posted_at"] == "2024-03-04"


def test_pinpoint_has_no_posted_at():
    posting = pinpoint.parse_jobs(load("pinpoint.json"), company_name="Acme")[0]
    assert posting["posted_at"] is None


# --- prefilter_postings (title_exclude + max-age drop) ----------------------

def test_prefilter_drops_title_exclude():
    posts = [{"job_title": "Software Engineer", "posted_at": None},
             {"job_title": "Sales Engineer", "posted_at": None}]
    kept = prefilter_postings(posts, title_exclude=["sales"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["Software Engineer"]


def test_prefilter_drops_stale_keeps_fresh_and_dateless():
    posts = [{"job_title": "A", "posted_at": "2026-01-01"},   # ~5 months old
             {"job_title": "B", "posted_at": "2026-06-01"},   # 3 days old
             {"job_title": "C", "posted_at": None}]           # dateless -> keep
    kept = prefilter_postings(posts, max_age_days=30, now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["B", "C"]


def test_prefilter_zero_max_age_keeps_old_dates():
    posts = [{"job_title": "A", "posted_at": "2020-01-01"}]
    assert prefilter_postings(posts, max_age_days=0, now="2026-06-04") == posts


def test_prefilter_unparseable_date_is_kept():
    posts = [{"job_title": "A", "posted_at": "not-a-date"}]
    assert prefilter_postings(posts, max_age_days=30, now="2026-06-04") == posts


def test_prefilter_age_boundary_exactly_max_age_is_kept():
    # posted exactly max_age_days before now -> (today-posted).days == max_age_days,
    # strict `>` keeps it.
    posts = [{"job_title": "A", "posted_at": "2026-05-05"}]  # 30 days before 2026-06-04
    assert prefilter_postings(posts, max_age_days=30, now="2026-06-04") == posts


def test_prefilter_age_boundary_one_day_over_is_dropped():
    posts = [{"job_title": "A", "posted_at": "2026-05-04"}]  # 31 days before 2026-06-04
    assert prefilter_postings(posts, max_age_days=30, now="2026-06-04") == []


def test_prefilter_future_posted_at_is_kept():
    # negative age is never "too old"
    posts = [{"job_title": "A", "posted_at": "2026-12-01"}]
    assert prefilter_postings(posts, max_age_days=30, now="2026-06-04") == posts


def test_prefilter_exclude_is_word_matched_not_substring():
    # The asymmetry this pins: `filter_postings` (keep-list) is SUBSTRING so that
    # "quant" reaches "Quantitative"; `title_exclude` is WHOLE-WORD so that "intern"
    # does not eat "Internal Compute Frameworks". Both directions asserted here — a
    # regression that unified them would otherwise pass every other test in this file.
    posts = [{"job_title": "Software Developer - Internal Compute Frameworks (Python)"},
             {"job_title": "International Sector Analyst"},
             {"job_title": "Software Engineering Intern"}]
    kept = prefilter_postings(posts, title_exclude=["intern"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == [
        "Software Developer - Internal Compute Frameworks (Python)",
        "International Sector Analyst"]
    # ... and the keep-list still stems.
    assert len(filter_postings([{"job_title": "Quantitative Developer"}], ["quant"])) == 1


def test_prefilter_exclude_carries_short_tokens_safely():
    # `sr`, `ios` and `ii` are the tokens a substring rule could not carry: they would
    # have hit SRAM/SRE, BIOS/Biosciences and any word containing "ii".
    posts = [{"job_title": "Sr. Software Engineer"},      # dropped
             {"job_title": "iOS Engineer"},               # dropped
             {"job_title": "Software Engineer II"},       # dropped
             {"job_title": "CPU SRAM Design Engineer"},   # kept: SRAM is not `sr`
             {"job_title": "AI Support Engineer, Biosciences"}]  # kept: not `ios`
    kept = prefilter_postings(posts, title_exclude=["sr", "ios", "ii"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["CPU SRAM Design Engineer",
                                              "AI Support Engineer, Biosciences"]


def test_prefilter_exclude_key_ending_in_punctuation_still_matches():
    # Lookarounds, not \b: "co-op" ends in a word char but "ai/ml" does not, and a
    # trailing \b would never fire on the latter.
    posts = [{"job_title": "AI/ML Engineer"}, {"job_title": "Software Engineer"}]
    kept = prefilter_postings(posts, title_exclude=["ai/ml"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["Software Engineer"]


def test_prefilter_composes_keep_then_exclude():
    posts = [{"job_title": "Senior Engineer", "posted_at": None},
             {"job_title": "Sales Engineer", "posted_at": None},
             {"job_title": "Designer", "posted_at": None}]
    kept = prefilter_postings(posts, title_filter=["engineer"],
                              title_exclude=["sales"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["Senior Engineer"]
