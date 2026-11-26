"""The candidate profile (#224): derived fields, row validation, the one-time seed."""
from __future__ import annotations

import json

import pytest

from ats_worker import config as cfgmod
from ats_worker import jev, profile
from ats_worker.screening.engine import _degree_rank
from tests._helpers import FIXTURES

CASES = json.loads((FIXTURES / "candidate-profile-cases.json").read_text())


@pytest.mark.parametrize("case", CASES["derived"], ids=lambda c: c["name"])
def test_derived_fields_match_the_shared_fixture(case):
    assert profile.highest_degree(case["education"]) == case["highest_degree"]
    assert profile.total_years(case["experience"]) == case["total_years"]


@pytest.mark.parametrize("case", CASES["setup"], ids=lambda c: c["name"])
def test_setup_steps_match_the_shared_fixture(case):
    from ats_worker.mcp.read_repository import setup_steps
    assert setup_steps(case["row"], sources=case["sources"],
                       has_posting=case["has_posting"]) == case["steps"]


@pytest.mark.parametrize("case", CASES["invalid"], ids=lambda c: c["name"])
def test_from_row_refuses_what_the_web_refuses(case):
    value = case["value"] if isinstance(case["value"], str) else json.dumps(case["value"])
    with pytest.raises(profile.ProfileError, match=case["error"]):
        profile.from_row({case["field"]: value})


def test_degree_vocabulary_is_the_screen_ranking():
    # The derived degree is compared by the screen's own matcher, so every DEGREES value
    # must rank at its position; the web offers the same list (constants.ts DEGREES).
    assert [_degree_rank(d) for d in profile.DEGREES] == list(range(len(profile.DEGREES)))
    assert list(profile.DEGREES) == CASES["degrees"]


def test_screen_candidate_is_none_until_a_requirement_is_set():
    assert profile.CandidateProfile(target_roles=("x",), title_include=("eng",)).screen_candidate() is None
    cand = profile.from_row({"education": '[{"degree":"master\'s","field":""}]'}).screen_candidate()
    assert cand == {"highest_degree": "master's", "work_authorization": "", "security_clearance": "",
                    "locations": [], "exclude_internships": False, "exclude_contract": False}


def test_triage_needs_a_target_role_or_a_custom_context():
    assert profile.CandidateProfile(locations=("USA",)).triage_texts() is None
    custom = profile.CandidateProfile(custom_triage_context={"profile_text": "{}", "yoe_context": "c"})
    assert custom.triage_texts()["profile_text"] == "{}"


@pytest.mark.parametrize("raw,canon", [("", ""), ("BS Computer Science", "none"),
                                       ("Bachelor's", "bachelor's"), ("M.S.", "none"),
                                       ("Master of Science", "master's"), ("PhD", "phd"),
                                       ("none", "none")])
def test_canonical_degree_keeps_the_screen_rank(raw, canon):
    assert profile.canonical_degree(raw) == canon
    if raw:
        assert _degree_rank(canon) == _degree_rank(raw)


def test_render_matches_the_206_form_bytes():
    # The exact bytes apps/web renderJevProfile wrote (#206) for the same form.
    p = profile.CandidateProfile(target_roles=("Backend",), open_to=(), not_interested=("Sales",),
                                 education=({"degree": "master's", "field": "CS"},),
                                 experience=({"title": "SWE", "company": "Acme", "years": 2.0},))
    out = profile.render_triage_context(p)
    assert out["profile_text"] == (
        '{\n  "target_roles": [\n    "Backend"\n  ],\n  "open_to": [],\n  "not_interested": [\n'
        '    "Sales"\n  ],\n  "education": [\n    {\n      "degree": "master\'s",\n      "field": "CS"\n'
        '    }\n  ],\n  "experience": [\n    {\n      "title": "SWE",\n      "company": "Acme",\n'
        '      "years": 2\n    }\n  ]\n}')
    assert out["yoe_context"] == ("Education: master's in CS.\nExperience: SWE at Acme, 2 years.\n"
                                  "Total years of experience: 2.")


def test_seed_from_an_empty_config_is_nothing():
    assert profile.seed_values(cfgmod.Config()) is None


