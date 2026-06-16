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
  scans company ATS boards (Greenhouse / Lever / Ashby / Workday / Pinpoint), scores
  each posting against your resume with a local LLM, screens out hard-constraint
  mismatches, auto-tailors a one-page resume for the best matches, and pings you on
  Telegram. You review and apply by hand, then one-click **Mark Applied** turns a
  posting into a tracked application. A human is always in the loop — no auto-apply.

> 📖 **Full documentation:** [`docs/SPEC.md`](./docs/SPEC.md) is the authoritative
> system spec (architecture, data model, behaviors, setup, testing).
> [`docs/PROGRESS.md`](./docs/PROGRESS.md) tracks what's done and what's open.

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
keywords and reasoning, download the auto-tailored one-page PDF, then **Mark
Applied** to promote it into a tracked application that flows into every chart
above.

The pipeline: **fetch** (5 board APIs) → **score + screen** (local Ollama, GPU) →
**tailor** (Claude + `tectonic` → single-page PDF) → **notify** (Telegram).

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
Python 3.11 worker (APScheduler, Ollama, Claude + `tectonic`, Telegram) ·
Jest + Playwright + pytest · Docker Compose. Details in
[`docs/SPEC.md` §6](./docs/SPEC.md#6-architecture).

---

## Documentation

| Doc | What |
|-----|------|
| [`docs/SPEC.md`](./docs/SPEC.md) | **Authoritative system spec** — architecture, components, data model, behaviors, setup, testing |
| [`docs/PROGRESS.md`](./docs/PROGRESS.md) | Live status: what's done, in flight, and open |
| [`docs/SETUP.md`](./docs/SETUP.md) | Setup pointer (→ spec §12) |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Conventions and how to run tests |
| [`CHANGELOG.md`](./CHANGELOG.md) | Release history |

---

## License

[MIT](./LICENSE).
