"""Shared helpers for fetch adapters."""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

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


def to_iso_date(value) -> str | None:
    """Normalize a board posting date to 'YYYY-MM-DD', or None.

    Accepts ISO-8601 strings (greenhouse first_published, ashby publishedAt,
    workday startDate — we keep the date prefix) and epoch-millisecond ints
    (lever createdAt). Anything unparseable returns None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # ponytail: epoch-ms is the only numeric date any board sends (lever)
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
    DNS query. A plain DNS name is allowed as-is (rebinding is out of scope; see
    PROGRESS)."""
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
