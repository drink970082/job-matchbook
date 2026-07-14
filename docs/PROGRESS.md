# ATS — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.

**Current phase:** v0.2.0, **validated live end-to-end.** Feature-set complete;
testing/CI hardened (coverage gates, integration + Playwright e2e, schema-drift
guard). **"Hardened" here means test/CI hardening, not security hardening** — a few
unverified properties remain open (see [Open work](#open-work)). On **2026-07-13**
the full `fetch → screen → score → notify` pipeline ran against live services for
the first time: one cold pass over 39 boards → **1169** postings fetched, **~45%**
screened out (internship/location/visa), **642** fit-scored by Claude with **zero
failures**, **11** matches (score ≥75) delivered to Telegram (~$8 one-time,
~cents/day steady-state; the `recommended_resume` swe/quant_dev pick and the
Telegram `Resume:` line were both confirmed live). The recurring 24h scheduler
(`python -m ats_worker.run`) is the operator's remaining launch step. (Recent
changes: see the [CHANGELOG](../CHANGELOG.md).)

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

🚧 **Fix the 6 audited screen/score defects (in flight, 2026-07-13).** The quality
audit of the first cold pass is **done** — the mechanical consistency check passed
all structural invariants, and a manual spot-audit filed **6 defects** (see
[Defects](#defects--shipped-behavior-that-is-wrong-should-fix) below). The fix design
is approved and speced in
[`docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md`](./superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md).
Two streams, **screen-first** (higher severity, cheaper to verify, and D5 depends on
D2):

- **Stream 1 — Screen (deterministic, TDD):** ✅ **D1** authorization phrase-gate —
  **shipped**: `NO_SPONSOR_PHRASES` explicit-phrase gate replaced the boilerplate
  `_SPONSOR_HINTS` false-positive ("company-sponsored", EEO "citizenship"); the 4B
  `offers_sponsorship` guess is no longer consulted. ✅ **D2** location via
  **geonamescache** — **shipped**: resolve every token city→country (highest-population
  match, any-US/allowed keeps, all-foreign discards, `OR`-split fixed), superseding the
  2026-07-07 last-token/pycountry gate.
- **Stream 2 — Score:** **S2.1 reasoning redesign** — replace the prose `reasoning`
  blob + flat keyword lists with a structured `assessment` scorecard (enum
  seniority/domain verdicts, split `must_haves`/`nice_to_haves`, one-line summary),
  which subsumes **D3** (seniority score-floor) and **D4** (plus-skills); **D5** drop
  `Location:` from the fit call; **D6** re-measure calibration *after* D3/D4/D5, then
  loosen rubric or lower threshold only if genuine good-fits still sit < 75.
- **Verify:** re-run the screen over the existing DB (local Ollama, ~$0) counting
  verdict flips; re-score the flagged set + a stratified sample (Claude, small $) for
  the score changes.
- **Status:** spec approved; implementation plan (writing-plans) next. On landing,
  each closed defect leaves Defects → CHANGELOG + SPEC (same commit), per the docs
  discipline below.

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Graded by
severity:** a shipped defect that silently loses prepared work is a different kind of
thing from an unbuilt nice-to-have, and the two should not read at the same weight.

### Defects — shipped behavior that is wrong (should fix)

Surfaced by the first quality audit of the 2026-07-13 cold pass (mechanical
consistency check — all structural invariants passed — plus a manual spot-audit of
8 mis-judged postings). These are quality/logic errors in the two LLM judgments,
not format bugs. Ordered by severity; posting ids are live-DB repros.

**Screen (Ollama hard-requirement gate):**

- **Seniority beyond a new grad is not gated — MEDIUM.** Roles whose hard bar is
  3+/4+ years (or "senior") pass screen and earn a mid fit score instead of being
  rejected; a new grad cannot fill them, so they are *under*-penalized. Repro:
  Squarepoint "Quant Developer (Python)" 4+ yrs (id=904, score 62); Cubist "SWE –
  Data" 3+ yrs (id=177, score 63). Sharper still: at Squarepoint the actually-
  suitable *Graduate*/*Junior* roles were discarded for being non-US-only
  (id=885/892/898), so the queue keeps the unreachable senior role and drops the
  reachable entry-level ones. **Fix (2026-07-13 decision):** score floor, not a
  screen discard — an explicit `seniority` verdict in the S2.1 scorecard redesign,
  with a rule that a material gap scores weak (≤30). Kept visible, ranked low.

**Score (Claude fit):**

- **Preferred / "plus" skills penalized like requirements — MEDIUM.** A missing
  nice-to-have (e.g. C++) drags the fit score down even when the core matches.
  Repro: HRT "SWE – AI Tools" (id=427, score 66) — strong Python/AI-tooling core,
  docked on missing C++/UNIX-internals which the JD lists only as pluses.
  **Fix:** the S2.1 scorecard splits `must_haves` / `nice_to_haves` so missing
  pluses barely move the score.
- **Location leaks into the fit score — MEDIUM.** The same role posted per-city
  scores differently and inconsistently — Cumberland ranks London (id=324, 62)
  *above* Chicago (id=323, 52); Prediction Markets ranks Chicago (id=322, 72) above
  London (id=320, 35). Location belongs to the screen; the fit score should not move
  on it. Entangles with the location-gate defect above.
- **Fit scale compressed / too strict — MEDIUM.** Genuinely strong matches land in
  the sub-75 near-miss band; 59% of all scores pile on 6 low values
  (5/8/15/22/28/32) and only 11/642 clear 75. Repro: Prediction Markets Chicago
  (id=322, 72). Systemic under-scoring risks missing real matches at the notify
  threshold.

### Unverified / unguaranteed properties — behavior may be fine, but nothing proves it (should address)

- **Stale-mount auto-recovery is unverified end-to-end.** The `/api/health` probe,
  Docker `healthcheck`, and `autoheal` sidecar are wired and the *healthy* path is
  confirmed (`ats-web` reports `healthy`, the sidecar monitors), but recovery from an
  *actual* WSL2 stale-bind-mount event has not been observed, and `/api/health` has
  no automated test. (SPEC §6.)
- **Chart-data actions have no automated test.** `getStatusFlow`,
  `getTimelineData`, and `getCategoryData` (`lib/actions.ts`, feeding the
  Sankey / heatmap / donut) are exercised by no unit, integration, or e2e test —
  only their components render. A regression in the aggregation would pass CI.
- **No schema migration path.** `prisma db push` keeps no migration history, so a
  *destructive* schema change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)

### Enhancements — not built, optional

- **Remaining feed coverage (the `feed_unresolved` long tail).** Feed-coverage Tier 1
  landed (greenhouse-EU host, Oracle, Workable, Jobvite + a per-listing detail-fetch
  path), lifting resolution ~67% → ~78% of the filtered feed. **Measurement snapshot
  (2026-06-18, live `listings.json`):** 18,207 raw → 1,394 after prefilter; 460
  unresolved by platform — Oracle 116 ✅, ByteDance/TikTok 85, iCIMS 42, greenhouse
  EU-host 23 ✅, embedded-greenhouse 54, greenhouse embed-token 17, Jobvite 14 ✅,
  Workable 7 ✅, long-tail bespoke ~remaining. Two robustness/coverage steps then landed:
  (1) the **detail-fetch robustness framework** (validate scraped postings; record
  raise/`None`/invalid failures to `feed_unresolved` as `detail_fetch_failed`; collapse
  warning) so scrapers fail *loudly*; (2) **embedded greenhouse** ✅ — an enriching
  resolver scrapes the board token from the company page and reuses the greenhouse
  adapter (recovers the server-side-embed subset; JS-injected embeds stay recorded).
  **Deferred after recon proved them not feasible via `requests`:** **iCIMS** (~42 —
  every request returns a "Human Verification" bot wall; needs a real browser, a heavy
  dep that contradicts the requests-only worker) and **ByteDance/TikTok** (~85 — no
  accessible clean API; the JD is rendered only inside fragile Next.js `__next_f` flight
  data with unreliable location, a hack not worth shipping). Revisit only with a
  headless-browser strategy. **Dropped:** greenhouse embed-token (URL has only a job id,
  no recoverable board slug); SuccessFactors (absent from the feed).
- **Feed performance ✅ (full pass ~tens of min → ~1 min).** Profiling found the feed was
  network-bound and dominated by N+1 boards (one SmartRecruiters board: ~11 min to keep
  1–2 jobs). Fixed by routing SmartRecruiters **and Workday** through per-job `fetch_one`
  in the feed (fetch only surfaced ids; Workday by `externalPath`, which also lifted
  Workday resolution) + concurrent fetching in `run_feed` (`ThreadPoolExecutor`, DB on the
  main thread; per-thread `Session` + shorter timeout). The previously-demoted Workday
  CXS-direct work thus landed — for speed, and it *gained* coverage rather than costing it.
- **Headless-browser fetch (Playwright) — the next step to unlock iCIMS + ByteDance
  (~127 listings).** Both deferred Tier-2 sources need a real browser: iCIMS gates every
  request behind a "Human Verification" bot wall, and ByteDance/TikTok renders the JD
  only client-side (no clean API; only fragile Next.js flight data server-side). Plan:
  add an *optional* Playwright-backed `fetch_one` path (new dep + headless Chromium),
  kept isolated and config-gated so the requests-only adapters and the core pipeline stay
  dependency-light — render the page, then reuse the per-source extractors (iCIMS
  `window._jibe`, ByteDance position data). The detail-fetch robustness framework already
  makes these fail loudly, and each remains its own spec.
- **`posted_at` board coverage.** The posting date is captured for
  greenhouse/lever/ashby/workday; Pinpoint exposes no board date, so `posted_at` falls
  back to the scrape date for Pinpoint rows (and any other dateless row).
- **More board adapters.** The adapter pattern (`fetch/<source>.py` + `ADAPTERS` +
  `VALID_SOURCES`; or `fetch_one` for a per-listing source in `DETAIL_SOURCES`) makes
  new sources cheap; JobSpy was noted as a possible fallback aggregator.
- **Deployment / monitoring.** `ats-web` now has a DB-reachability healthcheck +
  `autoheal` auto-restart (SPEC §6), but there are still no metrics or alerting
  beyond the per-job Telegram notification, and the **worker** has no healthcheck;
  failures there are visible only in the DB / logs.

---

## How to update

This file tracks only *movement*; it should never accumulate a wall of finished
items. When state changes:

- **Starting work** → add a 🚧 line under [In flight](#in-flight).
- **Closing a gap / shipping a feature** → remove its line here, add a
  [`CHANGELOG.md`](../CHANGELOG.md) entry (history), and update the matching section
  of [`SPEC.md`](./SPEC.md) (the capability map / behavior) — **all in the same
  commit**.
- **Discovering a new gap** → add it to [Open work](#open-work) in the right severity
  bucket. Keep the ordering honest: defects (broken) above unverified properties
  above enhancements (optional).
