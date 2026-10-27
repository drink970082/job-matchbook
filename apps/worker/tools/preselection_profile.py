#!/usr/bin/env python3
"""Validate/render one explicitly supplied candidate profile without printing its text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/worker"))

from ats_worker.preselection.profile import (  # noqa: E402
    ProfileValidationError,
    load_profile,
    render_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", help="explicit path to candidate_profile.json")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--check-rendered", help="compare exact bytes with an existing context file"
    )
    destination.add_argument(
        "--write-rendered", help="write generated context to this explicit path"
    )
    args = parser.parse_args()

    try:
        profile = load_profile(args.profile)
        rendered = render_profile(profile)
        match: bool | None = None
        if args.check_rendered:
            match = Path(args.check_rendered).read_bytes() == rendered.encode("utf-8")
        elif args.write_rendered:
            Path(args.write_rendered).write_bytes(rendered.encode("utf-8"))
    except (OSError, ProfileValidationError) as exc:
        print(f"invalid candidate profile: {exc}", file=sys.stderr)
        return 2

    report = {
        "schema": profile.schema,
        "version": profile.version,
        "status": profile.status,
        "background_blocks": len(profile.background),
        "preference_blocks": len(profile.preferences),
        "profile_sha256": profile.identity_sha256,
        "context_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "context_characters": len(rendered),
    }
    if match is not None:
        report["rendered_file_matches"] = match
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
