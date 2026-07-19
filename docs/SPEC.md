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
- **Version:** 0.2.0 (unreleased: feed + DB watchlist + feed-coverage Tier 1 + multi-resume scoring) · **Spec last updated:** 2026-07-12 · **License:** MIT

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
  scans company ATS boards, screens out hard-constraint mismatches with a local
  LLM, scores each posting's fit against your resume version(s) with Claude, and
  pings you on Telegram for the best matches.

The two services never call each other. Their only contract is the **shared
database**. The worker discovers and prepares; the web app is where a human
triages, applies by hand, and tracks.

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
2. **Discovery** is repetitive: scanning boards and judging fit per role → the
   worker automates everything *up to* the apply click, leaving the human in
   control of the actual submission.

---

## 3. Users and principles

- **Single, self-hosting user.** No multi-tenant accounts, no auth layer — you run
  it on your own machine against your own data.
- **Human always in the loop.** The pipeline invests *nothing* in auto-apply. It
  prepares (screen, score, notify); you review and submit by hand, then
  one-click "Mark Applied" records it.
- **Privacy first.** Resume, secrets, target-company list, and the database are all
  gitignored; the repo ships only `*.example` templates so a clean clone runs
  without exposing personal data.
- **Local-first compute where it's cheap, Claude where judgment matters.** The
  high-frequency hard-requirements screen runs on a local GPU (Ollama), not a paid
  API; fit scoring (every posting, needs real seniority/domain judgment) hits Claude.

---

## 4. Goals and non-goals

*Class: **Contract** — code must satisfy these; disagreements are code bugs.*

**Goals**

- Track applications end-to-end with status history and visual analytics.
- Discover and pre-qualify jobs from company ATS boards on a schedule.
- Alert the human on Telegram for every high-scoring role, for manual application.
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
            ─► screen (local Ollama, hard requirements) ─gate─► score (Claude, reason-first)
                     [location: deterministic code gate off the board field, not the LLM]
                                          [disqualified → discarded, Claude call skipped]
            ─► notify (Telegram message)   [gate: seniority=match AND domain=match,
                                            NOT insufficient_context — score is display/ranking only]

Phase 2 — Triage & tracking (apps/web, browser)
  Discovered Jobs tab ─► review JD + match analysis
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
   │     fetch ──► screen + score ──► notify (Telegram)                │
   └───────────────┬───────────────────────────────────────────────────┘
                   │ writes job_postings rows
                   ▼
            ┌─────────────────┐
            │   db/           │   shared SQLite (WAL)
            │ applications.db │
            └─────┬───────────┘
                  │ reads postings / writes applications
                  ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  apps/web  (Next.js 14, Server Actions + 1 API route)             │
   │   Discovered Jobs tab  ──"Mark Applied"──►  Applications + charts  │
   └───────────────────────────────────────────────────────────────────┘
                  ▲
                  │  you (browser): triage, apply by hand, track
