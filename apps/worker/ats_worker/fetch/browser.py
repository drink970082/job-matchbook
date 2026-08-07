"""Browser recipe executor — the isolated phase-4 fallback.

For boards plain HTTP can't fetch (Cloudflare-blocked) or can't cleanly parse
(fragile shape). Recipe-driven like `custom`, but the transport is a headless
Playwright Chromium and extraction reads the RENDERED DOM via CSS selectors.

Walled off so the pure-`requests` core never touches Chromium: Playwright is
lazy-imported INSIDE fetch() and ships as an optional extra
(requirements-browser.txt); importing this module needs only bs4. Detail merging
belongs to the shared stage (`_detail.py`) — which also means a board Chromium must
only ENUMERATE can hydrate over plain `requests` via an `http-html`/`http-json`
detail mode, instead of paying a render per posting. The pure `parse_jobs` is
unit-tested against saved HTML fixtures; the
`fetch` glue's SSRF guards (detail + pagination URLs) are exercised via a fake
`sync_playwright` (test_browser.py) with no real Chromium, but the live browser
I/O itself is not (same as other adapters' network I/O). The executor is also
gated off the default cycle in run.py (enable_browser_sources).
"""
from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from ats_worker.fetch import _detail
from ats_worker.fetch._recipe import apply_css_fields
from ats_worker.util import BROWSER_UA, is_safe_public_url

SOURCE = "browser"

_INSTALL_HINT = (
    "source 'browser' needs Playwright: "
    "pip install -r requirements-browser.txt && playwright install chromium"
)

# A realistic UA + headed-looking context + the automation-flag off lets Cloudflare's
# "Just a moment" JS interstitial auto-clear; the default headless-shell fingerprint
# gets stuck on it (0 cards) and leaks "HeadlessChrome". Shared with the `custom`
# executor's default header — see util.BROWSER_UA on why the version is not bumped.
_UA = BROWSER_UA


def _block_unsafe_navigation(route):
    """Playwright route handler: abort any request to a non-public host.
    Registered on every page and guards each request's OWN url — the initial
    nav/pagination/detail URL, and any subresource (img/css/xhr) the rendered
    page issues. It does NOT stop a navigation's redirect target: per the
    Playwright docs, the route handler fires only for a navigation's initial
    URL, so a 3xx Location is followed by Chromium without re-invoking this
    handler. Closing that gap is `render()`'s post-goto `page.url` check
    below, not this interceptor."""
    if is_safe_public_url(route.request.url):
        route.continue_()
    else:
        route.abort()


def parse_jobs(pages: list[str], recipe: dict, company_name: str) -> list[dict]:
    """Parse rendered listing-page HTML into postings (pure; no browser).
    De-dups by external_id across pages."""
    item_sel = recipe.get("item")
    if not item_sel:
        raise ValueError("browser recipe requires an `item` CSS selector")
    fields = recipe.get("fields") or {}
    base = recipe.get("url", "")
    out: list[dict] = []
    seen: set[str] = set()
    for html in pages:
        for node in BeautifulSoup(html or "", "html.parser").select(item_sel):
            posting = apply_css_fields(node, fields, company_name, SOURCE, base_url=base)
            if not posting["external_id"] or posting["external_id"] in seen:
                continue  # no id can't dedup; a repeated id means we looped
            seen.add(posting["external_id"])
            out.append(posting)
    return out


def _stealth_context(sync_playwright):
    """The playwright context manager, stealth-patched when the optional extra is
    installed.

    **Placement is the whole fix.** `Stealth().use_sync(sync_playwright())` patches at
    context creation and clears Citadel's Cloudflare wall — 3/3 detail pages at
    3.4-5.4k chars, with the SSRF route guard still installed. The obvious per-page form,
    `Stealth().apply_stealth_sync(page)`, silently under-patches and does NOT: six
    measured arms failed on it (with and without the route guard, with and without a UA
    override, with crawl4ai's full launch-flag set, with a 14s fixed dwell). crawl4ai's
    `enable_stealth=True` is this same library and nothing else, so it buys nothing a
    208 KB dependency does not.

    Absent, the un-patched context is returned: the extra stays optional and the core
    install, CI, and the no-network test gate stay Chromium-free.
    """
    try:
        from playwright_stealth import Stealth
    except ImportError:       # pragma: no cover - env-dependent, like playwright itself
        return sync_playwright()
    return Stealth().use_sync(sync_playwright())


