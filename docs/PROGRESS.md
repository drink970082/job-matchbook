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

🚧 **Analyze screen + score quality (queued — next session).** The pipeline runs
clean (0 failures over 1169), but the *quality* of its two judgments is unmeasured.
Evaluate against the first live cold pass (2026-07-13):

- **Screen** — is the ~45% screen-out correct? Sample the **527 discarded** for
  false-positives (good roles wrongly cut on location/visa/internship) and check the
  deterministic gates (pycountry location, internship title regex) against the Ollama
  hard-requirement call.
- **Score** — is the 0–100 scale calibrated to the 75 threshold? The scorer is strict
  (**11/642 ≥75, ~1.7%**); review the **30 near-misses (60–74)** for false-negatives,
  confirm the 11 matches are genuine, and sanity-check the `recommended_resume`
  (swe vs quant_dev) choice per posting.
- Deliverable: a calibration read on both stages + any threshold / prompt / gate
  adjustments worth making.

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Graded by
severity:** a shipped defect that silently loses prepared work is a different kind of
thing from an unbuilt nice-to-have, and the two should not read at the same weight.

### Defects — shipped behavior that is wrong (should fix)

_No known defects._

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
