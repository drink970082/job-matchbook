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

- **Fetch-time filtering — by date + per-board settings** — `[M · design call · NEXT UP]`. Add
  deterministic, pre-scorer filters applied at FETCH time to cut volume/noise (the only fetch-time
  filter today is the coarse *global* `title_filter`):
  - **By date** — drop postings whose `posted_at` is older than a max-age (keep the last N days).
    Postings already carry `posted_at`; nothing filters on it yet. Note dateless boards fall back to
    the scrape date (SPEC §8), so a max-age keeps those through.
  - **Per-board settings** — move keep-rules onto the watchlist row so each board carries its own
    query / keywords / locations / max-age (e.g. Amazon's `base_query` is hardcoded in the recipe
    today, and high-volume boards like Amazon/Microsoft flood the scorer). Set at onboard time from
    the candidate **profile / `config.yaml`**.
  **Design forks (take to the operator):** where filters live — global `config.yaml` vs a new
  nullable `filters` JSON column on `watched_companies` (Prisma-owned, mirrored in the drift
  fixture) vs both (global default + per-board override); how they compose with the existing
  `title_filter` + `candidate.*` disqualifiers and the LLM scorer (stay a cheap deterministic
  pre-filter — **no LLM at fetch** — the scorer still does the real relevance judging); and whether
  "from my profile" means the `onboard-board` skill / web UI *generates* the per-board filter or the
  operator hand-sets it. Ties into [[design-work-preference]] — research the forks, operator decides.
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
  show only in the DB/logs.
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
