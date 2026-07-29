"""Location gazetteer: deterministic country/US-state/subdivision/city resolution backing
the LOCATION screen gate (`location_verdict` / `resolve_location`) — no LLM. Country and
subdivision data comes from pycountry (countries at import, subdivisions lazily); the city
index (geonamescache) is a heavier payload and also stays lazy, built on first use.

**Evidence tiers, not first-match.** Every token is classified once, then the verdict is
read off the strongest evidence present:

  TIER A — a token that NAMES a country (including informal spellings: "UK", "England",
           "Great Britain") or a US state. Self-corroborating: one such token decides,
           and it outranks the remote hint.
  TIER B — a foreign subdivision ("Telangana", "Ontario") or a gazetteer city
           ("Montreal"). Weaker: a city name is ambiguous across countries, so Tier B
           discards only when CORROBORATED (see `location_verdict`). It still KEEPS on
           its own — allowed evidence is allowed evidence whatever tier found it.
           Subdivision outranks city within the tier, which is what makes "Ontario" read
           as the Canadian province rather than Ontario, California.
  neither — no verdict is recorded at all. The gate stays silent rather than guessing,
           which is what lets a later tier (the free screen extraction) answer instead.

The tiering is what fixes the 2026-07-29 leak survey's six mechanical failure classes at
once: informal country names, the remote hint firing before resolution, city-derived US
evidence outvoting a named country, ASCII-vs-diacritic city misses, unknown foreign
subdivisions, and region acronyms resolving to same-named villages.
"""
from __future__ import annotations

import re
import unicodedata

import pycountry

# The 4B model tends to invent remote=true out of silence. We only honour that guess
# when the LOCATION STRING actually says remote (see location_verdict); this can only
# DOWNGRADE an unsupported guess, so it never causes a wrong discard.
_REMOTE_HINTS = ("remote", "work from home", "work-from-home", "wfh", "work from anywhere",
                 "fully remote", "remotely", "location independent", "location-independent")


