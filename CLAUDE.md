# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo. This file is loaded
automatically every session — keep it lean.

## Read first

Before any substantive work, read these two — they are the source of truth:

- **[`docs/SPEC.md`](./docs/SPEC.md)** — what the system *is*, including the current
  capability map (architecture, components, data model, behaviors & invariants,
  setup, testing).
- **[`docs/PROGRESS.md`](./docs/PROGRESS.md)** — only the *delta*: what's **in flight
  and open** (defects, unverified properties, enhancements). Completed capabilities
  live in `SPEC.md`; release history in `CHANGELOG.md`.

Keep them current: when you change behavior, in the **same commit** update the
matching section of `SPEC.md` (capabilities/behavior), `PROGRESS.md` (close the gap
or add an in-flight entry), and [`CHANGELOG.md`](./CHANGELOG.md) (history) as
applicable. Conventions in [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## What this is

A self-hosted, semi-automated job-application system — **two services, one shared
SQLite database**:

- **`apps/web`** — Next.js 14 + Prisma tracker UI (applications, KPIs, charts,
  Discovered Jobs queue).
- **`apps/worker`** — Python 3.11 pipeline: fetch (5 boards) → screen (Ollama) +
  score fit (Claude) → notify (Telegram). Human applies by hand.

## Repo map

```
apps/web/      Next.js app   (schema, server actions, components, e2e)
apps/worker/   Python worker (ats_worker/: fetch/ score notify pipeline run)
db/            shared SQLite  (gitignored)
docs/          SPEC.md · PROGRESS.md · SETUP.md (stub) · pipeline-design.md (historical)
tools/         check_schema_drift.mjs · seed_db.mjs
```

## Run / test / build (from repo root)

```bash
make dev            # Next.js dev server → http://localhost:3000
make test           # both suites (Jest + pytest)
make test-web       # Jest only       make test-worker   # pytest only
make test-coverage  # both, gated      make test-e2e      # Playwright (seeds throwaway DB)
make check-schema   # fail if worker SQL fixture drifts from schema.prisma
make db-push        # sync Prisma schema into SQLite
make up / make down # full Docker Compose stack (UID/GID passthrough)
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
- **Privacy:** never commit secrets (`apps/worker/.env`), the real resume
  (`apps/worker/resume/`), `config.yaml`, or `db/` — all gitignored;
  the repo ships only `*.example` templates.
- **Git identity:** commit as `drink970082 <howdywu@gmail.com>`.

## Gotchas

- **Ollama runs on the host** (GPU), not in a container; the worker reaches it via
  `host.docker.internal:11434`. Docker Desktop cannot reach a host Ollama the same
  way — see `docs/SPEC.md` §6.
- **SQLite is mounted as a directory** (`./db` → `/data`), not a single file, so
  WAL `-wal`/`-shm` sidecars are shared across both containers. A single-file mount
  silently breaks cross-container WAL.
- **Coverage gates:** worker `fail_under = 85` (`apps/worker/pyproject.toml`); web
  gated via `jest.all.config.ts`. CI also runs the schema-drift guard.
- Default models: local `qwen3.5:4b` screens hard requirements, Claude `claude-sonnet-5`
  scores fit (override via env / CLI — see SPEC §7.1).
```