```

**Process / deployment topology**

| Piece | Runs in | Talks to |
|-------|---------|----------|
| Next.js web app | `web` service (`ats-web` container) | shared SQLite (read postings, write applications) |
| fetch / screen / score / notify | **host** — `python -m ats_worker.run`, not containerized | board APIs, host Ollama, Codex CLI (fit score), Telegram API |
| Ollama | **host** (GPU) — not containerized | — |
| SQLite db | `./db` directory, bind-mounted into the `web` container | — |

The worker is **not containerized** (the `ats-worker` service was removed 2026-07-16):
the default fit-score backend shells out to the **Codex CLI**, which authenticates from
the operator's `~/.codex/auth.json` (`codex login`) — containerizing it would mean
baking a 285 MB binary into the image *and* mounting a live subscription token into it,
for a process Ollama's GPU already pinned to the host.

The `web` container runs as the host user (UID/GID build args) so bind-mount writes
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

**Response headers.** `next.config.mjs` sets a fixed header set on every response
(`headers()`, matcher `/:path*`): `X-Frame-Options: DENY`, `X-Content-Type-Options:
nosniff`, `Referrer-Policy: same-origin`, and a `Content-Security-Policy` that is
`default-src 'self'` but keeps `'unsafe-inline'`/`'unsafe-eval'` on `script-src` for
Next's inline runtime — minimal hardening (clickjacking / MIME-sniff / framing) for
a single-user localhost app, not a strict script CSP.

**Stack**

| Layer | Web (`apps/web`) | Worker (`apps/worker`) |
|-------|------------------|------------------------|
| Language | TypeScript 5 | Python 3.11 |
| Framework | Next.js 14 (App Router, Server Actions, `output: standalone`) | APScheduler (cron) |
| Data | Prisma 6 + SQLite | `sqlite3` stdlib (raw SQL, WAL) |
| UI | React 18, Tailwind CSS 4, Radix UI primitives | — |
| Charts | Recharts (donut) + hand-rolled SVG (heatmap, funnel, Sankey) | — |
| Forms | react-hook-form + Zod | — |
| External | — | Anthropic SDK (Claude), Ollama HTTP, Telegram Bot API |
| Tests | Jest + Testing Library + jest-mock-extended; Playwright e2e | pytest (fully mocked) |
| Container | Alpine multi-stage, non-root | python:3.11-slim |

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
  `--resume-dir` (directory of resume versions, default `resume/`),
  `--model` (`OLLAMA_MODEL`, local hard-requirements screen only),
  `--score-backend` (`SCORE_BACKEND`, `codex`|`claude`),
  `--codex-score-model` (`CODEX_SCORE_MODEL`, fit scoring on the codex backend),
  `--anthropic-score-model` (`ANTHROPIC_SCORE_MODEL`, fit scoring on the claude backend),
  `--import-companies` (seed the DB watchlist from config and exit). Defaults:
  screen `qwen3.5:4b`; fit score `codex` / `gpt-5.6-sol`. Each pass
  **auto-seeds** `watched_companies` from `config.companies` when the table is empty,
  reads the watchlist from the DB (not config), runs `run_fetch` over it, then runs
  `run_feed` for each enabled feed. The only module that knows about
  secrets/external services.
- **`config.py` — load/validate `config.yaml`.** Validates `source ∈ VALID_SOURCES`
  (the watchlist-capable boards: {greenhouse, lever, ashby, workday, pinpoint,
  smartrecruiters, workable, icims, phenom, custom, browser} — feed-only sources oracle/jobvite
  are intentionally excluded); a `RECIPE_SOURCES` row (`custom`, `browser`) must carry a `recipe`
  mapping (else a startup `ConfigError`). Each company's `slug` is checked by `_valid_slug`
  against the same charset rule as the web boundary — `[A-Za-z0-9._/-]`, no `..`, no
  leading/trailing/doubled `/` — since the worker interpolates it straight into a fetch
  URL host/path (`ConfigError` on a bad slug). Exposes `companies` (each with an optional
  `recipe: dict | None`), `enable_browser_sources` (opt-in gate for `browser` rows, default off),
  `title_filter`, `candidate` (with `is_empty()`), `feeds`, `schedule_hours`. Bad
  source / missing field → clear
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
  | Workday | `*.myworkdayjobs.com` | list (watchlist) + per-job (feed) | ✅ (per-job by externalPath) | ✅ |
  | SmartRecruiters | `jobs.smartrecruiters.com` | list (watchlist) + per-job (feed) | ✅ (per-job by id) | ✅ |
  | Pinpoint | `{slug}.pinpointhq.com` | list | ❌ | ✅ |
  | Workable | `apply.workable.com` | list | ✅ | ✅ |
  | iCIMS | `{slug}.icims.com` | list (server HTML) | ❌ | ✅ |
  | Phenom | `{host}` (e.g. `apply.careers.microsoft.com`) | list + per-job detail | ❌ | ✅ |
  | Custom (recipe) | any (recipe-driven) | list (`json`/`next-data`) | ❌ | ✅ (needs `recipe`) |
  | Browser (recipe) | any (Cloudflare-blocked / JS-only) | list (headless Chromium + CSS) | ❌ | ✅ (needs `recipe`; opt-in) |
  | Oracle Cloud HCM | `*.oraclecloud.com` | detail (`fetch_one`) | ✅ | ❌ feed-only |
  | Jobvite | `jobs.jobvite.com` | detail (JSON-LD) | ✅ | ❌ feed-only |
  | Embedded Greenhouse | custom domains `?gh_jid=` | via greenhouse | ✅ enriching (I/O token scrape) | ❌ feed-only |

  Endpoints: greenhouse `boards-api.greenhouse.io/v1/boards/{slug}/jobs` (the US
  api host serves EU boards too); lever `api.lever.co/v0/postings/{slug}`; ashby
  `api.ashbyhq.com/posting-api/job-board/{slug}`; workday CXS list + per-job detail,
  slug packs `tenant/datacenter/site`; pinpoint `{slug}.pinpointhq.com/postings.json`;
  smartrecruiters `api.smartrecruiters.com/v1/companies/{slug}/postings` + `/{id}`
  detail; workable `apply.workable.com/api/v1/widget/accounts/{slug}?details=true`;
  oracle `{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{reqId}`
  (slug packs `{host}/{site}`); jobvite `jobs.jobvite.com/{slug}/job/{id}` → schema.org
  JobPosting JSON-LD; icims `{slug}.icims.com/jobs/search?in_iframe=1&pr={n}` → server-rendered
  HTML cards (bs4), paginate `pr` (plain HTTP, no browser); phenom
  `{host}/api/pcsx/search?domain={domain}&start={n}` (`data.positions[]`, `data.count`) + per-job
  `…/position_details?…&position_id={id}` for the description, slug packs `{host}/{domain}`.
  **Custom (recipe) executor** (`fetch/custom.py`): a generic, declarative fetcher — the board's
  `recipe` (a JSON object stored on the watchlist row) names the `url`, `method` (GET/POST),
  `mode` (`json`, or `next-data` = extract the `__NEXT_DATA__` blob then treat as JSON),
  `item_path`/`total_path` (`item_path` optional — omit it when the payload is already the job
  array, i.e. a bare root-level JSON feed like Jane Street), `page` (`offset`/`page`/`none`), and a
  `fields` map (dotted paths, `url` templates, list-concat descriptions) into the canonical dict via
  the shared `fetch/_recipe.py` helpers. One executor covers many boards (Amazon, ByteDance/TikTok,
  DE Shaw, Jane Street, …) with **no per-site code** — adding one stays a data row. Anything a recipe can't express is a
  `browser` recipe, never a hand-written adapter.
  **Browser (recipe) executor** (`fetch/browser.py`): the same recipe idea for boards plain HTTP
  can't reach — a headless Playwright Chromium renders the page and CSS selectors extract from the
  rendered DOM (`item` + `fields`, `url`-template pagination, optional per-role `detail` enrich). A
  realistic UA + viewport + `--disable-blink-features=AutomationControlled` and *waiting for the
  `item` selector* (not a fixed sleep) clears a Cloudflare "Just a moment" interstitial for the
  listing — the default headless-shell fingerprint otherwise gets stuck (0 cards). Cloudflare still
  re-challenges rapid deep-link navigations, so `detail` pages on a walled board return
  description-less; a **circuit-breaker bails detail after 3 straight empties** (postings still ship
  title/location/url; self-heals if the wall relaxes). **Isolated**: Playwright is lazy-imported and
  lives in `requirements-browser.txt` (not core), and `browser` rows are gated off the default cycle
  by `enable_browser_sources` (default off) — so a normal run stays pure `requests` and never imports
  Chromium. Members: Citadel Securities + Citadel (Cloudflare — list-only in practice, detail
  blocked) and Renaissance (Struts, JS-rendered, detail works). The pure `parse_jobs`/`apply_detail`
  are fixture-tested; the browser-driving `fetch` is not (like other adapters' network I/O).
  **Dual-mode (Workday, SmartRecruiters):** the *watchlist* lists the whole board
  (`fetch`), but the *feed* routes them through `fetch_one` so it pulls ONLY the
  surfaced jobs — listing a 1500-job board (N+1 detail-per-job) just to keep the 1-2
  the feed wants was the dominant feed cost (≈11 min for one big board). Workday's
  feed id is the job's externalPath (CXS per-job endpoint); SmartRecruiters' is the
  posting id. With this + concurrent fetching (below), a full feed pass dropped from
  ~tens of minutes to ~1 minute.
  *Backlog (in `feed_unresolved`, not routed):* iCIMS (bot-walled — "Human
  Verification" on every request, needs a real browser), greenhouse embed-token (no
  recoverable slug), ByteDance/TikTok (no clean API; JD only in fragile Next.js flight
  data). See [`PROGRESS.md`](./PROGRESS.md).
- **`feed/` — discovery-feed package.** Ingests a broad listing stream and resolves
  it back to boards (a feed is a *transport*, not a `source`). Pure parts:
  - `simplify` — `fetch` the SimplifyJobs `listings.json` (a public GitHub data
    file) over injected HTTP; returns raw listing dicts (no JD text).
  - `prefilter` — cheap metadata gate: keep `active` listings whose `category` is in
    the configured keep-list and whose `sponsorship` is not an explicit "no".
  - `resolve` — `resolve_url` maps an apply URL → `(source, slug, external_id)` for
    the board sources `lever`/`ashby`/`greenhouse`-direct (incl. the EU host)/`workable`
    (external_ids match the adapters exactly), and the per-job/per-listing detail
    sources `smartrecruiters` (posting id), `workday` (the job's `externalPath` for the
    CXS per-job endpoint), `oracle` (slug packs `{host}/{site}`), and `jobvite`; else
    `None`.
    `classify_reason` labels the residual unresolvable ones (an *unparseable* `workday`
    URL → `workday_deferred`, `embedded_greenhouse`, `unsupported_host`) for the
    `feed_unresolved` backlog.
  - `embedded_gh` — `resolve_embedded` is an *enriching* resolver for embedded
    greenhouse: `resolve_url` stays pure, so when it returns None and the reason is
    `embedded_greenhouse`, `run_feed` calls this (I/O) fallback to fetch the company
    page and scrape the board token (`…/embed/job_board?for=<token>`), yielding
    `("greenhouse", token, gh_jid)` — then the normal greenhouse list path ingests it
    (dedups with direct greenhouse). Wired only in `run.py` (DI). Recovers only the
    subset that embeds the token server-side; JS-injected embeds return None and stay
    on the unresolved board. **SSRF guard:** before fetching, `resolve_embedded` calls
    `util.is_safe_public_url` — only a public `http(s)` host is fetched; `localhost`
    and private/loopback/link-local/reserved IP literals (incl. `169.254.169.254`) are
    refused with no HTTP call.
- **`db.py` — SQLite layer.** WAL pragmas + `busy_timeout`; `upsert_postings`
  (dedup on `(source, external_id)`; persists `company_slug`), `get_by_status`
  (selects rows by pipeline status), `get_notifiable` (the notify gate: `scored`
  rows whose `score_detail` verdicts read `seniority=match AND domain=match AND
  NOT insufficient_context`, via `json_extract`), `save_score`,
  `mark_notified` (clears `pipeline_error`), `mark_failed` (terminal),
  `record_notify_failure` (retry-aware: keeps the row `scored` until the caller
  declares the budget exhausted, then parks it `failed`). Watchlist + feed
  helpers: `get_watchlist`, `count_watchlist`, `import_watchlist` (idempotent),
  `record_unresolved` (upsert on `url`), `existing_external_ids`. Issues no DDL.
- **`score.py` — `screen_posting` / `score_posting`.** Up to two calls, two backends,
  **SCREEN-gated**: the cheap local screen runs FIRST and gates the paid fit score. (1) The
  hard-requirements **SCREEN** runs on host Ollama (`think: false`, `num_ctx` from
  `OLLAMA_NUM_CTX`, default 8192), only when a non-empty `candidate` is supplied,
  and — with **no résumé in the prompt** — extracts each requirement (degree, work
  authorization, clearance) as a JOB fact *semantically*.
  CODE then decides pass/fail: for degree/clearance by applying the
  candidate's configured constraint to the extracted fact (a 4B model is unreliable at
  the pass/fail judgment itself); for **work authorization by a deterministic JD-text
  phrase gate** (`_check_authorization` / `NO_SPONSOR_PHRASES`) — disqualified only when
  the candidate needs sponsorship *and* the description literally contains an explicit
  no-sponsorship phrase. The model's `offers_sponsorship` guess is no longer trusted: it
  invented `"no"` from silence and the old loose substring guard fired on boilerplate
  ("company-sponsored", an EEO "citizenship" line) — the **D1** fix. `disqualified` is
  derived from those per-requirement verdicts. **Location is a deterministic code gate**
  (`resolve_location`) matched against the board's `posting["location"]`
  string — not the LLM. It resolves **every** token (not just the last) to a country —
  US state / country name via `pycountry`, else a city via **geonamescache** (highest-
  population match, so a tiny US namesake like Paris TX can't mask Paris FR) — and errs
  toward keep: keep if any token is US or an allowed country, discard only when ≥1 token
  resolves and none are allowed (naming the first foreign country), keep if nothing
  resolves (**D2** — superseded the last-token/`pycountry`-only gate that leaked a bare
  "London" and dropped multi-city US roles). US-state and remote strings keep, so a
  `locations`-only candidate makes no Ollama call. The screen prompt carries no
  location clause. The scoring prompts live in **two** files —
  `prompts/score.txt` (fit rubric) and `prompts/screen.txt` (Ollama
  hard-requirements checklist). Separately, when `candidate.exclude_internships` is set,
  intern/co-op roles are disqualified by a whole-word match on the job title (no LLM
  call — runs even when no other screen clause is configured). A SCREEN parse failure
  errs toward keep (not disqualified). (2) The fit **SCORE** — reached **only when the
  screen did not disqualify** (a discarded posting records `score` 0 and never pays
  for a fit call) — comes from an injected **`score_fit(postings, resumes) -> list[dict]`**
  callable: **batch-first, list in / list out**, one scorecard per input posting in the
  same order. `score_posting` itself always calls it with a one-posting batch and
  normalizes the single result (`fit([posting], resumes)[0]`); the batching payoff is at
  the `run_score` orchestration layer (§7.1/§9), not here. Two interchangeable twins
  build it, picked by `run.make_scorer` (`--score-backend`/`SCORE_BACKEND`); both send
  the **same prompt sections** (`_scorer_system_sections`) and the **same per-element
  JSON schema** (`_score_schema`), so a score is comparable across them and a prompt
  edit lands on both:
  - **`codex` (default)** — `make_codex_scorer`, the Codex CLI on the operator's
    **ChatGPT subscription** (flat-rate, not metered), and the **only backend with
    batching machinery**: one `codex exec` per call can handle up to `batch_size`
    postings at once (`--batch-size`/`CODEX_BATCH_SIZE`), because the subscription's
    quota is MESSAGE-bound, not token-bound — fewer `codex exec` calls would be the
    saving. **Batching is disabled by default (`DEFAULT_BATCH_SIZE=1` in `run.py`):**
    the live batched==single verdict-drift guard (§13) failed on the golden set
    (19/23 agree — cross-JD domain-verdict bleed), so per the design's rollout rule
    it does not ship; opt in via `--batch-size`/`CODEX_BATCH_SIZE` once the drift is
    fixed (§9, §11). Each JD gets its own `=== JOB job_ref=<posting id> ===` block in one prompt; the
    schema wraps N per-posting elements as `{"results": [{job_ref, ...}, ...]}`, enforced
    via `--output-schema`, JSON read back from `--output-last-message`. Results are
    realigned to the input postings **by `job_ref`, not list position** (an LLM isn't
    guaranteed to preserve order across N items) — a missing, duplicate, or unknown
    `job_ref` raises `ScoreError` for the **whole batch** (silently misattributing a score
    to the wrong job is worse than failing loudly). `batch_size=1` degrades to exactly
    the pre-batching one-call-per-posting shape (no special-casing).
    Auth is the operator's `codex login` state
    (`auth_mode=chatgpt`), **not** an env key — but `CODEX_API_KEY`, if set, *overrides*
    it and silently moves scoring onto metered API billing (`OPENAI_API_KEY` is ignored).
    Model `gpt-5.6-sol` (`CODEX_SCORE_MODEL`/`--codex-score-model`), the CLI's own
    default — chosen on the golden set, the only measurement that counts. `gpt-5.6-terra`
    looked better on a synthetic probe (tighter spread, half the credit rate) but scored
    **worse on real JDs** (gate agreement 76% vs 86%, flip-rate 38% vs 29%) and calibrated
    looser; `gpt-5.6-luna` was rejected outright (~3x looser spread) despite the docs
    recommending it for classification.
    **Tool-less by construction** (`--disable shell_tool`, `web_search="disabled"`) — a
    security boundary, since a JD is untrusted scraped text and `codex exec` is natively
    an agent with a shell that `--sandbox read-only` still lets read any file; also worth
    ~3.1k input tokens/call.
    **Pinned `model_reasoning_effort=low` + `model_verbosity=low`.** Effort buys nothing
    on this task shape (reasoning tokens were non-monotonic across levels) but **must** be
    pinned anyway: the default is server-controlled and was seen flipping `low`→`medium`
    →`low`. Verbosity is a no-op under `--output-schema`.
    **No determinism:** codex exposes no `seed`/`temperature`, so score noise cannot be
    turned off — but routing no longer depends on the noisy number (§9), so
    `make eval-score` gates on whether the per-dimension `seniority`/`domain` verdicts
    stay accurate, not on whether the score moves a band.
    **Quota-usage capture (free):** when `run.py` passes a `usage_path`, the scorer reads
    codex's own `/status` accounting (`used_percent`, `window_minutes`, `resets_at`,
    `plan_type`) off the **session rollout** the scoring call writes, and snapshots it to
    `codex_usage.json` in the shared db dir. Still free — it piggybacks the scoring
    message, no probe call. **Mechanism (learned the hard way, verified 0.144.5):**
    `codex exec --json` stdout carries only thread/turn/item events, **not** `rate_limits`;
    the quota figures live only in the session rollout, which `--ephemeral` suppresses. So
    when capturing, the scorer **drops `--ephemeral`**, reads the newest rollout past a
    pre-call mtime mark, then conditionally **deletes it** (net equivalent to ephemeral,
    usage extracted first). **Deletion is guarded, not merely mtime-picked:** codex owns
    the rollout filename, so there's no schema-independent way to tag "ours" — instead
    `_rollouts_after(since_mtime)` gathers **every** rollout newer than the mark, and the
    scorer deletes the newest one **only when it's the sole entry**. Zero or two-plus
    newer rollouts means a concurrent codex session (interactive, or another scoring run)
    landed in the same window, and the guard leaves *all* of them in place rather than risk
    nuking that session's history — still correct under the assumed-sequential `run_once`
    loop, just conservative when that assumption breaks. The eval/test path (no
    `usage_path`) keeps `--ephemeral` and its byte-for-byte gated call. codex reports
    `primary`+`secondary` limits; the observed `primary` was the **weekly** window
    (`window_minutes=10080`, `secondary` null), and the capture keeps whatever non-null
    limits are present, so a 5h secondary renders too if codex ever reports one (§11).
    Best-effort (a parse failure never breaks a score). The web renders it as a bar
    (§7.2); a live "now" reading is out of scope (it would cost a quota message). Capture
    is on the production `run_once` path only, not the eval harness. **Reaped on failure
    too:** the capture call sits in a `finally` around the `codex exec` subprocess call +
    exit-code check + result-JSON read, so a résumé-bearing rollout (full prompt: résumé +
    profile + JD) is deleted even when the exec raises `ScoreError` — capturing dropped
    `--ephemeral` to write that rollout, so leaving it on disk only on the success path
    would mean a failed call leaks the prompt.
  - **`claude`** — `make_claude_scorer` (metered API, `claude-sonnet-5` by default —
    structured outputs require it; `claude-sonnet-4-6` doesn't support
    `output_config.format` — overridable via
    `ANTHROPIC_SCORE_MODEL`/`--anthropic-score-model`); needs `ANTHROPIC_API_KEY`. Does
    **not** batch — `fit` loops one `messages.create` call per posting regardless of
    `batch_size` (harmless no-op chunking cadence on this backend): Claude's win is the
    cached system prefix (already flat per-call marginal cost), not fewer round-trips,
    so batching would only save request count, which doesn't matter on metered billing.

  Either backend raises `ScoreError` on a failed call. On `claude` (single-call) that
  fails **one** posting, same as before. On `codex` (batched) a raised `ScoreError` — or
  any other exception, e.g. a transient API error from the `claude` backend surfacing
  through the same `run_score` call site — fails the **whole batch call**; `run_score`'s
  safety net (§9) catches that and retries the batch's postings **singly**, so one
  malformed batch costs latency, not correctness, and only a single that still fails
  marks just that one row `failed`. A non-zero `codex exec` exit never
  yields a `0` score, because codex purges `~/.codex/auth.json` after repeated auth
  failures and a logged-out cron must fail loudly, not score the queue 0.
  `resumes` is the `{label: text}`
  dict `run.py`'s `load_resumes` builds from every `*.txt` in `--resume-dir`: label =
  filename minus a leading `resume_` (`resume.txt` → `resume`,
  `resume_quant_dev.txt` → `quant_dev`), plus an optional `personal_profile.txt`
  read separately as about-the-candidate context (goals/constraints/preferences,
  never itself scored as a résumé); two files deriving the same label, or zero
  resume files, is a config error (`SystemExit`, never a silent overwrite). The
  scorer sends **all resume versions** (+ the profile, if present) and the rubric as
  **one cached system prefix** (`cache_control: ephemeral`, byte-identical every
  call in a run, only the JD is fresh) with **adaptive thinking**, returning
  schema-constrained JSON: a structured **`assessment` scorecard** (ordered first so the
  model works the verdicts before the number) + `score 0-100`. The scorecard carries
  enum-constrained `seniority` (match/too_junior/too_senior) and `domain`
  (match/adjacent/mismatch) verdicts + notes, split `must_haves` {met, missing} /
  `nice_to_haves` {missing}, and a one-line `summary` (**S2.1** — replaced the flat
  `matched_keywords`/`missing_keywords` lists + prose `reasoning`). The **`domain`
  verdict is a target-fit rule** (redesigned 2026-07-17, replacing the criteria-less
  "is their background in this role's domain?"): the model records **three checks** in
  the note — (1) ANTI-TARGETS, (2) which TARGET priority the role's *day-to-day work*
  (not its title) falls under, (3) whether the RÉSUMÉ evidences the field — and collapses
  them deterministically (`mismatch` if anti or no-target-and-no-background; `match` if
  TARGET priority 1-3 and résumé-backed; `adjacent` otherwise) against the operator's
  gitignored `personal_profile.txt` (TARGET tiers / ANTI-TARGETS / POSITIONING). This is
  what makes the match/adjacent line — which the notify predicate turns on (§9) — a
  checkable rule rather than a vibe, and drove the eval flip-rate from 24–38% to 5% (§13).
  Because the verdict reads the profile, **verdict behavior is operator-tunable via the
  profile, not only the prompt** — e.g. an "engineering-facing analyst with real tooling"
  seat is a `match` or `adjacent` depending on how the profile's tier-3 qualifier is
  drawn. The prompt scores
  from the verdicts: a material seniority gap floors the score at 0–30 (**D3**), and
  missing `nice_to_haves` barely move it (**D4**). The scorer also sets a top-level
  **`insufficient_context`** boolean (**case #2**): true when the JD is too thin,
  boilerplate, or truncated to assess fit with confidence — a signal (independent of the
  0–100 score, which is still filled in as best it can) that routes the posting to the
  **Low-context** bucket for human review rather than trusting the number. With **two or more** resume versions
  the schema additionally requires `recommended_resume`, enum-constrained to the actual
  labels (so the model can never name a nonexistent version) — the best-fitting version,
  persisted in `score_detail` and surfaced as a `Resume: <label>` line in the Telegram
  alert and an always-visible badge in the job detail modal; a single-resume setup omits
  the field entirely. The JOB section sent to this call **omits the location line**
  (`include_location=False`) so geography can't move the fit number (**D5** — location is
  the screen gate's decision; the same role posted per city scores identically). `score_posting` normalizes/clamps the result and validates the
  scorecard (`ScoreError` on a missing score or an out-of-enum verdict); the modal renders
  the scorecard with a legacy matched/missing/reasoning fallback for pre-S2.1 rows.
  **There is no local experience/years gate** — seniority is judged by the Claude
  scorecard's verdict + floor, not a deterministic code check.
- **`notify.py` — `notify_posting`.** Telegram `sendMessage` (company / title /
  score / JD link, plus an optional `Resume: <label>` line when `score_detail`
  carries `recommended_resume`) — a single atomic message per match; the human
  applies by hand.
- **`pipeline.py` — orchestration.** Stateless stage functions over a db
  connection with injected worker callables and an explicit `now`:
  `run_fetch` → (`run_feed`) → `run_score` → `run_notify`. Every stage
  wraps each item in try/except: one bad posting/company is recorded
  (`db.mark_failed`; at the notify stage `db.record_notify_failure`, which retries —
  §9) or skipped, and the batch continues. `run_feed` (optional) runs
  the feed: prefilter → resolve → record-unresolved, then groups survivors by
  `(source, slug)`, skips ids already ingested (`existing_external_ids`), and ingests
  the surfaced postings via one of two paths: **per-board** sources fetch the whole
  board via the existing adapter and keep **only** the surfaced ids (exact
  `external_id` membership); **detail sources** (`fetch.DETAIL_SOURCES` — oracle,
  jobvite, plus the per-job feed routes for smartrecruiters/workday) fetch each
  surfaced id directly via `fetch_one_company` (per-id try/except, so one bad listing
  is skipped). The network work runs **concurrently** (a `ThreadPoolExecutor`; the
  embedded-greenhouse I/O resolves and the per-group fetches each fan out) while every
  DB read/write stays on the main thread — SQLite connections aren't safe across
  threads. `run.py` hands each worker thread its own `requests.Session` (keep-alive)
  and a shorter timeout. A fetched posting is **validated** (`_valid_posting`:
  non-empty `external_id` + `job_title` + `description`) before it counts — an empty JD
  means a scrape silently lost the body, the main way an HTML/JS scraper breaks without
  raising. Any failed id (raise / `None` / invalid) is recorded in `feed_unresolved`
  (`reason="detail_fetch_failed"`, host from the listing URL) so a broken scraper
  surfaces on the unresolved board instead of vanishing; a source that resolves ids but
  keeps **none** also prints a one-line collapse warning. Each kept posting is stamped
  with its `company_slug`.
  `run_score` is **screen-all-then-batch-fit-survivors**, not one per-posting loop:
  (1) every `new` row is screened (Ollama, per-item — one bad screen call marks only
  that row `failed`), and a disqualified one is persisted `discarded` right here,
  **never** reaching the fit call; (2) the survivors are chunked into batches of
  `batch_size` (**default 1 — batching parked**, see below) and each chunk is **one**
  `fit_fn` call; (3) a chunk whose call raises — `ScoreError` or any other exception —
  falls back to scoring that chunk's postings **singly**, so one malformed batch costs
  latency, not correctness, and a single that still fails marks only that row
  `failed`. `batch_size` is harmless on the `claude` backend (which loops internally
  regardless) and would be the quota lever on `codex` if raised above 1 (§7.1's scorer
  description, §11 quota math) — but the live batched==single guard failed on
  domain-verdict bleed, so `batch_size` stays at its parked default of 1 until that's
  fixed.
  Stage gating in §[9](#9-behaviors-and-invariants).

### 7.2 Web (`apps/web/src/`)

- **`app/page.tsx`** — dashboard entry; SSR with `export const dynamic =
  'force-dynamic'` so it always reads the live db.
- **`app/api/health/route.ts`** — DB-reachability probe for the Docker healthcheck.
  `GET` runs `SELECT 1` (`200 {status:"ok"}`, else `503`) so a stale bind mount is
  caught and the `autoheal` sidecar can restart the container (§6).
- **`app/api/codex-usage/route.ts`** — serves the codex quota snapshot the worker
  captures off each scoring call (§7.1): reads `codex_usage.json` (path derived from
  `DATABASE_URL`, overridable via `CODEX_USAGE_FILE`), returns the snapshot plus `as_of`
  (the file mtime). Missing/unparseable → empty state (`{limits:[], as_of:null}`, still
  `200`), since the worker may not have scored yet.
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
  - *Discovered jobs:* `getJobPostings` (score-aware `bucket` ∈ matched/belowbar/
    discarded/lowcontext/failed, default matched; sort `JobSort` ∈ score/posted, default
    score; paginated `page`/`size`; optional `minScore` filter and, for the discarded
    bucket, a disqualification-`cause` ∈ authorization/location/degree/clearance/internship
    sub-filter). `discardJobPosting`,
    `reopenJobPosting`, `bulkRemove(ids)` (terminal `removed`, UI-only hide, worker-inert),
    `bulkReopen(ids)`, `removeAllInView(bucket, filters)`, `markJobApplied(id, category)`
    (category chosen at apply time, validated against `CATEGORIES`, default `Others`).
    Bucket definitions and `removed` semantics in §9.
  - *Watchlist:* `getWatchedCompanies` (name asc), `addWatchedCompany` (validates
    `source ∈ VALID_SOURCES`, dedups `(source, slug)`, and rejects a `slug` outside
    `[A-Za-z0-9._/-]` or containing `..`/leading-trailing-doubled `/` — the slug is
    interpolated into a fetch URL host/path by the worker, so this blocks
    host-injection metacharacters while still allowing multi-part slugs like
    workday's `tenant/dc/site`), `removeWatchedCompany`.
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
- **`lib/constants.ts`** — `STATUSES` (14), `CATEGORIES` (9),
  `VALID_SOURCES` (7 watchlist-capable boards, mirrors the worker; feed-only sources
  are not listed), `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`
  (200; the trimmed-`description` char count below which a scored posting is bucketed
  Low-context — the single tuning knob for that heuristic), `getStatusColor`. **Edit here
  to extend statuses/categories/sources.** `MATCH_SCORE_THRESHOLD` was **removed** — the
  Discovered-Jobs matched/below-bar split is now the verdict predicate (`matchedIds()` in
  `lib/actions.ts`, mirroring the worker's `db.get_notifiable`), not a score cutoff; the
  fit score is display/ranking only.
- **`components/`** — `Dashboard` (Applications ↔ Discovered Jobs ↔ Watchlist ↔
  Unresolved tabs), `ApplicationTable` (inline status edit), `KPIGrid`,
  `StatusHistoryModal`, `AddApplicationForm`, `DiscoveredJobsTable` (bucket tabs on their
  own row — Matched/Below-bar/Discarded/Failed/Low-context — above a filter row of sort
  toggle Best match/Newest posted + score/disqualification-cause filters; a bucket-aware
  per-row "why" subline (below-bar seniority/domain verdict pills + top missing must-have,
  falling back to the legacy one-line `reasoning` for pre-S2.1 rows; disqualification
  reason; thin-JD size; pipeline error); a `recommended_resume` label under the score;
  folded Company/location/source and Posted/Fetched date columns + bulk
  Remove/Reopen/Remove-all-in-view + job-title links to the live posting),
  `Pagination` (reusable: first/last, numbered pages, go-to), `ApplyCategoryDialog`
  (category picker on Mark Applied), `WatchlistTable`
  (list + add/remove watched companies), `PromotionSuggestions` (approve/dismiss feed→
  watchlist suggestions, shown in the Watchlist tab), `UnresolvedFeedsTable` (read-only
  backlog), `CodexUsageBar` (codex quota bar on the Discovered Jobs view — polls
  `/api/codex-usage`, one bar per limit with % + "resets in Nd Hh" + "as of"; reflects
  the last scoring call, not a live reading), `JobDetailModal` (JD + score detail), and
  the four charts `TimelineHeatmap` /
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
  score           Int?          // 0-100, from Claude fit score
  score_detail    String?       // JSON: assessment scorecard (seniority/domain/must_haves/nice_to_haves/summary), insufficient_context flag, screen, disqualification, recommended_resume (pre-S2.1 rows: matched/missing keywords + reasoning)
  posted_at       String?       // board posting date YYYY-MM-DD (greenhouse/lever/ashby/workday); scrape-date fallback for pinpoint + dateless rows
  pipeline_status String        @default("new") // new|scored|notified|applied|discarded|failed|removed
  pipeline_error  String?       // last stage/send error; cleared on successful notify
  attempts        Int           @default(0)     // cumulative failures (notify retries until 3, then parks failed)
  application_id  Int?          // back-link once marked applied
  application     applications? @relation(fields: [application_id], references: [id], onDelete: SetNull)
  created_at      String
  updated_at      String?

  @@unique([source, external_id])  // dedup key
  @@index([pipeline_status])
}

model watched_companies {        // the DB-owned watchlist (web-managed)
  id          Int     @id @default(autoincrement())
  source      String  // greenhouse|lever|ashby|workday|pinpoint|smartrecruiters|workable|icims|phenom|custom|browser
  slug        String  // board identifier (workday packs tenant/datacenter/site)
  name        String
  recipe      String? // JSON recipe for source=custom|browser (declarative fetch); NULL otherwise
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
  `Rejected`, `Withdrew`, `Ghosted`.
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
notify:  scored, seniority=match AND domain=match AND NOT insufficient_context → notified
                                                   (else: stay scored, untouched;
                                                    success clears pipeline_error)
         on send error            → scored         (attempts+1, pipeline_error recorded;
                                                    retried next pass — the 3rd cumulative
                                                    failure parks the row failed)
fetch/score, on exception         → failed         (pipeline_error set; batch continues)
UI:      any non-applied row      → removed        (terminal; bulk Remove; UI-only hide)
```

- **`removed` is a terminal, UI-only status.** Set by `bulkRemove` / `removeAllInView` and by the per-row dismiss (`discardJobPosting`); the worker never writes it and never transitions away from it (`run_score`/`run_notify` ignore `removed` rows). Invisible to all buckets in the Discovered Jobs view; effectively hides the row without deleting it.

- **Stage gating is strict:** `run_score` processes only `new`; `run_notify` only
  `scored` rows the fit verdicts mark a strong match (`db.get_notifiable` —
  `seniority=match AND domain=match AND NOT insufficient_context`; non-matching rows
  stay `scored`, untouched). The score is not the gate — it quantizes to a rubric
  band edge and flipped run-to-run near the old `≥75` threshold, while the verdicts
  held stable across every draw (see `PROGRESS.md`). A failure in one posting never
  aborts the batch (per-item try/except → `mark_failed`, or the notify stage's
  bounded retry — see "Failure handling and recovery limits" below).
- **Screening is part of scoring, not a separate stage.** With an empty `candidate`
  block, the screen call is skipped entirely (no disqualification). A `discarded`
  row keeps its `score`/`score_detail` (including `disqualification_reason`) so the
  UI can explain *why*.
- **A batch-fit call can never silently misattribute a score to the wrong posting.**
  `make_codex_scorer`'s batched `fit` realigns results by `job_ref` (the posting id),
  not list position; a missing/duplicate/unknown `job_ref` raises `ScoreError` for the
  **whole batch** rather than pairing a scorecard with the wrong JD. `run_score` (§7.1)
  catches that (or any other exception the batch call raises) and retries the batch's
  postings **singly** — one malformed batch costs latency, not correctness or
  misattribution, and only a single that still fails marks just that one row `failed`.
- **`now` is injected** per run (ISO-8601 UTC ms), making the pipeline
  deterministic and testable without a clock or network.

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
  resolved id, so no keep-filter is needed.
- **Silently-broken scrapers are made visible.** A detail-fetch failure — a raise, a
  `None`, or a posting failing `_valid_posting` (non-empty id/title/description) — is
  recorded in `feed_unresolved` (`reason="detail_fetch_failed"`) like an unresolvable
  URL, so it shows on the unresolved board rather than vanishing into the swallowed
  per-listing exception. A source that resolves ids but keeps none additionally prints a
  collapse warning. (Canary self-tests and proactive Telegram/banner alerting are
  deferred — see PROGRESS.) These sources are **feed-only**: they
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
  `count(pipeline_status ∈ {notified,applied}) ≥ 2` **or**
  `count(applied) ≥ 1`, ranked by applied then high-score count. Approve is the user
  calling `addWatchedCompany`; `dismissPromotion` records `(source, slug)` (idempotent)
  to suppress it. The watchlist only ever grows by an explicit human action.

**Web ↔ pipeline seam** (`lib/actions.ts`):

- **Discovered-jobs buckets** (`getJobPostings`, `bucket` ∈ {matched, belowbar, discarded,
  lowcontext, failed}, default `matched`). Verdict-aware, not score-aware — the fit
  **score is display/ranking only and gates nothing**: **matched** = `{scored, notified}`
  rows whose `score_detail` verdicts read `seniority=match AND domain=match AND NOT
  insufficient_context` (`matchedIds()`, a raw `json_extract` query), **minus low-context
  rows**. Both the Matched tab and the worker's notify gate (`db.get_notifiable`) apply
  the **same** low-context hold-back — the enum predicate **and** a thin-JD exclusion
  (`insufficient_context` OR `LENGTH(TRIM(description)) < 200`,
  `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`) — so **the UI's Matched tab and the Telegram alert
  agree**: a short-but-confident `match/match` JD is held back on both sides and shown
  under **Low-context**. (The `200` is hand-synced between `get_notifiable` and web
  `constants.ts` — a cross-service constant, flagged in both.) **belowbar** = `{scored,
  notified}` rows outside
  that id set — every scored-but-not-a-verdict-match row, *including* deep misses, so
  nothing scored is orphaned (ACTIVE rows are never disqualified, so this is cleanly
  "scored, not a match"); **discarded** =
  disqualified **only**: `pipeline_status='discarded'` with the screen's `disqualified:true`
  (substring-matched in `score_detail`, tolerating `"disqualified": true` / `"disqualified":true`
  spacing) — a non-matching scored row is **not** discarded (it lives in belowbar);
  **lowcontext** = `{scored, notified}` rows too thin to score with confidence, by
  **either** signal (OR): a short JD body (`LENGTH(TRIM(description)) <
  LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`, default 200 — case #1) **or** the fit scorer's
  persisted `insufficient_context: true` flag (case #2 — a full-length but boilerplate/
  truncated JD the LLM couldn't assess); **failed** = `pipeline_status='failed'`. All
  buckets exclude `removed` rows, and the buckets are **mutually exclusive** — the
  low-context set is a *derived* (query-time, part-persisted) id set from one raw query
  (`LENGTH(...) < N OR json_extract(score_detail,'$.insufficient_context') = 1`) layered
  as `id IN` on the low-context bucket and `id NOT IN` on the others, so a low-context
  scored row appears only under Low-context, never in Matched/Below-bar. Each is **paginated**
  (`page`/`size`, default 25) and sortable (`JobSort` ∈ `score`/`posted`, default
  `score desc`; `posted` orders by `posted_at desc, id desc`). Optional filters: a
  `minScore` floor (any bucket) and, within discarded, a disqualification-`cause` ∈
  {authorization, location, degree, clearance, internship} sub-filter — a *derived* id set
  (mirroring low-context) from a raw query matching the worker's keyed
  `disqualification_reason` via `json_extract(score_detail,'$.disqualification_reason') LIKE`
  the cause pattern (`%authorization:%`, `%location:%`, `%degree:%`, `%clearance:%`,
  `%internship/co-op%`), layered as `id IN` on the discarded query. `getJobPostings`
  returns every row's `created_at` + `posted_at` (the table shows both dates).
- **`markJobApplied(id, category?)`** runs in a `$transaction`: it refuses if an
  application with the same `(company_name, job_title)` exists, else creates the
  application (`status='Applied'`, `category` chosen by the user at apply time —
  validated against `CATEGORIES`, default `Others` — url from `job_url`) and atomically
  sets the posting to `pipeline_status='applied'` + `application_id`. Application and
  back-link are created together or not at all.
- **`reopenJobPosting(id)`** reverses a disqualification (from the Discarded view) back
  to `scored`, preserving `score_detail`.
- **`discardJobPosting(id)`** — the per-row dismiss — sets `pipeline_status='removed'`
  (hidden, like bulk Remove), **not** `discarded`: the Discarded bucket is disqualified-only,
  so a hand-dismissed row must not masquerade as an auto-disqualification.
- **`bulkRemove(ids)`** sets `pipeline_status='removed'` for the given ids (terminal;
  available in Matched and Discarded buckets).
- **`bulkReopen(ids)`** sets `pipeline_status='scored'` for the given ids (available in
  the Discarded bucket; reverses a prior discard or bulk-remove back to scored).
- **`removeAllInView(bucket, filters)`** applies `bulkRemove` to every row matching the
  current bucket + filter (available in the Discarded bucket; respects the disqualification-
  `cause` sub-filter + `minScore`).

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

**Cross-service data invariant:** the schema is owned solely by Prisma; the worker
reads/writes rows but issues **no DDL**. The worker's test fixture
(`apps/worker/tests/fixtures/schema.sql`) is kept in sync with `schema.prisma` by a
CI guard (`tools/check_schema_drift.mjs`, `make check-schema`).

**Failure handling and recovery limits:**

- **`failed` is terminal.** No stage transitions a row *out* of `failed`
  (`run_score`←`new`, `run_notify`←`scored`); recovery is a human act
  (`reopenJobPosting`/`bulkReopen` write `scored`). A fetch/score exception parks the
  row `failed` immediately.
- **Notify send errors are retried, bounded.** `run_notify` treats a Telegram send
  error as transient: the row **stays `scored`** (`attempts+1`, `pipeline_error`
  recorded) so the next scheduled pass retries the send — the match never leaves the
  default Discovered-Jobs view while retrying. The `NOTIFY_MAX_ATTEMPTS`-th (3)
  cumulative failure parks it `failed` (terminal, the Failed tab), so a *persistent*
  channel failure (revoked token, wrong chat id) surfaces in a visible queue instead
  of retrying silently forever. A successful send clears `pipeline_error`. Delivery
  is **at-least-once**: the send is a single atomic `sendMessage`, so a timeout after
  delivery can only duplicate the alert, never half-send it — a duplicate ping beats
  a lost match. `attempts` counts failures cumulatively, so a row manually reopened
  from `failed` gets one fresh notify attempt per reopen. Design:
  [`superpowers/specs/2026-07-09-notify-retry-design.md`](./superpowers/specs/2026-07-09-notify-retry-design.md).

**Unenforced clause (asserted, not checked).** One contract-flavored claim has no
deterministic gate; treat it as an *intention backed by the human in the loop*, not a
guarantee:

- **Hard-constraint screening**: **work authorization** is a deterministic JD-text
  phrase gate (`_check_authorization` / `NO_SPONSOR_PHRASES`) — disqualified only when
  the candidate needs sponsorship *and* the description literally states no sponsorship;
  the 4B model's `offers_sponsorship` guess is not consulted (**D1** fix — it invented
  "no" from silence and the old substring guard fired on boilerplate). A JD that declines
  to sponsor in wording outside the phrase set errs toward keep. **Clearance** remains an
  LLM *semantic* extraction with a code check — a misjudgment sends a spurious alert or
  discards an applicable role. The kept `disqualification_reason` + `reopenJobPosting`
  let a human override.
- **Location** is a deterministic `resolve_location` check (pycountry + geonamescache
  city index), not an LLM judgment, and errs toward keep. The old bare-"London" leak is
  closed (city tokens now resolve to a country); the residual gaps are ambiguity-shaped:
  a city name whose **highest-population** bearer is foreign discards even when the
  posting meant a smaller US namesake ("Manchester" → GB, though Manchester NH exists —
  real boards append the state, which the US-state guard keeps), and a token that
  resolves to nothing at all still keeps. Both are backed by the human in the loop (kept
  `disqualification_reason` + `reopenJobPosting`).

### Invariant → test traceability

Grounds the "verifiable" claim. ⚠ marks an invariant with **no** (or only indirect)
automated coverage — those rely on code review or the human in the loop, not a test.

| Invariant | Test(s) |
|-----------|---------|
| Pipeline stage gating + per-item failure isolation | `worker/tests/test_pipeline.py`, `integration/test_pipeline_e2e.py` |
| Dedup `(source, external_id)` on ingest | `test_db.py`, `test_pipeline.py` |
| WAL + `busy_timeout` pragmas on connect | `test_db.py` |
| Disqualified → `discarded`; empty candidate skips the screen | `test_score.py`, `test_pipeline.py`, `test_run.py` |
| Deterministic location gate (`resolve_location`, pycountry + geonamescache; every token resolved): foreign→discard, US-state/US-city/remote/missing→keep | `test_score.py` (`test_resolve_location`, `test_token_country_*` + gate integration tests) |
| Multi-resume loading (`load_resumes`): label = stem minus `resume_`; `personal_profile.txt` → profile, never a version; sorted order; dotfiles skipped; zero files / duplicate label / non-UTF-8 → clean `SystemExit` | `test_run.py` (`test_load_resumes_*`) |
| Multi-resume scoring: `recommended_resume` enum-constrained to the actual labels (≥2 versions), field omitted for a single resume; cached-prefix block layout (header → profile → resumes, `cache_control` on last); normalization pass-through | `test_score.py` (`test_score_schema_*`, `test_scorer_system_blocks_*`, `test_recommended_resume_*`) |
| `recommended_resume` persisted in `score_detail`; Telegram `Resume:` line only when set — malformed/absent `score_detail` never crashes notify; modal badge renders when present, absent otherwise | `test_pipeline.py`, `test_notify.py`, `web/components/__tests__/JobDetailModal.test.tsx` |
| `mark_failed` → terminal `failed` + `attempts+1` (fetch/score paths) | `test_db.py` |
| Notify send error → stays `scored` + `attempts+1` + error recorded; parks `failed` at `NOTIFY_MAX_ATTEMPTS` (3); success clears `pipeline_error`; notified rows never re-alerted | `test_pipeline.py`, `test_db.py`, `integration/test_pipeline_e2e.py` |
| Discovered-jobs score-aware buckets (matched/belowbar/discarded/lowcontext/failed, mutually exclusive; discarded = disqualified only; low-context = thin-JD **or** `insufficient_context` flag) + sort (score/posted) + pagination + disqualification-cause sub-filter + bulk remove/reopen/removeAllInView; per-row dismiss → `removed` | `web/src/__tests__/actions.test.ts`, `actions.int.test.ts`, `components/__tests__/DiscoveredJobsTable.test.tsx` |
| Fit scorer emits a top-level `insufficient_context` boolean (schema-required, normalized, persisted); Below-bar why-cell shows seniority/domain verdict pills + top gap with a legacy-`reasoning` fallback; `recommended_resume` label under the score | `worker/tests/test_score.py`, `test_pipeline.py`, `web/components/__tests__/DiscoveredJobsTable.test.tsx` |
| `markJobApplied` atomic create + back-link + dedup | `actions.test.ts`, `actions.int.test.ts` (real-Prisma tx) |
| `updateApplicationStatus` validates `STATUSES`, appends history | `actions.test.ts`, `actions.int.test.ts` |
| `reopenJobPosting`→`scored`, `discardJobPosting`→`discarded`, `bulkRemove`→`removed`, `bulkReopen`→`scored`, `removeAllInView` | `actions.test.ts`, `actions.int.test.ts` |
| `deleteHistoryItem` recomputes current status | `actions.int.test.ts` |
| KPI aggregation buckets | `actions.test.ts`, `actions.int.test.ts` |
| ⚠ Chart-data aggregation (`getStatusFlow`/`getTimelineData`/`getCategoryData`) | **none** — no unit/integration/e2e coverage; only the components render |
| CSV import/export rules (dedup, enum fallback) | `actions.int.test.ts` |
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
- **Server Actions, not REST.** All mutations go through Server Actions; the one
  exception is the `GET /api/health` route — an HTTP-status probe the Docker
  healthcheck can call, which doesn't fit the Server Action model.
- **Local + cloud LLM split.** The hard-requirements SCREEN is high-frequency
  (every posting with candidate constraints configured) → stays on local Ollama on
  the GPU, free and rate-limit-free, `qwen3.5:4b` (fits an 8 GB card, `think:false`
  so reasoning models still return JSON) — it only extracts JOB facts; CODE applies
  the candidate's constraints, since a 4B model is unreliable at the pass/fail
  judgment itself. The fit SCORE (every posting) goes to a **hosted** model: scoring
  needs a real seniority/domain judgment the local model kept getting wrong
  (mode-collapsed scores, missed disqualifiers). It runs by default on the **Codex CLI
  against the operator's ChatGPT subscription** — a full re-score of the ~640-row queue
  is a flat-rate pass instead of a metered one, which is what the cost of re-scoring
  actually turns on. The codex fit call has **batching machinery** (up to `batch_size`
  postings per `codex exec`) because that subscription's real limit is a MESSAGE-bound
  quota, not tokens (§7.1/§11) — but it is **parked at `batch_size=1` (disabled by
  default)**: the live batched==single guard failed on the golden set (cross-JD
  domain-verdict bleed), so the intended quota win is not active — the loss of
  any determinism knob (no `seed`/`temperature` on `codex exec`) remains; the Claude backend
  stays wired for a metered A/B and deliberately does **not** batch. Claude's cached system prefix (rubric + optional
  profile + all resume versions) keeps its per-posting cost down to just the fresh JD;
  codex has no such lever, so amortizing the fixed scaffolding cost across a batch would
  stand in for it, if batching were enabled.
- **Résumé is authoritative for evidence; the profile only shapes fit.** The gitignored
  `personal_profile.txt` may push a fit score *up* (genuine interest — the one legitimate
  upward lever, since interest ≠ skill), *down* (honest caveats), or *sideways* (positioning
  / target direction), but it **never injects a skill the résumé lacks** — a recruiter sees
  the résumé, so a genuine gap is fix-the-résumé signal (put courses on the résumé), not
  profile content. **Config vs profile seam:** `config.yaml` serves the machine — the
  structured hard constraints feeding the deterministic screen gates (degree / auth /
  clearance / location / internships) — and stays structured (dissolving it into prose would
  regress the gates); the profile serves only the LLM fit score, so it holds target direction
  (priority-ordered) · anti-targets · career stage · self-positioning · genuine interests ·
  honest downward caveats, and **excludes** anything the résumé omits and any hard constraint
  already in config. Kept concise + stable (a cached prefix on every score call).
- **Charts are mostly hand-rolled SVG.** Heatmap, funnel, and Sankey are written
  directly so they render exactly right on dark backgrounds without per-library
  theming; only the donut uses Recharts. The Sankey palette is deliberately
  desaturated so flow geometry leads, not color.
- **Fully dependency-injected worker.** Every external (Ollama, Claude, Telegram) is
  injected, so the pytest suite runs anywhere with no network and no keys; real
  wiring lives only in `run.py`.
- **UID/GID passthrough.** Containers run as the host user so bind-mount writes work
  without `chmod 777`.
- **Official board APIs only.** Greenhouse/Lever/Ashby/Workday/Pinpoint public
  endpoints are stable and compliant; LinkedIn/Indeed scraping is deliberately
  avoided. Adapters are isolated so one broken source only affects that source.

---

## 11. Non-functional requirements

- **Privacy:** resume (`apps/worker/resume/`), secrets (`apps/worker/.env`),
  config (`config.yaml`), and the database (`db/`) are gitignored. The repo ships
  only `*.example` templates; real resume files are untracked, so no extra git
  steps are needed for *new* work (see `CONTRIBUTING.md`). **Open defect (PROGRESS):**
  gitignore prevents *future* commits only — `resume.txt` + the real `config.yaml`
  were committed 2026-06-05 and untracked 2026-06-08, but the blobs remain in the
  **public** repo's git history and need a history rewrite (or private repo) to purge.
- **Reliability / error recovery:** one bad posting or flaky external never aborts a
  batch — the failure is recorded on the row and processing continues. The scorer
  returning junk JSON marks that row `failed` rather than crashing. A notify send
  error is retried across passes (bounded at 3) before parking `failed`; `failed`
  itself stays terminal and manual-reopen-only — see §9, "Failure handling and
  recovery limits."
- **Concurrency safety:** WAL + `busy_timeout=5000`ms (+ the directory mount) keep the
  containerized web app and the host worker from hitting `database is locked` **under
  low write-contention**
  (concurrent readers + one serialized writer; brief contention blocks-and-retries up
  to 5 s). Not a guarantee under sustained dual-write load.
- **Performance:** the local hard-requirements screen runs ~2 s/posting on an 8 GB
  GPU; the fit score adds one hosted call per **batch of up to `batch_size` postings**
  on the default `codex` backend — tens of seconds per `codex exec` turn, amortized
  over the batch when `batch_size>1` — but `batch_size` defaults to **1** (batching
  parked, see below), so in practice this is one `codex exec` turn per posting; or one
  cached-prefix API call **per posting** on `claude` (unbatched by design; see §7.1).
  The root page is `force-dynamic` (no stale cache).
- **Subscription quota is the real bound on a big re-score — flat-rate is NOT
  unlimited, and batching, if it shipped, is what would make the queue fit it.
  It doesn't ship: the acceptance guard failed, so the win below is unrealized.**
  Codex on ChatGPT Plus meters usage as a **message budget** whose observed **binding
  limit is weekly** (codex's own `rate_limits`: `window_minutes=10080`; a shorter 5h
  `secondary` may also apply but was null when observed — the capture renders whatever
  codex reports, §7.1). At the **shipped default** `batch_size=1`, a ~640-row re-score is
  ~640 messages against that budget — it must be **paced against remaining weekly
  headroom** (now visible via the codex usage bar, §7.2), not run in one sitting — and
  this is the actual current cost, not a
  worst case: batching machinery exists (`--batch-size`/`CODEX_BATCH_SIZE`, §7.1/§9)
  but is **parked at `batch_size=1` (default-off)**. *If* raised to `batch_size=10`,
  the same 640 rows would become **~64 `codex exec` calls** — turning a multi-window
  job into something that could plausibly clear in one or two — and because the fixed
  scaffolding prefix (below) would then be paid once per **batch** instead of once
  per **posting**, total input tokens would drop **~6×** too. **That number is not
  live-validated and is not attainable at any batch size:** `tools/score_eval.py
  --batched` (§13), the live guard that asserts batched verdicts match single-scored
  verdicts on the golden set, **ran 2026-07-16 (`gpt-5.6-sol`, `batch_size=10`, 23
  rows) and FAILED — 19/23 agree**, every drift row on the **domain** verdict.
  The follow-up **drift probe** (§13, K=3 per row at b=1/5/10, 2026-07-17) then
  **confirmed the cause is real context bleed and showed it scales with batch size**
  (rows holding one verdict: **3/4 → 2/4 → 1/4** at b=1 → b=5 → b=10) — and killed the
  obvious salvage: **`batch_size=5` is not a safe middle ground**, it turns id 111 from
  stably *correct* into stably *wrong* (`match/match` ×3, crossing the notify
  predicate), and it bleeds id 132's **seniority** verdict, so the corruption is not
  confined to `domain`. Per the design's rollout rule, batching does not ship at **any**
  size >1: `run.py`'s `DEFAULT_BATCH_SIZE=1`, and the queue re-score stays on the
  unbatched, multi-window path. **The ~64-call / ~6×-token win is therefore off the
  table via batching** — the message-quota problem needs a different lever (pacing across
  windows + the usage tracker in `PROGRESS.md`), not a bigger batch. A fix would have to
  be *stronger per-JD prompt isolation*, but on this backend isolation is what one-JD-per-
  call already buys — i.e. the win and the fix are in tension. At the cap Codex hard-
  blocks (no degraded fallback) and `codex exec` exits **1 with no distinct rate-limit
  code**, so any pacing logic must match the stderr text, not the exit status. Each call
  also pays a fixed ~9.7 k input tokens of Codex scaffolding (12.8 k before the tools
  were disabled) to emit ~80 tokens of JSON per posting in the call, and **gets no
  prompt-cache credit**
  (`cached_input_tokens` was 0 even on back-to-back identical prompts) — the opposite of
  the `claude` backend, whose cached prefix makes the marginal posting nearly free. This
  is the strongest standing argument for the metered API if the flat rate ever stops
  paying for itself.
- **Responsive UI:** the web layout is responsive and stacks to a single column
  below ~640px.
- **Time zone:** the heatmap uses the server's local "today"; set `TZ` on the
  container if deploying in a different zone from where you live.
- **Security:** the RESUME / PERSONAL PROFILE / JOB text is marked as *data, not
  instructions* in the score prompt (a posting can't inject directives); secrets
  live only in the gitignored `.env`, read by `run.py`. **Open defect (PROGRESS):** a
  Telegram send error can embed the bot token (carried in the request URL) into an
  exception string that is persisted to `job_postings.pipeline_error` and logged — so
  the token can escape `.env` into the shared DB / logs until that path scrubs it.

---

## 12. Setup and deployment

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

Full prerequisites and step-by-step (Telegram bot, Ollama, troubleshooting) were
historically in `docs/SETUP.md`; this section is now authoritative.

**Prerequisites:** Docker + Compose (≥ 24); Node 20+ and Python 3.11+ only for
local non-Docker dev/tests; Ollama + an NVIDIA GPU on the **host** for the
hard-requirements screen; an Anthropic API key for fit scoring; a
Telegram bot for alerts.

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
   (`source` ∈ the seven watchlist-capable boards {greenhouse, lever, ashby,
   workday, pinpoint, smartrecruiters, workable}, board `slug`, `name`),
   optional `title_filter`, the `candidate` hard-constraint block, `schedule_hours`
   (24). Workday's `slug` packs `tenant/datacenter/site` (quote it).
2. `cp apps/worker/resume/resume.txt.example …/resume.txt`, then replace with your
   real resume (plain text, fed to the fit scorer) — or provide multiple
   `resume_<label>.txt` versions plus an optional `personal_profile.txt` for
   about-the-candidate context (`apps/worker/resume/README.md`).
3. `cp apps/worker/.env.example apps/worker/.env` — fill `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `OLLAMA_HOST` (`http://host.docker.internal:11434` for
   Docker), plus `ANTHROPIC_API_KEY` **only** for `--score-backend claude`. Optional
   overrides: `OLLAMA_MODEL`, `SCORE_BACKEND`, `CODEX_SCORE_MODEL`,
   `ANTHROPIC_SCORE_MODEL`, `OLLAMA_NUM_CTX`.
4. The default `codex` fit backend authenticates from the operator's `codex login`
   state (`auth_mode=chatgpt`), not from `.env` — run `codex login` once on the
   worker host and confirm with `codex doctor` (auth ✓). A logged-out host fails
   every fit call loudly; it never scores 0.
4. On the host: `ollama pull qwen3.5:4b && ollama serve`.
5. From the repo root: `UID=$(id -u) GID=$(id -g) docker compose up --build`
   (or `make up`). The worker runs one pass immediately, then every
   `schedule_hours`.

**One-off test pass:**
`docker compose run --rm worker python -m ats_worker.run --once --config /app/config.yaml --env /app/.env`

**Volumes & env:** `./db` → `/data` (directory mount; `DATABASE_URL=
file:/data/applications.db`, worker `DB_PATH=/data/applications.db`). `make` targets
wrap all of this — see §[13](#13-testing-and-quality) and `make help`.

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
| `make eval-score` | verdict-accuracy gate for the fit-score prompt vs the golden set — PASS needs 0 hard-invariant violations, ≥85% per-dimension (`seniority`/`domain`) verdict agreement, <20% verdict flip-rate (**manual, not a CI gate**; default `codex` backend, flat-rate ChatGPT subscription, ~70 read-only calls, free; `SCORE_BACKEND=claude` A/Bs the paid metered path). **Two consecutive PASS 2026-07-17 (target-fit domain rubric): 100%, then 95% agreement; hard 10/10; 5% flip — ship-gate cleared.** Lone wobbler: id 26 (a borderline Aquatic Quant-Researcher seat that wavers match↔mismatch run-to-run — genuinely research-central, not a clean twin of the stable id 652). The golden set + operator profile are gitignored, so the gate is only reproducible with the operator's local files |
| `make db-push` | sync Prisma schema into SQLite |
| `make up` / `make down` | Docker Compose stack up/down |

- **Web:** Jest unit (`jest.config.ts`, Prisma mocked via `jest-mock-extended`) +
  integration (`jest.integration.config.ts`, real Prisma over a throwaway SQLite) +
  merged coverage (`jest.all.config.ts`). Playwright e2e (`e2e/`) runs against a
  seeded throwaway DB and is gated in CI.
- **Worker:** pytest, **fully dependency-injected** — no network / Ollama / Claude
  needed. `integration` marker runs `run_once` end-to-end over
  a temp SQLite. Coverage floor `fail_under = 85` (single source of truth in
  `pyproject.toml`, read by both `make test-coverage` and CI).
- **CI** (`.github/workflows/ci.yml`): runs both suites on push / PR / nightly, with
  coverage gates, the schema-drift guard, and a gated Playwright e2e job.
- **Schema-drift guard:** `tools/check_schema_drift.mjs` fails if
  `apps/worker/tests/fixtures/schema.sql` and `apps/web/prisma/schema.prisma` fall
  out of sync.
- **Batched==single drift guard (`tools/score_eval.py --batched`, no `make` target —
  invoked directly, e.g. `apps/worker/.venv/bin/python apps/worker/tools/score_eval.py
  --batched`):** a **separate, LIVE, quota-spending** check from the K=3 gate above —
  never run from CI/selftest. Scores the golden set once **single**
  (`fit([posting], resumes)`) and once **batched** (`fit(chunk, resumes)` at
  `BATCH_SIZE=10`), one draw per row per pass, and asserts the per-row `(seniority,
  domain)` verdicts are **identical** — PASS = 0 drift. This is the check that proves
  (or disproves) that batching N JDs into one `codex exec` call doesn't corrupt a JD's
  score via context bleed from its batch-mates, and it is the **acceptance gate** for
  trusting `batch_size>1` on a real re-score of the queue. **Run 2026-07-16
  (`gpt-5.6-sol`, `batch_size=10`, 23 golden rows) — FAILED, 19/23 agree** (see
  `PROGRESS.md`, `CHANGELOG.md`): all 4 drift rows are on the `domain` verdict, two of
  them (`adjacent`→`match`) appearing to cross the notify predicate. Per the design's
  rollout rule, batching **does not ship** — the shipped default is `batch_size=1`
  (§7.1, §9, §11), and the batching machinery + this guard stay in place for a future
  fix. The Part A verdict-routing change (§9) stands regardless. **Its verdict is
  confirmed but its reasoning was partly wrong — see the drift probe below;** the guard
  counts `marked` rows (fixed 2026-07-17: they still ride in their real batches, since
  their bleed can corrupt a gate-eligible batch-mate, but they no longer decide PASS),
  and one draw per row per pass cannot separate bleed from draw noise.
- **Drift probe (`tools/score_eval.py --drift-probe`, `CODEX_BATCH_SIZE` selects the
  setting):** a one-shot **experiment**, not a gate — it has no PASS/FAIL, it *measures*.
  Re-draws the 4 known drift rows **K=3×** at one batch size per run (`1` = single, probe
  rows only; `>1` = batched over the **whole** golden set, so probe rows keep their real
  batch-mates) and reports whether each verdict held. It exists because `--batched` draws
  each row once per pass and so cannot attribute drift to context **bleed** vs a JD whose
  verdict is a **coin-flip on any re-draw**. **Run 2026-07-17 (`gpt-5.6-sol`, K=3, b=1/5/10,
  36 calls) — bleed CONFIRMED, and it scales with batch size:** rows holding one verdict went
  **3/4 → 2/4 → 1/4** at b=1 → b=5 → b=10. Decisive rows: **id 111** stable-correct
  (`match/adjacent` ×3) alone but **stably *wrong*** (`match/match` ×3) at b=5; **id 184**
  stable in *both* modes at *different* values (`match/match` at b=1/b=5 vs `match/adjacent`
  at b=10) — which noise cannot explain; **id 132** seniority stable `too_junior` ×3 alone but
  bleeding to `match` at b=5/b=10, so **bleed is not confined to `domain`** as the guard
  concluded. **`batch_size=5` is not a safe middle ground** — it converts a correct stable
  verdict into a confident wrong one (worse than a flip, which at least announces itself).
  Batching stays parked at `batch_size=1` at **every** size >1; the quota problem needs a
  different lever (§11). Corrects two of the guard's claims: id 132 and 184 are `marked`
  watch-list rows (132's golden note already documents a 50/50 split), and **id 125 is not a
  batching victim** — it reads `match/match` on 3/3 *single* draws, so unbatched scoring
  notifies it too; it is a stable calibration disagreement with its `adjacent` label.

---

## 14. References

- **Status & open work:** [`PROGRESS.md`](./PROGRESS.md)
- **Release history:** [`../CHANGELOG.md`](../CHANGELOG.md)
- **Contributor conventions:** [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Design principles (decision DNA):** [`PRINCIPLES.md`](./PRINCIPLES.md)
- **Session protocol & definition of done:** [`DEVELOPMENT.md`](./DEVELOPMENT.md)
- **Service READMEs:** [`../apps/web`](../apps/web), [`../apps/worker/README.md`](../apps/worker/README.md)
- **Historical design note (superseded by this spec):** [`pipeline-design.md`](./pipeline-design.md)
- **Code anchors:** schema `apps/web/prisma/schema.prisma` · enums
  `apps/web/src/lib/constants.ts` · server actions `apps/web/src/lib/actions.ts` ·
  pipeline `apps/worker/ats_worker/pipeline.py` · wiring `apps/worker/ats_worker/run.py`
