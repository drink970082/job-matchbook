# ATS — System Specification

> **Authoritative source of truth for this repository.** This document describes
> the system *as it actually exists* and is written to be verified against the
> code. When code and this spec disagree, that is a bug in one of them — fix it,
> don't let them drift. New work should update this file in the same change.
>
> Companion documents: [`PROGRESS.md`](./PROGRESS.md) (live status + open work),
> [`../CHANGELOG.md`](../CHANGELOG.md) (release history),
> [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (conventions).

- **Project:** personal-ats — a self-hosted, semi-automated job-application system
- **Repo:** https://github.com/drink970082/personal-ats
- **Version:** 0.2.0 (unreleased: feed + DB watchlist + feed-coverage Tier 1) · **Spec last updated:** 2026-06-18 · **License:** MIT

---

## Table of contents

0. [How to read this spec: contract vs. snapshot](#how-to-read-this-spec-contract-vs-snapshot)
1. [Overview](#1-overview)
2. [Problem and motivation](#2-problem-and-motivation)
3. [Users and principles](#3-users-and-principles)
4. [Goals and non-goals](#4-goals-and-non-goals)
5. [System overview](#5-system-overview)
6. [Architecture](#6-architecture)
7. [Component specifications](#7-component-specifications)
8. [Data model](#8-data-model)
9. [Behaviors and invariants](#9-behaviors-and-invariants)
10. [Design decisions and rationale](#10-design-decisions-and-rationale)
11. [Non-functional requirements](#11-non-functional-requirements)
12. [Setup and deployment](#12-setup-and-deployment)
13. [Testing and quality](#13-testing-and-quality)
14. [References](#14-references)

---

## How to read this spec: contract vs. snapshot

This document is the authoritative source of truth, but not every statement is
authoritative in the same way. Clauses fall into two classes that resolve
disagreements with the code differently:

- **Contract — spec wins.** Normative clauses the code must satisfy: **Goals and
  non-goals (§4)** and **Behaviors and invariants (§9)**. If the code and a contract
  clause disagree, the *code* is the bug — fix the code (and its guarding test). Each
  contract clause should be covered by a test; §9 carries the invariant → test
  traceability (and flags the ones that currently aren't).
- **Snapshot — code wins.** Descriptive clauses recording how the system is
  *currently* built: **System overview (§5)**, **Architecture (§6)**, **Component
  specifications (§7)**, **Data model (§8)**, and **Setup and deployment (§12)** —
  including details like a route's path or a module's name. If the code and a
  snapshot clause disagree, the *spec* is stale — update the spec to match reality.

The product-context preamble (§1–§3) and the supporting material (§10–§11, §13–§14)
are explanatory. Each section is tagged with its class under its heading.

---

## 1. Overview

ATS is **one project made of two cooperating services that share a single SQLite
database**:

- **`apps/web`** — a Next.js 14 tracker + dashboards. You browse a queue of
  discovered jobs, triage them, and track every application through its status
  lifecycle with KPIs and charts.
- **`apps/worker`** — a scheduled Python pipeline that *feeds* the tracker: it
  scans company ATS boards, scores each posting against your resume with a local
  LLM, screens out hard-constraint mismatches, auto-tailors a one-page resume for
  the best matches, and pings you on Telegram.

The two services never call each other. Their only contract is the **shared
database** (and a shared folder of tailored PDFs). The worker discovers and
prepares; the web app is where a human triages, applies by hand, and tracks.

---

## 2. Problem and motivation

Job hunting generates a lot of state per application — company, role, date applied,
current status, interview rounds, where it stalled, category (SWE / MLE / DS /
Quant / …). A spreadsheet handles the first two columns but falls over once you
want to ask "what's my offer rate by category?" or "where do most of my
applications die?"

Two pains, addressed by the two services:

1. **Tracking** is tedious and hard to analyze in a spreadsheet → the web app is
   "the spreadsheet plus the answers" (KPIs, heatmap, funnel, Sankey).
2. **Discovery** is repetitive: scanning boards, judging fit, tailoring a resume
   per role → the worker automates everything *up to* the apply click, leaving the
   human in control of the actual submission.

---

## 3. Users and principles

- **Single, self-hosting user.** No multi-tenant accounts, no auth layer — you run
  it on your own machine against your own data.
- **Human always in the loop.** The pipeline invests *nothing* in auto-apply. It
  prepares (score, screen, tailor, notify); you review and submit by hand, then
  one-click "Mark Applied" records it.
- **Privacy first.** Resume, secrets, target-company list, and the database are all
  gitignored; the repo ships only `*.example` templates so a clean clone runs
  without exposing personal data.
- **Local-first compute.** High-frequency scoring runs on a local GPU (Ollama),
  not a paid API; only the low-frequency tailoring step (high scorers) hits Claude.

---

## 4. Goals and non-goals

*Class: **Contract** — code must satisfy these; disagreements are code bugs.*

**Goals**

- Track applications end-to-end with status history and visual analytics.
- Discover and pre-qualify jobs from company ATS boards on a schedule.
- Tailor a one-page resume per high-scoring role. Faithfulness (no fabricated
  experience) is prompt-instructed and verified by the human before applying — not a
  checked guarantee (see §9, "Unenforced clauses").
- Keep the two services safely co-writing one SQLite database.
- Stay runnable on a single host with one `docker compose up`.

**Non-goals**

- **No auto-apply / auto-submit.** A human always performs the application.
- **No multi-tenant SaaS, no user accounts, no public hosting.** Single-user, self-hosted.
- **No scraping of LinkedIn / Indeed.** Only official company ATS board APIs
  (anti-scraping + ToS risk avoided). The optional discovery feed reads a **public
  GitHub data file** (SimplifyJobs `listings.json`) — not a scraped UI — and still
  fetches every JD from the official board the listing's URL resolves to; aggregator
  *product* UIs (jobright.ai, simplify.jobs) remain out of scope.
- **No cloud dependency** beyond the three external APIs the worker calls
  (Anthropic Claude, the host's Ollama, Telegram).
- **The worker issues no schema DDL** — Prisma owns the schema.

---

## 5. System overview

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

The two-phase workflow:

```
Phase 1 — Discovery & scoring (apps/worker, scheduled)
  watchlist (DB) ─► fetch (GH/Lever/Ashby/Workday/Pinpoint/SmartRecruiters/Workable) ─┐
  feed (Simplify) ─► prefilter ─► resolve URL→board ─► fetch/fetch_one (reuse) ────────┤
                    (per-listing detail sources: Oracle/Jobvite)                       │
                    (unresolvable URL → feed_unresolved backlog)                       │
            (both paths upsert job_postings, deduped on source+id) ◄──┘
            ─► score + screen (local Ollama)
            ─► tailor one-page resume (Claude + tectonic)   [only score ≥ threshold]
            ─► notify (Telegram message + PDF)

Phase 2 — Triage & tracking (apps/web, browser)
  Discovered Jobs tab ─► review JD + match analysis ─► download tailored PDF
            ─► you apply by hand ─► one-click "Mark Applied"
            ─► becomes a tracked application ─► flows into KPIs + charts
```

Two ingestion paths feed the same `job_postings` table: the **watchlist** (companies
you curate, fetched in full) and an optional **discovery feed** (a broad listing
stream resolved back to boards, JD fetched with the same adapters). Both dedup on
`(source, external_id)` of the underlying board, so the feed is a *transport*, never
a `source`.

A posting moves through a `pipeline_status` state machine in the database
(§[9](#9-behaviors-and-invariants)). "Mark Applied" is the seam between the two
phases: it promotes a `job_postings` row into an `applications` row.

---

## 6. Architecture

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

```
            ATS boards          Ollama (host GPU)   Claude API      Telegram
       Greenhouse/Lever/Ashby/        │                 │              ▲
        Workday/Pinpoint              │                 │              │
                  │                    ▼                 ▼              │
   ┌──────────────┴────────────────────────────────────────────────────┐
   │  apps/worker  (Python 3.11, APScheduler)                          │
   │     fetch ──► score+screen ──► tailor (1-page PDF) ──► notify      │
   └───────────────┬───────────────────────────────────┬───────────────┘
                   │ writes job_postings rows           │ writes PDFs
                   ▼                                     ▼
            ┌────────────┐                        ┌────────────┐
            │   db/      │   shared SQLite (WAL)  │  resumes/  │  shared volume
            │ applications.db ◄──────────────────►│  (PDFs)    │
            └─────┬──────┘                        └─────┬──────┘
                  │ reads postings / writes applications │ serves PDFs
                  ▼                                       ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  apps/web  (Next.js 14, Server Actions + 2 API routes)            │
   │   Discovered Jobs tab  ──"Mark Applied"──►  Applications + charts  │
   └───────────────────────────────────────────────────────────────────┘
                  ▲
                  │  you (browser): triage, apply by hand, track
```

**Process / deployment topology**

| Piece | Runs in | Talks to |
|-------|---------|----------|
| Next.js web app | `web` service (`ats-web` container) | shared SQLite (read postings, write applications) |
| fetch / score / tailor / notify | `worker` service (`ats-worker` container) | board APIs, host Ollama, Anthropic API, Telegram API |
| Ollama | **host** (GPU) — not containerized | — |
| SQLite db | `./db` directory, bind-mounted into both containers | — |
| Tailored PDFs | `./resumes`, bind-mounted into both containers | — |

Both containers run as the host user (UID/GID build args) so bind-mount writes
work without `chmod 777`. The database is mounted as a **directory** (not a single
file) so SQLite's WAL `-wal`/`-shm` sidecars are visible to both processes — a
single-file mount silently breaks cross-container WAL. Ollama runs on the host
because GPU pass-through into a container under WSL2 is fiddly; the worker reaches
it via `host.docker.internal:11434` (`extra_hosts: host-gateway` makes this work
on Linux Compose).

**Resilience: stale bind mount → autoheal.** On WSL2, Docker bind mounts ride the
WSL2 VM's filesystem share; when the VM suspends/resumes, a *long-running*
container can end up with a stale view of `./db` while the host and freshly-started
containers see it fine. Prisma then fails with `SQLITE_CANTOPEN` (Error code 14) —
the browser shows only a Next.js error digest; the real stack trace is in
`docker logs ats-web` — even though permissions, ownership, disk, and the mount
config are all correct. The cure is to recreate the container. To make this
self-healing, `web` exposes `GET /api/health`, which actually opens the DB
(`SELECT 1` → `200`, else `503`), wired to a Docker `healthcheck`; the `autoheal`
sidecar (watches the `autoheal=true` label via the mounted Docker socket) restarts
any container Docker marks **unhealthy**. Plain Compose does *not* restart on
unhealthy by itself — `restart: unless-stopped` only fires on container exit — so
the sidecar is what closes the loop.

**Stack**

| Layer | Web (`apps/web`) | Worker (`apps/worker`) |
|-------|------------------|------------------------|
| Language | TypeScript 5 | Python 3.11 |
| Framework | Next.js 14 (App Router, Server Actions, `output: standalone`) | APScheduler (cron) |
| Data | Prisma 6 + SQLite | `sqlite3` stdlib (raw SQL, WAL) |
| UI | React 18, Tailwind CSS 4, Radix UI primitives | — |
| Charts | Recharts (donut) + hand-rolled SVG (heatmap, funnel, Sankey) | — |
| Forms | react-hook-form + Zod | — |
| External | — | Anthropic SDK (Claude), Ollama HTTP, Telegram Bot API, `tectonic`, `pypdf` |
| Tests | Jest + Testing Library + jest-mock-extended; Playwright e2e | pytest (fully mocked) |
| Container | Alpine multi-stage, non-root | python:3.11-slim + tectonic (bundle prewarmed) |

---

## 7. Component specifications

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

Each unit below lists *what it does · inputs/outputs · what it depends on*. The
worker modules are pure and dependency-injected; real services are wired only in
`run.py` (`ats_worker/`).

### 7.1 Worker (`apps/worker/ats_worker/`)

- **`run.py` — entrypoint & wiring.** CLI: `--once` (single pass then exit) vs
  scheduler (immediate pass, then every `schedule_hours`). Flags: `--config`,
  `--env`, `--db` (`DB_PATH`, default `../web/prisma/applications.db`),
  `--resume-dir` (`RESUME_DIR`, default `../../resumes`), `--resume`,
  `--master-tex`, `--model` (`OLLAMA_MODEL`), `--anthropic-model`
  (`ANTHROPIC_MODEL`), `--import-companies` (seed the DB watchlist from config and
  exit). Defaults: scoring `qwen3.5:4b`, tailoring `claude-sonnet-4-6`. Each pass
  **auto-seeds** `watched_companies` from `config.companies` when the table is empty,
  reads the watchlist from the DB (not config), runs `run_fetch` over it, then runs
  `run_feed` for each enabled feed. The only module that knows about
  secrets/external services.
- **`config.py` — load/validate `config.yaml`.** Validates `source ∈ VALID_SOURCES`
  (the watchlist-capable boards: {greenhouse, lever, ashby, workday, pinpoint,
  smartrecruiters, workable} — feed-only sources oracle/jobvite are intentionally
  excluded); exposes `companies`,
  `title_filter`, `candidate` (with `is_empty()`), `feeds`, `threshold`,
  `schedule_hours`, `max_single_page_rounds`. Bad source / missing field → clear
  startup error. `feeds` is an optional mapping of feed-name → settings (only
  `simplify` is valid in v1: `enabled`, `categories` keep-list, optional `url`);
  `companies` is now consumed only by the one-time watchlist import (see `run.py`).
- **`fetch/` — board adapters.** One thin module per source, registered in
  `fetch/ADAPTERS`. Each returns the unified posting dict (`title`, `location`,
  `url`, full JD `description`, `external_id`). Two shapes:
  - **Per-board** adapters expose `fetch(slug, …)` — list a whole board. These are
    **watchlist-capable** (the watchlist enumerates a company's board).
  - **Per-listing** adapters expose `fetch_one(slug, external_id, …)` — fetch ONE
    job by id, for boards with no public list endpoint. These are **feed-only**
    (you can't enumerate a board, so they can't be watch-listed) and are routed by
    `fetch.DETAIL_SOURCES` / `fetch_one_company`.
  - `filter_postings(postings, title_filter)` — optional case-insensitive
    title-substring pre-filter (title only; geography is handled by the scorer).

  **Source coverage matrix** (the at-a-glance support map — keep it current when a
  source is added). *Adapter* = can fetch a JD; *feed router* = `resolve_url` maps
  the host; *watchlist* = enumerable per-board source (in `VALID_SOURCES`). These
  capabilities come apart — e.g. Pinpoint has an adapter + watchlist but no feed
  router:

  | Platform | Host(s) | Adapter | Feed router | Watchlist |
  |---|---|---|---|---|
  | Greenhouse | `boards.greenhouse.io`, `job-boards.greenhouse.io`, `job-boards.eu.greenhouse.io` | list | ✅ | ✅ |
  | Lever | `jobs.lever.co` | list | ✅ | ✅ |
  | Ashby | `jobs.ashbyhq.com` | list | ✅ | ✅ |
  | Workday | `*.myworkdayjobs.com` | list, N+1 | ✅ (jobReqId substring) | ✅ |
  | SmartRecruiters | `jobs.smartrecruiters.com` | list, N+1 | ✅ | ✅ |
  | Pinpoint | `{slug}.pinpointhq.com` | list | ❌ | ✅ |
  | Workable | `apply.workable.com` | list | ✅ | ✅ |
  | Oracle Cloud HCM | `*.oraclecloud.com` | detail (`fetch_one`) | ✅ | ❌ feed-only |
  | Jobvite | `jobs.jobvite.com` | detail (JSON-LD) | ✅ | ❌ feed-only |

  Endpoints: greenhouse `boards-api.greenhouse.io/v1/boards/{slug}/jobs` (the US
  api host serves EU boards too); lever `api.lever.co/v0/postings/{slug}`; ashby
  `api.ashbyhq.com/posting-api/job-board/{slug}`; workday CXS list + per-job detail,
  slug packs `tenant/datacenter/site`; pinpoint `{slug}.pinpointhq.com/postings.json`;
  smartrecruiters `api.smartrecruiters.com/v1/companies/{slug}/postings` + `/{id}`
  detail; workable `apply.workable.com/api/v1/widget/accounts/{slug}?details=true`;
  oracle `{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{reqId}`
  (slug packs `{host}/{site}`); jobvite `jobs.jobvite.com/{slug}/job/{id}` → schema.org
  JobPosting JSON-LD.
  *Backlog (in `feed_unresolved`, not yet routed):* iCIMS, embedded greenhouse
  (`?gh_jid` on custom domains), greenhouse embed-token (no recoverable slug),
  ByteDance/TikTok. See [`PROGRESS.md`](./PROGRESS.md).
- **`feed/` — discovery-feed package.** Ingests a broad listing stream and resolves
  it back to boards (a feed is a *transport*, not a `source`). Pure parts:
  - `simplify` — `fetch` the SimplifyJobs `listings.json` (a public GitHub data
    file) over injected HTTP; returns raw listing dicts (no JD text).
  - `prefilter` — cheap metadata gate: keep `active` listings whose `category` is in
    the configured keep-list and whose `sponsorship` is not an explicit "no".
  - `resolve` — `resolve_url` maps an apply URL → `(source, slug, external_id)` for
    `lever`/`ashby`/`greenhouse`-direct (incl. the EU host)/`smartrecruiters`/`workable`
    (external_ids match the adapters exactly), `workday` (returns the `jobReqId`,
    matched downstream as a substring of the posting's `job_url`), and the per-listing
    detail sources `oracle` (slug packs `{host}/{site}`) and `jobvite`; else `None`.
    `classify_reason` labels the residual unresolvable ones (an *unparseable* `workday`
    URL → `workday_deferred`, `embedded_greenhouse`, `unsupported_host`) for the
    `feed_unresolved` backlog.
- **`db.py` — SQLite layer.** WAL pragmas + `busy_timeout`; `upsert_postings`
  (dedup on `(source, external_id)`; persists `company_slug`), `get_by_status`
  (optionally `min_score`), `save_score`, `save_resume`, `mark_notified`,
  `mark_failed`. Watchlist + feed helpers: `get_watchlist`, `count_watchlist`,
  `import_watchlist` (idempotent), `record_unresolved` (upsert on `url`),
  `existing_external_ids`. Issues no DDL.
- **`score.py` — `score_posting`.** Calls host Ollama (`think: false`,
  `num_ctx` from `OLLAMA_NUM_CTX`, default 8192) with `resume.txt` + JD → JSON
  `{score 0-100, matched_keywords, missing_keywords, reasoning}`. When a non-empty
  `candidate` is supplied, also screens each hard requirement (experience, degree,
  work authorization, clearance, locations, dealbreakers) *semantically* and may
  return `disqualified` + `disqualification_reason` + per-requirement `screen`
  verdicts.
- **`tailor.py` — `tailor_resume` + helpers** (`make_claude`, `tectonic_compile`,
  `pypdf_count`). Claude reorders/rephrases `master.tex` for the JD; a
  `FABRICATION_GUARD` instruction is injected every round telling it never to invent
  experience — **prompt-level only**; the sole deterministic gate in the loop is page
  count (see §9). `tectonic` compiles to PDF, `pypdf` counts pages; if > 1 page, feed
  "now N pages, cut to 1" back to Claude and recompile, up to `max_single_page_rounds`
  (default 3). Returns `{tex, pdf_path, pages, ok}`.
- **`notify.py` — `notify_posting`.** Telegram `sendMessage` (company / title /
  score / JD link) + `sendDocument` (tailored PDF). Degrades to message-only if the
  PDF is missing.
- **`pipeline.py` — orchestration.** Stateless stage functions over a db
  connection with injected worker callables and an explicit `now`:
  `run_fetch` → (`run_feed`) → `run_score` → `run_tailor` → `run_notify`. Every stage
  wraps each item in try/except: one bad posting/company is recorded (via
  `db.mark_failed` or skipped) and the batch continues. `run_feed` (optional) runs
  the feed: prefilter → resolve → record-unresolved, then groups survivors by
  `(source, slug)`, skips ids already ingested (`existing_external_ids`), and ingests
  the surfaced postings via one of two paths: **per-board** sources fetch the whole
  board via the existing adapter and keep **only** the surfaced ids (match: exact
  `external_id` for most boards; `jobReqId`-substring-of-`job_url` for workday);
  **detail sources** (`fetch.DETAIL_SOURCES`, e.g. oracle/jobvite — no board-list
  endpoint) fetch each surfaced id directly via `fetch_one_company` (per-id try/except,
  so one bad listing is skipped). Each kept posting is stamped with its `company_slug`.
  Stage gating in §[9](#9-behaviors-and-invariants).

### 7.2 Web (`apps/web/src/`)

- **`app/page.tsx`** — dashboard entry; SSR with `export const dynamic =
  'force-dynamic'` so it always reads the live db.
- **`app/api/resume/[id]/route.ts`** — `GET` streams a tailored PDF for a
  `job_postings.id`. Contract in §[9](#9-behaviors-and-invariants).
- **`app/api/health/route.ts`** — DB-reachability probe for the Docker healthcheck.
  `GET` runs `SELECT 1` (`200 {status:"ok"}`, else `503`) so a stale bind mount is
  caught and the `autoheal` sidecar can restart the container (§6).
- **`lib/actions.ts`** — all mutations and aggregations as Server Actions (return
  shape `{ success, ... }` or `{ data, total }`). Key actions:
  - *Applications:* `getApplications` (paginated; filters: status, historical
    status, category, free-text; `date_applied desc`), `addApplication`,
    `updateApplicationDetails`, `updateApplicationStatus` (validates against
    `STATUSES`, appends to `status_history`), `deleteApplication`,
    `getApplicationHistory`, `deleteHistoryItem` (recomputes current status from
    remaining history), `getKPIs`.
  - *Charts:* `getStatusFlow` (Sankey transitions), `getTimelineData` (heatmap),
    `getCategoryData` (donut).
  - *Discovered jobs:* `getJobPostings` (default queue = `scored|tailored|notified`,
    `score desc`), `discardJobPosting`, `reopenJobPosting`, `markJobApplied`.
  - *Watchlist:* `getWatchedCompanies` (name asc), `addWatchedCompany` (validates
    `source ∈ VALID_SOURCES`, dedups `(source, slug)`), `removeWatchedCompany`.
  - *Promotion / unresolved* (in separate `lib/promotion-actions.ts` /
    `lib/unresolved-actions.ts`, not `actions.ts`): `getPromotionSuggestions` (raw-SQL
    aggregate over `job_postings` by `(source, company_slug)`, watchlist-capable sources
    only, excluding watched + dismissed; signal in §9), `dismissPromotion`;
    `getUnresolvedFeeds` (groups
    `feed_unresolved` by host + reason). Approve reuses `addWatchedCompany`.
  - *CSV:* `exportApplicationsCSV`, `importApplicationsCSV` (hand-rolled RFC-4180
    parser; validates status/category against enums; dedups).
- **`lib/db.ts`** — process-singleton Prisma client (avoids dev hot-reload
  connection leaks).
- **`lib/constants.ts`** — `STATUSES` (14), `CATEGORIES` (9), `TERMINAL_STATUSES`,
  `VALID_SOURCES` (7 watchlist-capable boards, mirrors the worker; feed-only sources
  are not listed), `getStatusColor`. **Edit here to extend statuses/categories/sources.**
- **`components/`** — `Dashboard` (Applications ↔ Discovered Jobs ↔ Watchlist ↔
  Unresolved tabs), `ApplicationTable` (inline status edit), `KPIGrid`,
  `StatusHistoryModal`, `AddApplicationForm`, `DiscoveredJobsTable`, `WatchlistTable`
  (list + add/remove watched companies), `PromotionSuggestions` (approve/dismiss feed→
  watchlist suggestions, shown in the Watchlist tab), `UnresolvedFeedsTable` (read-only
  backlog), `JobDetailModal` (JD + score detail), and the four charts `TimelineHeatmap` /
  `CategoryDonut` / `StatusFunnel` / `SankeyChart`, plus Radix-based `ui/` primitives.

---

## 8. Data model

*Class: **Snapshot** — mirrors `schema.prisma` (the real source of truth); if they disagree, update this spec.*

Six tables, owned solely by `apps/web/prisma/schema.prisma` (`applications`,
`status_history`, `job_postings`, `watched_companies`, `feed_unresolved`,
`promotion_dismissed`). Dates are stored as **ISO-8601 strings** for sortability and
timezone-independence (`date_applied` as `YYYY-MM-DD`; timestamps as full ISO with
millisecond precision to match Prisma / the worker's `_now()`).

```prisma
model applications {
  id              Int              @id @default(autoincrement())
  company_name    String
  job_title       String
  application_url String?
  date_applied    String           // YYYY-MM-DD
  category        String?          // one of CATEGORIES
  status          String           // one of STATUSES
  notes           String?
  last_updated    String?
  status_history  status_history[]
  job_postings    job_postings[]   // back-link from a promoted posting
}

model status_history {
  id             Int          @id @default(autoincrement())
  application_id Int
  status         String
  timestamp      String
  applications   applications @relation(fields: [application_id], references: [id],
                                         onDelete: Cascade, onUpdate: NoAction)
}

model job_postings {
  id              Int           @id @default(autoincrement())
  source          String        // greenhouse|lever|ashby|workday|pinpoint|smartrecruiters|workable|oracle|jobvite
  external_id     String        // id returned by the board
  company_slug    String?       // board slug this posting came from (promotion grouping; null on legacy rows)
  company_name    String
  job_title       String
  location        String?
  job_url         String
  description     String        // full JD text (fed to the LLM)
  score           Int?          // 0-100, from Ollama
  score_detail    String?       // JSON: matched/missing keywords, reasoning, screen, disqualification
  resume_tex      String?       // tailored LaTeX source
  resume_path     String?       // tailored PDF path on the shared volume
  resume_pages    Int?          // page count after compile (1 = good)
  pipeline_status String        @default("new") // new|scored|tailored|notified|applied|discarded|failed
  pipeline_error  String?       // last error when pipeline_status='failed'
  attempts        Int           @default(0)     // recorded on failure (auto-retry not implemented)
  application_id  Int?          // back-link once marked applied
  application     applications? @relation(fields: [application_id], references: [id], onDelete: SetNull)
  created_at      String
  updated_at      String?

  @@unique([source, external_id])  // dedup key
  @@index([pipeline_status])
}

model watched_companies {        // the DB-owned watchlist (web-managed)
  id          Int    @id @default(autoincrement())
  source      String // watchlist-capable boards: greenhouse|lever|ashby|workday|pinpoint|smartrecruiters|workable
  slug        String // board identifier (workday packs tenant/datacenter/site)
  name        String
  created_at  String
  @@unique([source, slug])       // dedup key
}

model feed_unresolved {          // feed listings not resolvable to a board (backlog)
  id           Int     @id @default(autoincrement())
  feed         String  // e.g. "simplify"
  url          String
  company_name String
  job_title    String
  host         String  // parsed hostname, for prioritising
  reason       String  // workday_deferred | embedded_greenhouse | unsupported_host
  created_at   String
  updated_at   String?
  @@unique([url])                // upsert key — no pile-up across passes
  @@index([reason])
}

model promotion_dismissed {      // companies the user dismissed from suggestions
  id          Int    @id @default(autoincrement())
  source      String
  slug        String
  created_at  String
  @@unique([source, slug])
}
```

Relationships: deleting an application **cascades** to its `status_history` and
**nulls** the `application_id` on any linked `job_postings`. A posting is deduped
on `(source, external_id)`.

**Enums** (single source: `apps/web/src/lib/constants.ts`):

- **Statuses** (funnel order): `Applied` → `Online Assessment` → `Phone Screen` →
  `Interviewing: 1st…5th round` → `Final Round` → `Offer` → `Accepted`; terminals
  `Rejected`, `Withdrew`, `Ghosted`. `TERMINAL_STATUSES` = {Offer, Accepted,
  Rejected, Withdrew, Ghosted}.
- **Categories:** SWE, MLE, DS, DA, Quant Dev, Quant Analyst, Quant Trader, AI
  Engineer, Others.

**Schema changes and migrations.** The schema is applied with `prisma db push`
(`make db-push`), so there is **no migration history**. This is a deliberate tradeoff
for a single-user, rebuildable tool, but it has a real edge: a *destructive* change
(dropping or renaming a column) has no migration/backfill path and can lose retained
`applications` / `status_history` data with no rollback. Back up `db/applications.db`
before schema changes — additive changes are low-risk, destructive ones are not.

---

## 9. Behaviors and invariants

*Class: **Contract** — verify the code against these; see the traceability table at the end of this section.*

The checkable contracts. These are the facts the code must satisfy; verify against
them when changing behavior.

**Pipeline state machine** (`pipeline.py`):

```
fetch:   (new posting)            → new
feed:    (surfaced posting, JD via board adapter) → new   (optional, alongside fetch)
score:   new                      → scored        (default)
                                  → discarded      (candidate hard-constraint fail)
tailor:  scored, score ≥ threshold → tailored      (below threshold: stay scored, untouched)
notify:  tailored                 → notified
any stage, on exception           → failed         (pipeline_error set; batch continues)
```

- **Stage gating is strict:** `run_score` processes only `new`; `run_tailor` only
  `scored` with `score ≥ threshold`; `run_notify` only `tailored`. A failure in one
  posting never aborts the batch (per-item try/except → `mark_failed`).
- **Screening is part of scoring, not a separate stage.** With an empty `candidate`
  block, the screen call is skipped entirely (no disqualification). A `discarded`
  row keeps its `score`/`score_detail` (including `disqualification_reason`) so the
  UI can explain *why*.
- **`now` is injected** per run (ISO-8601 UTC ms), making the pipeline
  deterministic and testable without a clock or network.
- **Tailored PDFs** are written to `{resume_dir}/{source}_{external_id}/` — unique
  per posting so concurrent tailors never clobber each other; rooted at the shared
  volume so `resume_path` is web-readable.

**Feed ingestion** (`run_feed`, optional):

- **A feed is a transport, never a `source`.** Each surfaced listing is resolved to
  its underlying board `(source, slug, external_id)` and ingested under that board's
  source, so dedup on `(source, external_id)` holds across the feed, the watchlist,
  and repeated passes. The resolver's id matches the adapter exactly for
  `lever`/`ashby` (uuid), `greenhouse` (numeric), and `smartrecruiters` (posting id);
  **workday is special** — the feed exposes the per-tenant `jobReqId` but the adapter
  keys on the GUID, so the resolver returns the `jobReqId` and the keep-filter matches
  it as a **substring of the posting's `job_url`** (the `externalUrl`).
- **Pre-filter then resolve then keep-only-surfaced.** Listings are gated on
  `active` + `category` keep-list + non-explicit-`sponsorship` *before* any fetch;
  survivors are grouped by `(source, slug)`, ids already present are skipped, and the
  board is fetched with the existing adapter keeping **only** the surfaced postings
  (a feed company is never ingested in full like a watchlist company). Each kept
  posting is stamped with its resolved `company_slug`.
- **Unresolvable listings are recorded, not dropped.** A URL the resolver can't map
  to a supported board+slug (an *unparseable* workday URL, embedded greenhouse,
  unsupported host) is upserted into `feed_unresolved` (`host` + `reason`), keyed on
  `url`. One bad board never aborts the batch (per-group try/except, mirroring `run_fetch`).
- **Detail-fetch sources fetch one job per surfaced id.** A source with no public
  board-list endpoint (`fetch.DETAIL_SOURCES`, e.g. `oracle`, `jobvite`) is ingested by
  fetching each surfaced id directly via `fetch_one` (per-id try/except → one bad
  listing skipped), not by listing-then-filtering; its `external_id` is exactly the
  resolved id, so no keep-filter is needed. These sources are **feed-only**: they
  cannot enumerate a board, so they are absent from `VALID_SOURCES` (not
  watch-listable) and excluded from promotion suggestions.

**Watchlist** (`watched_companies`):

- **DB-owned, single source of truth.** The worker reads its watchlist from the DB,
  not `config.yaml`. On a pass where `watched_companies` is empty, it is **seeded
  once** from `config.companies` (idempotent); thereafter config edits are ignored
  (`--import-companies` forces a re-seed). Dedup on `(source, slug)`.

**Promotion suggestions** (`lib/promotion-actions.ts`):

- **Suggest, never auto-promote.** `getPromotionSuggestions` groups `job_postings` by
  `(source, company_slug)` (non-null slug only, and **only watchlist-capable sources**
  — `source ∈ VALID_SOURCES`, so feed-only sources like oracle/jobvite are never
  suggested, since approving one would be rejected by `addWatchedCompany`),
  **excluding** companies already in `watched_companies` or `promotion_dismissed`, and
  surfaces those with
  `count(pipeline_status ∈ {tailored,notified,applied}) ≥ 2` **or**
  `count(applied) ≥ 1`, ranked by applied then high-score count. Approve is the user
  calling `addWatchedCompany`; `dismissPromotion` records `(source, slug)` (idempotent)
  to suppress it. The watchlist only ever grows by an explicit human action.

**Web ↔ pipeline seam** (`lib/actions.ts`):

- **Discovered-jobs queue** (`getJobPostings`, no explicit status) shows only the
  actionable set `{scored, tailored, notified}`, ordered `score desc, id asc`.
  `status: 'all'` removes the filter; an explicit status narrows to one.
- **`markJobApplied(id)`** runs in a `$transaction`: it refuses if an application
  with the same `(company_name, job_title)` exists, else creates the application
  (`status='Applied'`, `category='Others'`, url from `job_url`) and atomically sets
  the posting to `pipeline_status='applied'` + `application_id`. Application and
  back-link are created together or not at all.
- **`reopenJobPosting(id)`** reverses a discard (user- or LLM-initiated) back to
  `scored`, preserving `score_detail`.
- **`discardJobPosting(id)`** sets `pipeline_status='discarded'`.

**Application invariants:**

- **Status changes append history.** `updateApplicationStatus` rejects values not
  in `STATUSES`, rejects a no-op (same status), and in one transaction updates the
  application and inserts a `status_history` row (timestamp = provided date at
  `T12:00:00Z`, else now).
- **Dedup on `(company_name, job_title)`** for `addApplication`, `markJobApplied`,
  and CSV import.
- **`deleteHistoryItem`** recomputes the application's current status to the most
  recent remaining history entry, or `Applied` if none remain.
- **KPIs** (`getKPIs`): `applied` = total; `active` = total − rejected − offer −
  withdrew − ghosted (offer bucket counts Offer + Accepted; interviewing bucket
  counts Phone Screen + any Interviewing + Final Round).
- **CSV import** requires columns `company_name, job_title, date_applied`; unknown
  `status`/`category` values fall back to `Applied`/`Others`; existing
  `(company, title)` rows are skipped (reported in `{added, skipped, errors}`).

**Resume API contract** (`GET /api/resume/[id]`):

- Non-integer `id` → 404. Missing posting or null `resume_path` → 404.
- **Path-traversal guard:** the resolved path must stay within `RESUME_DIR` or →
  403. On success → 200 `application/pdf`, `Content-Disposition: inline`,
  `Cache-Control: private`.

**Cross-service data invariant:** the schema is owned solely by Prisma; the worker
reads/writes rows but issues **no DDL**. The worker's test fixture
(`apps/worker/tests/fixtures/schema.sql`) is kept in sync with `schema.prisma` by a
CI guard (`tools/check_schema_drift.mjs`, `make check-schema`).

**Failure handling and recovery limits:**

- **`failed` is terminal.** No stage or action transitions a row *out* of `failed`
  (`run_score`←`new`, `run_tailor`←`scored`, `run_notify`←`tailored`;
  `reopenJobPosting` only writes `scored`). `mark_failed` increments `attempts`, but
  **auto-retry is not implemented** — `attempts` is recorded, not acted on.
- **Notify failure buries finished work.** `run_notify` wraps the whole send in
  try/except → `mark_failed`, so a *transient* Telegram error on an already-tailored
  posting (PDF written, `resume_path` set) marks it `failed`. Because the default
  Discovered-Jobs queue is `{scored, tailored, notified}`, that posting then disappears
  from the default view and is never re-notified. Recovery is manual (filter to
  `failed`/`all`; a manual reopen routes it to `scored`, which re-tailors and
  re-notifies). This conflates a transient notification failure with a genuine pipeline
  failure. *(Tracked in [`PROGRESS.md`](./PROGRESS.md) → Open work → Defects.)*

**Unenforced clauses (asserted, not checked).** Two contract-flavored claims have no
deterministic gate; treat them as *intentions backed by the human in the loop*, not
guarantees:

- **"Never fabricates" (resume tailoring)** is enforced only by the `FABRICATION_GUARD`
  prompt injected each round; the sole deterministic gate in the loop is page count.
  `test_tailor.py::test_first_prompt_forbids_fabrication` asserts the guard text is in
  the *prompt* — **not** that the output is faithful. The human reviewing the PDF
  before applying is the actual backstop.
- **Hard-constraint screening** (work authorization / clearance / location) is an LLM
  *semantic* judgment, not a rule check — a misjudgment wastes a tailor or discards an
  applicable role. The kept `disqualification_reason` + `reopenJobPosting` let a human
  override.

### Invariant → test traceability

Grounds the "verifiable" claim. ⚠ marks an invariant with **no** (or only indirect)
automated coverage — those rely on code review or the human in the loop, not a test.

| Invariant | Test(s) |
|-----------|---------|
| Pipeline stage gating + per-item failure isolation | `worker/tests/test_pipeline.py`, `integration/test_pipeline_e2e.py` |
| Dedup `(source, external_id)` on ingest | `test_db.py`, `test_pipeline.py` |
| WAL + `busy_timeout` pragmas on connect | `test_db.py` |
| Disqualified → `discarded`; empty candidate skips the screen | `test_score.py`, `test_pipeline.py`, `test_run.py` |
| `mark_failed` → `failed` + `attempts+1` (no recovery exists) | `test_db.py` |
| One-page loop (≤ `max_rounds`; `ok` iff 1 page) | `test_tailor.py` |
| ⚠ Non-fabrication of resume content | `test_tailor.py::test_first_prompt_forbids_fabrication` — **prompt wiring only**, not output |
| Discovered-jobs default queue `{scored,tailored,notified}`, `score desc` | `web/src/__tests__/actions.test.ts`, `actions.int.test.ts` |
| `markJobApplied` atomic create + back-link + dedup | `actions.test.ts`, `actions.int.test.ts` (real-Prisma tx) |
| `updateApplicationStatus` validates `STATUSES`, appends history | `actions.test.ts`, `actions.int.test.ts` |
| `reopenJobPosting`→`scored`, `discardJobPosting`→`discarded` | `actions.test.ts` |
| `deleteHistoryItem` recomputes current status | `actions.int.test.ts` |
| KPI aggregation buckets | `actions.test.ts`, `actions.int.test.ts` |
| ⚠ Chart-data aggregation (`getStatusFlow`/`getTimelineData`/`getCategoryData`) | **none** — no unit/integration/e2e coverage; only the components render |
| CSV import/export rules (dedup, enum fallback) | `actions.int.test.ts` |
| ⚠ Resume API path-traversal guard (403) | **none** — guard is code-only in `route.ts` |
| Feed resolve (URL→board incl. workday/smartrecruiters/workable/oracle/jobvite + GH-EU host) + classify-reason | `test_feed_resolve.py` |
| SmartRecruiters adapter (two-step list+detail) | `test_smartrecruiters.py` |
| Workable adapter (per-board list) | `test_workable.py` |
| Oracle adapter (per-listing `fetch_one`) + Jobvite adapter (JSON-LD `fetch_one`) | `test_oracle.py`, `test_jobvite.py` |
| `fetch_one_company` dispatcher (detail source / unknown / non-detail) | `test_fetch.py` |
| `run_feed` detail-fetch path (per-id fetch, bad-listing isolation, slug stamp) | `test_feed_pipeline.py` |
| Feed prefilter (active / category / sponsorship) | `test_feed_prefilter.py` |
| `run_feed` keeps only surfaced ids (workday substring match), records unresolved, skips existing, isolates a bad board, stamps `company_slug` | `test_feed_pipeline.py`, `test_feed_simplify.py` |
| Promotion suggestions (signal, exclude watched/dismissed + feed-only sources) + dismiss | `web/src/__tests__/promotion.test.ts`, `promotion.int.test.ts` |
| Unresolved-feed grouping by host+reason | `web/src/__tests__/unresolved.test.ts`, `unresolved.int.test.ts` |
| Watchlist DB helpers (import idempotent, record_unresolved upsert, existing ids) | `test_watchlist_db.py` |
| Watchlist auto-seed-on-empty + feed wiring in `run_once` | `test_run.py` |
| `feeds:` config parsing + defaults | `test_feed_config.py` |
| Watchlist actions (list / add+validate+dedup / remove) | `web/src/__tests__/watchlist.test.ts`, `watchlist.int.test.ts` |
| Worker SQL fixture ↔ `schema.prisma` in sync | `test_schema_sync.py` + `tools/check_schema_drift.mjs` (CI) |

---

## 10. Design decisions and rationale

- **Two processes, one database.** The web app and worker co-write
  `db/applications.db`. SQLite **WAL + `busy_timeout=5000`** (ms; `db.py:connect`)
  make concurrent access safe **under low write-contention** — WAL permits concurrent
  readers with a single serialized writer, and brief lock contention blocks-and-retries
  for up to 5 s instead of raising `database is locked`. It is not unconditional: the
  worker mostly writes `job_postings` while the app mostly reads them and writes
  `applications` (low conflict), but sustained simultaneous writes from both could
  still exhaust the timeout. The db is mounted as a **directory** so WAL sidecars are
  shared; a single-file mount breaks this silently.
- **Prisma owns the schema.** One source of truth; the worker aligns its columns
  and issues no DDL. A CI schema-drift guard keeps the worker's SQL fixture honest.
- **Server Actions, not REST.** All mutations go through Server Actions; the
  exceptions are the two `GET` routes — `/api/resume/[id]` (binary PDF streaming
  doesn't fit the Server Action model) and `/api/health` (an HTTP-status probe the
  Docker healthcheck can call).
- **Local + cloud LLM split.** Scoring is high-frequency (every posting) → local
  Ollama on the GPU, free and rate-limit-free, `qwen3.5:4b` (fits an 8 GB card,
  ~2 s/posting, `think:false` so reasoning models still return JSON). Tailoring is
  low-frequency (only high scorers) → Claude `claude-sonnet-4-6`, prompted (via
  `FABRICATION_GUARD`) to reorder existing resume content only — faithfulness is
  prompt-instructed and human-verified, not enforced (see §9). Sonnet is plenty (and
  cost-effective) for a step that may run several rounds per job.
- **One-page resume loop.** Single-page can't be guaranteed in one shot, so compile
  → count pages → feed back "cut to 1 page" up to `max_single_page_rounds`, then
  store the last version and flag `resume_pages` for a UI warning.
- **Charts are mostly hand-rolled SVG.** Heatmap, funnel, and Sankey are written
  directly so they render exactly right on dark backgrounds without per-library
  theming; only the donut uses Recharts. The Sankey palette is deliberately
  desaturated so flow geometry leads, not color.
- **Fully dependency-injected worker.** Every external (Ollama, Claude, Telegram)
  and binary (`tectonic`, `pypdf`) is injected, so the pytest suite runs anywhere
  with no network and no keys; real wiring lives only in `run.py`.
- **UID/GID passthrough + Tectonic prewarm.** Containers run as the host user so
  bind-mount writes work without `chmod 777`; the worker image prewarms Tectonic's
  package bundle at build so the first real compile doesn't stall on a download.
- **Official board APIs only.** Greenhouse/Lever/Ashby/Workday/Pinpoint public
  endpoints are stable and compliant; LinkedIn/Indeed scraping is deliberately
  avoided. Adapters are isolated so one broken source only affects that source.

---

## 11. Non-functional requirements

- **Privacy:** resume (`apps/worker/resume/`), secrets (`apps/worker/.env`),
  config (`config.yaml`), the database (`db/`), and tailored output (`resumes/`)
  are gitignored. The repo ships only `*.example` templates. Keep real-resume edits
  out of git with `git update-index --skip-worktree`.
- **Reliability / error recovery:** one bad posting or flaky external never aborts a
  batch — the row is marked `failed` with its error and processing continues. The
  scorer returning junk JSON marks that row `failed` rather than crashing. Caveat:
  `failed` is terminal and not auto-retried, so a *transient* failure (notably at the
  notify step) can bury an already-tailored posting — see §9, "Failure handling and
  recovery limits."
- **Concurrency safety:** WAL + `busy_timeout=5000`ms (+ the directory mount) keep the
  two containers from hitting `database is locked` **under low write-contention**
  (concurrent readers + one serialized writer; brief contention blocks-and-retries up
  to 5 s). Not a guarantee under sustained dual-write load.
- **Performance:** scoring ~2 s/posting locally on an 8 GB GPU; tailoring (Claude +
  compile) runs only for `score ≥ threshold`. The root page is `force-dynamic` (no
  stale cache); the resume route is `Cache-Control: private`.
- **Responsive UI:** the web layout is responsive and stacks to a single column
  below ~640px.
- **Time zone:** the heatmap uses the server's local "today"; set `TZ` on the
  container if deploying in a different zone from where you live.
- **Security:** the resume route guards against path traversal; secrets live only
  in the gitignored `.env`, read by `run.py`.

---

## 12. Setup and deployment

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

Full prerequisites and step-by-step (Telegram bot, Ollama, troubleshooting) were
historically in `docs/SETUP.md`; this section is now authoritative.

**Prerequisites:** Docker + Compose (≥ 24); Node 20+ and Python 3.11+ only for
local non-Docker dev/tests; Ollama + an NVIDIA GPU on the **host** for scoring; an
Anthropic API key for tailoring; a Telegram bot for alerts.

**Web app only (no pipeline):**

```bash
# Local dev
cd apps/web && npm install && npx prisma generate && npm run dev   # :3000
npx prisma db push          # if db/applications.db doesn't exist yet
# Docker, web service only
UID=$(id -u) GID=$(id -g) docker compose up web --build -d
```

**Full pipeline:**

1. `cp apps/worker/config.yaml.example apps/worker/config.yaml` — set `companies`
   (`source` ∈ {greenhouse, lever, ashby, workday, pinpoint}, board `slug`, `name`),
   optional `title_filter`, the `candidate` hard-constraint block, `threshold`
   (default 75), `schedule_hours` (24), `max_single_page_rounds` (3). Workday's
   `slug` packs `tenant/datacenter/site` (quote it).
2. `cp apps/worker/resume/master.tex.example …/master.tex` and
   `…/resume.txt.example …/resume.txt`, then replace with your real resume.
3. `cp apps/worker/.env.example apps/worker/.env` — fill `ANTHROPIC_API_KEY`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_HOST`
   (`http://host.docker.internal:11434` for Docker). Optional overrides:
   `OLLAMA_MODEL`, `ANTHROPIC_MODEL`, `OLLAMA_NUM_CTX`.
4. On the host: `ollama pull qwen3.5:4b && ollama serve`.
5. From the repo root: `UID=$(id -u) GID=$(id -g) docker compose up --build`
   (or `make up`). The worker runs one pass immediately, then every
   `schedule_hours`.

**One-off test pass:**
`docker compose run --rm worker python -m ats_worker.run --once --config /app/config.yaml --env /app/.env`

**Volumes & env:** `./db` → `/data` (directory mount; `DATABASE_URL=
file:/data/applications.db`, worker `DB_PATH=/data/applications.db`); `./resumes`
→ `/resumes` (`RESUME_DIR`). `make` targets wrap all of this — see
§[13](#13-testing-and-quality) and `make help`.

---

## 13. Testing and quality

**Entry points** (root `Makefile`; `make help` lists all):

| Target | What |
|--------|------|
| `make test` | both suites |
| `make test-web` | Jest (`apps/web && npm test`) |
| `make test-worker` | pytest (`apps/worker && python -m pytest`) |
| `make test-integration` | worker `-m integration` + web `npm run test:integration` |
| `make test-e2e` | Playwright (builds web, seeds a throwaway DB) |
| `make test-coverage` | both suites with coverage gates |
| `make check-schema` | fail if the worker SQL fixture drifts from `schema.prisma` |
| `make db-push` | sync Prisma schema into SQLite |
| `make up` / `make down` | Docker Compose stack up/down |

- **Web:** Jest unit (`jest.config.ts`, Prisma mocked via `jest-mock-extended`) +
  integration (`jest.integration.config.ts`, real Prisma over a throwaway SQLite) +
  merged coverage (`jest.all.config.ts`). Playwright e2e (`e2e/`) runs against a
  seeded throwaway DB and is gated in CI.
- **Worker:** pytest, **fully dependency-injected** — no network / Ollama / Claude /
  `tectonic` / `pypdf` needed. `integration` marker runs `run_once` end-to-end over
  a temp SQLite. Coverage floor `fail_under = 85` (single source of truth in
  `pyproject.toml`, read by both `make test-coverage` and CI).
- **CI** (`.github/workflows/ci.yml`): runs both suites on push / PR / nightly, with
  coverage gates, the schema-drift guard, and a gated Playwright e2e job.
- **Schema-drift guard:** `tools/check_schema_drift.mjs` fails if
  `apps/worker/tests/fixtures/schema.sql` and `apps/web/prisma/schema.prisma` fall
  out of sync.

---

## 14. References

- **Status & open work:** [`PROGRESS.md`](./PROGRESS.md)
- **Release history:** [`../CHANGELOG.md`](../CHANGELOG.md)
- **Contributor conventions:** [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Service READMEs:** [`../apps/web`](../apps/web), [`../apps/worker/README.md`](../apps/worker/README.md)
- **Historical design note (superseded by this spec):** [`pipeline-design.md`](./pipeline-design.md)
- **Code anchors:** schema `apps/web/prisma/schema.prisma` · enums
  `apps/web/src/lib/constants.ts` · server actions `apps/web/src/lib/actions.ts` ·
  pipeline `apps/worker/ats_worker/pipeline.py` · wiring `apps/worker/ats_worker/run.py`
