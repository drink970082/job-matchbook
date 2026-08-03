"""The bounded fit extraction: refs, schema, validation, evidence verification.

Three properties carry the design and each has a test that fails if it erodes:

1. The model is never shown a preference — no `kind`, no `priority`, no bonus, no
   personal profile reaches the wire.
2. The vocabulary is closed — every out-of-enum value, unknown ref, over-cap list and
   inconsistent mapping raises rather than being coerced.
3. Evidence fails asymmetrically — an invented JOB requirement is dropped and never costs
   the candidate anything, while an invented RÉSUMÉ claim is kept and marked.
"""
import json

import pytest

from ats_worker.score.errors import ScoreError
from ats_worker.score.extract import (
    MAX_DUTIES,
    batch_extraction_schema,
    concept_block,
    extraction_schema,
    extractor_system_sections,
    make_extractor,
    mint_refs,
    job_source_text,
    normalize_extraction,
    normalize_quote,
    verify_evidence,
)
from ats_worker.fit_profile import parse_fit_profile

PROFILE = parse_fit_profile({
    "priority_levels": {"one": {"rank": 1, "bonus": 10}, "none": {"rank": 99, "bonus": -12}},
    "concepts": [
        {"id": "ml_platform", "priority": "one", "description": "Building ML infrastructure."},
        {"id": "trading_tools", "priority": "one", "description": "Trading desk tooling."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."},
    ],
})
LABELS = ["swe"]
JOB = ("You will build model serving pipelines for our research team. "
       "Requires a Bachelor's degree in a quantitative field.")
RESUME = "Built an Airflow DAG that trains and serves ranking models at Acme."


def _refs():
    entries, ref_to_id = mint_refs(PROFILE, "run-1")
    return entries, ref_to_id


def _duty(ref, **over):
    item = {
        "label": "build serving pipelines",
        "importance": "core",
        "concept_mapping": {"status": "mapped", "refs": [ref]},
        "job_evidence": {"quote": "build model serving pipelines", "source": "description"},
        "resume_relations": {"swe": {
            "relation": "adjacent_match",
            "resume_evidence": {"quote": "Built an Airflow DAG", "source": "swe"}}},
    }
    item.update(over)
    return item


def _record(*duties, quals=(), nice=()):
    return {"duties": list(duties), "required_qualifications": list(quals),
            "nice_to_haves": list(nice), "summary": "a serving role",
            "insufficient_context": False}


# --- 1. the wire carries no preference --------------------------------------------

def test_refs_are_opaque_and_carry_no_preference():
    entries, ref_to_id = _refs()
    assert set(ref_to_id.values()) == {"ml_platform", "trading_tools", "frontend"}
    for entry in entries:
        assert set(entry) == {"ref", "description"}  # no kind, priority or stable id
        assert entry["ref"].startswith("c_")
        assert not any(token in entry["ref"] for token in ("ml", "front", "target", "anti"))


def test_refs_are_reproducible_per_run_and_differ_between_runs():
    """Per-RUN minting, not per-request: every call in a run shares one system prefix, so
    the cached prefix survives. Reproducible from the token so an artifact replays."""
    assert mint_refs(PROFILE, "run-1")[1] == mint_refs(PROFILE, "run-1")[1]
    assert mint_refs(PROFILE, "run-1")[1] != mint_refs(PROFILE, "run-2")[1]


def test_system_sections_omit_the_personal_profile():
    """The one rule the design turns on. If the extractor could read the operator's
    preferences it would be today's `domain` judgment with new field names."""
    entries, _ = _refs()
    text = "\n".join(extractor_system_sections(entries, {"swe": RESUME}))
    assert "=== CONCEPTS ===" in text and "=== RESUME (swe) ===" in text
    assert "PERSONAL PROFILE" not in text
    assert "priority" not in text.lower().split("=== resume")[0].replace("prioritis", "")


def test_concept_block_lists_ref_and_description_only():
    entries, ref_to_id = _refs()
    block = concept_block(entries)
    for ref, concept_id in ref_to_id.items():
        assert f"{ref}: " in block
        assert concept_id not in block


# --- 2. the vocabulary is closed --------------------------------------------------

def test_schema_pins_the_enums_and_the_minted_refs():
    entries, _ = _refs()
    refs = [e["ref"] for e in entries]
    schema = extraction_schema(refs, ["swe", "ml"])
    duty = schema["properties"]["duties"]["items"]["properties"]
    assert duty["concept_mapping"]["properties"]["refs"]["items"]["enum"] == refs
    assert set(duty["resume_relations"]["properties"]) == {"swe", "ml"}
    # Absent by design: every number is computed in code from these categories.
    assert not {"score", "confidence", "target_priority", "anti_target",
                "recommended_resume"} & set(schema["properties"])


def test_batch_schema_tags_job_ref_like_the_fit_backends():
    entries, _ = _refs()
    schema = batch_extraction_schema([e["ref"] for e in entries], LABELS)
    element = schema["properties"]["results"]["items"]
    assert element["properties"]["job_ref"] == {"type": "integer"}
    assert "job_ref" in element["required"]


def test_normalize_maps_refs_back_to_stable_concept_ids():
    entries, ref_to_id = _refs()
    ref = next(r for r, cid in ref_to_id.items() if cid == "ml_platform")
    out = normalize_extraction(_record(_duty(ref)), ref_to_id=ref_to_id, resume_labels=LABELS)
    assert out["duties"][0]["concept_mapping"] == {"status": "mapped",
                                                   "concept_ids": ["ml_platform"]}


@pytest.mark.parametrize("mutation, message", [
    ({"importance": "critical"}, "importance"),
    ({"concept_mapping": {"status": "guessed", "refs": []}}, "status"),
    ({"concept_mapping": {"status": "mapped", "refs": []}}, "'mapped' with no refs"),
    ({"resume_relations": {"swe": {"relation": "great", "resume_evidence": None}}}, "relation"),
])
def test_out_of_enum_and_inconsistent_values_raise(mutation, message):
    entries, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    with pytest.raises(ScoreError, match=message):
        normalize_extraction(_record(_duty(ref, **mutation)),
                             ref_to_id=ref_to_id, resume_labels=LABELS)


def test_status_none_may_not_carry_refs():
    entries, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    with pytest.raises(ScoreError, match="'none' but carries refs"):
        normalize_extraction(
            _record(_duty(ref, concept_mapping={"status": "none", "refs": [ref]})),
            ref_to_id=ref_to_id, resume_labels=LABELS)


def test_an_unminted_ref_raises():
    _, ref_to_id = _refs()
    with pytest.raises(ScoreError, match="not minted for this run"):
        normalize_extraction(_record(_duty("c_dead")),
                             ref_to_id=ref_to_id, resume_labels=LABELS)


def test_over_cap_lists_fail_rather_than_truncate():
    """Silent truncation would make the coverage denominator a function of how verbose
    the model felt — the cap is in the prompt and the schema, so exceeding it is a bug."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    with pytest.raises(ScoreError, match=f"over the {MAX_DUTIES} cap"):
        normalize_extraction(_record(*[_duty(ref)] * (MAX_DUTIES + 1)),
                             ref_to_id=ref_to_id, resume_labels=LABELS)


def test_every_resume_needs_its_own_relation():
    """No version may answer for another: that is what makes a composite fit score no
    single résumé earns structurally impossible rather than merely detectable."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    with pytest.raises(ScoreError, match="resume_relations.ml missing"):
        normalize_extraction(_record(_duty(ref)), ref_to_id=ref_to_id,
                             resume_labels=["swe", "ml"])


def test_a_claimed_match_owes_a_quote_and_a_miss_owes_none():
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    with pytest.raises(ScoreError, match="required for this relation"):
        normalize_extraction(
            _record(_duty(ref, resume_relations={
                "swe": {"relation": "direct_match", "resume_evidence": None}})),
            ref_to_id=ref_to_id, resume_labels=LABELS)
    out = normalize_extraction(
        _record(_duty(ref, resume_relations={
            "swe": {"relation": "missing", "resume_evidence": None}})),
        ref_to_id=ref_to_id, resume_labels=LABELS)
    assert out["duties"][0]["resume_relations"]["swe"]["resume_evidence"] is None


def test_a_missing_relation_may_not_carry_evidence():
    """`missing` asserts the résumé shows NOTHING. A quote attached to it is a
    self-contradictory record, and no rule would ever read it."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    with pytest.raises(ScoreError, match="must carry null"):
        normalize_extraction(
            _record(_duty(ref, resume_relations={"swe": {
                "relation": "missing",
                "resume_evidence": {"quote": "Built an Airflow DAG", "source": "swe"}}})),
            ref_to_id=ref_to_id, resume_labels=LABELS)


def test_absent_groups_and_non_bool_flags_raise():
    """The schema marks all three groups and the flag required, so an absent group is a
    backend ignoring the schema — not a posting with no requirements. And `bool("false")`
    is True, on a field that routes a row out of delivery."""
    _, ref_to_id = _refs()
    with pytest.raises(ScoreError, match="duties is absent"):
        normalize_extraction({"summary": "s", "insufficient_context": False},
                             ref_to_id=ref_to_id, resume_labels=LABELS)
    with pytest.raises(ScoreError, match="must be a JSON boolean"):
        normalize_extraction({**_record(), "insufficient_context": "false"},
                             ref_to_id=ref_to_id, resume_labels=LABELS)


def test_requirements_carry_a_type_and_no_concept_mapping():
    _, ref_to_id = _refs()
    qual = {"requirement": "Bachelor's degree", "requirement_type": "credential",
            "job_evidence": {"quote": "Requires a Bachelor's degree", "source": "description"},
            "resume_relations": {"swe": {"relation": "missing", "resume_evidence": None}}}
    out = normalize_extraction(_record(quals=[qual]), ref_to_id=ref_to_id,
                               resume_labels=LABELS)
    item = out["required_qualifications"][0]
    assert item["requirement_type"] == "credential" and "concept_mapping" not in item


# --- 3. evidence fails asymmetrically ---------------------------------------------

def test_quote_matching_survives_formatting_but_not_paraphrase():
    # Case, whitespace runs and a JD's mid-sentence line breaks are folded — a faithful
    # copy still has to pass, or the check only teaches the model to give up.
    assert normalize_quote("BUILD  model\nserving pipelines") in normalize_quote(JOB.upper())
    # So are the smart dashes and quotes a model substitutes while "copying verbatim".
    assert normalize_quote("real–time") == normalize_quote("real-time")
    assert normalize_quote("a ’plus’") == normalize_quote("a 'plus'")
    # Everything else must match: a paraphrase fails, which is the whole point.
    assert normalize_quote("build pipelines for serving models") not in normalize_quote(JOB)
    assert normalize_quote("build model-serving pipelines") not in normalize_quote(JOB)


def test_an_invented_job_requirement_is_dropped_never_charged():
    """A quote that is not in the posting means the model may have invented the
    requirement. Penalising the candidate for the model's invention is the worst outcome
    available here, so the item leaves the record entirely."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    record = normalize_extraction(
        _record(_duty(ref, job_evidence={"quote": "must hold a pilot licence",
                                         "source": "description"})),
        ref_to_id=ref_to_id, resume_labels=LABELS)
    out = verify_evidence(record, JOB, {"swe": RESUME})
    assert out["duties"] == []
    assert out["dropped_items"][0]["reason"] == "job_evidence_not_found"
    # Core duty / required qualification: material, because a record built on invention
    # should be re-derived rather than quietly scored.
    assert out["dropped_items"][0]["material"] is True
    assert out["evidence"]["material_job_quote_failure"] is True


