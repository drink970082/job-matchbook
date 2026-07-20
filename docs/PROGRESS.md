# ATS — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.

**Current phase:** v1.0.0 cut on `dev` (2026-07-20), CI fully green (web / worker /
e2e). Feature-set complete and validated live end-to-end; testing/CI hardened
(coverage gates, integration + Playwright e2e, schema-drift guard). **"Hardened"
means test/CI hardening, not security hardening** — accepted residuals are documented
in SPEC §11 + `SECURITY.md`; genuinely open items are below.

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

- 🚧 **Publish v1.0.0** — operator steps remaining: flip the GitHub repo
  private → **public**, merge `dev` → `master`, tag `v1.0.0` on master. (Version
  strings + CHANGELOG are already cut; see [CHANGELOG](../CHANGELOG.md).)
- 🚧 **Run the pipeline as a daemon** — the recurring 24h scheduler
  (`python -m ats_worker.run`) remains the operator's standing launch step; passes
  are currently run by hand.
- 🚧 **General-purpose pivot (in progress).** Broadening the product from a quant/SWE
  niche to any field. **Shipped:** user-configurable job categories (`app_settings`,
  first-run modal + header editor, free-form labels); a persona-neutral
  `personal_profile.txt.example` + TARGET/ANTI-TARGET/STAGE docs in `resume/README.md`;
  an `onboard-me` skill scaffold (categories only). **Remaining:** expand `onboard-me`
  to the full profile/résumé/config interview (Stage 2); non-tech discovery feeds are
  **deferred** (the watchlist already covers any company — decide before building). By
  design the fit-scoring prompt (`score.txt`) is **left untouched** — generality lives in
  `personal_profile.txt`, and scorer-prompt edits have destabilized verdicts before.

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Two axes:**
*severity* sets the bucket (a shipped defect that loses prepared work ≠ an unbuilt
nice-to-have), and within each bucket items run **easiest → hardest** with an effort tag —
**XS** (~an hour) · **S** (~an afternoon) · **M** (~a day + a design call) · **L**
(multi-day / new dependency / architectural). Blocked items name their blocker.

### Defects — shipped behavior that is wrong (should fix)

*Empty — no known shipped defects open.* (All previously tracked defects were fixed;
history in the [CHANGELOG](../CHANGELOG.md).)

### Unverified / deferred — behavior may be fine, but nothing proves it, or a decision is pending

- **Rename the GitHub repo** — `[XS · blocked on target name]`. Local checkout dir
  is already `ats`; the GitHub remote is still `drink970082/personal-ats`. Decided
  to rename, target name not yet picked (operator deferred 2026-07-20) — once
  chosen, rename on GitHub and update the README badge/link + `SPEC.md` §1 repo URL
  (GitHub redirects the old clone URL once, not indefinitely).
- **Watchlist slug host-safety check** — `[XS]`. Slug *structure* is validated at all
  three write boundaries, but `phenom`/`workday` pack a hostname as the slug's first
  segment, so an internal-IP host passes (accepted meanwhile — SPEC §11). Closable by
  calling `is_safe_public_url` on the built host inside `phenom._parts` /
  `workday._parts`.
- **Stale-mount recovery is unobserved end-to-end** — `[S · needs a live drill]`. The
  `/api/health` probe + Docker `healthcheck` + `autoheal` sidecar are wired, the
  healthy path is confirmed, and the 200/503 logic has a unit test (`health.test.ts`).
  Unproven: recovery from an *actual* WSL2 stale-bind-mount event — never observed,
  not unit-testable (needs a live event or manual drill). (SPEC §6.)
- **SSRF residual shapes** — `[M]`. Three shapes remain reachable (browser-path
  redirect GET · DNS-rebinding · statically-internal hostnames — accepted meanwhile,
  SPEC §11). Closing the DNS shapes needs a resolve-then-check with a TOCTOU-safe
  connect; closing the browser-path GET needs an intercept-before-connect mechanism
  Playwright's routing API doesn't expose for navigations.
- **`applications` has no DB `@@unique(company_name, job_title)`** — `[M · deferred ·
  deliberate; waits on operator]`. Three transactional app-code paths hold the dedupe
  invariant (`addApplication`, `markJobApplied`, `importApplicationsCSV`). The hard
  constraint needs a backup + dedupe migration first — the real table may hold
  legitimate duplicate rows (re-applications), so `prisma db push` can't build the
  index without `--accept-data-loss`. Deferral operator-confirmed 2026-07-19.
- **No schema migration path** — `[L]`. `prisma db push` keeps no migration history,
  so a *destructive* change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)

### Enhancements — not built, optional

- **Discovered Jobs README screenshot** — `[XS]`. The prose is now expanded to Track
  parity (bucket triage, the per-row "why" subline, the fit-assessment modal, bulk
  actions). Still missing: an inline screenshot of the tab to match the "Track"
  images. Needs a seeded throwaway DB (never the real `db/applications.db` — see the
  privacy note in §11/CHANGELOG on the existing screenshots) and a richer fixture than
  the e2e seed, which only populates the Matched + Discarded buckets.
