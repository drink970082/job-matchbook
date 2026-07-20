#!/usr/bin/env python3
"""Set the web app's application-category vocabulary — the list a user picks from
when marking a job applied / adding an application, and the slices of the category
donut.

The categories live in the shared SQLite as ONE `app_settings` row
(key='categories', value = a JSON string array) — NOT config.yaml. This writes it
directly, reusing the worker's own DB layer, so the web UI reflects the chosen list
immediately. Used by the onboard-me flow to let a new user pick categories for their
own field (finance, product, …) instead of the built-in defaults.

Usage:
  python set_categories.py "Investment Banking,Private Equity,Equity Research,Others"
  python set_categories.py "Product" "Growth" "Product Marketing" "Others"

Accepts one comma-separated argument or several positional args; trims blanks and
de-duplicates case-insensitively. Prints `set N categories: …`.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.normpath(os.path.join(HERE, "../../../../apps/worker"))  # <repo>/apps/worker
sys.path.insert(0, WORKER)

from ats_worker import db  # noqa: E402

# <repo>/db/applications.db — the real shared DB (see add_watched.py for why not the
# gitignored prisma symlink).
DEFAULT_DB = os.path.normpath(os.path.join(WORKER, "../../db/applications.db"))


def parse_categories(argv) -> list[str]:
    """Split args on commas, trim, drop blanks, dedupe case-insensitively (first
    spelling wins). Order is preserved — it's the dropdown order the user sees."""
    raw: list[str] = []
    for a in argv:
        raw.extend(a.split(","))
    seen: set[str] = set()
    out: list[str] = []
    for c in raw:
        c = c.strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    db_path = os.environ.get("DB_PATH", DEFAULT_DB)
    cats = parse_categories(argv)
    if not cats:
        sys.exit('error: give at least one category, e.g. '
                 'set_categories.py "Finance,Product,Others"')
    if not os.path.exists(db_path):
        sys.exit(f"error: DB not found at {db_path} (run `make db-push` first?)")

    conn = db.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_setting(conn, "categories", json.dumps(cats), now=now)
    print(f"set {len(cats)} categories: {', '.join(cats)}")


if __name__ == "__main__":
    main()
