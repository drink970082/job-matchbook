#!/usr/bin/env python3
"""Replay recency and role-coverage baselines on an offline frozen pool.

The report contains only aggregate metrics and never includes row/group identifiers or
posting/profile text. This tool has no provider, database, scorer, or legacy-eval calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/worker"))

from ats_worker.preselection.replay import (  # noqa: E402
    ReplayValidationError,
    build_replay_report,
    load_pool_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pool", help="explicit JSON frozen pool")
    parser.add_argument("--seed", required=True, help="fixed split seed recorded in the report")
    parser.add_argument("--heldout-fraction", required=True, type=float)
    parser.add_argument("--budget", required=True, action="append", type=int, dest="budgets")
    args = parser.parse_args()

    try:
        pool = load_pool_text(Path(args.pool).read_text(encoding="utf-8"))
        report = build_replay_report(
            pool,
            seed=args.seed,
            heldout_fraction=args.heldout_fraction,
            budgets=tuple(args.budgets),
        )
    except (OSError, UnicodeError, ReplayValidationError) as exc:
        print(f"invalid frozen pool or replay parameters: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
