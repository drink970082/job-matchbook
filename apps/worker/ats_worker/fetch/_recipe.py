"""Shared recipe extraction for the declarative `custom` (plain-HTTP) and `browser`
executors. A recipe is data (a dict), authored once per board; these helpers turn a
raw job object (JSON node or a parsed DOM node) into the canonical 8-field posting
dict, so neither executor grows per-site code.

Field spec (all optional except title/external_id in practice):
  title        dotted path
  location     dotted path (str, or list -> joined; missing -> None)
  url          dotted path OR a "template with {dotted.field}" placeholders
  description  dotted path OR [path, path, ...]  (list -> concatenated)
  posted_at    dotted path (tolerant-normalized; missing -> None)
  external_id  dotted path

Dotted paths index dicts by key and lists by integer index, e.g. "office.0.name".
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ats_worker.util import html_to_text

_PLACEHOLDER = re.compile(r"\{([^}]+)\}")


def dotted_get(obj, path):
    """Walk a dotted path into nested dicts/lists. Numeric segments index lists.
    Returns None on any miss (never raises)."""
    if not path:
        return None
    cur = obj
    for key in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and key.isdigit():
            i = int(key)
            cur = cur[i] if -len(cur) <= i < len(cur) else None
        else:
            return None
    return cur


def _s(v) -> str:
    return "" if v is None else str(v)


def interpolate(template: str, item) -> str:
    """Fill `{dotted.field}` placeholders in a URL template from the raw item."""
    return _PLACEHOLDER.sub(lambda m: _s(dotted_get(item, m.group(1))), template)


def normalize_date(value):
    """Tolerant date -> 'YYYY-MM-DD' or None. Handles ISO-ish strings, the human
    'Month D, YYYY' form (Amazon), and epoch seconds/ms. Kept separate from
    util.to_iso_date so that adapter's epoch-ms-only contract stays untouched."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000 if value >= 1e12 else value  # epoch ms vs seconds
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OSError, ValueError, OverflowError):
            return None
    s = str(value).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def _location(item, spec):
    if not spec:
        return None
    val = dotted_get(item, spec)
    if val is None or val == "":
        return None
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v) or None
    return str(val)


def _url(item, spec):
    if not spec:
        return ""
    if "{" in spec:  # template
        return interpolate(spec, item)
    return _s(dotted_get(item, spec))


def _description(item, spec):
    if not spec:
        return ""
    if isinstance(spec, list):
        parts = [_s(dotted_get(item, p)) for p in spec]
        return "\n\n".join(p for p in parts if p)
    return _s(dotted_get(item, spec))


def apply_fields(item, fields: dict, company_name: str, source: str) -> dict:
    """Build one canonical posting dict from a raw job object + the field spec."""
    fields = fields or {}
    return {
        "source": source,
        "external_id": _s(dotted_get(item, fields.get("external_id"))),
        "company_name": company_name,
        "job_title": _s(dotted_get(item, fields.get("title"))).strip(),
        "location": _location(item, fields.get("location")),
        "job_url": _url(item, fields.get("url")),
        "description": html_to_text(_description(item, fields.get("description"))),
        "posted_at": normalize_date(dotted_get(item, fields.get("posted_at"))),
    }
