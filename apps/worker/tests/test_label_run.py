"""Tests for tools/label_run.py — the blind K=1 corpus labeler.

Nothing here talks to a network or a real backend: `label_one` takes the scorer as an
argument, so a fake closure is the whole seam.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "label_run.py"
_spec = importlib.util.spec_from_file_location("label_run", TOOL)
label_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(label_run)


CARD = {
    "score": 71,
    "insufficient_context": False,
    "assessment": {
        "seniority": {"verdict": "match", "note": "no stated bar"},
        "domain": {"verdict": "adjacent", "note": "ANTI: no. TARGET: priority 5."},
        "summary": "tier-5 general SWE",
    },
}


def test_load_ids_reads_only_ids(tmp_path):
    """BLINDNESS is the whole point: a corpus row's own verdict must not be readable
    here, or a prior label (the operator's included) could leak into the run."""
    corpus = tmp_path / "c.jsonl"
    corpus.write_text(
        json.dumps({"id": 5, "seniority": "match", "domain": "match",
                    "note": "operator said so"}) + "\n"
        + json.dumps({"id": 7, "domain": "mismatch"}) + "\n")
    assert label_run.load_ids(corpus) == [5, 7]


def test_label_one_flattens_the_scorecard():
    fit = lambda postings, resumes: [dict(CARD)]  # noqa: E731
    got = label_run.label_one(fit, {"swe": "r"}, {"id": 9, "job_title": "t"})
    assert got == {
        "id": 9, "seniority": "match", "domain": "adjacent", "score": 71,
        "insufficient_context": False, "seniority_note": "no stated bar",
        "domain_note": "ANTI: no. TARGET: priority 5.", "summary": "tier-5 general SWE",
    }


def test_label_one_records_a_backend_failure_as_data():
    """A dead backend must leave a visible `error` row, not a silently absent id — a
    287-row run whose output is 280 rows should say which 7 failed and why."""
    def boom(postings, resumes):
        raise RuntimeError("codex exec failed (exit 1)")
    got = label_run.label_one(boom, {}, {"id": 3})
    assert got["id"] == 3
    assert "RuntimeError" in got["error"] and "exit 1" in got["error"]
    assert "domain" not in got  # no half-row that could be mistaken for a verdict


def test_build_scorer_rejects_an_unknown_backend():
    with pytest.raises(SystemExit, match="unknown SCORE_BACKEND"):
        label_run.build_scorer("openai", "m", "", {})


def test_build_scorer_never_reaches_the_metered_path_by_accident(monkeypatch):
    """`claude-code` and `claude-api` are one character apart in intent and a world
    apart in billing; the split must be explicit, never a fall-through else."""
    monkeypatch.setattr(label_run.score, "make_claude_cli_scorer",
                        lambda model, **kw: ("cli", model))
    monkeypatch.setattr(label_run.score, "make_claude_scorer",
                        lambda key, model, **kw: ("api", key, model))
    assert label_run.build_scorer("claude-code", "m", "", {}) == ("cli", "m")
    assert label_run.build_scorer("claude-api", "m", "", {"ANTHROPIC_API_KEY": "k"}) == (
        "api", "k", "m")


def test_reachable_drops_what_the_shipped_filters_refuse(tmp_path):
    """Driven through the real `prefilter_postings`, not a reimplementation of its rule
    — the point is to spend calls only on rows the pipeline can still produce."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE job_postings (id INTEGER PRIMARY KEY, job_title TEXT)")
    conn.executemany("INSERT INTO job_postings VALUES (?, ?)", [
        (1, "Software Engineer, New Grad"),   # kept
        (2, "Senior Software Engineer"),      # refused: seniority
        (3, "Chief Happiness Officer"),       # refused: fails the keep-list
    ])
    conn.commit()
    cfg = tmp_path / "config.yaml"
    cfg.write_text('title_filter: ["engineer"]\ntitle_exclude: ["senior"]\n')
    assert label_run.reachable(conn, [1, 2, 3], cfg) == [1]
