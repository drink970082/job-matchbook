"""Shared helpers for fetch adapters."""
from __future__ import annotations

import html
import re

# Canonical fields every adapter must produce. Aligned with the Prisma
# job_postings model (worker writes a subset; score/tailor fill the rest).
POSTING_FIELDS = (
    "source",
    "external_id",
    "company_name",
    "job_title",
    "location",
    "job_url",
    "description",
)

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
