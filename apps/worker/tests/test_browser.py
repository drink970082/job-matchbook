"""Browser recipe executor: pure CSS extraction over rendered-DOM fixtures.

The browser-driving `fetch` glue is not unit-tested (it needs a live Chromium,
like other adapters' network I/O); the extraction logic all lives in the pure
`parse_jobs` / `apply_detail`, tested here against captured Citadel HTML.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ats_worker.fetch import browser
from ats_worker.util import POSTING_FIELDS

FIXTURES = Path(__file__).parent / "fixtures"
CITADEL_LIST = (FIXTURES / "citadel.html").read_text(encoding="utf-8")
CITADEL_DETAIL = (FIXTURES / "citadel_detail.html").read_text(encoding="utf-8")

CITADEL_RECIPE = {
    "url": "https://www.citadelsecurities.com/careers/open-opportunities/",
    "mode": "html-css",
    "item": "a.careers-listing-card",
    "page": {"type": "url",
             "template": "https://www.citadelsecurities.com/careers/open-opportunities/page/{n}/",
             "start": 2},
    "fields": {
        "title": "h2",
        "location": ".careers-listing-card__location",
        "url": {"attr": "href"},
        "external_id": {"attr": "href", "extract": "details/([^/]+)/"},
    },
    "detail": {"url_field": "job_url", "fields": {"description": ".single-job-post-description"}},
}


def test_parse_jobs_extracts_cards():
    jobs = browser.parse_jobs([CITADEL_LIST], CITADEL_RECIPE, "Citadel Securities")
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["source"] == "browser"
    assert j["external_id"] == "systematic-options-trader"     # regex-extracted from href
    assert j["job_title"] == "Systematic Options Trader"
    assert j["location"] == "Miami"
    assert j["job_url"] == (
        "https://www.citadelsecurities.com/careers/details/systematic-options-trader/"
    )
    assert j["description"] == ""      # description comes from the detail page
    assert j["posted_at"] is None
    # second card's multi-city location
    assert jobs[1]["external_id"] == "systematic-trader"
    assert "Singapore" in jobs[1]["location"]


def test_parse_jobs_dedups_across_pages():
    # the same page served twice (a board that clamps pagination) must not double
    out = browser.parse_jobs([CITADEL_LIST, CITADEL_LIST], CITADEL_RECIPE, "Citadel Securities")
    assert len(out) == 2


def test_parse_jobs_requires_item_selector():
    with pytest.raises(ValueError):
        browser.parse_jobs([CITADEL_LIST], {"fields": {}}, "X")


def test_parse_jobs_no_matches_returns_empty():
    recipe = {**CITADEL_RECIPE, "item": "div.nonexistent-card"}
    assert browser.parse_jobs([CITADEL_LIST], recipe, "X") == []


def test_apply_detail_merges_description():
    [job] = browser.parse_jobs([CITADEL_LIST], CITADEL_RECIPE, "Citadel Securities")[:1]
    assert job["description"] == ""
    browser.apply_detail(job, CITADEL_DETAIL, CITADEL_RECIPE)
    assert "systematic options trader" in job["description"].lower()
    assert "Role Overview" in job["description"]


def test_apply_detail_no_detail_block_is_noop():
    job = {"description": "keep me"}
    browser.apply_detail(job, CITADEL_DETAIL, {"item": "x"})   # no `detail` in recipe
    assert job["description"] == "keep me"
