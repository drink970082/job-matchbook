"""Cheap metadata pre-filter for feed listings, run BEFORE any JD fetch/score.

A discovery feed is a firehose (~18k Simplify listings). The feed hands us
structured metadata for free, so we drop the obvious non-matches here — for
pennies, before spending a board fetch or an LLM score on them.

Hybrid posture (the semantic calls stay with the LLM scorer):
  - active:      keep only live postings (most of the firehose is filled/expired).
  - category:    keep only the role families you want (drops Product / Hardware).
  - sponsorship: drop ONLY when the feed EXPLICITLY says no sponsorship /
                 citizenship-required. Blanks ("Other", ~99% of rows) are kept —
                 the LLM `candidate` screen judges sponsorship from the JD.
"""
from __future__ import annotations

# Feed sponsorship labels that are an explicit hard "no" for a visa candidate.
# Everything else (notably the blank "Other") is left for the LLM screen.
_NO_SPONSORSHIP = frozenset({
    "Does Not Offer Sponsorship",
    "U.S. Citizenship is Required",
})


def prefilter(listings, keep_categories) -> list[dict]:
    """Keep listings that are active, in `keep_categories`, and not explicitly
    no-sponsorship. Pure, no I/O."""
    keep = set(keep_categories or [])
    out: list[dict] = []
    for x in listings:
        if not x.get("active"):
            continue
        if x.get("category") not in keep:
            continue
        if x.get("sponsorship") in _NO_SPONSORSHIP:
            continue
        out.append(x)
    return out
