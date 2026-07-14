# Design: Screen + score quality fixes — six defects from the first live audit

**Status:** approved (user fork decisions, 2026-07-13 session), ready to plan.
**Date:** 2026-07-13.

## Problem / motivation

The 2026-07-13 cold pass ran clean *mechanically* — a consistency check passed all
structural invariants (parse, type, status↔detail). But a manual spot-audit of 8
postings surfaced **6 quality defects** in the two LLM judgments (now filed in
[`PROGRESS.md`](../../PROGRESS.md) → Defects). They split cleanly along the
two-model seam:

- **Screen (Ollama hard-req gate)** — *false negatives* that silently drop reachable
  US roles (a NYC job killed on a boilerplate "sponsor" match; a NYC job killed
  because the gate read only the last of its three locations).
- **Score (Claude fit)** — *miscalibrations* that rank real matches too low (missing
  "nice-to-have" C++ tanks a strong Python role; a new grad's unreachable 4-yr role
  outscores the reachable entry-level ones; location bleeds into the fit number).

Fixing them is the difference between a pipeline that *runs* and one whose verdicts
the operator can trust before applying by hand.

## Goal

Correct all six defects with the **smallest, most verifiable change per defect**:
deterministic Python + unit tests for the screen-gate bugs; sharpened rubric/context
for the score bugs. Verify by re-running each stage over the existing 1,169-row DB
and tabulating how verdicts flip.

## Non-goals

- **Not re-architecting the screen/score split.** The two-model seam stays.
- **Not changing the notify threshold (75)** as part of this. Revisit only if D6
  re-scoring shows genuine good-fits still clustering below it.
- **Not a full re-score of all 642 rows** until fixes settle (Claude $). Validate on
  the flagged set + a stratified sample.

## Two streams

| Stream | Nature | Verify | Defects |
|---|---|---|---|
| **1 — Screen** | deterministic Python, TDD | re-run screen (local Ollama, ~$0), count flips | D1 auth, D2 location |
| **2 — Score** | rubric / call-context edits | re-score flagged + sample (Claude, small $), compare distribution | D3 seniority, D4 plus-skills, D5 location leak, D6 calibration |

**Order: Stream 1 first** — higher severity (false negatives lose real roles),
cheaper to verify, and **D5 depends on D2** (location handling).

---

## Stream 1 — Screen (deterministic)

### D1 — Authorization disqualifies on boilerplate

- **Symptom:** reachable US roles discarded as `authorization: no visa sponsorship
  offered` — Tower Research SWE NYC (id=986), WorldQuant Frontend (id=1071).
