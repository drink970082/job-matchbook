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
| **2 — Score** | structured scorecard (schema + prompt + web render) + rubric/context | unit tests (scorecard, D5 payload) + re-score sample, compare distribution | scorecard (D3 seniority + D4 plus-skills), D5 location leak, D6 calibration |

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

## Stream 2 — Score (structured scorecard + rubric)

The centerpiece is a **reasoning redesign**: the fit call's free-text `reasoning`
blob is replaced with a **structured scorecard** the model must fill in — auditable
*and* the vehicle that fixes D3 and D4 structurally rather than by prose nudge (user
fork decisions, 2026-07-13). D5 and D6 ride alongside. Validated **statistically**
(re-score + compare), except D5 (deterministic payload change with a unit test) and
the scorecard schema/render (deterministic, unit-tested).

### S2.1 — Score scorecard (redesign; subsumes D3 + D4)

- **Problem.** The fit output is `matched_keywords` + `missing_keywords` (flat, no
  required-vs-preferred distinction) + `reasoning` (a wall-of-text paragraph) — a
  "disaster to audit": you can't see at a glance which factor drove the score,
  missing "plus" skills read the same as missing must-haves (**D4**), and a
  seniority gap is buried in prose (**D3**). Only `JobDetailModal` renders these;
  Telegram and `DiscoveredJobsTable` don't (the table reads only
  `disqualified`/`disqualification_reason`), so the blast radius is one component.

- **New `score_detail` shape (non-disqualified rows)** — replace the flat keyword
  lists and prose with an `assessment` object; the numeric `score` stays in the
  `job_postings.score` column:
  ```json
  "assessment": {
    "seniority": {"verdict": "match|too_junior|too_senior", "note": "<short>"},
    "domain":    {"verdict": "match|adjacent|mismatch",      "note": "<short>"},
    "must_haves":    {"met": ["..."], "missing": ["..."]},
    "nice_to_haves": {"missing": ["..."]},
    "summary": "<one-line bottom line>"
  }
  ```
  `recommended_resume` and the `screen` block are unchanged. Discarded rows are
  unchanged (fit is skipped → no `assessment`). `matched_keywords` /
  `missing_keywords` / `reasoning` are **dropped from new rows** — `must_haves` /
  `nice_to_haves` and `summary` supersede them; the modal keeps a legacy fallback so
  old rows still render. No DB migration (old rows keep their old shape).

- **Schema (`_SCORE_SCHEMA` / `_score_schema`).** Add `assessment` as a required
  object (`additionalProperties:false`) with `seniority.verdict` / `domain.verdict`
  `enum`-constrained — structured outputs enforce the shape, so the model can't emit
  a freeform verdict. `score` stays a bare integer (clamp in `_coerce_score`). Drop
  `reasoning` / `matched_keywords` / `missing_keywords` from the schema.

- **Prompt (`score.txt`).** Rewrite `score_header` to ask for the scorecard:
  classify each JD requirement as must-have vs nice-to-have, emit the
  seniority/domain verdicts + short notes and a one-line summary, THEN score. Fold
  in the two rules:
  - **D3 (seniority):** *"A material seniority mismatch is disqualifying, not partial
    — if `seniority.verdict` is too_junior/too_senior with a real gap (e.g. a new
    grad against a role wanting 3+ years), score weak (0–30) even when domain and
    skills match."*
  - **D4 (plus-skills):** *"Only missing `must_haves` lower the score materially;
    missing `nice_to_haves` (a 'plus'/'preferred'/'bonus', or a secondary language
    like C++ where the core is Python) barely move it."*
  Keep "assess substance, not keyword overlap" and the 90/75/60/0 bands, now phrased
  against the structured verdicts.

- **Normalize (`_normalize_score`).** Extract + validate `assessment` (verdict enums
  in range, met/missing are string lists, summary a string); raise `ScoreError` on a
  malformed assessment (consistent with the existing fail-loud stance on a missing
  score). Stop writing the flat keyword lists.

- **Rendering (`JobDetailModal.tsx`).** Replace the flat matched/missing/reasoning
  block with an assessment card: Seniority + Domain verdict rows (chip colored by
  verdict — match=green, too_junior/too_senior/adjacent=amber, mismatch=red — +
  note), must-haves met (green chips) / missing (red chips), nice-to-haves missing
  (muted chips labeled *optional*), and the summary line. Keep the legacy
  `reasoning`/`matched`/`missing` path as a fallback. Update the `ScoreDetail`
  interface + `parseScoreDetail`.

- **Audit payoff.** Per-dimension verdicts are queryable — e.g. the whole D3 class is
  `assessment.seniority.verdict = 'too_junior' AND score > 50`.

- **Tests.** Worker: `_normalize_score` accepts a well-formed assessment and rejects
  a bad enum / missing sub-field; `_score_schema` carries the enum-constrained
  assessment. Web: the modal renders an `assessment` row set, and a legacy-shape row
  still renders via the fallback. Validation: re-score id=904 / id=177 (expect ≤30,
  D3) and id=427 (expect ≥75 once plus-skills stop dragging, D4) + a sample; eyeball
  that the scorecard reads cleanly.

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
  reach ≥75, weak fits stay low, less pile-up on the modal values. The scorecard
  (S2.1) makes this auditable per-dimension — a low score now shows *which* dimension
  (seniority / domain / must-haves) cost the points.

---

## Testing & verification

- **Stream 1:** pytest fixtures per defect using the **real stored descriptions /
  location strings** as repro (red → green); existing screen + location-gate suites
  stay green; new helpers (`_token_country`, the phrase gate) get their own tests;
  worker coverage gate `fail_under = 85` holds. Then re-run the screen over the DB
  (local Ollama, ~$0) and tabulate verdict flips.
- **Stream 2:** deterministic parts get unit tests — the scorecard schema/normalize
  (worker) and modal render + legacy fallback (web), plus D5's no-`Location:` payload
  check; worker `fail_under = 85` holds. The LLM judgment itself is validated
  **statistically**: re-score the ~8 flagged rows + a stratified sample via Claude
  (small $) and compare scores/distribution to the targets above.
- **Docs discipline:** as each defect closes, move it out of `PROGRESS.md` → add a
  `CHANGELOG.md` entry and update the matching `SPEC.md` section (location gate,
  scoring rubric), same commit; update the 2026-07-07 location-gate lineage.

## Deferred forks (decide with data, not now)

- **D3** deterministic YOE cap — only if the prompt alone leaks on re-score.
  **Resolved 2026-07-14: not needed.** The prompt floor held — id=904/177/322 all scored
  `too_junior` at ≤28 with notes citing the exact YoE gap; no deterministic cap added.
- **D6** rubric-loosen vs threshold-drop — only if good-fits still sit < 75.
  **Resolved 2026-07-14: neither.** The 20-row re-score showed the scale de-compressed
  emergently (near-miss band 9→1, 75+ 0→6); the notify threshold stays 75.

## Risks

- **geonamescache name ambiguity** (same city name, multiple countries) → mitigate
  with population-max + any-US-keeps bias; unresolved tokens keep, so no *new* false
  negatives are introduced.
- **Prompt tuning (D3/D4/D6) can regress unaudited rows** → validate on a stratified
  sample, not just the 8 flagged, before declaring done.
