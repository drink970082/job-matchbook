#!/usr/bin/env python3
"""Add ONE board to the live watchlist so it shows up in the web Sources tab.

The add goes through the web's write API (`POST /api/v1/watchlist`), the same path as
MCP `add_source`: the web validates source, slug, duplicate and recipe, and writes the
audit row (actor `mcp`). There is no direct database write and no fallback to one: no
key, or no reachable web app, fails with the reason.

The key is ATS_API_KEY, else the file ~/.config/ats-mcp/api-key; ATS_API_URL overrides
the web address (default http://127.0.0.1:3000).

A known-ATS board is fetched once from its list before it is added, and refused when it
lists nothing or the fetch fails. A custom/browser recipe is not fetched here: validate
it FIRST (the onboard-board skill does this).

Usage:
  python add_watched.py --source greenhouse --slug databricks --name "Databricks"
  python add_watched.py --source custom --slug deshaw --name "D. E. Shaw" --recipe recipe.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.normpath(os.path.join(HERE, "../../../../apps/worker"))  # <repo>/apps/worker
sys.path.insert(0, WORKER)

from ats_worker.fetch import RECIPE_SOURCES, board_has_listings  # noqa: E402
from ats_worker.mcp.write_client import WriteAPIError, write_client_from_env  # noqa: E402
from ats_worker.source_lifecycle import verify_board  # noqa: E402


def key_file() -> Path:
    return Path.home() / ".config/ats-mcp/api-key"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.exit(f"error: cannot read {path}: {exc}")


def write_client():
    env = dict(os.environ)
    try:
        from_file = not env.get("ATS_API_KEY", "").strip() and key_file().is_file()
    except OSError as exc:
        sys.exit(f"error: cannot read {key_file()}: {exc}")
    if from_file:
        env["ATS_API_KEY"] = read_text(key_file())
    key = env.get("ATS_API_KEY", "").strip()
    if not key.isascii() or len(key.split()) > 1:  # would fail as a header, as "unreachable"
        sys.exit("error: the write key must be one line of ASCII with no spaces")
    client = write_client_from_env(env)
    if client is None:
        sys.exit(f"error: no write key: set ATS_API_KEY or put the web's ATS_API_KEY_READ_WRITE "
                 f"value in {key_file()} (docs/SETUP.md, \"enable writes\")")
    return client


def post(client, body) -> dict:
    board = client.call("POST", "/api/v1/watchlist", body)
    if not isinstance(board, dict) or not {"source", "slug", "name"} <= board.keys():
        raise WriteAPIError("the server at ATS_API_URL is not the ATS web app")
    return board


def main(argv=None, has_listings=board_has_listings):
    ap = argparse.ArgumentParser(description="Add one board to the watchlist through the web.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--recipe", help="path to a recipe JSON file (required for custom/browser)")
    args = ap.parse_args(argv)

    body = {"source": args.source, "slug": args.slug, "name": args.name}
    if args.recipe:
        body["recipe"] = read_text(Path(args.recipe))

    client = write_client()
    try:
        # The web resolves and validates first, so the fetch only ever runs on a board it
        # would accept (an unsafe slug never reaches a fetch URL).
        board = post(client, {**body, "dry_run": True})
        if board["source"] not in RECIPE_SOURCES:
            reason = verify_board(has_listings, board["source"], board["slug"], board["name"])
            if reason:
                sys.exit(f"error: {board['source']}/{board['slug']} not added: {reason}")
    except WriteAPIError as exc:
        sys.exit(f"error: {args.source}/{args.slug} not added: {exc}")
    try:
        added = post(client, body)
    except WriteAPIError as exc:  # a timeout may come after the web stored the row
        sys.exit(f"error: {args.source}/{args.slug} not confirmed (run again to see whether it was added): {exc}")
    print(f"added: {added['source']}/{added['slug']} ({added['name']}) - now in the web Sources tab; "
          f"the worker fetches it next cycle")
    if added.get("warning"):
        print(f"warning: {added['warning']}")


if __name__ == "__main__":
    main()
