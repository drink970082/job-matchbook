"""The worker's URL resolver agrees with the web's (apps/web/src/lib/board-url.ts) on the
job-URL shapes both handle, via the fixture both suites run (#208)."""
import json
from pathlib import Path

import pytest

from ats_worker.feed.resolve import resolve_url

CASES = json.loads((Path(__file__).parent / "fixtures" / "board-url-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", [c for c in CASES if c.get("job")], ids=lambda c: c["url"])
def test_resolve_url_matches_the_shared_board_cases(case):
    got = resolve_url(case["url"])
    assert got is not None and got[:2] == (case["source"], case["slug"])
