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


def test_the_veto_can_only_ever_lower_or_remove_a_bar():
    assert seniority.clamp_years(5, "at least 2 years") == 2
    assert seniority.clamp_years(1, "at least 4 years") == 1   # already lower, untouched
    assert seniority.clamp_years(None, "3 years") is None
    # CHANGED 2026-07-31, and the old assertion was `== 7`. A years bar the posting never
    # states is a bar with no evidence behind it — exactly what `rank_stated_in` has
    # refused on the rank path since the vetoes landed, while this path silently accepted
    # it. Still keep-direction: it can only ever remove a demotion.
    assert seniority.clamp_years(7, "no years mentioned") is None


def test_a_capped_or_age_figure_is_not_a_bar():
    # SCORING §4.2 says a cap is entry/early-career and NOT a stated bar; the regex was
    # collecting it anyway, so *"Less than 2 years"* read as a 2-year FLOOR and demoted a
    # posting written for exactly this candidate (T-Mobile `Assoc Engineer, Software`).
    assert seniority.stated_years("Less than 2 years technical experience") == set()
    assert seniority.stated_years("up to 5 years of experience") == set()
    assert seniority.stated_years("no more than 3 years") == set()
    # an AGE is not experience — the same posting also said "At least 18 years of age"
    assert seniority.stated_years("must be at least 18 years of age") == set()
    # a real floor in the same text still counts
    assert seniority.stated_years("Less than 2 years preferred; 4 years required") == {4}
    # and the verdict follows: a capped figure no longer manufactures a demotion
    assert seniority.verdict({"stated_min_years": 2},
                             job_text="Less than 2 years technical experience") == "match"


def test_a_clamped_bar_does_not_cancel_a_rank_the_posting_states():
    # The compounding bug: the model reads a real 5-year bar on a "Senior ..." posting, a
    # stray "1 year of experience with X" in the preferred qualifications clamps it to 1,
    # and the clamped value then cancels the rank — keeping the row as if it were open to
    # a new grad. A keep-direction correction applied twice. 34 of 61 misses.
    jd = ("Senior Fabric Design Verification Engineer\n"
          "5+ years of design verification experience required.\n"
          "Preferred: 1 year of experience with formal methods.")
    assert seniority.clamp_years(5, jd) == 1          # the clamp itself is unchanged
    assert seniority.verdict({"stated_min_years": 5, "stated_rank": "senior"},
                             job_text=jd) == "too_junior"
    # a figure the candidate genuinely clears still beats the rank word (veto (b) intact)
    open_jd = "Senior Engineer\nWe welcome candidates with 0-2 years of experience."
    assert seniority.verdict({"stated_min_years": 0, "stated_rank": "senior"},
                             job_text=open_jd) == "match"


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
    # job_text must CONTAIN the rank word -- the veto below is what makes that
    # necessary, and an empty JD is exactly the invented-rank case it refuses.
    for rank in seniority.RANKS:
        jd = f"We are hiring a {rank.title()} Engineer."
        assert seniority.verdict({"stated_rank": rank}, job_text=jd) == "too_junior"
        assert seniority.verdict({"stated_rank": rank}, job_text=jd,
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


def test_an_invented_rank_the_posting_never_names_is_vetoed():
    # The rank path's half of the keep-direction veto. Without it a rank the model
    # supplied from nowhere demotes a row with no evidence at all, while the years path
    # is vetoed -- an asymmetry the pre-merge review found.
    assert seniority.verdict({"stated_rank": "principal"},
                             job_text="Junior Analyst, no experience needed.") == "match"
    assert seniority.verdict({"stated_rank": "staff"},
                             job_text="We are hiring a Staff Engineer.") == "too_junior"
    # It cannot fix mis-ATTRIBUTION, and the docstring says so: the word is present here.
    assert seniority.verdict({"stated_rank": "senior"},
                             job_text="New Grad Engineer. You will work with senior "
                                      "engineers.") == "too_junior"


def test_a_stated_years_figure_the_candidate_clears_beats_a_rank_word():
    # "Senior Engineer ... 0-2 years of experience" says outright it will take this
    # candidate. The years figure is the vetoed, evidence-grounded signal; the rank
    # is not, so the number wins.
    assert seniority.verdict({"stated_min_years": 0, "stated_rank": "senior"},
                             job_text="Senior Engineer. 0 years required.") == "match"
    assert seniority.verdict({"stated_min_years": 1, "stated_rank": "lead"},
                             job_text="Lead Engineer, 1 year of experience.") == "match"
    # but a number ABOVE the bar still demotes, rank or no rank
    assert seniority.verdict({"stated_min_years": 6, "stated_rank": "senior"},
                             job_text="Senior Engineer, 6 years.") == "too_junior"


def test_a_non_finite_years_value_cannot_take_the_pass_down():
    # json.loads accepts NaN/Infinity and int() raises on both. assess()'s try covers
    # only the extract call, so an unguarded int() here aborted the whole pass.
    assert seniority.normalize({"stated_min_years": float("nan")}) == (None, None)
    assert seniority.normalize({"stated_min_years": float("inf")}) == (None, None)
    assert seniority.normalize({"stated_min_years": 10**9}) == (None, None)
