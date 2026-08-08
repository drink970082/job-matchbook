"""tools/backfill_descriptions.py — the one-off that re-hydrates stored teaser rows.

`upsert_postings` is ON CONFLICT DO NOTHING, so the fetch-layer work helps only postings
fetched after it; these are the rows already in the table. The property worth pinning is
what the tool must NOT do: 665 of those rows hold a paid fit verdict computed from the
teaser, and re-scoring them is a quota decision the operator makes, not this script.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from ats_worker import db
from tests._helpers import bootstrap_db, make_posting

TOOL = Path(__file__).resolve().parents[1] / "tools" / "backfill_descriptions.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("backfill_descriptions", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_descriptions"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seeded(tmp_path):
    """One scored row holding a teaser, one unscored, and one that has left the board."""
    path = bootstrap_db(tmp_path / "t.db")
    conn = db.connect(path)
    db.upsert_postings(conn, [
        make_posting("keep-me", description="teaser " * 30),
        make_posting("also-me", description="teaser " * 30),
        make_posting("gone", description="teaser " * 30),
    ], now="2026-08-01T00:00:00.000Z")
    conn.execute("UPDATE job_postings SET company_slug='acme'")
    conn.execute("UPDATE job_postings SET score=88, score_detail='{\"fit\":1}', "
                 "pipeline_status='scored' WHERE external_id='keep-me'")
    conn.commit()
    return conn


BOARD = {"source": "greenhouse", "slug": "acme", "name": "Acme", "recipe": None}


def _fake_fetch(mod, monkeypatch, postings):
    monkeypatch.setattr(mod, "fetch_company", lambda *a, **kw: postings)


def test_dry_run_writes_nothing(seeded, monkeypatch):
    mod = _load_tool()
    _fake_fetch(mod, monkeypatch, [make_posting("keep-me", description="F" * 4000)])
    examined, improved, before, after = mod.backfill(
        seeded, BOARD, apply_changes=False, min_gain=1.2)
    assert (examined, improved) == (1, 1) and before == [210] and after == [4000]
    stored = seeded.execute(
        "SELECT LENGTH(description) n FROM job_postings WHERE external_id='keep-me'"
    ).fetchone()["n"]
    assert stored == 210, "a dry run must not write"


def test_apply_replaces_only_the_description(seeded, monkeypatch):
    mod = _load_tool()
    _fake_fetch(mod, monkeypatch, [make_posting("keep-me", description="F" * 4000)])
    mod.backfill(seeded, BOARD, apply_changes=True, min_gain=1.2)
    row = seeded.execute(
        "SELECT LENGTH(description) n, score, score_detail, pipeline_status "
        "FROM job_postings WHERE external_id='keep-me'").fetchone()
    assert row["n"] == 4000
    # The whole point: a stale verdict stays stale and visible, it is not silently
    # recomputed (that costs quota) nor silently reset (that hides it).
    assert row["score"] == 88
    assert row["score_detail"] == '{"fit":1}'
    assert row["pipeline_status"] == "scored"


def test_a_posting_that_left_the_board_is_untouched(seeded, monkeypatch):
    mod = _load_tool()
    _fake_fetch(mod, monkeypatch, [make_posting("keep-me", description="F" * 4000)])
    examined, improved, *_ = mod.backfill(seeded, BOARD, apply_changes=True, min_gain=1.2)
    assert examined == 1, "only rows still on the board are examined"
    gone = seeded.execute(
        "SELECT LENGTH(description) n FROM job_postings WHERE external_id='gone'"
    ).fetchone()["n"]
    assert gone == 210


@pytest.mark.parametrize("fresh_len, improved", [(4000, 1), (220, 0), (100, 0), (0, 0)])
def test_min_gain_guards_against_churn_and_regression(seeded, monkeypatch,
                                                      fresh_len, improved):
    """A board transiently serving a SHORTER body must not overwrite a good stored one."""
    mod = _load_tool()
    _fake_fetch(mod, monkeypatch, [make_posting("keep-me", description="F" * fresh_len)])
    _, got, *_ = mod.backfill(seeded, BOARD, apply_changes=False, min_gain=1.2)
    assert got == improved


def test_only_ids_restricts_the_rows_and_gates_the_detail_calls(seeded, monkeypatch):
    """`--ids` is the eval-corpus path: touch the graded rows, leave the rest alone.
    The `keep` verdict it builds is what stops the board hydrating everything else."""
    mod = _load_tool()
    target = seeded.execute(
        "SELECT id FROM job_postings WHERE external_id='keep-me'").fetchone()["id"]
    verdicts = {}

    def fake_fetch(source, slug, name, recipe=None, keep=None):
        for ext in ("keep-me", "also-me"):
            verdicts[ext] = keep({"external_id": ext})
        return [make_posting("keep-me", description="F" * 4000),
                make_posting("also-me", description="F" * 4000)]

    monkeypatch.setattr(mod, "fetch_company", fake_fetch)
    examined, improved, *_ = mod.backfill(
        seeded, BOARD, apply_changes=True, min_gain=1.2, only_ids=[target])

    assert verdicts == {"keep-me": "hydrate", "also-me": "drop"}
    assert (examined, improved) == (1, 1)
    untouched = seeded.execute(
        "SELECT LENGTH(description) n FROM job_postings WHERE external_id='also-me'"
    ).fetchone()["n"]
    assert untouched == 210, "a row outside --ids must not be rewritten"
