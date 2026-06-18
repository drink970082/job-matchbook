"""Unit tests for feed/simplify.py — fetch the listings.json over injected HTTP."""
from __future__ import annotations

import json

from ats_worker.feed import simplify
from tests._helpers import FIXTURES, FakeSession


def _fixture_listings():
    return json.loads((FIXTURES / "simplify_listings.json").read_text())


def test_fetch_returns_listing_array_via_injected_session():
    listings = _fixture_listings()
    sess = FakeSession(payload=listings)
    out = simplify.fetch(session=sess)
    assert out == listings
    # hit the configured listings URL once, via GET
    assert len(sess.calls) == 1
    method, url, _ = sess.calls[0]
    assert method == "GET"
    assert url == simplify.DEFAULT_URL


def test_fetch_uses_custom_url():
    sess = FakeSession(payload=[])
    simplify.fetch(url="https://example.com/feed.json", session=sess)
    assert sess.calls[0][1] == "https://example.com/feed.json"


def test_fetch_non_list_payload_is_empty():
    sess = FakeSession(payload={"unexpected": "shape"})
    assert simplify.fetch(session=sess) == []
