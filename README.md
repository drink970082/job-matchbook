# Job Matchbook

**The job tracker that finds your matches for you.**

[![CI](https://github.com/drink970082/job-matchbook/actions/workflows/ci.yml/badge.svg)](https://github.com/drink970082/job-matchbook/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

*match* — it watches company job boards, screens each posting against your hard
requirements, and scores fit against your résumé.
*book* — every match you act on is tracked: status history, KPIs, charts.

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
  scans company ATS boards — Greenhouse, Lever, Ashby, Workday, Pinpoint, and 6 more
  platform adapters, plus generic custom/browser recipe executors (11 of these are
  watchlist-capable; Oracle and Jobvite resolve discovery-feed listings only) —
  screens out hard-constraint mismatches with a local LLM, scores each
  posting's fit against your resume — by default via the **Codex CLI** (your ChatGPT
  subscription, flat-rate), with **Claude** as a metered alternate — and pings you on
  Telegram for the best matches. You review and apply by hand, then one-click **Mark
  Applied** turns a posting into a tracked application. A human is always in the loop —
  no auto-apply.

> **Full documentation:** [`docs/SPEC.md`](./docs/SPEC.md) is the authoritative
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

**Discover:** a **Discovered Jobs** tab triages everything the worker surfaced into
five buckets — **Matched** (cleared the seniority + domain verdict gate, the same
predicate the worker notifies on), **Below bar** (scored but non-matching),
**Discarded** (failed hard-requirement screening), **Failed** (pipeline error), and
**Low-context** (JD too thin to score fairly) — sortable by best match / newest and
filterable by score and disqualification cause. Every row carries a bucket-aware
"why" subline — seniority/domain verdict pills plus the top missing must-have, or the
disqualification reason, thin-JD size, or pipeline error — and a recommended-resume
label. Open a row for the full JD and a fit assessment: seniority/domain verdicts,
must-haves met vs. missing, and a one-line summary. Triage in bulk (Remove / Reopen /
Remove-all-in-view), or **Mark Applied** — with a category picker — to promote a
posting into a tracked application that flows into every chart above.

The pipeline: **fetch** (11 platform adapters plus generic custom/browser recipe
executors) → **screen** (local Ollama, GPU, hard requirements) + **score** fit
(Codex CLI default / Claude alternate, reason-first) → **notify** (Telegram) for
every high scorer.

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
# web + autoheal (or: make up) — the worker is NOT containerized, it runs
# natively on the host (see the spec) after creating its config + secrets:
UID=$(id -u) GID=$(id -g) docker compose up --build -d
cd apps/worker && python -m ats_worker.run   # scheduler; --once for a single pass
```

The database is bind-mounted as a **directory** (`db/` → `/data`) so SQLite's WAL
sidecars are shared between containers, and `UID`/`GID` build args let the container
user own the bind-mounted files. Full setup (Ollama, Telegram, worker config) is in
[`docs/SPEC.md` §12](./docs/SPEC.md#12-setup-and-deployment).

---

## Stack

Next.js 14 (App Router, Server Actions) · TypeScript · Prisma 6 + SQLite ·
React 18 · Tailwind CSS 4 · Radix UI · Recharts + hand-rolled SVG charts ·
Python 3.11 worker (APScheduler, Ollama, Codex CLI, Claude, Telegram) ·
Jest + Playwright + pytest · Docker Compose. Details in
[`docs/SPEC.md` §6](./docs/SPEC.md#6-architecture).

---

## Documentation

| Doc | What |
|-----|------|
| [`docs/SPEC.md`](./docs/SPEC.md) | **Authoritative system spec + capability map** — architecture, components, data model, behaviors, setup, testing |
| [`docs/PROGRESS.md`](./docs/PROGRESS.md) | Live delta — what's in flight and open (capabilities → SPEC, history → CHANGELOG) |
| [`docs/SETUP.md`](./docs/SETUP.md) | Setup front door — prerequisites, gotchas, tracker-only vs. full-pipeline paths, and where each setting lives (→ spec §12 for authoritative commands) |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Conventions and how to run tests |
| [`CHANGELOG.md`](./CHANGELOG.md) | Release history |
| [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) | Community expectations (Contributor Covenant) |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting + accepted-risk scope |

---

## License

[MIT](./LICENSE).
