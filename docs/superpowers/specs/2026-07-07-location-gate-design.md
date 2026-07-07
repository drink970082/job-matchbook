# Design: Deterministic location gate — code owns location off the board field

**Status:** approved (brainstorming), ready for implementation plan.
**Date:** 2026-07-07.

## Problem / motivation

The hard-requirements SCREEN asks the local 4B model (qwen3.5:4b) to *extract*
`{city, region, country, remote}` from each posting, and code then matches those
fields against the candidate's allowed `locations`. Location is the screen's
highest-value filter for this candidate (allowed `["remote", "USA"]`, screening a
watchlist of quant firms with heavy London/Amsterdam/Singapore/Sydney/Shanghai
presence).

A live run on Optiver (2026-07-07) exposed the failure: **"AI Researcher" listed on
the board as `Shanghai, China` was KEPT.** The board API had already handed the clean
string `"Shanghai, China"` into the prompt's `Location:` line, but the 4B returned no
country field; `_check_location` then hit `if not fields: return True` (err toward
keep) and let a clearly-foreign role through to the paid Claude score. The matching
code is correct — its *input* is unreliable. We are re-deriving location from a JD via
a 4B when the board already gave us a structured `location` string.

## Goal

Make the location gate reliable by matching against the board's `posting["location"]`
string **in code**, removing the flaky 4B location extraction. Foreign on-site roles
that carry a country token (all observed leaks) get discarded before the paid Claude
call; US/remote roles are kept.

## Non-goals

- No change to the other screen gates (degree, work authorization, clearance,
  dealbreakers) — they stay LLM-extract + code-apply.
- No change to the internship gate (already deterministic, title-only).
- No change to the score→screen ordering (already reordered: screen gates score).
- No attempt to resolve bare foreign **cities** with no country token (e.g. "London"
  alone). Err toward keep covers these; see Decisions.

## Decisions (resolved with the user)

1. **Failure mode: err toward keep.** Discard only when the location string *clearly*
   resolves to a disallowed country; ambiguous / missing / unresolved → keep. Matches
   the existing screen philosophy and the board data shape (foreign roles carry a
   country token; domestic US roles often omit it — "New York, New York").
2. **Code owns location; drop it from the LLM.** The location-extraction clause leaves
   the screen prompt entirely. The LLM screen runs only for degree/auth/clearance/
   dealbreakers. A candidate configured with only `locations` (± internships) makes
   **zero Ollama calls**.
3. **Country recognition: geo dataset dependency — `pycountry`.** Chosen over a curated
   no-dep list (for exhaustiveness) and over geonamescache (pycountry ships countries
   **and subdivisions**, which resolve "City, State, Country" strings natively and is
   the lighter package; geonamescache's bare-city→country edge is not needed and
   err-toward-keep can leak it).
4. **Split the prompt file in two** (score vs screen), since we are already editing it.

## Change list

### Worker — `ats_worker/score.py`

- **New pure resolver** `resolve_location(location_str, allowed, description) -> (passed, note)`:
  1. **Remote:** if the location string (or `description`, as today) signals remote and
     `"remote" ∈ allowed` → `(True, "…remote")`.
  2. **Tokenize** `location_str` on commas; resolve each token via `pycountry`
     (`countries` + `subdivisions`) to an ISO country code.
     - token → an allowed country (candidate "USA" → `US`) **or a US subdivision**
       (state) → *US signal*.
     - token → a resolved country not in `allowed` → *foreign signal*.
  3. **Decide (US-precedence, keep-leaning):** any US/remote signal → keep; else any
     foreign signal → `(False, "on-site in <country>")`; else nothing resolved → keep.
  - Normalise the candidate's allowed entries to country codes once (reuse/extend
    `_COUNTRY_ALIASES` so "USA"/"US"/"United States" all map to `US`); "remote" is a
    special allowed token, not a country.
  - US-precedence resolves the US-state/country name collision ("Atlanta, **Georgia**":
    Georgia is a US subdivision *and* a country → US-subdivision match wins → keep).
- **`_check_location` (old, LLM-entry based) is removed**, replaced by `resolve_location`.
- **`score_posting`:** gate location from `posting["location"]` and merge the verdict
  into `screen` — the same pattern as the existing deterministic internship merge —
  guarded by `candidate.get("locations")`. Runs regardless of whether an LLM screen
  call was made.
