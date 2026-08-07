"""Shared detail-hydration stage: extraction by document type, the stub gate, and the
board-level circuit breaker.

`hydrate` is pure given `fetch_doc`, so everything below runs with no network — the
same shape as test_phenom.py's stub-gate tests.
"""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from ats_worker.fetch import _detail
from tests._helpers import FakeResponse, FakeSession, make_posting

SPEC = {"fields": {"description": "res.body"}}
HTML_SPEC = {"fields": {"description": ".jd"}}


def _url(posting):
    return f"https://example.com/d/{posting['external_id']}"


def _postings(n=3):
    return [make_posting(str(i), description="") for i in range(n)]


# --- extraction dispatches on the document TYPE ---------------------------

def test_dict_document_reads_dotted_paths():
    out = _detail.hydrate(_postings(1), SPEC, detail_url=_url,
                          fetch_doc=lambda u: {"res": {"body": "full JD here"}})
    assert out[0]["description"] == "full JD here"


def test_node_document_reads_css_selectors():
    doc = BeautifulSoup("<div class='jd'><p>full</p><p>JD</p></div>", "html.parser")
    out = _detail.hydrate(_postings(1), HTML_SPEC, detail_url=_url, fetch_doc=lambda u: doc)
    assert "full" in out[0]["description"] and "JD" in out[0]["description"]


def test_json_description_accepts_a_list_of_paths():
    spec = {"fields": {"description": ["res.a", "res.b"]}}
    out = _detail.hydrate(_postings(1), spec, detail_url=_url,
                          fetch_doc=lambda u: {"res": {"a": "one", "b": "two"}})
    assert "one" in out[0]["description"] and "two" in out[0]["description"]


def test_non_description_fields_merge_too():
    spec = {"fields": {"description": "res.body", "location": "res.loc"}}
    out = _detail.hydrate(_postings(1), spec, detail_url=_url,
                          fetch_doc=lambda u: {"res": {"body": "jd", "loc": "Berlin"}})
    assert out[0]["location"] == "Berlin"


def test_blank_detail_never_erases_the_list_description():
    """A detail page that renders an empty section must not cost us what the list
    call already gave us."""
    posting = make_posting("1", description="from the list call")
    out = _detail.hydrate([posting], SPEC, detail_url=_url,
                          fetch_doc=lambda u: {"res": {"body": ""}})
    assert out[0]["description"] == "from the list call"


def test_no_fields_in_spec_is_a_passthrough():
    calls = []
    out = _detail.hydrate(_postings(2), {}, detail_url=_url,
                          fetch_doc=lambda u: calls.append(u))
    assert len(out) == 2 and calls == []


# --- the stub gate: same contract the two-step adapters use ---------------

def test_keep_drop_omits_the_posting_and_skips_the_call():
    calls = []
    out = _detail.hydrate(_postings(2), SPEC, detail_url=_url, keep=lambda p: "drop",
                          fetch_doc=lambda u: calls.append(u) or {"res": {"body": "x"}})
    assert out == [] and calls == []


def test_keep_discard_stores_the_posting_unhydrated():
    calls = []
    out = _detail.hydrate(_postings(2), SPEC, detail_url=_url, keep=lambda p: "discard",
                          fetch_doc=lambda u: calls.append(u) or {"res": {"body": "x"}})
    assert len(out) == 2 and all(p["description"] == "" for p in out) and calls == []


def test_an_unknown_keep_verdict_hydrates():
    """A broken predicate must cost requests, never postings."""
    out = _detail.hydrate(_postings(1), SPEC, detail_url=_url, keep=lambda p: "???",
                          fetch_doc=lambda u: {"res": {"body": "jd"}})
    assert out[0]["description"] == "jd"


# --- the circuit breaker is per BOARD, not per posting --------------------

def test_breaker_stops_the_board_after_n_consecutive_no_gain(capsys):
    calls = []

    def doc(url):
        calls.append(url)
        return {"res": {"body": ""}}          # a bot wall: HTTP 200, no JD

    out = _detail.hydrate(_postings(10), SPEC, detail_url=_url, fetch_doc=doc,
                          breaker=3, label="custom/acme")
    assert len(calls) == 3, "breaker must stop the board, not retry per posting"
    assert len(out) == 10, "postings survive un-hydrated; only hydration stops"
    assert "hydration STOPPED" in capsys.readouterr().out


def test_a_raising_fetch_counts_toward_the_breaker_and_keeps_the_posting():
    calls = []

    def doc(url):
        calls.append(url)
        raise RuntimeError("connection reset")

    out = _detail.hydrate(_postings(10), SPEC, detail_url=_url, fetch_doc=doc, breaker=2)
    assert len(calls) == 2 and len(out) == 10


def test_the_breaker_resets_on_a_gain():
    """Two failures, a success, then two more must not trip a breaker of 3."""
    seq = [{"res": {"body": ""}}, {"res": {"body": ""}}, {"res": {"body": "jd"}},
           {"res": {"body": ""}}, {"res": {"body": ""}}]
    calls = []

    def doc(url):
        calls.append(url)
        return seq.pop(0)

    _detail.hydrate(_postings(5), SPEC, detail_url=_url, fetch_doc=doc, breaker=3)
    assert len(calls) == 5


# --- the detail href comes from third-party HTML, so it is checked --------

@pytest.mark.parametrize("url", [None, "", "http://127.0.0.1/admin",
                                 "http://169.254.169.254/latest/meta-data/"])
def test_a_missing_or_unsafe_detail_url_is_skipped_without_a_call(url):
    calls = []
    out = _detail.hydrate(_postings(1), SPEC, detail_url=lambda p: url,
                          fetch_doc=lambda u: calls.append(u) or {"res": {"body": "x"}})
    assert calls == [], "an unsafe detail target must never be requested"
    assert len(out) == 1 and out[0]["description"] == ""


# --- the plain-HTTP transport --------------------------------------------

def test_http_doc_returns_json_by_default():
    sess = FakeSession(payload={"res": {"body": "jd"}})
    assert _detail.http_doc(sess, timeout=5)("https://example.com/d/1") == {"res": {"body": "jd"}}


def test_http_doc_returns_a_soup_node_in_html_mode():
    sess = FakeSession(text="<div class='jd'>hello</div>")
    doc = _detail.http_doc(sess, timeout=5, html=True)("https://example.com/d/1")
    assert doc.select_one(".jd").get_text() == "hello"


def test_http_doc_propagates_a_bad_status():
    sess = FakeSession(responses=[FakeResponse(raise_exc=RuntimeError("404"))])
    with pytest.raises(RuntimeError):
        _detail.http_doc(sess, timeout=5)("https://example.com/d/1")
