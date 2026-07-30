# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo. [`AGENTS.md`](./AGENTS.md)
is the same guidance for other agents, minus the Claude-Code-specific conduct below —
a real file, not a symlink (a symlinked `AGENTS.md` serves as its 9-byte target path
over `raw.githubusercontent.com` and degrades silently on Windows). Keep the two in
sync by hand.

## The docs

**Before you touch code, read `PROGRESS.md`'s "In flight" section** — it is the claim
registry, and skipping it is how two sessions collide on one branch. That one is
unconditional; the rest you pull in as the task needs them (the `session-boot` skill
walks the order):

- **[`docs/SPEC.md`](./docs/SPEC.md)** — what the system *is*: the capability map,
  data model, behaviors & invariants. Source of truth.
- **[`docs/PROGRESS.md`](./docs/PROGRESS.md)** — the *delta* only: in flight and open.
  Completed work lives in `SPEC.md`, history in `CHANGELOG.md`.
- **[`docs/PRINCIPLES.md`](./docs/PRINCIPLES.md)** — the design DNA, for design forks.
  Includes the four-way uncertainty policy (keep · fail loud · circuit break · retry)
  — "err toward keep" is only one row.
- **[`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md)** — the session rail: task
  classification, verify-gate evidence table, definition of done, team protocol.
- **[`docs/SCORING.md`](./docs/SCORING.md)** — the scoring subsystem as a *rebuild
  spec*, self-contained and portable (it assumes no repo knowledge, so it restates
  what SPEC covers). Read it before touching `score/`, either prompt, or an eval —
  its "measured history" section is the record of what has already been tried and
  failed, and its "known-hostile directions" list is why several odd-looking rules
  are the way they are.

Keep them current: when you change behavior, in the **same commit** update the
matching section of `SPEC.md` (capabilities/behavior), `PROGRESS.md` (close the gap
or add an in-flight entry), and [`CHANGELOG.md`](./CHANGELOG.md) (history) as
applicable. Conventions in [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Agent conduct

Effort levels are in [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md).

- **Doc length matches substance.** `SPEC.md`/`PROGRESS.md`/`CHANGELOG.md` are
  already large and every session reloads them. Write the clause the change needs —
  no padded sections, restated summaries, or boilerplate. Same for specs and plans
  under `docs/superpowers/`.
- **Delegate rarely.** Subagents are for large, genuinely independent tracks (a wide
  multi-file sweep) and for the §7 pre-merge review — never as a substitute for the
  verify gate, never for something finishable in a handful of tool calls. A skill
  invoking another skill is not delegation. One agent beats several.
- **The verify gate is the verification.** DEVELOPMENT.md §5 means run the commands
  and paste the output — that *is* the check. Don't stack a self-review on top; §7's
  pre-merge review is a separate gate on *merging*, not a second verification.
- **Sessions are teammates you can't talk to.** One branch per unit of work, claimed by
  its `PROGRESS.md` In-flight entry. Never merge another session's work. The rest —
  branch/PR rules and the authority split — is
  [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) §7.

## What this is

A self-hosted, semi-automated job-application system — **two services, one shared
SQLite database**:

- **`apps/web`** — Next.js 14 + Prisma tracker UI (applications, KPIs, charts,
  Discovered Jobs queue).
- **`apps/worker`** — Python 3.11 pipeline: fetch (board adapters + generic
  custom/browser recipe executors) → screen (Ollama) + score fit (Codex CLI default /
  Claude alternate) → notify (Telegram). Human applies by hand.

## Run / test / build

Run `make help` from the repo root — every target is self-documenting.

## Conventions

- **Prisma owns the schema** (`apps/web/prisma/schema.prisma`). The worker reads/
  writes rows but issues **no DDL**. Change schema there, then `make db-push`.
  Status/category enums live in `apps/web/src/lib/constants.ts`.
- **Worker modules are pure + dependency-injected.** Real services are wired only
  in `ats_worker/run.py`; tests mock everything (no network/keys). Keep it that way.
- **Web:** mutations go through Server Actions (`lib/actions.ts`); run `make lint`
  before pushing.
- **Branches:** never force-push `main`.
- **Privacy:** never commit `.env`, `resume/`, `config.yaml`, or `db/` — enforced by
  `.gitignore`, `make check-privacy` in CI, and a PreToolUse hook.

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