- **`_candidate_block`:** drop the location clause (no `SCORE_C_LOCATION`). Consequence:
  when only `locations`/`exclude_internships` are configured, `_candidate_block` returns
  `""` → no Ollama call.
- **`_screen_verdict`:** remove the `location` gate (no longer reads an LLM location
  entry). Keeps degree/auth/clearance/dealbreakers.
- Keep `_norm_loc`/`_COUNTRY_ALIASES` (still used to normalise allowed entries + the
  resolved country label). `_mentions`/`_REMOTE_HINTS` stay for the remote cross-check.

### Worker — prompts

- **Split** `prompts/score.txt` into:
  - `prompts/score.txt` — `score_header` only (Claude fit rubric).
  - `prompts/screen.txt` — `screen_header`, `screen_list_header`, `c_degree`,
    `c_authorization`, `c_clearance`, `c_dealbreakers`, `screen_footer`.
- **Delete `c_location`** entirely.
- **`prompts.py`:** load both files (`_sections("score.txt")` for `SCORE_HEADER`,
  `_sections("screen.txt")` for the `SCREEN_*` / `SCORE_C_*` constants). Drop
  `SCORE_C_LOCATION`. Exported constants otherwise unchanged, so `score.py` imports
  are unaffected (minus the removed `SCORE_C_LOCATION`).

### Worker — dependency

- Add **`pycountry`** to the worker dependencies (offline data; safe to import at module
  load; hermetic tests stay network-free once installed). Ensure the test/CI environment
  installs it.

### Docs (same commit)

- **SPEC §7 `score.py`:** location is now a deterministic code gate off `posting["location"]`
  (pycountry), not an LLM extraction; the screen prompt no longer carries a location clause.
- **SPEC §5 flow / §7 prompts:** note the two prompt files (score.txt / screen.txt).
- **CHANGELOG:** entry under Changed.
- **PROGRESS:** no open-work entry needed (this closes a fresh finding, not a tracked gap),
  unless bare-city leak is worth logging as a known limitation.

## Impact & operational risks

- **Behavior change:** location decisions move from the 4B to code. Expected effect is
  *more* correct discards (foreign roles with a country token now reliably dropped) and
  no new wrong-drops (err toward keep preserved). US roles with a state-only string
  ("New York, New York") keep via US-precedence / absence-of-foreign.
- **Known limitation (accepted):** a bare foreign city with no country token and no
  recognizable subdivision leaks to the Claude score (err toward keep). Rare in the
  observed feed.
- **New dependency:** `pycountry` in a deliberately dependency-light worker — accepted by
  the user for exhaustive recognition.
- **Collision names** (US state == country, e.g. Georgia): handled by US-precedence.

## Testing / verification

- **Rewrite the existing location tests** in `tests/test_score.py`: they currently feed
  the LLM-extracted location entry via `_screen_resp({"location": {...}})`. Since location
  leaves the LLM, drive `posting["location"]` (the board string) instead:
  - `"Shanghai, China"` → disqualified; `"Sydney, Australia"`,
    `"Amsterdam, North Holland, Netherlands"`, `"London, England, United Kingdom"` → disqualified.
  - `"Chicago, Illinois, United States"`, `"New York, New York"` → kept.
  - `"Atlanta, Georgia"` (collision) → kept; `"Remote - US"` → kept; `""`/`None` → kept.
- **Screen-call assertions:** a `locations`-only candidate makes no Ollama call (extend
  the internship-only precedent).
- **Prompt split:** the `prompts.py` constants still resolve from the two files (existing
  import-time load is the check; add a smoke assert if useful).
- Full worker suite green; coverage gate (`fail_under = 85`) holds; schema-drift guard
  unaffected (no schema change).
- **Live check:** re-run the fetch→screen probe on Optiver; "AI Researcher @ Shanghai,
  China" must now be DISQ on location.

## Sequencing (suggested)

1. Add `pycountry` dep; split the prompt files + update `prompts.py` (drop
   `SCORE_C_LOCATION`).
2. Add `resolve_location`; wire it into `score_posting`; remove `_check_location` +
   the LLM location gate + `_candidate_block` location clause.
3. Rewrite/extend the location tests; run the full suite.
4. Update docs (SPEC/CHANGELOG). 5. Live probe re-check on Optiver.
