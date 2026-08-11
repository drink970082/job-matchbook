"""The labelling queue: what lands in it, and that the blinding is really blind.

The UI is hand-driven and needs no test. The queue builder does: it decides which rows
a human ever sees, and a silent bug there biases the corpus that every later rule is
fitted on.
"""
import json

from tools.label_extractions import align_items, build_queue


def _duty(label, concept, importance="core"):
    return {"label": label, "importance": importance,
            "concept_mapping": {"status": "mapped", "concept_ids": [concept]},
            "job_evidence": {"quote": label, "source": "job 1"}}


def _arm(tmp_path, name, rows, model):
    path = tmp_path / name
    lines = [json.dumps({"kind": "run_header", "backend": "x", "model": model,
                         "concepts": [{"ref": "c_1", "concept_id": "alpha",
                                       "description": "alpha work"}]})]
    for pid, extraction in rows.items():
        lines.append(json.dumps({"id": pid, "extraction": extraction}))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _frame(tmp_path, pids):
    path = tmp_path / "frame_extraction.jsonl"
    path.write_text("\n".join(
        json.dumps({"id": pid, "stratum": "match/match",
                    "posting": {"job_title": f"role {pid}", "company_name": "co",
                                "source": "greenhouse", "location": "NYC",
                                "description": f"jd text {pid}"},
                    "current": {"score": 60}})
        for pid in pids), encoding="utf-8")
    return path


def _build(tmp_path, opus, codex, **kw):
    _arm(tmp_path, "extract_opus.jsonl", opus, "opus")
    _arm(tmp_path, "extract_codex.jsonl", codex, "codex")
    _frame(tmp_path, sorted(set(opus) | set(codex)))
    return build_queue(tmp_path, **kw)


def test_agreeing_rows_are_sampled_not_queued_wholesale(tmp_path):
    """Agreement is the cheap half; only a sample of it is worth a human's time."""
    same = {pid: {"duties": [_duty("build alpha", "alpha")]} for pid in range(1, 21)}
    out = _build(tmp_path, same, dict(same), agree_sample=4)

    assert out["counts"]["disagree"] == 0
    assert out["counts"]["agree_pool"] == 20
    # One stratum, floor of 2 per stratum: the sample is a fraction, never the pool.
    assert 2 <= out["counts"]["agree_sampled"] < 20


def test_a_different_dominant_concept_is_a_disagreement(tmp_path):
    opus = {1: {"duties": [_duty("build alpha", "alpha")]}}
    codex = {1: {"duties": [_duty("build beta", "beta")]}}
    out = _build(tmp_path, opus, codex)

    assert out["counts"]["disagree"] == 1
    assert out["counts"]["queue"] == 1


def test_insufficient_context_on_one_side_only_is_a_disagreement(tmp_path):
    """One arm giving up where the other did not is exactly what a human must settle."""
    duties = [_duty("build alpha", "alpha")]
    opus = {1: {"duties": duties, "insufficient_context": True}}
    codex = {1: {"duties": duties, "insufficient_context": False}}

    assert _build(tmp_path, opus, codex)["counts"]["disagree"] == 1


def test_error_rows_are_dropped_rather_than_labelled(tmp_path):
    opus = {1: {"duties": [_duty("build alpha", "alpha")]}, 2: {"error": "schema retry"}}
    codex = {1: {"duties": [_duty("build beta", "beta")]}, 2: {"duties": []}}
    out = _build(tmp_path, opus, codex)

    assert out["counts"]["dropped_error"] == 1
    assert [r["id"] for r in out["rows"]] == [1]


def test_rows_with_nothing_to_extract_are_capped(tmp_path):
    """Both arms declaring insufficient_context cannot separate them -- and the thinness
    is a fetch defect, so grading more than a handful buys nothing."""
    thin = {"duties": [], "insufficient_context": True}
    opus = {pid: dict(thin) for pid in range(1, 16)}
    codex = {pid: dict(thin) for pid in range(1, 16)}
    out = _build(tmp_path, opus, codex, thin_keep=3)

    assert out["counts"]["dropped_thin"] == 12
    assert out["counts"]["queue"] <= 3

    # One arm alone saying it is a disagreement, and stays: that IS the signal.
    opus[1] = {"duties": [_duty("build alpha", "alpha")], "insufficient_context": False}
    kept = _build(tmp_path, opus, codex, thin_keep=0)
    assert 1 in [r["id"] for r in kept["rows"]]


def test_arm_assignment_is_blind_but_stable(tmp_path):
    """A/B must not be a fixed alias for one model, or the labeller can learn it."""
    opus = {pid: {"duties": [_duty("build alpha", "alpha")]} for pid in range(1, 41)}
    codex = {pid: {"duties": [_duty("build beta", "beta")]} for pid in range(1, 41)}
    out = _build(tmp_path, opus, codex)

    assigned = [r["arm_a"] for r in out["rows"]]
    assert set(assigned) == {"opus", "codex"}, "one model always got slot A"
    assert 8 <= assigned.count("opus") <= 32, "the flip is not close to even"

    # Stable across rebuilds: re-running the builder mid-labelling must not reshuffle
    # A/B, or answers already given would decode to the wrong model.
    again = _build(tmp_path, opus, codex)
    assert {r["id"]: r["arm_a"] for r in out["rows"]} == {r["id"]: r["arm_a"] for r in again["rows"]}


def test_alignment_pairs_by_quote_not_by_position(tmp_path):
    """The arms order their output differently; pairing by index invents disagreements."""
    a = [_duty("build alpha", "alpha"), _duty("run beta", "beta")]
    b = [_duty("run beta", "beta"), _duty("build alpha", "alpha")]

    rows = align_items(a, b)
    assert [r["status"] for r in rows] == ["same", "same"]
    assert rows[0]["a"]["label"] == rows[0]["b"]["label"] == "build alpha"


def test_an_item_only_one_arm_found_is_reported_as_such(tmp_path):
    a = [_duty("build alpha", "alpha"), _duty("audit the ledger quarterly", "alpha")]
    b = [_duty("build alpha", "alpha")]

    rows = align_items(a, b)
    assert [r["status"] for r in rows] == ["same", "only_a"]
    assert rows[1]["b"] is None          # the gap opposite it is what the sheet renders

    flipped = align_items(b, a)
    assert [r["status"] for r in flipped] == ["same", "only_b"]
    assert flipped[1]["a"] is None


def test_the_same_duty_mapped_to_different_concepts_is_flagged(tmp_path):
    a = [_duty("build alpha", "alpha")]
    b = [_duty("build alpha", "beta")]

    assert align_items(a, b)[0]["status"] == "concept_differs"


def test_rows_carry_what_the_sheet_needs_to_render(tmp_path):
    opus = {1: {"duties": [_duty("build alpha", "alpha")]}}
    codex = {1: {"duties": [_duty("build beta", "beta")]}}
    row = _build(tmp_path, opus, codex)["rows"][0]

    assert row["description"] == "jd text 1"      # no description, nothing to judge from
    assert row["job_title"] == "role 1"
    assert row["location"] == "NYC"
    assert row["a"] and row["b"]
