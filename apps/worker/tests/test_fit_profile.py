"""The fit vocabulary and its four provenance hashes.

The hash tests are the load-bearing half. A corpus row is only meaningful against the
inputs it was labelled under, and the whole reason there is more than one hash is that a
cheap edit must not invalidate expensive human work — so what each hash IGNORES is as
much a behavior as what it covers.
"""
import unicodedata

import pytest

from ats_worker.config import ConfigError, load_config
from ats_worker.fit_profile import (
    INVALIDATED_BY,
    MAX_DESCRIPTION_CHARS,
    FitProfile,
    concept_vocab_hash,
    parse_fit_profile,
    preference_policy_hash,
    profile_hash,
    provenance,
    resume_hash,
)

BASE = {
    "priority_levels": {"one": {"rank": 1, "bonus": 10}, "none": {"rank": 99, "bonus": -12}},
    "none_level": "none",
    "concepts": [
        {"id": "ml_platform", "priority": "one", "description": "Building ML infrastructure."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."},
    ],
}


def _profile(**overrides) -> FitProfile:
    raw = {**BASE, **overrides}
    return parse_fit_profile(raw)


def test_parses_concepts_levels_and_kinds():
    fp = _profile()
    assert [c.id for c in fp.concepts] == ["ml_platform", "frontend"]
    assert fp.by_id("ml_platform").priority == "one"
    assert fp.by_id("frontend").kind == "anti_target"
    assert fp.priority_levels["one"].bonus == 10
    assert not fp.is_empty()


def test_absent_block_is_legal_and_empty():
    assert parse_fit_profile(None).is_empty()
    assert parse_fit_profile({}).is_empty()


@pytest.mark.parametrize("mutation, message", [
    # An anti-target is not a low tier — it wins over any target the role also matches,
    # so letting it carry a priority would invite exactly that misreading.
    ({"concepts": [{"id": "a", "kind": "anti_target", "priority": "one", "description": "x"}]},
     "may not carry a target priority"),
    ({"concepts": [{"id": "a", "priority": "nope", "description": "x"}]},
     "not a declared priority level"),
    ({"concepts": [{"id": "a", "description": "x"}]}, "priority is required"),
    ({"concepts": [{"id": "A b", "priority": "one", "description": "x"}]}, "must be lowercase"),
    ({"concepts": [{"id": "a", "priority": "one", "description": "x"},
                   {"id": "a", "priority": "one", "description": "y"}]}, "duplicate"),
    ({"concepts": [{"id": "a", "priority": "one", "description": ""}]}, "non-empty string"),
    ({"concepts": [{"id": "a", "priority": "one", "description": "x", "extra": 1}]},
     "unknown key"),
    ({"none_level": "absent"}, "not a declared priority level"),
    # A vocabulary of only anti-targets can reject but never rank.
    ({"concepts": [{"id": "a", "kind": "anti_target", "description": "x"}]},
     "declares no target concepts"),
])
def test_structural_violations_fail_at_load(mutation, message):
    with pytest.raises(ConfigError, match=message):
        _profile(**mutation)


def test_anti_target_only_is_legal_with_explicit_opt_in():
    fp = parse_fit_profile({**BASE, "allow_anti_target_only": True,
                            "concepts": [{"id": "a", "kind": "anti_target", "description": "x"}]})
    assert [c.kind for c in fp.concepts] == ["anti_target"]


def test_description_length_is_bounded():
    with pytest.raises(ConfigError, match="over the"):
        _profile(concepts=[{"id": "a", "priority": "one",
                            "description": "x" * (MAX_DESCRIPTION_CHARS + 1)}])


def test_concept_count_warns_then_fails():
    many = [{"id": f"c{i}", "priority": "one", "description": "x"} for i in range(6)]
    warned = parse_fit_profile({**BASE, "concepts": many, "warn_concepts": 3})
    assert warned.warnings and "6 concepts" in warned.warnings[0]
    with pytest.raises(ConfigError, match="above max_concepts"):
        parse_fit_profile({**BASE, "concepts": many, "max_concepts": 3})


def test_the_warning_fires_ON_the_threshold_not_only_past_it():
    """`warn_concepts` is documented as "warn at ~20". With a strict `>` the warning is
    unreachable for anyone who read the default as a target and wrote exactly 20."""
    six = [{"id": f"c{i}", "priority": "one", "description": "x"} for i in range(6)]
    assert parse_fit_profile({**BASE, "concepts": six, "warn_concepts": 6}).warnings
    assert not parse_fit_profile({**BASE, "concepts": six, "warn_concepts": 7}).warnings


@pytest.mark.parametrize("key", ["max_concepts", "warn_concepts"])
def test_the_ceilings_raise_configerror_rather_than_coercing(key):
    """`config._int_field` exists so a typo is a startup error naming the key, not a bare
    ValueError. And `0` has to be a real value: read through `or`, `max_concepts: 0` would
    silently mean 40."""
    with pytest.raises(ConfigError, match=f"{key} must be an integer"):
        _profile(**{key: "lots"})
    with pytest.raises(ConfigError, match=f"{key} must be >= 1"):
        _profile(**{key: 0})


def test_load_config_carries_the_block():
    cfg = load_config("""
fit_profile:
  priority_levels:
    one: {rank: 1, bonus: 5}
    none: {rank: 99, bonus: -5}
  concepts:
    - {id: a, priority: one, description: "Some work."}
""")
    assert [c.id for c in cfg.fit_profile.concepts] == ["a"]


# --- hashes -----------------------------------------------------------------------

def test_vocab_hash_ignores_preference_and_ordering():
    """The model is shown ids and descriptions ONLY. Re-tagging a target as an
    anti-target, re-ranking it, or reordering the list changes not one extracted duty —
    so it must not invalidate the human-labelled extraction layer."""
    base = _profile()
    retagged = _profile(allow_anti_target_only=True, concepts=[
        {"id": "ml_platform", "kind": "anti_target", "description": "Building ML infrastructure."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    reordered = _profile(concepts=list(reversed(BASE["concepts"])))
    rebonused = _profile(priority_levels={"one": {"rank": 1, "bonus": 99},
                                          "none": {"rank": 99, "bonus": -12}})
    assert concept_vocab_hash(base) == concept_vocab_hash(retagged)
    assert concept_vocab_hash(base) == concept_vocab_hash(reordered)
    assert concept_vocab_hash(base) == concept_vocab_hash(rebonused)


def test_vocab_hash_moves_when_the_model_would_see_something_new():
    edited = _profile(concepts=[
        {"id": "ml_platform", "priority": "one", "description": "Building ML infra AND serving."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    renamed = _profile(concepts=[
        {"id": "ml_infra", "priority": "one", "description": "Building ML infrastructure."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    assert concept_vocab_hash(_profile()) != concept_vocab_hash(edited)
    assert concept_vocab_hash(_profile()) != concept_vocab_hash(renamed)


def test_reflowing_the_yaml_does_not_invalidate_a_corpus():
    """Canonicalization, not cosmetics: a wrapped description is the same description,
    and a corpus that expires on a line break is a corpus nobody dares reformat."""
    wrapped = _profile(concepts=[
        {"id": "ml_platform", "priority": "one",
         "description": "Building   ML\n  infrastructure."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    assert concept_vocab_hash(_profile()) == concept_vocab_hash(wrapped)


def test_policy_hash_covers_preference_and_not_wording():
    base = _profile()
    retagged = _profile(allow_anti_target_only=True, concepts=[
        {"id": "ml_platform", "kind": "anti_target", "description": "Building ML infrastructure."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    rebonused = _profile(priority_levels={"one": {"rank": 1, "bonus": 99},
                                          "none": {"rank": 99, "bonus": -12}})
    reworded = _profile(concepts=[
        {"id": "ml_platform", "priority": "one", "description": "Totally different words."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    assert preference_policy_hash(base) != preference_policy_hash(retagged)
    assert preference_policy_hash(base) != preference_policy_hash(rebonused)
    assert preference_policy_hash(base) == preference_policy_hash(reworded)


def test_profile_and_resume_hashes_are_content_addressed():
    assert profile_hash("a  b") == profile_hash(" a b ")
    assert profile_hash("a b") != profile_hash("a c")
    assert resume_hash({"swe": "x"}) != resume_hash({"swe": "y"})
    assert resume_hash({"swe": "x"}) != resume_hash({"ml": "x"})  # the label is content


def test_a_unicode_reencoding_does_not_expire_a_corpus():
    """NFKC as well as whitespace: a copy-paste that swaps a composed accent for a
    decomposed one is not a content change, and a corpus that dies on it dies silently."""
    composed = _profile(concepts=[
        {"id": "ml_platform", "priority": "one", "description": "Café systems."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    decomposed = _profile(concepts=[
        {"id": "ml_platform", "priority": "one", "description": "Café systems."},
        {"id": "frontend", "kind": "anti_target", "description": "Client UI work."}])
    assert concept_vocab_hash(composed) == concept_vocab_hash(decomposed)


def test_each_layer_names_the_hashes_that_invalidate_it():
    """Stamping all four on a row is right; comparing all four is not. A currency check
    demanding every hash match would expire the expensive model-extraction layer the
    moment the operator edits their preference document — the over-coarse invalidation
    the split exists to prevent."""
    assert "profile_hash" not in INVALIDATED_BY["extraction"]
    assert "preference_policy_hash" not in INVALIDATED_BY["extraction"]
    assert set(INVALIDATED_BY["extraction"]) == {"concept_vocab_hash", "resume_hash"}
    stamp = provenance(_profile(), profile_text="p", resumes={"swe": "r"})
    for names in INVALIDATED_BY.values():
        assert set(names) <= set(stamp)


def test_provenance_carries_four_named_hashes():
    stamp = provenance(_profile(), profile_text="p", resumes={"swe": "r"})
    assert set(stamp) == {"concept_vocab_hash", "preference_policy_hash",
                          "profile_hash", "resume_hash"}
    assert all(len(v) == 16 for v in stamp.values())
