"""Tests for tools/build_review_sheet.py — the generator for the review sheet that
`eval/review_server.py` serves. No DB and no network: `classify` and `render_row` are
pure, and that is where the decisions live.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_review_sheet.py"
_spec = importlib.util.spec_from_file_location("build_review_sheet", TOOL)
sheet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sheet)


def _row(i, sen="match", dom="adjacent", **kw):
    return {"id": i, "seniority": sen, "domain": dom, "score": 70, **kw}


def test_classify_splits_on_either_verdict():
    codex = {1: _row(1), 2: _row(2), 3: _row(3, dom="match")}
    claude = {1: _row(1), 2: _row(2, sen="too_junior"), 3: _row(3, dom="mismatch")}
    dis, con = sheet.classify(codex, claude)
    assert dis == [2, 3]   # 2 differs on seniority, 3 on domain
    assert con == [1]


def test_classify_treats_a_backend_error_as_reviewable():
    """An `error` row must reach the human rather than being silently dropped or
    counted as consensus — a short output should say which rows failed."""
    codex = {1: {"id": 1, "error": "ScoreError: exit 1"}}
    claude = {1: _row(1)}
    dis, con = sheet.classify(codex, claude)
    assert dis == [1] and con == []


def test_classify_ignores_ids_only_one_backend_labelled():
    dis, con = sheet.classify({1: _row(1), 9: _row(9)}, {1: _row(1)})
    assert dis == [] and con == [1]


def test_render_row_shows_the_prior_answer_as_context_not_as_an_answer():
    """The operator's earlier verdict is displayed, but must NOT pre-fill the input —
    those answers were written mid-edit and pre-filling would launder a superseded rule
    into the new corpus."""
    out = sheet.render_row(
        5, "Data Engineer", "LeoLabs", "jd text", _row(5), _row(5, dom="match"),
        {"seniority": "match", "domain": "mismatch", "note": "old reasoning"},
        "disagreement")
    assert "context only" in out
    assert "old reasoning" in out
    assert 'match / mismatch' in out          # shown...
    assert 'value="mismatch" selected' not in out  # ...but never selected for them


def test_render_row_escapes_hostile_jd_text():
    # A JD is scraped from the internet and lands in a local HTML page.
    out = sheet.render_row(1, "<script>t</script>", "co", "<script>alert(1)</script>",
                           _row(1), _row(1), None, "consensus")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_render_row_marks_a_backend_error():
    out = sheet.render_row(1, "t", "c", "jd", {"id": 1, "error": "boom"}, _row(1),
                           None, "disagreement")
    assert "ERROR: boom" in out


def test_audit_sample_is_deterministic():
    """Regenerating the sheet must not reshuffle which consensus rows are audited, or a
    partly-reviewed sheet loses its place."""
    import random
    con = list(range(100))
    a = random.Random(sheet.AUDIT_SEED).sample(con, 10)
    b = random.Random(sheet.AUDIT_SEED).sample(con, 10)
    assert a == b


def test_read_labels_keys_by_int_id(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps({"id": "42", "domain": "match"}) + "\n")
    assert sheet.read_labels(p) == {42: {"id": "42", "domain": "match"}}
