"""SimplifyJobs discovery-feed adapter.

Fetches the community-maintained `listings.json` (a public GitHub data file, NOT
a scraped job board) and returns its raw listing dicts. Each listing carries
company + apply `url` + structured metadata (`active`, `category`, `sponsorship`,
…) but NO job-description text — that comes later from the board adapter the URL
resolves to (see feed/resolve.py).

HTTP is injected (like the board adapters) so tests run with no network.
"""
from __future__ import annotations

import requests

# The data file behind the SimplifyJobs/New-Grad-Positions README table.
DEFAULT_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions"
    "/dev/.github/scripts/listings.json"
)


def fetch(url: str = DEFAULT_URL, session: requests.Session | None = None,
          timeout: int = 30) -> list[dict]:
    """Return the raw feed listings (a JSON array). Prefilter/resolve read the
    individual fields downstream, so no per-listing transformation here."""
    http = session or requests
    resp = http.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []
