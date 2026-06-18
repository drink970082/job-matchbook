"""Unit tests for feed/prefilter.py — the cheap active/category/sponsorship gate."""
from __future__ import annotations

from ats_worker.feed.prefilter import prefilter

KEEP = ["Software", "AI/ML/Data", "Quant"]


def _listing(**over):
    base = {"active": True, "category": "Software", "sponsorship": "Other"}
    base.update(over)
    return base


def test_keeps_active_in_category_without_explicit_no_sponsorship():
    kept = prefilter([_listing()], KEEP)
    assert len(kept) == 1


def test_drops_inactive():
    assert prefilter([_listing(active=False)], KEEP) == []


def test_drops_missing_active():
    assert prefilter([_listing(active=None)], KEEP) == []


def test_drops_category_not_in_keeplist():
    assert prefilter([_listing(category="Hardware")], KEEP) == []
    assert prefilter([_listing(category="Product")], KEEP) == []


def test_drops_explicit_no_sponsorship():
    assert prefilter([_listing(sponsorship="Does Not Offer Sponsorship")], KEEP) == []
    assert prefilter([_listing(sponsorship="U.S. Citizenship is Required")], KEEP) == []


def test_keeps_blank_and_offered_sponsorship():
    # blanks ("Other") and explicit offers are kept — the LLM screen decides.
    assert len(prefilter([_listing(sponsorship="Other")], KEEP)) == 1
    assert len(prefilter([_listing(sponsorship="Offers Sponsorship")], KEEP)) == 1


def test_keeps_each_category_in_list():
    items = [_listing(category=c) for c in KEEP]
    assert len(prefilter(items, KEEP)) == 3
