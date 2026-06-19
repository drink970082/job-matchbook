"""TDD for the Workable per-board widget adapter (watchlist-capable)."""
from __future__ import annotations

import pytest
import requests

from ats_worker.fetch import workable
from ats_worker.util import POSTING_FIELDS
from tests._helpers import FakeSession

PAYLOAD = {
    "name": "SciTec",
    "jobs": [
        {"title": "Security Engineer", "shortcode": "F09ABB200B",
         "description": "<p>Secure <b>things</b>.</p>",
         "city": "Boulder", "state": "Colorado", "country": "United States"},
        {"title": "Data Scientist", "shortcode": "00EC28A7E5",
         "description": "<p>Model.</p>", "country": "United States"},
        {"title": "No Code", "shortcode": "", "description": "x"},  # dropped (no id)
    ],
}


def test_parse_jobs_builds_canonical_and_skips_idless():
    out = workable.parse_jobs(PAYLOAD, slug="scitec", company_name="SciTec")
    assert len(out) == 2  # the empty-shortcode job is dropped
    for p in out:
        assert set(p.keys()) == set(POSTING_FIELDS)
    p = out[0]
    assert p["source"] == "workable"
    assert p["external_id"] == "F09ABB200B"
    assert p["job_url"] == "https://apply.workable.com/scitec/j/F09ABB200B"
    assert p["location"] == "Boulder, Colorado, United States"
    assert "things" in p["description"] and "<" not in p["description"]
    assert out[1]["location"] == "United States"  # only country present


def test_parse_jobs_handles_non_dict():
    assert workable.parse_jobs(None, slug="x", company_name="X") == []


def test_fetch_hits_endpoint_with_details_param():
    sess = FakeSession(payload=PAYLOAD)
    out = workable.fetch("scitec", "SciTec Co", session=sess, timeout=20)
    method, url, kwargs = sess.calls[0]
    assert method == "GET"
    assert "apply.workable.com/api/v1/widget/accounts/scitec" in url
    assert kwargs.get("params") == {"details": "true"}
    assert out and all(p["company_name"] == "SciTec Co" for p in out)


def test_fetch_propagates_http_error():
    sess = FakeSession(payload={}, raise_exc=requests.HTTPError("404"))
    with pytest.raises(requests.HTTPError):
        workable.fetch("nope", "X", session=sess)