def _fold(value) -> str:
    """Canonical comparison key: NFKD-decompose, drop combining marks, lowercase, drop
    dots, collapse whitespace. ONE folding function for every index and every lookup —
    boards write "Montreal"/"Sao Paulo"/"Zurich" while geonamescache stores "Montréal"/
    "São Paulo"/"Zürich", and 6,449 of its 30,699 city keys carry non-ASCII, so an
    unfolded index leaves a fifth of the world unreachable."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.replace(".", "").lower().split())


# Informal country spellings -> ISO alpha-2. Keyed by FOLDED phrase and consulted by
# `_country_code`, so both the candidate's allowed list and the posting's tokens resolve
# through it. Before 2026-07-30 this map existed but was read only when comparing against
# the allowed list, never when resolving a token — which is why `UK` (116 rows) sailed
# through: pycountry knows "GB", not "UK". It also silently broke the other direction,
# `locations: ["UK", "USA"]` yielding allowed_codes {"US"} and discarding every UK role.
# Seeded from the spellings actually observed in the live corpus, not from imagination.
_COUNTRY_ALIASES = {
    "us": "US", "usa": "US", "america": "US", "united states": "US",
    "united states of america": "US", "the united states": "US",
    "uk": "GB", "gb": "GB", "gbr": "GB", "united kingdom": "GB", "britain": "GB",
    "great britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "greater london": "GB", "ldn": "GB",
    "uae": "AE", "emirates": "AE",
    "republic of korea": "KR", "south korea": "KR",
}

# Region acronyms, work-arrangement words and placeholders. These name no country, so
# they must resolve to NOTHING rather than to a same-named village — `APAC` is a town in
# Uganda (pop 67,700) and used to discard "APAC - India - Pune" as "on-site in Uganda".
# A population floor cannot fix that class: Apac UG outranks Zug CH (30,542), so any
# floor that kills the acronym also kills legitimate small European cities. A stoplist can.
# Distinct from an UNKNOWN token: a vague token is knowingly uninformative, so it never
# blocks corroboration, whereas an unknown one does.
_VAGUE_TOKENS = frozenset({
    "remote", "hybrid", "on-site", "onsite", "in-office", "flexible", "anywhere",
    "worldwide", "global", "international", "multiple locations", "multiple cities",
    "various", "various locations", "other", "tbd", "n/a", "hq", "headquarters",
    "emea", "apac", "apj", "latam", "anz", "mena", "eu", "europe", "asia",
    "asia pacific",
})

# Regions that CONTAIN the United States. They name no single country, but they are not
# uninformative either: "Remote, Americas; Remote, Canada; Remote, United Kingdom" is
# US-eligible, and treating "Americas" as empty let the named Canada/UK discard it. So
# they contribute US as weak evidence — err toward keep (PRINCIPLES 3). The cost is
# accepted and one-directional: "AMER - Canada - Ontario - Toronto" now keeps too, which
# is one wasted fit call rather than a silently deleted job. LATAM is deliberately NOT
# here: it excludes the US.
# ("NA" is deliberately absent: it is Namibia's ISO code and appears in no live string.)
_US_INCLUSIVE_REGIONS = frozenset({
    "americas", "amer", "amers", "nam", "namer", "north america",
})

# US subdivisions (states + territories), built once at import. Used to KEEP a US
# role whose location string names only a state ("New York, New York", "Austin, TX")
# and to win the state/country name collision ("Atlanta, Georgia": Georgia is a US
# state AND a country — the state reading wins, see `_classify_token`'s ordering).
_US_STATE_NAMES = {_fold(s.name) for s in pycountry.subdivisions if s.country_code == "US"}
_US_STATE_CODES = {s.code.split("-")[1] for s in pycountry.subdivisions if s.country_code == "US"}


def _mentions(description: str, hints: tuple[str, ...]) -> bool:
    """True if the JD text contains any of `hints` (used to sanity-check the model's
    sponsorship/remote guesses against the source)."""
    t = (description or "").lower()
    return any(h in t for h in hints)


def _norm_loc(value) -> str:
    """Normalise a location entry for direct comparison against the allowed list.
    Country spellings fold together (United States == USA == US) via `_country_code`,
    so an allowed "UK" matches a token "United Kingdom"."""
    folded = _fold(value)
    code = _country_code(folded)
    return code or folded


def _is_us_state(token: str) -> bool:
    """True if `token` is a US state/territory name ('California') or 2-letter code ('CA')."""
    return _fold(token) in _US_STATE_NAMES or str(token).strip().upper() in _US_STATE_CODES


def _country_code(token: str) -> str | None:
    """ISO alpha-2 for a country name/code token ('China'->'CN', 'USA'->'US', 'UK'->'GB'),
    else None. Consults the informal-alias table BEFORE pycountry, which knows only the
    official names."""
    folded = _fold(token)
    if not folded:
        return None
    alias = _COUNTRY_ALIASES.get(folded)
    if alias:
        return alias
    try:
        return pycountry.countries.lookup(str(token).strip()).alpha_2
    except LookupError:
        return None


_SUBDIVISION_INDEX: dict[str, str] | None = None


def _subdivision_index() -> dict[str, str]:
    """Lazy index: folded FOREIGN subdivision name -> ISO alpha-2. A name is admitted only
    when it is unambiguous (maps to exactly one country) and is not a US state name, so
    'Florida'/'Maryland'/'Montana' — US states that are also foreign subdivisions — keep
    their US reading. Gives the gate 'Telangana', 'Haryana', 'Ontario', 'British Columbia',
    'New South Wales', which the city gazetteer does not carry.

    2-letter subdivision CODES are deliberately excluded: 51 of them collide with US state
    codes, and 'ON' alone is ambiguous across Canada, Namibia and Nigeria. That is why
    'London, ON' stays uncorroborated (and therefore kept) — by choice, not by accident."""
    global _SUBDIVISION_INDEX
    if _SUBDIVISION_INDEX is None:
        by_name: dict[str, set] = {}
        for sub in pycountry.subdivisions:
            if sub.country_code == "US":
                continue
            folded = _fold(sub.name)
            if not folded or folded in _US_STATE_NAMES:
                continue
            by_name.setdefault(folded, set()).add(sub.country_code)
        _SUBDIVISION_INDEX = {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1}
    return _SUBDIVISION_INDEX


_CITY_INDEX: dict[str, str] | None = None


def _city_index() -> dict[str, str]:
    """Lazy geonamescache index: FOLDED city name -> ISO alpha-2 of the HIGHEST-POPULATION
    city with that name. Built once (~31k cities) on first use — fine for the batch worker.
    Folding is what lets a board's ASCII "Montreal"/"Sao Paulo"/"Zurich" reach the stored
    "Montréal"/"São Paulo"/"Zürich". No US bias: a tiny US namesake (Paris TX, Amsterdam
    NY) must NOT override the world city it shares a name with, or clearly-foreign postings
    would leak through the gate."""
    global _CITY_INDEX
    if _CITY_INDEX is None:
        import geonamescache  # heavy data payload — deferred to first location gate
        idx: dict[str, str] = {}
        best: dict[str, int] = {}
        for c in geonamescache.GeonamesCache().get_cities().values():
            name = _fold(c["name"])
            pop = c.get("population") or 0
            if name not in best or pop > best[name]:
                best[name] = pop
                idx[name] = c["countrycode"]
        _CITY_INDEX = idx
    return _CITY_INDEX


_ALIAS_INDEX: dict[str, str] | None = None


def _alias_index() -> dict[str, str]:
    """Lazy index of geonamescache's `alternatenames` — the endonyms, abbreviations and
    former names boards actually write: `NYC`, `Bangalore` (indexed as Bengaluru),
    `Gurgaon` (Gurugram), `Frankfurt` (Frankfurt am Main), `Bombay`. 141k keys the
    primary index throws away, and the single largest remaining source of unresolved
    strings after the 2026-07-30 rebuild.

    Same highest-population-wins policy as `_city_index`, and consulted only AFTER it,
    so an alias can never override a primary name. ASCII-only and 3+ characters: the
    alternatenames list is full of non-Latin scripts and 2-letter stubs that would
    collide with country and US-state codes.

    SHORT aliases additionally need a big city behind them. A 3-4 character alias is
    mostly noise — `MOD` is an alternate name for some small US place, and it made
    `Sanand - 303A - AT/SSD/MOD, India` keep as US-eligible despite naming India twice.
    Requiring a million people for those keeps the ones boards actually write (`NYC` ->
    New York) and drops the facility-code collisions; longer aliases (`Bangalore`,
    `Gurgaon`, `Frankfurt`) carry enough signal on their own."""
    global _ALIAS_INDEX
    if _ALIAS_INDEX is None:
        import geonamescache
        idx: dict[str, str] = {}
        best: dict[str, int] = {}
        for c in geonamescache.GeonamesCache().get_cities().values():
            pop = c.get("population") or 0
            for alt in (c.get("alternatenames") or []):
                name = _fold(alt)
                if len(name) < 3 or not name.isascii():
                    continue
                if len(name) <= 4 and pop < 1_000_000:
                    continue
                if name not in best or pop > best[name]:
                    best[name] = pop
                    idx[name] = c["countrycode"]
        _ALIAS_INDEX = idx
    return _ALIAS_INDEX


# Site/facility nouns boards append to a real place name ("San Francisco HQ", "London
# Office", "San Francisco Bay Area"). Stripped only as a LAST resort, after the token
# failed every index, so a real place called "... Office" is never shadowed.
_SITE_SUFFIXES = ("bay area", "metro area", "metropolitan area", "greater area", "area",
                  "headquarters", "head office", "office", "hq", "campus", "site",
                  "location", "region")


def _strip_site_suffix(folded: str) -> str:
    """'san francisco hq' -> 'san francisco'. Returns the input unchanged when nothing
    strips, so callers can test for a change."""
    for suffix in _SITE_SUFFIXES:
        if folded.endswith(" " + suffix):
            return folded[: -(len(suffix) + 1)].strip()
    return folded


def _classify_token(token: str) -> tuple[str, str | None]:
    """Classify one location token as (kind, ISO alpha-2 or None). Kinds:
    'vague' | 'country' | 'us_state' | 'subdivision' | 'city' | 'unknown'.

    ORDER IS LOAD-BEARING:
      1. vague     — a stoplist hit names no place at all (kills the APAC->Uganda class).
      2. us_state  — before country so 'Georgia' reads as the state, not the country;
                     before subdivision so 'Florida'/'Maryland'/'Montana' stay US.
      3. country   — alias table, then pycountry.
      4. subdivision — foreign, unambiguous, name-only.
      5. city      — folded gazetteer, highest population wins.
      6. alias     — geonamescache alternatenames ('NYC', 'Bangalore', 'Frankfurt'),
                     after the primary index so it can only ADD resolutions.
      7. site-noun strip — one retry with a trailing facility word removed
                     ('San Francisco HQ' -> 'San Francisco'), last so a real place is
                     never shadowed by it.
      8. unknown   — resolves to nothing AND is not knowingly uninformative, so it
                     withholds corroboration from a lone city reading.
    """
    raw = str(token or "").strip()
    folded = _fold(raw)
    if not folded:
        return "unknown", None
    if folded in _VAGUE_TOKENS:
        return "vague", None
    if folded in _US_INCLUSIVE_REGIONS:
        return "region", "US"
    if _is_us_state(raw):
        return "us_state", "US"
    code = _country_code(raw)
    if code:
        return "country", code
    sub = _subdivision_index().get(folded)
    if sub:
        return "subdivision", sub
    city = _city_index().get(folded) or _alias_index().get(folded)
    if city:
        return "city", city
    stripped = _strip_site_suffix(folded)
    if stripped != folded and stripped:
        kind, code = _classify_token(stripped)
        if kind != "unknown":
            return kind, code
    return "unknown", None


def _weak_readings(token: str) -> set[str]:
    """EVERY Tier-B country a token could denote — its subdivision reading AND its city
    reading, not just the winning one.

    A fixed precedence between the two cannot work, and both directions have a live
    counter-example: 'Ontario' must read as the Canadian province (so 'Toronto, Ontario'
    discards) while 'Charlotte' must read as the US city (it is also a parish of Saint
    Vincent and the Grenadines, and preferring the subdivision discarded 4 live US rows as
    "on-site in Saint Vincent and the Grenadines"; 'Fontana' is the same story via Malta).
    So a token votes for both, and `location_verdict` lets the SUPPORTING-TOKEN COUNT
    settle it: 'Toronto, Ontario' gives Canada two votes to America's one, while a bare
    'Charlotte' ties 1-1 and the US reading keeps it."""
    folded = _fold(token)
    if not folded or folded in _VAGUE_TOKENS:
        return set()
    if folded in _US_INCLUSIVE_REGIONS:
        return {"US"}
    out = set()
    sub = _subdivision_index().get(folded)
    if sub:
        out.add(sub)
    for index in (_city_index(), _alias_index()):
        city = index.get(folded)
        if city:
            out.add(city)
            break
    if not out:
        stripped = _strip_site_suffix(folded)
        if stripped != folded and stripped:
            return _weak_readings(stripped)
    return out


def _token_country(token: str) -> str | None:
    """ISO alpha-2 for a single location token, or None if it names no place. Thin wrapper
    over `_classify_token` kept for callers that only want the code."""
    return _classify_token(token)[1]


def _country_name(code: str) -> str:
    """Human country name for an ISO alpha-2 code (used in the discard reason)."""
    c = pycountry.countries.get(alpha_2=code)
    return c.name if c else code


_PHRASE_RE: re.Pattern | None = None


def _phrase_countries(location_str) -> list[tuple[str, str]]:
    """Country names appearing as whole words ANYWHERE in the string, in order — for the
    boards that use no separator the tokenizer recognises: "Remote Canada", "Remote
    Poland", "India-Pune", "MX-Mexico-Remote", "Glasgow, UK (ZUK118)". Tokenizing alone
    left 40+ live rows unresolved because a bare space or hyphen is not a separator (and
    must not become one — "Winston-Salem" and "Trinidad and Tobago" depend on that).

    Only names of 4+ characters and the explicit alias spellings are scanned, so short
    ISO codes ("CA", "IN", "OR") can never fire here — those stay a token-level decision
    where the US-state reading wins."""
    global _PHRASE_RE
    if _PHRASE_RE is None:
        names = {k for k in _COUNTRY_ALIASES if len(k) >= 2}
        for country in pycountry.countries:
            for attr in ("name", "common_name", "official_name"):
                value = getattr(country, attr, None)
                if value and len(value) >= 4 and "," not in value:
                    names.add(_fold(value))
        # A US state name must never be read as a foreign country by a free-text scan:
        # "885 GEORGIA ST W:VANCOUVER" is a street address, and matching the country
        # Georgia in it produced a discard reason naming the wrong continent. The
        # state/country collision stays a TOKEN-level decision, where us_state wins.
        names -= _US_STATE_NAMES
        ordered = sorted(names, key=len, reverse=True)
        _PHRASE_RE = re.compile(r"(?<![a-z])(" + "|".join(re.escape(n) for n in ordered)
                                + r")(?![a-z])")
    folded = _fold(location_str)
    out = []
    for match in _PHRASE_RE.finditer(folded):
        code = _country_code(match.group(1))
        if code:
            out.append((match.group(1), code))
    return out


# The punctuation the primary tokenizer deliberately ignores, used ONLY to retry a token
# that already resolved to nothing. Splitting on these up front would shred
# "Winston-Salem"; splitting only on failure cannot, because "Winston-Salem" resolves.
_SUBPART_RE = re.compile(r"[-–—./\\]+")


def _expand_unresolved(classified: list) -> list:
    """Give every token that named nothing one more chance, split on `- . /` — the
    site-code formats boards use with no separator the splitter recognises:
    `PL-Warsaw-Lixa C`, `FR-Paris`, `NO-Oslo-MSO`, `USA.VA.Reston`, `IN-Pune`.

    Sub-parts are appended as ordinary tokens, so the normal tiering decides: an
    unambiguous country prefix (`FR`, `NO`, `PL`, `AU`) becomes Tier A and discards.
    A prefix that collides with a US state code is read as the COUNTRY only when a
    later part corroborates it — `DE-Germany-Remote` and `CO-Colombia-Remote` name their
    country twice, and `CA-Toronto` has Toronto to vouch for Canada, while `USA.VA.Reston`
    keeps Virginia because nothing there points at the Holy See. Uncorroborated, the
    state reading wins and the row keeps: err toward keep, no worse than the unresolved
    status quo.

    A token whose parts all still fail keeps its original `unknown` classification, so
    it goes on withholding corroboration."""
    out = []
    for entry in classified:
        token, kind, _code = entry
        if kind != "unknown":
            out.append(entry)
            continue
        parts = [p for p in _SUBPART_RE.split(str(token)) if p.strip()]
        if len(parts) < 2:
            out.append(entry)
            continue
        resolved = [(p, *_classify_token(p)) for p in parts]
        # Corroborated country prefix: a part read as a US state whose 2-letter code is
        # ALSO a country code that another part independently names.
        others = {c for _, k, c in resolved if c and k != "us_state"}
        resolved = [
            (p, "country", _country_code(p))
            if k == "us_state" and len(p.strip()) == 2 and _country_code(p) in others
            else (p, k, c)
            for p, k, c in resolved
        ]
        resolved = [r for r in resolved if r[1] != "unknown"]
        out.extend(resolved or [entry])
    return out


def _tokenize(location_str) -> list[str]:
    """Split a board location string on its separators: commas, slashes, semicolons,
    pipes, the word ' or ', and a SPACE-PADDED dash (en/em too). A bare hyphen is NOT a
    separator, so 'Winston-Salem' survives intact. ' and ' is deliberately not a
    separator either — it would shred 'Trinidad and Tobago'."""
    return [t for t in re.split(r"[,/;|]| or | +[-–—]+ +", str(location_str), flags=re.I)
            if t.strip()]


def location_verdict(location_str, allowed_locations) -> dict:
    """Decide keep/discard for a posting's board `location` string against the candidate's
    `allowed_locations`, in CODE (no LLM). Returns
    `{keep, note, resolved, ask_llm, codes}`:

      keep     — whether the posting survives this gate
      note     — "remote", or "on-site in <Country>" on a discard
      resolved — whether the gate actually REACHED a verdict. False means "no evidence",
                 which is a keep by policy (err toward keep) but must NOT be recorded as
                 a passing location check: leaving the key absent is what lets a later
                 free extraction fill the gap instead of the gate silently blessing it.
      ask_llm  — the string carried a token that named no place at all, so a model may
                 do better than the gazetteer. (A merely VAGUE string — "Remote", "EMEA" —
                 sets this False: there is nothing there for anyone to resolve.)
      codes    — every country code the string was read as, for the audit trail

    Rule order (the order itself is the fix for three of the nine leak classes):

      (A) missing location -> keep, resolved.
      (B) direct match: an allowed entry equals a token, country-aliased, so allowed
          "USA" matches token "United States". The literal "remote" allow-entry is
          EXCLUDED here — it is a work arrangement, not a place, and matching it as one
          is how "Remote - India" used to keep before its country was ever looked at.
      (C) TIER A decides alone. Keep if any named country / US state is allowed;
          otherwise discard, naming the first foreign one. Runs BEFORE the remote check
          so "Remote - India" discards while "Remote - US" keeps.
      (D) remote: only now, and only off the LOCATION STRING (not JD prose, so a JD
          that merely says "not remote" can't false-match).
      (E) TIER B decides only when corroborated — either every token resolved, or the
          winning country has two supporting tokens. Uncorroborated city evidence keeps:
          only US subdivisions are in the gazetteer, so 'London, ON' would otherwise drop
          its unresolvable 'ON' and be judged by 'London' alone as the United Kingdom —
          discarding a Canadian posting under a reason naming the wrong country.
      (F) nothing resolved -> keep, NOT resolved.

    Multi-country strings keep by construction: the test is `any(code allowed)`, never
    `all`, so "London, UK / New York, NY" survives. That single choice is what preserves
    the zero-false-discard invariant across the whole redesign.
    """
    if not location_str or not str(location_str).strip():
        return {"keep": True, "note": "", "resolved": True, "ask_llm": False, "codes": []}

    allowed_norm = {_norm_loc(a) for a in allowed_locations if str(a).strip()}
    remote_allowed = any(_fold(a) == "remote" for a in allowed_locations)
    allowed_codes = {c for c in (_country_code(a) for a in allowed_locations) if c}
    # ponytail: US always keep-worthy — the operator is US-based, and the shipped example
    # config is `locations: ["remote"]`, which resolves to NO country codes at all. Without
    # this, "New York, NY" would discard.
    keep_codes = allowed_codes | {"US"}

    tokens = _tokenize(location_str)
    classified = _expand_unresolved([(t, *_classify_token(t)) for t in tokens])
    codes = [c for _, _, c in classified if c]
    # Whether the STRING says remote (not the JD prose, so a JD that merely says "not
    # remote" can't false-match). Computed up front because it only ever decorates the
    # note on a keep — it must never be what DECIDES a keep, which was the old bug.
    said_remote = remote_allowed and _mentions(str(location_str), _REMOTE_HINTS)

    # (B) direct match — geography only; "remote" is handled at (D), never as a place.
    geo_allowed = allowed_norm - {"remote"}
    if geo_allowed & {_norm_loc(t) for t in tokens}:
        return {"keep": True, "note": "remote" if said_remote else "",
                "resolved": True, "ask_llm": False, "codes": codes}

    strong = [(t, c) for t, kind, c in classified if kind in ("country", "us_state") and c]
    # A country named inside an unsplittable token still counts as Tier A evidence.
    phrase_only = [(t, c) for t, c in _phrase_countries(location_str)
                   if c not in {code for _, code in strong}]
    strong += phrase_only
    # Evidence in TOKEN ORDER, so a discard names the first foreign place a human reading
    # the string would see ("London, Montreal, Singapore" -> United Kingdom, not Singapore).
    # Phrase-only hits are appended last: they exist precisely because nothing tokenized.
    evidence = [(t, c) for t, kind, c in classified
                if kind in ("country", "us_state", "subdivision", "city", "region") and c]
    evidence += phrase_only
    weak = [(t, c) for t, kind, c in classified if kind in ("subdivision", "city", "region") and c]
    unknown = [t for t, kind, _c in classified if kind == "unknown"]

    # TIER B is settled by SUPPORTING-TOKEN COUNT over every reading each token allows
    # (see `_weak_readings`): the countries with the most agreeing tokens win, so
    # "Toronto, Ontario" reads Canada 2-1 while a bare "Charlotte" ties and keeps its US
    # reading. Ties keep every winner, which is what makes the tie fall the safe way.
    tally: dict[str, int] = {}
    for token, kind, _c in classified:
        if kind not in ("subdivision", "city", "region"):
            continue
        for code in _weak_readings(token):
            tally[code] = tally.get(code, 0) + 1
    winners = [c for c, n in tally.items() if n == max(tally.values())] if tally else []

    # ANY allowed evidence keeps, whatever tier found it. Tier A outranks Tier B for the
    # discard REASON, never as a veto over Tier B's keep-evidence — "Singapore" is a
    # country AND a city, so a Tier-A-decides-alone rule discarded
    # "New York City, London, Singapore" despite New York City resolving US.
    if any(c in keep_codes for _, c in strong) or any(c in keep_codes for c in winners):
        return {"keep": True, "note": "remote" if said_remote else "",
                "resolved": True, "ask_llm": False, "codes": codes}

    # (C) TIER A — a named country / US state is self-corroborating, so it discards on its
    # own, and it does so BEFORE the remote check: that ordering is the whole fix for
    # "Remote - India" (85 rows), while "Remote - US" keeps above.
    if strong:
        return {"keep": False, "note": f"on-site in {_country_name(evidence[0][1])}",
                "resolved": True, "ask_llm": False, "codes": codes}

    # (D) remote — reached only when nothing named a country.
    if said_remote:
        return {"keep": True, "note": "remote", "resolved": True, "ask_llm": False, "codes": codes}

    # (E) TIER B — city/subdivision evidence discards only when CORROBORATED: either every
    # token resolved, or two tokens agree. A lone city beside an unresolvable token stays
    # unresolved ("London, ON" -> ON is in no gazetteer, and London alone would name the
    # wrong country for a Canadian posting).
    if weak:
        if unknown and len(weak) < 2:
            return {"keep": True, "note": "", "resolved": False, "ask_llm": True, "codes": codes}
        return {"keep": False, "note": f"on-site in {_country_name(evidence[0][1])}",
                "resolved": True, "ask_llm": False, "codes": codes}

    # (F) no evidence at all. Keep, but record NO verdict — an unknown token means a
    # model may still resolve it; a merely vague string means nobody can.
    return {"keep": True, "note": "", "resolved": False,
            "ask_llm": bool(unknown), "codes": codes}


def resolve_location(location_str, allowed_locations) -> tuple[bool, str]:
    """`(keep, note)` for the location gate — the two-value view of `location_verdict`,
    kept so every existing caller and test stays byte-compatible."""
    verdict = location_verdict(location_str, allowed_locations)
    return verdict["keep"], verdict["note"]
