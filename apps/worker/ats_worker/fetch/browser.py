"""Browser recipe executor — the isolated phase-4 fallback.

For boards plain HTTP can't fetch (Cloudflare-blocked) or can't cleanly parse
(fragile shape). Recipe-driven like `custom`, but the transport is a headless
Playwright Chromium and extraction reads the RENDERED DOM via CSS selectors.

Walled off so the pure-`requests` core never touches Chromium: Playwright is
lazy-imported INSIDE fetch() and ships as an optional extra
(requirements-browser.txt); importing this module needs only bs4. The pure
`parse_jobs` / `apply_detail` are unit-tested against saved HTML fixtures; the
browser-driving `fetch` glue is not (same as other adapters' network I/O). The
executor is also gated off the default cycle in run.py (enable_browser_sources).
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from ats_worker.fetch._recipe import _css_description, apply_css_fields

SOURCE = "browser"

_INSTALL_HINT = (
    "source 'browser' needs Playwright: "
    "pip install -r requirements-browser.txt && playwright install chromium"
)


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


def apply_detail(posting: dict, detail_html: str, recipe: dict) -> dict:
    """Merge detail-page fields (currently `description`) into a posting (pure)."""
    fields = (recipe.get("detail") or {}).get("fields") or {}
    if "description" in fields:
        node = BeautifulSoup(detail_html or "", "html.parser")
        posting["description"] = _css_description(node, fields["description"])
    return posting


def fetch(slug: str, company_name: str, recipe: dict,
          session=None, timeout: int = 30) -> list[dict]:
    """Render the board in headless Chromium, paginate, optionally enrich each
    posting from its detail page. `session` is ignored (signature parity)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuntimeError(_INSTALL_HINT) from exc

    page_cfg = recipe.get("page") or {"type": "none"}
    ptype = page_cfg.get("type", "none")
    detail = recipe.get("detail") or {}
    url_field = detail.get("url_field")
    enrich = bool(url_field and detail.get("fields"))

    with sync_playwright() as pw:  # pragma: no cover - browser-driving glue
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context().new_page()

        def render(url: str) -> str:
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # let a Cloudflare challenge clear + content render
            return page.content()

        postings = parse_jobs([render(recipe["url"])], recipe, company_name)
        seen = {p["external_id"] for p in postings}
        if ptype == "url":
            template, n = page_cfg["template"], page_cfg.get("start", 2)
            while True:
                fresh = [p for p in parse_jobs([render(template.format(n=n))], recipe, company_name)
                         if p["external_id"] not in seen]
                if not fresh:
                    break  # empty page or all-seen -> past the end
                seen.update(p["external_id"] for p in fresh)
                postings.extend(fresh)
                n += 1
        elif ptype != "none":
            raise ValueError(f"browser recipe: unsupported page type {ptype!r}")

        if enrich:
            # ponytail: one detail render per posting (Citadel first run ~81, ~minutes).
            # Upgrade path if it bites: enrich only unseen external_ids (the pipeline
            # already diffs new by id), so steady-state is a handful/run.
            for p in postings:
                url = p.get(url_field)
                if not url:
                    continue
                try:
                    apply_detail(p, render(url), recipe)
                except Exception:  # noqa: BLE001 — keep the posting, description as-is
                    continue
        browser.close()
    return postings
