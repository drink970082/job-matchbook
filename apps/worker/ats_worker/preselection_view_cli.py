"""Explicit fixture runner for the offline assessment-view projection."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .preselection_view import project_assessment_view

_CASE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("fixture_read_error") from exc
    if (not isinstance(fixture, dict) or fixture.get("fixture_schema_version") != 1
            or type(fixture.get("fixture_schema_version")) is not int
            or fixture.get("synthetic") is not True
            or not isinstance(fixture.get("cases"), list)
            or len(fixture.get("cases", [])) > 32):
        raise ValueError("invalid_fixture")
    return fixture


def _load_case(fixture: dict[str, Any], case_name: str) -> Any:
    matches = [case for case in fixture["cases"]
               if isinstance(case, dict) and case.get("name") == case_name]
    if len(matches) != 1 or "snapshot" not in matches[0]:
        raise ValueError("fixture_case_not_unique_or_missing")
    return matches[0]["snapshot"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, help="explicit synthetic fixture JSON path")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", help="case name in the supplied fixture")
    selection.add_argument("--all", action="store_true", help="project every case in the supplied fixture")
    parser.add_argument("--output", help="write JSON to this explicit path instead of stdout")
    args = parser.parse_args(argv)

    try:
        fixture = _load_fixture(Path(args.fixture))
        if args.all:
            cases = fixture["cases"]
            names = [case.get("name") for case in cases if isinstance(case, dict)]
            if (len(names) != len(cases) or any(not isinstance(name, str) or not _CASE_NAME.fullmatch(name)
                                                for name in names)
                    or len(set(names)) != len(names)):
                raise ValueError("invalid_fixture_cases")
            output: Any = {
                "fixture_schema_version": 1,
                "scope": "synthetic_assessment_cases",
                "synthetic": True,
                "cases": [
                    {"name": case["name"],
                     "view": project_assessment_view(case.get("snapshot"))}
                    for case in cases
                ],
            }
        else:
            output = project_assessment_view(_load_case(fixture, args.case))
        encoded = json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n"
        if args.output:
            Path(args.output).write_text(encoded, encoding="utf-8")
        else:
            sys.stdout.write(encoded)
    except (OSError, ValueError) as exc:
        # Never echo a path, payload, or exception string supplied by the caller.
        sys.stderr.write(f"{exc.args[0] if isinstance(exc, ValueError) else 'fixture_write_error'}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
