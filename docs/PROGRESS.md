# ATS — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.

**Current phase:** v0.2.0. Feature-set complete; testing/CI hardened (coverage
gates, integration + Playwright e2e, schema-drift guard). **"Hardened" here means
test/CI hardening, not security hardening** — several known reliability/security
gaps remain open (see [Open work](#open-work)), including one shipped data-loss
defect and an untested security guard. Nothing is in flight right now. (Most recent
change: feed-coverage Tier 1 — see [CHANGELOG](../CHANGELOG.md); remaining coverage in
[Enhancements](#enhancements--not-built-optional).)

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

🚧 Nothing in flight. (Starting work → add a line here; see
[How to update](#how-to-update).)

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Graded by
severity:** a shipped defect that silently loses prepared work is a different kind of
thing from an unbuilt nice-to-have, and the two should not read at the same weight.

### Defects — shipped behavior that is wrong (should fix)

- **`failed` is a dead-end, and a transient notify failure buries already-tailored
  work.** Any stage exception marks a row `failed`, and nothing transitions it back.
  Worse: `run_notify` wraps the whole Telegram send in try/except, so a *transient*
  send error on an *already-tailored* posting (PDF written, `resume_path` set) marks
  it `failed` — and because the default Discovered-Jobs queue is
  `{scored, tailored, notified}`, that high-score posting vanishes from the default
  view and is never re-notified. **This is data loss of prepared work from the
  user's default view;** recovery is manual (filter to `failed`/`all`, reopen →
  re-tailor → re-notify). The `attempts` column is incremented on failure but
  **auto-retry is not implemented** — `attempts` is recorded, never acted on. The fix
  is one of: wire the auto-retry `attempts` anticipates; let notify failure leave the
  row at `tailored` (retried next pass); or add a "needs attention" view for
  `failed`. (SPEC §9, "Failure handling and recovery limits.")

### Unverified / unguaranteed properties — behavior may be fine, but nothing proves it (should address)

- **Path-traversal guard has no automated test.** The 403 guard in
  `api/resume/[id]/route.ts` is code-only; no test exercises it. (SPEC §9
  traceability, marked ⚠.)
- **Stale-mount auto-recovery is unverified end-to-end.** The `/api/health` probe,
  Docker `healthcheck`, and `autoheal` sidecar are wired and the *healthy* path is
  confirmed (`ats-web` reports `healthy`, the sidecar monitors), but recovery from an
  *actual* WSL2 stale-bind-mount event has not been observed, and `/api/health` has
  no automated test. (SPEC §6.)
- **Chart-data actions have no automated test.** `getStatusFlow`,
  `getTimelineData`, and `getCategoryData` (`lib/actions.ts`, feeding the
  Sankey / heatmap / donut) are exercised by no unit, integration, or e2e test —
  only their components render. A regression in the aggregation would pass CI.
- **Resume non-fabrication has no deterministic gate.** "Never fabricates" is
  enforced only by the `FABRICATION_GUARD` prompt plus the human reviewing the PDF;
  the sole deterministic gate in the tailor loop is page count. A defensible check
  could *warn* (not hard-block) on numbers / years / proper nouns present in the
  tailored resume but absent from `master.tex`. (SPEC §9, marked ⚠.)
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
  Workable 7 ✅, long-tail bespoke ~remaining. **Deferred** (need fragile scraping):
  **iCIMS** (`window._jibe`), **embedded greenhouse** (scrape board token from the
  custom-domain embed page → reuse the greenhouse adapter), **ByteDance/TikTok**
  (bespoke single-employer). **Dropped:** greenhouse embed-token (URL has only a job
  id, no recoverable board slug — verified no public endpoint); SuccessFactors (absent
  from the feed). **Demoted:** a direct Workday CXS per-job fetch would fix the
  `jobReqId`-substring fragility + whole-board N+1 but buys **0** coverage (Workday is
  already fully resolved), so it's robustness-only.
- **More board adapters.** The adapter pattern (`fetch/<source>.py` + `ADAPTERS` +
  `VALID_SOURCES`; or `fetch_one` for a per-listing source in `DETAIL_SOURCES`) makes
  new sources cheap; JobSpy was noted as a possible fallback aggregator.
- **Deployment / monitoring.** `ats-web` now has a DB-reachability healthcheck +
  `autoheal` auto-restart (SPEC §6), but there are still no metrics or alerting
  beyond the per-job Telegram notification, and the **worker** has no healthcheck;
  failures there are visible only in the DB / logs.
- **Batch / smarter tailoring.** Tailoring is per-posting and serial; no batching or
  caching of near-identical JDs.

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
