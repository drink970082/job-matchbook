#!/usr/bin/env python3
"""Probe a careers URL and classify it for the ATS board-onboarding cascade.

This is a *scout*, not a decision. It narrows the search — the agent/human confirms
the real endpoint and writes the recipe. It reports which cascade rung fits:

  platform    -> a known ATS adapter (greenhouse, lever, ashby, workday, pinpoint,
                 smartrecruiters, workable, icims, phenom) — onboarding = a data row, no recipe
  platform?   -> the URL is a known ATS board whose list is empty or unreadable, or (with no
                 plain-HTTP signal) the page embeds one that could not be read
  plain-http  -> a `custom` recipe: a JSON/XHR endpoint, __NEXT_DATA__, or json-ld on the page
  browser     -> a `browser` recipe: the page bot-walls plain HTTP (403 challenge) or renders
                 its jobs only client-side with no discoverable JSON

Usage:
  python probe.py <careers-url>

Design note: it recognizes an ATS only from the URL structure or an embedded link in the
page (the worker's own feed/resolve.py), then VERIFIES through the worker's adapter that the
board lists a posting — it deliberately does NOT guess a slug from
generic domain/path words, because shared ATS APIs host squatted accounts for common words
("careers", "search", "amazon" with 0 jobs), which would misclassify. Prints a `VERDICT:` line.
"""
from __future__ import annotations

import html
import os
import re
import sys
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../../../../apps/worker")))  # <repo>/apps/worker

try:
    import requests
    from ats_worker.feed.resolve import FIXED_HOSTS, SUBDOMAIN_HOSTS, resolve_board
    from ats_worker.fetch import board_has_listings
    from ats_worker.source_lifecycle import verify_board
except ImportError as exc:
    sys.exit(f"probe.py needs the worker's dependencies (pip install -r apps/worker/requirements.txt): {exc}")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/137.0 Safari/537.36"}
TIMEOUT = 15


def get(url, **kw):
    try:
        return requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
    except requests.RequestException:
        return None


MAX_EMBEDS = 5
# A board host anywhere in a page, whatever surrounds it (a nested or encoded URL, prose), and
# the path and query after it; resolve_board decides what it names. A subdomain board's first
# label starts at a boundary or after a percent escape. Every length is bounded, so a minified
# page scans linearly; the lookahead leaves what follows a host to be scanned too.
_BOARD_HOST = re.compile(
    r"(?:(" + "|".join(map(re.escape, FIXED_HOSTS)) + r")"
    r"|(?:%(?:25){0,3}[0-9a-f]{2}|(?<![a-z0-9_-]))"
    r"((?:[a-z0-9_-]{1,63}\.){1,2}(?:" + "|".join(map(re.escape, SUBDOMAIN_HOSTS)) + r")))"
    r"(?![a-z0-9_-]|\.[a-z0-9])"
    r"(?=((?:(?:/|%(?:25){0,3}2f)[a-z0-9._~%+/-]{0,300})?(?:\?[a-z0-9._~%+/=&\[\]-]{0,300})?))", re.I)
# /, \x2f or \/ in a script.
_SCRIPT_ESCAPED = re.compile(r"\\(?:u00|x)([0-9a-f]{2})", re.I)
# What follows the slug of a URL cut out of text: an escape that is no part of one.
_TAIL = re.compile(r"(?:%(?!(?:2f|20)[a-z0-9])|[~+ ]).*", re.I)
_DECODED = re.compile(r"[a-z0-9._~%+/=&?\[\] -]*", re.I)


def board_hosts(page: str) -> list[tuple[str, str]]:
    """(host, the path and query after it) of each board host in a page."""
    text = _SCRIPT_ESCAPED.sub(lambda m: chr(int(m.group(1), 16)), page or "")
    text = re.sub(r"(?<!\\)\\+/", "/", html.unescape(text))
    out = []
    for m in _BOARD_HOST.finditer(text):
        rest = m.group(3)
        while rest.startswith("%"):  # the host was inside a percent-encoded URL
            rest = unquote(rest)
        rest = _DECODED.match(rest).group().rstrip()  # decoding can end the URL
        out.append(((m.group(1) or m.group(2)).lower(), rest))
    return out


def recognize_url(url: str) -> tuple[str, str] | None:
    """The (source, slug) the worker's own resolver reads from a URL."""
    return resolve_board(url)


def recognize_page(page: str) -> list[tuple[str, str]]:
    """Boards a page links to or embeds, each through the same resolver. Deduped, in page
    order, at most MAX_EMBEDS (each one costs a list request)."""
    urls = [f"https://{host}{rest.rstrip('.')}" for host, rest in board_hosts(page)]
    found = (resolve_board(u) or resolve_board(_TAIL.sub("", u)) for u in urls)
    return list(dict.fromkeys(b for b in found if b))[:MAX_EMBEDS]


def workday_hosts(text: str) -> list[str]:
    """`{tenant}/{dc}` of each Workday host in a URL or page: the slug still needs the site."""
    labels = [host.split(".") for host, _ in board_hosts(text) if host.endswith(".myworkdayjobs.com")]
    return [f"{x[0]}/{x[1]}" for x in labels if len(x) == 4]