- **Adjust dev/release workflow** — `[? · design call · scope not yet set, DO NOT
  EXECUTE until the operator says so]`. Branch management, tagging, and
  version-control/GitHub workflow conventions flagged as needing a change
  (2026-07-20), but the operator explicitly deferred specifics — hold this open,
  discuss and scope it in a future session before touching `DEVELOPMENT.md` §6 /
  `CONTRIBUTING.md` / any GitHub settings.
- **Fetch-time filtering — Phase 2 (per-board settings)** — `[M · design call]`.
  Phase 1 shipped (global `max_age_days` + `title_exclude` drops, and the deterministic
  intern/location gates hoisted ahead of the Ollama call on the watchlist path — see
  `docs/superpowers/specs/2026-07-20-fetch-time-filtering-design.md`). Still open: move
  keep-rules onto the watchlist row so each board carries its own query / keywords /
  locations / max-age (Amazon/Microsoft flood the scorer). **Design forks:** a nullable
  `filters` JSON column on `watched_companies` (Prisma-owned + drift fixture) vs staying
  global-only; source-side query narrowing (recipe `base_query` — the only lever that
  cuts the scrape itself); and whether the `onboard-board` skill / Watchlist UI generates
  the per-board filter or the operator hand-sets it. Ties into [[design-work-preference]].
- **Privacy-guard CI test** — `[S]`. A small test alongside `check_schema_drift`
  asserting no secrets / PII are committed (idea mined from
  `MadsLorentzen/ai-job-search`'s `security_guards.py`; echoes
  [[user-security-privacy-prefs]]).
- **Mark dead postings `expired`** — `[S]`. Fetch hygiene worth mirroring from the
  same reference: a dead / redirected / expired posting gets marked, never scored
  from its title alone.
- **`onboard-board` skill — eval iteration 2** — `[M · optional]`. Re-run the
  skill-creator eval loop on the add-or-fail flow (with-skill agents add to a
  *throwaway* DB via `--db`) with tougher/undocumented boards — iteration 1 hit 100%
  pass on both configs, so it measured speed (−42% time / −18% tokens), not
  correctness.
- **More board adapters** — `[M · pick a target]`. The adapter pattern
  (`fetch/<source>.py` + `ADAPTERS`/`VALID_SOURCES`, or `fetch_one` in
  `DETAIL_SOURCES`) makes new sources cheap. Leads: LinkedIn's public `jobs-guest`
  endpoint (unauthenticated, zero-dep; personal-use / ToS caveat, keep volume low);
  JobSpy as a possible fallback aggregator.
- **Remaining feed coverage (the `feed_unresolved` long tail)** — `[M · needs
  iCIMS/ByteDance feed routers]`. Resolution sits at ~78% after tier 1. What's left
  is iCIMS + ByteDance — both plain HTTP (iCIMS ships as a list adapter, TikTok as a
  `custom` recipe), but closing the *feed* tail still needs a `resolve_url` host
  router + a per-listing `fetch_one`, which the list adapters don't provide.
  **Dropped:** greenhouse embed-token (job id only, no board slug); SuccessFactors
  (absent from feed).
- **Deployment / monitoring** — `[L · open-ended]`. `ats-web` has a DB-reachability
  healthcheck + `autoheal` (SPEC §6), but there's no metrics/alerting beyond the
  per-job Telegram notification, and the **worker** has no healthcheck — its failures
  show only in the DB/logs. Includes the deferred scraper **canary self-tests** and
  proactive Telegram/banner alerting for silently-broken scrapers (SPEC §9 points
  here).
- **AI fetch+score fallback for unparseable JDs** — `[L · optional]`. Where text
  extraction fails (JS-rendered / bot-walled / odd markup), let the scorer's model
  fetch the job page and score fit directly from the raw page, bypassing
  parse-then-score. Candidate landing spot for the iCIMS/ByteDance tail if a plain
  fetch isn't enough.

#### Architecture / maintainability

- **Cross-service drift — partially guarded** — `[M]`. `test_source_enums_sync.py`
  guards the cheaply-comparable duplicated items (source enums + the low-context
  length literal). **Still unguarded (deliberate scope call — fragile, low value):**
  the `pipeline_status` string literals (scattered across worker + web) and the full
  notify / matched verdict-predicate SQL (`db.py` vs `actions.ts`) — these stay
  documented-not-guarded, hand-duplicated with "must match" comments only.
- **`requirements-dev.txt` duplicates base pins** — accepted (no include mechanism
  exists without adding tooling), but the duplication bit once — see the
  [CHANGELOG](../CHANGELOG.md) geonamescache CI fix. **Standing rule:** any new
  module-load or test-exercised runtime import MUST be mirrored into
  `requirements-dev.txt` in the same commit that adds it to `requirements.txt`.

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
  bucket, placed **easiest-first** with an effort tag (`[XS/S/M/L · blocker]`). Keep
  severity honest: defects (broken) above unverified properties above enhancements
  (optional).
