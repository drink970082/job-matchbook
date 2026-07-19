"""Generic `custom` recipe executor: json (GET/POST) + next-data modes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats_worker import config
from ats_worker.fetch import _recipe, custom
from ats_worker.util import POSTING_FIELDS
from tests._helpers import FakeSession

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
    def __init__(self, payload=None, *, text=""):
        self._payload = payload
        self.text = text

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

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, None, headers))
        return _Resp(self._full if self._offset(params, None) == 0 else self._empty)

    def post(self, url, params=None, json=None, headers=None, timeout=None):
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


def test_fetch_tiktok_post_headers_and_body_offset():
    sess = _PagedJson(TIKTOK, {"data": {"count": 3701, "job_post_list": []}})
    out = custom.fetch("tiktok", "TikTok", TIKTOK_RECIPE, session=sess, timeout=20)
    assert len(out) == 2
    assert all(m == "POST" for m, *_ in sess.calls)
    assert sess.calls[0][4] == {"website-path": "tiktok"}       # headers passed
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

        def get(self, url, params=None, headers=None, timeout=None):
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