def verify(boards, has_listings=board_has_listings):
    """Read each board's list through its adapter, the check an add runs too. Returns
    (the boards that list a posting, [(source, slug, reason)] for the rest)."""
    hits, misses = [], []
    for source, slug in boards:
        reason = verify_board(has_listings, source, slug, slug)
        if reason:
            misses.append((source, slug, reason))
        else:
            hits.append((source, slug))
    return hits, misses


def plain_http_signals(page: str) -> list[str]:
    signals = []
    if re.search(r'<script[^>]*id="__NEXT_DATA__"', page or ""):
        signals.append("__NEXT_DATA__ (Next.js data blob — parse it as `next-data` mode)")
    if re.search(r'"@type"\s*:\s*"JobPosting"', page or ""):
        signals.append("json-ld JobPosting (schema.org — a `json-ld` recipe target)")
    for hint in ("admin-ajax.php", "/wp-json/", "graphql", "search.json", "/pcsx/"):
        if hint in (page or ""):
            signals.append(f"inline API hint: {hint!r} (candidate XHR/JSON endpoint)")
    return signals


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    url = sys.argv[1] if "//" in sys.argv[1] else "https://" + sys.argv[1]
    print(f"# probe {url}")

    # 1. platform from the URL itself (highest confidence)
    own = recognize_url(url) or next(iter(recognize_page(url)), None)  # or one inside a redirect URL
    plat, misses = verify([own] if own else [])
    own_miss = misses[0] if misses and recognize_url(url) else None

    # 2. fetch the page: status -> bot wall; body -> embedded ATS + plain-HTTP signals
    print("\n## page fetch")
    r = get(url)
    status = r.status_code if r is not None else "ERR"
    print(f"  GET {url} -> {status}")
    bot_walled = r is not None and r.status_code in (403, 429) and \
        bool(re.search(r"just a moment|challenge|cf-|captcha|verify you are human", r.text, re.I))
    signals, phenom, workdays = [], "/api/pcsx/" in url, workday_hosts(url)
    if r is not None and r.status_code == 200:
        hits, more = verify([b for b in recognize_page(r.text) if b != own])
        plat, misses = plat + hits, misses + more
        signals = plain_http_signals(r.text)
        phenom = phenom or "/api/pcsx/" in r.text
        workdays += workday_hosts(r.text)
    # A tenant whose board lists, or whose site the URL names, needs no hint. An embedded miss
    # may be an asset or login link, so it keeps the hint.
    read = {slug.rsplit("/", 1)[0] for source, slug, *_ in plat + ([own_miss] if own_miss else []) if source == "workday"}
    workday = next((w for w in workdays if w not in read), None)
    # An embed that could not be checked (not an empty one) is still a lead.
    unread = next((m for m in misses if m[2].startswith("could not verify")), None)

    print("\n## platform check")
    for source, slug in plat:
        print(f"  HIT  {source}  slug={slug}  (lists postings)")
    for source, slug, reason in misses:
        print(f"  no   {source}  slug={slug}  ({reason})")
    if phenom:
        print("  MAYBE  phenom  (/api/pcsx/ seen; slug is {host}/{domain}, not checked here)")
    if workday:
        print(f"  MAYBE  workday  (host of {workday}; site not confirmed)")
    if not (plat or misses or phenom or workday):
        print("  no known ATS recognized in the URL or embedded in the page")
    if bot_walled:
        print("\n  !! bot wall (Cloudflare/challenge) — plain HTTP is blocked")
    print("\n## plain-HTTP signals")
    print("  " + ("\n  ".join(signals) if signals else "none in static HTML (jobs may load via XHR)"))

    # verdict — earliest cascade rung that fits
    print()
    if plat:
        source, slug = plat[0]
        print(f"VERDICT: platform={source} slug={slug} -> data row, NO recipe needed")
    elif phenom:
        print("VERDICT: platform=phenom -> verify the {host}/{domain} slug, then data row, NO recipe needed")
    elif workday:
        print(f"VERDICT: platform=workday -> find or confirm the site for slug {workday}/{{site}}, then data row, NO recipe needed")
    elif own_miss:
        source, slug, reason = own_miss
        print(f"VERDICT: platform? -> the URL is {source} slug={slug}, but {reason}")
    elif bot_walled:
        print("VERDICT: browser -> plain HTTP is blocked; write a `browser` recipe (render + CSS)")
    elif signals:
        print("VERDICT: plain-http -> write a `custom` recipe; start from the signal(s) above")
    elif unread:
        source, slug, reason = unread
        print(f"VERDICT: platform? -> the page embeds {source} slug={slug}, but {reason}")
    elif r is None or status != 200:
        print("VERDICT: browser -> page not fetchable by plain HTTP; try a `browser` recipe")
    else:
        print("VERDICT: plain-http? -> page fetched but jobs aren't in the static HTML. Find the "
              "XHR that returns them (browser DevTools > Network, filter Fetch/XHR) and write a "
              "`custom` recipe; if there's no JSON endpoint, fall back to a `browser` recipe.")


if __name__ == "__main__":
    main()
