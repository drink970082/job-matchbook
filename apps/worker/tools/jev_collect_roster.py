#!/usr/bin/env python3
"""Private, immutable native-board snapshot capture; no DB or model operations."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ats_worker.roster_collection import canonical, collect, validate_scope
from ats_worker.fetch import ashby, greenhouse, lever


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("scope", "output", "window-start", "window-end"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--now")
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fixture")
    modes.add_argument("--live", action="store_true")
    for name in ("max-requests", "max-seconds", "max-response-bytes", "max-output-bytes"):
        p.add_argument("--" + name, type=int)
    args = p.parse_args(argv)
    scope = json.loads(Path(args.scope).read_text())
    validate_scope(scope)
    # Reserve the private output BEFORE any request; existing/unwritable paths never dispatch.
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        if args.live:
            if args.now or any(v is None or v <= 0 for v in (args.max_requests, args.max_seconds, args.max_response_bytes, args.max_output_bytes)):
                p.error("live requires explicit positive request/time/total-byte caps; --now forbidden")
            import requests
            started, requests_used, bytes_used = time.monotonic(), 0, 0
            session = requests.Session()
            def fetch(board):
                nonlocal requests_used, bytes_used
                remaining = args.max_seconds - (time.monotonic() - started)
                if requests_used >= args.max_requests or remaining <= 0:
                    raise RuntimeError("collection_cap_exhausted")
                source = board["source"]
                adapter = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}[source]
                params = {"greenhouse": {"content": "true"}, "lever": {"mode": "json"}, "ashby": {"includeCompensation": "true"}}[source]
                requests_used += 1
                with session.get(adapter.API.format(slug=board["slug"]), params=params,
                                 timeout=min(20, remaining), stream=True, allow_redirects=False) as response:
                    if not 200 <= response.status_code < 300:
                        raise RuntimeError("http_failure")
                    chunks = []
                    for chunk in response.iter_content(65536):
                        bytes_used += len(chunk)
                        if bytes_used > args.max_response_bytes or time.monotonic() - started > args.max_seconds:
                            raise RuntimeError("collection_cap_exhausted")
                        chunks.append(chunk)
                    return json.loads(b"".join(chunks).decode("utf-8"))
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            if not args.now:
                p.error("fixture mode requires --now")
            fixtures = json.loads(Path(args.fixture).read_text())
            def fetch(board):
                return fixtures[board["source"] + "/" + board["slug"]]
            now = args.now
        result = collect(scope, fetch_json=fetch, now=now,
                         window_start=args.window_start, window_end=args.window_end)
        output = canonical(result) + b"\n"
        if args.max_output_bytes is not None and len(output) > args.max_output_bytes:
            p.error("serialized output exceeds max-output-bytes; no file written")
        handle.write(output)
        print(json.dumps({"counts": result["counts"], "scope_capture_complete": result["scope_capture_complete"],
                          "daily_window_complete": False, "model_calls": 0, "database_writes": 0}, sort_keys=True))
        return 0 if result["scope_capture_complete"] else 2



if __name__ == "__main__":
    raise SystemExit(main())
