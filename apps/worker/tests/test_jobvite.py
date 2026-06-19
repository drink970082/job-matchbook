"""TDD for the Jobvite per-listing adapter (feed-only, JSON-LD)."""
from __future__ import annotations

import pytest
import requests

from ats_worker.fetch import jobvite
from ats_worker.util import POSTING_FIELDS
from tests._helpers import FakeSession

PAGE = '''
<html><head>
<script type="application/ld+json">
{"@context":"http://schema.org","@type":"JobPosting","title":"AI Analyst",
 "description":"<div>Kickstart your <b>AI</b> career.</div>",
 "jobLocation":[{"@type":"Place","address":{"addressLocality":"El Segundo","addressRegion":"California"}}]}
</script>
</head><body>...</body></html>
'''


def test_parse_page_extracts_jsonld():
    p = jobvite.parse_page(PAGE, slug="internetbrands", external_id="o25Rzfwh",
                           company_name="Internet Brands")
    assert set(p.keys()) == set(POSTING_FIELDS)
    assert p["source"] == "jobvite"
    assert p["external_id"] == "o25Rzfwh"
    assert p["job_title"] == "AI Analyst"
    assert p["location"] == "El Segundo, California"
    assert p["job_url"] == "https://jobs.jobvite.com/internetbrands/job/o25Rzfwh"
    assert "AI" in p["description"] and "<" not in p["description"]


def test_parse_page_no_jsonld_returns_none():
    assert jobvite.parse_page("<html>no structured data here</html>",
                              "s", "1", "Co") is None


def test_parse_page_ignores_non_jobposting_ld():
    other = ('<script type="application/ld+json">'
             '{"@type":"Organization","name":"Acme"}</script>')
    assert jobvite.parse_page(other, "s", "1", "Co") is None


def test_fetch_one_fetches_and_parses():
    sess = FakeSession(text=PAGE)
    p = jobvite.fetch_one("internetbrands", "o25Rzfwh", "Internet Brands", session=sess)
    method, url, kwargs = sess.calls[0]
    assert method == "GET"
    assert url == "https://jobs.jobvite.com/internetbrands/job/o25Rzfwh"
    assert p["job_title"] == "AI Analyst"


def test_fetch_one_missing_args_returns_none():
    sess = FakeSession(text=PAGE)
    assert jobvite.fetch_one("", "1", "Co", session=sess) is None
    assert jobvite.fetch_one("s", "", "Co", session=sess) is None


def test_fetch_one_propagates_http_error():
    sess = FakeSession(text="", raise_exc=requests.HTTPError("404"))
    with pytest.raises(requests.HTTPError):
        jobvite.fetch_one("s", "1", "Co", session=sess)
