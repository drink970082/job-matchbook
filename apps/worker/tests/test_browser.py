"""Browser recipe executor: pure CSS extraction over rendered-DOM fixtures.

The browser-driving `fetch` glue is not unit-tested against a live Chromium
(like other adapters' network I/O); the extraction logic all lives in the pure
`parse_jobs` / `apply_detail`, tested here against captured Citadel HTML.

The SSRF guards on the scraped detail URL and the pagination URL (inside
`fetch`'s `with sync_playwright()` block) ARE exercised here, though, by
registering a fake `playwright.sync_api` in sys.modules (see
`_install_fake_playwright`) implementing just enough of the
Page/BrowserContext/Browser surface for `fetch` to drive — no real browser and
no installed `playwright` needed, so these run in the hermetic suite / CI.
"""
from __future__ import annotations

import sys
import types
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


# --- SSRF guard -----------------------------------------------------------

def test_browser_fetch_refuses_internal_url():
    with pytest.raises(ValueError):
        browser.fetch("slug", "Acme", {"url": "http://169.254.169.254/", "item": ".job"})


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    """Fake Playwright `Route`: records whether continue_()/abort() was called."""

    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.continued = False
        self.aborted = False

    def continue_(self):
        self.continued = True

    def abort(self):
        self.aborted = True


def test_block_unsafe_navigation_aborts_internal_target():
    # This is the redirect backstop: a 302 issued mid-navigation (initial nav,
    # pagination, or detail) re-enters the router with the Location as the new
    # request URL, so blocking here closes the redirect-to-internal SSRF gap
    # regardless of which navigation triggered it.
    route = _FakeRoute("http://169.254.169.254/latest/meta-data/")
    browser._block_unsafe_navigation(route)
    assert route.aborted is True
    assert route.continued is False


def test_block_unsafe_navigation_continues_public_target():
    route = _FakeRoute("https://example.com/careers")
    browser._block_unsafe_navigation(route)
    assert route.continued is True
    assert route.aborted is False


class _FakePage:
    """Just enough of Playwright's Page surface for `fetch` to drive: goto()
    records the requested URL and switches content() to whatever `content_map`
    has for it (missing -> ''), wait_for_* are no-ops.

    `final_url_map` (requested url -> landed url) models a server-side redirect:
    Playwright's real `page.url` reflects the URL the browser actually landed on
    after following any 3xx, not the one passed to goto(). Omitting it (the
    default, `None`) leaves `self.url` equal to the requested URL — the existing
    no-redirect tests are unaffected."""

    def __init__(self, content_map: dict[str, str], final_url_map: dict[str, str] | None = None):
        self.goto_calls: list[str] = []
        self._content_map = content_map
        self._final_url_map = final_url_map or {}
        self._current = ""
        self.url = ""

    def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append(url)
        self.url = self._final_url_map.get(url, url)
        self._current = self._content_map.get(self.url, "")

    def wait_for_selector(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def content(self):
        return self._current

    def route(self, pattern, handler):
        """No-op: the SSRF route-interceptor registration itself isn't under
        test here (see the direct _block_unsafe_navigation tests below) — this
        just lets `fetch()` call `page.route(...)` without erroring."""


class _FakeContext:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page


class _FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_context(self, **kwargs):
        return _FakeContext(self._page)

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, page):
        self._page = page

    def launch(self, **kwargs):
        return _FakeBrowser(self._page)


class _FakePlaywright:
    def __init__(self, page):
        self.chromium = _FakeChromium(page)


class _FakeSyncPlaywright:
    """Stands in for `playwright.sync_api.sync_playwright()`'s context manager."""

    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return _FakePlaywright(self._page)

    def __exit__(self, *exc):
        return False


def _install_fake_playwright(monkeypatch, page):
    """Register a fake `playwright.sync_api` in sys.modules so `fetch`'s lazy
    `from playwright.sync_api import sync_playwright` resolves to the stub —
    exercising the guards with NO playwright installed (it's an optional extra
    absent from the hermetic test env / CI worker job). A string-target
    monkeypatch.setattr would instead `__import__("playwright")` and ERROR."""
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _FakeSyncPlaywright(page)
    pkg = types.ModuleType("playwright")
    pkg.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


_GUARD_RECIPE_BASE = {
    "url": "https://example.com/careers",
    "item": "a.job",
    "fields": {
        "title": {"selector": None},
        "url": {"attr": "href"},
        "external_id": {"attr": "href"},
    },
}


