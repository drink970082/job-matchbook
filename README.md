# ATS — Application Tracking System

[![CI](https://github.com/drink970082/personal-ats/actions/workflows/ci.yml/badge.svg)](https://github.com/drink970082/personal-ats/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

A self-hosted, semi-automated job-application system built with **Next.js 14**,
**Prisma/SQLite**, and a **Python** pipeline. Keep every application, status
transition, and interview round in one place — then look at it visually instead of
scrolling a spreadsheet.

<p align="center">
  <img src="docs/images/dashboard.png" alt="Full dashboard view" width="900">
</p>

This repo is **one project made of two cooperating services that share a single
SQLite database**:

- [`apps/web`](./apps/web) — the Next.js tracker + dashboards you interact with.
- [`apps/worker`](./apps/worker) — a Python pipeline that *feeds* the tracker: it
  scans company ATS boards (Greenhouse / Lever / Ashby / Workday / Pinpoint), screens
  out hard-constraint mismatches with a local LLM, scores each posting's fit against
  your resume with Claude, and pings you on Telegram for the best matches. You review
  and apply by hand, then one-click **Mark Applied** turns a posting into a tracked
  application. A human is always in the loop — no auto-apply.

> 📖 **Full documentation:** [`docs/SPEC.md`](./docs/SPEC.md) is the authoritative
> system spec (architecture, data model, behaviors, setup, testing) and the current
> capability map. [`docs/PROGRESS.md`](./docs/PROGRESS.md) tracks only open work
> (in-flight + known gaps).

---

## Features

**Track:** header KPIs, a searchable/paginated table with inline status editing and
per-application history, CSV import/export, and four dashboards — a GitHub-style
activity heatmap, a category donut, a status funnel, and a status-flow Sankey
reconstructed from history.

<p align="center">
  <img src="docs/images/kpi-and-table.png" alt="KPI strip and applications table" width="900"><br>
  <img src="docs/images/charts-row.png" alt="Activity heatmap and category donut" width="900"><br>
  <img src="docs/images/sankey.png" alt="Status flow Sankey diagram" width="900">
</p>

**Discover:** a **Discovered Jobs** tab shows a scored, filterable queue of postings
the worker found. Open any row for the full JD plus the model's matched/missing
keywords and reasoning, then **Mark Applied** to promote it into a tracked
application that flows into every chart above.

The pipeline: **fetch** (5 board APIs) → **screen** (local Ollama, GPU, hard
requirements) + **score** fit (Claude, reason-first) → **notify** (Telegram) for
every high scorer.

---

## Feature status

At-a-glance maturity. **Status:** ✅ shipped · 🚧 in flight · ⛔ planned.
**Tested:** ✅ automated tests · ⚠ shipped but unverified or with a known caveat
(see note) · — UI, not separately tested. The authoritative invariant→test map is
[`SPEC.md` §9](./docs/SPEC.md#9-behaviors-and-invariants); open items live in
[`PROGRESS.md`](./docs/PROGRESS.md).

| Feature | Status | Tested | Notes |
|---------|:---:|:---:|-------|
| Applications table — paginate / filter / search | ✅ | ✅ | |
| Inline status editing + status history | ✅ | ✅ | each change appends a history row |
| Status history modal (add / edit / delete) | ✅ | ✅ | delete recomputes current status |
| KPI strip | ✅ | ✅ | |
| Dashboards — heatmap · donut · funnel · Sankey | ✅ | ⚠ | render shipped; **chart-data actions (`getStatusFlow`/`getTimelineData`/`getCategoryData`) have no test** |
| CSV import / export | ✅ | ✅ | RFC-4180, enum validation, dedup |
| Discovered Jobs queue + triage | ✅ | ✅ | unit + Playwright e2e |
| JD + score-detail dialog | ✅ | ✅ | keywords, reasoning, screen verdicts |
| Mark Applied (posting → application) | ✅ | ✅ | atomic transaction + dedup |
| Discard / Reopen posting | ✅ | ✅ | reopen keeps disqualification reason |
| Responsive / mobile layout | ✅ | — | stacks below ~640px |
| Fetch — Greenhouse / Lever / Ashby / Workday / Pinpoint | ✅ | ✅ | dedup on `(source, external_id)` |
| Title pre-filter (fetch-time) | ✅ | ✅ | |
| Score — Claude (reason-first) | ✅ | ✅ | |
| Hard-constraint screening — local Ollama | ✅ | ✅ | disqualified → `discarded` |
| Notify — Telegram message (score ≥ threshold) | ✅ | ✅ | ⚠ transient failure can bury a match → [PROGRESS Defects](./docs/PROGRESS.md#open-work) |
| Pipeline state machine + per-item failure isolation | ✅ | ✅ | |
| Scheduler (APScheduler) | ✅ | ✅ | immediate pass + every `schedule_hours` |
| Config load / validate | ✅ | ✅ | |
| Auto-retry of `failed` postings | ⛔ | — | not built → [PROGRESS Defects](./docs/PROGRESS.md#open-work) |
| Docker Compose · shared SQLite (WAL) | ✅ | ✅ | |
| CI · coverage gates · schema-drift guard | ✅ | ✅ | |

---

## Quick start

**Local dev (web app):**

```bash
cd apps/web
npm install
npx prisma generate
npx prisma db push    # if db/applications.db doesn't exist yet
npm run dev           # http://localhost:3000
```

Or from the repo root: `make install && make db-push && make dev`.

**Docker (full stack):**

```bash
# web app only:
UID=$(id -u) GID=$(id -g) docker compose up web --build -d
# full pipeline too (after creating the worker's config + secrets — see the spec):
UID=$(id -u) GID=$(id -g) docker compose up --build -d        # or: make up
```

The database is bind-mounted as a **directory** (`db/` → `/data`) so SQLite's WAL
sidecars are shared between containers, and `UID`/`GID` build args let the container
user own the bind-mounted files. Full setup (Ollama, Telegram, worker config) is in
[`docs/SPEC.md` §12](./docs/SPEC.md#12-setup-and-deployment).

---

## Stack

Next.js 14 (App Router, Server Actions) · TypeScript · Prisma 6 + SQLite ·
React 18 · Tailwind CSS 4 · Radix UI · Recharts + hand-rolled SVG charts ·
Python 3.11 worker (APScheduler, Ollama, Claude, Telegram) ·
Jest + Playwright + pytest · Docker Compose. Details in
[`docs/SPEC.md` §6](./docs/SPEC.md#6-architecture).

---

## Documentation

| Doc | What |
|-----|------|
| [`docs/SPEC.md`](./docs/SPEC.md) | **Authoritative system spec + capability map** — architecture, components, data model, behaviors, setup, testing |
| [`docs/PROGRESS.md`](./docs/PROGRESS.md) | Live delta — what's in flight and open (capabilities → SPEC, history → CHANGELOG) |
| [`docs/SETUP.md`](./docs/SETUP.md) | Setup pointer (→ spec §12) |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Conventions and how to run tests |
| [`CHANGELOG.md`](./CHANGELOG.md) | Release history |

---

## License

[MIT](./LICENSE).
