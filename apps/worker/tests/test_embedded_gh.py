"""TDD for feed.embedded_gh — the embedded-greenhouse enriching resolver.

Fixtures are real-derived snippets of company careers pages: the steelpoint one
embeds greenhouse server-side (token in the HTML); the no-token one mimics a site
that injects greenhouse via JS (only the `grnhse_app` placeholder, token absent).
No network — the page fetch is a FakeSession.
"""
from __future__ import annotations

from ats_worker.feed import embedded_gh
from tests._helpers import FakeSession

# Real embed markup from a steelpoint-llc.com careers page.
_WITH_TOKEN = (
    "<p>Apply below.</p><div id=\"grnhse_app\"></div> "
    "<script src=\"https://boards.greenhouse.io/embed/job_board/js?"
    "for=steelpointsolutions\"></script>"
)
# Token injected client-side: only the placeholder, plus a decoy `for=` that must
# NOT be mistaken for the board token.
_NO_TOKEN = "<label for=\"email\">Email</label><div id=\"grnhse_app\"></div>"


def test_resolves_embedded_token_to_greenhouse():
    sess = FakeSession(text=_WITH_TOKEN)
    got = embedded_gh.resolve_embedded(
        "https://steelpoint-llc.com/careers/?gh_jid=7453484003", session=sess)
    assert got == ("greenhouse", "steelpointsolutions", "7453484003")
    assert [c[0] for c in sess.calls] == ["GET"]  # fetched the page once


def test_no_static_token_returns_none():
    # JS-injected embed (and a `<label for=>` decoy) → not recoverable.
    sess = FakeSession(text=_NO_TOKEN)
    assert embedded_gh.resolve_embedded(
        "https://nuro.ai/careersitem?gh_jid=7351066", session=sess) is None


def test_missing_gh_jid_returns_none_without_fetching():
    sess = FakeSession(text=_WITH_TOKEN)
    assert embedded_gh.resolve_embedded(
        "https://x.com/careers", session=sess) is None
    assert sess.calls == []  # no fetch when there's nothing to resolve
