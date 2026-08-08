"""Frame composition — the one part of `tools/pick_frame.py` that can be silently wrong.

Everything else there is I/O. The allocation is where a corpus quietly ends up 15 keep /
54 near / 2 skip: no error, no empty file, just a gate that can detect improvements and
not regressions. It is worth a test even though the rest of `tools/` has none.
"""
import random

from tools.pick_frame import THIN_JD_MAX, _allocate, _draw, _stratum


def _row(i, *, company="acme", length=4000):
    return {"id": i, "company_name": company, "length": length}


def test_allocation_is_balanced_not_proportional():
    """Proportional sampling reproduces the backlog — 42% mismatch, 6% match — and spends
    the human budget on the easy majority. Balanced gives every cell the same share."""
    quotas = _allocate({"match/match": 30, "mismatch/too_junior": 211}, 100)
    assert quotas["match/match"] == 30      # take-all: the cell is smaller than its share
    assert quotas["mismatch/too_junior"] == 70   # the remainder, not 211/241 of the frame
    assert sum(quotas.values()) == 100


def test_a_small_stratum_gives_its_leftover_back():
    quotas = _allocate({"a": 2, "b": 2, "c": 500}, 60)
    assert quotas == {"a": 2, "b": 2, "c": 56}


def test_allocation_stops_at_the_population():
    quotas = _allocate({"a": 3, "b": 4}, 100)
    assert quotas == {"a": 3, "b": 4}
    assert _allocate({}, 50) == {}


def test_empty_strata_are_skipped_without_looping():
    assert _allocate({"a": 0, "b": 10}, 5) == {"a": 0, "b": 5}


def test_stratum_names_the_cell_including_the_holes():
    assert _stratum({"length": 5000, "domain": "match", "seniority": "too_junior"}) \
        == "match/too_junior"
    # Never scored is a CELL, not a hole: it is the majority of the backlog.
    assert _stratum({"length": 5000, "domain": None, "seniority": None}) == "unscored"
    # And the thin cell is deliberate — `insufficient_context` must be able to fail.
    assert _stratum({"length": THIN_JD_MAX - 1, "domain": "match",
                     "seniority": "match"}) == "thin_jd"


def test_draw_spreads_across_companies_and_lengths():
    rows = [_row(i, company=f"c{i // 10}", length=500 + (i % 4) * 2500) for i in range(60)]
    picked = _draw(rows, 12, 3, random.Random("seed"))
    assert len(picked) == 12
    counts = {}
    for row in picked:
        counts[row["company_name"]] = counts.get(row["company_name"], 0) + 1
    assert max(counts.values()) <= 3
    assert len({500 + (row["id"] % 4) * 2500 for row in picked}) > 1


def test_the_company_cap_never_shrinks_a_stratum():
    """A cap that cannot be met must yield a concentrated cell that the report names,
    not a quota quietly missed — a short stratum is invisible, a concentrated one isn't."""
    rows = [_row(i, company="one-employer") for i in range(20)]
    assert len(_draw(rows, 10, 3, random.Random("seed"))) == 10
