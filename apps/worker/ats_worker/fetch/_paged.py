"""Shared paged-list -> per-item-detail skeleton for board adapters.

workday/smartrecruiters/phenom all drive a paged list endpoint into per-item
detail fetches to build canonical postings; they differ only in list verb,
total key, and detail-failure policy — which the caller supplies via
`fetch_page`/`build_row`.
"""
from __future__ import annotations

from typing import Callable

import requests


def paged_details(
    session,
    *,
    fetch_page: Callable,
    build_row: Callable,
) -> list[dict]:
    """Drive a paged list endpoint -> per-item detail into canonical postings.

    Owns http = session or requests, the page loop, the empty-id skip, len-based
    offset advance, and termination on an empty page OR a reached honest total.
    `fetch_page(http, offset) -> (items, total|None)`; `build_row(http, item) ->
    posting dict | None` (None or empty external_id is skipped).
    """
    http = session or requests
    out: list[dict] = []
    offset = 0
    while True:
        items, total = fetch_page(http, offset)
        for item in items:
            row = build_row(http, item)
            if row and row["external_id"]:
                out.append(row)
        offset += len(items)
        if not items or (isinstance(total, int) and offset >= total):
            break
    return out
