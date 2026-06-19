"""TDD for the Oracle Recruiting Cloud per-listing adapter (feed-only).

Oracle has no public board-LIST endpoint, so the adapter exposes `fetch_one`
(one requisition by id) rather than `fetch`. Exercised with an injected fake
session — no network.
"""
from __future__ import annotations

import pytest
import requests

from ats_worker.fetch import oracle
from ats_worker.util import POSTING_FIELDS
from tests._helpers import FakeSession

# The detail body's internal RequisitionId DIFFERS from the URL req id on purpose:
# the adapter must key on the URL id (what the resolver surfaced), not the body's.
DETAIL = {
    "Title": "Equity Quant Researcher",
    "RequisitionId": 300082384493036,
    "PrimaryLocation": "London",
    "ExternalDescriptionStr": "<p>Build <strong>quant</strong> models.</p>",
    "ExternalResponsibilitiesStr": "<ul><li>Research markets</li></ul>",
    "ExternalQualificationsStr": "<p>PhD preferred.</p>",
}

SLUG = "jpmc.fa.oraclecloud.com/CX_1001"


def test_parse_job_builds_canonical():
    p = oracle.parse_job(DETAIL, slug=SLUG, external_id="210706680", company_name="JPMC")
    assert set(p.keys()) == set(POSTING_FIELDS)
    assert p["source"] == "oracle"
    # external_id is the URL req id, NOT the payload's internal RequisitionId.
    assert p["external_id"] == "210706680"
    assert p["company_name"] == "JPMC"
    assert p["job_title"] == "Equity Quant Researcher"
    assert p["location"] == "London"
    assert p["job_url"] == ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/"
                            "en/sites/CX_1001/job/210706680")
    # all three sections stitched + flattened to readable text
    assert "quant" in p["description"]
    assert "Research markets" in p["description"]
    assert "PhD" in p["description"]
    assert "<" not in p["description"] and ">" not in p["description"]


def test_parse_job_handles_items_wrapper_and_empty_fields():
    p = oracle.parse_job({"items": [{"Title": "Role"}]}, slug=SLUG,
                         external_id="1", company_name="Co")
    assert p["job_title"] == "Role"
    assert p["location"] is None
    assert p["description"] == ""


def test_fetch_one_hits_detail_endpoint():
    sess = FakeSession(payload=DETAIL)
    p = oracle.fetch_one(SLUG, "210706680", "JPMC", session=sess, timeout=20)
    method, url, kwargs = sess.calls[0]
    assert method == "GET"
    assert url == ("https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/"
                   "recruitingCEJobRequisitionDetails/210706680")
    assert p["external_id"] == "210706680"
    assert p["job_title"] == "Equity Quant Researcher"


def test_fetch_one_missing_host_or_id_returns_none():
    sess = FakeSession(payload=DETAIL)
    assert oracle.fetch_one("", "1", "Co", session=sess) is None
    assert oracle.fetch_one(SLUG, "", "Co", session=sess) is None


def test_fetch_one_propagates_http_error():
    sess = FakeSession(payload={}, raise_exc=requests.HTTPError("500"))
    with pytest.raises(requests.HTTPError):
        oracle.fetch_one(SLUG, "1", "Co", session=sess)
