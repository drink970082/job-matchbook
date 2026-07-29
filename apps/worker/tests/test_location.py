"""The location gate's own tier: `resolve_location` / `location_verdict` unit cases, plus
the committed live corpus that gates the one-directional invariant.

Screen-level wiring (does the gate reach `screen_posting`, does it cost an Ollama call)
stays in `test_score.py` — this file tests the resolver, not its callers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ats_worker import score
from ats_worker.score import location as loc

ALLOWED = ["remote", "USA"]   # frozen: the corpus was measured under exactly this


# --- the committed live corpus -------------------------------------------
#
# Labels come from an INDEPENDENT oracle, never from resolve_location — see the
# fixture's `_readme`. A corpus labeled by the code under test only asserts that the
# code agrees with itself.

CORPUS_PATH = Path(__file__).parent / "fixtures" / "location_corpus.jsonl"

# Rows the gate still keeps despite the oracle naming only foreign countries. PINNED
# EXACTLY, not `<=`: this is the size of an accepted trade, and it must not drift in
# either direction unnoticed. An unexplained IMPROVEMENT matters too — on this gate,
# "more aggressive" is the dangerous direction.
#
# Every one is the same shape: a foreign country IS named, but an ambiguous token also
# reads as a US city ("Central" in Singapore, "Geneva" in Switzerland, "Ontario" in
# Canada), and allowed evidence keeps whatever tier found it. Tightening that rule is
# what would let "New York City, London, Singapore" discard, so the leak is the price of
# the invariant, deliberately paid.
LEAK_CEILING_STRINGS = 6
LEAK_CEILING_ROWS = 14


def _corpus():
    rows = []
    with open(CORPUS_PATH, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if "_readme" in row:
                continue
            rows.append(row)
    return rows


def test_the_corpus_is_labeled_the_way_the_gate_assumes():
    rows = _corpus()
    assert len(rows) > 1500, "corpus looks truncated"
    assert {r["expect"] for r in rows} == {"keep", "discard", "either"}
    assert all(r["n"] >= 1 for r in rows)
    assert len({r["s"] for r in rows}) == len(rows), "duplicate location strings"
    # The oracle's two decidable labels must actually be decidable.
    assert all(r["us"] and not r["foreign"] for r in rows if r["expect"] == "keep")
    assert all(r["foreign"] and not r["us"] for r in rows if r["expect"] == "discard")


def test_no_us_eligible_string_is_ever_discarded():
    """THE gate. Zero tolerance, no `<=`.

    A discarded posting is reviewed by nobody; a leaked one costs a single paid fit call
    and still reaches the human. That asymmetry is why the whole gate errs toward keep,
    and it is the one property that must survive every future widening of the resolver.
    """
    offenders = [(r["s"], r["n"], score.resolve_location(r["s"], ALLOWED)[1])
                 for r in _corpus() if r["expect"] == "keep"
                 and not score.resolve_location(r["s"], ALLOWED)[0]]
    assert not offenders, (
        f"{sum(n for _, n, _ in offenders)} live rows would be silently deleted: "
        f"{offenders[:10]}")


def test_the_leak_set_is_pinned_exactly():
    leaks = [(r["s"], r["n"]) for r in _corpus() if r["expect"] == "discard"
             and score.resolve_location(r["s"], ALLOWED)[0]]
    rows = sum(n for _, n in leaks)
    assert (len(leaks), rows) == (LEAK_CEILING_STRINGS, LEAK_CEILING_ROWS), (
        f"leak set moved to {len(leaks)} strings / {rows} rows: {sorted(leaks)}")


def test_a_discard_always_names_a_country_the_string_actually_mentions():
    """The APAC->Uganda class, as a corpus-wide invariant rather than one table row: a
    right verdict under a WRONG country name is still a bug in the audit trail.

    Scoped to SINGLE-TOKEN strings, which is where the claim is well founded. On a
    multi-token string the oracle sees only full country names while the gate also reads
    cities, so "London, Montreal, Singapore" legitimately names the United Kingdom where
    the oracle recorded only Singapore — a disagreement about which of several real
    countries to name first, not a wrong one."""
    import pycountry
    wrong = []
    for r in _corpus():
        if r["expect"] != "discard" or len(r["foreign"]) != 1:
            continue
        if len(loc._tokenize(r["s"])) != 1:
            continue
        keep, note = score.resolve_location(r["s"], ALLOWED)
        if keep:
            continue
        want = pycountry.countries.get(alpha_2=r["foreign"][0])
        if want and want.name not in note:
            wrong.append((r["s"], note, want.name))
    assert not wrong, f"discard reason names the wrong country: {wrong[:10]}"


# --- unit table ----------------------------------------------------------

@pytest.mark.parametrize("location,allowed,want_keep,want_note", [
    # --- 2026-07-30 rebuild. The 2026-07-29 survey (9,633 rows / 1,611 distinct strings)
    # measured 317 rows kept that were clearly non-US, against a CLEAN discard side (0
    # false discards). Each block below is one of the nine failure classes it named, with
    # the string that actually leaked and the row count it cost.

    # (1) informal country names — 116 rows. pycountry knows "GB", not "UK"; the alias
    # table existed but was consulted only for the ALLOWED list, never for a token.
    ("UK", ["remote", "USA"], False, "on-site in United Kingdom"),
    ("LDN", ["remote", "USA"], False, "on-site in United Kingdom"),
    ("Great Britain - London", ["remote", "USA"], False, "on-site in United Kingdom"),
    ("Edinburgh, Scotland", ["remote", "USA"], False, "on-site in United Kingdom"),
    ("Dubai, UAE", ["remote", "USA"], False, "on-site in United Arab Emirates"),
    # ...and the same table fixes the mirror bug: an operator who allows "UK" used to get
    # allowed_codes {"US"} and had every UK role discarded.
    ("London", ["UK", "USA"], True, ""),

    # (2) the remote hint fired BEFORE any country resolved — 85 rows.
    ("Remote - India", ["remote", "USA"], False, "on-site in India"),
    ("Remote - Canada", ["remote", "USA"], False, "on-site in Canada"),
    ("France, Remote", ["remote", "USA"], False, "on-site in France"),
    ("Remote - US", ["remote", "USA"], True, "remote"),
    ("Remote", ["remote", "USA"], True, "remote"),

    # (3) US-namesake collision — 53 rows. `Ontario` resolved to Ontario, California.
    ("Toronto, Ontario, CAN", ["remote", "USA"], False, "on-site in Canada"),
    ("Toronto, Ontario", ["remote", "USA"], False, "on-site in Canada"),
    ("Ottawa, Ontario, Canada", ["remote", "USA"], False, "on-site in Canada"),
    ("Ontario, CA", ["remote", "USA"], True, ""),   # ...and Ontario, California still keeps

    # (4) diacritics — 32 rows. The gazetteer stores Montréal/São Paulo/Zürich; boards
    # write ASCII. 6,449 of 30,699 city keys carry non-ASCII.
    ("Montreal", ["remote", "USA"], False, "on-site in Canada"),
    ("Sao Paulo", ["remote", "USA"], False, "on-site in Brazil"),
    ("Zurich", ["remote", "USA"], False, "on-site in Switzerland"),
    ("Mexico City, México", ["remote", "USA"], False, "on-site in Mexico"),

    # (5) foreign subdivisions the city gazetteer does not carry — 25 rows.
    ("Gurugram, Haryana", ["remote", "USA"], False, "on-site in India"),
    ("Hyderabad, Telangana", ["remote", "USA"], False, "on-site in India"),
    ("Bengaluru, Karnataka", ["remote", "USA"], False, "on-site in India"),

    # (6) no separator at all — the tokenizer never split these, so nothing resolved.
    # A bare space/hyphen must NOT become a separator ("Winston-Salem", "Trinidad and
    # Tobago"), so a phrase-level scan catches them instead.
    ("Remote Canada", ["remote", "USA"], False, "on-site in Canada"),
    ("Remote Poland", ["remote", "USA"], False, "on-site in Poland"),
    ("India-Pune", ["remote", "USA"], False, "on-site in India"),
    ("Winston-Salem, NC", ["remote", "USA"], True, ""),

    # (7) region acronyms resolving to same-named villages. Right verdict, WRONG country:
    # `APAC` is a town in Uganda. A population floor cannot fix this (Apac UG 67,700 >
    # Zug CH 30,542) — only a stoplist can.
    ("APAC - India - Pune", ["remote", "USA"], False, "on-site in India"),
    ("EMEA", ["remote", "USA"], True, ""),
    ("Multiple Locations", ["remote", "USA"], True, ""),
    # A region that CONTAINS the US is not vague — it is weak US evidence (err toward keep).
    ("Remote, Americas; Remote, Canada; Remote, United Kingdom", ["remote", "USA"], True, "remote"),

    # (8) a foreign subdivision/parish must not outrank a major US city. `Charlotte` is a
    # parish of Saint Vincent and the Grenadines, `Fontana` a locality of Malta — reading
    # those first discarded 6 live US rows.
    ("Charlotte", ["remote", "USA"], True, ""),
    ("Fontana", ["remote", "USA"], True, ""),

    # (9) multi-country strings keep by construction — the test is `any allowed`, never
    # `all`. This single choice is what preserves the zero-false-discard invariant.
    ("New York City, London, Singapore", ["remote", "USA"], True, ""),
    ("London, Montreal, Singapore", ["remote", "USA"], False, "on-site in United Kingdom"),

    # --- preserved: cases earlier eras paid for, which the rebuild must not break.
    ("London, ON", ["Canada", "USA", "remote"], True, ""),      # D8: Canadian London
    ("Hyderabad, TS", ["Canada", "USA", "remote"], True, ""),   # accepted miss, now escalated
    ("Atlanta, Georgia", ["remote", "USA"], True, ""),          # state beats country
    ("885 GEORGIA ST W:VANCOUVER", ["remote", "USA"], True, ""),  # ...and in free text too
    ("Chicago, IL", ["New York"], True, ""),                    # US postal code, not Israel
    ("Sacramento, CA", ["New York"], True, ""),                 # CA=California, not Canada
    ("", ["remote", "USA"], True, ""),
    (None, ["remote", "USA"], True, ""),
])
def test_resolve_location(location, allowed, want_keep, want_note):
    passed, note = score.resolve_location(location, allowed)
    assert passed is want_keep, (location, allowed)
    assert note == want_note, (location, allowed)


# --- the tier-1/tier-2 seam ----------------------------------------------

@pytest.mark.parametrize("location,want_resolved,want_ask", [
    ("Bangalore, India", True, False),      # Tier A decided
    ("Sunnyvale, CA, USA", True, False),    # Tier A decided
    ("Montreal", True, False),              # Tier B, corroborated (nothing unresolvable)
    ("Remote", True, False),                # vague only -> the remote rule decided
    ("EMEA", False, False),                 # nothing to resolve, and no model can help
    ("NYC", False, True),                   # unknown token -> a model may do better
    ("London, ON", False, True),            # lone city + unresolvable region
    ("Bangalore - Bagmane Tridib", False, True),
])
def test_location_verdict_marks_what_escalates(location, want_resolved, want_ask):
    """`resolved` is what gates whether a location verdict is RECORDED at all, and
    `ask_llm` is what tier 2 keys off. Both matter on cost: if `ask_llm` widens, every
    pass makes an extra Ollama call per posting; if it narrows to nothing, tier 2 is
    dead code."""
    verdict = loc.location_verdict(location, ALLOWED)
    assert verdict["resolved"] is want_resolved, location
    assert verdict["ask_llm"] is want_ask, location
    if not verdict["resolved"]:
        assert verdict["keep"] is True, "an undecided location must still KEEP"


def test_the_escalation_rate_stays_inside_its_budget():
    """Tier 2's per-pass cost, in rows rather than distinct strings — the call count is
    what the operator pays in wall-clock."""
    rows = _corpus()
    total = sum(r["n"] for r in rows)
    asked = sum(r["n"] for r in rows if loc.location_verdict(r["s"], ALLOWED)["ask_llm"])
    assert asked / total < 0.06, f"{asked}/{total} rows would escalate to the model"


def test_token_country_resolves_states_countries_and_cities():
    assert loc._token_country("London") == "GB"           # foreign city (no US namesake)
    assert loc._token_country("New York City") == "US"     # US city
    assert loc._token_country("Chicago") == "US"
    assert loc._token_country("CA") == "US"                # US state code, NOT Canada
    assert loc._token_country("Georgia") == "US"           # US state, NOT the country
    assert loc._token_country("China") == "CN"             # country name
    assert loc._token_country("UK") == "GB"                # informal spelling
    assert loc._token_country("Montreal") == "CA"          # diacritic-folded
    assert loc._token_country("Telangana") == "IN"         # foreign subdivision
    assert loc._token_country("EMEA") is None              # region, not a place
    assert loc._token_country("Nowhereville") is None      # unresolved


def test_folding_is_the_same_function_everywhere():
    assert loc._fold("Montréal") == loc._fold("Montreal") == "montreal"
    assert loc._fold("  ZÜRICH  ") == "zurich"
    assert loc._fold("U.S.A.") == "usa"
