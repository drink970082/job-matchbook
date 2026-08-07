"""Generic `custom` recipe executor: json (GET/POST) + next-data modes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats_worker import config
from ats_worker.fetch import _recipe, custom
from ats_worker.util import BROWSER_UA, POSTING_FIELDS
from tests._helpers import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures"
AMAZON = json.loads((FIXTURES / "amazon.json").read_text())
TIKTOK = json.loads((FIXTURES / "tiktok.json").read_text())
BYTEDANCE = json.loads((FIXTURES / "bytedance.json").read_text())
JANESTREET = json.loads((FIXTURES / "janestreet.json").read_text())
DESHAW_HTML = (FIXTURES / "deshaw.html").read_text(encoding="utf-8")

AMAZON_RECIPE = {
    "method": "GET",
    "url": "https://www.amazon.jobs/en/search.json?base_query=software+engineer",
    "mode": "json",
    "item_path": "jobs",
    "total_path": "hits",
    "page": {"type": "offset", "param": "offset", "size_param": "result_limit", "size": 100},
    "fields": {
        "title": "title", "location": "normalized_location",
        "url": "https://www.amazon.jobs{job_path}", "description": "description",
        "posted_at": "posted_date", "external_id": "id_icims",
    },
}

TIKTOK_RECIPE = {
    "method": "POST",
    "url": "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts",
    "headers": {"website-path": "tiktok"},
    "body": {"recruitment_id_list": [], "keyword": "", "limit": 100, "offset": 0},
    "mode": "json",
    "item_path": "data.job_post_list",
    "total_path": "data.count",
    "page": {"type": "offset", "body_param": "offset", "size": 100},
    "fields": {
        "title": "title", "location": "city_info.en_name",
        "url": "https://lifeattiktok.com/search/{id}",
        "description": ["description", "requirement"], "external_id": "id",
    },
}

DESHAW_RECIPE = {
    "method": "GET",
    "url": "https://www.deshaw.com/careers",
    "mode": "next-data",
    "item_path": "props.pageProps.regularJobs",
    "page": {"type": "none"},
    "fields": {
        "title": "displayName", "location": "office.0.name",
        "url": "https://www.deshaw.com/careers/{data.jobUrl}",
        "description": "data.jobDescription.websiteDescription",
        "posted_at": "data.validFromDate", "external_id": "id",
    },
}

# ByteDance corp: same jobs.bytedance.com API as TikTok, different portal header/body.
BYTEDANCE_RECIPE = {
    "method": "POST",
    "url": "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts",
    "headers": {"website-path": "en"},
    "body": {"recruitment_id_list": ["201"], "job_category_id_list": [], "subject_id_list": [],
             "location_code_list": [], "keyword": "", "limit": 100, "offset": 0},
    "mode": "json",
    "item_path": "data.job_post_list",
    "total_path": "data.count",
    "page": {"type": "offset", "body_param": "offset", "size": 100},
    "fields": {
        "title": "title", "location": "city_info.en_name",
        "url": "https://joinbytedance.com/search/{id}",
        "description": ["description", "requirement"], "external_id": "id",
    },
}

# Jane Street: main.json is a bare top-level array -> no item_path.
JANESTREET_RECIPE = {
    "url": "https://www.janestreet.com/jobs/main.json",
    "mode": "json",
    "headers": {"User-Agent": "Mozilla/5.0"},
    "page": {"type": "none"},
    "fields": {
        "title": "position", "location": "city",
        "url": "https://www.janestreet.com/join-jane-street/position/{id}/",
        "description": "overview", "external_id": "id",
    },
}


# --- SSRF guard -----------------------------------------------------------

def test_custom_fetch_refuses_internal_url():
    sess = FakeSession(payload={"jobs": []})
    with pytest.raises(ValueError):
        custom.fetch("slug", "Acme", {"url": "http://127.0.0.1/jobs"}, session=sess)
    assert sess.calls == []


_REDIRECT_RECIPE = {
    "url": "https://board.example.com/jobs",
    "mode": "json",
    "page": {"type": "none"},
    "fields": {"title": "position", "external_id": "id",
               "url": "https://board.example.com/{id}/", "location": "city"},
}


def test_custom_fetch_follows_legit_redirect_to_public_target():
    redirect = FakeResponse(status_code=302, is_redirect=True,
                            headers={"location": "https://board.example.com/jobs-moved"})
    payload = [{"id": "1", "position": "Engineer", "city": "NYC"}]
    final = FakeResponse(payload=payload, status_code=200)
    sess = FakeSession(responses=[redirect, final])

    out = custom.fetch("acme", "Acme", _REDIRECT_RECIPE, session=sess, timeout=20)

    assert len(out) == 1
    assert out[0]["external_id"] == "1"
    assert [c[1] for c in sess.calls] == [
        "https://board.example.com/jobs", "https://board.example.com/jobs-moved",
    ]


def test_custom_fetch_refuses_redirect_to_internal_target():
    # Same body-content trap as embedded_gh's redirect test: the 302 response
    # carries a JSON payload that WOULD parse into a posting if a redirect-blind
    # implementation treated the first hop's body as the answer — proving the
    # failure is "the hop was correctly refused", not "there was nothing to parse".
    redirect = FakeResponse(status_code=302, is_redirect=True,
                            payload=[{"id": "1", "position": "Engineer", "city": "NYC"}],
                            headers={"location": "http://169.254.169.254/jobs"})
    sess = FakeSession(responses=[redirect])

    with pytest.raises(ValueError):
        custom.fetch("acme", "Acme", _REDIRECT_RECIPE, session=sess, timeout=20)

    assert len(sess.calls) == 1  # only the initial (safe) hop was requested
    assert not any("169.254.169.254" in c[1] for c in sess.calls)


def test_custom_fetch_post_recipe_follows_redirect_to_public_target():
    # method="POST" exercises the other branch of `_request` (the two tests
    # above default to GET): get_redirect_safe downgrades a redirect hop to
    # GET regardless of the original method (see util.get_redirect_safe), so
    # this proves the POST recipe's initial hop still gets a GET-on-redirect
    # follow-through rather than erroring or re-POSTing the Location.
    redirect = FakeResponse(status_code=302, is_redirect=True,
                            headers={"location": "https://board.example.com/jobs-moved"})
    payload = [{"id": "1", "position": "Engineer", "city": "NYC"}]
    final = FakeResponse(payload=payload, status_code=200)
    sess = FakeSession(responses=[redirect, final])

    recipe = {**_REDIRECT_RECIPE, "method": "POST"}
    out = custom.fetch("acme", "Acme", recipe, session=sess, timeout=20)

    assert len(out) == 1
    assert out[0]["external_id"] == "1"
    assert [c[0] for c in sess.calls] == ["POST", "GET"]  # redirect hop downgrades to GET
    assert [c[1] for c in sess.calls] == [
        "https://board.example.com/jobs", "https://board.example.com/jobs-moved",
    ]


# --- recipe helpers ------------------------------------------------------

def test_dotted_get_indexes_dicts_and_lists():
    obj = {"office": [{"name": "NYC"}, {"name": "London"}]}
    assert _recipe.dotted_get(obj, "office.0.name") == "NYC"
    assert _recipe.dotted_get(obj, "office.1.name") == "London"
    assert _recipe.dotted_get(obj, "office.9.name") is None   # out of range
    assert _recipe.dotted_get(obj, "missing.path") is None


def test_interpolate_url_template():
    assert _recipe.interpolate("x/{id}/y", {"id": 5}) == "x/5/y"
    assert _recipe.interpolate("a{b.c}", {"b": {"c": "z"}}) == "az"


@pytest.mark.parametrize("value,expected", [
    ("July 17, 2026", "2026-07-17"),
    ("Jul 17, 2026", "2026-07-17"),
    ("2026-04-15", "2026-04-15"),
    ("2026-04-15T09:00:00Z", "2026-04-15"),
    (1784386514, "2026"),            # epoch seconds
    (1700000000000, "2023"),         # epoch ms
    (None, None), ("", None), ("garbage", None), (True, None),
])
def test_normalize_date(value, expected):
    got = _recipe.normalize_date(value)
    if expected is None:
        assert got is None
    else:
        assert got.startswith(expected)


# --- json mode (Amazon GET) ---------------------------------------------

def test_parse_jobs_amazon_maps_fields():
    jobs = custom.parse_jobs(AMAZON, AMAZON_RECIPE, "Amazon")
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["source"] == "custom"
    assert j["external_id"] == "10477971"
    assert j["job_title"].startswith("Software Development Engineer")
    assert j["location"] == "Austin, Texas, USA"
    assert j["job_url"] == (
        "https://www.amazon.jobs/en/jobs/10477971/"
        "software-development-engineer-aws-opensearch-service"
    )
    assert j["posted_at"] == "2026-07-17"     # "July 17, 2026" normalized
    assert j["description"]


def test_parse_jobs_bytedance_maps_fields():
    jobs = custom.parse_jobs(BYTEDANCE, BYTEDANCE_RECIPE, "ByteDance")
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["source"] == "custom"
    assert j["external_id"] and j["job_title"]
    assert j["location"]                                      # city_info.en_name
    assert j["job_url"].startswith("https://joinbytedance.com/search/")
    assert j["description"]                                   # description + requirement concat


def test_parse_jobs_janestreet_bare_array():
    jobs = custom.parse_jobs(JANESTREET, JANESTREET_RECIPE, "Jane Street")  # no item_path
    assert len(jobs) == 2
    j = jobs[0]
    assert set(j) == set(POSTING_FIELDS)
    assert j["external_id"] and j["job_title"]
    assert j["job_url"].startswith("https://www.janestreet.com/join-jane-street/position/")
    assert j["posted_at"] is None                            # feed carries no date


def test_parse_jobs_rejects_non_list_item_path():
    with pytest.raises(ValueError):
        custom.parse_jobs({"jobs": {"not": "a list"}}, AMAZON_RECIPE, "Amazon")


def test_parse_jobs_root_array_no_item_path():
    """A bare JSON array (root IS the job list, e.g. Jane Street) needs no item_path."""
    recipe = {"fields": {"title": "position", "external_id": "id",
                         "url": "https://x/{id}/", "location": "city"}}
    payload = [{"id": 7, "position": "Trader", "city": "NYC"}]
    jobs = custom.parse_jobs(payload, recipe, "Jane Street")
    assert len(jobs) == 1
    assert jobs[0]["external_id"] == "7"
    assert jobs[0]["job_title"] == "Trader"
    assert jobs[0]["job_url"] == "https://x/7/"


class _Resp:
    # is_redirect/headers default to a plain non-redirect response — the shape
    # get_redirect_safe inspects on every hop before returning.
    def __init__(self, payload=None, *, text="", is_redirect=False, headers=None):
        self._payload = payload
        self.text = text
        self.is_redirect = is_redirect
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _PagedJson:
    """First page (offset 0) returns `full`; later pages return `empty`. Offset is
    read from GET params or the POST json body. Records every call."""

    def __init__(self, full, empty):
        self._full, self._empty = full, empty
        self.calls: list[tuple] = []

    @staticmethod
    def _offset(params, body):
        if params and "offset" in params:
            return params["offset"]
        if body and "offset" in body:
            return body["offset"]
        return 0

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
        self.calls.append(("GET", url, params, None, headers))
        return _Resp(self._full if self._offset(params, None) == 0 else self._empty)

    def post(self, url, params=None, json=None, headers=None, timeout=None, allow_redirects=None):
        self.calls.append(("POST", url, params, json, headers))
        return _Resp(self._full if self._offset(params, json) == 0 else self._empty)


def test_fetch_amazon_offset_get_pagination():
    sess = _PagedJson(AMAZON, {"hits": 1986, "jobs": []})
    out = custom.fetch("amazon", "Amazon", AMAZON_RECIPE, session=sess, timeout=20)
    assert len(out) == 2
    offsets = [(p or {}).get("offset") for _, _, p, _, _ in sess.calls]
    assert offsets == [0, 2]                   # advance by rows, then empty page -> stop
    assert (sess.calls[0][2] or {}).get("result_limit") == 100  # size_param applied
    assert all(m == "GET" for m, *_ in sess.calls)


def test_a_recipe_urls_own_query_string_survives_pagination():
    """Pagination goes in `params`, never spliced into the url — so a recipe that
    carries its own filter keeps it on every page.

    The shipped Amazon recipe is
    `...search.json?base_query=software+engineer&normalized_country_code%5B%5D=USA`
    (`[]` percent-encoded, as the live row and the example both write it)
    (`config.yaml.example`), a US-only filter that removes ~768 rows/pass with zero
    coverage loss (BACKLOG, the intake-cut entry). Rebuild the url by concatenation —
    the obvious "simplification" — and the `?offset=` clobbers the filter, silently
    restoring the non-US rows on every page but the first.

    SCOPE, so nobody reads more assurance into this than it gives: the session here is
    injected, so what is pinned is *this executor's* contract — url passed through
    byte-identical, pagination confined to `params`. The other half of the guarantee is
    `requests` merging `params=` onto an existing query string, which no unit test
    covers because no real client is involved. A session object that REPLACED the query
    string instead of merging would keep this test green and still kill the filter."""
    recipe = dict(AMAZON_RECIPE,
                  url=AMAZON_RECIPE["url"] + "&normalized_country_code%5B%5D=USA")
    sess = _PagedJson(AMAZON, {"hits": 1986, "jobs": []})
    custom.fetch("amazon", "Amazon", recipe, session=sess, timeout=20)

    assert [url for _, url, *_ in sess.calls] == [recipe["url"]] * len(sess.calls)
    assert all("offset" not in url for _, url, *_ in sess.calls)
    assert [(p or {}).get("offset") for _, _, p, _, _ in sess.calls] == [0, 2]


def test_fetch_tiktok_post_headers_and_body_offset():
    sess = _PagedJson(TIKTOK, {"data": {"count": 3701, "job_post_list": []}})
    out = custom.fetch("tiktok", "TikTok", TIKTOK_RECIPE, session=sess, timeout=20)
    assert len(out) == 2
    assert all(m == "POST" for m, *_ in sess.calls)
    # The recipe's own headers pass through, plus the defaulted browser UA. A recipe
    # that sets its own User-Agent still wins -- setdefault, not overwrite.
    assert sess.calls[0][4] == {"website-path": "tiktok", "User-Agent": BROWSER_UA}
    body_offsets = [(b or {}).get("offset") for _, _, _, b, _ in sess.calls]
    assert body_offsets == [0, 2]                               # offset in POST body
    j = out[0]
    assert j["location"] == "Singapore"                        # city_info.en_name
    assert j["job_url"].startswith("https://lifeattiktok.com/search/")
    assert j["posted_at"] is None                              # no date field
    assert j["description"]                                    # description + requirement concat


def test_fetch_deshaw_next_data():
    class _HtmlSession:
        def __init__(self, html):
            self._html = html
            self.calls = []

        def get(self, url, params=None, headers=None, timeout=None, allow_redirects=None):
            self.calls.append((url, params))
            return _Resp(text=self._html)

    out = custom.fetch("deshaw", "D. E. Shaw", DESHAW_RECIPE,
                       session=_HtmlSession(DESHAW_HTML), timeout=20)
    assert len(out) == 2
    j = out[0]
    assert j["external_id"] == "5874"
    assert j["job_title"] == "Administrative Associate (6-Month LTA)"
    assert j["location"] == "New York"                         # office.0.name (list index)
    assert j["job_url"].endswith("/Administrative-Associate-6-Month-LTA-5874")
    assert j["posted_at"] == "2026-04-15"
    assert "administrative" in j["description"].lower()


# --- config validation ---------------------------------------------------

def test_config_custom_requires_recipe():
    with pytest.raises(config.ConfigError):
        config.load_config(
            "companies:\n  - {source: custom, slug: acme, name: Acme}\n"
        )


def test_config_custom_with_recipe_parses():
    cfg = config.load_config(
        "companies:\n"
        "  - source: custom\n"
        "    slug: acme\n"
        "    name: Acme\n"
        "    recipe: {url: 'https://x', item_path: jobs}\n"
    )
    assert cfg.companies[0].recipe == {"url": "https://x", "item_path": "jobs"}


def test_config_bad_recipe_type_rejected():
    with pytest.raises(config.ConfigError):
        config.load_config(
            "companies:\n  - {source: greenhouse, slug: acme, name: Acme, recipe: notamap}\n"
        )


# --- `detail:` block: hydrate from one detail document per posting --------

LIST_RECIPE = {
    "method": "GET",
    "url": "https://boards.example.com/api/search",
    "mode": "json",
    "item_path": "results",
    "page": {"type": "none"},
    "fields": {"title": "postingTitle", "url": "https://x/{positionId}",
               "description": "teaser", "external_id": "id"},
}
LIST_PAYLOAD = {"results": [
    {"id": "PIPE-900", "positionId": "900", "postingTitle": "Engineer", "teaser": "short"},
]}


def test_detail_url_template_interpolates_against_the_RAW_item():
    """The id a detail endpoint wants is often NOT the one mapped to external_id
    (Apple keys its detail API on positionId while external_id is `id`). Re-pointing
    external_id would re-key every stored row, so the template reads the raw item."""
    recipe = {**LIST_RECIPE, "detail": {
        "mode": "http-json",
        "url": "https://boards.example.com/api/jobDetails/{positionId}",
        "fields": {"description": "res.body"}}}
    sess = FakeSession(responses=[
        FakeResponse(LIST_PAYLOAD),
        FakeResponse({"res": {"body": "the full job description"}}),
    ])
    out = custom.fetch("acme", "Acme", recipe, session=sess)
    assert out[0]["description"] == "the full job description"
    assert sess.calls[1][1] == "https://boards.example.com/api/jobDetails/900"


def test_detail_url_field_reuses_the_postings_own_url():
    recipe = {**LIST_RECIPE, "detail": {
        "mode": "http-json", "url_field": "job_url",
        "fields": {"description": "res.body"}}}
    sess = FakeSession(responses=[
        FakeResponse(LIST_PAYLOAD), FakeResponse({"res": {"body": "hydrated"}}),
    ])
    out = custom.fetch("acme", "Acme", recipe, session=sess)
    assert out[0]["description"] == "hydrated"
    assert sess.calls[1][1] == "https://x/900"


def test_detail_html_mode_selects_on_the_rendered_page():
    """A board may list as JSON and hydrate from HTML: the detail transport is
    independent of the list transport."""
    recipe = {**LIST_RECIPE, "detail": {
        "mode": "http-html", "url_field": "job_url",
        "fields": {"description": ".jd"}}}
    sess = FakeSession(responses=[
        FakeResponse(LIST_PAYLOAD),
        FakeResponse(text="<html><div class='jd'>rendered JD body</div></html>"),
    ])
    out = custom.fetch("acme", "Acme", recipe, session=sess)
    assert "rendered JD body" in out[0]["description"]


def test_no_detail_block_makes_no_extra_request():
    sess = FakeSession(responses=[FakeResponse(LIST_PAYLOAD)])
    out = custom.fetch("acme", "Acme", LIST_RECIPE, session=sess)
    assert out[0]["description"] == "short"
    assert len(sess.calls) == 1


def test_detail_keep_gate_skips_the_call_for_a_doomed_posting():
    recipe = {**LIST_RECIPE, "detail": {
        "mode": "http-json", "url_field": "job_url",
        "fields": {"description": "res.body"}}}
    sess = FakeSession(responses=[FakeResponse(LIST_PAYLOAD)])
    out = custom.fetch("acme", "Acme", recipe, session=sess, keep=lambda p: "drop")
    assert out == [] and len(sess.calls) == 1


def test_a_recipe_user_agent_overrides_the_default():
    recipe = {**LIST_RECIPE, "headers": {"User-Agent": "custom-agent/1.0"}}
    sess = FakeSession(responses=[FakeResponse(LIST_PAYLOAD)])
    custom.fetch("acme", "Acme", recipe, session=sess)
    assert sess.calls[0][2]["headers"]["User-Agent"] == "custom-agent/1.0"