def fetch(slug: str, company_name: str, recipe: dict,
          session=None, timeout: int = 30, keep=None) -> list[dict]:
    """Render the board in headless Chromium, paginate, optionally enrich each posting
    from its detail page.

    `session` is used ONLY by an `http-html`/`http-json` detail mode (a board Chromium
    must enumerate but whose job pages are server-rendered); the listing render never
    touches it. `keep` is the stub-gate predicate — see `phenom.fetch`."""
    if not is_safe_public_url(recipe.get("url")):
        raise ValueError(f"browser recipe url is not a safe public http(s) URL: {recipe.get('url')!r}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(_INSTALL_HINT) from exc

    page_cfg = recipe.get("page") or {"type": "none"}
    ptype = page_cfg.get("type", "none")
    detail = recipe.get("detail") or {}
    url_field = detail.get("url_field")

    item_sel = recipe.get("item")
    detail_desc = (detail.get("fields") or {}).get("description")
    detail_wait = detail_desc if isinstance(detail_desc, str) else None

    with _stealth_context(sync_playwright) as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_context(
            user_agent=_UA, viewport={"width": 1920, "height": 1080}).new_page()
        page.route("**/*", _block_unsafe_navigation)

        def render(url: str, wait_sel: str | None = None) -> str:
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            if not is_safe_public_url(page.url):
                # Redirect backstop for navigations: page.route fires only for a
                # nav's INITIAL url (Playwright follows a 3xx without re-invoking
                # the handler — see _block_unsafe_navigation's docstring), so a
                # public href that redirects to an internal host would otherwise
                # be scraped. Discard the response so an internal target's body
                # never reaches a posting's description. (Residual: the single
                # read-only redirect GET still fires before we discard here —
                # accepted; browser sources are gated off by default.)
                return ""
            # A Cloudflare "Just a moment" JS challenge auto-clears in a few seconds;
            # wait for the expected element rather than a fixed sleep (a fixed 3s left
            # 0 cards). Fall through on timeout so a genuinely empty page still returns
            # whatever rendered. The clearance cookie persists, so later same-domain
            # renders (pages, details) don't re-challenge.
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=15000)
                except Exception:  # noqa: BLE001 — empty/other page: return as-is
                    pass
            page.wait_for_timeout(500)
            return page.content()

        postings = parse_jobs([render(recipe["url"], item_sel)], recipe, company_name)
        seen = {p["external_id"] for p in postings}
        if ptype == "url":
            template, n = page_cfg["template"], page_cfg.get("start", 2)
            while True:
                page_url = template.format(n=n)
                if not is_safe_public_url(page_url):
                    # Operator-authored pagination template produced an unsafe URL —
                    # fail loudly like an unsafe recipe.url (pipeline logs + skips the
                    # board), not a silent break that would return page-1 as success
                    # and permanently drop pages 2+ on a broken template.
                    raise ValueError(
                        f"browser recipe pagination url is not a safe public http(s) URL: {page_url!r}")
                fresh = [p for p in parse_jobs([render(page_url, item_sel)],
                                               recipe, company_name)
                         if p["external_id"] not in seen]
                if not fresh:
                    break  # empty page or all-seen -> past the end
                seen.update(p["external_id"] for p in fresh)
                postings.extend(fresh)
                n += 1
        elif ptype != "none":
            raise ValueError(f"browser recipe: unsupported page type {ptype!r}")

        # Hydration through the shared stage, which owns the board-level breaker, the
        # stub gate and the SSRF re-check. A bot wall clears once for the listing but
        # re-challenges deep-link navigations, so a walled board's detail renders come
        # back description-less and the breaker ends them rather than burning a ~15s
        # render on every posting; `_stealth_context` is what stops the re-challenge.
        #
        # **The detail transport need not be the browser.** Plenty of boards need
        # Chromium only to ENUMERATE — the listing is a JS app but each job page is
        # server-rendered — and for those an `http-html`/`http-json` detail mode hydrates
        # over plain `requests`, turning one Chromium render per posting into one cheap
        # GET. Google is the case in point: 817 rows, SSR'd detail pages.
        if url_field:
            mode = detail.get("mode")
            if mode in ("http-html", "http-json"):
                fetch_doc = _detail.http_doc(session or requests, timeout=timeout,
                                             html=mode == "http-html")
            else:
                def fetch_doc(url):
                    return BeautifulSoup(render(url, detail_wait), "html.parser")
            postings = _detail.hydrate(
                postings, detail, keep=keep, label=f"{SOURCE}/{slug}",
                detail_url=lambda p: p.get(url_field), fetch_doc=fetch_doc)
        browser.close()
    return postings
