# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo. This file is loaded
automatically every session — keep it lean.

## Read first

Before any substantive work, read these — the source of truth and the working
protocol:

- **[`docs/SPEC.md`](./docs/SPEC.md)** — what the system *is*, including the current
  capability map (architecture, components, data model, behaviors & invariants,
  setup, testing).
- **[`docs/PROGRESS.md`](./docs/PROGRESS.md)** — only the *delta*: what's **in flight
  and open** (defects, unverified properties, enhancements). Completed capabilities
  live in `SPEC.md`; release history in `CHANGELOG.md`.
- **[`docs/PRINCIPLES.md`](./docs/PRINCIPLES.md)** — the design DNA: consult at every
  design fork; forks go to the user, who decides. Includes the four-way uncertainty
  policy (keep · fail loud · circuit break · retry) — "err toward keep" is only one row.
- **[`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md)** — the session rail: task
  classification, verify-gate evidence table, definition of done.

Keep them current: when you change behavior, in the **same commit** update the
matching section of `SPEC.md` (capabilities/behavior), `PROGRESS.md` (close the gap
or add an in-flight entry), and [`CHANGELOG.md`](./CHANGELOG.md) (history) as
applicable. Conventions in [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## What this is

A self-hosted, semi-automated job-application system — **two services, one shared
SQLite database**:

- **`apps/web`** — Next.js 14 + Prisma tracker UI (applications, KPIs, charts,
  Discovered Jobs queue).
- **`apps/worker`** — Python 3.11 pipeline: fetch (11 platform adapters plus
  generic custom/browser recipe executors; 11 of those are watchlist-capable —
  oracle/jobvite are feed-only) → screen (Ollama) + score fit (Codex CLI default /
  Claude alternate) → notify (Telegram). Human applies by hand.

## Repo map

```
apps/web/      Next.js app   (schema, server actions, components, e2e)
apps/worker/   Python worker (ats_worker/: fetch/ feed/ score notify pipeline run)
db/            shared SQLite  (gitignored)
docs/          SPEC.md · PROGRESS.md · PRINCIPLES.md · DEVELOPMENT.md ·
               SETUP.md · superpowers/ (specs·plans)
tools/         check_schema_drift.mjs · check_privacy.mjs
```

## Run / test / build (from repo root)

```bash
make setup          # one-command bootstrap: web+worker deps, DB, non-clobbering template copies
make doctor         # preflight: status line per prerequisite (core-hard exit, provider rows soft)
make dev            # Next.js dev server → http://localhost:3000
make test           # both suites (Jest + pytest)
make test-web       # Jest only       make test-worker   # pytest only
make test-integration  # worker run_once + web real-Prisma tiers
make test-coverage  # both, gated      make test-e2e      # Playwright (seeds throwaway DB)
make check-schema   # fail if worker SQL fixture drifts from schema.prisma
make check-privacy  # fail if git tracks .env / resume / db / config.yaml
make db-push        # sync Prisma schema into SQLite
make up / make down # web stack only (web + autoheal, UID/GID passthrough);
                    # the worker is native — run it yourself, see Gotchas
```

## Conventions

- **Prisma owns the schema** (`apps/web/prisma/schema.prisma`). The worker reads/
  writes rows but issues **no DDL**. Change schema there, then `make db-push`.
  Status/category enums live in `apps/web/src/lib/constants.ts`.
- **Worker modules are pure + dependency-injected.** Real services are wired only
  in `ats_worker/run.py`; tests mock everything (no network/keys). Keep it that way.
- **Web:** TS, 2-space indent, mutations via Server Actions (`lib/actions.ts`); run
  `make lint` before pushing. **Worker:** Python, 4-space indent.
- **Commits:** short imperative subject, optional `type(scope):` prefix
  (`feat(worker): …`, `docs: …`). Keep each commit green.
- **Branches:** `main` is the only long-lived branch and is always releasable.
  Substantive work goes on a short-lived `feat/`·`fix/`·`docs/`·`chore/` branch and
  lands as a squash-merged PR once CI is green. Never force-push `main`.
- **Privacy:** never commit secrets (`apps/worker/.env`), the real resume
  (`apps/worker/resume/`), `config.yaml`, or `db/` — all gitignored;
  the repo ships only `*.example` templates.
- **Git identity:** commit as `drink970082 <howdywu@gmail.com>`.

## Gotchas

- **Ollama runs on the host** (GPU); the worker is native and reaches it via
  `localhost:11434` — see `docs/SPEC.md` §6.
- **SQLite is mounted as a directory** (`./db` → `/data`), not a single file, so
  WAL `-wal`/`-shm` sidecars are shared between the web container and the native
  worker. A single-file mount silently breaks WAL across the two processes.
- **Coverage gates:** worker `fail_under = 85` (`apps/worker/pyproject.toml`); web
  gated via `jest.all.config.ts`. CI also runs the schema-drift guard.
- Default models: local `qwen3.5:4b` screens hard requirements; fit scoring runs on
  the Codex CLI by default (`gpt-5.6-sol`), or Claude `claude-sonnet-5` when
  `SCORE_BACKEND=claude` (override via env / CLI — see SPEC §7.1).
```