def test_an_invented_resume_claim_is_kept_and_marked():
    """The mirror case, and the one a single rule gets backwards: the requirement is
    real, the claimed candidate evidence is not. It has to stay in the record and cost
    the score — that IS the invented-capability failure this design exists to catch."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    record = normalize_extraction(
        _record(_duty(ref, resume_relations={"swe": {
            "relation": "direct_match",
            "resume_evidence": {"quote": "led the Kubernetes migration", "source": "swe"}}})),
        ref_to_id=ref_to_id, resume_labels=LABELS)
    out = verify_evidence(record, JOB, {"swe": RESUME})
    relation = out["duties"][0]["resume_relations"]["swe"]
    assert relation["relation"] == "direct_match"        # untouched: the arithmetic decides
    assert relation["resume_evidence_verified"] is False
    assert out["evidence"]["resume_quote_failures"] == 1


def test_a_one_word_quote_does_not_pass_verification():
    """Being FOUND in the source is not enough. "a" is in every posting and every résumé,
    and the prompt tells the model an unmatched quote is discarded — so the cheapest way
    to survive the check would be the shortest string that survives it. The quote has to
    localize the item, which is what the word floor buys."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    record = normalize_extraction(
        _record(_duty(ref,
                      job_evidence={"quote": "a", "source": "description"},
                      resume_relations={"swe": {
                          "relation": "direct_match",
                          "resume_evidence": {"quote": "at", "source": "swe"}}})),
        ref_to_id=ref_to_id, resume_labels=LABELS)
    out = verify_evidence(record, JOB, {"swe": RESUME})
    assert out["duties"] == []
    # `too_short` is recorded distinctly from `not_found`: gaming the floor and inventing
    # a requirement are different failures and only one of them is about honesty.
    assert out["dropped_items"][0]["reason"] == "job_evidence_too_short"


