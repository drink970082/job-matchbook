"""Run one fully explicit, local synthetic preselection rehearsal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .preselection_rehearsal import MAX_FIXTURE_BYTES, RehearsalError, run_synthetic_rehearsal


def _read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_FIXTURE_BYTES:
            raise RehearsalError("fixture exceeds explicit input bound")
        return json.loads(path.read_text(encoding="utf-8"))
    except RehearsalError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("fixture could not be read") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True,
                        help="explicit synthetic rehearsal scenario JSON")
    parser.add_argument("--assessment-fixture", type=Path, required=True,
                        help="explicit synthetic assessment fixture JSON")
    parser.add_argument("--pool-fixture", type=Path, required=True,
                        help="explicit synthetic candidate pool JSON")
    parser.add_argument("--output", type=Path, required=True,
                        help="explicit output path for the synthetic report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    input_paths = (args.scenario.resolve(), args.assessment_fixture.resolve(), args.pool_fixture.resolve())
    output_path = args.output.resolve()
    if output_path in input_paths:
        parser.error("invalid output path: it must differ from every explicit fixture")
    try:
        report = run_synthetic_rehearsal(
            _read_json(args.scenario),
            _read_json(args.assessment_fixture),
            _read_json(args.pool_fixture),
        )
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        args.output.write_text(encoded, encoding="utf-8")
    except (OSError, RehearsalError, TypeError, ValueError):
        # Never echo fixture data, private text, paths, or exception contents.
        sys.stderr.write("invalid synthetic rehearsal input or output\n")
        return 2
    sys.stdout.write("synthetic rehearsal report written\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
