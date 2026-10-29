"""Explicit fixture-only CLI for synthetic review-batch creation and replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ats_worker.review_batch import (
    ReviewBatchError,
    build_review_batch,
    page_review_batch,
    revalidate_review_batch,
    summary,
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewBatchError("fixture or replay state could not be read") from exc


def _write_state(path: Path, batch: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(batch, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReviewBatchError("replay state could not be written") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or replay a synthetic review batch")
    parser.add_argument("--action", choices=("create", "page", "revalidate"), required=True)
    parser.add_argument("--state", type=Path, required=True, help="explicit local JSON replay state path")
    parser.add_argument("--fixture", type=Path, help="explicit synthetic fixture path")
    parser.add_argument("--cursor", help="cursor returned by the preceding page")
    parser.add_argument("--elapsed-seconds", type=int, help="injected synthetic revalidation elapsed time")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.action in {"create", "revalidate"} and args.fixture is None:
        parser.error("--fixture is required for this action")
    if args.action == "revalidate" and args.elapsed_seconds is None:
        parser.error("--elapsed-seconds is required for revalidation")
    if args.fixture is not None and args.fixture.resolve() == args.state.resolve():
        parser.error("fixture and state paths must be different")

    try:
        if args.action == "create":
            batch = build_review_batch(_read_json(args.fixture))
            _write_state(args.state, batch)
            output = summary(batch)
            output["first_page"] = page_review_batch(batch)
        else:
            batch = _read_json(args.state)
            if args.action == "page":
                output = page_review_batch(batch, args.cursor)
            else:
                updated = revalidate_review_batch(
                    batch, _read_json(args.fixture), elapsed_seconds=args.elapsed_seconds
                )
                _write_state(args.state, updated)
                output = summary(updated)
                output["first_page"] = page_review_batch(updated)
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    except Exception:
        print("invalid synthetic fixture, state, or cursor", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
