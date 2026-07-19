"""Location gazetteer: deterministic country/US-state/city resolution backing the
LOCATION screen gate (`resolve_location`) — no LLM. Country/state data comes from
pycountry (loaded at import); the city index (geonamescache) is a heavier payload
and stays lazily imported inside `_city_index`, built only on first use.
"""
from __future__ import annotations

import re

import pycountry

# The 4B model tends to invent remote=true out of silence. We only honour that guess
# when the LOCATION STRING actually says remote (see resolve_location); this can only
# DOWNGRADE an unsupported guess, so it never causes a wrong discard.
_REMOTE_HINTS = ("remote", "work from home", "work-from-home", "wfh", "work from anywhere",
                 "fully remote", "remotely", "location independent", "location-independent")

# Country aliases normalised so the LLM's free-form country ("United States") and
# the candidate's config ("USA") compare equal. Only the common multi-spelling
# countries need entries; everything else compares on its lowercased name.
_COUNTRY_ALIASES = {
    "us": "usa", "u.s": "usa", "u.s.a": "usa", "usa": "usa", "america": "usa",
    "united states": "usa", "united states of america": "usa", "the united states": "usa",
    "uk": "uk", "u.k": "uk", "united kingdom": "uk", "britain": "uk",
    "great britain": "uk", "england": "uk",
}

# US subdivisions (states + territories), built once at import. Used to KEEP a US
# role whose location string names only a state ("New York, New York", "Austin, TX")
# and to win the state/country name collision ("Atlanta, Georgia": Georgia is a US
# state AND a country — the state reading wins when the candidate allows USA).
_US_STATE_NAMES = {s.name.lower() for s in pycountry.subdivisions if s.country_code == "US"}
_US_STATE_CODES = {s.code.split("-")[1] for s in pycountry.subdivisions if s.country_code == "US"}


def _mentions(description: str, hints: tuple[str, ...]) -> bool:
    """True if the JD text contains any of `hints` (used to sanity-check the model's
    sponsorship/remote guesses against the source)."""
    t = (description or "").lower()
    return any(h in t for h in hints)


def _norm_loc(value) -> str:
    """Normalise a country for comparison, folding common multi-spellings
    (United States == USA == US)."""
    t = " ".join(str(value).strip().lower().replace(".", "").split())
    return _COUNTRY_ALIASES.get(t, t)


def _is_us_state(token: str) -> bool:
    """True if `token` is a US state/territory name ('California') or 2-letter code ('CA')."""
    t = token.strip()
    return t.lower() in _US_STATE_NAMES or t.upper() in _US_STATE_CODES


def _country_code(token: str) -> str | None:
    """ISO alpha-2 for a country name/code token ('China'->'CN', 'USA'->'US'), else None."""
    try:
        return pycountry.countries.lookup(token.strip()).alpha_2
    except LookupError:
        return None


_CITY_INDEX: dict[str, str] | None = None


def _city_index() -> dict[str, str]:
    """Lazy geonamescache index: lowercased city name -> ISO alpha-2 of the
    HIGHEST-POPULATION city with that name. Built once (~32k cities, a few MB) on first
    use — fine for the batch worker. No US bias: a tiny US namesake (Paris TX, Amsterdam
    NY) must NOT override the world city it shares a name with, or clearly-foreign
    postings would leak through the gate."""
    global _CITY_INDEX
    if _CITY_INDEX is None:
        import geonamescache  # heavy data payload — deferred to first location gate
        idx: dict[str, str] = {}
        best: dict[str, int] = {}
        for c in geonamescache.GeonamesCache().get_cities().values():
            name = c["name"].lower()
            pop = c.get("population") or 0
            if name not in best or pop > best[name]:
                best[name] = pop
                idx[name] = c["countrycode"]
        _CITY_INDEX = idx
    return _CITY_INDEX


def _token_country(token: str) -> str | None:
    """ISO alpha-2 for a single location token, or None if unresolved. US state (name
    or 2-letter code) wins FIRST — so 'CA'->US not Canada, 'Georgia'->US not the country
    — then a country name/code (pycountry), then a city via geonamescache."""
    t = (token or "").strip()
    if not t:
        return None
    if _is_us_state(t):
        return "US"
    code = _country_code(t)
    if code:
        return code
    return _city_index().get(t.lower())


def _country_name(code: str) -> str:
    """Human country name for an ISO alpha-2 code (used in the discard reason)."""
    c = pycountry.countries.get(alpha_2=code)
    return c.name if c else code


def resolve_location(location_str, allowed_locations) -> tuple[bool, str]:
    """Decide keep/discard for a posting's board `location` string against the
    candidate's `allowed_locations`, in CODE (no LLM). Errs toward KEEP: discards
    only when the string clearly resolves to a disallowed country.

    Order:
      (A) missing location -> keep.
      (B) remote: if 'remote' is allowed and the LOCATION STRING says remote -> keep.
          (Keyed off the board location field, NOT the JD prose, so a JD that merely
          says 'not remote' can't false-match.)
      (C) direct match: an allowed entry equals a location token, with country
          aliasing via _norm_loc (allowed 'USA' matches token 'United States'; an
          allowed city/state matches that token).
      (D) US-state precedence: a US-state token keeps when USA is allowed (also
          settles the Georgia state-vs-country collision).
      (E) foreign: resolve EVERY token to a country (city->country via geonamescache,
          highest-population match), not just the last. Keep if any token is US (the
          operator is US-based; this also keeps the IL/CA/GA postal codes, read as US
          states, not Israel/Canada/Gabon) or an allowed country; discard only when
          >=1 token resolves and none are allowed, naming the first foreign country.
      (F) nothing resolved -> keep (err toward keep, as today).
    """
    if not location_str or not str(location_str).strip():
        return True, ""                                                      # (A)
    allowed_norm = {_norm_loc(a) for a in allowed_locations if str(a).strip()}
    allowed_codes = set()
    for a in allowed_locations:
        if _norm_loc(a) == "remote":
            continue
        code = _country_code(str(a))
        if code:
            allowed_codes.add(code)
    if "remote" in allowed_norm and _mentions(str(location_str), _REMOTE_HINTS):  # (B)
        return True, "remote"
    # Split on board separators — commas, slashes, ' or '/' OR ' (case-insensitive, so
    # "Hanoi OR Ho Chi Minh City" splits), and a SPACE-padded dash ("London - United
    # Kingdom", en/em too); a bare hyphen ("Winston-Salem") is NOT a separator, so
    # intra-token hyphens survive.
    tokens = [t for t in re.split(r"[,/;|]| or | +[-–—]+ +", str(location_str), flags=re.I)
              if t.strip()]
    if allowed_norm & {_norm_loc(t) for t in tokens}:                        # (C)
        return True, ""
    if "usa" in allowed_norm and any(_is_us_state(t) for t in tokens):       # (D)
        return True, ""
    # (E) resolve EVERY token, not just the last. Keep if any is US or an allowed
    # country; discard only when >=1 resolves and none are allowed.
    resolved = [(t, _token_country(t)) for t in tokens]
    codes = [c for _, c in resolved if c]
    if not codes:
        return True, ""                                                      # (F)
    keep_codes = allowed_codes | {"US"}  # ponytail: US always keep-worthy (US-based operator + postal guard)
    if any(c in keep_codes for c in codes):
        return True, ""
    token, code = next((t, c) for t, c in resolved if c and c not in keep_codes)
    return False, f"on-site in {_country_name(code)}"
