# AGENTS.md

Instructions for any coding agent working in this repo. Claude Code reads
[`CLAUDE.md`](./CLAUDE.md), which carries the same rules plus Claude-Code-specific
conduct (effort levels, subagent policy) that will not apply to you.

This is a real file, not a symlink to `CLAUDE.md`, on purpose: a symlinked `AGENTS.md`
is served as its 9-byte target path over `raw.githubusercontent.com`, and degrades into
a plain text file containing `CLAUDE.md` on a Windows checkout without
`core.symlinks=true` — an agent would find a file, read nine characters, and stop
looking. Keep the two in sync by hand; there is little here to drift.

## Read before you touch code

**`docs/PROGRESS.md`'s "In flight" section is unconditional** — it is the claim
registry, and skipping it is how two sessions collide on one branch. Pull in the rest as
the task needs:

- **`docs/SPEC.md`** — what the system *is*: capability map, data model, behaviors and
  invariants. Source of truth.
- **`docs/PROGRESS.md`** — the *delta* only: in flight, the pick order, quota, open
  defects. Completed work lives in SPEC, history in `CHANGELOG.md`. Two files hang off
  it and are loaded on demand, not by default: **`docs/BACKLOG.md`** (the open catalogue
  — unverified/deferred and enhancements) and **`docs/REJECTED.md`** (proposals
  evaluated and turned down — read your block's entry before proposing a redesign).
- **`docs/PRINCIPLES.md`** — the design DNA, for design forks. The four-way uncertainty
  policy (keep / fail loud / circuit break / retry) is the part most often misread:
  "err toward keep" is one row of four.
- **`docs/DEVELOPMENT.md`** — the session rail: task classification, the verify gate,
  definition of done, and the branch/PR/merge protocol (§7).
- **`docs/SCORING.md`** — the scoring subsystem as a *rebuild spec*, self-contained and
  portable (it assumes no repo knowledge, so it restates what SPEC covers). Read it
  before touching `score/`, either prompt, or an eval — its "measured history" section
  records what has already been tried and failed, and its "known-hostile directions"
  list is why several odd-looking rules are the way they are.

When you change behavior, update the matching section of `SPEC.md`, `PROGRESS.md` and
`CHANGELOG.md` **in the same commit**. Conventions in `CONTRIBUTING.md`.

## Skills

Reusable procedures live in `.claude/skills/` as `SKILL.md` files — the cross-agent
format. `.agents/skills` is a symlink to that directory for agents that look there.
**Verified on `codex-cli` 0.144.5 (2026-07-26):** Codex discovers all three skills
*through* the symlink, and finds **none** of them without it — it does not read
`.claude/skills/` on its own, so the link is load-bearing rather than decorative.
Other agents are untested; if yours does not follow it, read `.claude/skills/` directly.

Current skills: `session-boot` (load repo state before substantive work), `onboard-me`
(configure the tool for a user's job hunt), `onboard-board` (add a company to the fetch
watchlist).

## What this is

A self-hosted, semi-automated job-application system — two services, one shared SQLite
database:

- **`apps/web`** — Next.js 14 + Prisma tracker UI (applications, KPIs, charts,
  Discovered Jobs queue).
- **`apps/worker`** — Python 3.11 pipeline: fetch (board adapters + generic
  custom/browser recipe executors) -> screen (Ollama) + score fit (Codex CLI default,
  Claude alternate) -> notify (Telegram). A human applies by hand.

## Run / test / build

`make help` from the repo root — every target is self-documenting.

## Conventions

- **Prisma owns the schema** (`apps/web/prisma/schema.prisma`). The worker reads and
  writes rows but issues **no DDL**. Change the schema there, then `make db-push`.
  Status/category enums live in `apps/web/src/lib/constants.ts`.
- **Worker modules are pure and dependency-injected.** Real services are wired only in
  `ats_worker/run.py`; tests mock everything, with no network and no keys.
- **Web:** mutations go through Server Actions (`lib/actions.ts`); run `make lint` before
  pushing.
- **Never force-push `main`.**
- **Privacy:** never commit `.env`, `resume/`, `config.yaml`, or `db/` — enforced by
  `.gitignore` and `make check-privacy` in CI.

## Gotchas

- **Ollama runs on the host** (GPU); the worker is native and reaches it at
  `localhost:11434` — see SPEC §6.
- **SQLite is mounted as a directory** (`./db` -> `/data`), not a single file, so the WAL
  `-wal`/`-shm` sidecars are shared between the web container and the native worker. A
  single-file mount silently breaks WAL across the two processes.
- **Coverage gates:** worker `fail_under = 85` (`apps/worker/pyproject.toml`); web gated
  via `jest.all.config.ts`. CI also runs the schema-drift guard.
- Default models: local `qwen3.5:4b` screens hard requirements; fit scoring runs on the
  Codex CLI by default (`gpt-5.6-sol`), or Claude `claude-sonnet-5` when
  `SCORE_BACKEND=claude-code` (Claude Code CLI, subscription) or `claude-api`
(metered Anthropic API) — see SPEC §7.1.
