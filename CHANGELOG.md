# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The current
system is described in [`docs/SPEC.md`](./docs/SPEC.md).

## [Unreleased]

### Added
- **Embedded-greenhouse feed resolution.** Companies that host greenhouse jobs on their
  own domain with `?gh_jid=` apply URLs now resolve: a new *enriching resolver*
  (`feed/embedded_gh.py`) fetches the company page, scrapes the greenhouse board token
  (`…/embed/job_board?for=<token>`), and yields `("greenhouse", token, gh_jid)` so the
  existing greenhouse adapter ingests it (dedups with direct greenhouse). It stays out
  of the pure `resolve_url`; `run_feed` calls it as an injected I/O fallback (wired only
  in `run.py`). Recovers the server-side-embed subset; JS-injected embeds return None and
  stay recorded on the unresolved board. Recon deferred the other two Tier-2 sources:
  iCIMS is bot-walled ("Human Verification") and ByteDance/TikTok exposes no clean API
  (JD only in fragile Next.js flight data) — both need a headless browser, so they're
  left recorded, not built.
- **Detail-fetch robustness (prep for Tier-2 scrapers).** Silently-broken scrapers are
  now made visible: a fetched detail posting is validated (non-empty
  `external_id`/`job_title`/`description`) before it counts, and any failed surfaced id
  (a raise, a `None`, or an invalid posting) is recorded in `feed_unresolved` as
  `detail_fetch_failed` — appearing on the existing unresolved board, grouped by host —
  instead of vanishing into `run_feed`'s swallowed per-listing exception. A detail source
  that resolves ids but keeps none also prints a one-line collapse warning. Source-agnostic
  (lives in `pipeline.run_feed`/`_detail_fetch`); no adapter changes, no schema change.
  Canary self-tests and proactive Telegram/banner alerting are deferred.
- **Feed coverage Tier 1 — Oracle / Workable / Jobvite + Greenhouse-EU host.** Lifts feed
  resolution from ~⅔ to ~78% of the filtered-active feed (measured against the live
  `listings.json`: 460 → ~300 unresolved). New: a **per-listing detail-fetch path** in
  `run_feed` (a source exposes `fetch_one` and is listed in `fetch.DETAIL_SOURCES`) for
  boards with no public list endpoint, alongside the existing per-board list adapters.
  Adapters: **Oracle Cloud HCM** (`recruitingCEJobRequisitionDetails`, +116, feed-only),
  **Jobvite** (schema.org JSON-LD, +14, feed-only), and **Workable** (widget list API,
  +7, watchlist-capable → added to `VALID_SOURCES`). One-line **Greenhouse EU host**
  (`job-boards.eu.greenhouse.io`) fix (+23). Feed-only sources can't be enumerated as a
  watchlist company, so they stay out of `VALID_SOURCES` and are excluded from promotion
  suggestions. Deferred (fragile scraping): iCIMS, embedded greenhouse, ByteDance/TikTok.
  Added a source coverage matrix to SPEC §7.1.
- **Feed coverage expansion + promotion suggestions + unresolved viewer.** Building on
  the discovery feed: (1) **Workday** feed resolution (the feed exposes the per-tenant
  `jobReqId`, matched as a substring of the board's `externalUrl` since the adapter keys
  on the GUID) and a new **SmartRecruiters** board adapter (two-step list+detail), lifting
  feed coverage from ~⅓ to ~⅔ of the filtered-active feed; (2) **promotion suggestions** —
  non-watchlisted companies whose feed-discovered postings repeatedly pass threshold
  (`tailored`/`notified`/`applied`) or get applied to are surfaced in the Watchlist tab
  with **Approve** (→ add to watchlist) / **Dismiss** (→ `promotion_dismissed`); (3) a
  read-only **Unresolved** tab grouping the `feed_unresolved` backlog by host + reason.
  Postings now carry a `company_slug` (set at ingest) so promotion grouping needs no URL
  re-parsing. Sources supported: six (added `smartrecruiters`).
- **Discovery feed (SimplifyJobs) + DB-backed watchlist.** A new opt-in feed path
  ingests the SimplifyJobs `New-Grad-Positions/listings.json` (a public GitHub data
  file, *not* a scraped board): it pre-filters cheaply on the feed's own metadata
  (`active`, `category` keep-list, explicit-no-`sponsorship`), resolves each apply
  URL back to its board `(source, slug, external_id)`, and **reuses the existing
  board adapters** to fetch the JD — keeping only the feed-surfaced postings so the
  score/tailor/notify pipeline runs unchanged. v1 resolves
  `lever`/`ashby`/`greenhouse`-direct (~⅓ of the filtered-active feed); the rest
  (Workday, SmartRecruiters, embedded-greenhouse, other ATSes) is recorded in a new
  `feed_unresolved` table as a prioritised backlog, never silently dropped. New
  worker package `ats_worker/feed/` (`simplify`/`prefilter`/`resolve`), pipeline
  stage `run_feed`, and an optional `feeds:` config block. (SPEC §5–§9.)
- **Watchlist moved into the database** (`watched_companies`) and is now managed in
  a new **Watchlist** tab in the web app (list / add / remove). The worker reads its
  watchlist from the DB and **auto-seeds it once** from `config.yaml`'s `companies:`
  when the table is empty (`--import-companies` forces a re-seed); `companies:` is
  now a one-time seed rather than the live source.
