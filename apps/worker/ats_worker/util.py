"""Shared helpers for fetch adapters."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

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
