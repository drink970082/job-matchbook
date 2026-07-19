"""Embedded-greenhouse enriching resolver — feed-only.

Some companies host their greenhouse jobs on their OWN careers domain with an
`?gh_jid=<id>` apply URL. The greenhouse board token (the slug the boards API is
keyed on) is NOT in that URL — but when the company embeds greenhouse *server-side*
the token appears in the page HTML, in the embed script:

    <div id="grnhse_app"></div>
    <script src="https://boards.greenhouse.io/embed/job_board/js?for=<token>"></script>

So we fetch the page, scrape `for=<token>`, and return `("greenhouse", token,
gh_jid)`. The EXISTING greenhouse list adapter then ingests it unchanged — source
stays `"greenhouse"` and `external_id` = the gh_jid, so it dedups with a directly
resolved greenhouse job.

This does I/O, so it deliberately lives OUTSIDE the pure `resolve.resolve_url`;
`pipeline.run_feed` calls it as a fallback when `resolve_url` returns None and
`classify_reason` is `embedded_greenhouse`. It only recovers the subset that embeds
the token server-side — sites that inject greenhouse via client-side JS leave no
token in the static HTML, so they return None and stay on the unresolved board.

HTTP is injected (like the board adapters) so tests run with no network.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

import requests

from ats_worker.util import is_safe_public_url

# The greenhouse board token is the `for=` query param on the embed script URL.
# Anchor to the greenhouse embed path so a stray `<label for="…">` can't match.
_TOKEN_RE = re.compile(
    r'greenhouse\.io/embed/job_board(?:/js)?\?[^"\'<>]*?\bfor=([A-Za-z0-9_]+)',
    re.IGNORECASE,
)


def _gh_jid(url: str) -> str | None:
    """The `gh_jid` query value (the greenhouse job id), or None."""
    try:
        vals = parse_qs(urlparse(url).query or "").get("gh_jid") or []
    except ValueError:
        return None
    return vals[0] if vals and vals[0] else None


def resolve_embedded(url: str, session: requests.Session | None = None,
                     timeout: int = 20) -> tuple[str, str, str] | None:
    """Return ("greenhouse", token, gh_jid) for an embedded-greenhouse URL, else None.

    None means "not recoverable from the static HTML" (no gh_jid, or the token is
    JS-injected) — the caller records it as unresolved, exactly as today.
    """
    jid = _gh_jid(url)
    if not jid:
        return None  # nothing to resolve — don't even fetch
    if not is_safe_public_url(url):
        return None  # SSRF guard: never fetch an internal/loopback/non-http(s) target
    http = session or requests
    resp = http.get(url, timeout=timeout)
    resp.raise_for_status()
    m = _TOKEN_RE.search(resp.text or "")
    if not m:
        return None
    return ("greenhouse", m.group(1), jid)
