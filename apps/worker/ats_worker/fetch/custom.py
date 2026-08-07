"""Generic `custom` executor — runs a declarative recipe over plain HTTP.

One executor, one recipe per board (stored as a data row), no per-site code. Two
modes: `json` (the response IS JSON) and `next-data` (extract the `__NEXT_DATA__`
`<script>` JSON out of an HTML response, then behave as `json`). Pagination is
`offset` (advance by rows), `page` (advance a page number), or `none`.

Anything a recipe can't express is a `browser` recipe (fetch/browser.py), never a
hand-written adapter — see the board-scraper-expansion design §4.2.
"""
from __future__ import annotations

import json

import requests
from bs4 import BeautifulSoup

from ats_worker.fetch import _detail
from ats_worker.fetch._recipe import apply_fields, dotted_get, interpolate
from ats_worker.util import get_redirect_safe, is_safe_public_url

SOURCE = "custom"


def _extract_next_data(html: str) -> dict:
    tag = BeautifulSoup(html or "", "html.parser").find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        raise ValueError("custom next-data recipe: no <script id=__NEXT_DATA__> found")
    return json.loads(tag.string)


def _payload(resp, mode: str):
    if mode == "next-data":
        return _extract_next_data(resp.text)
    return resp.json()


def raw_items(payload, recipe: dict) -> list:
    """The raw job objects on one page. Split out of `parse_jobs` because `fetch` needs
    them too: a `detail:` URL template interpolates against the RAW item, not the
    canonical posting, since the id a detail endpoint wants is often not the one the
    recipe maps to `external_id` (Apple's detail API keys on `positionId` while
    `external_id` is `id`, and re-pointing `external_id` would re-key every stored row).
    """
    ip = recipe.get("item_path")
    # No item_path + the payload IS the array -> root-level array board (e.g. a bare
    # JSON feed). Otherwise walk item_path into the payload.
    items = payload if (not ip and isinstance(payload, list)) else (dotted_get(payload, ip) or [])
    if not isinstance(items, list):
        raise ValueError(f"custom recipe item_path {recipe.get('item_path')!r} is not a list")
    return items


def parse_jobs(payload, recipe: dict, company_name: str) -> list[dict]:
    """Map one page's payload to canonical postings (pure; no I/O). 1:1 with
    `raw_items(payload, recipe)` and in the same order — `fetch` pairs them by index."""
    fields = recipe.get("fields") or {}
    return [apply_fields(item, fields, company_name, SOURCE)
            for item in raw_items(payload, recipe)]


def _request(http, method: str, url: str, params, body, headers, timeout):
    # get_redirect_safe re-validates every redirect hop (see util.py) so a
    # recipe.url that 302s into an internal target is refused mid-fetch, not
    # just at the initial is_safe_public_url check below.
    if method == "POST":
        return get_redirect_safe(http, url, method="post", timeout=timeout,
                                 params=params or None, json=body or None,
                                 headers=headers or None)
    return get_redirect_safe(http, url, method="get", timeout=timeout,
                             params=params or None, headers=headers or None)


def _page_request(recipe: dict, page: dict, n: int):
    """Build the (params, body) for page index/offset `n` from the recipe."""
    params: dict = {}
    body = dict(recipe.get("body") or {})
    if page.get("param"):
        params[page["param"]] = n
    elif page.get("body_param"):
        body[page["body_param"]] = n
    if page.get("size_param") and page.get("size") is not None:
        params[page["size_param"]] = page["size"]
    return params, body


def fetch(slug: str, company_name: str, recipe: dict,
          session: requests.Session | None = None, timeout: int = 20,
          keep=None) -> list[dict]:
    if not is_safe_public_url(recipe.get("url")):
        raise ValueError(f"custom recipe url is not a safe public http(s) URL: {recipe.get('url')!r}")
    http = session or requests
    method = (recipe.get("method") or "GET").upper()
    mode = recipe.get("mode") or "json"
    headers = recipe.get("headers")
    page = recipe.get("page") or {"type": "none"}
    ptype = page.get("type", "none")

    out: list[dict] = []
    raws: list = []          # 1:1 with `out`; only used to interpolate a detail URL
    seen: set[str] = set()
    n = 0  # offset (rows) for `offset`, page number for `page`
    while True:
        params, body = _page_request(recipe, page, n)
        resp = _request(http, method, recipe["url"], params, body, headers, timeout)
        resp.raise_for_status()
        payload = _payload(resp, mode)
        postings = parse_jobs(payload, recipe, company_name)

        fresh = 0
        for p, raw in zip(postings, raw_items(payload, recipe)):
            if not p["external_id"] or p["external_id"] in seen:
                continue  # empty id can't dedup; a repeated id means we looped
            seen.add(p["external_id"])
            out.append(p)
            raws.append(raw)
            fresh += 1

        if ptype == "none" or not postings or fresh == 0:
            break
        # Advance, then stop once an honest total (if any) is reached.
        n += len(postings) if ptype == "offset" else 1
        total = dotted_get(payload, recipe.get("total_path")) if recipe.get("total_path") else None
        if isinstance(total, int) and ptype == "offset" and n >= total:
            break

    detail = recipe.get("detail") or {}
    if not detail.get("fields"):
        return out
    # A board whose LIST call carries only a teaser (or nothing) hydrates from one
    # detail document per posting. `mode` lives on this block, not on the recipe, so a
    # board can list as JSON and hydrate from HTML (or the reverse) — the transports
    # are independent by design (see _detail.py).
    raw_of = {p["external_id"]: raw for p, raw in zip(out, raws)}

    def _detail_url(posting):
        template = detail.get("url")
        if template:
            return interpolate(template, raw_of.get(posting["external_id"]) or {})
        field = detail.get("url_field")
        return posting.get(field) if field else None

    return _detail.hydrate(
        out, detail, keep=keep, label=f"{SOURCE}/{slug}",
        detail_url=_detail_url,
        fetch_doc=_detail.http_doc(http, timeout=timeout,
                                   headers=detail.get("headers") or headers,
                                   html=detail.get("mode") == "http-html"))
