#!/usr/bin/env python3
"""Replay deterministic baselines over an offline frozen pool.

Use ``--snapshot`` for evidence-grade input validation. The legacy ID-only pool format is
still accepted for exploration and is always reported as INCONCLUSIVE because it lacks
full source payloads, exact profile/context linkage and a daily-membership manifest.
Reports contain aggregate metrics only; no provider, database, scorer or legacy-eval calls
are made.
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
    build_snapshot_replay_report,
    load_pool_text,
    load_snapshot_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pool", help="explicit JSON frozen pool or snapshot bundle")
    parser.add_argument("--snapshot", action="store_true", help="require the full frozen snapshot contract")
    parser.add_argument("--seed", required=True, help="fixed split seed recorded in the report")
    parser.add_argument("--heldout-fraction", required=True, type=float)
    parser.add_argument("--budget", required=True, action="append", type=int, dest="budgets")
    args = parser.parse_args()

    try:
        source = Path(args.pool).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print("cannot read explicit frozen replay input", file=sys.stderr)
        return 2

    try:
        if args.snapshot:
            snapshot = load_snapshot_text(source)
            report = build_snapshot_replay_report(
                snapshot,
                seed=args.seed,
                heldout_fraction=args.heldout_fraction,
                budgets=tuple(args.budgets),
            )
        else:
            pool = load_pool_text(source)
            report = build_replay_report(
                pool,
                seed=args.seed,
                heldout_fraction=args.heldout_fraction,
                budgets=tuple(args.budgets),
            )
    except ReplayValidationError as exc:
        print(f"cannot replay frozen input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
