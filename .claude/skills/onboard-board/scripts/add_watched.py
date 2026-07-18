#!/usr/bin/env python3
"""Add ONE board to the live watchlist so it shows up in the web Watchlist tab.

The watchlist is the DB table `watched_companies` (the shared SQLite the web app and
worker both use) — NOT config.yaml. config's `companies:` is only a one-time seed;
editing it after the first run does nothing and never reaches the UI. This inserts
directly, deduped on (source, slug), reusing the worker's own import path — so the row
appears in the Watchlist tab immediately and the worker fetches it next cycle.

Usage:
  python add_watched.py --source greenhouse --slug databricks --name "Databricks"
  python add_watched.py --source custom --slug deshaw --name "D. E. Shaw" --recipe recipe.json

Validate the recipe FIRST (the onboard-board skill does this) — only add rows that
actually parse >=1 posting. Prints `added` or `already on the watchlist`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.normpath(os.path.join(HERE, "../../../../apps/worker"))  # <repo>/apps/worker
sys.path.insert(0, WORKER)

from ats_worker import config, db  # noqa: E402

DEFAULT_DB = os.path.normpath(os.path.join(WORKER, "../web/prisma/applications.db"))


def main():
    ap = argparse.ArgumentParser(description="Add one board to the watchlist DB.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--recipe", help="path to a recipe JSON file (required for custom/browser)")
    ap.add_argument("--db", default=os.environ.get("DB_PATH", DEFAULT_DB))
    args = ap.parse_args()

    if args.source not in config.VALID_SOURCES:
        sys.exit(f"error: unknown source {args.source!r}; must be one of {config.VALID_SOURCES}")

    recipe = None
    if args.recipe:
        with open(args.recipe) as fh:
            recipe = json.load(fh)
    if args.source in config.RECIPE_SOURCES and not isinstance(recipe, dict):
        sys.exit(f"error: source {args.source!r} needs a --recipe JSON file (a mapping)")

    if not os.path.exists(args.db):
        sys.exit(f"error: watchlist DB not found at {args.db} (run `make db-push` first?)")

    row = {"source": args.source, "slug": args.slug, "name": args.name, "recipe": recipe}
    conn = db.connect(args.db)
    now = datetime.now(timezone.utc).isoformat()
    added = db.import_watchlist(conn, [row], now=now)
    if added:
        print(f"added: {args.source}/{args.slug} ({args.name}) — now in the web Watchlist tab; "
              f"the worker fetches it next cycle")
    else:
        print(f"already on the watchlist: {args.source}/{args.slug} (no change)")


if __name__ == "__main__":
    main()
