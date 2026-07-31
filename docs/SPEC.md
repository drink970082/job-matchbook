# Job Matchbook — System Specification

> **Authoritative source of truth for this repository.** This document describes
> the system *as it actually exists* and is written to be verified against the
> code. When code and this spec disagree, that is a bug in one of them — fix it,
> don't let them drift. New work should update this file in the same change.
>
> Companion documents: [`PROGRESS.md`](./PROGRESS.md) (live delta: in flight, the pick
> order, open defects) and its two on-demand halves [`BACKLOG.md`](./BACKLOG.md) (the
> open catalogue) + [`REJECTED.md`](./REJECTED.md) (turned-down proposals),
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

**Guarding the guard.** The sidecar's health check was, until 2026-07-28, the image's
`pgrep -f autoheal` — a check that **cannot fail while the container runs**, because
`Cmd=["autoheal"]` puts that string in the process's own argv and the check matches
itself. Zero signal. It is now a socket **ping** (`curl --unix-socket … /_ping`), which
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

- **`run.py` — entrypoint & wiring.** CLI: `--once` (single pass then exit) vs the
  daemon, which fires on **wall-clock slots** — `cron_hours(h)` renders
  `range(0, 24, h)` into APScheduler's `hour=` string (`4` -> `0,4,8,12,16,20`), so
  passes land at 00:00/04:00/08:00 regardless of when the daemon started and a restart
  cannot re-phase the day. **The daemon runs NO pass at launch**; `--run-now` restores
  that on demand and is rejected together with `--once`. Flags: `--config`,
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
  `--score-max-id N` (score only `new` rows with `id <= N`, 0 = no bound — the selector
  to `--score-limit`'s budget, applied first; **requires `--once`**, see §9),
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
  `http=requests` explicitly at each call site. **One pass at a time per database:** every
  pass (scheduled or `--once`) runs inside `pass_lock` — a non-blocking `fcntl.flock`
  on `<resolved --db>.pass.lock`, taken per *pass*, not for the process lifetime, and
  keyed on the `resolve()`d DB path so a relative `--db`, an absolute one and a
  symlinked checkout all land on one file. A pass that cannot take it runs
  nothing: `--once` exits non-zero naming the holder's pid, a scheduled firing skips
  that slot and stays scheduled (§9). An **unwritable** lock file (the root-owned
  leftover of one `sudo` run) degrades to an `O_RDONLY` hold rather than failing —
  `flock` needs no write access, so the guard stays exclusive and only the pid record is
  lost, which both sides announce. Failing there instead would leave the daemon `active
  (running)` on a healthy-looking schedule while completing no pass, since with no eager
  startup pass the error is raised inside the APScheduler job. Other open failures
  (an unwritable DB directory, a file this user simply cannot read) still fail loud.
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
  `max_age_days` also gates a workday stub: `parse_stub` dates the stub's relative prose
  ("Posted N+ Days Ago") against the injected `now` (`now - age`, treating the number as
  a lower bound), so a stale stub is dropped before its detail GET. Only the confident
  English "N[+] Days Ago" form parses — "Today"/"Yesterday" and any other locale or
  wording leave `posted_at` None (kept), so a mis-parse never drops a good posting. `now`
  reaches the adapter through the same `keep`-gate call path.
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
  dict only, same as the fit backend, never promoted to an argparse default (§12).

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
  nobody while a miss costs one paid fit call and reaches the human. A label count that
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
  condemned, while `run_score` records a breaker **success**, so the degraded backend
  never trips it and walks the whole backlog. It costs no quota — the row is not
  fit-scored. Realistic trigger is a wrong `--model` tag or a non-instruct model: `_post`
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
  the postings this design keeps. `run_score` leaves a `provider_error` row `new` rather
  than fit-scoring it, so the absent key is never read and `merge_fallback_screen` is
  never reached: no second model vote, and the next pass screens the row properly.

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

  **`NO_SPONSOR_PHRASES` is the floor for SILENCE only** — `SCREEN_BACKEND=none`, a
  provider error, or the fit scorer's Stage 4 shape. It can only *add* a
  disqualification, never veto a model pass. And `authorization` **always records a
  verdict** when the candidate configured it, even when nothing was retrieved and no
  clause was asked and no LLM call was made: `merge_fallback_screen` fills only the keys
  the screen left absent, and a second model vote on a disqualification is exactly what
  that function is documented not to be.

  **Superseded measurements.** The 2026-07-25 precision/recall table
  (`NO_SPONSOR_PHRASES` 81.8%/45.0%; shipped `_check_authorization` 90.9%/100% over 20
  known true positives, via the now-retired `tools/sponsor_diff.py`) described the quote
  design and no longer describes shipped behavior; it is kept in
  [`../CHANGELOG.md`](../CHANGELOG.md) as history. The standing rule it established still
  holds and now applies to the veto patterns: **the vocabulary is measured, not guessed**
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
  **The fit scorer's Stage 4 block still emits the old single `required_degree`, on
  purpose**, and `_check_degree` reads both shapes: that block runs on a strong model
  where the minimum is a judgment it can make, and changing it would edit `score.txt`,
  whose gate is two consecutive quota-spending `score_eval` runs.

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
  bar phrased with none of these words is a **miss**, which costs one paid fit call and
  reaches the human; a false discard is reviewed by nobody. The floor is keep-direction
  only — it can turn a discard into a keep, never the reverse — and it applies to
  `merge_fallback_screen`'s Stage 4 extraction too, since that routes through the same
  `_screen_verdict`. `degree` is **not** guarded this way: 38 of 38 live degree discards
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
    Scoring calls are unconditionally `--ephemeral`: nothing is written to
    `~/.codex/sessions`, so the résumé+profile+JD prompt never reaches disk. (Before
    2026-07-29 the quota bar forced `--ephemeral` off — see **Quota telemetry** below.)
  - **`claude`** — `make_claude_scorer` (metered API, `claude-sonnet-5` by default —
    structured outputs require it; `claude-sonnet-4-6` doesn't support
    `output_config.format` — overridable via
    `ANTHROPIC_SCORE_MODEL`/`--anthropic-score-model`); needs `ANTHROPIC_API_KEY`. Does
    **not** batch — `fit` loops one `messages.create` call per posting regardless of
    `batch_size` (harmless no-op chunking cadence on this backend): Claude's win is the
    cached system prefix (already flat per-call marginal cost), not fewer round-trips,
    so batching would only save request count, which doesn't matter on metered billing.

  **Quota telemetry (`score/usage.py`, free).** After a scoring pass that actually
  built a scorer, `run_once` makes **one** HTTP GET against the active backend's own
  usage endpoint and writes a snapshot to `scorer_usage.json` in the shared db dir
  (`{backend, plan_type, as_of, limits:[{key, used_percent, window_minutes, resets_at}]}`).
  Best-effort by contract: `capture_usage` never raises, and a failed fetch leaves the
  PREVIOUS snapshot in place rather than truncating it — a transient 429 should dim the
  bar's freshness (the web reads file mtime as `as_of`), not blank it. The write is
  atomic (tmp + `os.replace`, tmp name keyed by pid+thread). **A failed capture is
  announced**: `run_once` prints `[quota] WARNING: no <backend> usage snapshot written`,
  and the write stamps an offset-aware `as_of` into the snapshot itself — a stale
  reading and a fresh one are otherwise indistinguishable to anything but `ls -la`, and
  this file is the instrument the `--score-limit` decisions are made on. Endpoints:
  - **codex** — `GET https://chatgpt.com/backend-api/codex/usage`, bearer token +
    `chatgpt-account-id` from `$CODEX_HOME/auth.json`. Yields `plan_type` and
    `rate_limit.primary_window`/`secondary_window` (`used_percent`,
    `limit_window_seconds` → `window_minutes`, `reset_at`). The observed `primary` is
    the **weekly** window (10080 min). This is the SAME budget the scorer spends.
    chatgpt.com is behind Cloudflare, which 403s urllib's default `Python-urllib/3.x`
    (and a browser-looking `Mozilla/5.0`), so an honest client `User-Agent` is sent.
  - **claude** — `GET https://api.anthropic.com/api/oauth/usage`, bearer token from
    `$CLAUDE_CONFIG_DIR/.credentials.json` + `anthropic-beta: oauth-2025-04-20`.
    Normalises the richer `limits[]` array (`kind`/`group`/`percent`/`resets_at`, plus
    `scope.model.display_name` for the model-scoped weekly row) and falls back to the
    flat named buckets (`five_hour`, `seven_day`, …). ISO reset strings are parsed to
    epoch seconds so both backends share one field.
    **This is the Claude Code SUBSCRIPTION budget, which is NOT what the claude scorer
    spends** — `make_claude_scorer` bills `ANTHROPIC_API_KEY` (metered; no
    percent-of-quota endpoint exists for it). The snapshot records `backend` and the
    bar states the distinction outright (§7.2) so the two are never conflated.

  Before 2026-07-29 the codex figures were scraped from the session **rollout** (the
  only place `codex exec` records `rate_limits`; `--json` stdout does not), which forced
  `--ephemeral` off, left the résumé-bearing prompt on disk until a guarded reap, and
  identified "our" rollout by mtime. The endpoint returns the same accounting directly,
  so all of that is gone. A live "now" reading still isn't attempted per scoring call —
  the snapshot reflects the last pass, a budget indicator rather than a live meter.

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
  score / JD link, plus an optional `Fit: <summary>` line from
  `score_detail.assessment.summary` and an optional `Resume: <label>` line when
  `score_detail` carries `recommended_resume`) — a single atomic message per match; the
  human
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
  `run_score` is **screen-all-then-batch-fit-survivors**, not one per-posting loop:
  (1) every `new` row is screened (Ollama, per-item — one bad screen call marks only
  that row `failed`), and a disqualified one is persisted `discarded` right here,
  **never** reaching the fit call — **except a `degree`/`clearance`-only fail, which is
  routed to the strong model for confirmation instead of being deleted**
  (`score.demote_for_confirmation`). The selection rule is **measured false-disqualification
  rate**, not "a model produced the verdict" — `authorization` is also a 4B labelling
  retrieved prose, and it is excluded because its measured false-disqualification count on
  the gate is **0** and it already carries the precision machinery the other two lack
  (retrieve-then-classify, the offers/preference vetoes, quote verification), so a second
  look is the wrong trade on the one check where a false positive is worst. Degree and
  clearance measured **24%** (9 of 38 live discards) and **83%** (20 of 24) respectively —
  both **pre-fix** figures, and the reason the routing was decided rather than a claim
  about current behavior: the clearance evidence floor already catches all 20 for free and
  the `degree_levels`/`min(rank)` rewrite cut degree's residual to 2-3 rows per eval run.
  Routing is insurance for that residual, which is a 4B ceiling no prompt has closed in
  four attempts. The demotion **clears**
  the failing verdicts rather than flipping them to pass — that is what turns them into
  gaps `merge_fallback_screen` fills from the fit scorer's own Stage 4 extraction, with
  the same CODE applying the candidate's constraint — and records
  `needs_confirmation: [checks]` in `score_detail`, kept whichever way the confirmation
  goes. A row failing **any** other check — `authorization`, the location gazetteer, the
  intern/co-op title regex — stays terminal and free. A
  disqualification carrying **no per-check entries at all** is likewise not routed — an
  unreadable shape is not evidence the verdict is wrong. It is a routing decision, not a
  persisted state: screen and fit run in the same pass, so no row is ever stored
  `needs_confirmation`, and the outcome is the usual `scored`/`discarded`; a screen survivor whose trimmed `description` is
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
  pass carries into the SCREEN phase (the `--score-limit` operator flag), bounding the
  paid scorer over a large fresh intake; the remainder stays `new`. It does **not** cap
  the free deterministic gates: `run_score` opens with a **phase 0 sweep**
  (`_sweep_free_gates`) that runs `deterministic_screen` and discards what it kills —
  0.26 ms/row to scan, ~0.5 ms/row including the committed write (~4.5s for 3,480
  discards over 9,390 rows), no model call, no quota — before `limit` is applied to what
  survives. The sweep runs INSIDE the `max_id` window (`max_id` filters first), so an
  operator's `--score-max-id` selection still bounds what it may touch.
  **`limit` is still not a pure quota budget, and the residual is deliberate:** an LLM
  screen-discard and a thin-JD row each consume a slot while spending no quota. Two
  measurements of how big that is disagree on their denominators and neither is wrong —
  **~18%** over the three live passes of 2026-07-29 (11/8/13 of 60 screened), **8.2%**
  over the rows in DB history that would enter the screen phase under this code (40 of
  486). Closing it would mean screening until `limit` *survivors* are found, which makes
  the model work per pass unbounded; the bound is worth more than the last 8-18%, and on
  the live data the difference is ~1.3 days of catch-up rather than ~16. Charging a quota budget for work that spends no quota is
  what stalled the live pipeline on 2026-07-31: `requeue_discarded` had returned 4,644
  rows to `new`, where they sort AHEAD of fresh intake, and the daemon then spent every
  pass re-killing location discards for free while fit-scoring nothing. An optional `max_id` (the
`--score-max-id` flag) restricts the pass to rows with `id <= N` and is applied
**before** `limit` — the SELECTOR to `limit`'s BUDGET. The two are not
interchangeable: the queue below is newest-first, so `limit` can only name rows from
the new end, while a `--rescreen-discarded` recovery target sits at the old end
(`requeue_discarded` stamps one `updated_at` across every discard, so they tie and
break by `id DESC`). Like `--rescreen-discarded` it is **one-shot — `main` rejects it
without `--once`** (§9): `once()` closes over the parsed args, so a bound left on the
daemon would hold for every future firing and every pass after the first would score
nothing while higher-id intake piled up behind it. A negative `N` is a parser error, not
"no bound" — `run_score` tests `max_id > 0`, so a sign typo would otherwise pass the
one-shot guard and silently disable the filter on a `--rescreen-discarded` pass. One
documented promise bends under a bound: a `run_retry` requeue above `N` is **not**
rescored that same pass (it keeps its original id, and the bound is applied to ids, not
to recency). It burns no retry budget — `requeue_failed` does not touch `attempts` — so
it simply waits for an unbounded pass. **The `new` queue is read
  newest-id-first** (`get_by_status(..., newest_first=True)` — the one caller that asks
  for it), which is what makes `limit` usable on a schedule: every `new` row has score
  NULL, so the default `score DESC, id ASC` degenerates to oldest-first and a bounded
  pass would work the back of the backlog while a posting discovered today waited
  behind every older one. Newest-first spends the cap on the current pass's discoveries
  and lets a backlog drain from its tail only when there is headroom, keeping "clear
  the backlog" an explicit operator action rather than something the schedule does
  silently and expensively. **Every pass ends with one summary
  line** — `[score] N row(s): … screen-discarded, … thin-JD (no fit call), …
  fit-scored, … sent for confirmation, … failed, … unreached, … left 'new'` — so a pass
  that worked is distinguishable from one with nothing to do. `fit-scored` is the
  quota-spending count; `sent for confirmation` **overlaps** the other counts rather than
  adding to them — the row was demoted out of `screen-discarded`, reached the fit phase,
  and landed wherever that phase put it (`fit-scored` normally, `failed` on a scorer
  error, `unreached` behind a tripped breaker) — and it is on the line because it is the
  number that moves a free outcome to a paid one. A demotion that lands in the **thin-JD**
  path is deliberately **not** counted: no fit call runs, so nothing confirms it (the
  `needs_confirmation` marker still rides along, naming a confirmation the row still
  needs);
  `unreached` is what a tripped breaker or an abort did not reach *within this pass's
  slice*; `left 'new'` is the **whole queue**, counted from the DB rather than from the
  slice, so a capped pass cannot report `0 left 'new'` while thousands wait. Both the
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
  and is left alone, because requeueing it destroys it irreversibly (§9). Skipping it is
  **not** a rescue either: nothing re-hydrates an existing row, so both outcomes are
  terminal. The filter buys honest state, not recovery. `main` rejects the flag without
  `--once` (§9).
  Stage gating in §[9](#9-behaviors-and-invariants).

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
- **`app/api/scorer-usage/route.ts`** — serves the fit-backend quota snapshot the
  worker captures once per scoring pass (§7.1): reads `scorer_usage.json` (path derived
  from `DATABASE_URL`, overridable via `SCORER_USAGE_FILE`), returns the snapshot —
  including the `backend` it describes — plus `as_of` (the file mtime).
  Missing/unparseable → empty state (`{backend:null, limits:[], as_of:null}`, still
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
  Discovered-Jobs matched/below-bar/discarded split is now the verdict predicate
  (`matchedIds()` / `belowBarIds()` in `lib/actions.ts`, the former mirroring the worker's
  `db.get_notifiable`), not a score cutoff; the fit score is display/ranking only.
- **`components/`** — `Dashboard` (Applications ↔ Discovered Jobs ↔ Watchlist ↔
  Unresolved tabs, each delegated to a `*Tab` wrapper), `ApplicationTable` (inline status edit), `KPIGrid`,
  `StatusHistoryModal`, `AddApplicationForm`, `DiscoveredJobsTable` (bucket tabs on their
  own row — Matched/Below-bar/Discarded/Failed/Low-context — above a filter row of sort
  toggle Best match/Newest posted + score/disqualification-cause filters; a bucket-aware
  per-row "why" subline (a shared `VerdictShortfall` — seniority/domain verdict pills +
  top missing must-have — for below-bar AND for the fit-reject half of discarded, falling
  back to the legacy one-line `reasoning` for pre-S2.1 rows; the keyed disqualification
  reason when there is one; **which** low-context rule caught the row — a short body
  ("Thin JD (N chars)") vs the scorer's own `insufficient_context` flag on a full-length
  JD; pipeline error); a `recommended_resume` label under the score;
  folded Company/location/source and Posted/Fetched date columns + bulk
  Remove/Reopen/Remove-all-in-view + job-title links to the live posting),
  `Pagination` (reusable: first/last, numbered pages, go-to), `ApplyCategoryDialog`
  (category picker on Mark Applied), `WatchlistTable`
  (list + add/remove watched companies), `PromotionSuggestions` (approve/dismiss feed→
  watchlist suggestions, shown in the Watchlist tab), `UnresolvedFeedsTable` (read-only
  backlog), `ScorerUsageBar` (fit-backend quota bar on the Discovered Jobs view — polls
  `/api/scorer-usage`, one bar per window with % + "resets in Nd Hh" + "as of"; reflects
  the last scoring pass, not a live reading. **Labels itself by backend** from the
  snapshot, so switching `SCORE_BACKEND` relabels the bar instead of showing the other
  provider's numbers under the old name; two windows of the same length are
  disambiguated by the model scope in the key (`weekly · Fable`); on `claude` it states
  outright that it reads the Claude Code SUBSCRIPTION, not the `ANTHROPIC_API_KEY`
  spend the scorer actually bills), `JobDetailModal` (JD + score detail), and
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
  `active` + `category` keep-list + non-explicit-`sponsorship` *before* any fetch,
  then by the operator's own `title_filter` / `title_exclude` / `max_age_days`
  through the **same** `fetch.prefilter_postings` `run_fetch` uses — one ingest rule
  for both paths, so they cannot drift apart. Both gates run *before* the resolve,
  the earliest point that saves anything: a refused listing costs no URL resolve, no
  board detail fetch and no screen call. For a listing that would have *ingested*
  those are one-time costs (`existing_external_ids` prunes it next pass and
  `run_score` only reads `new`); what recurs every pass is the resolve for whatever
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
  collapse warning naming the split. (Canary self-tests and proactive Telegram/banner alerting are
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
  `constants.ts` — a cross-service constant, flagged in both.) The **keep** half of the
  verdicts always requires `seniority=match` — a seniority miss is disqualifying, not
  partial (`prompts/score.txt`) — and then splits on domain: **belowbar** = `{scored,
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
  **It does NOT compose with `--score-limit`, and that is a real limitation rather than
  a subtlety.** `requeue_discarded` stamps `updated_at`, so requeued rows do sort to the
  front of the `new` queue — but the queue holds *every* requeued discard (the UPDATE is
  unfiltered), so a bounded pass reaches an arbitrary prefix of thousands of them and
  the operator cannot aim the cap at the rows the rescreen was for. Aiming at a
  *specific* set is what `--score-max-id` is for (§7.1) — pair the two, not
  `--score-limit`.
  Unbudgeted: a discard spends no `attempts`, so there is no counter to guard the way
  `run_retry` guards two. **Filtered on exactly one condition — the row must have a
  non-empty `description`.** A stub-gate discard is stored deliberately un-hydrated
  (`run_fetch` exempts `discarded` rows from the bodyless drop) because it never reaches
  the scorer; requeueing one is *irreversible loss*, since it becomes `new`, the thin-JD
  gate parks it `scored` at score 0, and `upsert_postings` is `ON CONFLICT DO NOTHING`
  so no later pass back-fills the JD. **Skipping it is not a rescue either** — nothing
  re-hydrates an existing un-hydrated row (the stub gate only decides whether to hydrate
  *before* insert, and the row already exists), so both outcomes are terminal. What the
  filter buys is honest state: the row keeps its real `discarded` reason and a live
  `job_url` instead of being relabelled `scored`/0 as though it had been evaluated.
  `run_once` prints the skipped count so the operator is told, not left to infer it.
  Everything else comes back. It is
  **one-shot** — `main` rejects it without `--once`, because on the schedule it would
  resurrect the same discards every pass and re-charge the paid fit scorer for each
  survivor indefinitely. `--run-now` does **not** unlock it either, despite also running
  a pass promptly: `once()` closes over the flag, so it would still be set on every later
  scheduled firing. Screening is free on the default ollama backend; the
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
  aborting it and cancelling the queued remainder. One success disarms it. **A backend
  that fails by answering blindly counts the same as one that raises** — a non-dict, or a
  dict with no `screen` object, is a provider error, because a degraded backend that
  returns healthy-looking JSON would otherwise record breaker successes forever (§7.1).
  `extract=None`
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
  The asymmetry that makes it worth guarding: a duplicated notify costs one extra
  Telegram message, a duplicated **score costs real paid quota**. `run.pass_lock` wraps
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
| Both LLM schemas are valid for strict structured output (every object lists every property in `required` **and** sets `additionalProperties: false`) — checked on `_batch_schema`, the payload codex actually receives | `test_score.py::test_schema_is_strict_mode_valid` |
| A blind degree/clearance extraction (null, blank, or any "unknown" spelling) materializes **no** verdict, so `merge_fallback_screen` still sees the gap — including the two new degree spellings (a non-bool `degree_required`, and `degree_required: true` with no recognized level) | `test_score.py` (`test_blind_screen_entry_still_leaves_a_gap_for_the_fallback`, `test_blind_degree_levels_leave_a_gap_for_the_fallback`) |
| Degree disqualifies on the **lowest** level the posting names, never the highest, and a merely preferred degree is no bar; unrecognized levels are dropped rather than ranked 0; the legacy single-`required_degree` shape the fit scorer emits still works | `test_score.py` (`test_degree_levels_take_the_lowest_not_the_highest`, `test_a_merely_preferred_degree_is_not_a_bar`, `test_unrecognized_degree_levels_are_dropped_not_ranked`, `test_higher_required_degree_disqualifies`) |
| A `degree`/`clearance`-**only** screen fail is routed to the strong model (`needs_confirmation` in `score_detail`, the failing verdicts cleared so the fallback fills them) instead of discarding; the strong model can still confirm the bar and discard; any other failing check — and a disqualification with no per-check entries, or an unreadable one — stays terminal and free; the routed count is reported separately from `screen-discarded`, is **not** counted on the thin-JD path (no fit call runs), and is not double-counted in the pass accounting | `test_pipeline.py` (`test_a_degree_only_fail_is_confirmed_by_the_strong_model_not_discarded`, `test_the_strong_model_can_still_confirm_the_bar_and_discard`, `test_a_location_fail_alongside_degree_is_still_discarded_free`, `test_a_disqualification_with_no_per_check_verdicts_is_not_routed`, `test_a_routed_row_reports_as_confirming_not_as_screen_discarded`, `test_a_thin_jd_demotion_is_not_counted_as_a_confirmation`, `test_a_confirming_row_is_not_double_counted_in_the_pass_accounting`), `test_score.py::test_only_a_degree_or_clearance_only_failure_is_demoted` |
| `merge_fallback_screen` may only rule on the checks it FILLED: `_screen_verdict` re-rules every configured check, and `authorization` produces a floor verdict from no entry at all, so an unfiltered read would let the blunt `NO_SPONSOR_PHRASES` substring floor overturn a check the screen already answered — discarding a row whose own `score_detail` records that check as passing | `test_pipeline.py::test_the_fallback_cannot_overturn_a_check_the_screen_already_answered` |
| Unknown `SCORE_BACKEND` fails at parse time, before fetch or `--rescreen-discarded` spends itself | `test_run.py::test_unknown_score_backend_fails_before_any_work` |
| `--score-max-id` selects the id range **before** `--score-limit` bounds the spend; the documented recovery recipe survives argparse and arrives at `run_score`; refused without `--once` (on the schedule it would bound every future pass into scoring nothing) and refused when negative (which `max_id > 0` would read as "no bound") | `test_pipeline.py` (`test_run_score_max_id_selects_the_low_ids_the_cap_cannot_reach`, `test_run_score_max_id_applies_before_the_limit`), `test_run.py` (`test_score_max_id_reaches_run_score`, `test_the_documented_recovery_recipe_is_accepted_and_wired`, `test_a_negative_score_max_id_is_refused_not_read_as_no_bound`, `test_score_max_id_requires_once`) |
| Wall-clock slots are evenly spaced and tile the day (`cron_hours`); `24` is one midnight slot, never an empty trigger that silently never fires | `test_run.py` (`test_the_schedule_is_evenly_spaced_wall_clock_slots`, `test_a_daily_schedule_is_one_midnight_slot_and_not_an_empty_list`) |
| `schedule_hours` must divide 24: a non-divisor and anything `> 24` are both rejected at config load rather than silently running tighter than configured, or collapsing to daily | `test_config.py` (`test_rejects_a_schedule_that_does_not_divide_the_day`, `test_rejects_a_schedule_longer_than_a_day_instead_of_collapsing_it_to_daily`, `test_every_divisor_of_24_is_accepted`, `test_rejects_non_positive_schedule_hours`) |
| The daemon runs NO pass at launch; `--run-now` runs exactly one before the scheduler blocks; `--run-now --once` is a parser error, and `--run-now` does not unlock `--rescreen-discarded` | `test_run.py` (`test_starting_the_daemon_runs_no_pass_at_launch`, `test_run_now_runs_exactly_one_pass_before_the_scheduler_takes_over`, `test_run_now_and_once_together_are_a_parser_error`, `test_run_now_does_not_open_the_rescreen_discarded_backdoor`) |
| One pass at a time per database (`pass_lock`, keyed on the resolved `--db` so a moved `TMPDIR` cannot dodge it and two different DBs do not block each other): a second acquisition is refused immediately (never blocks/queues), the lock is released on exception, a **stale** lockfile is taken without manual cleanup, and a refused pass runs nothing — `--once` exits non-zero, a scheduled firing skips the slot, stays scheduled, and says so at `logging.WARNING` rather than on stdout (the daemon installs a timestamped handler for it; a bare import installs none) | `test_run.py` (`test_a_second_pass_is_refused_while_the_first_holds_the_lock`, `test_the_lock_is_released_when_the_pass_raises`, `test_a_stale_lockfile_does_not_wedge_the_pipeline`, `test_main_once_refuses_to_start_inside_another_pass`, `test_a_scheduled_pass_skips_the_slot_instead_of_dying`, `test_main_once_takes_the_lock_and_gives_it_back`, `test_the_lock_is_keyed_on_the_db_not_on_the_temp_dir`); an unwritable lock still guards exclusively and says the pid is unrecorded (`test_an_unwritable_lock_still_guards_the_pass`) |
| Sponsorship retrieval is deterministic and per-sentence: one snippet per `sponsor` sentence with a +/-1 window, adjacent hits **not** merged, abbreviations not splitting the sentence, and a JD that never says "sponsor" yielding nothing | `test_score.py` (`test_snippets_are_the_sponsor_sentence_plus_one_neighbour_each_side`, `test_one_snippet_per_sponsor_sentence_even_when_they_are_adjacent`, `test_a_bare_sentence_would_lose_its_antecedent_so_the_window_carries_it`, `test_a_jd_that_never_says_sponsor_yields_no_snippets`, `test_the_abbreviation_trap_pr22_sprang_does_not_split_early`) |
| Sponsorship decision: any `offers` outranks any `refuses`; the offers/preference vetoes overturn a `refuses` but can never create one; hallucination cannot disqualify because the model supplies no text | `test_score.py` (`test_an_offer_anywhere_outranks_a_refusal`, `test_a_scoped_refusal_beside_an_offer_keeps_the_posting`, `test_the_offers_veto_overrules_a_refuses_label_but_never_creates_one`, `test_a_preference_is_vetoed_too_because_the_classifier_calls_it_a_refusal`, `test_hallucination_cannot_disqualify_because_the_model_supplies_no_text`) |
| An unusable label list (wrong count, off-vocabulary, **or an empty array against retrieved snippets**) drops the check and KEEPS, and does **not** fall through to `NO_SPONSOR_PHRASES`; silence — and `[]` with nothing retrieved — still reaches the floor; `authorization` records a verdict even when no clause was asked and no LLM call was made | `test_score.py` (`test_unusable_labels_drop_the_check_rather_than_guessing`, `test_a_miscounted_answer_does_not_fall_through_to_the_floor`, `test_an_empty_label_array_against_retrieved_snippets_is_a_bad_count_not_silence`, `test_an_empty_label_array_with_nothing_retrieved_still_reaches_the_floor`, `test_the_phrase_floor_runs_only_when_no_labels_arrived`, `test_authorization_records_a_verdict_even_with_no_llm_call_at_all`) |
| The `sponsor`-only vocabulary's recall trade is pinned in both directions — exactly 6 of 13 must-flag sentences retrievable, 7 deliberately given up — so it cannot drift silently, and no genuine offer is ever disqualified | `test_score.py` (`test_the_narrowed_vocabulary_names_exactly_which_bars_it_gives_up`, `test_every_must_keep_sentence_survives_the_code_path`) |
| Clearance disqualifies only when a `CLEARANCE_TOKENS` match is present in the JD description **or** the title; an ungrounded `requires_clearance: true` keeps, science/scientist never grounds, and the Stage 4 fallback obeys the same floor | `test_score.py` (`test_ungrounded_clearance_claim_keeps_the_posting`, `test_clearance_grounded_in_the_title_alone_disqualifies`, `test_science_words_do_not_ground_a_clearance_claim`, `test_fallback_screen_clearance_also_needs_evidence`) |
| Deterministic location gate (`location_verdict`, pycountry + geonamescache, evidence-tiered): a NAMED country / US state decides alone and outranks the remote hint; city/subdivision evidence is diacritic-folded, votes for every reading it allows, and discards only when corroborated; region acronyms are a stoplist; any allowed evidence keeps | `test_location.py` (`test_resolve_location`, `test_location_verdict_marks_what_escalates`, `test_token_country_*`, `test_folding_is_the_same_function_everywhere`) + gate integration tests in `test_score.py` |
| **Zero false discards** over every distinct location string in the live DB, gated in CI against a committed corpus labeled by an INDEPENDENT oracle (not by the code under test); the residual leak set is pinned EXACTLY, in both directions, so the accepted trade cannot drift silently | `test_location.py` (`test_no_us_eligible_string_is_ever_discarded`, `test_the_leak_set_is_pinned_exactly`, `test_the_corpus_is_labeled_the_way_the_gate_assumes`, `test_a_discard_always_names_a_country_the_string_actually_mentions`), `tests/fixtures/location_corpus.jsonl` |
| Fetch-time max-age + title_exclude drop | `test_fetch.py::test_prefilter_*` |
| Deterministic gate hoisted to fetch (discarded, no Ollama) | `test_pipeline.py::test_run_fetch_marks_location_miss_discarded` |
| Multi-resume loading (`load_resumes`): label = stem minus `resume_`; `personal_profile.txt` → profile, never a version; sorted order; dotfiles skipped; zero files / duplicate label / non-UTF-8 → clean `SystemExit` | `test_run.py` (`test_load_resumes_*`) |
| Multi-resume scoring: `recommended_resume` enum-constrained to the actual labels (≥2 versions), field omitted for a single resume; cached-prefix block layout (header → profile → resumes, `cache_control` on last); normalization pass-through | `test_score.py` (`test_score_schema_*`, `test_scorer_system_blocks_*`, `test_recommended_resume_*`) |
| `recommended_resume` persisted in `score_detail`; Telegram `Resume:` line only when set — malformed/absent `score_detail` never crashes notify; modal badge renders when present, absent otherwise | `test_pipeline.py`, `test_notify.py`, `web/src/components/__tests__/JobDetailModal.test.tsx` |
| Telegram `Fit:` line carries the persisted `assessment.summary` (whitespace collapsed to one line, truncated at 300 chars, which bounds the only unbounded field against Telegram's 4096 cap — title/company/URL are not capped); absent/malformed `score_detail` or empty summary omits the line entirely; notify calls no model | `test_notify.py` (`test_message_carries_the_persisted_fit_summary`, `test_a_long_summary_is_truncated_rather_than_bursting_the_message_limit`, `test_message_omits_fit_line_when_absent_or_malformed`) |
| A screen `provider_error` row is never fit-scored (left `new`, 0 `attempts`). The old "unless a deterministic gate disqualified it" case is **no longer producible through `screen_posting`** (2026-07-31: those gates return before the model call, so the two flags cannot co-occur) — `run_score`'s branch for it and `test_run_score_provider_error_still_discards_on_a_deterministic_gate`, which hand-builds that verdict, are kept as defence in depth for any other caller; `_BREAKER_LIMIT` consecutive provider errors with zero successes abort the screen phase; one success disarms; `SCREEN_BACKEND=none` is not a provider error | `test_pipeline.py` (`test_run_score_never_pays_to_fit_score_an_unscreened_row`, `test_run_score_provider_error_still_discards_on_a_deterministic_gate`, `test_run_score_screen_breaker_aborts_and_says_so`, `test_screen_breaker_counts_raised_failures_too`, `test_run_score_circuit_breaks_a_dead_screen_provider`, `test_run_score_one_screen_success_disarms_the_breaker`), `test_score.py` (`test_extract_failure_is_flagged_provider_error`, `test_screen_backend_none_is_not_a_provider_error`, `test_a_deterministically_disqualified_row_never_reaches_the_provider`) |
| The code-side gates (intern title, location string) run BEFORE the model call and short-circuit it: a row they disqualify makes no backend call, carries no `provider_error`, and its reason is the deterministic one alone. `run_score` sweeps them over the whole `max_id` window in phase 0, outside `--score-limit`, so a **deterministic** discard consumes no budget slot — an LLM screen-discard and a thin-JD row still do | `test_score.py` (`test_a_deterministically_disqualified_row_never_reaches_the_provider`, `test_a_deterministic_gate_short_circuits_the_model_reason`, `test_multiple_failing_gates_join_reasons`), `test_pipeline.py` (`test_the_free_gates_do_not_consume_the_score_limit`) |
| A row the phase-0 sweep cannot WRITE stays `new` (the pending UPDATE is rolled back, so the next row's commit cannot adopt it), is not counted, and is announced; but `_BREAKER_LIMIT` consecutive write failures with zero successes re-raise rather than retrying a systemic fault row by row, pass after pass | `test_pipeline.py` (`test_an_unwritable_free_gate_discard_stays_new_and_says_so`, `test_a_systemic_sweep_write_failure_fails_loud_instead_of_retrying_forever`) |
| A provider error never disqualifies on the sponsorship **phrase floor** — the deterministic gates still stand, but the blunt whole-description scan is skipped and `authorization` is left absent; `SCREEN_BACKEND=none`, which has no provider to fail, still records that floor verdict | `test_score.py` (`test_a_provider_error_never_disqualifies_on_the_sponsorship_phrase_floor`, `test_screen_backend_none_still_records_the_authorization_floor_verdict`) |
| A **blind** live backend (nothing usable: not a dict, or neither a `screen` object nor any requirement key) is a `provider_error`, not a verdict; the FLAT shape the 4B emits ~1 call in 100 is a real verdict and is honoured, byte-identical to the nested shape — so it cannot discard on the phrase floor and cannot record breaker successes; the narrow scope is pinned on the other side, where an empty `screen` dict is an answer and keeps the floor | `test_score.py` (`test_a_blind_response_is_a_provider_error_not_a_verdict`, `test_an_empty_screen_object_is_a_verdict_and_keeps_the_floor`, `test_the_flat_shape_is_a_verdict_and_is_honoured`, `test_the_flat_shape_and_the_schema_shape_agree`, `test_the_observed_flat_response_is_kept_not_discarded`) |
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
| `run_retry` requeues `failed`→`new` only while `attempts < RETRY_MAX_ATTEMPTS` (3) **and** `notify_attempts < NOTIFY_MAX_ATTEMPTS` (3), caps at the 3rd failure on either, never requeues a notify-exhausted row, sets `updated_at` | `test_pipeline.py` (`test_run_retry_*`), `test_run.py` (`test_run_once_calls_five_stages_in_order`) |
| A recovered row (score-fail → `run_retry` → successful re-score) clears `pipeline_error` and preserves `attempts` | `test_pipeline.py` (`test_run_retry_recovery_clears_pipeline_error_keeps_attempts`) |
| Discovered-jobs verdict-aware buckets (matched/belowbar/discarded/lowcontext/failed, mutually exclusive; keep needs `seniority=match`, then domain splits match→matched / adjacent→belowbar; discarded = hard-constraint failures **plus** fit-verdict rejects; low-context = thin-JD **or** `insufficient_context` flag) + sort (score/posted) + pagination + disqualification-cause sub-filter + bulk remove/reopen/removeAllInView; per-row dismiss → `removed` | `web/src/__tests__/actions.test.ts`, `actions.int.test.ts`, `web/src/components/__tests__/DiscoveredJobsTable.test.tsx` |
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
| Feed inherits `title_filter`/`title_exclude`/`max_age_days` before the resolve; epoch-date and `title`->`job_title` translation | `test_feed_pipeline.py` |
| The feed re-runs the age gate on the BOARD's `posted_at` before upsert, so a fresh-per-feed evergreen req is not stored older than `max_age_days` | `test_feed_pipeline.py` (`test_run_feed_re_gates_on_the_boards_date_not_the_feeds`) |
| `new` queue read most-recently-touched-then-newest so `--score-limit` reaches today's discoveries **and** a `run_retry` requeue keeping its old id; other queues keep score-first | `test_db.py`, `test_pipeline.py` (`test_run_score_limit_takes_the_newest_rows_not_the_oldest`, `test_run_score_reaches_a_retried_row_inside_the_cap`) |
| The score summary separates `unreached` (this pass's slice) from `left 'new'` (the whole queue), so a capped pass cannot report an empty queue | `test_pipeline.py` (`test_run_score_summary_reports_the_whole_queue_not_just_the_capped_slice`, `test_run_score_summary_counts_rows_a_breaker_never_reached`) |
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
| Quota telemetry is one HTTP GET per pass against the ACTIVE backend's usage endpoint (codex `/backend-api/codex/usage`, Claude Code `/api/oauth/usage`), skipped when nothing was scored; `capture_usage` never raises and keeps the last-good snapshot on a failed fetch; codex scoring calls stay unconditionally `--ephemeral` | `test_score.py` (`test_fetch_codex_usage_normalizes_the_window`, `test_codex_usage_sends_a_non_default_user_agent`, `test_fetch_claude_usage_prefers_the_limits_array_and_keeps_the_model_scope`, `test_claude_usage_falls_back_to_the_flat_buckets`, `test_capture_usage_keeps_the_last_good_snapshot_when_the_fetch_fails`, `test_capture_usage_never_raises`, `test_codex_scorer_always_stays_ephemeral`), `test_run.py` (`test_run_once_refreshes_the_quota_bar_for_whichever_backend_scored`, `test_run_once_skips_the_quota_fetch_when_nothing_was_scored`) |
| A failed quota capture is announced, not swallowed (`[quota] WARNING` on a `False` return), and every written snapshot carries an offset-aware `as_of` so a stale reading is legible without an mtime check | `test_score.py` (`test_capture_usage_stamps_as_of_so_a_stale_reading_is_legible`), `test_run.py` (`test_a_failed_quota_capture_is_announced_not_swallowed`) |
| `/api/health` 200/503 probe; `/api/scorer-usage` snapshot route (incl. backend passthrough); usage-bar labelling | `web/src/__tests__/health.test.ts`, `scorer-usage.test.ts`, `web/src/components/__tests__/ScorerUsageBar.test.tsx` |
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
| `make eval-score` | verdict-accuracy gate for the fit-score prompt vs the golden set — PASS needs 0 hard-invariant violations, ≥85% per-dimension (`seniority`/`domain`) verdict agreement, <20% verdict flip-rate (**manual, not a CI gate**; default `codex` backend, flat-rate ChatGPT subscription, ~70 read-only calls, free; `SCORE_BACKEND=claude` A/Bs the paid metered path, and `CODEX_SCORE_MODEL` / `ANTHROPIC_SCORE_MODEL` A/B the model — the same vars `run.py` reads, so eval-model == production-model by default and an override is honoured rather than silently ignored). **Two consecutive PASS 2026-07-17 (target-fit domain rubric): 100%, then 95% agreement; hard 10/10; 5% flip — ship-gate cleared.** Lone wobbler: id 26 (a borderline Aquatic Quant-Researcher seat that wavers match↔mismatch run-to-run — genuinely research-central, not a clean twin of the stable id 652). The golden set + operator profile are gitignored, so the gate is only reproducible with the operator's local files |
| `make eval-screen` | hard-requirement accuracy gate for the **screen** prompt vs `apps/worker/eval/screen_golden.jsonl` — the gate `screen.txt` never had. **PASS = zero false disqualification**, judged on *any* of K=3 draws, not the majority: a check that discards a good posting one time in three is not a passing check. Recall and flip-rate are **reported, never gated** — a miss costs one paid fit call and reaches the human, a false discard is reviewed by nobody. 83 rows / 249 calls on local Ollama, free, ~10 min (**manual, not a CI gate** — CI has no Ollama). `SCREEN_BACKEND` A/Bs a hosted backend, and the run mirrors production's model resolution exactly — `OLLAMA_MODEL` / `SCREEN_MODEL` **and** `OLLAMA_NUM_CTX`, which feeds both the screener and `screen_posting`'s `num_ctx*2` JD cap; the report header names the model actually used (the real `DEFAULT_*_SCREEN_MODEL`, not "backend default"), since that is what an A/B is diffed on. `--selftest` is a free hermetic check of the gate logic and the corpus's own invariants — including that a row labeled as a **bar** carries that requirement's vocabulary in its own excerpt+title (`unsupportable_bars`). That is a check on the CORPUS, not the model: an excerpt truncated before the sentence its label rests on is a guaranteed miss for any model or prompt, so recall computed over it is meaningless. Only the bar direction is asserted — for clearance and sponsorship, absence of the vocabulary *is* the evidence of no bar. The corpus is gitignored (`apps/worker/eval/`), so like `eval-score` the gate is only reproducible with the operator's local files |
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
  *tracks* any private file — `.env` **and every `.env.<suffix>` variant** (`.bak`,
  `.local`, `.production`; `.gitignore` matches `.env*` for the same reason, since a
  literal rule left a backup both unignored and unchecked), `config.yaml`, `db/` or any `*.db`,
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