- **Root cause:** `_check_authorization` fails when `explicit_no AND
  _mentions(description, _SPONSOR_HINTS)`. `_SPONSOR_HINTS` = loose substrings
  (`"sponsor"`, `"visa"`, `"citizen"`, …) that match unrelated boilerplate —
  `"sponsor"` in **"company-sponsored sports teams"** (id=986), `"citizen"` in the
  EEO line **"…citizenship, national origin, disability…"** (id=1071). The guard
  meant to confirm the JD *discusses* sponsorship is defeated, so the 4B model's
  invented `"no"` (emitted despite the screen prompt's explicit "MOST postings never
  mention sponsorship — those are 'unknown', NEVER 'no'") passes through.
- **Fix:** stop trusting the 4B yes/no. Disqualify **only when the JD literally
  contains an explicit no-sponsorship phrase.** Replace the
  `explicit_no AND _mentions(hints)` test with a deterministic phrase match over the
  normalized (lowercased, whitespace-collapsed) description:
  `NO_SPONSOR_PHRASES = ("will not sponsor", "does not sponsor", "do not sponsor",
  "cannot sponsor", "unable to sponsor", "not able to sponsor", "no visa
  sponsorship", "no sponsorship", "without sponsorship", "not provide sponsorship",
  "no immigration sponsorship", "must be authorized to work without sponsorship")`
  (a substring-match phrase set over the normalized text, not a regex). Fail iff
  `_needs_sponsorship(cand)` **and** a phrase is present; the model's
  `offers_sponsorship` is **no longer used** for the disqualification decision. None
  of the boilerplate above contains any of these phrases, so the false positives
  vanish. Positive "we sponsor" case is unaffected (still keeps).
- **Test (TDD, red first):** real stored descriptions for id=986 / id=1071 → PASS;
  a synthetic "We do not offer visa sponsorship for this role" → FAIL; existing auth
  tests stay green.
- **Verify:** re-run screen over the 156 authorization-killed rows; count flips to
  pass; spot-check that rows staying failed contain a real phrase.

### D2 — Location gate honors the wrong location

- **Symptom:** a multi-location role with a US city discarded (Tudor NYC/London/
  Singapore → "on-site in Singapore", id=1009); foreign-city roles with **no** US
  location kept (DRW "London" id=324 → scored 62; WorldQuant "Hanoi OR Ho Chi Minh
  City" id=1071 → `location: pass`).
- **Root cause:** `resolve_location` step (E) inspects only the **last token** and
  resolves it via **pycountry (countries, not cities)**. A foreign *city* ("London")
  isn't a country → not seen as foreign → kept. A US *city* ("New York City") isn't
  a state name/code → not seen as US; and only the last token ("Singapore") is
  checked → discarded. Token order and city-vs-country decide the verdict, so it's
  *unreliable*, not merely strict (contrast id=885 "London, Montreal, Singapore",
  correctly discarded only because Singapore happens to be a country *and* last).
- **Fix (fork resolved: user chose the city-dataset dependency):** add
  **geonamescache ≥3.0.1** and resolve **every token**, not just the last.
  - New helper `_token_country(token) -> str | None`: US-state → `"US"`; else
    pycountry country lookup; else geonamescache city → `countrycode` (on
    ambiguous names, prefer the highest-population match, and bias to `US` if any
    match is US). Returns ISO alpha-2 or `None`.
  - Rewrite the (C)–(F) tail: resolve all tokens; **keep if any token is an allowed
    country / allowed city-or-state / remote-allowed; discard only if ≥1 token
    resolves and none are allowed** (reason names the first foreign token); if no
    token resolves, **keep** (err toward keep, as today).
  - Preserve step (A) missing→keep, (B) remote, and the US-postal-vs-ISO guard
    (`IL`/`CA`/`GA` are US states, not Israel/Canada/Gabon) — `_is_us_state` wins
    before geonamescache.
  - Build the city→country index once at module load (lazy, cached; ~25k cities,
    a few MB — one-time cost, fine for the batch worker).
  - Add `geonamescache>=3.0.1` to `apps/worker/requirements.txt`.
- **Supersedes** part of [`2026-07-07-location-gate-design.md`](./2026-07-07-location-gate-design.md)
  (the last-token / pycountry-only approach); update that lineage note and SPEC §.
- **Test (TDD, red first):** id=1009 (allowed USA) → keep; id=324, id=1071 →
  discard; id=885 → **stays** discarded (regression); "Austin, Texas" → keep;
  an ambiguous name with a US match → keep. **The entire existing location-gate
  test suite must stay green** (postal-code collisions especially).
- **Verify:** re-run screen over the 350 location-killed rows + the kept rows;
  tabulate flips both directions; confirm existing tests pass.

---

## Stream 2 — Score (rubric / call-context)

`score.txt` already lists a "seniority gap" as a heavy disqualifier and asks for
must-have vs surface-keyword weighting — so these are **sharpenings, not
inventions**. Each is validated **statistically** (re-score + compare), except D5
which is a deterministic payload change with a real unit test.

### D3 — Seniority beyond a new grad under-penalized

- **Symptom:** unreachable senior roles score mid — Squarepoint Quant Dev (Python)
  4+ yrs (id=904 = 62), Cubist SWE-Data 3+ yrs (id=177 = 63). At Squarepoint the
  *reachable* Graduate/Junior roles were discarded (non-US) while this one survived.
- **User decision:** keep visible but **rank low (heavy score floor)** — not a hard
  screen discard.
- **Root cause:** the model *notes* the gap in `reasoning` but the "60-74 partial
  fit: … a real gap in seniority" band lets a strong-domain senior role land at 62.
  The penalty is too soft.
- **Fix:** sharpen the rubric so a **material seniority excess is a weak-fit
  disqualifier, not partial.** Add to `score_header`: *"A seniority mismatch in
  either direction is disqualifying, not partial: if the role requires materially
  more experience than the candidate has (e.g. a new grad against a role wanting 3+
  years), score it weak (0–30) even when domain and skills match well."*
- **Backstop (deferred):** a deterministic post-score cap keyed on an extracted
  required-YOE — add **only if** prompt-only proves leaky on re-score. ponytail:
  try prompt first.
- **Validation:** re-score id=904, id=177 + peers; expect ≤ ~30.

### D4 — Plus / preferred skills penalized like requirements

- **Symptom:** HRT SWE-AI Tools (id=427 = 66) — strong Python/AI-tooling core,
  docked on missing C++/UNIX-internals that the JD lists only as pluses.
- **Root cause:** `matched/missing_keywords` don't separate must-have from
  nice-to-have; the model folds pluses into "missing core" and drags the score,
  even though the rubric says missing nice-to-haves ⇒ 75–89.
- **Fix:** add to `score_header`: *"Distinguish must-haves from nice-to-haves.
  Missing a nice-to-have (a 'plus', 'bonus', 'preferred', or a secondary language
  like C++ where the core is Python) should barely move the score; only missing
  MUST-HAVES are real gaps."* No schema change (keep single `missing_keywords`).
- **Validation:** re-score id=427; expect ≥75 if the core genuinely matches.

### D5 — Location leaks into the fit score

- **Symptom:** the same role posted per-city scores differently and inconsistently —
  Cumberland London (id=324 = 62) *above* Chicago (id=323 = 52); Prediction Markets
  Chicago (id=322 = 72) above London (id=320 = 35).
- **Root cause:** the JOB section fed to the SCORE call includes a `Location:` line
  (`_job_section`), so the model factors geography into fit though the prompt never
  asks it to. Location belongs to the screen.
- **Fix (deterministic, preferred):** **omit `Location:` from the JOB context sent
  to the SCORE call** (the screen extracts degree/auth/clearance from prose, not
  location, so location can be dropped from scoring safely). Smallest change: an
  `include_location=False` on the score call's section builder; confirm whether
  `_job_section` is shared and split if so. Belt-and-suspenders prompt line: *"Do
  not consider work location or geography; it is handled separately."*
- **Note:** once D2 gates location, non-US per-city dupes never reach scoring; this
  ensures the surviving US dupes (NYC vs Chicago) score on merit.
- **Test:** unit — the score-call payload contains **no** `Location:` line.
- **Validation:** re-score the US per-city dupes; expect convergence.

### D6 — Fit scale compressed / too strict

- **Symptom:** 59% of scores land on 6 low values (5/8/15/22/28/32); only 11/642
  clear 75; near-misses too tight (Prediction Markets Chicago id=322 = 72).
- **Root cause (hypothesis):** partly *emergent* from D3/D4 (senior roles and
  plus-skill penalties both suppress). Genuine weak fits *should* score low (boards
  are noisy) — so not all compression is wrong; the concern is real near-matches
  sitting at 60–74.
- **Fix approach: measure after D3/D4/D5 land — do not blind-tune.** Re-score the
  flagged set + a stratified sample; **if** genuine good-fits still cluster below 75,
  then a **deferred fork:** (a) loosen the rubric bands, or (b) lower the notify
  threshold. Decide with data in hand.
- **Validation:** compare score distribution before/after; target — genuine matches
  reach ≥75, weak fits stay low, less pile-up on the modal values.

---

## Testing & verification

- **Stream 1:** pytest fixtures per defect using the **real stored descriptions /
  location strings** as repro (red → green); existing screen + location-gate suites
  stay green; new helpers (`_token_country`, the phrase gate) get their own tests;
  worker coverage gate `fail_under = 85` holds. Then re-run the screen over the DB
  (local Ollama, ~$0) and tabulate verdict flips.
- **Stream 2:** edit `score.txt` (+ D5's deterministic payload change with its unit
  test); re-score the ~8 flagged rows + a stratified sample via Claude (small $);
  compare scores/distribution to the targets above. No unit test asserts the LLM
  judgment itself beyond D5's payload check.
- **Docs discipline:** as each defect closes, move it out of `PROGRESS.md` → add a
  `CHANGELOG.md` entry and update the matching `SPEC.md` section (location gate,
  scoring rubric), same commit; update the 2026-07-07 location-gate lineage.

## Deferred forks (decide with data, not now)

- **D3** deterministic YOE cap — only if the prompt alone leaks on re-score.
- **D6** rubric-loosen vs threshold-drop — only if good-fits still sit < 75.

## Risks

- **geonamescache name ambiguity** (same city name, multiple countries) → mitigate
  with population-max + any-US-keeps bias; unresolved tokens keep, so no *new* false
  negatives are introduced.
- **Prompt tuning (D3/D4/D6) can regress unaudited rows** → validate on a stratified
  sample, not just the 8 flagged, before declaring done.
