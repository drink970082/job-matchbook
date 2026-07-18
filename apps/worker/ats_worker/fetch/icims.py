"""iCIMS careers-board adapter (server-rendered HTML, plain HTTP).

iCIMS renders its job list inside an iframe, but the same URL returns server HTML
rows to plain `requests`. The config `slug` is the careers subdomain, e.g.
"careers-sig" for https://careers-sig.icims.com. Paginate `pr` (0-based page
index) until a page yields no new job cards.

  list: GET https://{slug}.icims.com/jobs/search?in_iframe=1&pr={page}
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from ats_worker.util import html_to_text

SOURCE = "icims"
SEARCH = "https://{slug}.icims.com/jobs/search"
_ID_RE = re.compile(r"/jobs/(\d+)/")


def parse_jobs(html: str, company_name: str) -> list[dict]:
    """Parse the job cards from one iCIMS search page. Empty list = no cards."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    for card in soup.select("li.iCIMS_JobCardItem"):
        a = card.select_one("div.title a")
        if a is None or not a.get("href"):
            continue
        href = a["href"].split("?", 1)[0]  # drop the ?in_iframe=1 query
        m = _ID_RE.search(href)
        if not m:
            continue  # a card with no numeric job id can't dedup — skip it
        title_el = a.select_one("h3")
        title = (title_el.get_text() if title_el else a.get_text()).strip()
        desc_el = card.select_one("div.description")
        out.append({
            "source": SOURCE,
            "external_id": m.group(1),
            "company_name": company_name,
            "job_title": title,
            "location": _location(card),
            "job_url": href,
            "description": html_to_text(str(desc_el)) if desc_el else "",
            "posted_at": None,  # the iCIMS list carries no post date
        })
    return out


def _location(card) -> str | None:
    """Some iCIMS boards carry a 'Location' header field; many (e.g. SIG) don't.
    Return the first Location-labeled value, else None."""
    for tag in card.select("div.iCIMS_JobHeaderTag"):
        label = tag.select_one("dt.iCIMS_JobHeaderField")
        if label and "location" in label.get_text(strip=True).lower():
            data = tag.select_one("dd.iCIMS_JobHeaderData")
            if data:
                return data.get_text(strip=True) or None
    return None


def fetch(slug: str, company_name: str, session: requests.Session | None = None,
          timeout: int = 20) -> list[dict]:
    http = session or requests
    out: list[dict] = []
    seen: set[str] = set()
    page = 0
    while True:
        resp = http.get(
            SEARCH.format(slug=slug),
            params={"in_iframe": 1, "pr": page},
            timeout=timeout,
        )
        resp.raise_for_status()
        # Stop on the first page with no NEW ids: covers both an empty page and a
        # board that clamps `pr` and repeats the last page (would loop forever).
        fresh = [j for j in parse_jobs(resp.text, company_name)
                 if j["external_id"] not in seen]
        if not fresh:
            break
        seen.update(j["external_id"] for j in fresh)
        out.extend(fresh)
        page += 1
    return out
