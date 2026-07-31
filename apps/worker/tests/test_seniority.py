"""The FREE seniority pre-ordering layer: the model EXTRACTS, code DECIDES.

Every test here is about that split. The model's job is to report what the posting
literally states; every pass/fail call, every clamp and every fallback is code's, so
each is asserted directly rather than through a fake model's answer.
"""
from __future__ import annotations

import pytest

from ats_worker.score import seniority

JOB = {"job_title": "Software Engineer", "company_name": "Acme",
       "description": "Build things. 5+ years of experience required."}


# --- what the model is allowed to say -------------------------------------

def test_the_closed_vocabulary_is_enforced_in_code_not_trusted_from_the_model():
    # A rank outside the four is not a bar, however confidently it comes back.
    for rank in ("manager", "director", "vp", "junior", "associate", "mid-level", ""):
        assert seniority.normalize({"stated_rank": rank}) == (None, None)
    for rank in seniority.RANKS:
        assert seniority.normalize({"stated_rank": rank.upper()}) == (None, rank)


def test_a_years_value_is_coerced_and_a_bool_is_not_a_number():
    assert seniority.normalize({"stated_min_years": "at least 3"}) == (3, None)
    assert seniority.normalize({"stated_min_years": 4.0}) == (4, None)
    assert seniority.normalize({"stated_min_years": True}) == (None, None)
    assert seniority.normalize({"stated_min_years": None}) == (None, None)
    assert seniority.normalize("not a dict") == (None, None)


def test_both_the_wrapped_and_the_flat_response_shape_are_verdicts():
    # The 4B drops the "screen" wrapper on ~1 call in 100 while returning a complete
    # answer; discarding those is the defect #48 fixed on the screen path.
    entry = {"stated_rank": "lead"}
    assert seniority.read_entry({"screen": {"seniority": entry}}) == entry
    assert seniority.read_entry({"seniority": entry}) == entry
    assert seniority.read_entry({"screen": {}}) is None
    assert seniority.read_entry("nonsense") is None


# --- the keep-direction veto ----------------------------------------------

def test_the_veto_clamps_down_to_the_smallest_years_figure_the_jd_states():
    # The dominant error, repeating verbatim from the degree fix: on a degree-conditional
    # ladder the model reports one rung instead of the minimum across rungs.
    ladder = "Master's and no experience; or Bachelor's and 3 years of experience."
    assert seniority.stated_years(ladder) == {3}
    assert seniority.clamp_years(3, ladder) == 3

    both = "PhD and 0 years, or Master's and 2 years, or Bachelor's and 5 years."
    assert seniority.clamp_years(5, both) == 0        # the minimum across rungs


def test_the_veto_can_only_ever_lower_a_bar():
    assert seniority.clamp_years(5, "at least 2 years") == 2
    assert seniority.clamp_years(1, "at least 4 years") == 1   # already lower, untouched
    assert seniority.clamp_years(7, "no years mentioned") == 7  # nothing to clamp to
    assert seniority.clamp_years(None, "3 years") is None


@pytest.mark.parametrize("text,expected", [
    ("5+ years", 5), ("minimum of 3 years", 3), ("at least 2 yrs", 2),
    ("three (3) years", 3), ("two to four years", 2), ("1-3 years", 1),
    ("8 YOE", 8), ("fifteen years", 15),
])
def test_the_literal_years_scan_reads_the_forms_real_jds_use(text, expected):
    assert min(seniority.stated_years(text)) == expected


# --- the decision, which is code's --------------------------------------

def test_a_stated_bar_above_the_candidates_experience_demotes():
    assert seniority.verdict({"stated_min_years": 5}, job_text="5 years") == "too_junior"
    assert seniority.verdict({"stated_min_years": 2}, job_text="2 years") == "too_junior"
    # ... and one at or below their level does not
    assert seniority.verdict({"stated_min_years": 1}, job_text="1 year") == "match"
    assert seniority.verdict({"stated_min_years": 0}, job_text="0 years") == "match"


def test_a_named_rank_demotes_unless_the_candidate_is_themselves_senior():
    for rank in seniority.RANKS:
        assert seniority.verdict({"stated_rank": rank}, job_text="") == "too_junior"
        assert seniority.verdict({"stated_rank": rank}, job_text="",
                                 years_experience=seniority.SENIOR_YEARS) == "match"


def test_the_bar_moves_with_the_candidates_own_experience():
    entry = {"stated_min_years": 6}
    assert seniority.verdict(entry, job_text="6 years", years_experience=0) == "too_junior"
    assert seniority.verdict(entry, job_text="6 years", years_experience=4) == "too_junior"
    assert seniority.verdict(entry, job_text="6 years", years_experience=5) == "match"


def test_silence_is_a_keep():
    # PRINCIPLES' uncertainty policy: this layer errs toward keep, always. A blind
    # response, an empty object and a posting that states no bar all mean "spend the
    # paid call" -- the cost of a wrong keep is one call, of a wrong demote a delay.
    for entry in (None, {}, {"stated_min_years": None, "stated_rank": None}):
        assert seniority.verdict(entry, job_text=JOB["description"]) == "match"


# --- the injected seam -----------------------------------------------------

def test_assess_runs_the_injected_extraction_and_reports_what_it_read():
    calls = []

    def extract(prompt, schema):
        calls.append(prompt)
        return {"screen": {"seniority": {"stated_min_years": 9, "stated_rank": "staff"}}}

    got, detail = seniority.assess(JOB, extract)
    assert got == "too_junior"
    assert detail == {"stated_min_years": 9, "stated_rank": "staff",
                      "clamped_min_years": 5}      # clamped to the JD's own "5+ years"
    assert JOB["description"] in calls[0] and "seniority" in calls[0]


def test_a_provider_failure_is_a_keep_and_says_which():
    def extract(prompt, schema):
        raise RuntimeError("ollama is down")

    got, detail = seniority.assess(JOB, extract)
    assert got == "match"                        # err toward keep, never toward demote
    assert "RuntimeError" in detail["error"]


def test_a_blind_response_is_flagged_and_still_kept():
    got, detail = seniority.assess(JOB, lambda prompt, schema: {"screen": {}})
    assert got == "match"
    assert detail["blind"] is True
