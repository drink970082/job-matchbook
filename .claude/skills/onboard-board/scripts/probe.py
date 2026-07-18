#!/usr/bin/env python3
"""Probe a careers URL and classify it for the ATS board-onboarding cascade.

This is a *scout*, not a decision. It narrows the search — the agent/human confirms
the real endpoint and writes the recipe. It reports which cascade rung fits:

  platform    -> a known ATS adapter (greenhouse, lever, ashby, workday, pinpoint,
                 smartrecruiters, workable, icims, phenom) — onboarding = a data row, no recipe
  plain-http  -> a `custom` recipe: a JSON/XHR endpoint, __NEXT_DATA__, or json-ld on the page
  browser     -> a `browser` recipe: the page bot-walls plain HTTP (403 challenge) or renders
                 its jobs only client-side with no discoverable JSON

Usage:
  python probe.py <careers-url>

Design note: it recognizes an ATS only from the URL structure or an embedded link in the
page, then VERIFIES the board is non-empty — it deliberately does NOT guess a slug from
generic domain/path words, because shared ATS APIs host squatted accounts for common words
("careers", "search", "amazon" with 0 jobs), which would misclassify. Prints a `VERDICT:` line.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    sys.exit("probe.py needs `requests` (pip install -r apps/worker/requirements.txt)")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/137.0 Safari/537.36"}
TIMEOUT = 15


def get(url, **kw):
    try:
        return requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
    except requests.RequestException:
        return None


# ATS host patterns -> (name, slug). Matched against the URL AND the page HTML (embeds).
# The slug comes from the URL structure, never a guess; workday needs its 3-part slug so we
# only surface the host for a human to complete.
ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_.-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)")),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_.-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_.-]+)")),
    ("icims", re.compile(r"([a-z0-9-]+)\.icims\.com")),
    ("pinpoint", re.compile(r"([a-z0-9-]+)\.pinpointhq\.com")),
    ("workday", re.compile(r"([a-z0-9-]+)\.[a-z0-9]+\.myworkdayjobs\.com")),
    ("phenom", re.compile(r"/api/pcsx/")),
]


def recognize(text: str) -> list[tuple[str, str]]:
    """ATS (name, slug) pairs found in a URL or page HTML. Deduped, order-preserving."""
    out, seen = [], set()
    for name, pat in ATS_PATTERNS:
        m = pat.search(text or "")
        if not m:
            continue
        slug = m.group(1) if m.groups() else ""
        key = (name, slug)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def verify(name: str, slug: str) -> int | None:
    """Confirm a recognized ATS points to a NON-EMPTY board. Returns the posting count,
    0 if empty/unknown, or None if the count can't be checked here (workday/phenom)."""
    api = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=5",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    }
    if name in api:
        r = get(api[name])
        if r is None or r.status_code != 200:
            return 0
        try:
            data = r.json()
        except ValueError:
            return 0
        if name == "lever":
            return len(data) if isinstance(data, list) else 0
        if name == "smartrecruiters":
            return int(data.get("totalFound", 0)) or len(data.get("content", []))
        return len(data.get("jobs", []))
    if name == "icims":
        r = get(f"https://{slug}.icims.com/jobs/search?in_iframe=1&pr=0")
        return r.text.count("iCIMS_JobCardItem") if (r and r.status_code == 200) else 0
    if name == "pinpoint":
        r = get(f"https://{slug}.pinpointhq.com/postings.json")
        try:
            return len(r.json().get("data", [])) if (r and r.status_code == 200) else 0
        except ValueError:
            return 0
    return None  # workday (needs tenant/dc/site) / phenom (host/domain) — can't count here


def plain_http_signals(html: str) -> list[str]:
    signals = []
    if re.search(r'<script[^>]*id="__NEXT_DATA__"', html or ""):
        signals.append("__NEXT_DATA__ (Next.js data blob — parse it as `next-data` mode)")
    if re.search(r'"@type"\s*:\s*"JobPosting"', html or ""):
        signals.append("json-ld JobPosting (schema.org — a `json-ld` recipe target)")
    for hint in ("admin-ajax.php", "/wp-json/", "graphql", "search.json", "/pcsx/"):
        if hint in (html or ""):
            signals.append(f"inline API hint: {hint!r} (candidate XHR/JSON endpoint)")
    return signals


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = sys.argv[1] if "//" in sys.argv[1] else "https://" + sys.argv[1]
    print(f"# probe {url}")

    def verified(pairs):
        out = []
        for name, slug in pairs:
            n = verify(name, slug)
            if n is None:              # workday/phenom: surface, human completes the slug
                out.append((name, slug, "?"))
            elif n > 0:
                out.append((name, slug, n))
        return out

    # 1. platform from the URL itself (highest confidence)
    plat = verified(recognize(url))

    # 2. fetch the page: status -> bot wall; body -> embedded ATS + plain-HTTP signals
    print("\n## page fetch")
    r = get(url)
    status = r.status_code if r is not None else "ERR"
    print(f"  GET {url} -> {status}")
    bot_walled = r is not None and r.status_code in (403, 429) and \
        bool(re.search(r"just a moment|challenge|cf-|captcha|verify you are human", r.text, re.I))
    signals, embeds = [], []
    if r is not None and r.status_code == 200:
        embeds = verified([p for p in recognize(r.text) if p not in {(n, s) for n, s, _ in plat}])
        signals = plain_http_signals(r.text)
    plat += embeds

    print("\n## platform check")
    if plat:
        for name, slug, n in plat:
            print(f"  HIT  {name}  slug={slug}  ({n} live postings)")
    else:
        print("  no known ATS recognized in the URL or embedded in the page")
    if bot_walled:
        print("\n  !! bot wall (Cloudflare/challenge) — plain HTTP is blocked")
    print("\n## plain-HTTP signals")
    print("  " + ("\n  ".join(signals) if signals else "none in static HTML (jobs may load via XHR)"))

    # verdict — earliest cascade rung that fits
    print()
    if plat:
        name, slug, n = plat[0]
        note = "verify tenant/host slug, then " if n == "?" else ""
        print(f"VERDICT: platform={name} slug={slug} -> {note}data row, NO recipe needed")
    elif bot_walled:
        print("VERDICT: browser -> plain HTTP is blocked; write a `browser` recipe (render + CSS)")
    elif signals:
        print("VERDICT: plain-http -> write a `custom` recipe; start from the signal(s) above")
    elif r is None or status != 200:
        print("VERDICT: browser -> page not fetchable by plain HTTP; try a `browser` recipe")
    else:
        print("VERDICT: plain-http? -> page fetched but jobs aren't in the static HTML. Find the "
              "XHR that returns them (browser DevTools > Network, filter Fetch/XHR) and write a "
              "`custom` recipe; if there's no JSON endpoint, fall back to a `browser` recipe.")


if __name__ == "__main__":
    main()
