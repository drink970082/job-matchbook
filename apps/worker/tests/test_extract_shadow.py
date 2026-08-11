"""The step-2 -> step-3 bridge: the shadow runner reading the frame the picker writes.

This file exists because that bridge was broken on first write and nothing caught it —
the picker had tests, the extractor had tests, and the one seam between them had none, so
`--frame` (the tool's headline usage) raised `KeyError: 'id'` on the frame's own header
line. Both halves being green is not the same as the pipeline running.
"""
import json

import pytest

import tools.extract_shadow as extract_shadow
from tools.extract_shadow import _rows_from_frame, _tightest_window

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


def test_a_row_with_no_usable_text_is_routed_to_the_db(tmp_path, monkeypatch):
    """A row that carries no inline text falls back to the DB, and an id the DB does not
    have fails loudly rather than shrinking the run — the same failure that had
    `make eval-score` running 71 of 93 rows and reporting PASS.

    The DB read is faked, not performed. Worker tests take no network and touch no real
    files (CLAUDE.md), and the operator's DB does not exist in CI — a test that opens it
    passes here and fails there, which is worse than no test.
    """
    asked = {}

    def fake_db(ids):
        asked["ids"] = ids
        raise SystemExit(f"{len(ids)} id(s) are not in the DB: {ids}")

    monkeypatch.setattr("tools.extract_shadow._rows_from_db", fake_db)
    stub = {"id": 999999999, "posting": {"description": ""}}
    with pytest.raises(SystemExit, match="not in the DB"):
        _rows_from_frame(_frame(tmp_path, FRAME_HEADER, FRAME_ROW, stub))
    # Only the textless row is asked for; the inline one never reaches the DB.
    assert asked["ids"] == [999999999]


@pytest.fixture
def clean_meter_cache():
    extract_shadow._meter_cache.clear()
    extract_shadow._meter_penalty.clear()
    yield
    extract_shadow._meter_cache.clear()
    extract_shadow._meter_penalty.clear()


def _fake_usage(calls, limits):
    def fetch():
        calls.append(1)
        return {"limits": limits} if limits else None
    return fetch


def test_the_meter_is_cached_so_a_fast_arm_does_not_rate_limit_itself(
        monkeypatch, clean_meter_cache):
    """The guard reads the meter before every call. At opus's ~25s/posting that is ~144
    requests/hour against a rate-limited endpoint, which answered 429 and ended a sitting
    at 31 rows. Reads inside the TTL must not reach the network."""
    calls = []
    monkeypatch.setattr("ats_worker.score.usage.fetch_claude_usage",
                        _fake_usage(calls, [{"used_percent": 40, "window_minutes": 300,
                                             "key": "session"}]))
    assert _tightest_window("claude") == (40, "session")
    assert _tightest_window("claude") == (40, "session")
    assert _tightest_window("claude") == (40, "session")
    assert len(calls) == 1, "cached reads must not re-fetch"

    # ttl=0 forces a refresh, proving the cache expires rather than pinning forever.
    assert _tightest_window("claude", ttl=0) == (40, "session")
    assert len(calls) == 2


def test_a_failure_opens_a_no_request_penalty_box(monkeypatch, clean_meter_cache):
    """`_get_json` retries a 429 four times, and without a penalty box the next row does
    it again 35s later — ~4 requests per row, which is what held the endpoint throttled
    and stalled two sittings. After a failure the run must make NO request for a while."""
    calls = []
    monkeypatch.setattr("ats_worker.score.usage.fetch_claude_usage", _fake_usage(calls, None))
    assert _tightest_window("claude") is None
    assert len(calls) == 1
    assert _tightest_window("claude") is None
    assert _tightest_window("claude") is None
    assert len(calls) == 1, "the penalty box must suppress the request entirely"


def test_a_stale_reading_beats_going_blind_but_only_up_to_the_ceiling(
        monkeypatch, clean_meter_cache):
    """A 429 means 'you asked too often', not 'the meter is broken' — the last good
    reading is still the best evidence available, so serve it rather than burning a blind
    strike. Past the ceiling it is too stale to act on and the run goes blind as before."""
    good = _fake_usage([], [{"used_percent": 40, "window_minutes": 300, "key": "session"}])
    monkeypatch.setattr("ats_worker.score.usage.fetch_claude_usage", good)
    assert _tightest_window("claude") == (40, "session")

    monkeypatch.setattr("ats_worker.score.usage.fetch_claude_usage", _fake_usage([], None))
    # ttl=0 forces past the cache; the failure serves the stale reading instead of None.
    assert _tightest_window("claude", ttl=0) == (40, "session")

    # Age the cached reading past the ceiling: now it is blind, and the strike counts.
    stamp, value = extract_shadow._meter_cache["claude"]
    extract_shadow._meter_cache["claude"] = (stamp - extract_shadow._METER_STALE_MAX_S - 1,
                                             value)
    extract_shadow._meter_penalty.clear()
    assert _tightest_window("claude", ttl=0) is None


def test_the_tightest_window_wins_not_the_largest(monkeypatch, clean_meter_cache):
    """A 250-call batch exhausts the rolling 5h session window long before the weekly."""
    monkeypatch.setattr("ats_worker.score.usage.fetch_claude_usage",
                        _fake_usage([], [{"used_percent": 88, "window_minutes": 10080,
                                          "key": "weekly_all"},
                                         {"used_percent": 12, "window_minutes": 300,
                                          "key": "session"}]))
    assert _tightest_window("claude") == (12, "session")