def test_a_quote_from_the_title_verifies():
    """`_job_block` renders the title and company into the JOB section, so the model is
    SHOWN them. Searching only the description would record a faithful quote of a duty
    stated in the title as an invention — manufacturing the material-failure signal that
    is supposed to mean "re-derive this record"."""
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    posting = {"id": 1, "job_title": "Machine Learning Platform Engineer",
               "company_name": "Acme", "description": JOB}
    record = normalize_extraction(
        _record(_duty(ref, job_evidence={"quote": "Machine Learning Platform Engineer",
                                         "source": "title"})),
        ref_to_id=ref_to_id, resume_labels=LABELS)
    out = verify_evidence(record, job_source_text(posting), {"swe": RESUME})
    assert len(out["duties"]) == 1
    assert out["evidence"]["material_job_quote_failure"] is False


def test_a_verified_record_reports_clean_counters():
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    record = normalize_extraction(_record(_duty(ref)), ref_to_id=ref_to_id,
                                  resume_labels=LABELS)
    out = verify_evidence(record, JOB, {"swe": RESUME})
    assert out["duties"][0]["resume_relations"]["swe"]["resume_evidence_verified"] is True
    assert out["evidence"] == {"items_checked": 1, "job_quote_failures": 0,
                               "material_job_quote_failure": False,
                               "resume_quote_failures": 0}


