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

# Citadel (hedge fund): same WordPress theme as Citadel Securities, different host.
CITADEL_COM_LIST = (FIXTURES / "citadel_com.html").read_text(encoding="utf-8")
CITADEL_COM_DETAIL = (FIXTURES / "citadel_com_detail.html").read_text(encoding="utf-8")
CITADEL_COM_RECIPE = {
    "url": "https://www.citadel.com/careers/open-opportunities/",
    "mode": "html-css",
    "item": "a.careers-listing-card",
    "page": {"type": "url",
             "template": "https://www.citadel.com/careers/open-opportunities/page/{n}/", "start": 2},
    "fields": {
        "title": "h2", "location": ".careers-listing-card__location",
        "url": {"attr": "href"}, "external_id": {"attr": "href", "extract": "details/([^/]+)/"},
    },
    "detail": {"url_field": "job_url", "fields": {"description": ".single-job-post-description"}},
}

# Renaissance (rentec): self-hosted Struts; the job title is the anchor's OWN text
# (`{"selector": None}` = the item node itself), external_id is a query param.
RENTEC_LIST = (FIXTURES / "rentec.html").read_text(encoding="utf-8")
RENTEC_DETAIL = (FIXTURES / "rentec_detail.html").read_text(encoding="utf-8")
RENTEC_RECIPE = {
    "url": "https://www.rentec.com/Careers.action?jobs=true",
    "mode": "html-css",
    "item": "a[href*='selectedPosition=']",
    "page": {"type": "none"},
    "fields": {
        "title": {"selector": None},
        "url": {"attr": "href"},
        "external_id": {"attr": "href", "extract": "selectedPosition=([^&]+)"},
    },
    "detail": {"url_field": "job_url", "fields": {"description": ".Body_content"}},
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


def test_parse_jobs_citadel_com():
    jobs = browser.parse_jobs([CITADEL_COM_LIST], CITADEL_COM_RECIPE, "Citadel")
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["external_id"] == "quantitative-researcher-phd-intern-us"
    assert j["job_title"].startswith("Quantitative Researcher")
    assert j["location"] == "Greenwich, Houston, Miami, New York"
    assert j["job_url"].endswith("/careers/details/quantitative-researcher-phd-intern-us/")
    assert j["description"] == ""                             # comes from the detail page


def test_apply_detail_citadel_com():
    [job] = browser.parse_jobs([CITADEL_COM_LIST], CITADEL_COM_RECIPE, "Citadel")[:1]
    browser.apply_detail(job, CITADEL_COM_DETAIL, CITADEL_COM_RECIPE)
    assert "citadel" in job["description"].lower()


def test_parse_jobs_rentec_self_text_title():
    jobs = browser.parse_jobs([RENTEC_LIST], RENTEC_RECIPE, "Renaissance Technologies")
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["external_id"] == "dataCenterSpecialist"
    assert j["job_title"] == "Data Center Specialist"        # {"selector": None} = the anchor's own text
    assert j["job_url"].endswith("selectedPosition=dataCenterSpecialist")


def test_apply_detail_rentec():
    [job] = browser.parse_jobs([RENTEC_LIST], RENTEC_RECIPE, "Renaissance Technologies")[:1]
    browser.apply_detail(job, RENTEC_DETAIL, RENTEC_RECIPE)
    assert "responsib" in job["description"].lower()