- Two more board adapters — **Workday** (CXS list + per-job detail; the `slug`
  packs `tenant/datacenter/site`) and **Pinpoint** — bringing supported sources
  to five.
- **Hard-constraint candidate screening**: an optional `candidate` block in
  `config.yaml` (years of experience, degree, work authorization, security
  clearance, locations, plus freeform dealbreakers). The local scorer screens each
  posting *semantically* and auto-discards conflicting roles, keeping the reason and
  per-requirement verdicts for the UI; a **Reopen** action reverses a discard.
- Integration test tiers (worker `run_once` over a temp SQLite; web Server Actions
  over a real throwaway Prisma DB) and a **Playwright** end-to-end suite.
- **Container self-healing for the WSL2 stale-bind-mount failure.** A new `GET
  /api/health` route opens the DB (`SELECT 1`) behind a Docker `healthcheck`, and an
  **`autoheal`** sidecar restarts `ats-web` whenever Docker marks it unhealthy —
  recovering from the `SQLITE_CANTOPEN` (Error code 14) a stale bind mount causes
  after the WSL2 VM suspends/resumes. (SPEC §6.)
- **`make seed-dev`** (`apps/web/prisma/seed-dev.mjs`) — appends a realistic spread
  of sample applications (varied statuses, categories, dates, and `status_history`
  trails) to the local DB for populating the dashboard. Unlike the e2e fixture it
  **never clears** existing rows, so it is safe to run against a DB holding real
  worker `job_postings`.

### Changed
- Default scoring model is now **`qwen3.5:4b`** (local Ollama) and default
  resume-tailoring model is **Claude `claude-sonnet-4-6`** — both overridable via
  CLI flag or env var.
- The repo ships only `*.example` templates; the real resume, `config.yaml`, and
  secrets stay gitignored.
- CI now gates coverage on both suites, runs a schema-drift guard (worker SQL
  fixture vs. `prisma/schema.prisma`), and runs a gated Playwright e2e job.

### Fixed
- Workday pagination and adapter robustness; hardened hard-constraint screening;
  HTML-to-text now collapses non-breaking spaces; config errors surface clearly.

### Documentation
- Added an authoritative system spec ([`docs/SPEC.md`](./docs/SPEC.md)), a progress
  tracker ([`docs/PROGRESS.md`](./docs/PROGRESS.md)), and an auto-loaded `CLAUDE.md`;
  slimmed the README and reduced `docs/SETUP.md` / `docs/pipeline-design.md` to
  pointers.
- Separated the three docs by role: **SPEC** = the current capability map ·
  **PROGRESS** = live delta only (in-flight + open work, graded by severity) ·
  **CHANGELOG** = chronological history. PROGRESS dropped its completed-feature
  tables (the capability inventory now lives solely in SPEC), recalibrated its
  summary (no "feature-complete and stable"), and surfaces the shipped notify
  data-loss defect as a graded defect rather than one bullet among nice-to-haves.
- Added a user-facing **Feature status** matrix to the README with an honest
  *Tested* axis (✅ / ⚠ / —) that distinguishes shipped from verified — fixing the
  old all-`✅` over-claim. Building it surfaced an untested gap: the chart-data
  actions (`getStatusFlow`/`getTimelineData`/`getCategoryData`) have no test
  coverage (now tracked in SPEC §9 and PROGRESS).

## [0.2.0] — 2026-06-08

### Added
- **Semi-automated job-hunt pipeline** (`apps/worker/`): a Python worker that
  scans Greenhouse / Lever / Ashby boards, scores each posting against your
  resume with a local Ollama model, auto-tailors a one-page resume for high
  scorers (Claude + `tectonic`), and notifies you on Telegram.
- **Discovered Jobs** tab in the web app: a scored, filterable queue with a
  job-description + match-analysis dialog, per-job tailored-resume download
  (`GET /api/resume/[id]`), and one-click "Mark Applied" that promotes a posting
  into a tracked application.
- `job_postings` model in the Prisma schema (deduped on `(source, external_id)`,
  advancing through a `pipeline_status` state machine).
- Repository scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`, this changelog,
  `.editorconfig`, a root `Makefile`, GitHub Actions CI, and a PR template.

### Changed
- Promoted `docker-compose.yml` to the repository root; it now orchestrates both
  the web app and the worker from one place (`docker compose up` from root).
- Moved `SETUP.md` and the pipeline design doc under `docs/`.
- Prisma datasource is now driven by `DATABASE_URL` so the same schema serves
  local dev and the directory-mounted Docker volume shared with the worker.

### Fixed
- Web `lint` step (and therefore CI) failed before running: the flat
  `eslint.config.mjs` used Next 15 / ESLint 9 imports (`eslint/config`,
  `eslint-config-next/typescript`) incompatible with the pinned Next 14 /
  ESLint 8 toolchain. Replaced with a standard `.eslintrc.json`
  (`next/core-web-vitals`) run via `next lint`.

## [0.1.0] — initial tracker

### Added
- Next.js + Prisma + SQLite application tracker: status KPIs, searchable and
  paginated table with inline status editing and history, CSV import/export,
  and dashboards (activity heatmap, category donut, status funnel, Sankey).
- Dockerized web app with a bind-mounted database.
