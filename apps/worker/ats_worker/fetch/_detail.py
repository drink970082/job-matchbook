"""Shared detail-hydration stage for board adapters and recipe executors.

Sibling of `_paged.py` and the same kind of thing: the skeleton lives here, the parts
that differ per board are injected. Many boards' LIST call carries only a teaser (or
nothing at all) — the full JD needs one more request per posting.

Two properties this exists to enforce, both learned the expensive way:

**The detail transport is independent of the list transport.** A board can need a
headless browser to enumerate and plain HTTP to hydrate, so the caller supplies
`fetch_doc` and this module never assumes which one it got. Coupling them costs a
Chromium render per posting on a board whose detail pages are server-rendered.

**The circuit breaker is per BOARD, not per posting.** A bot wall or a dead detail
endpoint fails identically for every posting, so `breaker` consecutive failures stop
the board rather than burning a request each. `PRINCIPLES.md` names a per-position
budget for a board-wide failure as exactly the wrong shape.

`fetch_doc` returns a parsed document and its TYPE selects the extractor: a `dict` is
read with dotted paths (`_recipe`'s JSON side), anything else is treated as a bs4 node
and read with CSS selectors (`_recipe`'s DOM side). Neither extractor is reimplemented
here — this module only routes between them.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ats_worker.fetch._recipe import _css_description, _css_one, _description, dotted_get
from ats_worker.util import get_redirect_safe, is_safe_public_url

# Consecutive detail failures that stop a board. 3 is what browser.py used per-posting
# before this module took the job over; kept, now that it means what it says.
DEFAULT_BREAKER = 3


def http_doc(http, *, timeout: int, headers: dict | None = None, html: bool = False):
    """`fetch_doc` for a detail page reachable over plain HTTP — the transport both
    `custom` (JSON detail APIs) and `icims` (server-rendered detail pages) use.

    `get_redirect_safe` re-validates every redirect hop, so a detail URL that 302s
    into an internal target is refused mid-fetch and not merely at the caller's
    `is_safe_public_url` check.
    """
    def _fetch(url):
        resp = get_redirect_safe(http, url, method="get", timeout=timeout,
                                 headers=headers or None)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser") if html else resp.json()
    return _fetch


def _extract(doc, spec):
    """One detail field out of a parsed document. `doc` being a dict selects the
    dotted-path reader, anything else the CSS reader — the same split `_recipe`
    already draws between the `custom` and `browser` field models."""
    if isinstance(doc, dict):
        return dotted_get(doc, spec) if isinstance(spec, str) else None
    return _css_one(doc, spec)


def _extract_description(doc, spec) -> str:
    """`description` is special-cased because both readers already flatten HTML to
    text for it, and a list-of-paths concatenation is JSON-side only."""
    if isinstance(doc, dict):
        return _description(doc, spec)
    return _css_description(doc, spec)


def apply_detail(posting: dict, doc, spec: dict) -> dict:
    """Merge a parsed detail document's fields into `posting` (pure; no I/O).

    Only non-empty values overwrite, so a detail page that renders a blank section
    cannot erase what the list call already gave us.
    """
    fields = (spec or {}).get("fields") or {}
    for name, field_spec in fields.items():
        value = (_extract_description(doc, field_spec) if name == "description"
                 else _extract(doc, field_spec))
        if value:
            posting[name] = value
    return posting


def hydrate(postings, spec: dict, *, detail_url, fetch_doc,
            keep=None, breaker: int = DEFAULT_BREAKER, label: str = ""):
    """Hydrate `postings` from their detail documents. Returns the kept postings.

    `detail_url(posting) -> str | None`   where this posting's detail lives. None or a
        non-public URL skips it — the detail href is scraped from third-party listing
        HTML, so it is checked here rather than trusted (SPEC section 11).
    `fetch_doc(url) -> doc | None`        the transport; see the module docstring on how
        the returned type picks the extractor.
    `keep(posting) -> 'drop' | 'discard' | 'hydrate'`  the same stub-gate contract the
        two-step adapters use (see `phenom.fetch`): 'drop' omits the posting entirely,
        'discard' keeps it un-hydrated so the caller can still record it, 'hydrate' is
        the normal path. Any other value hydrates — a broken predicate must cost
        requests, never postings. None disables the gate.

    A posting whose detail fetch raises is kept as-is (the list call already gave us
    title/location/url); only the description is lost. `breaker` consecutive such
    failures end the board, and say so.
    """
    if not (spec or {}).get("fields"):
        return list(postings)

    out, failures = [], 0
    for posting in postings:
        if keep is not None:
            verdict = keep(posting)
            if verdict == "drop":
                continue          # never stored, no detail call
            if verdict == "discard":
                out.append(posting)
                continue          # stored un-hydrated, no detail call
        out.append(posting)
        if failures >= breaker:
            continue              # board is broken; keep the rest un-hydrated, no calls

        url = detail_url(posting)
        if not url or not is_safe_public_url(url):
            continue              # missing or unsafe: keep the posting description-less
        try:
            doc = fetch_doc(url)
        except Exception:         # noqa: BLE001 — one bad detail must not lose the board
            doc = None
        before = len(posting.get("description") or "")
        if doc is not None:
            apply_detail(posting, doc, spec)
        # "Did this call earn us more description?" is the honest health signal, and the
        # only one that catches a bot wall: a Cloudflare interstitial is a HTTP 200 with
        # a parseable body, so counting transport errors alone would never trip.
        failures = 0 if len(posting.get("description") or "") > before else failures + 1
        if failures == breaker:
            print(f"[fetch] {label or 'detail'}: {breaker} consecutive detail failures — "
                  f"hydration STOPPED for this board; remaining postings keep their "
                  f"list-call description")
    return out
