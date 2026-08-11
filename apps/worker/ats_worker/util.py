"""Shared helpers for the fetch adapters, plus the URL-safety pair
(`is_safe_public_url`, `get_redirect_safe`) the feed resolver imports."""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

# Canonical fields every adapter must produce. Aligned with the Prisma
# job_postings model (worker writes a subset; scoring fills the rest).
POSTING_FIELDS = (
    "source",
    "external_id",
    "company_name",
    "job_title",
    "location",
    "job_url",
    "description",
    "posted_at",
)


def join_present(obj: dict, keys: tuple[str, ...]) -> str | None:
    """`", "`-join the non-blank values of `keys`, in order — or None if none are set.

    Three boards spell a location as flat sibling fields under different names, and
    each carried its own copy of this comprehension with only the key tuple differing:
    workable (city/state/country), smartrecruiters (city/region/country), and jobvite's
    JSON-LD address (addressLocality/addressRegion/addressCountry).

    Present-but-blank values are dropped rather than joined, so a record with an empty
    city yields "CA, US" and never ", CA, US". Everything is `str()`-coerced first —
    these are board JSON payloads, where a country can arrive as a number.
    """
    parts = [str(obj.get(k)).strip() for k in keys
             if obj.get(k) and str(obj.get(k)).strip()]
    return ", ".join(parts) or None


def to_iso_date(value) -> str | None:
    """Normalize a board posting date to 'YYYY-MM-DD', or None.

    Accepts ISO-8601 strings (greenhouse first_published, ashby publishedAt,
    workday startDate — we keep the date prefix) and epoch-millisecond ints
    (lever createdAt). Anything unparseable returns None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # ponytail: every numeric date that reaches here is epoch-ms — lever sends it
        # that way natively, and phenom scales its epoch-SECONDS before calling.
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    s = str(value)
    return s[:10] if len(s) >= 10 else None

_TAG_RE = re.compile(r"<[^>]+>")
# Include U+00A0 (the unescaped &nbsp;) so non-breaking spaces collapse to a
# normal space rather than leaking into descriptions.
_WS_RE = re.compile(r"[ \t\f\v\xa0]+")
_BLANKS_RE = re.compile(r"\n\s*\n\s*\n+")


def html_to_text(value: str | None) -> str:
    """Convert a (possibly entity-escaped) HTML blob to readable plain text.

    Greenhouse returns entity-escaped HTML in `content`; Ashby/Lever expose a
    `descriptionHtml`. The LLM only needs readable text, so unescape entities,
    drop tags, and collapse runaway whitespace while keeping paragraph breaks.
    """
    if not value:
        return ""
    text = html.unescape(value)
    # Turn block-ish tags into newlines before stripping the rest.
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|tr)\s*>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)  # entities that were themselves escaped twice
    text = _WS_RE.sub(" ", text)
    text = _BLANKS_RE.sub("\n\n", text)
    return text.strip()


def is_safe_public_url(url: str | None) -> bool:
    """True only for an http(s) URL whose host is a public target. Pure (no DNS):
    blocks the SSRF vectors a scraped URL can carry — non-http(s) schemes, `localhost`,
    and private/loopback/link-local/reserved IP literals (incl. 169.254.169.254), incl.
    legacy IPv4 notations (decimal/octal/hex/short) that the OS resolver accepts with NO
    DNS query. Also normalizes a trailing dot (`localhost.`) before the `localhost` check
    and rejects an IPv6 zone-id suffix (`%`, e.g. `fe80::1%eth0`). A plain DNS name is
    allowed as-is (rebinding is out of scope; see PROGRESS)."""
    try:
        p = urlparse(url or "")
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost") or "%" in host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    # Legacy IPv4 notations (decimal "2130706433", octal "0177.0.0.1", short "127.1",
    # hex) are parsed by the OS resolver via inet_aton with NO DNS query, so
    # ip_address() alone is bypassable. inet_aton is pure parsing — if it accepts
    # the host, judge the decoded address; only a genuine DNS name falls through.
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return True   # a real DNS name (rebinding out of scope; see PROGRESS)
    return ipaddress.ip_address(socket.inet_ntoa(packed)).is_global


def get_redirect_safe(http, url, *, timeout, method="get", max_redirects=5, **kwargs):
    """GET/POST `url` via `http` (a `requests.Session` or the `requests` module),
    following redirects MANUALLY so every hop — the initial URL and each 3xx
    `Location` — is re-validated with `is_safe_public_url` before it is ever
    requested. `requests`' default `allow_redirects=True` (and a browser's
    `page.goto`) instead follow a redirect without re-checking, so a URL that
    passes the initial guard can still 302 into an internal target; this is
    what closes that gap for the plain-HTTP fetch paths.

    A redirect hop is always re-issued as a GET with headers only — params/
    body are dropped, since the Location is the full next target (this mirrors
    browser 302-to-GET behavior and is sufficient for these scrapers).

    Returns the final non-redirect `requests.Response`. Raises `ValueError` if
    any hop (initial or via a `Location`) fails `is_safe_public_url`, or if
    more than `max_redirects` hops are followed.
    """
    kwargs["allow_redirects"] = False
    m = method.lower()
    for _ in range(max_redirects + 1):
        if not is_safe_public_url(url):
            raise ValueError(f"unsafe url (initial or via redirect): {url!r}")
        resp = getattr(http, m)(url, timeout=timeout, **kwargs)
        if resp.is_redirect and resp.headers.get("location"):
            url = urljoin(url, resp.headers["location"])
            # ponytail: every hop is re-issued as GET, dropping params/body —
            # 307/308's strict method+body preservation is intentionally not
            # modeled (these scrapers never see 307/308 in practice).
            m, kwargs = "get", {"allow_redirects": False, "headers": kwargs.get("headers")}
            continue
        return resp
    raise ValueError(f"too many redirects (> {max_redirects})")
