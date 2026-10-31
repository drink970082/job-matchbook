#!/usr/bin/env python3
"""Build an aggregate preselection evaluation report from explicit local inputs.

This tool reads no job/profile text, makes no provider calls and never records GO.
Keep evaluation inputs and outputs in the private local research area.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/worker"))

from ats_worker.preselection.evaluation import (  # noqa: E402
    EvaluationValidationError,
    build_evaluation_report,
    load_evaluation_text,
)
from ats_worker.preselection.shadow import AttemptJournal, ShadowIntegrityError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_input", help="explicit local JSON labels/outcomes manifest")
    parser.add_argument("--journal", required=True, help="explicit private #111 attempt-journal path")
    args = parser.parse_args()

    try:
        evaluation = load_evaluation_text(Path(args.evaluation_input).read_text(encoding="utf-8"))
        journal = AttemptJournal.load(args.journal)
        report = build_evaluation_report(evaluation, journal)
    except (OSError, UnicodeError, EvaluationValidationError, ShadowIntegrityError) as exc:
        print(f"cannot build preselection evaluation report: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