def test_browser_fetch_skips_unsafe_detail_url(monkeypatch):
    """A detail href scraped from third-party listing HTML that resolves to an
    internal target (the real SSRF vector: a compromised/malicious board embeds
    e.g. the cloud metadata IP as a job's href) must never be rendered — the
    posting is kept, just description-less, same as a failed render."""
    listing_html = (
        '<div>'
        '<a class="job" href="https://example.com/job/1">Job One</a>'
        '<a class="job" href="http://169.254.169.254/secret">Job Two</a>'
        '</div>'
    )
    detail_html = "<div class='jd'>Real description</div>"
    page = _FakePage({
        "https://example.com/careers": listing_html,
        "https://example.com/job/1": detail_html,
        # deliberately no entry for the internal URL: if it's ever goto()'d the
        # assertion on goto_calls below catches it regardless of what content()
        # would have returned.
    })
    _install_fake_playwright(monkeypatch, page)

    recipe = {
        **_GUARD_RECIPE_BASE,
        "page": {"type": "none"},
        "detail": {"url_field": "job_url", "fields": {"description": ".jd"}},
    }
    postings = browser.fetch("slug", "Acme", recipe)

    assert page.goto_calls == ["https://example.com/careers", "https://example.com/job/1"]
    assert len(postings) == 2
    safe = next(p for p in postings if p["job_url"] == "https://example.com/job/1")
    unsafe = next(p for p in postings if p["job_url"] == "http://169.254.169.254/secret")
    assert "Real description" in safe["description"]
    assert unsafe["description"] == ""


def test_browser_fetch_discards_detail_page_that_redirects_to_internal_target(monkeypatch):
    """A detail href that itself passes `is_safe_public_url` (it's a public URL)
    but server-side 302s to an internal target (e.g. 169.254.169.254) must not
    leak the internal response into the posting's description.

    Playwright's own `page.route` interceptor does NOT catch this: per the
    Playwright docs, the route handler fires only for a navigation's INITIAL
    URL — a 3xx redirect is followed by Chromium without re-invoking the
    handler for the Location target. So the only backstop is inspecting
    `page.url` (the URL actually landed on) AFTER goto() returns, which is
    what `render()` now does. Before that change this test fails RED: the
    internal page's body ends up in `description`."""
    listing_html = (
        '<div><a class="job" href="https://example.com/job/1">Job One</a></div>'
    )
    internal_detail_html = "<div class='jd'>SECRET METADATA</div>"
    page = _FakePage(
        content_map={
            "https://example.com/careers": listing_html,
            "http://169.254.169.254/secret": internal_detail_html,
        },
        final_url_map={
            # the requested (public, guard-passing) detail URL lands on the
            # internal target after a server-side redirect Playwright follows
            # transparently — page.url reflects the LANDED url, not the one
            # passed to goto().
            "https://example.com/job/1": "http://169.254.169.254/secret",
        },
    )
    _install_fake_playwright(monkeypatch, page)

    recipe = {
        **_GUARD_RECIPE_BASE,
        "page": {"type": "none"},
        "detail": {"url_field": "job_url", "fields": {"description": ".jd"}},
    }
    postings = browser.fetch("slug", "Acme", recipe)

    # the redirect IS followed (goto is called with the public href — this is
    # the residual single read-only GET, accepted) but its response is discarded.
    assert page.goto_calls == ["https://example.com/careers", "https://example.com/job/1"]
    [posting] = postings
    assert posting["description"] == ""
    assert "SECRET" not in posting["description"]


def test_browser_fetch_raises_on_unsafe_pagination_url(monkeypatch):
    """The pagination template is operator-authored (lower risk than the scraped
    detail href), but an unsafe rendered page URL must fail loudly — same as an
    unsafe recipe.url — not silently return page-1 as success (which would hide a
    broken template and permanently drop pages 2+). The listing page is rendered
    first, then the guard raises before the bad page is ever goto()'d."""
    listing_html = '<div><a class="job" href="https://example.com/job/1">Job One</a></div>'
    page = _FakePage({"https://example.com/careers": listing_html})
    _install_fake_playwright(monkeypatch, page)

    recipe = {
        **_GUARD_RECIPE_BASE,
        "page": {"type": "url", "template": "http://169.254.169.254/page/{n}", "start": 2},
    }
    with pytest.raises(ValueError):
        browser.fetch("slug", "Acme", recipe)

    assert page.goto_calls == ["https://example.com/careers"]  # paginated url never rendered


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


# A Balyasny-shape board: the id lives in a data-* attr, routing is JS-side, so the
# card carries no href — job_url can only be built by templating an extracted field.
_TEMPLATE_URL_LIST = """
<html><body>
  <div class="job" data-id="Quant_REQ8036">
    <span class="t">Quantitative Researcher</span>
    <span class="loc">New York</span>
  </div>
</body></html>
"""

_TEMPLATE_URL_RECIPE = {
    "url": "https://careers.bamfunds.com/careers",
    "item": "div.job",
    "fields": {
        "title": ".t",
        "location": ".loc",
        "external_id": {"attr": "data-id"},
        "url": "/s/details?jobReq={external_id}",
    },
}


def test_parse_jobs_url_template_interpolates_an_extracted_field():
    [job] = browser.parse_jobs([_TEMPLATE_URL_LIST], _TEMPLATE_URL_RECIPE, "Balyasny")
    assert job["external_id"] == "Quant_REQ8036"
    # `{external_id}` filled from the extracted field, then resolved against base_url.
    assert job["job_url"] == "https://careers.bamfunds.com/s/details?jobReq=Quant_REQ8036"


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