def test_an_incidental_drop_is_not_material():
    _, ref_to_id = _refs()
    ref = next(iter(ref_to_id))
    record = normalize_extraction(
        _record(_duty(ref, importance="incidental",
                      job_evidence={"quote": "nowhere in the posting", "source": "description"})),
        ref_to_id=ref_to_id, resume_labels=LABELS)
    out = verify_evidence(record, JOB, {"swe": RESUME})
    assert out["evidence"]["material_job_quote_failure"] is False


# --- the extractor callable -------------------------------------------------------

def test_extractor_drives_the_cli_and_returns_verified_records(monkeypatch):
    entries, ref_to_id = mint_refs(PROFILE, "tok")
    ref = next(iter(ref_to_id))
    captured = {}

    def fake_codex(prompt, schema, **kwargs):
        captured["prompt"], captured["schema"] = prompt, schema
        return {"results": [{**_record(_duty(ref)), "job_ref": 7}]}

    monkeypatch.setattr("ats_worker.score.extract.codex_json", fake_codex)
    extract = make_extractor(PROFILE, "tok", backend="codex", model="m")
    out = extract([{"id": 7, "job_title": "SWE", "company_name": "Acme", "description": JOB}],
                  {"swe": RESUME})

    assert len(out) == 1 and out[0]["evidence"]["job_quote_failures"] == 0
    assert out[0]["duties"][0]["concept_mapping"]["concept_ids"] == [ref_to_id[ref]]
    assert extract.ref_to_id == ref_to_id
    # The JOB block carries no Location line — geography must never move a fit judgment.
    assert "job_ref=7" in captured["prompt"] and "Location:" not in captured["prompt"]
    assert "PERSONAL PROFILE" not in captured["prompt"]
    json.dumps(captured["schema"])  # the schema is JSON-serializable as handed to the CLI


def test_extractor_rejects_an_unknown_backend_and_an_empty_vocabulary():
    with pytest.raises(ScoreError, match="unknown extraction backend"):
        make_extractor(PROFILE, "tok", backend="ollama", model="m")
    with pytest.raises(ScoreError, match="needs a `fit_profile` block"):
        make_extractor(parse_fit_profile(None), "tok", backend="codex", model="m")


def test_extraction_is_not_wired_into_the_pipeline():
    """SHADOW IS A CORRECTNESS REQUIREMENT, not caution. The live fit response carries a
    secondary `screen` block that `merge_fallback_screen` uses to refill a check
    `demote_for_confirmation` removed; swapping in an extraction record would leave that
    refill with nothing to read and materialize a pass verdict from a blind check."""
    from pathlib import Path
    worker = Path(__file__).resolve().parents[1] / "ats_worker"
    for module in ("pipeline.py", "run.py"):
        assert "score.extract" not in (worker / module).read_text(encoding="utf-8")
