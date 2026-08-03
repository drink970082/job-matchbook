"""The step-2 -> step-3 bridge: the shadow runner reading the frame the picker writes.

This file exists because that bridge was broken on first write and nothing caught it —
the picker had tests, the extractor had tests, and the one seam between them had none, so
`--frame` (the tool's headline usage) raised `KeyError: 'id'` on the frame's own header
line. Both halves being green is not the same as the pipeline running.
"""
import json

import pytest

from tools.extract_shadow import _rows_from_frame

FRAME_HEADER = {"kind": "frame_header", "seed": "s", "size": 1, "strata": {"a": 1},
                "provenance": {"concept_vocab_hash": "abc"}}
FRAME_ROW = {"id": 7, "stratum": "match/match",
             "posting": {"job_title": "SWE", "company_name": "Acme", "source": "greenhouse",
                         "location": "Remote", "description": "Build things."},
             "current": {"score": 80, "domain": "match", "seniority": "match"}}


def _frame(tmp_path, *rows):
    path = tmp_path / "frame.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_the_frame_header_is_skipped_not_parsed_as_a_posting(tmp_path):
    rows = _rows_from_frame(_frame(tmp_path, FRAME_HEADER, FRAME_ROW))
    assert [r["id"] for r in rows] == [7]
    assert rows[0]["description"] == "Build things."


def test_inline_posting_text_is_used_without_touching_the_db(tmp_path):
    """Self-containment is the lesson of the 22 dead `golden.jsonl` rows: a corpus that
    reads its text from mutable DB state decays without announcing it. A frame row with
    inline text must never need the DB — including when the DB row is gone."""
    row = {**FRAME_ROW, "id": 999999999}  # an id that is certainly not in any DB
    rows = _rows_from_frame(_frame(tmp_path, FRAME_HEADER, row))
    assert rows[0]["description"] == "Build things."


def test_a_row_with_no_usable_text_falls_back_to_the_db_and_says_so(tmp_path):
    """The fallback is real, so an unreachable id must fail loudly rather than shrink the
    run — the same failure that had `make eval-score` running 71 of 93 rows and reporting
    PASS."""
    stub = {"id": 999999999, "posting": {"description": ""}}
    with pytest.raises(SystemExit, match="not in the DB"):
        _rows_from_frame(_frame(tmp_path, FRAME_HEADER, stub))
