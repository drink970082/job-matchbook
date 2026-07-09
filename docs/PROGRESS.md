# ATS — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.

**Current phase:** v0.2.0. Feature-set complete; testing/CI hardened (coverage
gates, integration + Playwright e2e, schema-drift guard). **"Hardened" here means
test/CI hardening, not security hardening** — several known reliability gaps remain
open (see [Open work](#open-work)), including a notify-failure defect that can bury a
high-scoring match. Nothing is in flight. (Recent changes: see the
[CHANGELOG](../CHANGELOG.md).)

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

- 🚧 **Notify-failure defect fix — bounded retry (cap 3) at the notify stage.**
  Approved spec:
  [`superpowers/specs/2026-07-09-notify-retry-design.md`](./superpowers/specs/2026-07-09-notify-retry-design.md).

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Graded by
severity:** a shipped defect that silently loses prepared work is a different kind of
thing from an unbuilt nice-to-have, and the two should not read at the same weight.

### Defects — shipped behavior that is wrong (should fix)

- **`failed` is a dead-end, and a transient notify failure buries a high-scoring
  match.** Any stage exception marks a row `failed`, and nothing transitions it back.
  `run_notify` wraps the Telegram send in try/except, so a *transient* send error on a
  `scored ≥ threshold` posting marks it `failed` — and because the default
  Discovered-Jobs queue is `{scored, notified}`, that match vanishes from the default
  view and is never re-notified. Recovery is manual (filter to `failed`/`all`, reopen
  → re-notify). The `attempts` column is incremented on failure but **auto-retry is
  not implemented** — `attempts` is recorded, never acted on. **The tailoring removal
  made the clean fix cheap:** notify is now a single atomic `sendMessage` (no PDF
  second send), so a failed send sent nothing — the row can simply be left `scored`
  and retried next pass with no double-alert risk. Alternatives: wire the auto-retry
  `attempts` anticipates, or add a "needs attention" view for `failed`. (SPEC §9,
  "Failure handling and recovery limits.")

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