def test_seed_from_config_takes_scope_and_candidate():
    cfg = cfgmod.load_config("title_filter: [engineer]\ntitle_exclude: [sales]\nmax_age_days: 9\n"
                             "candidate: {highest_degree: \"Master's\", locations: [USA]}\n")
    p = profile.from_row(profile.seed_values(cfg))
    assert (p.title_include, p.title_exclude, p.max_age_days) == (("engineer",), ("sales",), 9)
    assert p.education == ({"degree": "master's", "field": ""},) and p.locations == ("USA",)
    assert p.triage_texts() is None and p.custom_packs is None


def _form_texts(**over):
    form = {"target_roles": ["Backend"], "open_to": [], "not_interested": [],
            "education": [{"degree": "master's", "field": "CS"}],
            "experience": [{"title": "SWE", "company": "Acme", "years": 2}]}
    form.update(over)
    p = profile.CandidateProfile(**{k: tuple(v) for k, v in form.items()})
    defaults = profile.default_packs()
    return {**profile.render_triage_context(p), "c_pack": defaults["preference_pack"],
            "yoe_pack": defaults["yoe_pack"]}


def test_a_form_written_jev_profile_migrates_to_fields_with_the_same_policy():
    texts = _form_texts()
    values = profile.seed_values(cfgmod.Config(), preferences={
        "highest_degree": "Master's", "work_authorization": "", "security_clearance": "",
        "locations": "[]", "exclude_internships": 0, "exclude_contract": 0}, jev_texts=texts)
    p = profile.from_row(values)
    assert p.custom_triage_context is None and p.custom_packs is None
    assert p.target_roles == ("Backend",) and p.total_years == 2
    assert (jev.inputs_from_texts(p.triage_texts()).policy_sha("m")
            == jev.inputs_from_texts(texts).policy_sha("m"))


def test_a_form_profile_whose_degree_disagrees_keeps_the_screen_degree_and_verbatim_text():
    texts = _form_texts(education=[{"degree": "phd", "field": ""}])
    values = profile.seed_values(cfgmod.Config(), preferences={
        "highest_degree": "Bachelor's", "work_authorization": "", "security_clearance": "",
        "locations": "[]", "exclude_internships": 0, "exclude_contract": 0}, jev_texts=texts)
    p = profile.from_row(values)
    assert p.highest_degree == "bachelor's"            # the screen decides as before
    assert p.custom_triage_context == {"profile_text": texts["profile_text"],
                                       "yoe_context": texts["yoe_context"]}


def test_a_blank_legacy_degree_leaves_degree_unscreened():
    values = profile.seed_values(cfgmod.Config(), preferences={
        "highest_degree": "", "work_authorization": "citizen", "security_clearance": "",
        "locations": '["USA"]', "exclude_internships": 0, "exclude_contract": 0},
        jev_texts=_form_texts())
    p = profile.from_row(values)
    assert p.education == () and p.screen_candidate()["highest_degree"] == ""


def test_config_drift_names_only_set_keys_that_differ():
    stored = profile.from_row(profile.seed_values(cfgmod.load_config("title_filter: [eng]\n")))
    assert profile.config_drift(cfgmod.Config(), stored) == []
    assert profile.config_drift(cfgmod.load_config("title_filter: [eng]\n"), stored) == []
    assert profile.config_drift(cfgmod.load_config(
        "title_filter: [dev]\nmax_age_days: 3\njev_dir: /x\ncandidate: {locations: [USA]}\n"),
        stored) == ["title_filter", "max_age_days", "candidate", "jev_dir"]


@pytest.mark.parametrize("column,value,message", [
    ("education", "not json", "not valid JSON"),
    ("education", '{"degree": "phd"}', "list of objects"),
    ("experience", '[{"years": "2"}]', "years"),
    ("custom_packs", '{"preference_pack": 1}', "custom_packs"),
    ("custom_triage_context", '{"profile_text": "x"}', "custom_triage_context"),
])
def test_from_row_refuses_malformed_json_columns(column, value, message):
    with pytest.raises(profile.ProfileError, match=message):
        profile.from_row({column: value})
