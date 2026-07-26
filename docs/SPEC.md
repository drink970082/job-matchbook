# Job Matchbook — System Specification

> **Authoritative source of truth for this repository.** This document describes
> the system *as it actually exists* and is written to be verified against the
> code. When code and this spec disagree, that is a bug in one of them — fix it,
> don't let them drift. New work should update this file in the same change.
>
> Companion documents: [`PROGRESS.md`](./PROGRESS.md) (live status + open work),
> [`../CHANGELOG.md`](../CHANGELOG.md) (release history),
> [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (conventions).

- **Project:** Job Matchbook (`job-matchbook`) — a self-hosted, semi-automated
  job-application system
- **Repo:** https://github.com/drink970082/job-matchbook
- **Version:** 1.0.0 (first public release) · **Spec last updated:** 2026-07-22 · **License:** MIT

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

Job Matchbook is **one project made of two cooperating services that share a single
SQLite database**:

- **`apps/web`** — a Next.js 14 tracker + dashboards. You browse a queue of
  discovered jobs, triage them, and track every application through its status
  lifecycle with KPIs and charts.
- **`apps/worker`** — a scheduled Python pipeline that *feeds* the tracker: it
  scans company ATS boards, screens out hard-constraint mismatches with a local
  LLM, scores each posting's fit against your resume version(s) — by default via
  the Codex CLI (the operator's ChatGPT subscription), with Claude as a metered
  alternate — and pings you on Telegram for the best matches.

The two services never call each other. Their only contract is the **shared
database**. The worker discovers and prepares; the web app is where a human
triages, applies by hand, and tracks.

---

## 2. Problem and motivation

Job hunting generates a lot of state per application — company, role, date applied,
current status, interview rounds, where it stalled, category (a user-defined label
set — engineering, finance, product, … — see §8). A spreadsheet handles the first two
columns but falls over once you
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
- **Local-first compute where it's cheap, a frontier LLM where judgment matters.**
  The high-frequency hard-requirements screen runs on a local GPU (Ollama), not a
  paid API; fit scoring (every posting, needs real seniority/domain judgment) hits
  the Codex CLI by default (flat-rate ChatGPT subscription), or Claude as a
  metered alternate.

---

## 4. Goals and non-goals

*Class: **Contract** — code must satisfy these; disagreements are code bugs.*

**Goals**

- Track applications end-to-end with status history and visual analytics.
- Discover and pre-qualify jobs from company ATS boards on a schedule.
- Alert the human on Telegram for every high-scoring role, for manual application.
- Keep the two services safely co-writing one SQLite database.
- Stay runnable on a single host: `docker compose up` brings up the whole web
  stack, and the worker is one native command alongside it (§12).

**Non-goals**

- **No auto-apply / auto-submit.** A human always performs the application.
- **No multi-tenant SaaS, no user accounts, no public hosting.** Single-user, self-hosted.
- **No scraping of LinkedIn / Indeed.** Only company-owned boards — official ATS
  APIs where they exist, plus operator-curated `custom`/`browser` recipes against a
  company's own careers pages (aggregator anti-scraping + ToS risk avoided). The
  optional discovery feed reads a **public
  GitHub data file** (SimplifyJobs `listings.json`) — not a scraped UI — and still
  fetches every JD from the official board the listing's URL resolves to; aggregator
  *product* UIs (jobright.ai, simplify.jobs) remain out of scope.
- **No cloud dependency** beyond the external services the worker calls (the
  Codex CLI or Anthropic Claude for fit scoring, the host's Ollama, Telegram).
- **The worker issues no schema DDL** — Prisma owns the schema.

---

## 5. System overview

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

The two-phase workflow:

```
Phase 1 — Discovery & scoring (apps/worker, scheduled)
  watchlist (DB) ─► fetch (9 watchlist platform adapters + custom/browser recipes) ────┐
  feed (Simplify) ─► prefilter ─► resolve URL→board ─► fetch/fetch_one (reuse) ────────┤
                    (per-listing detail sources: Oracle/Jobvite)                       │
                    (unresolvable URL → feed_unresolved backlog)                       │
            (both paths upsert job_postings, deduped on source+id) ◄──┘
            ─► screen (local Ollama, hard requirements) ─gate─► score (codex|claude, reason-first)
                     [location: deterministic code gate off the board field, not the LLM]
                                          [disqualified → discarded, fit call skipped]
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

The watchlist path additionally runs deterministic, no-LLM filtering **at fetch**,
before either ingestion path ever reaches Ollama: `fetch.prefilter_postings` (the
`title_filter` keep-list + a `title_exclude` drop + a `max_age_days` freshness drop)
narrows what each company fetch returns, and the same intern/location gate the
screen stage uses (`score.deterministic_screen`) runs immediately after — a gate
miss is upserted straight to `discarded` (with its reason), skipping the Ollama call
entirely. The feed path is unaffected; its postings still gate at the screen stage
via `screen_posting`, which runs the identical `deterministic_screen` helper.

A posting moves through a `pipeline_status` state machine in the database
(§[9](#9-behaviors-and-invariants)). "Mark Applied" is the seam between the two
phases: it promotes a `job_postings` row into an `applications` row.

---

## 6. Architecture

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

```
            ATS boards          Ollama (host GPU)  Codex CLI/Claude   Telegram
      11 platforms + custom/          │                 │              ▲
        browser recipes               │                 │              │
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

Both writers rely on SQLite's `busy_timeout` to survive brief co-writes: the worker
sets it explicitly (`db.py:connect`, 5000 ms); the web Prisma client (`lib/db.ts`,
§7.2) sets none explicitly but Prisma 6's SQLite connector already defaults to the
same 5000 ms, verified by `db-pragma.int.test.ts` — no `connection_limit` tuning or
pragma call was required on the web side.

The `web` container runs as the host user (UID/GID build args) so bind-mount writes
work without `chmod 777`. The database is mounted as a **directory** (not a single
file) so SQLite's WAL `-wal`/`-shm` sidecars are visible to both processes — a
single-file mount silently breaks cross-container WAL. Ollama runs on the host
because GPU pass-through into a container under WSL2 is fiddly; the worker is native
and reaches it via `localhost:11434`.

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
| External | — | Codex CLI subprocess (default fit scorer), Anthropic SDK (Claude, alternate), Ollama HTTP, Telegram Bot API |
| Tests | Jest + Testing Library + jest-mock-extended; Playwright e2e | pytest (fully mocked) |
| Container | Alpine multi-stage, non-root | — (native on the host, not containerized) |

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
  `--model` (`OLLAMA_MODEL`, the Ollama model tag — only consulted when
  `--screen-backend ollama`),
  `--score-backend` (`SCORE_BACKEND`, `codex`|`claude`),
  `--screen-backend` (`SCREEN_BACKEND`, one of six values — documented under
  `score/` below), `--screen-model` (`SCREEN_MODEL`, overrides the chosen screen
  backend's default model; unset lets each backend fall back to its own default,
  and on `claude-code` that default is the CLI's own, not a value hard-coded here),
  `--codex-score-model` (`CODEX_SCORE_MODEL`, fit scoring on the codex backend),
  `--anthropic-score-model` (`ANTHROPIC_SCORE_MODEL`, fit scoring on the claude backend),
  `--fetch-only` (run fetch/feed/expire/retry then stop before any screen/scorer call —
  a quota-free board refresh), `--score-only` (skip the network ingest and score the
  existing `new` backlog — the inverse of `--fetch-only`), `--score-limit N` (cap `new`
  rows scored this pass, 0 = no cap — bounds the paid fit scorer on a large fresh intake),
  `--rescreen-discarded` (return every `discarded` row to `new` before this pass so it
  is re-screened under the current candidate hard requirements — **requires `--once`**,
  see §9),
  `--no-notify` (score but send no Telegram alerts — for a bulk/unattended pass;
  nothing is consumed, rows stay `scored` and alert on a later pass without the flag),
  `--import-companies` (seed the DB watchlist from config and exit). Defaults:
  screen `ollama` / `qwen3.5:4b`; fit score `codex` / `gpt-5.6-sol`. Each pass
  **auto-seeds** `watched_companies` from `config.companies` when the table is empty,
  reads the watchlist from the DB (not config), runs `run_fetch` over it, then runs
  `run_feed` for each enabled feed. The only module that knows about
  secrets/external services — and the only place the real network callables are
  bound: `pipeline.run_fetch`/`run_feed`'s `fetch_fn`/`detail_fetch_fn` and
  `score.screen_posting`'s `http` all default to `None` in their pure modules
  (the fetch/screen seams never bind a real network callable as a default —
  `notify.py`'s `http=requests` default is the one deliberate exception), and
  `run.py` supplies `fetch_company`, `fetch_one_company`, and the screen's
  `http=requests` explicitly at each call site.
- **`config.py` — load/validate `config.yaml`.** Validates `source ∈ VALID_SOURCES`
  (the watchlist-capable boards: {greenhouse, lever, ashby, workday, pinpoint,
  smartrecruiters, workable, icims, phenom, custom, browser} — feed-only sources oracle/jobvite
  are intentionally excluded); a `RECIPE_SOURCES` row (`custom`, `browser`) must carry a `recipe`
  mapping (else a startup `ConfigError`). Each company's `slug` is checked by `_valid_slug`
  against the same charset rule as the web boundary — `[A-Za-z0-9._/-]`, no `..`, no
  leading/trailing/doubled `/` — since the worker interpolates it straight into a fetch
  URL host/path (`ConfigError` on a bad slug). Exposes `companies` (each with an optional
  `recipe: dict | None`), `enable_browser_sources` (opt-in gate for `browser` rows, default off),
  `title_filter`, `title_exclude` (negative title list — drop a posting whose title
  contains any listed keyword, the complement of `title_filter`), `max_age_days`
  (fetch-time freshness gate — drop a posting whose `posted_at` is older than N days;
  `0`/omitted = off; a null/unparseable `posted_at` is always kept), `candidate` (with
  `is_empty()`), `feeds`, `schedule_hours` (daemon pass interval in hours; must be
  `>= 1` — a `0`/negative value would make APScheduler's interval trigger hot-loop the
  watchlist at a 1-second period, so `config.py` raises `ConfigError`). Bad
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
  - `prefilter_postings(postings, *, title_filter, title_exclude, max_age_days, now)`
    — the fetch-time coarse pre-filter the watchlist path runs (deterministic, no
    LLM): the positive `title_filter` keep-list above, a negative `title_exclude`
    drop (title contains any listed keyword), and a `max_age_days` freshness drop (a
    parsed `posted_at` older than N days is dropped; `0`/omitted `max_age_days` and a
    null/unparseable `posted_at` both keep the posting — err toward keep).

  **Source coverage matrix** (the at-a-glance support map — keep it current when a
  source is added). *Adapter* = can fetch a JD; *feed router* = `resolve_url` maps the
  host; *watchlist* = enumerable per-board source (in `VALID_SOURCES`). These
  capabilities come apart — e.g. Pinpoint has an adapter + watchlist but no feed router.
  **Only two of the five columns are tested.** `test_spec_matrix_matches_adapters` reads
  the **Platform** column's first word as the source name and checks the set against
  `ADAPTERS`, and checks **Watchlist** `yes` against `VALID_SOURCES`; it skips a row
  whose *Adapter* cell begins `via ` (routed through another module). *Adapter*,
  *Host(s)* and *Feed router* are **hand-maintained and unguarded** — `resolve_url` is a
  URL-pattern parser rather than a registry, and the adapter cell's prose has no single
  source of truth to compare against, so a wrong value in those three columns will not
  fail CI:

  | Platform | Host(s) | Adapter | Feed router | Watchlist |
  |---|---|---|---|---|
  | Greenhouse | `boards.greenhouse.io`, `job-boards.greenhouse.io`, `job-boards.eu.greenhouse.io` | list | yes | yes |
  | Lever | `jobs.lever.co` | list | yes | yes |
  | Ashby | `jobs.ashbyhq.com` | list | yes | yes |
  | Workday | `*.myworkdayjobs.com` | list (watchlist) + per-job (feed) | yes (per-job by externalPath) | yes |
  | SmartRecruiters | `jobs.smartrecruiters.com` | list (watchlist) + per-job (feed) | yes (per-job by id) | yes |
  | Pinpoint | `{slug}.pinpointhq.com` | list | no | yes |
  | Workable | `apply.workable.com` | list | yes | yes |
  | iCIMS | `{slug}.icims.com` | list (server HTML) | no | yes |
  | Phenom | `{host}` (e.g. `apply.careers.microsoft.com`) | list + per-job detail | no | yes |
  | Custom (recipe) | any (recipe-driven) | list (`json`/`next-data`) | no | yes (needs `recipe`) |
  | Browser (recipe) | any (Cloudflare-blocked / JS-only) | list (headless Chromium + CSS) | no | yes (needs `recipe`; opt-in) |
  | Oracle Cloud HCM | `*.oraclecloud.com` | detail (`fetch_one`) | yes | no (feed-only) |
  | Jobvite | `jobs.jobvite.com` | detail (JSON-LD) | yes | no (feed-only) |
  | Embedded Greenhouse | custom domains `?gh_jid=` | via greenhouse | yes, enriching (I/O token scrape) | no (feed-only) |

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
  `phenom` is also the one adapter with **429 handling** — it is the only board that has
  ever rate-limited (`careers.qualcomm.com` at `start=930`, 2026-07-22). Its search GET
  retries the same offset up to 3 times (2s → 4s → 8s, honoring a delta-seconds
  `Retry-After` clamped to 30s); still throttled at `start > 0` it returns an empty page,
  which the paginator reads as the end of the board, so **the pages already walked are
  kept** instead of the whole board being lost. At `start == 0` it raises, because a
  silent empty result would report a throttled board as an empty one. The other
  paginating adapters are deliberately bare (see PROGRESS).
  `phenom` also accepts an optional `keep` stub-gate from `run_fetch`: the search
  stub carries the title and location — everything the deterministic gates read — so
  a posting rejected on either skips its per-position detail GET (measured
  2026-07-21: 1,580 -> ~458 detail calls on the Microsoft board). A stub-gated
  discard is still recorded, with an EMPTY description; because `upsert_postings` is
  `ON CONFLICT DO NOTHING`, that row is never back-filled later.
  `workday` shares the N+1 shape and is gated too, but honours **only** the `drop`
  verdict (`parse_stub` builds the title/location stub the gate reads). Its list stub
  carries no GUID — `parse_job` takes `external_id` from the *detail* payload — so a
  *stored* stub would key on `jobReqId` and a later hydration would insert a second
  row under the GUID. A dropped posting is never stored, so it has no id to reconcile;
  every other verdict falls through and hydrates, which is also the fail-open path.
  Measured 2026-07-22 across 28 watchlist boards: 14,902 -> 6,703 detail calls (-55%).
  `max_age_days` cannot gate a workday stub — its only date is prose ("Posted 30+ Days
  Ago"), so `parse_stub` sets `posted_at: None`, which the age filter treats as keep.
  (See `docs/superpowers/specs/2026-07-21-stub-gate-design.md`.)
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
  rendered DOM (`item` + `fields`, `url`-template pagination, optional per-role `detail` enrich).
  As on the `custom` path, a `fields.url` spec containing `{` is a **template** rather than a
  selector, interpolated over the recipe's own other `fields` (which may include url-only helper
  fields) — this is how a board whose cards carry no `href` (id in a `data-*` attribute, routing
  JS-side) still yields a real `job_url`; an undefined name substitutes empty, and the result
  passes the same `is_safe_public_url` guard as a scraped href. A
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
  are fixture-tested, as are `fetch`'s SSRF guards on the scraped detail + pagination URLs (via a
  fake `sync_playwright`, no Chromium); only the live browser I/O itself is not (like other adapters').
  **Dual-mode (Workday, SmartRecruiters):** the *watchlist* lists the whole board
  (`fetch`), but the *feed* routes them through `fetch_one` so it pulls ONLY the
  surfaced jobs — listing a 1500-job board (N+1 detail-per-job) just to keep the 1-2
  the feed wants was the dominant feed cost (≈11 min for one big board). Workday's
  feed id is the job's externalPath (CXS per-job endpoint); SmartRecruiters' is the
  posting id. With this + concurrent fetching (below), a full feed pass dropped from
  ~tens of minutes to ~1 minute.
  *Backlog (in `feed_unresolved`, not feed-routed):* iCIMS + ByteDance/TikTok — list
  ingestion ships (iCIMS as a list adapter, TikTok as a `custom` recipe) but closing
  the feed tail still needs a `resolve_url` host router + a per-listing `fetch_one`,
  which the list adapters don't provide. Dropped: greenhouse embed-token (job id
  only, no recoverable board slug). See [`PROGRESS.md`](./PROGRESS.md).
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
    on the unresolved board. **SSRF guard:** `resolve_embedded` fetches via
    `util.get_redirect_safe`, which re-validates `util.is_safe_public_url` on the initial
    URL **and every redirect hop** before issuing it — only public `http(s)` hosts are
    contacted; `localhost` and private/loopback/link-local/reserved IP literals (incl.
    `169.254.169.254`) are refused with no HTTP call, and a public URL that 3xx-redirects
    to an internal target is refused mid-chain (→ unresolvable/`None`). Same
    `get_redirect_safe` guards the `custom` recipe fetch; the `browser` executor validates
    each navigation URL and discards a render whose post-redirect `page.url` is non-public.
- **`db.py` — SQLite layer.** WAL pragmas + `busy_timeout`; `upsert_postings`
  (dedup on `(source, external_id)`; persists `company_slug`), `get_by_status`
  (selects rows by pipeline status), `get_notifiable` (the notify gate: `scored`
  rows whose `score_detail` verdicts read `seniority=match AND domain=match AND
  NOT insufficient_context`, via `json_extract`, **and** whose trimmed
  `description` is ≥ 200 chars — the same low-context hold-back the web Matched
  tab applies, §9), `save_score` (also clears
  `pipeline_error`, so a row recovering via a retry requeue drops its stale
  error), `mark_notified` (clears `pipeline_error`), `mark_failed` (terminal —
  aside from `requeue_failed`, below), `record_notify_failure` (retry-aware:
  keeps the row `scored` until the caller declares the budget exhausted, then
  parks it `failed`), `requeue_failed(conn, now, max_attempts,
  max_notify_attempts)` (bulk `UPDATE ... SET pipeline_status='new' WHERE
  pipeline_status='failed' AND attempts < max_attempts AND notify_attempts <
  max_notify_attempts`, returns rows requeued — both caps passed in by the caller
  (`pipeline.RETRY_MAX_ATTEMPTS` / `NOTIFY_MAX_ATTEMPTS`), so this module stays
  policy-free like every other mutator here; guarding both keeps a notify-exhausted
  row terminal even though its score `attempts` may be 0). Watchlist + feed
  helpers: `get_watchlist` (skips a `custom`/`browser` row with malformed recipe JSON,
  but keeps a platform-source row — it fetches without a recipe), `count_watchlist`,
  `import_watchlist` (idempotent), `record_unresolved` (upsert on `url`),
  `delete_unresolved` (clears a row once its posting is re-ingested),
  `existing_external_ids`. Issues no DDL.
- **`score/` — screening + fit scoring.** A package — `screen.py`, `location.py`,
  `prompts.py`, `usage.py`, `backends_screen.py` (SCREEN backends),
  `backends_codex.py`/`backends_claude.py` (fit-SCORE backends) — re-exported
  through `score/__init__.py`, so `score.screen_posting` / `score._normalize_score`
  still resolve. Up to two calls, **SCREEN-gated**: the cheap hard-requirements
  screen runs FIRST and gates the paid fit score.

  (1) The hard-requirements **SCREEN** is injected as one seam — `extract(prompt,
  schema) -> dict` (`screen_posting`'s `extract` kwarg) — so swapping backends is a
  new callable, never a new branch inside `screen_posting`. `run.make_screener(backend,
  *, env, http=None, model=None, screen_model=None, num_ctx=8192)` builds that
  callable from **`SCREEN_BACKEND`/`--screen-backend`**, one of **six** values in
  **three** adapter shapes (`score/backends_screen.py`):
  - **HTTP + JSON schema** — `ollama` (**default**; free, local,
    `score.screen.make_ollama_extract`, `think: false`, `num_ctx` from
    `OLLAMA_NUM_CTX`/`--model`, default model `qwen3.5:4b`), `claude-api` (metered,
    the Anthropic SDK's structured outputs, default `claude-haiku-4-5`, needs
    `ANTHROPIC_API_KEY`), `openai-api` (metered, plain `requests` against
    `chat/completions` with `response_format: json_schema`, default `gpt-5.6-luna`,
    needs `OPENAI_API_KEY`).
  - **CLI subprocess + schema** — `codex` (the operator's ChatGPT-subscription CLI,
    default `gpt-5.6-sol`; runs **tool-less** — `--disable shell_tool`,
    `web_search="disabled"` — the same security posture as the fit backend below,
    since a JD is untrusted scraped text; the schema goes in as a **file**,
    `--output-schema`), `claude-code` (the operator's Claude Code CLI subscription;
    **no** hard-coded default model, so an unset `--screen-model` takes whatever the
    CLI itself defaults to; the schema goes in **inline** as JSON text —
    `--json-schema <json>`, **not** a file path, despite the flag name — verified
    behaviorally against the CLI 2026-07-23, so it is **not** symmetric with codex's
    `--output-schema`).
  - **Deterministic-only** — `none`: no LLM call at all, `make_screener` returns
    `None` and `screen_posting` runs only the code-side location + intern gates.
    **LOW RECALL on sponsorship** — with no per-JD extraction to ground it, the
    work-authorization check falls all the way back to the closed
    `NO_SPONSOR_PHRASES` substring list (~2/11 recall — see below).

  `--screen-model`/`SCREEN_MODEL` overrides whichever backend's default model.
  **Auto-detection never selects a paid backend** — the default is always `ollama`
  and `make_screener` never guesses from what happens to be installed; spending
  money is explicit opt-in via `SCREEN_BACKEND` (`make doctor` reports what is
  actually available, and the operator — or `onboard-me` Step 0 — chooses from
  that). `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` are read from the in-process `env`
  dict only, same as the fit backend, never promoted to an argparse default (§12).

  Whichever backend is picked, the call only fires when a non-empty `candidate` is
  supplied, and — with **no résumé in the prompt** — extracts each requirement
  (degree, work authorization, clearance) as a JOB fact *semantically*.
  CODE then decides pass/fail — on every backend, not just the free 4B `ollama`
  default that motivated it (a small local model is unreliable at the pass/fail
  judgment itself, and keeping it code-side means the check behaves the same
  regardless of which backend did the extracting): for degree/clearance by applying
  the candidate's configured constraint to the extracted fact; for **work
  authorization by a quote-grounded LLM check** (`_check_authorization` / `_quote_in`)
  — the model returns `no_sponsorship_quote`, the verbatim JD sentence it claims
  states sponsorship is unavailable, and CODE verifies that sentence is actually
  present in the description (`_quote_in`, whitespace-collapsed + case-insensitive)
  *before* disqualifying — a hallucinated quote fails verification and the posting is
  *kept*, so a hallucination cannot disqualify anything by construction, not by trust.
  A verified quote must **also be on topic** (`_quote_on_topic`): it has to touch
  `AUTHORIZATION_TERMS` (sponsor · visa · immigration · authoriz/authoris · citizen ·
  right to work · work permit · green card). Presence proves a sentence is real, not
  that it is *about* sponsorship — the 2026-07-25 labeled set caught the model quoting
  agency boilerplate ("we do not require any assistance from third-parties including
  agencies in the recruitment of this role") on 5 of 28 fires, wrongly disqualifying
  those postings. Both gates guard the same direction: a false positive here discards a
  good posting silently, the error "err toward keep" exists to prevent.
  This is the **D1** fix: the model's earlier `offers_sponsorship` guess had invented
  "no" from silence, so the check no longer trusts a bare verdict — it trusts only a
  verdict it can find verbatim in the JD. `NO_SPONSOR_PHRASES` — the prior gate — is
  demoted to a **floor** underneath the quote check: it still runs and can only *add*
  a disqualification, never veto a model pass, so it still catches blunt closed-list
  phrasings even on `SCREEN_BACKEND=none` (no LLM call at all). **Precision/recall —
  measured 2026-07-25** on 3,553 already-scored rows via `tools/sponsor_diff.py`, which
  diffs the check against the old phrase list so only the 21 disagreements needed
  hand-labeling against the three-class truth (*no-sponsorship / offers / silent*);
  agreements are free labels. Against 20 known true positives (the union of both
  systems — so recall is relative to that union, **not** to truth):

  **Measure the whole function, not one branch of it.** `_check_authorization`
  disqualifies on `(quote grounded AND on topic) OR NO_SPONSOR_PHRASES`, so a number
  quoted for the quote branch alone flatters it — the ungated floor adds fires nobody
  counted:

  | | fires | correct | precision | recall |
  |---|---|---|---|---|
  | `NO_SPONSOR_PHRASES` alone (the retired gate) | 11 | 9 | 81.8% | 45.0% |
  | quote branch, presence check only | 28 | 20 | 71.4% | 100% |
  | quote branch **+ `_quote_on_topic`** | 20 | 20 | 100% | 100% |
  | **shipped `_check_authorization` (gate OR floor)** | 22 | 20 | **90.9%** | **100%** |

  The relevance gate removes 8 false positives — 5 agency boilerplate, 3 soft-preference
  — and **zero** true positives. `_quote_on_topic` is three vetoes then a vocabulary, all
  resolving toward keep: an off-topic sentence carrying an authorization word (the D1
  pair: "company-sponsored sports teams", "we do not discriminate on citizenship"), a
  sentence of the wrong **polarity** ("Visa sponsorship is available for this position."
  — quote grounding fixes invented text, never inverted meaning), and a soft preference
  ("prioritizing applicants who…"), which is not a bar because the candidate can still
  apply.

  **The 2 residual false positives are the ungated floor**, not the gate: IMC ids 465/490,
  where `without sponsorship` appears inside an *invitation* ("or are eligible to work
  without sponsorship, we encourage you to apply"). Open, not accepted — the floor matches
  a substring anywhere in the description with no sentence and no relevance check, which
  is the blunt-instrument tradeoff it was demoted for. Unmeasured, deliberately: false
  negatives among the 3,523 agreed-negative rows, which neither system flagged and nobody
  read; recall is relative to the 20-row union of the two systems, **not** to truth.
  `candidate.work_authorization` is a **closed vocabulary** validated at config load
  (`citizen` | `permanent resident` | `authorized-no-sponsorship` | `needs visa
  sponsorship`, case-insensitive; blank = don't screen on it). It has to be closed
  because `_needs_sponsorship` reads the value by substring — an off-vocabulary string
  like `F-1 OPT` would read as "needs no sponsorship" and silently disable the whole
  authorization check, so `config.py` raises `ConfigError` instead.
  `disqualified` is derived from those per-requirement verdicts, and a check the model
  returned **no data** for records no verdict at all rather than a pass — `degree` and
  `clearance` only materialize their key when the extraction carried an entry, so a
  ran-but-blind check stays distinguishable from a genuinely cleared one.
  (`authorization` always records, since `NO_SPONSOR_PHRASES` gives it a real verdict
  with no model data.) **Location is a deterministic code gate**
  (`resolve_location`) matched against the board's `posting["location"]`
  string — not the LLM. It resolves **every** token to a country — US state / country
  name via `pycountry`, else a city via **geonamescache** (highest-population match,
  so a tiny US namesake like Paris TX can't mask Paris FR) — and errs toward keep:
  keep if any token is US or an allowed country, discard only when the foreign reading
  is **corroborated** — every token resolved, or at least two did — and none are
  allowed (naming the first foreign country), keep if nothing resolves (**D2**). The
  corroboration requirement exists because only **US** subdivisions are in the
  gazetteer: without it, `London, ON` dropped its unresolved `ON` and was judged by
  `London` alone as United Kingdom, discarding a Canadian posting under a reason that
  named the wrong country. It costs misses only (`Hyderabad, TS` keeps = one fit call),
  never a live match. US-state and remote strings keep, so a
  `locations`-only candidate makes no SCREEN call (any backend). The screen prompt
  carries no location clause. The scoring prompts live in **two** files —
  `prompts/score.txt` (fit rubric) and `prompts/screen.txt` (the SCREEN
  hard-requirements checklist, shared by every backend). Separately, when
  `candidate.exclude_internships` is set,
  intern/co-op roles are disqualified by a whole-word match on the job title (no LLM
  call — runs even when no other screen clause is configured). A SCREEN **provider**
  failure errs toward keep (not disqualified) and stamps `provider_error` on the
  verdict; `run_score` then leaves that row `new` rather than fit-scoring it unscreened,
  and a run of them circuit-breaks the screen phase (§9). (2) The fit **SCORE** —
  reached **only when the screen did not disqualify** (a discarded posting records `score` 0 and never pays
  for a fit call) — comes from an injected **`score_fit(postings, resumes) -> list[dict]`**
  callable: **batch-first, list in / list out**, one scorecard per input posting in the
  same order. `run_score` itself calls it directly with each chunk's full batch of
  postings (`fit_fn(postings)`, chunked by `batch_size`); `pipeline._persist_scored`
  then normalizes every result in the returned list (`score._normalize_score(card)`) —
  the batching happens at the `run_score` orchestration layer (§7.1/§9), not inside a
  per-posting call. Two interchangeable twins
  build it, picked by `run.make_scorer` (`--score-backend`/`SCORE_BACKEND`); both send
  the **same prompt sections** (`_scorer_system_sections`) and the **same per-element
  JSON schema** (`_score_schema`), so a score is comparable across them and a prompt
  edit lands on both:
  - **`codex` (default)** — `make_codex_scorer`, the Codex CLI on the operator's
    **ChatGPT subscription** (flat-rate, not metered), and the **only backend with
    batching machinery**: one `codex exec` per call can handle up to `batch_size`
    postings at once (`--batch-size`/`CODEX_BATCH_SIZE`), because the subscription's
    quota is MESSAGE-bound, not token-bound — fewer `codex exec` calls would be the
    saving. **Parked at `DEFAULT_BATCH_SIZE=1` (`run.py`):** the batched==single
    verdict-drift guard failed on cross-JD bleed (full post-mortem in §13); opt back
    in via `--batch-size`/`CODEX_BATCH_SIZE` only once that guard passes.
    Each JD gets its own `=== JOB job_ref=<posting id> ===` block in one prompt; the
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
    default — chosen on the golden set, the only measurement that counts
    (`gpt-5.6-terra` won a synthetic probe but lost on real JDs, gate agreement 76%
    vs 86%; `gpt-5.6-luna` rejected outright, ~3× looser spread).
    **Tool-less by construction** (`--disable shell_tool`, `web_search="disabled"`) — a
    security boundary, since a JD is untrusted scraped text and `codex exec` is natively
    an agent with a shell that `--sandbox read-only` still lets read any file; also worth
    ~3.1k input tokens/call.
    **Pinned `model_reasoning_effort=low` + `model_verbosity=low`.** Effort buys nothing
    on this task shape (reasoning tokens were non-monotonic across levels) but **must** be
    pinned anyway: the default is server-controlled and was seen flipping `low`→`medium`
    →`low`. Verbosity is a no-op under `--output-schema`.
    **No determinism:** codex exposes no `seed`/`temperature`, so score noise can't
    be turned off — but routing turns on the verdicts, not the noisy number (§9),
    and `make eval-score` gates verdict accuracy. If that gate ever fails, the
    escape hatch is majority-of-K draws or A/B-ing `--score-backend claude`; the
    residual ±10–15 score noise affects only display/ranking, never routing.
    **Quota-usage capture (free):** when `run.py` passes a `usage_path` (production
    `run_once` only, not the eval harness), the scorer snapshots codex's own `/status`
    accounting (`used_percent`, `window_minutes`, `resets_at`, `plan_type`) to
    `codex_usage.json` in the shared db dir, piggybacking the scoring message — no
    probe call. The figures live only in the **session rollout** (`--json` stdout
    carries no `rate_limits`; verified 0.144.5), which `--ephemeral` suppresses — so
    when capturing, the scorer drops `--ephemeral`, reads the newest rollout past a
    pre-call mtime mark, then deletes it **only when it's the sole rollout newer than
    the mark** (`_rollouts_after`): zero or 2+ newer means a concurrent codex session
    landed in the window, and the guard leaves them all rather than risk nuking that
    session's history. The capture sits in a `finally` around the exec call, so the
    résumé-bearing rollout is reaped even when the call raises — a failed call never
    leaks the prompt to disk. Best-effort (a parse failure never breaks a score); the
    observed `primary` limit is the **weekly** window (`window_minutes=10080`), and
    whatever non-null limits codex reports are kept, so a 5h secondary would render
    too. Shown by the web usage bar (§7.2); a live "now" reading is out of scope (it
    would cost a quota message).
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
  verdict is a target-fit rule** (redesigned 2026-07-17): the model records **three checks** in
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
  the screen gate's decision; the same role posted per city scores identically).
  `pipeline._persist_scored` normalizes/clamps the result and validates the
  scorecard via `score._normalize_score` (`ScoreError` on a missing score or an
  out-of-enum verdict — the row is marked `failed` via `db.mark_failed` rather than
  aborting the batch); the modal renders
  the scorecard with a legacy matched/missing/reasoning fallback for pre-S2.1 rows.
  **There is no local experience/years gate** — seniority is judged by the Claude
  scorecard's verdict + floor, not a deterministic code check.
- **`notify.py` — `notify_posting`.** Telegram `sendMessage` (company / title /
  score / JD link, plus an optional `Resume: <label>` line when `score_detail`
  carries `recommended_resume`) — a single atomic message per match; the human
  applies by hand. **Telegram is optional:** if `TELEGRAM_BOT_TOKEN` /
  `TELEGRAM_CHAT_ID` are absent from `.env`, `run_once` skips `run_notify` and matched
  rows stay `scored` — still visible in the web Discovered Jobs Matched bucket
  (`pipeline_status IN ('scored','notified')`), just with no push alert.
- **`pipeline.py` — orchestration.** Stateless stage functions over a db
  connection with injected worker callables and an explicit `now`:
  `run_fetch` → (`run_feed`) → `run_expire` → `run_retry` → `run_score` →
  `run_notify`. Every stage
  wraps each item in try/except: one bad posting/company is recorded
  (`db.mark_failed`; at the notify stage `db.record_notify_failure`, which retries —
  §9) or skipped, and the batch continues. `run_fetch` runs the watchlist path: fetch
  each company, apply `fetch.prefilter_postings` (title keep/exclude + max-age), then
  — when a `candidate` is configured — run the **same** deterministic intern/location
  gate as the post-LLM screen (`score.deterministic_screen`, shared code, not a
  reimplementation) against each surviving posting *before* it is ever upserted. A
  gate miss is tagged `pipeline_status="discarded"` with a screen-shaped
  `score_detail` right there at fetch time — visible in the Discovered "Discarded"
  bucket with its reason — **without** an Ollama call; a company that raises is
  logged-and-skipped so the rest of the watchlist still ingests. Finally, a surviving
  posting with **no description is dropped, logged, and recorded in `feed_unresolved`**
  (`feed="watchlist"`, `reason="empty_description"`) — `_valid_posting`, the same
  body-required guard the feed path applies: a bodyless row is permanent
  (`upsert_postings` is `ON CONFLICT DO NOTHING`, so a later cycle never back-fills it)
  and would reach the paid fit scorer blind, so a board whose list endpoint carries no
  JD simply yields nothing that cycle — while the `feed_unresolved` record surfaces the
  silently-broken scraper on the Unresolved board (dropping, not storing as `discarded`,
  keeps the id re-fetchable so the board self-heals if a later cycle returns the body).
  Rows already tagged `discarded` are exempt —
  the stub gate returns those deliberately un-hydrated and they never reach the scorer. `screen_posting`
  still runs `deterministic_screen` again post-LLM (preserving any degree/auth/
  clearance disqualification the SCREEN call found), so the feed path — which never
  goes through `run_fetch` — gates identically, just one stage later.
  `run_feed` (optional) runs
  the feed: prefilter → resolve → record-unresolved, then groups survivors by
  `(source, slug)`, skips ids already ingested (`existing_external_ids`), and ingests
  the surfaced postings via one of two paths: **per-board** sources fetch the whole
  board via the existing adapter and keep **only** the surfaced ids (exact
  `external_id` membership) — a **raising** list fetch is a real failure, not a
  genuinely-empty board, so every surfaced id for that group is recorded rather than
  silently dropped; **detail sources** (`fetch.DETAIL_SOURCES` — oracle,
  jobvite, plus the per-job feed routes for smartrecruiters/workday) fetch each
  surfaced id directly via `fetch_one_company` (per-id try/except, so one bad listing
  is skipped). The network work runs **concurrently** (a `ThreadPoolExecutor`; the
  embedded-greenhouse I/O resolves and the per-group fetches each fan out) while every
  DB read/write stays on the main thread — SQLite connections aren't safe across
  threads. `run.py` hands each worker thread its own `requests.Session` (keep-alive)
  and a shorter timeout. A fetched posting is **validated** (`_valid_posting`:
  non-empty `external_id` + `job_title` + `description`) before it counts — an empty JD
  means a scrape silently lost the body, the main way an HTML/JS scraper breaks without
  raising. Any failed id (board raise / detail raise / `None` / invalid) is recorded in
  `feed_unresolved` — `reason="list_fetch_failed"` for a per-board source's raising list
  fetch, `reason="detail_fetch_failed"` for a detail source's per-id failure (host from
  the listing URL) — so a broken scraper or a down board surfaces on the unresolved
  board instead of vanishing; a detail source that resolves ids but
  keeps **none** also prints a one-line collapse warning. Each kept posting is stamped
  with its `company_slug`.
  `run_score` is **screen-all-then-batch-fit-survivors**, not one per-posting loop:
  (1) every `new` row is screened (Ollama, per-item — one bad screen call marks only
  that row `failed`), and a disqualified one is persisted `discarded` right here,
  **never** reaching the fit call; a screen survivor whose trimmed `description` is
  shorter than `db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH` (200, the shared low-context
  threshold) is persisted `scored` + `insufficient_context` right here too — the
  UI/notify gate hold back any scored row that thin, so a paid fit call would only buy
  a verdict that is then hidden, and it is skipped; the row still shows under
  Low-context for a human to eyeball; (2) the (substantial) survivors are chunked into
  batches of `batch_size` (**default 1 — batching parked**, see below) and each chunk
  is **one** `fit_fn` call; (3) a chunk whose call raises — `ScoreError` or any other
  exception — falls back to scoring that chunk's postings **singly**, so one malformed
  batch costs latency, not correctness, and a single that still fails marks only that
  row `failed`. `batch_size` is harmless on the `claude` backend (which loops
  internally regardless) and is the parked codex quota lever — default 1 until the
  batched==single guard passes (§13). An optional `limit` caps how many `new` rows a
  pass touches (the `--score-limit` operator flag), bounding the paid scorer over a
  large fresh intake; the remainder stays `new`. Both the screen phase and the
  per-chunk fit calls run **concurrently** — the same read-serial / network-parallel /
  write-serial shape `run_feed` uses above: a `ThreadPoolExecutor` fans out
  `screen_fn`/`fit_fn` (each I/O-bound — an HTTP round trip or a subprocess spawn),
  while every DB read/write stays on the calling thread, and futures are consumed in
  **submission order** so a screen verdict or fit card is never mis-associated with
  the wrong posting and writes stay deterministic. `--screen-workers`/
  `--score-workers` (`SCREEN_WORKERS`/`SCORE_WORKERS`) bound each pool; the screen
  pool defaults **per backend** (`run.DEFAULT_SCREEN_WORKERS`) — **1** for
  `ollama`/`none` (a single GPU serializes the compute, so parallel requests
  interleave rather than speed up the underlying inference), **4** for the
  subprocess/hosted backends, which are latency- not compute-bound. The singles
  fallback in (3) stays serial. Fit concurrency is quota-neutral (§11).
  `run_expire` is the dead-link sweep: it re-fetches up to `EXPIRE_BATCH` (50) live
  (`scored`/`notified`) postings from **detail sources only** — the ones with a real
  per-job endpoint (`fetch.DETAIL_SOURCES`), so the check costs one honest request
  with a real HTTP status and board sources are untouched — least-recently-updated
  first. A **404/410** marks the row `pipeline_status='expired'` (terminal; it drops
  out of the live Discovered buckets like `removed`). **Every other outcome leaves
  the row alone** — a timeout, a 403 bot wall, a 5xx, or a `None` from the adapter is
  treated as alive, because wrongly expiring a live match costs the operator a job
  while a missed dead link costs one stale row. A successful check rewrites
  `updated_at`, which rotates the row to the back of the queue — that's the whole
  scheduling mechanism, no extra column.
  `run_retry` requeues every `failed` row with `attempts < RETRY_MAX_ATTEMPTS` (3)
  **and** `notify_attempts < NOTIFY_MAX_ATTEMPTS` (3) back to `new` — one bulk
  `db.requeue_failed` UPDATE, run **after** the fetch/feed ingest and **before**
  `run_score` so a requeued row is rescored in the same pass. The retry semantics —
  the separate score/notify budgets, the 3-failure ceiling each, `discarded`-on-retry
  being legitimate — are contract; see §9 "Failure handling and recovery limits".
  `db.requeue_discarded(conn, now)` is the operator-only counterpart for the other
  terminal state: `--rescreen-discarded` returns every **hydrated** `discarded` row to
  `new` immediately before `run_retry`, so a candidate hard-requirement edit doesn't
  leave postings frozen under the old rule. Unbudgeted (a discard spends no `attempts`);
  filtered on one thing only — a row with an empty `description` is a stub-gate discard
  and is left alone, because requeueing it destroys it irreversibly (§9). `main` rejects
  the flag without `--once` (§9).
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
    (category chosen at apply time from the user-configured vocabulary — free-form,
    default `Others` when blank), `getCategories`/`setCategories` (the user-editable
    category list, stored in `app_settings`).
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
    parser; validates status against `STATUSES`; keeps category free-form; dedups).
- **`lib/db.ts`** — process-singleton Prisma client (avoids dev hot-reload
  connection leaks). No explicit `busy_timeout` pragma or `connection_limit` is set —
  verified (`db-pragma.int.test.ts`) that Prisma 6's SQLite connector already defaults
  `busy_timeout` to 5000 ms, matching the worker's `db.py` setting (§7.1), so a
  worker write-lock already makes web block-and-retry instead of throwing
  `SQLITE_BUSY`; no code change was needed.
- **`lib/constants.ts`** — `STATUSES` (14), `DEFAULT_CATEGORIES` (9 — the *seed* for the
  user-editable category vocabulary, which is stored per-install in `app_settings` and
  managed in the UI, no longer a fixed enum),
  `VALID_SOURCES` (11 watchlist-capable boards, mirrors the worker; feed-only sources
  are not listed), `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`
  (200; the trimmed-`description` char count below which a scored posting is bucketed
  Low-context — the single tuning knob for that heuristic), `getStatusColor`. **Edit here
  to extend statuses/sources (categories are edited in-app, not here).** `MATCH_SCORE_THRESHOLD` was **removed** — the
  Discovered-Jobs matched/below-bar split is now the verdict predicate (`matchedIds()` in
  `lib/actions.ts`, mirroring the worker's `db.get_notifiable`), not a score cutoff; the
  fit score is display/ranking only.
- **`components/`** — `Dashboard` (Applications ↔ Discovered Jobs ↔ Watchlist ↔
  Unresolved tabs, each delegated to a `*Tab` wrapper), `ApplicationTable` (inline status edit), `KPIGrid`,
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

Seven tables, owned solely by `apps/web/prisma/schema.prisma` (`applications`,
`status_history`, `job_postings`, `watched_companies`, `feed_unresolved`,
`promotion_dismissed`, `app_settings`). Dates are stored as **ISO-8601 strings** for sortability and
timezone-independence (`date_applied` as `YYYY-MM-DD`; timestamps as full ISO with
millisecond precision to match Prisma / the worker's `_now()`).

```prisma
model applications {
  id              Int              @id @default(autoincrement())
  company_name    String
  job_title       String
  application_url String?
  date_applied    String           // YYYY-MM-DD
  category        String?          // free-form user label (vocabulary in app_settings)
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

  @@index([application_id])  // getApplicationHistory / deleteHistoryItem / getStatusFlow
}

model job_postings {
  id              Int           @id @default(autoincrement())
  source          String        // any VALID_SOURCES board (11 watchlist-capable) or feed-only oracle|jobvite
  external_id     String        // id returned by the board
  company_slug    String?       // board slug this posting came from (promotion grouping; null on legacy rows)
  company_name    String
  job_title       String
  location        String?
  job_url         String
  description     String        // full JD text (fed to the LLM)
  score           Int?          // 0-100 fit score (codex default / claude alternate)
  score_detail    String?       // JSON: assessment scorecard (seniority/domain/must_haves/nice_to_haves/summary), insufficient_context flag, screen, disqualification, recommended_resume, scorer provenance backend/model/scorer_version on fit-scored rows (pre-S2.1 rows: matched/missing keywords + reasoning)
  pipeline_status String        @default("new") // new|scored|notified|applied|discarded|failed|removed|expired
  pipeline_error  String?       // last stage/send error; cleared on successful notify
  attempts        Int           @default(0)     // SCORE-stage failures (requeued until 3, then parks failed)
  notify_attempts Int           @default(0)     // NOTIFY-stage send failures, separate budget (parks failed at 3)
  application_id  Int?          // back-link once marked applied
  application     applications? @relation(fields: [application_id], references: [id], onDelete: SetNull)
  created_at      String
  updated_at      String?
  posted_at       String?       // board posting date YYYY-MM-DD; scrape-date fallback for dateless boards; null on legacy pre-backfill rows

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
  reason       String  // workday_deferred | embedded_greenhouse | unsupported_host | list_fetch_failed | detail_fetch_failed
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

model app_settings {             // web-only key-value prefs (worker never reads it)
  key         String  @id        // e.g. 'categories'
  value       String             // JSON — for 'categories', the user's label list
  updated_at  String?
}
```

Relationships: deleting an application **cascades** to its `status_history` and
**nulls** the `application_id` on any linked `job_postings`. A posting is deduped
on `(source, external_id)`.

**Enums** (single source: `apps/web/src/lib/constants.ts`):

- **Statuses** (funnel order): `Applied` → `Online Assessment` → `Phone Screen` →
  `Interviewing: 1st…5th round` → `Final Round` → `Offer` → `Accepted`; terminals
  `Rejected`, `Withdrew`, `Ghosted`.
- **Categories:** user-configurable, **not a fixed enum** — the list lives per-install
  in `app_settings` (key `categories`) and is edited in-app (the header **Categories**
  button, auto-opened on first run). `DEFAULT_CATEGORIES` in `constants.ts` (Software
  Engineering, Data & Analytics, Product, Design, Finance, Marketing, Operations, Sales,
  Others) is only the seed/fallback before the user chooses. Category values are free-form
  labels — nothing in the pipeline reads them.

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
retry:   failed, attempts < 3     → new             (requeued next pass, BEFORE score;
                                                    attempts unchanged until re-failed)
score:   new                      → scored        (default)
                                  → discarded      (candidate hard-constraint fail)
notify:  scored, seniority=match AND domain=match AND NOT insufficient_context → notified
                                                   (else: stay scored, untouched;
                                                    success clears pipeline_error)
         on send error            → scored         (attempts+1, pipeline_error recorded;
                                                    retried next pass — the 3rd cumulative
                                                    failure parks the row failed)
expire:  scored|notified, detail source, board 404/410 → expired
                                                   (terminal; capped at 50/pass,
                                                    least-recently-updated first;
                                                    any other error → left alone)
fetch/score, on exception         → failed         (pipeline_error set; batch continues)
UI:      any non-applied row      → removed        (terminal; bulk Remove; UI-only hide)
```

- **`removed` is a terminal, UI-only status.** Set by `bulkRemove` / `removeAllInView` and by the per-row dismiss (`discardJobPosting`); the worker never writes it and never transitions away from it (`run_score`/`run_notify` ignore `removed` rows). Invisible to all buckets in the Discovered Jobs view; effectively hides the row without deleting it.

- **`expired` is terminal too**, and like `removed` it drops the row out of every
  Discovered bucket (the live buckets filter on `scored`/`notified`). It's written
  only by `run_expire`, only on an unambiguous 404/410 from the board's own per-job
  endpoint — never on a timeout, bot wall, or 5xx.

- **Stage gating is strict:** `run_retry` processes only `failed` rows with
  `attempts < RETRY_MAX_ATTEMPTS`; `run_score` processes only `new`; `run_notify` only
  `scored` rows the fit verdicts mark a strong match (`db.get_notifiable` —
  `seniority=match AND domain=match AND NOT insufficient_context`; non-matching rows
  stay `scored`, untouched). The score is not the gate — it quantizes to a rubric
  band edge and flipped run-to-run near the old `≥75` threshold, while the verdicts
  held stable across every draw (see §13). A failure in one posting never
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
- **Concurrent screen/fit calls never reorder or mis-associate a write.** `run_score`
  (§7.1) submits every `screen_fn`/`fit_fn` call to a thread pool up front, then
  consumes the futures **in the same order they were submitted** — never
  `as_completed` — so a slow call finishing late still lands its result on the
  correct row, and every `db.*` write stays on the calling thread throughout.
- **Every fit-scored row records who scored it — and only those rows.** `run.py`
  (the sole wiring layer, which alone knows the scorer's identity) hands `run_score`
  a `scorer_meta` of three fields — `backend`, `model`, `scorer_version` — and
  `_score_detail` merges them into the persisted `score_detail` JSON, so there is no
  schema change. They are stamped **only where a fit call actually ran**: both
  `_persist_scored` outcomes (`scored`, and the fallback-disqualified `discarded`
  that already paid for its call), never a screen-discarded or low-context row, which
  would otherwise claim a backend it never reached. `model` branches on `backend`
  alongside `make_scorer` (`run._scorer_meta`) so the stamp cannot name a model the
  scorer wasn't built with, and `scorer_version` (`prompts.SCORER_VERSION`) is a
  hand-bumped date string — bumped when `score.txt` or the profile/résumé inputs
  change in a way that should invalidate existing scores. This makes a
  `--score-backend` A/B readable off the data afterwards and lets a re-score select
  the rows predating a rubric change instead of re-buying the whole table.
  Deliberately **not** content hashes with automatic re-score triggering: that is a
  cache-invalidation system for inputs the operator changes a handful of times a year.
- **`now` is injected** per run (ISO-8601 UTC ms), making the pipeline
  deterministic and testable without a clock or network.

**Feed ingestion** (`run_feed`, optional):

- **A feed is a transport, never a `source`.** Each surfaced listing is resolved to
  its underlying board `(source, slug, external_id)` and ingested under that board's
  source, so dedup on `(source, external_id)` holds across the feed, the watchlist,
  and repeated passes. The resolver's id matches the adapter exactly for
  `lever`/`ashby` (uuid), `greenhouse` (numeric), and `smartrecruiters` (posting id);
  `workday` resolves to the job's `externalPath` and is ingested per-job through the
  CXS detail endpoint (`fetch_one`, like the other detail sources — §7.1 dual-mode),
  so no board-list keep-filter is involved.
- **Pre-filter then resolve then keep-only-surfaced.** Listings are gated on
  `active` + `category` keep-list + non-explicit-`sponsorship` *before* any fetch;
  survivors are grouped by `(source, slug)`, ids already present are skipped, and the
  board is fetched with the existing adapter keeping **only** the surfaced postings
  (a feed company is never ingested in full like a watchlist company). Each kept
  posting is stamped with its resolved `company_slug`. A **raising** board list-fetch
  is distinguished from a genuinely-empty board: the raise records every id that group's
  feed listings surfaced into `feed_unresolved` (`reason="list_fetch_failed"`) instead of
  silently dropping them — mirrors the detail-source failure recording below.
- **Unresolvable listings are recorded, not dropped.** A URL the resolver can't map
  to a supported board+slug (an *unparseable* workday URL, embedded greenhouse,
  unsupported host) is upserted into `feed_unresolved` (`host` + `reason`), keyed on
  `url`. When a later pass successfully (re-)ingests a posting for that URL, its
  `feed_unresolved` row is cleared (`db.delete_unresolved`), so a transient board failure
  doesn't permanently pollute the backlog. One bad board never aborts the batch (per-group
  try/except, mirroring `run_fetch`).
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
  nothing scored is orphaned (a row that reached scoring is never retroactively
  disqualified, so this is cleanly "scored, not a match"); **discarded** =
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
  application (`status='Applied'`, `category` chosen by the user at apply time from the
  configured vocabulary — free-form, default `Others` when blank — url from `job_url`) and atomically
  sets the posting to `pipeline_status='applied'` + `application_id`. Application and
  back-link are created together or not at all.
- **`reopenJobPosting(id)`** reverses a disqualification (from the Discarded view) back
  to `scored`, preserving `score_detail`.
- **`discardJobPosting(id)`** — the per-row dismiss — sets `pipeline_status='removed'`
  (hidden, like bulk Remove), **not** `discarded`: the Discarded bucket is disqualified-only,
  so a hand-dismissed row must not masquerade as an auto-disqualification.
- **`bulkRemove(ids)`** sets `pipeline_status='removed'` for the given ids (terminal;
  the Remove-selected button is offered in every bucket whenever rows are selected).
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
  and CSV import — all three run their existence-check + create in a `$transaction`
  (findFirst-then-throw-to-rollback if a match exists), closing the TOCTOU window
  between the check and the write. There is no DB-level `@@unique` on the pair
  (deferred — see PROGRESS.md); dedup is enforced entirely in application code.
- **`deleteHistoryItem`** recomputes the application's current status to the most
  recent remaining history entry, or `Applied` if none remain — the delete +
  recompute + status update run in one `$transaction`.
- **KPIs** (`getKPIs`): `applied` = total; `active` = total − rejected − offer −
  withdrew − ghosted (offer bucket counts Offer + Accepted; interviewing bucket
  counts Phone Screen + any Interviewing + Final Round).
- **CSV import** requires columns `company_name, job_title, date_applied`; unknown
  `status`/`category` values fall back to `Applied`/`Others`; existing
  `(company, title)` rows are skipped (reported in `{added, skipped, errors}`).
  The per-row loop runs in **chunked** `$transaction`s (100 rows each), so a large
  import doesn't hold SQLite's single write lock long enough to starve a concurrent
  worker pass; a mid-import DB error rolls back only the current chunk, and re-import is
  idempotent (per-`(company, title)` dedup) so it completes the rest. Import also
  **reverses the export formula-injection guard** — it strips a leading `'` that precedes
  a formula-lead char (`= + - @`, tab, CR) — so an export→import round-trip is lossless.
  Per-row validation `continue`s (missing field, duplicate) are unaffected.

**Cross-service data invariant:** the schema is owned solely by Prisma; the worker
reads/writes rows but issues **no DDL**. The worker's test fixture
(`apps/worker/tests/fixtures/schema.sql`) is kept in sync with `schema.prisma` by a
CI guard (`tools/check_schema_drift.mjs`, `make check-schema`).

**Failure handling and recovery limits:**

- **`failed` is retried automatically, capped — not fully terminal.** A fetch/score
  exception parks the row `failed` immediately (`db.mark_failed`, `attempts+1`,
  `pipeline_error` set). `run_retry` requeues it back to `new` on the **next** pass
  as long as `attempts < RETRY_MAX_ATTEMPTS` (3) — a bulk, non-per-item UPDATE
  (`db.requeue_failed`), run before `run_score` so the requeued row is rescored
  the same pass. Score and notify keep **separate counters**: `attempts` counts
  score-stage failures (`mark_failed`), `notify_attempts` counts send failures
  (`record_notify_failure`), so score hiccups can no longer pre-spend the delivery
  budget. `run_retry` guards **both** (`attempts < RETRY_MAX_ATTEMPTS AND
  notify_attempts < NOTIFY_MAX_ATTEMPTS`), so a row parked by `run_notify`'s
  exhausted retries (`notify_attempts >= NOTIFY_MAX_ATTEMPTS`) never requeues even
  though its `attempts` may be 0 — no other code path writes
  `pipeline_status='failed'`. A requeued row re-runs the full screen+fit; flipping
  to `discarded` on a retry is a legitimate outcome, not a bug. Persistent failures
  requeue, fail, and repark each pass until the 3rd failure on either counter — a
  hard ceiling of **3 score + 3 notify failures per row** — at which point
  `run_retry` no longer requeues it and it stays parked for good; from there,
  recovery is still the human act (`reopenJobPosting`/`bulkReopen` write `scored`,
  resetting neither counter).
- **`discarded` is terminal, with one operator-only way back.** Nothing automatic
  re-screens a discard: the state exists precisely so a posting ruled out by a
  candidate hard requirement stops costing calls. But the rule itself is editable
  (`candidate.locations`, `highest_degree`, `work_authorization`,
  `exclude_internships`), so without an escape hatch an edit — or a fix to the screen
  itself — would leave every prior discard frozen under the old rule, and a **false**
  discard permanent. `--rescreen-discarded` (`db.requeue_discarded`, one bulk UPDATE
  run immediately before `run_retry`) returns them to `new` for this pass.
  Unbudgeted: a discard spends no `attempts`, so there is no counter to guard the way
  `run_retry` guards two. **Filtered on exactly one condition — the row must have a
  non-empty `description`.** A stub-gate discard is stored deliberately un-hydrated
  (`run_fetch` exempts `discarded` rows from the bodyless drop) because it never reaches
  the scorer; requeueing one is *irreversible loss*, since it becomes `new`, the thin-JD
  gate parks it `scored` at score 0, and `upsert_postings` is `ON CONFLICT DO NOTHING`
  so no later pass back-fills the JD. Left `discarded`, the stub gate can still revisit
  it. Everything else comes back. It is
  **one-shot** — `main` rejects it without `--once`, because on the interval schedule
  it would resurrect the same discards every pass and re-charge the paid fit scorer
  for each survivor indefinitely. Screening is free on the default ollama backend; the
  fit calls that follow are bounded only by `--score-limit`, so pair the two on a
  large backlog.
- **A dead screen *provider* circuit-breaks the screen phase — and no unscreened row
  is ever fit-scored.** `screen_posting` errs toward KEEP on any provider failure,
  which is right for one flaky call and wrong for an outage: it raises no exception and
  marks nothing `failed`, so before this the whole backlog was silently handed to the
  **paid** fit scorer unscreened — the ~18% normally discarded for free became paid
  calls, and the hard-requirement gate stopped filtering. The verdict now carries
  `provider_error`, and `run_score` (a) leaves such a row `new` — untouched, no
  `attempts` spent, screened properly next pass — unless a **deterministic** gate
  (location/intern, which cost nothing and ran fine) disqualified it, in which case that
  verdict stands; and (b) runs a second `_BackendBreaker` over the screen phase with the
  same signature as the fit one (`_BREAKER_LIMIT` provider errors, zero successes),
  aborting it and cancelling the queued remainder. One success disarms it. `extract=None`
  (`SCREEN_BACKEND=none`) is **not** a provider error — there is no provider, the
  deterministic gates run alone, and those rows score normally as documented.
  (PRINCIPLES "the four kinds of uncertainty" — circuit break.)
- **A dead fit *backend* circuit-breaks the score pass — it does not convict every
  posting.** `run_score` isolates a bad posting (per-item `mark_failed`), but a
  *systemic* fit-backend outage (e.g. `codex exec` not logged in) would otherwise
  mark the whole `new` backlog `failed`, burning its retry budget on the outage. A
  shared `_BackendBreaker` watches for the outage signature — `_BREAKER_LIMIT` (5)
  failures with **zero** successes this pass — and aborts scoring, leaving the
  untouched remainder `new` (recoverable), with one operator-level line. One success
  disarms it, so a flaky-but-alive backend never trips. The `batch_size==1` singles
  fallback is guarded (`len(chunk) > 1`) so it no longer re-issues the identical
  failed call. (PRINCIPLES "the four kinds of uncertainty" — circuit break.)
- **A score run is interruptible and does not abandon finished work.** The fit phase
  consumes futures via `as_completed` and persists each result on the calling thread
  as it completes (associated to its row by a `future -> chunk` map), so a straggler
  never holds finished, already-paid-for scores unwritten. On `KeyboardInterrupt` the
  pool is torn down with `cancel_futures=True` — queued fit calls are **cancelled, not
  drained** — so Ctrl-C stops launching new paid calls instead of waiting out the
  whole backlog (the old `shutdown(wait=True)` made abort uninterruptible).
- **Notify send errors are retried, bounded — but a systemic channel fault breaks the
  pass instead.** `run_notify` treats a genuinely *per-posting* Telegram send error as
  transient: the row **stays `scored`** (`notify_attempts+1`, `pipeline_error`
  recorded) so the next scheduled pass retries the send — the match never leaves the
  default Discovered-Jobs view while retrying. The `NOTIFY_MAX_ATTEMPTS`-th (3) send
  failure parks it `failed` (terminal *for the notify stage*), so a *persistent* per-row
  fault (a malformed message) surfaces in a visible queue instead of retrying silently
  forever. A **systemic** fault, though, must never convict the postings riding on it:
  a bad-token error (`_systemic_send_error` — 401/403 or an invalid-token body), or
  `_BREAKER_LIMIT` consecutive failures with zero deliveries, **circuit-breaks the
  pass** — every remaining matched row left `scored`, **no `notify_attempts` spent**,
  one operator line. This closes the data-loss hole where a wrong token drove every
  matched row to `failed` over three passes, unrecoverably. A successful send clears
  `pipeline_error`. Delivery is **at-least-once**: the send is a single atomic
  `sendMessage`, so a timeout after delivery can only duplicate the alert, never
  half-send it — a duplicate ping beats a lost match. `notify_attempts` counts send
  failures cumulatively, so a row manually reopened from `failed` gets one fresh notify
  attempt per reopen. Design:
  [`superpowers/specs/2026-07-09-notify-retry-design.md`](./superpowers/specs/2026-07-09-notify-retry-design.md).

**Unenforced clause (asserted, not checked).** One contract-flavored claim has no
deterministic gate; treat it as an *intention backed by the human in the loop*, not a
guarantee:

- **Hard-constraint screening**: work authorization is the quote-grounded LLM check
  (**D1**, §7.1) — the model's extracted quote is verified against the JD text before
  it can disqualify, with `NO_SPONSOR_PHRASES` as a closed-list floor underneath it —
  and its precision/recall have not yet been measured against a labeled set (open
  item, §7.1/PROGRESS.md); **clearance** remains an LLM *semantic* extraction with a
  code check — a misjudgment sends a spurious alert or discards an applicable role.
  The kept `disqualification_reason` + `reopenJobPosting` let a human override.
- **Location** (`resolve_location`, **D2**, §7.1) errs toward keep; the residual
  gaps are ambiguity-shaped — a city whose **highest-population** bearer is foreign
  discards even when the posting meant a smaller US namesake ("Manchester" → GB,
  though Manchester NH exists; real boards append the state, which the US-state
  guard keeps), and a token that resolves to nothing still keeps. Both are backed by
  the human in the loop (kept `disqualification_reason` + `reopenJobPosting`).

### Invariant → test traceability

Grounds the "verifiable" claim. **(no test)** marks an invariant with **no** (or only indirect)
automated coverage — those rely on code review or the human in the loop, not a test.

| Invariant | Test(s) |
|-----------|---------|
| Pipeline stage gating + per-item failure isolation | `worker/tests/test_pipeline.py`, `integration/test_pipeline_e2e.py` |
| Dedup `(source, external_id)` on ingest | `test_db.py`, `test_pipeline.py` |
| WAL + `busy_timeout` pragmas on connect | `test_db.py` |
| Web Prisma client's SQLite connection defaults `busy_timeout` ≥5000 ms (regression lock) | `db-pragma.int.test.ts` |
| Disqualified → `discarded`; empty candidate skips the screen | `test_score.py`, `test_pipeline.py`, `test_run.py` |
| Sponsorship disqualifies only on a quote that is both **present** in the JD and **on topic** — hallucinated and real-but-irrelevant quotes each keep the posting | `test_score.py` (`test_hallucinated_quote_keeps_the_posting`, `test_real_but_off_topic_quote_keeps_the_posting`, `test_on_topic_quotes_still_disqualify`) |
| Deterministic location gate (`resolve_location`, pycountry + geonamescache; every token resolved): foreign→discard, US-state/US-city/remote/missing→keep | `test_score.py` (`test_resolve_location`, `test_token_country_*` + gate integration tests) |
| Fetch-time max-age + title_exclude drop | `test_fetch.py::test_prefilter_*` |
| Deterministic gate hoisted to fetch (discarded, no Ollama) | `test_pipeline.py::test_run_fetch_marks_location_miss_discarded` |
| Multi-resume loading (`load_resumes`): label = stem minus `resume_`; `personal_profile.txt` → profile, never a version; sorted order; dotfiles skipped; zero files / duplicate label / non-UTF-8 → clean `SystemExit` | `test_run.py` (`test_load_resumes_*`) |
| Multi-resume scoring: `recommended_resume` enum-constrained to the actual labels (≥2 versions), field omitted for a single resume; cached-prefix block layout (header → profile → resumes, `cache_control` on last); normalization pass-through | `test_score.py` (`test_score_schema_*`, `test_scorer_system_blocks_*`, `test_recommended_resume_*`) |
| `recommended_resume` persisted in `score_detail`; Telegram `Resume:` line only when set — malformed/absent `score_detail` never crashes notify; modal badge renders when present, absent otherwise | `test_pipeline.py`, `test_notify.py`, `web/src/components/__tests__/JobDetailModal.test.tsx` |
| A screen `provider_error` row is never fit-scored (left `new`, 0 `attempts`) unless a deterministic gate disqualified it; `_BREAKER_LIMIT` consecutive provider errors with zero successes abort the screen phase; one success disarms; `SCREEN_BACKEND=none` is not a provider error | `test_pipeline.py` (`test_run_score_never_pays_to_fit_score_an_unscreened_row`, `test_run_score_provider_error_still_discards_on_a_deterministic_gate`, `test_run_score_screen_breaker_aborts_and_says_so`, `test_screen_breaker_counts_raised_failures_too`, `test_run_score_circuit_breaks_a_dead_screen_provider`, `test_run_score_one_screen_success_disarms_the_breaker`), `test_score.py` (`test_extract_failure_is_flagged_provider_error`, `test_screen_backend_none_is_not_a_provider_error`, `test_provider_error_still_honours_the_deterministic_gates`) |
| The screen breaker **announces** its abort, and counts a raised exception the same as a `provider_error` verdict | `test_pipeline.py` (`test_run_score_screen_breaker_aborts_and_says_so`, `test_screen_breaker_counts_raised_failures_too`) — the two `circuit_breaks`/`disarms` tests above pass with the breaker stubbed out, so they are not on their own evidence that it works |
| `--rescreen-discarded` never requeues an un-hydrated (`description=''`) stub-gate discard | `test_pipeline.py::test_requeue_discarded_leaves_un_hydrated_stub_discards_alone` |
| `--no-notify` skips the notify stage without consuming anything (rows stay `scored`, alert on a later pass) | `test_run.py::test_run_once_no_notify_scores_without_alerting` |
| Scorer provenance (`backend`/`model`/`scorer_version`) stamped into `score_detail` on fit-scored rows only — never screen-discarded or low-context; `model` tracks the backend `make_scorer` picks | `test_pipeline.py` (`test_run_score_stamps_provenance_only_on_fit_scored_rows`, `test_run_score_stamps_provenance_on_fallback_disqualified_rows`, `test_run_score_omits_provenance_when_no_scorer_meta`), `test_run.py` (`test_run_once_stamps_the_active_fit_backend_and_model`, `test_scorer_meta_model_tracks_the_backend_make_scorer_picks`) |
| `discarded` is terminal except via `--rescreen-discarded` (`db.requeue_discarded`): all discards → `new`, no other status touched, one-shot (rejected without `--once`) | `test_pipeline.py` (`test_requeue_discarded_returns_rows_to_new_for_a_later_screen`, `test_requeue_discarded_leaves_every_other_status_alone`), `test_run.py` (`test_run_once_rescreen_discarded_requeues_before_scoring`, `test_rescreen_discarded_requires_once`) |
| `mark_failed` → terminal `failed` + `attempts+1` (fetch/score paths) | `test_db.py` |
| Per-posting notify send error → stays `scored` + `notify_attempts+1` (its own budget, not score `attempts`) + error recorded; parks `failed` at `NOTIFY_MAX_ATTEMPTS` (3); success clears `pipeline_error`; notified rows never re-alerted | `test_pipeline.py`, `test_db.py`, `integration/test_pipeline_e2e.py` |
| A **systemic** send fault (bad token `_systemic_send_error`, or `_BREAKER_LIMIT` consecutive failures, zero deliveries) circuit-breaks the notify pass: rows left `scored`, **no `notify_attempts` spent** | `test_pipeline.py` (`test_run_notify_auth_error_circuit_breaks_without_charging`, `test_run_notify_circuit_breaks_after_consecutive_failures`) |
| Score `attempts` and notify `notify_attempts` are independent — score hiccups never pre-spend the notify budget | `test_pipeline.py` (`test_notify_budget_survives_prior_score_hiccups`) |
| A **dead fit backend** (`_BREAKER_LIMIT` failures, zero successes) circuit-breaks the score pass, leaving the untouched remainder `new`; the `batch_size==1` singles fallback is not re-issued | `test_pipeline.py` (`test_run_score_dead_fit_backend_circuit_breaks_leaving_rows_new`, `test_run_score_singles_fallback_not_reissued_at_batch_size_one`) |
| A score run is interruptible (`KeyboardInterrupt` → `cancel_futures`, queued fit calls not drained) and persists finished work as it completes (`as_completed` + `future→chunk` map) | `test_pipeline.py` (`test_run_score_keyboard_interrupt_cancels_pending_keeps_done`) |
| `run_retry` requeues `failed`→`new` only while `attempts < RETRY_MAX_ATTEMPTS` (3) **and** `notify_attempts < NOTIFY_MAX_ATTEMPTS` (3), caps at the 3rd failure on either, never requeues a notify-exhausted row, sets `updated_at` | `test_pipeline.py` (`test_run_retry_*`), `test_run.py` (`test_run_once_calls_four_stages_in_order` — the feeds-off path; with a feed enabled the pipeline is five stages) |
| A recovered row (score-fail → `run_retry` → successful re-score) clears `pipeline_error` and preserves `attempts` | `test_pipeline.py` (`test_run_retry_recovery_clears_pipeline_error_keeps_attempts`) |
| Discovered-jobs score-aware buckets (matched/belowbar/discarded/lowcontext/failed, mutually exclusive; discarded = disqualified only; low-context = thin-JD **or** `insufficient_context` flag) + sort (score/posted) + pagination + disqualification-cause sub-filter + bulk remove/reopen/removeAllInView; per-row dismiss → `removed` | `web/src/__tests__/actions.test.ts`, `actions.int.test.ts`, `web/src/components/__tests__/DiscoveredJobsTable.test.tsx` |
| Fit scorer emits a top-level `insufficient_context` boolean (schema-required, normalized, persisted); Below-bar why-cell shows seniority/domain verdict pills + top gap with a legacy-`reasoning` fallback; `recommended_resume` label under the score | `worker/tests/test_score.py`, `test_pipeline.py`, `web/src/components/__tests__/DiscoveredJobsTable.test.tsx` |
| `markJobApplied` atomic create + back-link + dedup | `actions.test.ts`, `actions.int.test.ts` (real-Prisma tx) |
| `updateApplicationStatus` validates `STATUSES`, appends history | `actions.test.ts`, `actions.int.test.ts` |
| `reopenJobPosting`→`scored`, `discardJobPosting`→`removed` (per-row dismiss), `bulkRemove`→`removed`, `bulkReopen`→`scored`, `removeAllInView` | `actions.test.ts`, `actions.int.test.ts` |
| `deleteHistoryItem` recomputes current status | `actions.int.test.ts` |
| KPI aggregation buckets | `actions.test.ts`, `actions.int.test.ts` |
| Chart-data aggregation (`getStatusFlow`/`getTimelineData`/`getCategoryData`): Sankey chain dedup/collapse + multi-hop, T-split day counts, category counts incl. ties/`null`->Others | `charts.int.test.ts` |
| CSV import/export rules (dedup, enum fallback) | `actions.int.test.ts` |
| Feed resolve (URL→board incl. workday/smartrecruiters/workable/oracle/jobvite + GH-EU host) + classify-reason | `test_feed_resolve.py` |
| SmartRecruiters adapter (two-step list+detail) | `test_smartrecruiters.py` |
| Workable adapter (per-board list) | `test_workable.py` |
| Oracle adapter (per-listing `fetch_one`) + Jobvite adapter (JSON-LD `fetch_one`) | `test_oracle.py`, `test_jobvite.py` |
| `fetch_one_company` dispatcher (detail source / unknown / non-detail) | `test_fetch.py` |
| `run_feed` detail-fetch path (per-id fetch, bad-listing isolation, slug stamp) | `test_feed_pipeline.py` |
| Feed prefilter (active / category / sponsorship) | `test_feed_prefilter.py` |
| `run_feed` keeps only surfaced ids, records unresolved, skips existing, isolates a bad board, stamps `company_slug` | `test_feed_pipeline.py`, `test_feed_simplify.py` |
| Promotion suggestions (signal, exclude watched/dismissed + feed-only sources) + dismiss | `web/src/__tests__/promotion.test.ts`, `promotion.int.test.ts` |
| Unresolved-feed grouping by host+reason | `web/src/__tests__/unresolved.test.ts`, `unresolved.int.test.ts` |
| Watchlist DB helpers (import idempotent, record_unresolved upsert, existing ids) | `test_watchlist_db.py` |
| Watchlist auto-seed-on-empty + feed wiring in `run_once` | `test_run.py` |
| `feeds:` config parsing + defaults | `test_feed_config.py` |
| Watchlist actions (list / add+validate+dedup / remove) | `web/src/__tests__/watchlist.test.ts`, `watchlist.int.test.ts` |
| iCIMS + Phenom adapters (server-HTML cards; pcsx search + per-job detail) | `test_icims.py`, `test_phenom.py` |
| A stub-rejected phenom posting costs no detail GET | `test_phenom.py::test_stub_gate_hydrates_only_the_survivor` |
| An unknown keep verdict fails open | `test_phenom.py::test_stub_gate_fails_open_on_an_unknown_verdict` |
| A stub-rejected workday posting costs no detail GET | `test_fetch_new.py::test_workday_stub_gate_skips_the_dropped_detail_call` |
| A workday `discard` HYDRATES rather than storing a GUID-less stub row | `test_fetch_new.py::test_workday_stub_gate_hydrates_a_discard_instead_of_storing_it` |
| The workday gate stub carries no `external_id` (unstorable by construction) | `test_fetch_new.py::test_workday_parse_stub_carries_no_external_id` |
| The gate never changes a row's status | `test_pipeline.py::test_run_fetch_gated_batch_matches_the_ungated_statuses` |
| Pinpoint + Workday board adapters | `test_fetch_new.py` |
| Custom-recipe executor (`json`/`next-data` modes, paging, fields map) | `test_custom.py` |
| Browser-recipe executor (CSS extraction, detail circuit-breaker, SSRF guards on scraped URLs) | `test_browser.py` |
| Embedded-greenhouse enriching resolver (token scrape → greenhouse ingest) | `test_embedded_gh.py` |
| SSRF guard (`is_safe_public_url` / `get_redirect_safe` re-validates every redirect hop) + util helpers | `test_util.py` |
| Config load/validate (sources, slugs, recipes, candidate block) | `test_config.py` |
| `add_watched` CLI watchlist write boundary | `test_add_watched.py` |
| Cross-service sync guard (source enums + low-context threshold + SPEC's source-coverage matrix) | `test_source_enums_sync.py` |
| `/api/health` 200/503 probe; `/api/codex-usage` snapshot route; usage-bar rendering | `web/src/__tests__/health.test.ts`, `codex-usage.test.ts`, `web/src/components/__tests__/CodexUsageBar.test.tsx` |
| Core UI rendering (tabs, KPI grid, application table, add form, pagination, history modal) | `web/src/components/__tests__/` (`Dashboard`, `KPIGrid`, `ApplicationTable`, `AddApplicationForm`, `Pagination`, `StatusHistoryModal`) |
| Integration-harness self-check (real Prisma round-trip on the temp DB) | `web/src/__tests__/harness.int.test.ts` |
| Dead-link sweep: 404/410 → `expired`, every other error leaves the row live, queue rotation | `test_pipeline.py` (`run_expire`) |
| Worker SQL fixture ↔ `schema.prisma` in sync | `test_schema_sync.py` + `tools/check_schema_drift.mjs` (CI) |
| No private file (`.env` / résumé / db / `config.yaml`) tracked by git | `tools/check_privacy.mjs` (+ `--self-test`; CI) |

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
  actually turns on. The codex fit call carries batching machinery for that quota
  (message-bound, not tokens) but it is **parked at `batch_size=1`** — the
  batched==single guard failed (§13). The Claude backend stays wired for a metered
  A/B and deliberately does **not** batch: its cached system prefix already makes
  the marginal posting cheap — the lever batching would have stood in for on codex.
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
- **Company-owned boards only.** The eleven platform adapters use official public
  endpoints (iCIMS via its server-rendered HTML); `custom`/`browser` rows are
  operator-curated recipes against a company's own careers site. LinkedIn/Indeed
  scraping is deliberately avoided. Adapters are isolated so one broken source only
  affects that source.

---

## 11. Non-functional requirements

- **Privacy:** resume (`apps/worker/resume/`), secrets (`apps/worker/.env`),
  config (`config.yaml`), and the database (`db/`) are gitignored. The repo ships
  only `*.example` templates; real resume files are untracked, so no extra git
  steps are needed for *new* work (see `CONTRIBUTING.md`). **Closed:** `resume.txt`
  and the real `config.yaml` were committed 2026-06-05 and untracked 2026-06-08;
  the blobs were purged from all history with `git filter-repo` and force-pushed
  (see CHANGELOG).
- **Reliability / error recovery:** one bad posting or flaky external never aborts a
  batch — the failure is recorded on the row and processing continues; failed rows
  auto-retry under separate 3-failure budgets for the score (`attempts`) and notify
  (`notify_attempts`) stages before parking for good, and recovery from there is a
  manual reopen. A *systemic* fit-backend or notify-channel outage circuit-breaks its
  stage (spending no budget, leaving rows recoverable) rather than convicting every
  posting (contract in §9, "Failure handling and recovery limits").
- **Concurrency safety:** WAL + `busy_timeout=5000` ms + the directory mount, as
  §6/§10 describe — safe under low write-contention, not a guarantee under sustained
  dual-write load.
- **Performance:** the local hard-requirements screen runs ~2 s/posting on an 8 GB
  GPU; the fit score adds one hosted call per **batch of up to `batch_size` postings**
  on the default `codex` backend — tens of seconds per `codex exec` turn, amortized
  over the batch when `batch_size>1` — but `batch_size` defaults to **1** (batching
  parked, see below), so in practice this is one `codex exec` turn per posting; or one
  cached-prefix API call **per posting** on `claude` (unbatched by design; see §7.1).
  The root page is `force-dynamic` (no stale cache).
- **Subscription quota is the real bound on a big re-score — flat-rate is NOT
  unlimited.** Codex on ChatGPT Plus meters a **message budget** whose observed
  binding limit is **weekly** (`window_minutes=10080`; the capture renders whatever
  limits codex reports, §7.1). At the shipped `batch_size=1`, a ~640-row re-score is
  ~640 messages — it must be **paced against remaining weekly headroom** (visible
  via the codex usage bar, §7.2), not run in one sitting. Batching at 10 would have
  cut that to ~64 `codex exec` calls and ~6× fewer input tokens, but it failed its
  acceptance guard and is parked at every size >1 (post-mortem + numbers in §13) —
  and a fix would need *stronger per-JD prompt isolation*, which is exactly what
  one-JD-per-call already buys, so the win and the fix are in tension; the quota
  problem needs pacing, not a bigger batch. **Concurrency (`--score-workers`, §7.1) is
  a different lever from batching and does not change the message count**: N parallel
  `codex exec` calls still spend N messages, exactly like N serial ones — only
  wall-clock shrinks. So the weekly-window bound argues for **pacing** the fit loop
  (`--score-limit`, run across multiple passes) against remaining headroom, not
  against running those N calls concurrently. At the cap Codex hard-blocks (no
  degraded fallback) and `codex exec` exits **1 with no distinct rate-limit code**,
  so pacing logic must match the stderr text, not the exit status. Each call also
  pays a fixed ~9.7 k input tokens of Codex scaffolding (12.8 k before the tools
  were disabled) to emit ~80 tokens of JSON, and gets **no prompt-cache credit**
  (`cached_input_tokens` stayed 0 on back-to-back identical prompts) — the opposite
  of the `claude` backend's cached prefix, and the strongest standing argument for
  the metered API if the flat rate ever stops paying for itself.
- **Time zone:** the heatmap uses the server's local "today"; set `TZ` on the
  container if deploying in a different zone from where you live.
- **Security:** the RESUME / PERSONAL PROFILE / JOB text is marked as *data, not
  instructions* in the score prompt (a posting can't inject directives); secrets
  live only in the gitignored `.env`, read by `run.py`. A Telegram send error's
  exception text embeds the bot token (carried in the request URL); `run_notify`
  scrubs it (replaced with `***`) before it reaches `job_postings.pipeline_error`
  or stdout, so it never escapes `.env` into the shared DB or logs (see CHANGELOG).
  Watchlist **slugs** are structurally validated at all three write boundaries
  (`actions.ts`, `config.py`, `add_watched.py`); the two sources that pack a hostname
  in the slug additionally run the built host through `is_safe_public_url` in their
  `_parts` (`phenom` — the segment *is* the host; `workday` — belt-and-braces, its
  `.myworkdayjobs.com` suffix is hardcoded), so an internal-IP slug raises instead
  of being fetched.
- **Accepted security residuals** (deliberate, documented — single-user,
  loopback-bound, curated-input deployment; `SECURITY.md` points here):
  - **`next@14.2.35` dependency advisories.** `npm audit --omit=dev` reports the
    `next` package as high severity — three GHSA advisories roll up into it: DoS via
    the Image Optimizer's `remotePatterns`
    ([GHSA-9g9p-9gw9-jx7f](https://github.com/advisories/GHSA-9g9p-9gw9-jx7f)), HTTP
    request deserialization DoS with insecure React Server Components
    ([GHSA-h25m-26qc-wcjf](https://github.com/advisories/GHSA-h25m-26qc-wcjf)), and
    HTTP request smuggling in rewrites
    ([GHSA-ggv3-7p47-pfv8](https://github.com/advisories/GHSA-ggv3-7p47-pfv8)) — plus
    a moderate finding for `postcss@8.4.31`, the copy Next.js 14 bundles internally
    (distinct from, and older than, the project's own top-level `postcss`, which is
    patched). All four need the `next@16` major to clear. Accepted because they are
    server-side web-request attack surfaces that presume a reachable, adversarial
    network client — not a concern for a server that only accepts connections from
    `127.0.0.1`. Revisit at the next Next.js major upgrade.
  - **`autoheal` holds the Docker socket** — `docker-compose.yml` mounts
    `/var/run/docker.sock` (root-equivalent host control) into
    `willfarrell/autoheal:1.2.0`, pinned by mutable tag, running as root — the
    highest-privilege component in the stack. Deliberate: it is what closes the
    stale-mount self-heal loop (§6).
  - **SSRF guard is a pure string check** (`util.is_safe_public_url`, §7.1): it does
    no DNS resolution, so three shapes remain reachable — (a) one read-only redirect
    GET on the `browser` path (Playwright's route interceptor can't fire on a
    followed 3xx; the response is discarded, so no data returns), (b) DNS-rebinding
    (public at check time, internal at fetch), (c) a hostname that statically
    resolves internal (e.g. `metadata.google.internal`). Accepted for a single-user
    worker fetching a curated board list with `browser` sources gated off by
    default; the feed/custom paths re-validate every redirect hop before it is
    requested (`util.get_redirect_safe`, §7.1).
  - **JD prompt-injection can skew a score, not leak a secret** — the codex scorer
    is tool-less by construction (§7.1), so a hostile JD can't read or exfiltrate
    anything; it could still talk the model into a wrong number/verdict. Probed
    behaviorally (a canary JD demanding score 99 got 0); blast radius is one bogus
    Telegram alert.

---

## 12. Setup and deployment

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

This section is the authoritative command list.
[`SETUP.md`](./SETUP.md) is the friendlier front door — prerequisites in table
form, the tracker-only vs. full-pipeline decision, and which settings live in
`config.yaml` vs. the DB — and links back here for the commands themselves.

**Prerequisites:** Docker + Compose (≥ 24) for the web app; Node 20+ and Python
3.11+ for local non-Docker dev/tests **and to run the worker**, which is native,
not containerized (§6); for the hard-requirements screen, Ollama reachable — a
local GPU, or a remote/cloud instance via `OLLAMA_HOST` — **or** one of five other
`SCREEN_BACKEND` values (`codex`, `claude-code`, `claude-api`, `openai-api`,
`none`; §7.1) if there is no GPU and no Ollama at all; the Codex CLI on the
operator's ChatGPT subscription for fit scoring by default (`codex login`), or an
Anthropic API key for the metered `claude` alternate; and **optionally** a
Telegram bot for push alerts — without it, matches still surface in the web
Discovered Jobs tab (§7), just with no push.

`make setup` bootstraps a checkout in one command (web + worker deps, `db-push`,
and non-clobbering `*.example` template copies); `make doctor` is the preflight —
one status line per prerequisite, exiting non-zero only when a *universal* one
(worker deps + a set-up DB) is missing, while provider rows (ollama/codex/claude/
telegram/…) report `ok`/`no` without failing the exit code.

**Web app only (no pipeline):**

```bash
# Local dev
cd apps/web && npm install && npx prisma generate && npm run dev   # :3000
npx prisma db push          # if db/applications.db doesn't exist yet
# Docker, web service only
UID=$(id -u) GID=$(id -g) docker compose up web --build -d
```

**Full pipeline:** `make setup` does deps, `db-push`, and steps 1 and 3's **config**
copies (only when the target is absent); then fill in the copied files. It does *not*
do step 2 — a placeholder `resume.txt` would be loaded as a real résumé version, so an
absent file (which fails loudly) is safer. Longhand:

1. `cp apps/worker/config.yaml.example apps/worker/config.yaml` — set `companies`
   (`source` ∈ the eleven watchlist-capable boards {greenhouse, lever, ashby,
   workday, pinpoint, smartrecruiters, workable, icims, phenom, custom, browser},
   board `slug`, `name`), optional `title_filter`, the `candidate` hard-constraint
   block, `schedule_hours` (24). Workday's `slug` packs `tenant/datacenter/site`
   (quote it).
2. `cp apps/worker/resume/resume.txt.example …/resume.txt`, then replace with your
   real resume (plain text, fed to the fit scorer) — or provide multiple
   `resume_<label>.txt` versions plus an optional `personal_profile.txt` for
   about-the-candidate context (`apps/worker/resume/README.md`).
3. `cp apps/worker/.env.example apps/worker/.env` — fill `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `OLLAMA_HOST` (`http://localhost:11434`), plus
   `ANTHROPIC_API_KEY` for `--score-backend claude` and/or
   `--screen-backend claude-api`, or `OPENAI_API_KEY` for
   `--screen-backend openai-api`. Optional overrides: `OLLAMA_MODEL`,
   `SCORE_BACKEND`, `SCREEN_BACKEND`, `SCREEN_MODEL`, `CODEX_SCORE_MODEL`,
   `ANTHROPIC_SCORE_MODEL`, `OLLAMA_NUM_CTX`, `CODEX_BATCH_SIZE`.
4. The default `codex` fit backend authenticates from the operator's `codex login`
   state (`auth_mode=chatgpt`), not from `.env` — run `codex login` once on the
   worker host and confirm with `codex doctor` (auth ok). A logged-out host fails
   every fit call loudly; it never scores 0.
5. On the host: `ollama pull qwen3.5:4b && ollama serve` — only needed for the
   default `SCREEN_BACKEND=ollama`; skip it entirely on one of the five other
   screen backends (§7.1).
6. From the repo root: `UID=$(id -u) GID=$(id -g) docker compose up --build -d`
   (or `make up`) starts the **web app + autoheal only** — the worker is **not**
   containerized (§6, removed 2026-07-16). Run it natively on the same host:
   `cd apps/worker && python -m ats_worker.run`. It runs one pass immediately,
   then every `schedule_hours`.

**One-off test pass:**
`cd apps/worker && python -m ats_worker.run --once` (defaults to `config.yaml`/`.env`
in the cwd; pass `--config`/`--env` for a different path).

**Volumes & env:** `./db` → `/data` (directory mount; the web container reads
`DATABASE_URL=file:/data/applications.db`). The native worker defaults to
`DB_PATH=../web/prisma/applications.db` — a symlink onto the same
`db/applications.db`. `make` targets
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
  coverage gates, web lint + `prisma generate`, the schema-drift and privacy guards,
  and a gated Playwright e2e job.
- **Schema-drift guard:** `tools/check_schema_drift.mjs` fails if
  `apps/worker/tests/fixtures/schema.sql` and `apps/web/prisma/schema.prisma` fall
  out of sync.
- **Privacy guard:** `tools/check_privacy.mjs` (`make check-privacy`) fails if git
  *tracks* any private file — `.env`, `config.yaml`, `db/` or any `*.db`,
  `apps/worker/resume/` (bar `README.md` / `*.example`), `apps/worker/eval/`,
  `resumes/`. `.gitignore` only guards the default path; this catches `git add -f`,
  a loosened ignore rule, or a pre-existing commit. Path deny-list only (no content
  scan); `--self-test` asserts the allow/deny regexes still discriminate, and CI runs
  both.
- **Batching acceptance gate — FAILED; `batch_size` is parked at 1.** Two **live,
  quota-spending** checks in `tools/score_eval.py` (no `make` target, never run from
  CI) tested whether batching N JDs into one `codex exec` call corrupts a JD's verdict
  via context bleed from its batch-mates: `--batched` (the pass/fail gate — same rows
  scored single vs. batched, PASS = identical `(seniority, domain)` verdicts) and
  `--drift-probe` (a measurement, no PASS/FAIL — re-draws known drift rows K× at one
  batch size per run, to separate bleed from ordinary draw noise). **Verdict: bleed is
  real and scales with batch size**, and it is not confined to the `domain` verdict.
  `batch_size=5` is not a safe middle ground — it can turn a correct stable verdict
  into a confidently wrong one, which is worse than a flip because it never announces
  itself. So batching does not ship at **any** size >1; the shipped default is
  `batch_size=1` (§7.1, §9, §11) and the machinery stays only so a future fix has
  something to test. The quota problem needs pacing, not a bigger batch (§11).
  Run-by-run numbers, the per-row forensics, and the corrections the probe made to the
  guard's original reasoning are in [`../CHANGELOG.md`](../CHANGELOG.md) (see the
  batched-scoring and drift-probe entries); the design rationale is in
  [`superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`](./superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md).

---

## 14. References

- **Status & open work:** [`PROGRESS.md`](./PROGRESS.md)
- **Release history:** [`../CHANGELOG.md`](../CHANGELOG.md)
- **Contributor conventions:** [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Design principles (decision DNA):** [`PRINCIPLES.md`](./PRINCIPLES.md)
- **Session protocol & definition of done:** [`DEVELOPMENT.md`](./DEVELOPMENT.md)
- **Setup front door:** [`SETUP.md`](./SETUP.md)
- **Service READMEs:** [`../apps/web`](../apps/web), [`../apps/worker/README.md`](../apps/worker/README.md)
- **Code anchors:** schema `apps/web/prisma/schema.prisma` · enums
  `apps/web/src/lib/constants.ts` · server actions `apps/web/src/lib/actions.ts` ·
  pipeline `apps/worker/ats_worker/pipeline.py` · wiring `apps/worker/ats_worker/run.py`
