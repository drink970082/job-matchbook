# Job Matchbook — System Specification

> **Authoritative source of truth for this repository.** This document describes
> the system *as it actually exists* and is written to be verified against the
> code. When code and this spec disagree, that is a bug in one of them — fix it,
> don't let them drift. New work should update this file in the same change.
>
> Companion documents: [`ARCHITECTURE.md`](./ARCHITECTURE.md) (ownership/boundaries),
> [`ROADMAP.md`](./ROADMAP.md) (product order), [`PROGRESS.md`](./PROGRESS.md)
> (branch claims and current gaps), [`BACKLOG.md`](./BACKLOG.md) (residual triage),
> [`EVALUATION.md`](./EVALUATION.md) (checks and corpus readiness),
> [`REJECTED.md`](./REJECTED.md) (turned-down proposals),
> [`../CHANGELOG.md`](../CHANGELOG.md) (release history),
> [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (conventions).

- **Project:** Job Matchbook (`job-matchbook`) — a self-hosted, semi-automated
  job-application system
- **Repo:** https://github.com/drink970082/job-matchbook
- **Version:** 1.0.0 (first public release) · **License:** MIT

---

## Product direction and implementation boundary

[The approved pivot](superpowers/specs/2026-10-22-chatgpt-first-pivot-design.md)
positions ATS as a job-source, evidence, tracking and tool layer, with ChatGPT as the
primary personal judgment/recommendation interface. **Hard-requirements screening is
supported optional assistance; the fit scorer is removed.** The opt-in JEV keep/skip
filter (`--jev`, §7.1) runs after the screen and narrows a reported approximately
200-posting daily load; MCP `list_jobs` hides its current `skip` verdicts by default.
Ranking within `keep` stays gated (#135). The offline preselection tooling
([preparation plan](superpowers/plans/2026-10-27-preselection-parallel-preparation.md))
is its provider-free foundation. Epic #152 makes MCP the main channel: the key-scoped
loopback write API (`/api/v1`, §7.2), the MCP application write tools over it (#154) and
the MCP workflow prompts (#159) are shipped; a read-only web dashboard is planned (#158). #94 still needs actual unattended evidence.

[ARCHITECTURE](ARCHITECTURE.md) separates target ownership from existing implementation;
[ROADMAP](ROADMAP.md) lists feature readiness and outstanding slices;
[EVALUATION](EVALUATION.md) scopes model checks. This specification's detailed pipeline,
UI, default-model and schema descriptions remain the shipped reference. A target feature
is not implemented merely because it appears in those planning documents.

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

Job Matchbook collects official job evidence and tracks applications in a shared
SQLite database. Its Next.js web UI, native Python worker and host stdio read-only MCP
process provide complementary access to that data. The MCP is used by an AI assistant
for research; the web app retains manual tracking and fit-oriented discovered-job views,
and serves a key-scoped loopback write API (`/api/v1`).

A worker pass fetches postings and screens them against the candidate's hard
requirements (`--fetch-only` stops before the screen), then, with `--jev`, runs the
paid JEV keep/skip filter over screened survivors. There is no fit scorer and no
notification stage; the stored fit verdicts in `score`/`score_detail` are history the web
and MCP still read.

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
2. **Discovery** is repetitive: scanning boards and retrieving JD evidence → the
   worker collects it for review and optional assistance; ChatGPT-led research can
   supply the primary personal judgment while the human controls actual submission.

---

## 3. Users and principles

- **Single, self-hosting user.** No multi-tenant accounts, no auth layer — you run
  it on your own machine against your own data.
- **Human always in the loop.** The pipeline invests *nothing* in auto-apply. It
  prepares (fetch, screen); you review and submit by hand, then
  one-click "Mark Applied" records it.
- **Privacy first.** Resume, secrets, target-company list, and the database are all
  gitignored; the repo ships only `*.example` templates so a clean clone runs
  without exposing personal data.
- **Cheap optional assistance, primary judgment in ChatGPT.** The worker supports
  multiple screen providers; no GPU is required for discovery or subscription-backed
  screening. Luna/medium is currently selected for standalone screen-only. Personal-fit
  ranking and delivery
  are not prerequisites for reading source evidence. See PRINCIPLES 4 and ROADMAP.

---

## 4. Goals and non-goals

*Class: **Contract** — code must satisfy these; disagreements are code bugs.*

**Goals**

- Track applications end-to-end with status history and visual analytics.
- Discover jobs from company ATS boards on a schedule; support explicitly selected
  screening without requiring it for discovery/MCP record access.
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
- **No mandatory model or notification service for local tracking/discovery.** Optional
  assistance and ChatGPT/MCP workflows depend on the selected services.
- **No required provider or GPU for the core tracker/discovery path.** Optional
  model stages require a supported configured backend; current adapters and defaults
  are specified in §7.1.
- **The worker issues no schema DDL** — Prisma owns the schema.

---

## 5. System overview

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

The two-phase workflow:

```
Phase 1 — Discovery & screening (apps/worker, scheduled)
  watchlist (DB) ─► fetch (9 watchlist platform adapters + custom/browser recipes) ────┐
  feed (Simplify) ─► prefilter ─► resolve URL→board ─► fetch/fetch_one (reuse) ────────┤
                    (per-listing detail sources: Oracle/Jobvite)                       │
                    (unresolvable URL → feed_unresolved backlog)                       │
            (both paths upsert job_postings, deduped on source+id) ◄──┘
            ─► screen (hard requirements; result in job_screenings)
                     [location: deterministic code gate off the board field, not the LLM]

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
entirely. The feed runs the same `prefilter_postings` over its listings' own metadata
before resolving them (§7.1 feed ingestion), but **not** the deterministic
intern/location gate: those postings gate one stage later at `screen_posting`, which
runs the identical `deterministic_screen` helper.

A posting moves through a `pipeline_status` state machine in the database
(§[9](#9-behaviors-and-invariants)). "Mark Applied" is the seam between the two
phases: it promotes a `job_postings` row into an `applications` row.

---

## 6. Architecture

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

```
            ATS boards          Ollama (host GPU)  Codex CLI/Claude
      11 platforms + custom/          │                 │
        browser recipes               │                 │
                  │                    ▼                 ▼
   ┌──────────────┴────────────────────────────────────────────────────┐
   │  apps/worker  (Python 3.11, APScheduler)                          │
   │     fetch ──► screen                                              │
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
   │  apps/web  (Next.js 14, Server Actions + /api/v1 write API)       │
   │   Discovered Jobs tab  ──"Mark Applied"──►  Applications + charts  │
   └───────────────────────────────────────────────────────────────────┘
                  ▲
                  │  you (browser): triage, apply by hand, track
```

**Process / deployment topology**

| Piece | Runs in | Talks to |
|-------|---------|----------|
| Next.js web app | `web` service (`ats-web` container) | shared SQLite (read postings, write applications); serves `/api/v1` on the same loopback port, enabled by `ATS_API_KEY_READ_WRITE` / `ATS_API_KEY_READ` in the root `.env` (§7.2) |
| fetch / screen / JEV | **host** — `python -m ats_worker.run`, not containerized | board APIs, the screen backend (host Ollama or a CLI/API provider), OpenRouter with `--jev` |
| ATS MCP (reads `mode=ro`; writes via web `/api/v1` when `ATS_API_KEY` is set) | **host** — stdio child of its dedicated tunnel-client user service | shared SQLite (`mode=ro`, `query_only`) |
| Ollama | **host** (GPU) — not containerized | — |
| SQLite db | `./db` directory, bind-mounted into the `web` container | — |

**Operator runtime:** the native worker service uses `--screen-only` with explicit
Codex `gpt-5.6-luna`, medium effort, explicit `--screen-unlimited` and one screen worker,
plus `--jev --jev-limit 300 --jev-max-usd 0.10`. Quota refresh is disabled in this mode.
It runs from a separate persistent deployment checkout with the existing private
configuration and shared database, and a dedicated tunnel serves the MCP to the AI
assistant. The `ats-web` container (compose project `ats`) is built from that same
checkout; a local, git-excluded `docker-compose.override.yml` there mounts the original
checkout's `db/` directory by absolute path, and its `.env` carries
`ATS_API_KEY_READ_WRITE`. Legacy rows keep unknown source state/revision until evidence
is observed; no source refresh or model pass is triggered by deployment. The landing page
emits React hydration errors 418/423 before recovering on the client. These deployment
choices do not change CLI defaults.

The worker is **not containerized**: Ollama's GPU pins it to the host, and the CLI
screen backends (`codex`, `claude-code`) authenticate from the operator's own CLI login —
containerizing them would mean baking the CLI into the image *and* mounting a live
subscription token into it.

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
config are all correct.

**The operator's cure is `docker compose up -d --force-recreate web`.** `docker restart
ats-web` often suffices and is cheaper, but it re-uses the bind source pinned at create
time (below), so it cannot fix the case where the host inode was replaced — prefer
`--force-recreate` when the restart does not take. Note what does *not* work at all:
`make up` will **not** recreate a running container whose config hash is unchanged, so
"just run `make up`" is a no-op here.
**The same applies to the sidecar** — if `ats-autoheal` is the thing that is broken,
`docker compose up -d --force-recreate autoheal` is its cure, for the same reason. Its
restart policy restarts it, which buys visibility rather than repair.

To make it self-healing, `web` exposes `GET /api/health`, which actually opens the DB
and **reads an application table** (`SELECT 1 FROM job_postings LIMIT 1` → `200`, else
`503`), wired to a Docker `healthcheck`; the `autoheal`
sidecar (watches the `autoheal=true` label via the mounted Docker socket) restarts
any container Docker marks **unhealthy**. **No compose mechanism acts on `unhealthy`** —
`restart:` fires on container *exit* only, and `depends_on: service_healthy` is a startup
gate that would be actively harmful here (it would hold the sidecar down exactly when web
is the thing needing repair). The sidecar is the only thing that closes that loop.

**Does a restart re-resolve the bind mount? On this host, NO — measured 2026-07-28.**
Docker Desktop on WSL2 pins a bind source through a create-time hashed path under
`/run/desktop/mnt/host/wsl/docker-desktop-bind-mounts/`. With a directory bind of the
same shape as `./db`, replacing the source directory on the host and then
`docker restart`ing showed the **old** contents, while a freshly *created* container on
the same path showed the new ones. So restart re-uses the pinned source; only
re-**creation** picks up a different inode. (This may well differ on native Linux Docker,
which mounts at start — do not generalize this line beyond WSL2.)

**What that does and does not say about the stale-mount cure.** The two failure modes are
different: the measurement above is *the source inode was replaced*, whereas the WSL2
symptom is *the same inode, a broken view*. A restart re-establishes the container's mount
namespace and is a plausible cure for the second; it is proven not to be a cure for the
first — and if the source path is gone entirely the restart cannot even start the
container. The recovery leg was drilled 2026-07-22 (autoheal does restart a labeled unhealthy
container), so "autoheal restarting `ats-web`
cures a stale mount" remains **reasonable and unproven**, not established. Prefer
`docker compose up -d --force-recreate web`, which works in both cases.

**What the probe can and cannot detect — MEASURED 2026-07-29**, against a throwaway copy of
the live DB: three candidate probe bodies x four filesystem failures. This replaced a
reasoned argument that turned out to be wrong, and the table is why the probe names an
application table.

| failure mode | `SELECT 1` | `sqlite_master` read | `job_postings` read |
|---|---|---|---|
| rename the DB's directory **after** connect | 200 | 200 | 200 |
| delete the DB file **after** connect | 200 | 200 | 200 |
| rename the DB's directory **before** connect | 503 | 503 | 503 |
| delete the DB file **before** connect | **200** | **200** | **503** |

Three things follow, and the first two contradict what this document previously claimed.
(1) **`SELECT 1` and a `sqlite_master` read are indistinguishable** in every mode. The
"a constant expression is answered without a page read" argument is true about SQLite and
irrelevant here: once the connection is open, *both* read through the same already-open fd.
(2) **Nothing detects a break that happens after connect**, for that same reason — POSIX
keeps the inode reachable through a live descriptor. Accepted, not fixable by a probe; a
restart re-opens. It is also why the earlier `chmod 000` drill left the live probe at 200
for five minutes, and why `chmod` was rejected as a proxy.
(3) **A missing DB file is the mode that discriminates, and it is the dangerous one:**
SQLite silently **creates an empty database**, so the two weaker probes report healthy
forever against a tracker holding no data. Naming a real table turns that into `no such
table: job_postings` → 503 → autoheal restarts. The cost is that a checkout whose schema was
never pushed reports unhealthy — correct, since that web container genuinely cannot serve.

**Guarding the guard.** The sidecar's health check is not the image's
`pgrep -f autoheal` — a check that **cannot fail while the container runs**, because
`Cmd=["autoheal"]` puts that string in the process's own argv and the check matches
itself. It is a socket **ping** (`curl --unix-socket … /_ping`), which
asks the question that matters: can this sidecar still reach the Docker API. Measured in a
socket-less container held up artificially, with a faster interval than shipped:
socket-ping reached `unhealthy`, `pgrep` reported healthy throughout. At the shipped 30s
interval a real socket-less sidecar usually exits before three probes can fail, so what
`make health` sees is `starting` — which it also fails on. The ping is what makes the
signal real; the timing is what makes it visible.

**No watchdog, and that is a deliberate reversal.** An entrypoint wrapper that exits when
the socket dies was built and drilled, and then removed, because two measurements killed
it. (1) The image's `/docker-entrypoint` already runs under `set -e -o pipefail`, so a
failed Docker API call exits the script: with the socket killed under a live sidecar the
**stock** image went `Exited (7)` and `restart: unless-stopped` climbed to 8 restarts
unaided — the "live sidecar doing nothing forever" state the wrapper targeted does not
exist. (2) The wrapper *created* a worse one: as PID 1 it survives its child, so killing
the autoheal loop left the container `Up (healthy)` with `RestartCount 0` and no autoheal
running, indefinitely. Details in PROGRESS.

**`make health`** (invoked by `make up`) polls both containers for `healthy`, treats a
missing healthcheck as failure, and waits out web's 40s `start_period`.

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
| External | — | Ollama HTTP (default screen), Codex/Claude CLI subprocesses, Anthropic/OpenAI APIs (metered screen backends) |
| Tests | Jest + Testing Library + jest-mock-extended; Playwright e2e | pytest (fully mocked) |
| Container | Alpine multi-stage, non-root | — (native on the host, not containerized) |

---

## 7. Component specifications

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

Each unit below lists *what it does · inputs/outputs · what it depends on*. The
worker modules are pure and dependency-injected; real services are wired only in
`run.py` (`ats_worker/`).

### 7.1 Worker (`apps/worker/ats_worker/`)

- **`run.py` — entrypoint & wiring.** CLI: `--once` (single pass then exit) vs the
  daemon, which fires on **wall-clock slots** — `cron_hours(h)` renders
  `range(0, 24, h)` into APScheduler's `hour=` string (`4` -> `0,4,8,12,16,20`), so
  passes land at 00:00/04:00/08:00 regardless of when the daemon started and a restart
  cannot re-phase the day. **The daemon runs NO pass at launch**; `--run-now` restores
  that on demand and is rejected together with `--once`. A pass is fetch -> feed ->
  expire -> standalone hard-requirements screen (`pipeline.run_screen`). Flags:
  `--config`, `--env`, `--db` (`DB_PATH`, default `../web/prisma/applications.db`),
  `--model` (`OLLAMA_MODEL`, the Ollama model tag — only consulted when
  `--screen-backend ollama`), `--screen-backend` (`SCREEN_BACKEND`, one of six values —
  documented under `screening/` below), `--screen-model` (`SCREEN_MODEL`, overrides the
  chosen backend's default model; Codex defaults to `gpt-5.6-luna`, and on `claude-code`
  the default is the CLI's own), `--screen-effort` (`SCREEN_EFFORT`, Codex reasoning
  effort, default `medium`), `--screen-limit N` (positive provider-call cap per pass,
  default 40 or `SCREEN_LIMIT`), `--screen-unlimited` (explicitly remove that cap; the
  provider breaker and successful-result cache stay active), `--screen-workers`
  (default 1), `--rescreen-screened` (clear successful screen cache for eligible `new`
  rows before a one-shot pass; requires `--once`), `--fetch-only` (run fetch/feed/expire
  then stop before any screen call — a quota-free board refresh), `--screen-only`
  (accepted no-op alias for the default pass, kept for existing service files; the
  retired fit flags `--score-*`, `--batch-size`, `--no-notify`, `--rescreen-discarded`
  and `--resume-dir` are likewise accepted and ignored with a warning),
  `--refresh-unscored --refresh-source smartrecruiters --refresh-limit N` (standalone,
  source-only refresh of eligible existing unscored rows; requires `--once`, an explicit
  adapter, and a limit from 1 through 25; runs no intake or screening), and
  `--import-companies` (seed the DB watchlist from config and exit). `--fetch-only`,
  `--screen-only` and `--refresh-unscored` are mutually exclusive; invalid combinations
  and a non-positive screen cap fail before config load or DB work, both in the CLI and
  in direct `run_once` calls. Each pass **auto-seeds** `watched_companies` from
  `config.companies` when the table is empty and reads the watchlist from the DB (not
  config). The only module that knows about secrets/external services — and the only
  place the real network callables are bound: `pipeline.run_fetch`/`run_feed`'s
  `fetch_fn`/`detail_fetch_fn` and `screening.screen_posting`'s `http` all default to
  `None` in their pure modules, and `run.py` supplies `fetch_company`,
  `fetch_one_company`, and the screen's `http=requests` explicitly at each call site.
  **One pass at a time per database:** every pass (scheduled or `--once`) runs inside
  `pass_lock` — a non-blocking `fcntl.flock` on `<resolved --db>.pass.lock`, taken per
  *pass*, not for the process lifetime, and keyed on the `resolve()`d DB path so a
  relative `--db`, an absolute one and a symlinked checkout all land on one file. A pass
  that cannot take it runs nothing: `--once` exits non-zero naming the holder's pid, a
  scheduled firing skips that slot and stays scheduled (§9). An **unwritable** lock file
  (the root-owned leftover of one `sudo` run) degrades to an `O_RDONLY` hold rather than
  failing — `flock` needs no write access, so the guard stays exclusive and only the pid
  record is lost, which both sides announce. Other open failures (an unwritable DB
  directory, a file this user simply cannot read) still fail loud. The worker reads no
  résumé or profile file.
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
  carries any listed keyword **as a whole word**, the complement of `title_filter`;
  note the deliberate asymmetry — the keep-list is substring, this is not), `max_age_days`
  (fetch-time freshness gate — drop a posting whose `posted_at` is older than N days;
  `0`/omitted = off; a null/unparseable `posted_at` is always kept), `candidate` (with
  `is_empty()`), `feeds`, `schedule_hours` (hours between wall-clock passes; must be a
  **divisor of 24** — `1, 2, 3, 4, 6, 8, 12, 24` — and `config.py` raises `ConfigError`
  otherwise, with a separate message for `0`/negative. Two failure modes justify the
  bound: a non-divisor leaves a `24 % h` gap across midnight that is always *tighter*
  than the configured cadence, and anything above 24 collapses to a single `hour=0`, so
  `schedule_hours: 48` would silently become daily — twice the paid spend from an
  unedited file). Bad
  source / missing field → clear
  startup error. `feeds` is an optional mapping of feed-name → settings (only
  `simplify` is valid in v1: `enabled`, `categories` keep-list, optional `url`);
  `companies` is now consumed only by the one-time watchlist import (see `run.py`).
  A top-level `fit_profile` block (the retired fit scorer's vocabulary) is accepted and
  ignored, so an existing `config.yaml` still loads.
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
    — the fetch-time coarse pre-filter **both** ingestion paths run (deterministic, no
    LLM): the positive `title_filter` keep-list above, a negative `title_exclude`
    drop, and a `max_age_days` freshness drop (a
    parsed `posted_at` older than N days is dropped; `0`/omitted `max_age_days` and a
    null/unparseable `posted_at` both keep the posting — err toward keep).
  - `exclude_matcher(title_exclude)` — the compiled **whole-word** matcher
    `prefilter_postings` applies to `title_exclude`, or `None` for an empty list. The
    asymmetry against `filter_postings`' substring rule is measured, not stylistic
    (11,675 titles, 2026-08-02): the keep-list *needs* substring as a stemmer — `quant`
    reaches 436 titles where a word match reaches 40, and the 396 "Quantitative …" rows
    it would lose are the product — while the exclude list needs precision, since a
    substring `intern` also drops "Internal Compute Frameworks (Python)" and an
    over-reaching exclude is invisible (the posting it ate never surfaces). Word
    matching is also what makes short keys usable at all: `sr` as a substring hits SRAM
    and SRE, `ios` hits BIOS and Biosciences. Consequence for operators: keys no longer
    stem, so `intern` and `internship` are both required. Uses lookarounds rather than
    `\b` so a key ending in punctuation (`co-op`, `ai/ml`) still matches.

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
  | iCIMS | `{slug}.icims.com` | list (server HTML) + per-job detail | no | yes |
  | Phenom | `{host}` (e.g. `apply.careers.microsoft.com`) | list + per-job detail | no | yes |
  | Custom (recipe) | any (recipe-driven) | list (`json`/`next-data`) + optional per-job `detail` | no | yes (needs `recipe`) |
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
  `phenom` is also the one adapter with **throttle handling** — it is the only board that
  has ever rate-limited (`careers.qualcomm.com` at `start=930`, 2026-07-22). **A 403 is
  treated as a throttle too, from 2026-07-31**: that board fails every live pass with a
  403 deep in pagination at a *varying* offset (`start=990`/`1060`/`1220`), and those
  exact offsets return **200** when probed cold from a fresh session — so it is a WAF
  tripping on the pass's cumulative request volume, not a missing page. A 403 on the
  FIRST page still raises (nothing to salvage; a board refusing from the start is a
  block, not a throttle). The salvage **announces the truncation** — it was silent, and a
  board cut short at 990 of 1,896 positions otherwise reads as a complete one. Its search
  GET retries the same offset up to 3 times (2s → 4s → 8s, honoring a delta-seconds
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
  `max_age_days` also gates a workday stub: `parse_stub` dates the stub's relative prose
  ("Posted N+ Days Ago") against the injected `now` (`now - age`, treating the number as
  a lower bound), so a stale stub is dropped before its detail GET. Only the confident
  English "N[+] Days Ago" form parses — "Today"/"Yesterday" and any other locale or
  wording leave `posted_at` None (kept), so a mis-parse never drops a good posting. `now`
  reaches the adapter through the same `keep`-gate call path.
  **iCIMS is the third stub-gated adapter.** Its search card's `div.description` is a
  teaser and on some tenants absent entirely, so the JD comes from the job's own page
  (`{job_url}?in_iframe=1` -> `div.iCIMS_JobContent`) through the shared detail stage. That
  is a PLATFORM fact, true of every iCIMS tenant, so it lives in the adapter exactly as
  `position_details` lives in phenom's — never in a per-board recipe. The card already
  carries id, title and location, so a `drop`/`discard` verdict is decidable from the stub
  and, unlike workday's GUID-less stub, costs no dedup key — both verdicts are honoured.
  Measured: SIG 561 -> 3,835, GTS 537 -> 3,987, MSCI **0 -> 7,032** median chars.
  **Custom (recipe) executor** (`fetch/custom.py`): a generic, declarative fetcher — the board's
  `recipe` (a JSON object stored on the watchlist row) names the `url`, `method` (GET/POST),
  `mode` (`json`, or `next-data` = extract the `__NEXT_DATA__` blob then treat as JSON),
  `item_path`/`total_path` (`item_path` optional — omit it when the payload is already the job
  array, i.e. a bare root-level JSON feed like Jane Street), `page` (`offset`/`page`/`none`), and a
  `fields` map (dotted paths, `url` templates, list-concat descriptions) into the canonical dict via
  the shared `fetch/_recipe.py` helpers. One executor covers many boards (Amazon, ByteDance/TikTok,
  DE Shaw, Jane Street, …) with **no per-site code** — adding one stays a data row. Anything a recipe can't express is a
  `browser` recipe, never a hand-written adapter.
  An optional **`detail` block** hydrates a board whose list call carries only a teaser: `url`
  (a `{field}` template interpolated against the **raw** item, not the canonical posting — the id a
  detail endpoint keys on is often not the one mapped to `external_id`) or `url_field` (reuse the
  posting's own `job_url`), `mode` (`http-json` default, or `http-html`), and a `fields` map read by
  the same `_recipe.py` helpers. Apple and Oracle hydrate this way; IBM needs no `detail` at all,
  because its full `body` was already in the list response and only wanted mapping.
  **Shared detail stage** (`fetch/_detail.py`): one hydration skeleton the recipe executors and
  detail-capable adapters share, with the per-board parts injected — sibling of `fetch/_paged.py`.
  Two properties it exists to enforce. **The detail transport is independent of the list
  transport**, so a board can need a browser to enumerate and plain HTTP to hydrate; the caller
  supplies `fetch_doc` and the stage never assumes which it got (a `dict` document is read with
  dotted paths, anything else as a bs4 node with CSS selectors — neither extractor is
  reimplemented, `_recipe.py` owns both). **The circuit breaker is per BOARD, not per posting**: a
  bot wall or a dead detail endpoint fails identically for every posting, so N consecutive calls
  that win no new description stop the board and say so. "Did this call earn more description?" is
  the health signal rather than the HTTP status, because a Cloudflare interstitial is a 200 with a
  parseable body. Detail URLs are `is_safe_public_url`-checked before the request — they are
  scraped from third-party listing HTML (§11).
  A `browser` recipe's `detail` block may declare `mode: http-html` / `http-json`, in which case
  hydration goes over plain `requests` and Chromium is used only to **enumerate** — the common
  shape where the listing is a JS app but each job page is server-rendered (Google: 817 rows,
  452 -> 1,821 median chars, one cheap GET each instead of a ~15s render).
  `custom` and `browser` are both stub-gated, so a detail call is spent only on postings that
  survive the free title/exclude/age gates.
  The browser transport is **stealth-patched at context creation** when the optional
  `playwright-stealth` extra is installed — `Stealth().use_sync(sync_playwright())`, never the
  per-page `apply_stealth_sync(page)`, which silently under-patches (six measured arms failed on
  it). Placement is the whole fix, and it is what makes a Cloudflare-walled board's DETAIL pages
  reachable at all: Citadel goes from a "Just a moment" interstitial on every detail navigation to
  10/10 full JDs (median 3,432 / 2,878 chars across the two rows). It is a property of the
  transport, not of a board — no per-row flag — and absent the extra the un-patched context is
  used, so the core install and the no-network test gate stay Chromium-free.
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
- **`review_batch.py` / `review_batch_cli.py` — offline fixed-batch preparation.** Consume
  only an explicitly marked synthetic pool, injected cutoff/resume window and complete
  caller policy. The pure engine filters confirmed applications/manual terminal actions
  and confirmed source closure, routes unknown/stale evidence to unresolved work, groups
  exact and explicitly corroborated identities before exclusions, and freezes a
  ranked/audit/unresolved batch. Confirmed application/manual evidence follows the
  identity group; mixed source closure is unresolved with per-source evidence. Requisition
  application matching requires the source scope, while an unscoped requisition match is
  visibly ambiguous. Stable posting occurrences are unique before audit sampling. Batch
  and cursor identity includes the injected clock, complete candidate/application inputs,
  merged-member versions and final order. Revalidation preserves cumulative invalidation
  and replacement history, meters analysis/scans/search against cumulative work caps, and
  suppresses any slot that cannot be checked within work/time limits. Its named
  age-service/role-coverage/audit recipe is synthetic, not the operator's production
  policy. The CLI requires an explicit fixture and local state path; it opens no database,
  profile, config, provider or runtime. Read/delivery and downstream resource cost remain
  unknown without acknowledgements.
- **`db.py` — SQLite layer.** WAL pragmas + `busy_timeout`; `upsert_postings`
  (dedup on `(source, external_id)`; persists `company_slug`; new complete source
  records start at content revision 1, while repeated exact identities update only
  source availability/last-seen time), `get_unscored_refresh_candidates` (known
  unscored states, no fit assessment or application link, oldest attempted first),
  `save_source_observation` (transactionally rechecks eligibility and exact identity;
  records inconclusive/closed/available outcomes; changes assessment inputs only after
  validation), `get_by_status` (selects rows by pipeline status, best-scored first),
  `mark_expired`, `touch`. Watchlist + feed
  helpers: `get_watchlist` (skips a `custom`/`browser` row with malformed recipe JSON,
  but keeps a platform-source row — it fetches without a recipe), `count_watchlist`,
  `import_watchlist` (idempotent), `record_unresolved` (upsert on `url`),
  `delete_unresolved` (clears a row once its posting is re-ingested),
  `existing_external_ids`. Standalone screening selects fresh eligible rows using the
  existing queue order: undemoted rows first, then recency and descending id within each
  priority group. Provider errors follow oldest-attempt-first; successful results stay cached until an
  explicit one-shot re-screen, and `save_screening` re-checks eligibility inside a
  transaction before writing. Issues no DDL.
- **`screening/` — the hard-requirements screen.** The provider-neutral package owns
  the hard-requirement engine, screen schema/rendering, location resolver, and screen
  transports. There is no fit scorer. Subscription quota telemetry is the neutral
  `ats_worker.usage` (§7.2's quota bar reads its snapshot); seniority is JEV's
  `required_yoe_for_candidate` question.

  (1) The hard-requirements **SCREEN** is injected as one seam — `extract(prompt,
  schema) -> dict` (`screen_posting`'s `extract` kwarg) — so swapping backends is a
  new callable, never a new branch inside `screen_posting`. `run.make_screener(backend,
  *, env, http=None, model=None, screen_model=None, screen_effort=None,
  num_ctx=8192)` builds that
  callable from **`SCREEN_BACKEND`/`--screen-backend`**, one of **six** values in
  **three** adapter shapes (`screening/backends.py`):
  - **HTTP + JSON schema** — `ollama` (**default**; free, local,
    `screening.make_ollama_extract`, `think: false`, `num_ctx` from
    `OLLAMA_NUM_CTX`/`--model`, default model `qwen3.5:4b`), `claude-api` (metered,
    the Anthropic SDK's structured outputs, default `claude-haiku-4-5`, needs
    `ANTHROPIC_API_KEY`), `openai-api` (metered, plain `requests` against
    `chat/completions` with `response_format: json_schema`, default `gpt-5.6-luna`,
    needs `OPENAI_API_KEY`).
  - **CLI subprocess + schema** — `codex` (the operator's ChatGPT-subscription CLI,
    default `gpt-5.6-sol`; runs **tool-less** — `--disable shell_tool`,
    `web_search="disabled"`, since a JD is untrusted scraped text; the schema goes in as a **file**,
    `--output-schema`; an explicit `screen_effort` is forwarded as
    `model_reasoning_effort`), `claude-code` (the operator's Claude Code CLI subscription;
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

  **The code-side gates run BEFORE the model call and short-circuit it** (changed
  2026-07-31). `screen_posting` applies `deterministic_screen` (intern title +
  location string) first and returns immediately when it disqualifies, so a row those
  gates kill never costs a backend round trip — 37% of the live `new` queue on
  2026-07-31. The verdict is unchanged (the gates' answer was already terminal
  whatever the model said); what is given up is the model's degree/authorization/
  clearance detail on a row that is being discarded anyway, the same trade `run_fetch`
  makes when it drops bodyless rows before any call. Two consequences worth naming: a
  deterministically-killed row no longer carries `provider_error` (nothing was
  attempted), and a reason string no longer joins a model-derived reason to a
  deterministic one — which the web's Discarded-bucket cause facet reads
  (`DISQUALIFY_CAUSE_PATTERNS` in `apps/web/src/lib/actions.ts` matches
  `disqualification_reason LIKE '%degree:%'` and friends), so a row failing location
  *and* degree now appears under `location` only.

  `--screen-model`/`SCREEN_MODEL` overrides whichever backend's default model.
  **Auto-detection never selects a paid backend** — the default is always `ollama`
  and `make_screener` never guesses from what happens to be installed; spending
  money is explicit opt-in via `SCREEN_BACKEND` (`make doctor` reports what is
  actually available, and the operator — or `onboard-me` Step 0 — chooses from
  that). `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` are read from the in-process `env`
  dict only, never promoted to an argparse default (§12).

  **Screen lifecycle.** `pipeline.run_screen` applies `screen_posting` and the
  deterministic hard-requirement rules. It stores one latest result per posting in `job_screenings`,
  leaving `job_postings.pipeline_status`, fit `score`/`score_detail`, score attempts,
  notification attempts and application links untouched. Successful results are reused
  until `--rescreen-screened --once` explicitly clears them for eligible
  `new` postings. Provider errors remain retryable and are selected oldest-attempt-first
  after fresh rows, under the configured positive per-pass provider-call cap (default
  40), or without a call-count cap when `--screen-unlimited` is explicit. The existing
  circuit-breaker policy remains active in either mode; there is no per-row retry budget or automatic input-hash
  invalidation. Deterministic-only outcomes do not spend provider-call capacity and are
  still processed after the cap. A provider error stores only a closed safe category and
  fixed summary, never raw exception text. A per-result transaction re-checks that the
  posting is still `new`; a provider call interrupted before commit can be repeated on
  a later pass (at-least-once external execution).

  **JEV keep/skip filter** (`jev.py`, `pipeline.run_jev`, opt-in `--jev`). After the
  screen, each screened, not-disqualified `new` posting gets two native OpenRouter JEV
  calls (`typesafe/jev-1.13`): the preference question pack with the approved profile,
  and a one-question required-experience pack with education/experience facts only. The
  verdict is `skip` when preference is `weak` or the applicable mandatory experience
  floor is `three_plus` years (the route matching the candidate's degree; ranges use
  the lower bound); everything else, including `unknown`, is `keep`. One latest row per
  posting lives in `job_jev_assessments`; `pipeline_status` and screen state are never
  touched. A row is re-queued when the policy hash (profile, both packs, the
  experience context, the resolved model, the rule version) or the posting's source
  revision changes; provider errors retry oldest-first after fresh work. A pass is
  sequential with no in-pass retries, capped by `--jev-limit` (default 300) and
  `--jev-max-usd` (default 0.10, settled charges including partial failures, checked
  before each posting, so a pass can exceed it by one posting's two calls). An unknown
  charge (missing/negative/non-finite cost, BYOK, or any transport failure other than a
  connect timeout) stops the
  pass; a dead backend trips the shared breaker. A request over 32,768 bytes is never
  sent, is stored as `request_too_large`, and is not retried until its source or policy
  changes. Each pass records its policy hash in `app_settings`
  (`jev_current_policy_sha256`) so MCP can label older verdicts stale. Without
  `OPENROUTER_API_KEY` or model metadata the stage is skipped with a log line; fetch and
  screen have already run. Inputs are four private files under config `jev_dir`
  (`config.yaml.example`). Measured basis (2026-11, model-proxy, not human truth):
  preference skips 57-69% of screened candidates per day with 0 of 7 real applications
  skipped; the experience question agreed with a blind review on 50 of 52; together they
  leave about a quarter of screened candidates. Ranking within `keep` was measured and
  rejected (it tied publication-time order).

  **Import boundary.** No fit module exists to import, and no résumé is loaded.
  Provider-free review-batch, rehearsal, profile, and replay imports are guarded in fresh
  processes: legacy fit/profile/runtime module names and `.txt` resource reads fail
  immediately.

  Each standalone result's persistence timestamp is sampled after its provider call on
  the DB thread through the clock injected by `run.py`. This records when the worker is
  ready to save the result, not an exact transaction commit time; existing rows are not
  backfilled.

  Whichever backend is picked, the call only fires when a non-empty `candidate` is
  supplied, and — with **no résumé in the prompt** — extracts each requirement
  (degree, work authorization, clearance) as a JOB fact *semantically*.
  CODE then decides pass/fail — on every backend, not just the free 4B `ollama`
  default that motivated it (a small local model is unreliable at the pass/fail
  judgment itself, and keeping it code-side means the check behaves the same
  regardless of which backend did the extracting): for **degree** by taking the LOWEST
  of the levels the model listed and comparing that rank (see the degree paragraph
  below); for clearance by applying the candidate's configured constraint to the
  extracted fact; for **work
  authorization by RETRIEVE-THEN-CLASSIFY** (`sponsorship_snippets` /
  `_check_authorization`) — CODE pulls every sentence naming `sponsor` plus one
  neighbour each side, the prompt numbers them, the MODEL returns one label per snippet
  (`refuses` / `offers` / `neither`), and CODE decides: any `offers` keeps, else any
  `refuses` discards, else keep.

  **Hallucination is structurally impossible rather than checked for.** The model
  labels text the code handed it and never supplies text, so there is no channel for
  invented evidence to reach the decision. That is strictly stronger than the
  `_quote_in` verification it replaces (retired 2026-07-28 along with
  `_quote_on_topic`, `_OFF_TOPIC_QUOTE` and `AUTHORIZATION_TERMS`), and free rather
  than a second step. It also retires the "anticipate every innocent English sentence"
  problem: an EEO line is simply `neither` to a classifier.

  **Why this way round.** The previous design had the halves swapped — the MODEL did
  retrieval (read 16K chars, find the sentence, copy it verbatim) and CODE did
  classification (three regex vetoes deciding whether that sentence was a refusal).
  Retrieval on a keyword is trivially deterministic; regexes are bad at stance. Three
  rounds of whack-a-mole, PR #22's five false positives, and the screen eval's 8-of-16
  sponsorship recall — on rows whose refusal sentence was *inside the text handed to the
  model* — were all measuring that mismatch. **Measured effect (`make eval-screen`,
  2026-07-28): sponsorship false disqualifications 2 → 0 over all 21 corpus rows**,
  closing the IMC 465/490 residuals open since 2026-07-25.

  **Window: one snippet per `sponsor` sentence, +/-1 neighbour, NOT merged.** A bare
  sentence loses its antecedent ("Sponsorship is not among them."); "paragraph" is
  unbounded and degenerates to the whole JD on exactly the postings where scoping would
  help. Adjacent hits are **not** merged and may repeat a shared neighbour: the label is
  about the CENTRE sentence, and merging forces one answer for two. Live rows 465/490 are
  the proof — one IMC paragraph refuses sponsorship for three named nationalities *and*
  offers it to Ukrainian applicants, and merged it could only return `refuses`.

  **Two regex vetoes survive, DEMOTED to keep-direction only** (`_not_really_a_refusal`):
  a `refuses` label on a snippet that plainly OFFERS (`_OFFERS_SPONSORSHIP`) or that is
  only a PREFERENCE (`_PREFERENCE_ONLY`) is overruled. Neither can create a
  disqualification. The design expected a classifier to make all three old vetoes
  unnecessary; two did, and `_PREFERENCE_ONLY` did not — the 4B labelled *"prioritizing
  applicants who … do not require sponsorship of a visa"* as `refuses` on 3 live TikTok
  rows, all three draws. Measured, not assumed.

  **Every uncertainty resolves toward KEEP**, because a discarded row is reviewed by
  nobody while a miss reaches the human. A label count that
  does not match the snippet count means the model answered a different question, so the
  check is dropped — and crucially it does **not** fall through to the floor. That path
  is where both IMC false positives came from: the 4B returned one label for three
  snippets, and `NO_SPONSOR_PHRASES` then matched `without sponsorship` inside *"or are
  eligible to work without sponsorship, we encourage you to apply"*. **Silence still
  reaches the floor; a bad count does not** — and `[]` is a bad count, not silence,
  whenever a snippet was retrieved: `sponsorship_labels` is `["array", "null"]` in the
  schema, so an empty *array* is a model answer while `null` is the absence of one.
  "Answered" is therefore `bool(labels) or isinstance(raw, list)` — a **type** test, not
  a was-a-question-asked test. With nothing retrieved there was no question, so `[]` is
  the correct empty answer and the floor is the whole verdict.
  **A BLIND response is a provider failure, not a verdict.** A live backend that returns
  nothing usable — not a dict, or a dict carrying neither a `screen` object nor any
  requirement key — is flagged `provider_error` — the row is
  left `new`, the floor is skipped, and the breaker counts a failure. Without that,
  degree and clearance suppress themselves on absent data and the floor is the *only*
  surviving check: a blunt substring scan disqualifying on a JD the model never
  condemned, while the pass records a breaker **success**, so the degraded backend
  never trips it and walks the whole backlog. Realistic trigger is a wrong `--model` tag or a non-instruct model: `_post`
  only checks that a dict came back and no hosted backend validates shape either.
  **Two response shapes are accepted, and the second is not hypothetical.** `verdict_block`
  reads `{"screen": {...}}` *and* the flat `{"degree": {...}, "clearance": {...}}` the local
  4B emits about 1 call in 100 — a complete, correct verdict with the wrapper missing.
  Reading it as silence threw that verdict away, and once a blind response became a
  `provider_error` it aborted `make eval-screen` on the first occurrence (observed
  2026-07-29). The **same** function supplies both the blind check and `_screen_verdict`'s
  reader, so the two cannot drift apart about what "usable" means.
  **The scope is narrow, and the residual is deliberate:** `sponsorship_labels: null`,
  `[]`, a missing key and an empty `screen` dict are all *answers* and still reach the
  floor, so a JD that says *"we do not sponsor work visas"* is caught with no model data.
  The floor is an independent deterministic signal by design (four tests pin it, all
  handing back a well-formed `screen` dict).
  **The floor is also skipped outright on a `provider_error`**, leaving `authorization`
  absent rather than recording a verdict. It is deterministic but blunt — a substring
  scan of the whole description — and on a working backend the model's labels overrule
  it while on a dead one nothing does, so running it during an outage discards precisely
  the postings this design keeps. `run_screen` stores a `provider_error` result as
  retryable, so the next pass screens the row properly.

  **The retrieval vocabulary is `sponsor` alone, and the cost is stated rather than
  hidden.** Every false positive ever recorded on this path came from a word that is not
  "sponsor" — `citizen` (EEO boilerplate, "a good citizen in our monorepo"), `visa` (the
  payment network), `authoriz` (OAuth/RBAC), `right to work` ("…in an environment
  where"). The narrowing gives up the bars that never say "sponsor": 7 of the 13
  must-flag sentences in `tests/fixtures/sponsorship_quotes.json` are no longer
  retrieved and become MISSES. `test_the_narrowed_vocabulary_names_exactly_which_bars_it_gives_up`
  pins that count in both directions so the trade cannot drift silently. The 72-of-156
  authorization discards with no `sponsor` token looked like bars this would lose; they
  are historical damage predating the 2026-07-25 relevance gate, and the genuine ones
  among them are foreign on-site roles `resolve_location` rejects independently.

  **`NO_SPONSOR_PHRASES` is the floor for SILENCE only** — `SCREEN_BACKEND=none`
  or a provider error. It can only *add* a
  disqualification, never veto a model pass. And `authorization` **always records a
  verdict** when the candidate configured it, even when nothing was retrieved and no
  clause was asked and no LLM call was made.

  **The vocabulary is measured, not guessed** (applies to the veto patterns too)
  — a round of speculative terms (`opt `, `cpt `, `e-3`, `us person`) each collided with
  common boilerplate and was reverted, because on a disqualification path a collision
  costs a real job. Add a term only with a must-flag sentence that needs it and must-keep
  still green.

  `candidate.work_authorization` is a **closed vocabulary** validated at config load
  (`citizen` | `permanent resident` | `authorized-no-sponsorship` | `needs visa
  sponsorship`, case-insensitive; blank = don't screen on it). It has to be closed
  because `_needs_sponsorship` reads the value by substring — an off-vocabulary string
  like `F-1 OPT` would read as "needs no sponsorship" and silently disable the whole
  authorization check, so `config.py` raises `ConfigError` instead.
  `disqualified` is derived from those per-requirement verdicts, and a check the model
  returned **no data** for records no verdict at all rather than a pass — `degree` and
  `clearance` only materialize their key when the extraction carried a recognized
  **value**, so a ran-but-blind check stays distinguishable from a genuinely cleared one.
  The test is the value, never the entry dict: under a strict schema the model must emit
  every key, so `{"degree_levels": null, "degree_required": null}` is a non-empty dict
  that says nothing. And it enumerates the **recognized** values (`_degree_extracted`
  wants a real bool for `degree_required`, plus at least one level `_degree_stated`
  recognizes whenever it says a degree *is* required; clearance must be an actual `bool`)
  rather than the no-data spellings — that set is open-ended ("unknown", "not stated",
  "TBD", "unclear", …) and cannot be closed, so listing it would let a shrug through as a
  pass. `none` counts as data, and `degree_required: false` needs no levels at all — "no
  degree required" is a real answer.
  (`authorization` always records, even when nothing was retrieved and no clause was
  asked — see the sponsorship paragraph below for why that key must never be absent.)

  **Degree is an EXTRACTION plus arithmetic, not a model judgment.** The model returns
  `degree_levels` — *every* level the posting names as acceptable — and `degree_required`,
  a bool separating a hard condition from a preference; CODE takes `min(rank)` and
  compares it to `highest_degree`, and `degree_required: false` is no bar at all.
  It used to ask for one `required_degree`, "the MINIMUM", which is a judgment: `make
  eval-screen` measured the 4B answering it wrong on **9 of 38 live discards**, reading
  *"PhD, or Master's degree"* and *"PhD strongly preferred"* as a hard PhD bar with all
  three draws agreeing. Listing what a posting says is extraction; picking the smallest
  number out of the list is arithmetic. **Measured effect: 9 false disqualifications → 3,
  recall 27/37 → 28/37** — the direction that matters improved without paying recall for
  it. Two rounds of pure prompt rewording had reached 4 and 5 and stopped converging.
  **Residual, and it is a 4B limit rather than a wording gap** (`[SCREEN · XS]`): 2-3
  rows still fire, all of them a soft or preferred degree bar read as hard, where
  `degree_required` comes back `true`. Ids 67/68 (*"DESIRABLE CANDIDATES: Ph.D.
  candidates"*, one JD shape twice) fire in every run observed; a third row joins them in
  some runs and not others — *"PhD or equivalent industry experience"* (id 738) or
  *"advanced degree … (preferably a Ph.D.)"* (id 672). **The exact count is not
  reproducible and must not be treated as a diffable number:** two back-to-back runs on
  2026-07-28 gave 3 then 2 on identical code, and the screen calls Ollama at
  `temperature: 0, seed: 0`, so the variance is in the runtime rather than in sampling
  (`flip` is 0 in both — all three draws agree *within* a run). On genuine sole-PhD roles
  the same model sometimes *invents* a `master's` level, so it is unreliable in both
  directions; the honest fix for the remainder is routing a degree fail to the strong
  model rather than a fifth prompt rewrite (see PROGRESS).
  `_check_degree` also reads the older single `required_degree` shape.

  **Clearance carries an EVIDENCE FLOOR, the same shape D1 gave sponsorship.**
  `_check_clearance` honours `requires_clearance: true` only when `CLEARANCE_TOKENS`
  (`clearance` · `top secret` · `secret` · `ts/sci` · `polygraph`, case-insensitive)
  matches the JD **description or the job title** — evidence the code can see, not the
  model's say-so. Measured 2026-07-27 over 24 live clearance discards: **20 were wrong**,
  every one of them containing "security" (the engineering domain — "Senior Security
  Researcher", "Azure security") and **no** clearance token, while all 4 true positives
  carried an explicit *"Other Requirements: Security Clearance Requirements:"* block. The
  token list is the measured one and stays that way: widening it re-opens the
  false-discard direction, which is why bare `sci` (matches "science"/"scientist") and
  bare `poly` are deliberately absent — the abbreviation is spelled `ts/sci`. A clearance
  bar phrased with none of these words is a **miss**, which reaches the human; a false discard is reviewed by nobody. The floor is keep-direction
  only — it can turn a discard into a keep, never the reverse. `degree` is **not** guarded this way: 38 of 38 live degree discards
  are grounded (36 in the description, 2 in the title), so the same guard there would be
  speculative.

  **Location is a deterministic code gate** (`location_verdict`, with
  `resolve_location` as its two-value shim) matched against the board's
  `posting["location"]` string — not the LLM. **Evidence tiers, not first match**
  (rebuilt 2026-07-30 after a 9,633-row survey measured 317 rows kept that were clearly
  non-US, against a clean discard side):

  - **TIER A** — a token that NAMES a country, including informal spellings resolved
    through `_COUNTRY_ALIASES` (`UK`, `England`, `Scotland`, `LDN`, `UAE`), or a US
    state. Self-corroborating: one such token decides. A country named inside a token the
    splitter cannot break (`Remote Canada`, `India-Pune`) is found by a phrase-level scan,
    which skips US state names so a street address (`885 GEORGIA ST W:VANCOUVER`) is never
    read as the country Georgia.
  - **TIER B** — a foreign subdivision (`Telangana`, `Ontario`, from a pycountry index
    admitting only unambiguous non-US names) or a gazetteer city, both looked up on an
    NFKD-**folded** key so a board's ASCII `Montreal`/`Sao Paulo`/`Zurich` reaches the
    stored `Montréal`/`São Paulo`/`Zürich` (6,449 of 30,699 city keys carry non-ASCII).
    Each token votes for *every* country it could denote and the supporting-token count
    settles it: `Toronto, Ontario` reads Canada 2-1, while a bare `Charlotte` ties and
    keeps its US reading (it is also a parish of Saint Vincent). Tier B *discards* only
    when **corroborated** — every token resolved, or two agree — which is what still
    keeps `London, ON`.
  - **neither** — no verdict is recorded at all (`resolved: False`), so the gate stays
    silent rather than blessing the row, and sets `ask_llm` when a token named something
    the gazetteer does not know.

  Ordering is load-bearing in three places. The **remote hint runs after Tier A**, so
  `Remote - India` discards while `Remote - US` keeps (85 rows). The literal `remote`
  allow-entry is excluded from the direct allowed-list match, because matching it as a
  *place* was the other half of that bug. And **any allowed evidence keeps, whatever tier
  found it** — never `all` — so `New York City, London, Singapore` survives; that single
  choice is what preserves the zero-false-discard invariant. Region acronyms are a
  stoplist (`EMEA`, `APAC`), not a population floor: `Apac` is a Ugandan town of 67,700
  against `Zug` CH at 30,542, so no floor separates them, and the acronym used to make
  `APAC - India - Pune` discard as "on-site in **Uganda**". Regions that *contain* the US
  (`Americas`, `AMER`) count as weak US evidence rather than noise (err toward keep).
  Three cheap passes run before a token is given up on, added once measurement showed
  that **197 of the 296 unresolved rows were gazetteer gaps rather than judgement** — a
  model tier would have been paying per posting for a lookup table. (1) geonamescache's
  `alternatenames` (141k keys the primary index discards) resolve `NYC`, `Bangalore`,
  `Gurgaon`, `Frankfurt`; a 3-4 character alias additionally needs a million-person city
  behind it, or facility codes collide (`MOD` made an Indian row read as US-eligible).
  (2) A token that resolved to nothing is retried split on `- . /` — the site-code
  formats (`FR-Paris`, `PL-Warsaw-Lixa C`, `USA.VA.Reston`); splitting on those up front
  would shred `Winston-Salem`, so it only ever runs on a failure. A 2-letter prefix that
  is both a US state code and a country code reads as the COUNTRY only when another part
  corroborates it (`DE-Germany`, `CA-Toronto`), and stays the state otherwise
  (`USA.VA.Reston` is Virginia, not the Holy See). (3) A trailing facility noun is
  stripped last (`San Francisco HQ`).

  Measured on the live corpus: **416 rows moved keep -> discard, 0 moved the other way,
  0 US-eligible strings discarded**; the residual leak is pinned at 6 strings / 14 rows
  and unresolved rows are down to **1.0%** (`tests/fixtures/location_corpus.jsonl`).
  Exempting *unambiguous* city names from corroboration was measured (+26 rows) and
  **rejected**: it discarded a US university building as Tanzania (via "Coast") and an
  Israeli site as Italy. US-state and remote strings keep, so a
  `locations`-only candidate makes no SCREEN call (any backend). The screen prompt
  carries no location clause. The screen prompt is
  `prompts/screen.txt`, shared by every backend. Separately, when
  `candidate.exclude_internships` is set,
  intern/co-op roles are disqualified by a whole-word match on the job title (no LLM
  call — runs even when no other screen clause is configured). A SCREEN **provider**
  failure errs toward keep (not disqualified) and stamps `provider_error` on the
  verdict; `run_screen` stores it as a retryable error, and a run of them
  circuit-breaks the pass (§9).

  **Quota telemetry (`ats_worker/usage.py`, free).** `capture_usage(path, backend)`
  makes **one** HTTP GET against a subscription backend's own usage endpoint and writes
  a snapshot to `scorer_usage.json` in the shared db dir
  (`{backend, plan_type, as_of, limits:[{key, used_percent, window_minutes, resets_at}]}`).
  Best-effort by contract: `capture_usage` never raises, and a failed fetch leaves the
  PREVIOUS snapshot in place rather than truncating it — a transient 429 should dim the
  bar's freshness (the web reads file mtime as `as_of`), not blank it. The write is
  atomic (tmp + `os.replace`, tmp name keyed by pid+thread). **A failed capture is
  announced WITH ITS CAUSE**: every route to a `False` return
  prints what happened — a non-200 with its status and reason, an `HTTPError` (which
  `urlopen` *raises*, so the status check never sees a 4xx), a connection or truncated-body
  failure with its exception type, "not logged in", a 200 whose body is not an object at all, a 200
  whose payload has no `rate_limit`, a 200 whose windows carry a null `used_percent`, an
  unknown backend, and the blanket catch that covers the file write. The claude fetcher
  carries the same prints, so the guarantee is not codex-only even though codex is the
  default. The narrow `_get_json` catch
  is only defensible because that blanket one speaks: `http.client.HTTPException`
  (`IncompleteRead`, `BadStatusLine`) subclasses neither `OSError` nor `ValueError`, so it
  is named in the tuple rather than left to fall through silently. **Why this much:** with a
  bare `False`, a 403, an expired token, a DNS blip and a malformed body are
  indistinguishable. The write also stamps an offset-aware `as_of` into the snapshot itself — a stale
  reading and a fresh one are otherwise indistinguishable to anything but `ls -la`. A
  pass on the `codex` screen backend calls it at the end of the pass; the web quota bar
  (§7.2) shows the last snapshot written.
  Endpoints:
  - **codex** — `GET https://chatgpt.com/backend-api/codex/usage`, bearer token +
    `chatgpt-account-id` from `$CODEX_HOME/auth.json`. Yields `plan_type` and
    `rate_limit.primary_window`/`secondary_window` (`used_percent`,
    `limit_window_seconds` → `window_minutes`, `reset_at`). The observed `primary` is
    the **weekly** window (10080 min). This is the budget the `codex` screen spends.
    chatgpt.com is behind Cloudflare, which 403s urllib's default `Python-urllib/3.x`
    (and a browser-looking `Mozilla/5.0`), so an honest client `User-Agent` is sent.
  - **claude** — `GET https://api.anthropic.com/api/oauth/usage`, bearer token from
    `$CLAUDE_CONFIG_DIR/.credentials.json` + `anthropic-beta: oauth-2025-04-20`.
    Normalises the richer `limits[]` array (`kind`/`group`/`percent`/`resets_at`, plus
    `scope.model.display_name` for the model-scoped weekly row) and falls back to the
    flat named buckets (`five_hour`, `seven_day`, …). ISO reset strings are parsed to
    epoch seconds so both backends share one field.
    **This is the Claude Code SUBSCRIPTION budget, which is NOT what the `claude-api`
    screen spends** — that bills `ANTHROPIC_API_KEY` (metered; no percent-of-quota
    endpoint exists for it). The snapshot records `backend` and the
    bar states the distinction outright (§7.2) so the two are never conflated.
- **`pipeline.py` — orchestration.** Stateless stage functions over a db
  connection with injected worker callables and an explicit `now`:
  `run_fetch` → (`run_feed`) → `run_expire` → `run_screen`. Every stage wraps each item
  in try/except: one bad posting/company is logged or recorded and the batch continues. `run_fetch` runs the watchlist path: fetch
  each company, apply `fetch.prefilter_postings` (title keep/exclude + max-age), then
  — when a `candidate` is configured — run the **same** deterministic intern/location
  gate as the post-LLM screen (`screening.deterministic_screen`, shared code, not a
  reimplementation) against each surviving posting *before* it is ever upserted. A
  gate miss is tagged `pipeline_status="discarded"` with a screen-shaped
  `score_detail` right there at fetch time — visible in the Discovered "Discarded"
  bucket with its reason — **without** an Ollama call; a company that raises is
  logged-and-skipped so the rest of the watchlist still ingests. Finally, a surviving
  posting with **no description is dropped, logged, and recorded in `feed_unresolved`**
  (`feed="watchlist"`, `reason="empty_description"`) — `_valid_posting`, the same
  body-required guard the feed path applies: a bodyless row is permanent
  (`upsert_postings` is `ON CONFLICT DO NOTHING`, so a later cycle never back-fills it)
  and would be screened blind, so a board whose list endpoint carries no
  JD simply yields nothing that cycle — while the `feed_unresolved` record surfaces the
  silently-broken scraper on the Unresolved board (dropping, not storing as `discarded`,
  keeps the id re-fetchable so the board self-heals if a later cycle returns the body).
  Rows already tagged `discarded` are exempt —
  the stub gate returns those deliberately un-hydrated and they never reach the screen. `screen_posting`
  still runs `deterministic_screen` again post-LLM (preserving any degree/auth/
  clearance disqualification the SCREEN call found), so the feed path — which never
  goes through `run_fetch` — gates identically, just one stage later.
  `run_feed` (optional) runs
  the feed: feed gate → operator pre-filter (`prefilter_postings`, the same call
  `run_fetch` makes) → resolve → record-unresolved, then groups survivors by
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
  raising. Any failed id is recorded in `feed_unresolved`, and the reason **names which
  failure it was** — the two have opposite meanings, so one string for both made the
  record undiagnosable: `reason="list_fetch_failed"` for a per-board source's raising list
  fetch; `reason="detail_fetch_failed"` for a detail source's raise or `None` (the
  endpoint did not serve the id, which for a feed-surfaced `externalPath` is usually a
  dead req — normal and harmless); `reason="empty_description"` when a posting *came back*
  and failed `_valid_posting` (a scraper parsing a shape it does not understand — the one
  worth acting on). That is the **same** string the watchlist path uses for the same
  condition, so one query over `feed_unresolved` covers both paths. Host comes from the
  listing URL. A detail source that resolves ids but keeps **none** also prints a
  one-line collapse warning, which names the split (`N unparseable — scraper may be
  broken` vs `N dead req(s), none unparseable`) because that line repeats every pass and
  an undiagnosable warning gets tuned out. Each kept posting is stamped with its
  `company_slug`.
  `run_screen` is the standalone screen (lifecycle under `screening/` above): it runs
  `screen_fn` over eligible `new` rows with up to `--screen-workers` concurrent calls
  (default 1), while every DB read/write stays on the calling thread.
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
  scheduling mechanism, no extra column. **Limitation:** nothing writes
  `scored`/`notified` any more, so this sweep only revisits legacy rows; a `new` posting is
  never rechecked and a stored one is not proof the requisition is open.
  The separate `run_unscored_refresh` mode accepts only the explicit
  `smartrecruiters` adapter and 1–25 requests. It selects `new`, `failed`, `discarded`,
  or `expired` rows without a fit assessment or application link, least recently
  attempted first. SmartRecruiters must return the exact ID, a matching company
  identifier when present, a boolean `active`, and complete core JD content when active.
  Exact-ID `active=false` confirms source closure; 404/410, timeouts, access blocks,
  malformed or incomplete responses are inconclusive. A valid response updates the
  current source content/hash/revision and the source timestamps, without changing
  pipeline/application state or calling a model. The write transaction rechecks source
  identity and eligibility. A later valid observation reopens only source availability.
  This one-shot mode does not run normal fetch, expiry or screen stages.
  Stage gating in §[9](#9-behaviors-and-invariants).

- **`mcp/` — optional ATS data service; reads SQLite read-only, writes only through web.** Install the pinned v2 SDK from
  `requirements-mcp.txt` only for this service. `ReadOnlyATSRepository` opens the
  Prisma-owned SQLite file with URI `mode=ro`, enables `query_only`, uses a bounded
  busy timeout, and opens a live connection per call so committed WAL updates remain
  visible. It never imports the worker scheduler or writer bootstrap, creates a missing
  database, seeds settings, or performs DDL. `ATS_DB_PATH` selects the database; when
  unset, the repository resolves the web Prisma database path from the checkout.
  The `MCPServer` entrypoint is `python -m ats_worker.mcp` and its default transport is
  stdio; it binds no listener. Registered tools are `get_ats_overview`, `list_jobs`,
  `get_job`, `get_job_description`, `list_applications`, `get_application`,
  `get_application_notes`, `list_application_history`, `list_ats_records`, and
  `get_ats_record`. Every tool carries read-only/closed-world annotations, but the
  connection-level SQLite settings enforce the boundary. The eight model names are a
  closed enum, identifiers are selected from an internal allowlist, values are bound,
  and no tool accepts SQL, filesystem paths, HTTP targets, or mutation requests.
  Lists use filter-scoped opaque keyset cursors (default 25, maximum 100); pages are live
  rather than one cross-call snapshot. Job descriptions and application notes use
  explicit character chunks up to 16,000; null and empty values remain distinct.
  The tools expose all eight current Prisma models, including unknown lifecycle states,
  links, complete text, and raw/parsed legacy JSON. `app_settings` exposes the approved
  `categories` value only; other setting values are withheld until reviewed. `custom`
  and `browser` recipes retain their ordinary fields and header names while all header
  values and conventional secret URL query values are redacted, including encoded keys
  in malformed URLs whose authority cannot be parsed; malformed recipes are
  withheld because they cannot be safely parsed. Tool errors contain actionable
  repository messages but never a database path or driver text. Server instructions
  mark job descriptions, application notes, recipes and scraped text as untrusted data.
  `list_jobs` takes `jev` (`keep` default, `skip`, `all`): `keep` hides only `new`
  postings whose current JEV verdict is `skip` and reports `jev_filter.hidden_skip_count`
  on the first page; unassessed, failed, non-`new` and stale (source revision changed,
  or a policy other than the latest pass recorded) postings are shown.
  Each row carries `jev.status`/`reasons`; `get_job` adds model, policy hash and attempt
  times; `get_ats_overview` adds `jev_filter_counts` over `pipeline_status=new`.
  `list_jobs` keeps metadata search as the default and offers opt-in literal `all_text`
  matching over title, company, location and description; `%`, `_` and `!` are escaped,
  and description bodies remain available only through the chunk tool. Its optional
  standalone `screen_outcome` filter and bounded summary use only `job_screenings`:
  outcomes distinguish `not_screened`, `provider_error`, `disqualified`,
  `no_disqualifier_found` and `unknown`. The positive outcome is advisory and does not
  establish full qualification; legacy `score_detail.screen` is reported separately and
  never creates a standalone result or assessment time. Optional offset-aware RFC3339
  `screening_updated_from` (inclusive) and `screening_updated_to` (exclusive) filter
  `job_screenings.updated_at`, including provider errors. UTC-equivalent values are
  normalized; stored offset-bearing T/t or space forms are supported. A
  `disqualified` outcome requires explicit top-level `disqualified=true` plus at least
  one typed failing check; an unsubstantiated true flag is `unknown`, as is a false flag
  paired with a failing check. Offsetless or otherwise unparseable stored assessment
  times do not match dated windows, count as unknown, and are summarized as null rather
  than interpreted as UTC. `get_ats_overview` reports disjoint standalone outcome counts
  over all postings, fresh/retry-eligible screen backlog counts for
  `pipeline_status=new`, unknown assessment-time count, and a query response timestamp
  that is not source freshness. Job list traversals carry a first-page maximum-id
  ceiling, but later requests still read current row state rather than a snapshot; an
  assessment may enter or leave a filter between pages. Callers rerun overlapping
  windows, deduplicate by source/external_id and assessment time, and periodically
  reconcile. Overlap cannot recover arbitrary backdated writes or every transition.
  `list_jobs` and `get_job` also expose a bounded `source_lifecycle` summary with the
  confirmed source state, seen/attempt/check times, safe error category, content revision,
  and independent fit/screen freshness (`not_assessed`, `current`, `stale`, `unknown`, or
  `provider_error`). A failed newer attempt does not replace the last conclusive check.
  They also expose a derived `triage_summary` with one of `rule_disqualified`,
  `screen_disqualified`, `candidate`, or `needs_review`, plus bounded reason and
  provenance. `list_jobs` accepts an optional `triage_status` filter, evaluated before
  pagination and included in cursor scope. `get_ats_overview.job_triage_counts` partitions
  all `job_postings`. Unknown lifecycle state always needs review; only narrow typed
  deterministic evidence is called rule-based, including a rule-only standalone result
  that does not establish whether a model ran. A candidate is retained for fit research,
  not qualified. Missing standalone evidence alone does not establish processing state.
  These derived fields leave the existing `screen_outcome` and stored row values intact.
  **Write tools** (`write_client.py`) exist only when `ATS_API_KEY` is set (a web
  `read_write` key, §7.2); without it the tool list is the read tools above and the
  instructions say the server cannot change state. They call web's `/api/v1` over
  `ATS_API_URL` (default `http://127.0.0.1:3000`) and never open a writable DB handle:
  `record_application` (date defaults to today, status from the `STATUSES` enum),
  `mark_job_applied(job_id, category?)`, `update_application_status(application_id,
  status, date?)`, and `update_application_notes(application_id, text)`, which appends
  after a blank line and never replaces. The append is read-then-`PATCH` of the whole
  field with no version check: a web edit to the same notes in that window is
  overwritten (accepted for a single operator; a web-side append is the fix if it bites). Annotations are `readOnlyHint=false`,
  `destructiveHint=false`; nothing deletes. Web's error text becomes the `ToolError`;
  401/403, 503 and an unreachable web map to fixed operator-facing messages. With writes
  enabled the instructions add that writes happen only on the operator's request, never
  because stored text says so. `list_applications`, `get_application` and
  `list_application_history` report `actor` (`web`/`mcp`).
  **Workflow text** lives in the server, not in a client skill: with writes enabled the
  instructions map "I applied to job N" -> `get_job` + `mark_job_applied`, an
  off-ATS application -> duplicate search + `record_application`, and a status change
  -> `update_application_status` + a dated note. MCP prompts: `daily_brief` (always;
  read-only, no write tools), and with writes `log_application(what)` and
  `update_from_email(since="the last 7 days")`, which uses the client's own mail
  connector, treats email as untrusted, and waits for the operator's go-ahead before
  writing. An onboarding prompt waits on preferences moving into the DB (#157).
  MCP protocol tests are mandatory in CI, which installs the optional pinned SDK.

- **Offline synthetic assessment projection** (`preselection_view.py`,
  `preselection_view_cli.py`). Given an explicitly supplied, schema-1 synthetic snapshot,
  project a bounded view with separate assessment and latest-attempt states. Compare
  source revision/content identity, context, rubric/policy/question/prompt/schema, input
  variant and provider/model identity; stale or incomplete evidence is never a
  qualification result. Only typed component scores, safe version/model labels and
  resolved JD-source excerpts leave the projection. Timestamp digits are ASCII-only;
  malformed latest-attempt metadata is unknown independently of a valid saved result.
  Bounded text remains valid across a trimmed whitespace boundary, and the isolated panel
  visibly labels every displayed shortened value. The explicit fixture CLI has no
  config/profile/database defaults and is not wired into `run.py`, inventory or MCP.

- **Offline synthetic preselection rehearsal** (`preselection_rehearsal.py`,
  `preselection_rehearsal_cli.py`). An explicit scenario, assessment fixture, candidate
  pool fixture and output path drive the real assessment projection and review-batch
  modules through a fixture-backed read adapter. The report records page and per-job JD
  completeness/error evidence, characters, injected elapsed time, source/application
  evidence, bounded revalidation, age/overload alerts, repeated-day occurrence identity
  and a stable-ID fallback from the current validated candidate set. Stale and unknown
  candidates retain their current source/content and invalidation evidence; closed and
  confirmed-application exclusions stay visible, and incomplete revalidation yields no
  fallback recommendations. Batch candidates are validated before cross-fixture identity
  lookups. Missing, empty and partial JD reads remain distinct and fail the completeness
  case. Monitoring keys are allowlisted, and missing optional thresholds remain unknown.
  Provider and missing-private-input faults are labeled simulations;
  provider cost, human reading and delivery stay unknown. This path has no provider,
  profile, resume, config, database, network, MCP, scheduler or production wiring.
  [Current rehearsal limits and unexercised gates](reports/preselection-rehearsal-readiness.md).

### 7.2 Web (`apps/web/src/`)

- **`app/page.tsx`** — dashboard entry; SSR with `export const dynamic =
  'force-dynamic'` so it always reads the live db.
- **`app/api/health/route.ts`** — DB-reachability probe for the Docker healthcheck.
  `GET` runs `SELECT 1 FROM job_postings LIMIT 1` (`200 {status:"ok"}`, else `503`) so a
  stale bind mount is caught and the `autoheal` sidecar can restart the container (§6).
  **It names an APPLICATION table on purpose, and which query it runs is measured rather
  than reasoned** — the drill matrix is in §6. `SELECT 1` and a `sqlite_master` read are
  behaviorally identical in every failure mode tested; the one that discriminates is a
  missing DB file, where SQLite silently creates an empty database and both weaker probes
  report healthy forever against a tracker with no data. A real table name yields `no such
  table: job_postings`.
- **Codex login notice:** the usage bar displays a compact re-login notice and
  `codex login --device-auth` when worker credentials are missing or the Codex usage
  endpoint returns HTTP 401. HTTP 403 and transport failures retain the prior snapshot
  without asserting login failure. A successful usage capture clears the notice. When
  the worker runs with a non-default `CODEX_HOME`, the snapshot carries it as
  `codex_home` (`$HOME`-relative when under the home directory) and the command is
  prefixed `CODEX_HOME="<codex_home>"`, so the operator's chosen codex account is the one
  re-logged. Detection happens at the end of each `codex` screen pass, not continuously.
  Access-token expiry alone does not establish that automatic refresh has failed.

- **`app/api/scorer-usage/route.ts`** — serves the subscription quota snapshot
  `ats_worker.usage.capture_usage` writes (§7.1): reads `scorer_usage.json` (path derived
  from `DATABASE_URL`, overridable via `SCORER_USAGE_FILE`), returns the snapshot —
  including the `backend` it describes — plus `as_of` (the file mtime).
  Missing/unparseable → empty state (`{backend:null, limits:[], as_of:null}`, still
  `200`), since the worker may not have scored yet.
- **`app/api/v1/*`** — the key-scoped loopback write API the MCP server calls, so write
  validation exists once in `lib/actions.ts`. Each route is a thin wrapper over one
  action; creating an application and changing a status stamp `actor='mcp'` (detail
  edits and watchlist rows carry no actor): `POST applications` (`addApplication`; an
  unknown `status` is a `400`, where the UI falls back to `Applied`), `PATCH
  applications/{id}` (`updateApplicationDetails`; omitted fields unchanged), `POST
  applications/{id}/status` `{status, date?}` (`updateApplicationStatus`), `POST
  jobs/{id}/applied` `{category?}` (`markJobApplied`, scope `bucket=all`), `POST
  watchlist` / `DELETE watchlist/{id}` (`addWatchedCompany` / `removeWatchedCompany`).
  Auth (`lib/api-v1.ts`): `Authorization: Bearer <key>` against `ATS_API_KEY_READ_WRITE`
  (scope `read_write`) or `ATS_API_KEY_READ` (scope `read`); neither set -> `503`
  (disabled, never open), missing/wrong key -> `401`, read key on a write -> `403`, an
  action's `{success:false}` -> `400` with the action's own error text. No route
  deletes an application or history row. The application history dialog marks an
  MCP-created application "logged via MCP" and each MCP status row "via MCP".
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
  - *Discovered jobs:* `getJobPostings` defaults to `bucket=all`, a direct inventory
    list/count that excludes only terminal `removed` rows and orders by
    `created_at desc, id desc`. Metadata search is the default; opt-in `all_text` includes
    descriptions with literal `%`, `_` and `!` matching. Screen outcome filters use the
    standalone screening row and shared five-value contract, with reasons/provenance
    summarized separately from legacy fit-record evidence. Inventory search and outcome
    predicates stay in bound SQL and do not materialize fit-derived ID lists. Standalone
    screening result JSON is projected into the bounded summary rather than returned;
    full JD text is not rendered in the table and remains available to the detail modal
    through the stored description, without a provider call. The
    score-aware `matched`/`belowbar`/`discarded`/`lowcontext`/`failed` buckets and their
    existing membership remain available; their default sort is score. All views support
    paginated `page`/`size`; optional `minScore` and the discarded-bucket
    disqualification-`cause` ∈ authorization/location/degree/clearance/internship
    sub-filter remain. Per-row actions validate current view scope; bulk lifecycle actions
    are rejected for All jobs and are confined to legacy buckets. `discardJobPosting`,
    `reopenJobPosting`, `bulkRemove(ids, scope)` (terminal `removed`, UI-only hide,
    worker-inert), `bulkReopen(ids, scope)`, `removeAllInView(bucket, filters)`,
    `markJobApplied(id, category, scope)`
    (category chosen at apply time from the user-configured vocabulary — free-form,
    default `Others` when blank), `getCategories`/`setCategories` (the user-editable
    category list, stored in `app_settings`).
    Bucket definitions and `removed` semantics in §9.
    Each row also carries a source-lifecycle summary: source state, last seen/check times,
    safe inconclusive category, current content revision, and independent fit/screen
    freshness. Unknown legacy revisions and provider errors stay explicitly unknown/error.
    Rows and job detail also carry a derived `triage_summary`: rule-based rejection,
    standalone screening rejection, candidate retained for fit research, or needs review.
    The All jobs view accepts an optional triage filter in bound SQL before pagination and
    count; MCP overview separately reports four disjoint counts that partition all postings. A rule-only standalone result
    can be deterministic even though it is stored in `job_screenings`; storage alone does
    not prove model invocation. Missing standalone evidence alone does not establish that
    screening never ran. Raw `screen_outcome`, the five-value standalone filter, and legacy
    fit-bucket membership remain unchanged; candidates are not presented as qualified.
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
  Discovered-Jobs matched/below-bar/discarded split is now the verdict predicate
  (`matchedIds()` / `belowBarIds()` in `lib/actions.ts`) over the stored fit verdicts,
  not a score cutoff; the fit score is display/ranking only.
- **`components/`** — `Dashboard` (Applications ↔ Discovered Jobs ↔ Watchlist ↔
  Unresolved tabs, each delegated to a `*Tab` wrapper), `ApplicationTable` (inline status edit), `KPIGrid`,
  `StatusHistoryModal`, `AddApplicationForm`, `DiscoveredJobsTable` (All jobs first and
  selected by default, with Matched/Below-bar/Discarded/Failed/Low-context buckets
  retained; filters are controlled by `Dashboard` and survive tab unmount/remount, while
  request-version checks discard stale responses and pending/error states hide old rows;
  All jobs offers literal metadata/all-text search, standalone outcome filters, discovery
  recency/score/posted sorting, lifecycle labels and no bulk controls; row actions carry
  the exact active filter scope. Screen summaries show advisory outcome, bounded reason,
  backend/model/effort and assessment time when present, separately from legacy fit-record
  screen evidence. A bucket-aware per-row "why" subline (a shared `VerdictShortfall` —
  seniority/domain verdict pills +
  top missing must-have — for below-bar AND for the fit-reject half of discarded, falling
  back to the legacy one-line `reasoning` for pre-S2.1 rows; the keyed disqualification
  reason when there is one; **which** low-context rule caught the row — a short body
  ("Thin JD (N chars)") vs the scorer's own `insufficient_context` flag on a full-length
  JD; pipeline error); a `recommended_resume` label under the score;
  folded Company/location/source and Posted/Fetched date columns + legacy-bucket bulk
  Remove/Reopen/Remove-all-in-view + job-title links to the live posting),
  `Pagination` (reusable: first/last, numbered pages, go-to), `ApplyCategoryDialog`
  (category picker on Mark Applied), `ImportCSVDialog` (drag-and-drop or browse file
  picker behind the Import CSV button, with the column contract — required columns,
  `YYYY-MM-DD` dates, the exact `status` vocabulary, dedup-skips-never-overwrites —
  stated inline; guards on the `.csv` extension, not the MIME type, since Excel on
  Windows reports a CSV as `application/vnd.ms-excel`), `WatchlistTable`
  (list + add/remove watched companies), `PromotionSuggestions` (approve/dismiss feed→
  watchlist suggestions, shown in the Watchlist tab), `UnresolvedFeedsTable` (read-only
  backlog), `ScorerUsageBar` (subscription quota bar on the Discovered Jobs view — polls
  `/api/scorer-usage`, one bar per window with % + "resets in Nd Hh" + "as of"; reflects
  the last captured snapshot, not a live reading. **Labels itself by backend** from the
  snapshot, so switching backends relabels the bar instead of showing the other
  provider's numbers under the old name; two windows of the same length are
  disambiguated by the model scope in the key (`weekly · Fable`); on `claude` it states
  outright that it reads the Claude Code SUBSCRIPTION, not the `ANTHROPIC_API_KEY`
  spend the scorer actually bills), `JobDetailModal` (JD + score detail), and
  the four charts `TimelineHeatmap` /
  `CategoryDonut` / `StatusFunnel` / `SankeyChart`, plus Radix-based `ui/` primitives.

- **Offline assessment panel** (`lib/assessment-view.ts`,
  `components/preselection/AssessmentPanel.tsx`) validates and renders only the bounded
  synthetic projection. The panel is exercised by an isolated component test and is not
  routed into inventory, Server Actions, MCP, or the deployed UI.

---

## 8. Data model

*Class: **Snapshot** — mirrors `schema.prisma` (the real source of truth); if they disagree, update this spec.*

Nine tables, owned solely by `apps/web/prisma/schema.prisma` (`applications`,
`status_history`, `job_postings`, `watched_companies`, `feed_unresolved`,
`promotion_dismissed`, `app_settings`, `job_screenings`, `job_jev_assessments`). Dates are stored as **ISO-8601 strings** for sortability and
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
  actor           String           @default("web") // who created it: web | mcp (ACTORS)
  status_history  status_history[]
  job_postings    job_postings[]   // back-link from a promoted posting
}

model status_history {
  id             Int          @id @default(autoincrement())
  application_id Int
  status         String
  timestamp      String
  actor          String       @default("web") // who made the change: web | mcp
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
  score           Int?          // 0-100 fit score (history: no current writer)
  score_detail    String?       // JSON: assessment scorecard (seniority/domain/must_haves/nice_to_haves/summary), insufficient_context flag, screen, disqualification, recommended_resume, scorer provenance backend/model/scorer_version on fit-scored rows (pre-S2.1 rows: matched/missing keywords + reasoning)
  pipeline_status String        @default("new") // new|scored|notified|applied|discarded|failed|removed|expired
  pipeline_error  String?       // last stage error (history: no current writer)
  attempts        Int           @default(0)     // fit-stage failures (history: no current writer)
  notify_attempts Int           @default(0)     // notify send failures (history: no current writer)
  application_id  Int?          // back-link once marked applied
  application     applications? @relation(fields: [application_id], references: [id], onDelete: SetNull)
  job_screening   job_screenings?
  jev_assessment  job_jev_assessments?
  created_at      String
  updated_at      String?
  posted_at       String?       // board posting date YYYY-MM-DD; scrape-date fallback for dateless boards; null on legacy pre-backfill rows
  source_state                    String  @default("unknown") // unknown|available|closed
  source_last_seen_at             String? // latest exact identity in a list or detail response
  source_last_check_attempted_at  String? // latest detail refresh attempt, including errors
  source_last_checked_at          String? // latest conclusive detail refresh
  source_last_check_outcome        String  @default("not_checked") // not_checked|found|confirmed_closed|inconclusive
  source_last_check_error_category String? // fixed safe category; never raw provider output
  source_content_hash              String? // SHA-256 of company/title/location/description
  source_content_revision           Int?    // version used by fit and standalone screens
  source_content_changed_at         String? // when the current revision replaced prior inputs

  @@unique([source, external_id])  // dedup key
  @@index([pipeline_status])
  @@index([source, source_last_check_attempted_at])
}

model job_screenings {
  id                Int          @id @default(autoincrement())
  job_posting_id    Int          @unique
  state             String       // complete | provider_error
  result_json       String?      // nested hard-requirements result; null on provider error
  error_category    String?
  error_message     String?      // fixed safe summary; never provider output
  backend           String
  model             String?
  effort            String?
  evaluator_version String
  last_attempted_at String
  completed_at      String?
  source_content_revision Int? // posting revision used by this completed screen
  created_at        String
  updated_at        String?
  job_posting       job_postings @relation(fields: [job_posting_id], references: [id], onDelete: Cascade)

  @@index([state, last_attempted_at])
}

// JEV keep/skip filter (worker `run_jev`). One latest assessment per posting; a skip
// only hides the row from the MCP default list, it never changes pipeline_status.
model job_jev_assessments {
  id                      Int          @id @default(autoincrement())
  job_posting_id          Int          @unique
  state                   String       // complete | provider_error
  verdict                 String?      // keep | skip; null on provider error
  reasons_json            String?      // JSON array of closed reason codes
  result_json             String?      // native answers of both questions
  error_category          String?
  model                   String?
  policy_sha256           String       // profile + question packs + model binding
  source_content_revision Int?
  cost_usd                String?
  last_attempted_at       String
  completed_at            String?
  created_at              String
  updated_at              String?
  job_posting             job_postings @relation(fields: [job_posting_id], references: [id], onDelete: Cascade)

  @@index([state, last_attempted_at])
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

`job_postings.source_state` is `unknown`, `available`, or `closed` and is independent
of `pipeline_status`. New exact source listings begin `available` with a source-seen
time; legacy/manual rows begin `unknown`. The last-seen time may advance from an exact
listing or detail observation. Detail-check attempt time advances on every refresh;
the conclusive-check time advances only for a verified `found` or `confirmed_closed`
result. Inconclusive errors preserve the last confirmed state/time and use a fixed safe
error category. `source_content_hash` is SHA-256 over stable JSON containing only
company, title, location, and description. A complete new posting starts at revision 1;
an incomplete JD has no revision until complete content is observed. A refresh changes
the stored assessment inputs and increments the revision only when that hash changes.
Fit assessment revision lives in `score_detail.source_content_revision`; completed
standalone screening revision lives in `job_screenings.source_content_revision`.
Freshness is derived per assessment: no assessment → `not_assessed`, matching revision
→ `current`, older revision → `stale`, and a missing, non-positive, non-integer, boolean, or JavaScript-unsafe
captured revision → `unknown`. Provider errors remain `provider_error` and do
not claim a screen verdict. The tracker separates the
current positive source observation and its last-seen time from the last conclusive
exact-ID detail-check time; a newer inconclusive attempt shows its attempt time without
assigning the older detail-check time to a possibly newer list-based source state.

Normal SmartRecruiters feed and watchlist ingestion drops a detail response whose
`active` field is explicitly `false` before canonical posting ingestion. It does not
insert a posting or reopen a closed source state, and it never writes `closed`; only the
explicit lifecycle refresh can record that closure. Missing `active` remains accepted
on normal ingestion for compatibility. This rule is SmartRecruiters-specific and does
not change other adapters.

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
                                  → discarded      (code-only gate fail at ingest)
feed:    (surfaced posting, JD via board adapter) → new   (optional, alongside fetch)
screen:  new                      → new            (result stored in job_screenings;
                                                    lifecycle untouched)
jev:     new (screened, not dq)   → new            (keep/skip in job_jev_assessments;
                                                    lifecycle untouched; --jev only)
expire:  scored|notified, detail source, board 404/410 → expired
                                                   (terminal; capped at 50/pass,
                                                    least-recently-updated first;
                                                    any other error → left alone)
UI:      any non-applied row      → removed        (terminal; bulk Remove; UI-only hide)
```
`scored`, `notified` and `failed` are written by nothing today; rows in those states
are the retired fit scorer's history, still read by the web and MCP.

Source refresh is a separate one-shot observation, not a pipeline transition. It selects
only `smartrecruiters` rows in `new`, `failed`, `discarded`, or `expired`, with no fit
assessment and no application link; `--refresh-limit` bounds the request count to 25.
Only a matching SmartRecruiters ID with `active=false` confirms source closure. A valid
active payload can update company/title/location/JD and the content revision; a changed
revision leaves existing assessments intact and visible as stale. Timeouts, blocks,
404/410, malformed payloads, and incomplete content are inconclusive. Every source write
rechecks identity and eligibility in a transaction. Refresh does not change
`pipeline_status`, applications, notes, status history, or retention, and calls no model.
Normal ingestion filters an explicit SmartRecruiters `active=false` detail response at
the adapter boundary; it does not close the row or advance its source-seen time. A
missing `active` value remains compatible with normal ingestion. This does not extend
to other adapters.

- **All jobs inventory view.** The default Discovered Jobs view lists every posting except terminal `removed`, including `new`, `applied`, expired and unrecognized lifecycle values; unknown statuses, including names inherited from JavaScript Object prototypes, are shown as stored. Its list and count query `job_postings` directly and do not run fit-derived membership scans. Default order is `created_at desc, id desc`; optional score/posted sorts retain an id tie-breaker. Metadata search is default, and `all_text` adds description search with literal escaped `%`, `_` and `!`. Standalone outcome filters and summaries use only `job_screenings`: no row is `not_screened`; persisted provider failure is `provider_error`; a complete `disqualified=true` result requires typed failing-check evidence; `disqualified=false` with a typed passing check and no typed failing check is `no_disqualifier_found`; malformed, incomplete, contradictory or unrecognized data is `unknown`. Every outcome is advisory. Legacy `score_detail.screen` remains separately labeled evidence and never fabricates a standalone result. Derived triage status is `rule_disqualified`, `screen_disqualified`, `candidate`, or `needs_review`. It uses the same typed evidence rules in Web and MCP; unknown lifecycle states, unsuccessful or malformed assessments, conflicting pass/lifecycle state, unsupported legacy data, and absent evidence remain `needs_review`. A narrow deterministic rejection can be supported by a rule-only `job_screenings` result or by a legacy discarded record with no fit evidence; a standalone row does not establish that a provider was invoked. Candidate requires a valid standalone pass on `new`, `scored`, or `notified`, and means retained for fit research, not qualified. No standalone record alone does not mean unprocessed. The All jobs triage filter runs in SQL before pagination and count; the MCP overview counts partition all postings. The table labels each triage category and the detail modal shows bounded reason/provenance. Raw standalone outcome semantics and legacy fit-bucket membership remain unchanged. The table and detail modal show source state/check timing and separate fit/screen freshness; a failed latest attempt does not overwrite the last confirmed state/time. Standalone screening result JSON is projected into the bounded summary; full JD text is not rendered in the table and remains available to the detail modal through the stored description, without a provider call. `created_at` describes discovery time; screen assessment time is never presented as source freshness. Invalid calendar dates and times have a null assessment time, matching the MCP summary contract. Source lifecycle timestamps use the same strict calendar/offset-aware validation and invalid values are null; non-positive, non-integer, boolean, or JavaScript-unsafe assessment revisions are unknown in Web and MCP. Per-row apply/discard/reopen actions revalidate the exact current view/filter scope at the server boundary. Apply retains duplicate protection and transaction behavior. All jobs has no bulk controls or bulk lifecycle action path; supported legacy buckets keep their validated bulk flows. Pending or failed list requests do not display a previous page as though it matched the current filters.

Triage evidence with duplicate object members at its root, screen map, or check object is ambiguous and maps to `needs_review`. Legacy `source_content_revision` may be absent or null; when non-null, it must be a mathematically integral JSON number from 1 through JavaScript’s maximum safe integer. Decimal/exponent forms such as `3.0` and `3e0` are accepted when they represent an integer; booleans, fractions, non-positive, and unsafe values remain unresolved.

- **`removed` is a terminal, UI-only status.** Set by `bulkRemove` / `removeAllInView` and by the per-row dismiss (`discardJobPosting`); the worker never writes it and never transitions away from it. Invisible to all buckets in the Discovered Jobs view; effectively hides the row without deleting it.

- **`expired` is terminal too**, and like `removed` it drops the row out of every
  Discovered bucket (the live buckets filter on `scored`/`notified`). It's written
  only by `run_expire`, only on an unambiguous 404/410 from the board's own per-job
  endpoint — never on a timeout, bot wall, or 5xx.

- **Stage gating is strict:** `run_screen` processes eligible `new` rows without
  changing their lifecycle or fit evidence; `run_expire` only live `scored`/`notified`
  rows from detail sources. A failure in one posting never aborts the batch. An empty
  `candidate` block skips the model call; deterministic location/internship gates still
  run. Provider calls default to a positive cap of 40; explicit `--screen-unlimited`
  removes only the count cap, retaining success caching and the provider breaker. An
  ingest-gate `discarded` row keeps a screen-shaped `score_detail` (including
  `disqualification_reason`) so the UI can explain *why*.
- **Concurrent screen calls never reorder or mis-associate a write.** Every `db.*`
  write stays on the calling thread.
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
  `active` + `category` keep-list + non-explicit-`sponsorship` *before* any fetch,
  then by the operator's own `title_filter` / `title_exclude` / `max_age_days`
  through the **same** `fetch.prefilter_postings` `run_fetch` uses — one ingest rule
  for both paths, so they cannot drift apart. Both gates run *before* the resolve,
  the earliest point that saves anything: a refused listing costs no URL resolve, no
  board detail fetch and no screen call. For a listing that would have *ingested*
  those are one-time costs (`existing_external_ids` prunes it next pass); what recurs every pass is the resolve for whatever
  never lands. A listing the operator's config refuses is dropped outright,
  **not** recorded in `feed_unresolved` (nothing about it is unresolved). The feed's
  own field names are translated first (`_feed_posting_view`): the feed publishes
  `title` where the filter reads `job_title`, and `date_posted` as a **Unix epoch
  int** where the age gate parses an ISO date. Both mistranslations fail *silently*
  and in opposite directions — an unmapped title matches no keep-list, so the feed
  ingests nothing; an unmapped epoch is unparseable, so `max_age_days` never fires —
  which is why the mapping is pinned by tests rather than left implicit. An absent
  or unreadable date keeps the listing, matching the board path.
  **The age gate then runs a second time, on the board's own date.** The pre-resolve
  pass judges the feed's `date_posted` — a proxy, but the only date available while the
  fetch is still avoidable, so that is where the cost is saved; before the upsert,
  `prefilter_postings` re-judges the `posted_at` the board returned, which is the date
  actually stored. The two disagree on evergreen requisitions (a greenhouse req first
  published 13 months ago that Simplify re-lists as fresh), and without the second pass
  a feed row could sit in the DB dated older than `max_age_days` — a guarantee the
  board path makes. Age only on the second pass: the title filters already passed on
  the feed's title, and the detail-fetch-collapse check reads the unfiltered result (an
  all-stale board is not a broken scraper).
  Survivors are grouped by `(source, slug)`, ids already present are skipped, and the
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
- **Silently-broken scrapers are made visible, and the record says which break it was.**
  A detail-fetch failure is recorded in `feed_unresolved` like an unresolvable URL, so it
  shows on the unresolved board rather than vanishing into the swallowed per-listing
  exception — a raise or a `None` as `reason="detail_fetch_failed"` (usually a dead req),
  a posting that came back and failed `_valid_posting` as `reason="empty_description"` (a
  broken parser). Filing both under one string is what made the collapse warning unable to
  say which had happened. A source that resolves ids but keeps none additionally prints a
  collapse warning naming the split. (Canary self-tests and proactive banner alerting are
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
  rows**: the Matched tab applies a low-context hold-back — the enum predicate **and** a
  thin-JD exclusion (`insufficient_context` OR `LENGTH(TRIM(description)) < 200`,
  `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`) — so a short-but-confident `match/match` JD is
  shown under **Low-context**. (The `200` is hand-synced between worker `db.py` and web
  `constants.ts` — a cross-service constant, flagged in both.) The **keep** half of the
  verdicts always requires `seniority=match` — a seniority miss is disqualifying, not
  partial — and then splits on domain: **belowbar** = `{scored,
  notified}` rows reading `seniority=match AND domain=adjacent` (`belowBarIds()`, the
  same raw-query shape as `matchedIds()`) — the **near miss**, worth a human glance;
  **discarded** = the audit view, **two** populations OR'd: (1) hard-constraint screen
  failures, `pipeline_status='discarded'` with the screen's `disqualified:true`
  (substring-matched in `score_detail`, tolerating `"disqualified": true` /
  `"disqualified":true` spacing), and (2) **fit-verdict rejects** — live rows in neither
  the matched nor the below-bar id set, i.e. a seniority miss (`too_junior`/`too_senior`)
  or `domain=mismatch`. Together the three buckets cover every scored row, so nothing is
  orphaned. Only population (1) carries a keyed `disqualification_reason`, so the
  discarded why-cell falls back to the same verdict-shortfall line Below bar uses rather
  than claiming a row was "disqualified" when it wasn't;
  **lowcontext** = `{scored, notified}` rows too thin to score with confidence, by
  **either** signal (OR): a short JD body (`LENGTH(TRIM(description)) <
  LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`, default 200 — case #1) **or** the stored
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
  {authorization, location, degree, clearance, internship, **prefilter**} sub-filter — a
  *derived* id set
  (mirroring low-context) from a raw query matching the worker's keyed
  `disqualification_reason` via `json_extract(score_detail,'$.disqualification_reason') LIKE`
  the cause pattern (`%authorization:%`, `%location:%`, `%degree:%`, `%clearance:%`,
  `%internship/co-op%`, `%prefilter:%`), layered as `id IN` on the discarded query.
  **`prefilter` is the one cause that is not a hard constraint**: the others name a
  requirement the candidate fails, it names the *operator's own* `title_filter`/
  `title_exclude` refusing an already-queued posting (written by the retired fit pass's
  free sweep — 1,504 rows as of 2026-07-31) and
  without a cause they are visible in the bucket but not selectable, so they cannot be
  bulk-removed. The worker writes two `prefilter:` spellings; only the first is ever
  `discarded`, so the wildcard is deliberately not narrowed to it. `getJobPostings`
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

- **`failed` and `discarded` are terminal for the worker.** Nothing requeues them;
  recovery is the human act (`reopenJobPosting`/`bulkReopen` write `scored`).
- **A dead screen *provider* circuit-breaks the screen pass.** `screen_posting` errs
  toward KEEP on any provider failure, which is right for one flaky call and wrong for
  an outage. The verdict carries `provider_error`; `run_screen` stores a closed-category
  retryable error (the posting stays `new`, retried oldest-attempt-first on a later
  pass) unless a **deterministic** gate (location/intern) disqualified it, and a
  `_BackendBreaker` (`_BREAKER_LIMIT` provider errors with zero successes) aborts the
  pass. One success disarms it. **A backend that fails by answering blindly counts the
  same as one that raises** — a non-dict, or a dict with no `screen` object, is a
  provider error (§7.1). `extract=None` (`SCREEN_BACKEND=none`) is **not** a provider
  error — there is no provider, and the deterministic gates run alone. (PRINCIPLES
  "the four kinds of uncertainty" — circuit break.)

- **Wall-clock slots systematically collide with the operator's habits, and the lock
  skips rather than queues.** Passes used to fire at launch time + N, which scattered
  them across the hour; they now land on 00:00/04:00/08:00. An operator who habitually
  runs `--once` at 08:00 will therefore kill the 08:00 *scheduled* pass every single day
  — `pass_lock` refuses the second one outright, and a skipped slot is not made up. This
  is accepted, not a defect: jitter would reintroduce exactly the drift wall-clock slots
  exist to remove. The mitigation is visibility — the skip logs at `WARNING` — and the
  workaround is to hand-run off the slot times.

- **Two pipeline passes never overlap on the same database.** The guard is keyed on the
  `resolve()`d `--db` path (`<db>.pass.lock`, beside the DB), which is the resource it
  actually protects: that DB plus the one paid scorer account. It used to key on
  `tempfile.gettempdir()`, and the difference was not academic — a daemon started from
  cron or from a systemd unit with `PrivateTmp=yes` resolves a *different* temp dir than
  an interactive shell that exports `TMPDIR`, so both acquired and both scored the same
  DB, the paid double-spend the lock exists to prevent. Keying on the DB closes that and
  also lets two checkouts pointed at two DBs run at once, which the shared temp path
  wrongly serialized. `resolve()` is load-bearing: the guard is void the moment two
  passes name the same file differently, and `apps/web/prisma/applications.db` is a
  symlink to `db/applications.db`. APScheduler's `max_instances=1`
  stops the scheduler overlapping *itself* (a long pass makes the next firing skip), but
  not a hand-run pass landing inside a scheduled one — likelier the higher the cadence.
  A duplicated pass re-spends screen-provider quota. `run.pass_lock` wraps
  the whole pass in a non-blocking exclusive `flock`. It is an `flock`, not a PID file,
  because that makes **staleness self-solving**: the kernel drops the lock when the
  holder dies, so a host killed mid-pass leaves a file the next pass takes immediately —
  no operator deleting anything, no guessing whether a recorded pid was reused. Release
  therefore covers every exit — normal return, exception, SIGINT (the `finally` runs),
  SIGTERM/SIGKILL (the kernel). The file is truncated and rewritten with the holder's
  pid so a refusal can name it, and is **never unlinked** (unlinking races: a second
  process can end up holding a lock on an inode no longer at that path). A refused pass
  is non-destructive and total — it neither queues, blocks, nor partially runs: `--once`
  raises `SystemExit` with the message (non-zero, before any fetch or scorer call), a
  scheduled firing logs one `logging.WARNING` and waits for the next slot.
  `_run_scheduler` installs the handler that record wants (`basicConfig`, INFO,
  timestamped) in the daemon branch only, so a bare import still configures nothing.

**Provider-free review-batch replay.** The offline `review_batch.py` path accepts only
an explicit synthetic schema-1 pool. Its policy requires K and allocations whose sum is
K, a deterministic tie rule, seed, role/age/retry/overload parameters, and candidate,
replacement, work and time caps. New arrivals use an explicit UTC half-open
resume/cutoff interval; deferred and due-retry rows are separate inputs, and historical
backfill requires an explicit flag. Occurrences use pool + stable posting identity +
source revision, independently of content/assessment versions, and duplicate stable
occurrences collapse before selection. Candidate identity groups are formed before
filtering so a confirmed application/manual terminal action is retained across exact or
corroborated duplicates; conflicting closed/open source observations remain unresolved
with each member's source/version evidence. Confirmed unlinked applications match by
posting identity or by source-scoped requisition identity; a matching requisition without
source scope is unresolved rather than a global exclusion. Title/company similarity only
raises a review flag. The synthetic recipe combines caller priority order, oldest-first
age service, greedy coverage of supplied role IDs, a seeded uniform sample over a frozen
low-rank frame, and explicit unused-slot redistribution. A batch freezes order and all
input state, including the injected clock, application and duplicate evidence, merged
member versions and final order; cursors bind its batch, snapshot and page scope.
Revalidation marks changed content/source, group, or application evidence, rejects a
changed policy identity, and preserves cumulative invalidation/replacement history and
caps across persisted replay. Work units include candidate/evidence validation,
application/dedup/similarity scans, slot checks and replacement scans/sorts. The supplied
elapsed-time observation accumulates across replay and is checked before each pass starts;
the CLI supplies an incremental duration for the current pass, not a cumulative timestamp.
This fixture-only input is not a measurement of production wall time. If that time
allowance is exceeded or cumulative work is exhausted, the batch is visibly incomplete,
its current candidate projection is empty, and selected slots are unverified rather than
recommended from old evidence. Reported reading, delivery and downstream resource cost
remain unknown.
The fixture CLI writes state only to an explicitly named local JSON path; this contract
does not add production policy, database, MCP, scheduler or worker-runtime wiring.

**Unenforced clause (asserted, not checked).** One contract-flavored claim has no
deterministic gate; treat it as an *intention backed by the human in the loop*, not a
guarantee:

- **Hard-constraint screening**: work authorization is **retrieve-then-classify**
  (**D1**, §7.1) — CODE retrieves the `sponsor` sentences, the model only labels them,
  so it cannot supply text and hallucination cannot disqualify by construction. It is
  now **gated**: `make eval-screen` measures 0 false disqualifications over 21 labeled
  live rows (2026-07-28). What stays unenforced is **recall** — the `sponsor`-only
  vocabulary gives up bars phrased without that word, deliberately, and each is a miss
  that costs one paid fit call and reaches the human; **clearance** remains an LLM *semantic* extraction with a
  code check, now floored on JD evidence (`CLEARANCE_TOKENS` over description + title,
  §7.1) so an ungrounded `requires_clearance` can no longer discard — the residual is a
  **miss**: a clearance bar phrased in none of those words costs one paid fit call.
  The kept `disqualification_reason` + `reopenJobPosting` let a human override.
- **Location** (`location_verdict`, **D2**, §7.1) errs toward keep. It is **now gated**:
  `test_location.py` measures **0 false discards** across all 1,611 distinct location
  strings in the live DB, in CI, against a committed corpus whose labels come from an
  independent oracle rather than the code under test. What stays unenforced is the
  *residual leak*, pinned at 6 strings / 14 rows rather than driven to zero: a city whose
  highest-population bearer is foreign still discards when the posting meant a smaller US
  namesake ("Manchester" → GB, though Manchester NH exists; real boards append the state,
  which the US-state guard keeps), and a string the gazetteer cannot resolve still keeps.
  Both are backed by the human in the loop (kept `disqualification_reason` +
  `reopenJobPosting`).

**Offline synthetic assessment-view projection.** A version-1 snapshot must be marked
synthetic and carry complete expected and captured identities. Matching identities yield
`current`; any identity change, including a late result for older content, yields `stale`;
absent success yields `not_assessed`; malformed, missing, oversized, or unsupported input
yields `unknown` without component values. A later provider error is reported separately
and never replaces a saved success. Invalid or unknown evidence never becomes a zero
score, qualification badge, or private-context display; only allowlisted JD references
are included. Malformed latest-attempt metadata becomes unknown without hiding a valid
saved result. Python and TypeScript share ASCII-digit offset timestamps and accept a
shortened label that drops a trailing boundary space; the panel visibly marks each
displayed shortened value. This contract runs through the explicit local fixture path
only.

### Invariant → test traceability

Grounds the "verifiable" claim. **(no test)** marks an invariant with **no** (or only indirect)
automated coverage — those rely on code review or the human in the loop, not a test.

| Invariant | Test(s) |
|-----------|---------|
| Discovery and read-only evidence access need no fit scoring or delivery | `tests/test_run.py` (`fetch_only` isolation case), `tests/test_screen_pipeline.py`, `tests/test_mcp_repository.py`, `tests/test_mcp_protocol.py`; existing behavior, unchanged by this documentation update |
| Pipeline stage gating + per-item failure isolation | `worker/tests/test_pipeline.py`, `integration/test_pipeline_e2e.py` |
| The synthetic rehearsal validates batch rows before associated evidence lookups, composes actual assessment and batch modules, allowlists monitoring output, reports per-selected-JD completeness/errors, scopes requisition evidence, and derives fallback only from complete current revalidation while retaining stale/unknown evidence and current exclusions | `apps/worker/tests/test_preselection_rehearsal.py` (`test_explicit_cli_composes_real_assessment_and_batch_modules`, `test_missing_monitoring_limit_is_reported_unknown_without_a_default`, `test_unknown_monitoring_value_is_not_echoed_by_the_cli`, `test_malformed_pool_candidate_fails_through_bounded_cli_validation`, `test_selected_job_description_completeness_is_per_candidate_and_visible`, `test_unscoped_requisition_evidence_stays_ambiguous_across_sources`, `test_fallback_fails_closed_when_current_revalidation_is_incomplete`) |
| Provider-free review-batch and rehearsal imports do not load legacy scoring/profile modules or read legacy prompts, résumés or personal profile files | `apps/worker/tests/test_review_batch.py::test_fresh_import_does_not_load_runtime_db_network_or_scorer_modules`, `apps/worker/tests/test_preselection_rehearsal.py::test_consumer_import_does_not_need_runtime_or_private_data_modules` |
| Profile/replay imports and direct fake-provider shadow assessment run with legacy score/fit/profile/prompt/config/runtime imports and text/YAML/`.env` file reads blocked | `apps/worker/tests/test_preselection_import_boundary.py` (`test_profile_replay_and_cli_import_without_legacy_modules_or_text_reads`, `test_shadow_assessment_runs_with_legacy_imports_and_resources_blocked`) |
| Candidate profile rejects duplicate IDs, invalid schema/text and Unicode line or paragraph separators; context measurement never truncates; deeply nested input returns a bounded error | `apps/worker/tests/test_preselection_profile.py` (`test_profile_rejects_invalid_or_unallowlisted_values`, `test_profile_rejects_duplicate_ids_across_both_sections_and_duplicate_json_members`, `test_context_budget_is_measurement_only_and_never_truncates`, `test_profile_cli_bounds_deeply_nested_json_errors`) |
| Frozen replay validates supplied profile/context/source payloads and manifest, preserves daily/split/group membership and unresolved rows, reports only aggregate evidence, rejects blank required source text, and stays inconclusive without an independent source roster | `apps/worker/tests/test_preselection_profile.py::test_rendered_context_cli_mismatch_is_a_failure_and_errors_are_redacted`, `apps/worker/tests/test_preselection_replay.py` (`test_k_is_allocated_once_per_complete_utc_day_inside_each_split`, `test_full_snapshot_cli_validates_complete_daily_pools_and_emits_aggregate_provenance`, `test_snapshot_cli_marks_recomputed_partial_pool_inconclusive`, `test_full_snapshot_allows_nullable_normalized_source_fields`, `test_full_snapshot_keeps_repeated_source_identity_in_one_split`, `test_full_snapshot_requires_non_empty_source_identity_fields`, `test_full_snapshot_requires_nonblank_source_text_fields`, `test_full_snapshot_requires_posted_at_even_if_the_manifest_is_recomputed`, `test_snapshot_rejects_actual_input_or_manifest_tampering`, `test_snapshot_rejects_profile_change_even_when_context_is_rerendered`, `test_unknown_labels_remain_in_pool_and_make_recall_inconclusive_without_denominator_shrink`, `test_snapshot_cli_never_emits_untrusted_role_labels`, `test_snapshot_cli_reports_malformed_unicode_as_a_bounded_input_error`, `test_snapshot_cli_bounds_deeply_nested_json_errors`, `test_replay_cli_emits_only_report_and_no_source_identifiers`) |
| Profile CLI refuses to overwrite its input through a same path, symlink or hard link; JSON integer conversion limits produce bounded profile and replay CLI errors; seed output is a domain-separated SHA-256 fingerprint; role-coverage greedy order preserves reference ties, runs once per day across budgets, and handles a large day | `apps/worker/tests/test_preselection_profile.py` (`test_profile_cli_refuses_rendered_output_aliasing_profile_input`, `test_profile_cli_bounds_oversized_json_integer_errors`), `apps/worker/tests/test_preselection_replay.py` (`test_replay_report_fingerprints_seed_without_echoing_raw_seed`, `test_role_coverage_order_matches_reference_greedy_ties_and_prefixes`, `test_baseline_orders_are_built_once_per_day_across_budgets`, `test_role_coverage_order_scales_to_large_single_day_without_reordering_ties`, `test_snapshot_cli_bounds_oversized_json_integer_errors`) |
| Out-of-range timestamp normalization fails as a bounded frozen-input validation error | `apps/worker/tests/test_preselection_replay.py::test_replay_cli_bounds_timestamp_utc_normalization_overflow` |
| Deeply nested JSON returns bounded CLI errors; large connected day/group inputs do not cause recursion tracebacks, and a one-component pool is rejected with a bounded validation error | `apps/worker/tests/test_preselection_profile.py::test_profile_cli_bounds_deeply_nested_json_errors`, `apps/worker/tests/test_preselection_replay.py` (`test_snapshot_cli_bounds_deeply_nested_json_errors`, `test_replay_cli_bounds_large_connected_component_without_recursion`) |
| Shadow requirements and YOE policy use validated JD spans; direct/extracted fake-provider runs account for attempts and reject changed bound inputs and outside-cohort jobs before transport; evaluation validates outcomes against schema-4 journal provenance, fingerprints split seeds and reports aggregates only; malformed JSON and UTC overflow return bounded errors | `apps/worker/tests/test_preselection_extraction.py` (`test_synthetic_required_yoe_boundary_truth_table_uses_supported_jd_facts`, `test_yoe_policy_keeps_unknown_alternatives_unresolved_and_never_calls_them_passes`), `apps/worker/tests/test_preselection_shadow.py` (`test_instruction_injection_stays_in_jd_and_cannot_change_typed_contract`, `test_direct_assessment_payload_contains_exact_profile_one_full_job_and_questions`, `test_extractor_gets_only_full_jd_and_extracted_assessment_omits_original_jd`, `test_retry_is_counted_and_resume_reuses_success_without_duplicate_call`), `apps/worker/tests/test_preselection_evaluation.py` (`test_report_rejects_changed_validated_content_with_retained_provenance`, `test_report_uses_verified_snapshot_when_original_inputs_change_mid_report`, `test_synthetic_report_counts_recall_failures_fields_and_draw_stability_without_ids`, `test_cli_bounds_oversized_and_deep_json_errors`, `test_evaluation_and_journal_timestamps_bound_utc_normalization_overflow`, `test_run_binding_is_immutable_and_journal_schema_four_round_trips_it`, `test_run_binding_rejects_invalid_identity_and_late_journal_binding`), `apps/worker/tests/test_preselection_shadow_evaluation_integration.py` (`test_real_shadow_rejects_profile_or_questions_that_differ_from_bound_run_before_transport`, `test_bound_journal_rejects_changed_inputs_when_binding_argument_is_omitted`, `test_bound_journal_can_reuse_success_on_resume_without_binding_argument`, `test_frozen_cohort_rejects_outside_job_before_any_side_effect`, `test_bound_run_rejects_missing_or_incompatible_cohort`, `test_standalone_bound_extraction_cannot_bypass_cohort`, `test_execution_rechecks_frozen_content_models_and_budgets_before_side_effects`) |
| Synthetic review batches use explicit K/policy and UTC intervals, keep stable posting identity separate from unique daily occurrence, group duplicates before terminal filtering while retaining member evidence, scope requisition application identity, freeze clock/inputs/final order and cursor identity, preserve unchanged source-state conflicts as active unresolved evidence, and cumulatively preserve invalidation/replacement history; work/time exhaustion visibly suppresses unchecked recommendations | `apps/worker/tests/test_review_batch.py` (`test_occurrence_identity_uses_pool_posting_and_source_revision_only`, `test_new_arrivals_use_half_open_resume_cutoff_and_historic_scope_is_explicit`, `test_exact_and_corroborated_duplicates_collapse_but_similarity_only_flags`, `test_confirmed_exclusion_survives_exact_and_corroborated_duplicate_grouping`, `test_requisition_application_evidence_is_scoped_or_visible_as_ambiguous`, `test_stable_posting_occurrences_are_unique_before_audit_sampling`, `test_clock_and_final_order_are_bound_to_batch_and_cursor_identity`, `test_revalidation_marks_changed_versions_and_replaces_within_caps_without_reordering`, `test_real_cli_revalidation_preserves_an_unchanged_duplicate_state_conflict`, `test_revalidation_work_cap_limits_full_analysis_and_hides_unverified_slots`, `test_revalidation_work_cap_counts_candidate_search_and_sorting`, `test_revalidation_time_cap_short_circuits_before_candidate_validation`, `test_real_cli_persisted_revalidation_keeps_history_and_cumulative_caps`, `test_committed_fixture_runs_real_projection_and_keeps_text_out_of_the_view`) |
| Screen-only stores result/provenance separately, preserves posting/fit lifecycle fields, caches completed rows, retries provider errors oldest-first under the provider-call cap, and re-checks eligibility before commit | `test_screen_pipeline.py` (`test_screen_results_cache_and_leave_fit_lifecycle_unchanged`, `test_provider_cap_counts_failures_and_errors_retry_oldest_first`, `test_screen_result_is_not_saved_if_lifecycle_changes_during_provider_call`, `test_provider_exception_text_is_not_persisted`) |
| A pass is fetch then screen; `--screen-only` is an accepted alias; invalid mode combinations are rejected; Codex defaults to Luna/medium when no overrides are set | `test_run.py` (`test_run_once_defaults_codex_to_luna_medium`, `test_screen_only_is_an_accepted_alias_for_the_default_pass`, `test_screen_only_invalid_combinations_fail_before_config_or_db`, `test_rescreen_screened_requires_one_shot`), `test_backends_screen.py` |
| Dedup `(source, external_id)` on ingest | `test_db.py`, `test_pipeline.py` |
| WAL + `busy_timeout` pragmas on connect | `test_db.py` |
| Web Prisma client's SQLite connection defaults `busy_timeout` ≥5000 ms (regression lock) | `db-pragma.int.test.ts` |
| Disqualified → `discarded`; empty candidate skips the screen | `test_screen.py`, `test_pipeline.py`, `test_run.py` |
| A blind degree/clearance extraction (null, blank, or any "unknown" spelling) materializes **no** verdict (a gap, not a pass) — including the two new degree spellings (a non-bool `degree_required`, and `degree_required: true` with no recognized level) | `test_screen.py` (`test_blind_screen_entry_still_leaves_a_gap_for_the_fallback`, `test_blind_degree_levels_leave_a_gap_for_the_fallback`) |
| Degree disqualifies on the **lowest** level the posting names, never the highest, and a merely preferred degree is no bar; unrecognized levels are dropped rather than ranked 0; the older single-`required_degree` shape still works | `test_screen.py` (`test_degree_levels_take_the_lowest_not_the_highest`, `test_a_merely_preferred_degree_is_not_a_bar`, `test_unrecognized_degree_levels_are_dropped_not_ranked`, `test_higher_required_degree_disqualifies`) |
| Wall-clock slots are evenly spaced and tile the day (`cron_hours`); `24` is one midnight slot, never an empty trigger that silently never fires | `test_run.py` (`test_the_schedule_is_evenly_spaced_wall_clock_slots`, `test_a_daily_schedule_is_one_midnight_slot_and_not_an_empty_list`) |
| `schedule_hours` must divide 24: a non-divisor and anything `> 24` are both rejected at config load rather than silently running tighter than configured, or collapsing to daily | `test_config.py` (`test_rejects_a_schedule_that_does_not_divide_the_day`, `test_rejects_a_schedule_longer_than_a_day_instead_of_collapsing_it_to_daily`, `test_every_divisor_of_24_is_accepted`, `test_rejects_non_positive_schedule_hours`) |
| The daemon runs NO pass at launch; `--run-now` runs exactly one before the scheduler blocks; `--run-now --once` is a parser error | `test_run.py` (`test_starting_the_daemon_runs_no_pass_at_launch`, `test_run_now_runs_exactly_one_pass_before_the_scheduler_takes_over`, `test_run_now_and_once_together_are_a_parser_error`) |
| One pass at a time per database (`pass_lock`, keyed on the resolved `--db` so a moved `TMPDIR` cannot dodge it and two different DBs do not block each other): a second acquisition is refused immediately (never blocks/queues), the lock is released on exception, a **stale** lockfile is taken without manual cleanup, and a refused pass runs nothing — `--once` exits non-zero, a scheduled firing skips the slot, stays scheduled, and says so at `logging.WARNING` rather than on stdout (the daemon installs a timestamped handler for it; a bare import installs none) | `test_run.py` (`test_a_second_pass_is_refused_while_the_first_holds_the_lock`, `test_the_lock_is_released_when_the_pass_raises`, `test_a_stale_lockfile_does_not_wedge_the_pipeline`, `test_main_once_refuses_to_start_inside_another_pass`, `test_a_scheduled_pass_skips_the_slot_instead_of_dying`, `test_main_once_takes_the_lock_and_gives_it_back`, `test_the_lock_is_keyed_on_the_db_not_on_the_temp_dir`); an unwritable lock still guards exclusively and says the pid is unrecorded (`test_an_unwritable_lock_still_guards_the_pass`) |
| Sponsorship retrieval is deterministic and per-sentence: one snippet per `sponsor` sentence with a +/-1 window, adjacent hits **not** merged, abbreviations not splitting the sentence, and a JD that never says "sponsor" yielding nothing | `test_screen.py` (`test_snippets_are_the_sponsor_sentence_plus_one_neighbour_each_side`, `test_one_snippet_per_sponsor_sentence_even_when_they_are_adjacent`, `test_a_bare_sentence_would_lose_its_antecedent_so_the_window_carries_it`, `test_a_jd_that_never_says_sponsor_yields_no_snippets`, `test_the_abbreviation_trap_pr22_sprang_does_not_split_early`) |
| Sponsorship decision: any `offers` outranks any `refuses`; the offers/preference vetoes overturn a `refuses` but can never create one; hallucination cannot disqualify because the model supplies no text | `test_screen.py` (`test_an_offer_anywhere_outranks_a_refusal`, `test_a_scoped_refusal_beside_an_offer_keeps_the_posting`, `test_the_offers_veto_overrules_a_refuses_label_but_never_creates_one`, `test_a_preference_is_vetoed_too_because_the_classifier_calls_it_a_refusal`, `test_hallucination_cannot_disqualify_because_the_model_supplies_no_text`) |
| An unusable label list (wrong count, off-vocabulary, **or an empty array against retrieved snippets**) drops the check and KEEPS, and does **not** fall through to `NO_SPONSOR_PHRASES`; silence — and `[]` with nothing retrieved — still reaches the floor; `authorization` records a verdict even when no clause was asked and no LLM call was made | `test_screen.py` (`test_unusable_labels_drop_the_check_rather_than_guessing`, `test_a_miscounted_answer_does_not_fall_through_to_the_floor`, `test_an_empty_label_array_against_retrieved_snippets_is_a_bad_count_not_silence`, `test_an_empty_label_array_with_nothing_retrieved_still_reaches_the_floor`, `test_the_phrase_floor_runs_only_when_no_labels_arrived`, `test_authorization_records_a_verdict_even_with_no_llm_call_at_all`) |
| The `sponsor`-only vocabulary's recall trade is pinned in both directions — exactly 6 of 13 must-flag sentences retrievable, 7 deliberately given up — so it cannot drift silently, and no genuine offer is ever disqualified | `test_screen.py` (`test_the_narrowed_vocabulary_names_exactly_which_bars_it_gives_up`, `test_every_must_keep_sentence_survives_the_code_path`) |
| Clearance disqualifies only when a `CLEARANCE_TOKENS` match is present in the JD description **or** the title; an ungrounded `requires_clearance: true` keeps, science/scientist never grounds, and the Stage 4 fallback obeys the same floor | `test_screen.py` (`test_ungrounded_clearance_claim_keeps_the_posting`, `test_clearance_grounded_in_the_title_alone_disqualifies`, `test_science_words_do_not_ground_a_clearance_claim`) |
| Deterministic location gate (`location_verdict`, pycountry + geonamescache, evidence-tiered): a NAMED country / US state decides alone and outranks the remote hint; city/subdivision evidence is diacritic-folded, votes for every reading it allows, and discards only when corroborated; region acronyms are a stoplist; any allowed evidence keeps | `test_location.py` (`test_resolve_location`, `test_location_verdict_marks_what_escalates`, `test_token_country_*`, `test_folding_is_the_same_function_everywhere`) + gate integration tests in `test_location.py` |
| **Zero false discards** over every distinct location string in the live DB, gated in CI against a committed corpus labeled by an INDEPENDENT oracle (not by the code under test); the residual leak set is pinned EXACTLY, in both directions, so the accepted trade cannot drift silently | `test_location.py` (`test_no_us_eligible_string_is_ever_discarded`, `test_the_leak_set_is_pinned_exactly`, `test_the_corpus_is_labeled_the_way_the_gate_assumes`, `test_a_discard_always_names_a_country_the_string_actually_mentions`), `tests/fixtures/location_corpus.jsonl` |
| Fetch-time max-age + title_exclude drop | `test_fetch.py::test_prefilter_*` |
| Deterministic gate hoisted to fetch (discarded, no Ollama) | `test_pipeline.py::test_run_fetch_marks_location_miss_discarded` |
| The code-side gates (intern title, location string) run BEFORE the model call and short-circuit it: a row they disqualify makes no backend call, carries no `provider_error`, and its reason is the deterministic one alone | `test_screen.py` (`test_a_deterministically_disqualified_row_never_reaches_the_provider`, `test_a_deterministic_gate_short_circuits_the_model_reason`, `test_multiple_failing_gates_join_reasons`), `test_pipeline.py`  |
| A provider error never disqualifies on the sponsorship **phrase floor** — the deterministic gates still stand, but the blunt whole-description scan is skipped and `authorization` is left absent; `SCREEN_BACKEND=none`, which has no provider to fail, still records that floor verdict | `test_screen.py` (`test_a_provider_error_never_disqualifies_on_the_sponsorship_phrase_floor`, `test_screen_backend_none_still_records_the_authorization_floor_verdict`) |
| A **blind** live backend (nothing usable: not a dict, or neither a `screen` object nor any requirement key) is a `provider_error`, not a verdict; the FLAT shape the 4B emits ~1 call in 100 is a real verdict and is honoured, byte-identical to the nested shape — so it cannot discard on the phrase floor and cannot record breaker successes; the narrow scope is pinned on the other side, where an empty `screen` dict is an answer and keeps the floor | `test_screen.py` (`test_a_blind_response_is_a_provider_error_not_a_verdict`, `test_an_empty_screen_object_is_a_verdict_and_keeps_the_floor`, `test_the_flat_shape_is_a_verdict_and_is_honoured`, `test_the_flat_shape_and_the_schema_shape_agree`, `test_the_observed_flat_response_is_kept_not_discarded`) |
| `mark_failed` → terminal `failed` + `attempts+1` (fetch/score paths) | `test_db.py` |
| Discovered-jobs verdict-aware buckets (matched/belowbar/discarded/lowcontext/failed, mutually exclusive; keep needs `seniority=match`, then domain splits match→matched / adjacent→belowbar; discarded = hard-constraint failures **plus** fit-verdict rejects; low-context = thin-JD **or** `insufficient_context` flag) + sort (score/posted) + pagination + disqualification-cause sub-filter + bulk remove/reopen/removeAllInView; per-row dismiss → `removed` | `web/src/__tests__/actions.test.ts`, `actions.int.test.ts`, `web/src/components/__tests__/DiscoveredJobsTable.test.tsx` |
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
| Feed inherits `title_filter`/`title_exclude`/`max_age_days` before the resolve; epoch-date and `title`->`job_title` translation | `test_feed_pipeline.py` |
| The feed re-runs the age gate on the BOARD's `posted_at` before upsert, so a fresh-per-feed evergreen req is not stored older than `max_age_days` | `test_feed_pipeline.py` (`test_run_feed_re_gates_on_the_boards_date_not_the_feeds`) |
| An unreadable lock fails loud; a contender never names a dead pid as the holder, but does name a live one | `test_run.py` (`test_an_unreadable_lock_fails_loud_instead_of_degrading`, `test_a_contender_never_names_a_dead_pid_as_the_holder`, `test_a_contender_names_the_holder_when_the_pid_is_live`) |
| `run_feed` keeps only surfaced ids, records unresolved, skips existing, isolates a bad board, stamps `company_slug` | `test_feed_pipeline.py`, `test_feed_simplify.py` |
| Promotion suggestions (signal, exclude watched/dismissed + feed-only sources) + dismiss | `web/src/__tests__/promotion.test.ts`, `promotion.int.test.ts` |
| Unresolved-feed grouping by host+reason | `web/src/__tests__/unresolved.test.ts`, `unresolved.int.test.ts` |
| Watchlist DB helpers (import idempotent, record_unresolved upsert, existing ids) | `test_watchlist_db.py` |
| Watchlist auto-seed-on-empty + feed wiring in `run_once` | `test_run.py` |
| `feeds:` config parsing + defaults | `test_feed_config.py` |
| Watchlist actions (list / add+validate+dedup / remove) | `web/src/__tests__/watchlist.test.ts`, `watchlist.int.test.ts` |
| iCIMS + Phenom adapters (server-HTML cards; pcsx search + per-job detail) | `test_icims.py`, `test_phenom.py` |
| A stub-rejected phenom posting costs no detail GET | `test_phenom.py::test_stub_gate_hydrates_only_the_survivor` |
| A phenom search **403** mid-pagination is a throttle: retried like a 429, and on a persistent one the pages already walked are kept rather than the board being lost, with the truncation announced; a 403 on the FIRST page still raises, on a bounded budget | `test_phenom.py` (`test_search_403_mid_pagination_is_retried_like_a_429`, `test_persistent_403_mid_pagination_keeps_the_pages_already_collected`, `test_a_403_on_the_first_page_still_raises`, `test_a_salvaged_board_says_so`) |
| An unknown keep verdict fails open | `test_phenom.py::test_stub_gate_fails_open_on_an_unknown_verdict` |
| A stub-rejected workday posting costs no detail GET | `test_fetch_new.py::test_workday_stub_gate_skips_the_dropped_detail_call` |
| A workday `discard` HYDRATES rather than storing a GUID-less stub row | `test_fetch_new.py::test_workday_stub_gate_hydrates_a_discard_instead_of_storing_it` |
| The workday gate stub carries no `external_id` (unstorable by construction) | `test_fetch_new.py::test_workday_parse_stub_carries_no_external_id` |
| The gate never changes a row's status | `test_pipeline.py::test_run_fetch_gated_batch_matches_the_ungated_statuses` |
| Pinpoint + Workday board adapters | `test_fetch_new.py` |
| Custom-recipe executor (`json`/`next-data` modes, paging, fields map, `detail` hydration) | `test_custom.py` |
| Shared detail stage (extractor picked by document type, stub gate, board-level breaker, unsafe-URL skip) | `test_detail.py` |
| Browser-recipe executor (CSS extraction, detail circuit-breaker, SSRF guards on scraped URLs) | `test_browser.py` |
| Embedded-greenhouse enriching resolver (token scrape → greenhouse ingest) | `test_embedded_gh.py` |
| SSRF guard (`is_safe_public_url` / `get_redirect_safe` re-validates every redirect hop) + util helpers | `test_util.py` |
| Config load/validate (sources, slugs, recipes, candidate block, and screen-only fit-profile skip) | `test_config.py` |
| `add_watched` CLI watchlist write boundary | `test_add_watched.py` |
| Cross-service sync guard (source enums + low-context threshold + SPEC's source-coverage matrix) | `test_source_enums_sync.py` |
| Quota telemetry is one HTTP GET per pass against the ACTIVE backend's usage endpoint (codex `/backend-api/codex/usage`, Claude Code `/api/oauth/usage`), **retried up to `_ATTEMPTS` (4) on a retryable failure — 403/429/5xx and transport errors — while a 401/404 is a verdict and is not retried**; `capture_usage` never raises and keeps the last-good snapshot on a failed fetch | `test_usage.py` (`test_which_statuses_are_worth_retrying`, `test_a_retryable_failure_is_retried_and_the_recovery_is_kept`, `test_a_verdict_status_is_not_retried`, `test_the_attempt_bound_and_the_sleep_schedule_are_the_module_defaults`, `test_fetch_codex_usage_normalizes_the_window`, `test_codex_usage_sends_a_non_default_user_agent`, `test_fetch_claude_usage_prefers_the_limits_array_and_keeps_the_model_scope`, `test_claude_usage_falls_back_to_the_flat_buckets`, `test_capture_usage_keeps_the_last_good_snapshot_when_the_fetch_fails`, `test_capture_usage_never_raises`), `test_run.py`  |
| A failed quota capture is announced **with its cause**, not swallowed — every route to a `False` return names what happened (status+reason, exception type, or which precondition failed — including a 200 whose body is not an object, and on the claude path as well as codex), including `http.client.HTTPException`, which subclasses neither `OSError` nor `ValueError`; plus the `[quota] WARNING` on the `False` return, and an offset-aware `as_of` in every written snapshot so a stale reading is legible without an mtime check | `test_usage.py` (`test_get_json_names_the_http_status_when_the_provider_raises`, `test_get_json_names_the_exception_when_the_connection_fails`, `test_a_truncated_body_is_caught_and_named`, `test_a_200_with_no_usable_window_says_so_instead_of_going_quiet`, `test_a_200_that_is_not_the_expected_shape_says_so`, `test_a_200_whose_body_is_not_an_object_says_so`, `test_an_unanticipated_failure_cannot_colour_the_pass_and_still_says_why`, `test_capture_usage_stamps_as_of_so_a_stale_reading_is_legible`), `test_run.py`  |
| Missing Codex credentials or usage HTTP 401 set a re-login notice (prefixed with a non-default `CODEX_HOME`); transient failures retain prior telemetry and successful capture clears the notice; `codex` screen passes capture usage | `test_codex_login_notice.py`, `test_run.py::test_run_once_defaults_codex_to_luna_medium`, `CodexLoginNotice.test.tsx`, `e2e/codex-login.spec.ts` |
| `/api/health` 200/503 probe; `/api/scorer-usage` snapshot route (incl. backend passthrough); usage-bar labelling | `web/src/__tests__/health.test.ts`, `scorer-usage.test.ts`, `web/src/components/__tests__/ScorerUsageBar.test.tsx` |
| Core UI rendering (tabs, KPI grid, application table, add form, pagination, history modal) | `web/src/components/__tests__/` (`Dashboard`, `KPIGrid`, `ApplicationTable`, `AddApplicationForm`, `Pagination`, `StatusHistoryModal`) |
| All jobs inventory directly queries/counts every non-removed lifecycle without fit-bucket scans, defaults to stable discovery recency, matches the shared standalone outcome fixture, escapes literal full-text search, scopes per-row actions and rejects All bulk mutations | `web/src/__tests__/inventory-query-shape.test.ts`, `web/src/__tests__/inventory-contract.int.test.ts` |
| Web/MCP triage classification, SQL filtering before paging, overview partition, raw screen-outcome compatibility, legacy rule-only detection, duplicate-member rejection, mathematically integral JS-safe legacy revisions, unknown-lifecycle priority and bounded summaries agree on the shared synthetic contract fixture | `web/src/lib/__tests__/triage-summary.test.ts`, `web/src/__tests__/inventory-contract.int.test.ts`, `web/src/__tests__/inventory-query-shape.test.ts`, `worker/tests/test_mcp_repository.py::test_job_triage_contract_fixture`, `test_job_triage_filter_summary_and_overview_share_one_partition`, `worker/tests/test_mcp_protocol.py` |
| Inventory filter/page requests hide stale rows, retain the selected view across tabs, and discard an older response after a newer request resolves | `web/src/components/__tests__/Dashboard.test.tsx` (`overlapping inventory requests never show stale rows under newer filters`), `web/e2e/discovered.spec.ts` |
| Unknown lifecycle names cannot crash inventory rendering; impossible calendar dates and invalid assessment times remain null with shared Python/web timestamp fixtures | `web/src/components/__tests__/DiscoveredJobsTable.test.tsx`, `web/src/lib/__tests__/screen-summary.test.ts`, `worker/tests/test_mcp_repository.py` |
| Synthetic browser flow: newest unscored job, full JD, all-text search, second page, retained Matched details and All-jobs application workflow | `web/e2e/discovered.spec.ts`, `apply-loop.spec.ts` |
| Integration-harness self-check (real Prisma round-trip on the temp DB) | `web/src/__tests__/harness.int.test.ts` |
| Dead-link sweep: 404/410 → `expired`, every other error leaves the row live, queue rotation | `test_pipeline.py` (`run_expire`) |
| Explicit one-shot source refresh stays within 1–25 SmartRecruiters requests without following redirects, selects only unscored/unlinked rows without fit assessment, validates identity and visible core JD content, preserves state on inconclusive/closed results, reopens source availability without relabeling detail-check time, and skips concurrent eligibility changes | `test_source_lifecycle.py`, `test_run.py::test_run_once_unscored_refresh_runs_as_an_isolated_source_only_mode`, `test_smartrecruiters.py` |
| Explicitly inactive SmartRecruiters details cannot insert or reopen a source observation on normal feed/watchlist ingestion; missing `active` remains compatible and normal ingest never records closure | `test_smartrecruiters.py` (`test_fetch_one_rejects_an_explicitly_inactive_detail`, `test_fetch_skips_explicitly_inactive_detail_but_keeps_missing_active_compatibility`), `test_feed_pipeline.py` (`test_run_feed_does_not_insert_smartrecruiters_explicitly_inactive_detail`, `test_run_fetch_does_not_reopen_closed_smartrecruiters_row_from_inactive_detail`), `test_source_lifecycle.py` |
| Complete source content is hashed/revisioned; duplicate listings only advance seen time; completed fit and standalone assessments capture the source revision; changed content makes old screen evidence stale without a provider rerun | `test_source_lifecycle.py`, `test_db.py`, `test_screen_pipeline.py` |
| Tracker shows confirmed source state, inconclusive attempt and separate fit/screen freshness in list and detail views; invalid source timestamps and invalid captured revisions remain null/unknown | `web/src/lib/__tests__/source-lifecycle.test.ts`, `web/src/components/__tests__/DiscoveredJobsTable.test.tsx`, `web/src/components/__tests__/JobDetailModal.test.tsx` |
| Read-only MCP job list/detail exposes bounded source state and freshness summaries without leaking raw errors or JD text; invalid captured screen revisions remain unknown | `tests/test_mcp_repository.py::test_source_lifecycle_separates_state_from_fit_and_screen_freshness`, `test_source_lifecycle_invalid_screen_revisions_are_unknown_in_list_and_detail`, `test_source_lifecycle_rejects_boolean_screen_revisions`, `test_source_lifecycle_rejects_unsafe_current_fit_and_screen_revisions`, `test_source_lifecycle_accepts_maximum_safe_revision` |
| Explicit unlimited screen mode processes more than 40 provider calls, reuses completed cache, preserves the dead-provider breaker; CLI rejects out-of-mode/conflicting use, and explicit unlimited overrides the environment cap while zero stays invalid | `tests/test_screen_pipeline.py` (`test_unlimited_screen_exceeds_default_cap_and_still_caches_success`, `test_unlimited_screen_retains_dead_provider_breaker`), `tests/test_run.py` (`test_screen_unlimited_cli_overrides_environment_limit`, `test_screen_only_invalid_combinations_fail_before_config_or_db`) |
| Standalone screen calls preserve the existing deprioritized queue order under the provider-call cap; demoted rows remain reachable after priority rows | `tests/test_screen_pipeline.py::test_screen_provider_cap_preserves_existing_deprioritized_queue` |
| Direct `run_once` rejects conflicting modes and invalid screen caps before opening or seeding a database | `tests/test_run.py::test_run_once_invalid_modes_fail_before_opening_database` |
| MCP recipe list/detail reads redact conventional secret query keys even in malformed URLs, including percent-encoded keys | `tests/test_mcp_repository.py::test_malformed_url_query_secrets_are_redacted_in_all_recipe_reads` |
| MCP repository uses SQLite `mode=ro` + `query_only`, fails without creating/incompletely accepting a DB, returns current WAL commits, and exposes only bounded, allowlisted, parameter-bound model reads with scoped cursors, chunked text, secret redaction, approved settings, and unknown/orphan data preserved | `tests/test_mcp_repository.py` (`test_database_is_opened_read_only_and_query_only`, `test_each_query_opens_a_live_connection_that_sees_committed_wal_writes`, `test_missing_or_incomplete_database_fails_safely_without_creating_file`, `test_cursor_is_bounded_and_does_not_store_filter_text`, `test_all_ats_entities_are_allowlisted_and_json_is_reported`, `test_malformed_recipe_is_withheld_without_leaking_raw_value`, `test_valid_json_that_is_not_a_recipe_object_is_withheld`, `test_entity_input_cannot_select_arbitrary_sql`) |
| MCP advisory standalone outcomes agree across filtering, list summaries, detail summaries and overview counts, keep legacy evidence separate, preserve unknown/contradictory cases, and bound/redact summary reasons | `tests/test_mcp_repository.py` (`test_standalone_screen_outcomes_share_synthetic_contract_fixture`, `test_screen_summaries_bound_and_redact_untrusted_reasons`, `test_assessment_time_unknowns_and_eligible_screen_counts_are_explicit`) |
| MCP metadata/all-text search, escaped literal metacharacters, UTC assessment windows (including fractional precision), filter-scoped cursors, first-page id ceiling, current-state traversal and payload bounds behave as specified | `tests/test_mcp_repository.py` (`test_all_text_search_is_opt_in_literal_and_keeps_descriptions_chunk_only`, `test_screening_windows_use_utc_instants_and_id_ceiling`, `test_screening_windows_preserve_fractional_precision_beyond_microseconds`, `test_job_cursor_ceiling_and_live_pages_make_no_snapshot_claim`, `test_screening_change_behind_cursor_is_found_by_reconciliation`, `test_large_generated_all_text_search_filters_before_limit_and_bounds_payload`) |
| MCP protocol advertises only read-only/closed-world tools, keeps all ten names, exposes research filters, returns structured data and safe errors, leaves application rows unchanged, and serves list → next page → get_job → all chunks through local stdio | `tests/test_mcp_protocol.py` (`test_in_memory_protocol_lists_read_only_tools_and_returns_structured_data`, `test_protocol_errors_are_actionable_without_exposing_database_paths`, `test_stdio_subprocess_uses_protocol_and_only_reads_its_configured_database`, `test_stdio_research_path_pages_gets_chunks_and_reports_safe_error`); CI installs `requirements-mcp.txt` so these cannot skip there |
| Standalone screen assessment times are sampled after each provider result on the DB thread and passed from `run.py` | `tests/test_screen_pipeline.py::test_screen_saves_sample_clock_after_each_result_on_the_db_thread`, `tests/test_run.py::test_run_once_defaults_codex_to_luna_medium` |
| Synthetic assessment projection compares the complete opaque identity, keeps freshness separate from latest attempt, preserves saved results after malformed or failed attempts, bounds/redacts the view, matches ASCII timestamp and boundary-truncation behavior across Python/TypeScript, and labels shortened text in the panel | `worker/tests/test_preselection_view.py::test_fixture_cli_keeps_saved_success_when_latest_attempt_state_is_unhashable`, `web/src/lib/__tests__/assessment-view.test.ts`, `web/src/components/__tests__/AssessmentPanel.test.tsx` |
| Worker SQL fixture ↔ `schema.prisma`, including `job_screenings`, in sync | `test_schema_sync.py` + `tools/check_schema_drift.mjs` (CI) |
| JEV: skip only on weak preference or a 3+ year floor; caps, re-queue on policy/source change, unknown charge stops the pass; MCP default hides only current skips | `test_jev.py`, `test_mcp_repository.py::test_jev_filter_*` |
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
- **Server Actions, not REST.** The UI mutates through Server Actions. The
  `/api/v1` routes exist for the MCP server only and wrap the same actions, so there
  is one write path; `GET /api/health` is an HTTP-status probe for the Docker
  healthcheck.
- **The screen extracts, code decides.** The hard-requirements SCREEN defaults to local
  Ollama on the GPU, free and rate-limit-free, `qwen3.5:4b` (fits an 8 GB card,
  `think:false` so reasoning models still return JSON). It only extracts JOB facts; CODE
  applies the candidate's constraints, since a 4B model is unreliable at the pass/fail
  judgment itself — and keeping the judgment code-side makes every backend behave alike.
- **Charts are mostly hand-rolled SVG.** Heatmap, funnel, and Sankey are written
  directly so they render exactly right on dark backgrounds without per-library
  theming; only the donut uses Recharts. The Sankey palette is deliberately
  desaturated so flow geometry leads, not color.
- **Fully dependency-injected worker.** Every external (board APIs, screen providers) is
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
  config (`config.yaml`), the database (`db/`), and local
  `job_search_profile_*_with_evidence/` source archives are gitignored. The repo ships
  only `*.example` templates; real resume files are untracked, so no extra git
  steps are needed for *new* work (see `CONTRIBUTING.md`). **Closed:** `resume.txt`
  and the real `config.yaml` were committed 2026-06-05 and untracked 2026-06-08;
  the blobs were purged from all history with `git filter-repo` and force-pushed
  (see CHANGELOG).
- **Reliability / error recovery:** one bad posting or flaky external never aborts a
  batch — the failure is recorded and processing continues. A *systemic* screen-provider
  outage circuit-breaks the pass, leaving rows retryable, rather than convicting every
  posting (contract in §9, "Failure handling and recovery limits").
- **Concurrency safety:** WAL + `busy_timeout=5000` ms + the directory mount, as
  §6/§10 describe — safe under low write-contention, not a guarantee under sustained
  dual-write load.
- **Performance:** the local hard-requirements screen runs ~2 s/posting on an 8 GB
  GPU; a hosted screen backend is one call per posting.
  The root page is `force-dynamic` (no stale cache).
- **Time zone:** the heatmap uses the server's local "today"; set `TZ` on the
  container if deploying in a different zone from where you live.
- **Security:** the JOB text is marked as *data, not instructions* in the screen
  prompt (a posting can't inject directives); secrets live only in the gitignored
  `.env`, read by `run.py`.
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
  - **`/api/v1` keys are static bearer secrets** read from the env, compared in
    constant time, with no rotation or expiry. The API is reachable only on the
    loopback bind (or the operator's `WEB_BIND` mesh) and is off unless a key is set;
    the Server Actions beside it remain unauthenticated by design, so `actor` is an
    attribution aid, not proof: any loopback client of an action can stamp `mcp`.
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
  - **JD prompt-injection can skew a screen verdict, not leak a secret** — the CLI
    screen backends run tool-less (§7.1), so a hostile JD can't read or exfiltrate
    anything; it could still talk the model into a wrong extraction, and code decides
    pass/fail from it.
  - **The optional ATS MCP deliberately sends selected business data to the connected
    model through Secure MCP Tunnel.** Its local process is stdio-only and exposes no
    write tool, but it has no per-record or per-user authorization layer. Tunnel and
    ChatGPT workspace permissions govern who can connect; a shared workspace or plugin
    should therefore be limited to people trusted with the ATS data. Job descriptions,
    application notes, and recipe fields remain untrusted model input. Header values and
    conventional secret URL query values are redacted, but all other returned ATS data
    is available to a caller with access.

---

## 12. Setup and deployment

*Class: **Snapshot** — current build; if code disagrees, update this spec.*

This section is the authoritative command list.
[`SETUP.md`](./SETUP.md) is the friendlier front door — prerequisites in table
form, the tracker-only vs. full-pipeline decision, and which settings live in
`config.yaml` vs. the DB — and links back here for the commands themselves.

**Prerequisites:** Docker + Compose (≥ 24) for the web app; Node 24+ and Python
3.11+ for local non-Docker dev/tests **and to run the worker**, which is native,
not containerized (§6); for the hard-requirements screen, Ollama reachable — a
local GPU, or a remote/cloud instance via `OLLAMA_HOST` — **or** one of five other
`SCREEN_BACKEND` values (`codex`, `claude-code`, `claude-api`, `openai-api`,
`none`; §7.1) if there is no GPU and no Ollama at all.

`make setup` bootstraps a checkout in one command (web + worker deps, `db-push`,
and non-clobbering `*.example` template copies); `make doctor` is the preflight —
one status line per prerequisite, exiting non-zero only when a *universal* one
(worker deps + a set-up DB) is missing, while provider rows (ollama/codex/claude/…)
report `ok`/`no` without failing the exit code.

**Web app only (no pipeline):**

```bash
# Local dev
cd apps/web && npm install && npx prisma generate && npm run dev   # :3000
npx prisma db push          # if db/applications.db doesn't exist yet
# Docker, web service only
UID=$(id -u) GID=$(id -g) docker compose up web --build -d
```

**Full pipeline:** `make setup` does deps, `db-push`, and steps 1 and 2's **config**
copies (only when the target is absent); then fill in the copied files. Longhand:

1. `cp apps/worker/config.yaml.example apps/worker/config.yaml` — set `companies`
   (`source` ∈ the eleven watchlist-capable boards {greenhouse, lever, ashby,
   workday, pinpoint, smartrecruiters, workable, icims, phenom, custom, browser},
   board `slug`, `name`), optional `title_filter`, the `candidate` hard-constraint
   block, `schedule_hours` (24). Workday's `slug` packs `tenant/datacenter/site`
   (quote it).
2. `cp apps/worker/.env.example apps/worker/.env` — fill `OLLAMA_HOST`
   (`http://localhost:11434`), plus `ANTHROPIC_API_KEY` for `--screen-backend
   claude-api` or `OPENAI_API_KEY` for `--screen-backend openai-api`. Optional
   overrides: `OLLAMA_MODEL`, `SCREEN_BACKEND`, `SCREEN_MODEL`, `SCREEN_EFFORT`,
   `SCREEN_LIMIT`, `SCREEN_WORKERS`, `OLLAMA_NUM_CTX`. The `codex`/`claude-code` screen
   backends authenticate from the CLI's own login, not from `.env`.
3. On the host: `ollama pull qwen3.5:4b && ollama serve` — only needed for the
   default `SCREEN_BACKEND=ollama`; skip it entirely on one of the five other
   screen backends (§7.1).
4. From the repo root: `UID=$(id -u) GID=$(id -g) docker compose up --build -d`
   (or `make up`) starts the **web app + autoheal only** — the worker is **not**
   containerized (§6, removed 2026-07-16). Run it natively on the same host:
   `cd apps/worker && python -m ats_worker.run` — but for anything unattended install the
   **systemd user unit** instead (§6): a shell-run daemon dies with the terminal, is not
   restarted, and does not appear in `make doctor`'s daemon row. Note the daemon needs
   `apscheduler` from `requirements.txt`, which `requirements-dev.txt` omits — `--once`
   never imports it, so a tests-only checkout crash-loops as a daemon and `make doctor`
   flags that on its `daemon dep` row. It runs **no pass at launch** — passes
   fire on wall-clock slots every `schedule_hours` (add `--run-now` for one immediately).
   It prints the resolved slots and timezone on startup, because with no eager pass a
   fresh daemon is otherwise indistinguishable from a hung one for up to
   `schedule_hours`:
   ```
   [schedule] passes at 0,4,8,12,16,20:00 America/New_York (every 4h, wall-clock)
   ```
   **The timezone comes from `tzlocal`**, so a host running UTC defeats the point of
   wall-clock slots. `TZ=America/New_York` in the environment is the no-code override.

**Read-only MCP:** apply the Prisma schema from the repository root (`make db-push`)
before first use of an existing database, so `job_screenings` is present; the worker
does not issue DDL. Install the optional pinned dependency with
`cd apps/worker && pip install -r requirements-mcp.txt`, then run
`ATS_DB_PATH=/absolute/path/to/applications.db python -m ats_worker.mcp` from
`apps/worker`. `ATS_DB_PATH` may be omitted when the checkout's default Prisma database
path is correct. This starts a stdio child process, not a web listener; do not run it
with a different database path than intended. The MCP has no writes or authentication
of its own, so tunnel/workspace access must be restricted to trusted users. See the
worker README for setup through OpenAI Secure MCP Tunnel; ChatGPT connectivity remains
separate from the local server's stdio tests.

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
| `make eval-screen` | hard-requirement accuracy gate for the **screen** prompt vs `apps/worker/eval/screen_golden.jsonl` — **PASS = zero false disqualification**, judged on *any* of K=3 draws, not the majority: a check that discards a good posting one time in three is not a passing check. Recall and flip-rate are **reported, never gated** — a miss reaches the human, a false discard is reviewed by nobody. 83 rows / 249 calls on local Ollama, free, ~10 min (**manual, not a CI gate** — CI has no Ollama). `SCREEN_BACKEND` A/Bs a hosted backend, and the run mirrors production's model resolution exactly — `OLLAMA_MODEL` / `SCREEN_MODEL` **and** `OLLAMA_NUM_CTX`, which feeds both the screener and `screen_posting`'s `num_ctx*2` JD cap; the report header names the model actually used (the real `DEFAULT_*_SCREEN_MODEL`, not "backend default"), since that is what an A/B is diffed on. `--selftest` is a free hermetic check of the gate logic and the corpus's own invariants — including that a row labeled as a **bar** carries that requirement's vocabulary in its own excerpt+title (`unsupportable_bars`). That is a check on the CORPUS, not the model: an excerpt truncated before the sentence its label rests on is a guaranteed miss for any model or prompt, so recall computed over it is meaningless. Only the bar direction is asserted — for clearance and sponsorship, absence of the vocabulary *is* the evidence of no bar. The corpus is gitignored (`apps/worker/eval/`), so the gate is only reproducible with the operator's local files |
| `make db-push` | sync Prisma schema into SQLite |
| `make up` / `make down` | Docker Compose stack up/down |

- **Web:** Jest unit (`jest.config.ts`, Prisma mocked via `jest-mock-extended`) +
  integration (`jest.integration.config.ts`, real Prisma over a throwaway SQLite) +
  merged coverage (`jest.all.config.ts`). Playwright e2e (`e2e/`) runs against a
  seeded throwaway DB and is gated in CI.
- **Worker:** pytest, **fully dependency-injected** — no network / Ollama / Claude
  needed. `integration` marker runs `run_once` end-to-end over
  a temp SQLite. Coverage floor `fail_under = 84` (single source of truth in
  `pyproject.toml`, read by both `make test-coverage` and CI).
- **CI** (`.github/workflows/ci.yml`): runs both suites on push / PR / nightly, with
  coverage gates, web lint + `prisma generate`, the schema-drift and privacy guards,
  and a gated Playwright e2e job.
- **Schema-drift guard:** `tools/check_schema_drift.mjs` fails if
  `apps/worker/tests/fixtures/schema.sql` and `apps/web/prisma/schema.prisma` fall
  out of sync.
- **Privacy guard:** `tools/check_privacy.mjs` (`make check-privacy`) fails if git
  *tracks* any private file — `.env` **and every `.env.<suffix>` variant** (`.bak`,
  `.local`, `.production`; `.gitignore` matches `.env*` for the same reason, since a
  literal rule left a backup both unignored and unchecked), `config.yaml`, `db/` or any `*.db`,
  `apps/worker/resume/` (bar `README.md` / `*.example`), `apps/worker/eval/`,
  `resumes/`, and root-level `job_search_profile_*_with_evidence/` source archives.
  `.gitignore` only guards the default path; this catches `git add -f`,
  a loosened ignore rule, or a pre-existing commit. Path deny-list only (no content
  scan); `--self-test` asserts the allow/deny regexes still discriminate, and CI runs
  both.
- **Candidate profile and frozen replay — offline tooling only.**
  `ats_worker/preselection/profile.py` validates the closed schema-1 profile, stable
  block IDs, version/date/status and one-paragraph text, then renders all background and
  preference blocks in declared order. An injected tokenizer measures the complete
  context against a soft budget; overflow is reported without truncation. The profile
  CLI reads only an explicit input and reports hashes/counts without profile text; a
  rendered-file mismatch exits nonzero, and rendered output cannot alias the profile
  input. The replay CLI validates a closed snapshot
  containing the profile, exact rendered context, normalized payload for every row, and
  manifest. Source and external IDs are non-empty trimmed text; company, title, URL and
  description must contain non-whitespace text; location and posted-at may be null.
  It recomputes versions, hashes, counts and UTC-day membership from inputs;
  a digest alone is not proof. This establishes consistency of the supplied pool, not
  whether the producer omitted eligible postings. No independent source roster is
  available, so every frozen replay is `INCONCLUSIVE`, even if a partial pool has a
  recomputed manifest. Splits keep complete days, duplicate/template groups and repeated
  `(source, external_id)` identities together; K is allocated to each complete day in
  each split. Unresolved labels remain in the counts and make recall inconclusive.
  Reports contain aggregate metrics and hashes only, with no row/group IDs or source or
  profile text; the split seed is represented by a domain-separated SHA-256 fingerprint,
  while the caller retains the raw seed for reproduction. The daily role-coverage
  baseline uses the same deterministic greedy score and recency/item-ID tie order as the
  full ordering, and its daily orders are reused across requested budgets. The legacy
  ID-only pool also remains inconclusive. This tooling has no
  provider, database, runtime-selection, quality-threshold or acceptance-GO wiring.
  Malformed or excessively nested JSON, oversized integer tokens and timestamps outside
  UTC's representable range return bounded validation errors. Connected-group assignment
  handles large valid inputs without recursion-depth failures; a pool with too few
  independent groups returns a bounded validation error.
- **Preselection shadow assessment and offline evaluation — isolated tooling only.**
  `preselection/extraction.py` validates JD-quoted requirement spans and required versus
  preferred experience facts; its YOE policy returns `exclude`, `not_excluded` or
  `unresolved` with evidence and an explicit policy version. `questions.py` validates the
  versioned question set and exact typed assessment answers. `shadow.py` is default-off
  and accepts an injected transport, model identity, limits, clock and private journal;
  there is no provider adapter or `run.py` wiring. Its bounded worker accounts for
  attempts, retries, elapsed time, usage and actual/estimated/unknown charges. Journal
  schema 4 persists `RunBinding` over the frozen run declaration, profile, question set,
  pool fingerprint and split manifest. Resume rejects changed bound inputs before a
  transport call. Bound assessments require the matching validated `EvaluationInput` cohort;
  job membership, declared variant and per-item draw are checked before journal writes,
  cache reuse or extraction/assessment transport. Standalone extraction with a bound
  journal requires the same cohort and membership check. Execution recomputes frozen
  pool, split and run-declaration hashes, rejecting mutated or replaced cohort contents.
  Actual assessor/extractor models and limits/retry fingerprints must match the frozen
  declaration before persistence, cache reuse or transport. Unbound single-job synthetic calls remain
  available. Instruction-injection fixtures verify JD text cannot alter the system prompt,
  candidate context or typed response contract; they do not establish live model resistance.
  `evaluation.py` validates explicit pseudonymous manifests and their
  matching journal. Report generation reparses the retained canonical manifest, rejects
  changed labels, baselines, outcomes or provenance, and uses the validated snapshot and
  a copied journal throughout calculation. It checks outcomes against successful responses and emits aggregate
  metrics without row IDs, answer values, evidence text or the raw split seed. Its report
  uses a domain-separated seed fingerprint; oversized/deep JSON and UTC-normalization
  overflow return bounded validation errors. The checked-in assessment and evaluation
  fixtures are synthetic. No live provider calls, real cost/quality claims,
  acceptance GO, production wiring, database writes or runtime selection are included.

---

## 14. References

- **Status (in flight, pick order, defects):** [`PROGRESS.md`](./PROGRESS.md); the open
  catalogue is [`BACKLOG.md`](./BACKLOG.md), turned-down proposals
  [`REJECTED.md`](./REJECTED.md)
- **Release history:** [`../CHANGELOG.md`](../CHANGELOG.md)
- **Contributor conventions:** [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Design principles (decision DNA):** [`PRINCIPLES.md`](./PRINCIPLES.md)
- **Session protocol & definition of done:** [`DEVELOPMENT.md`](./DEVELOPMENT.md)
- **Setup front door:** [`SETUP.md`](./SETUP.md)
- **Service READMEs:** [`../apps/web`](../apps/web), [`../apps/worker/README.md`](../apps/worker/README.md)
- **Code anchors:** schema `apps/web/prisma/schema.prisma` · enums
  `apps/web/src/lib/constants.ts` · server actions `apps/web/src/lib/actions.ts` ·
  pipeline `apps/worker/ats_worker/pipeline.py` · wiring `apps/worker/ats_worker/run.py`
