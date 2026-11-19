# AGENTS.md

Instructions for any coding agent working in this repo. Claude Code reads
[`CLAUDE.md`](./CLAUDE.md), which carries the same rules plus Claude-Code-specific
conduct (doc length, subagent policy) that will not apply to you.

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
- **`docs/PROGRESS.md`** — the *delta* only: in flight, branch claims, current
  limitations and open defects. Completed work lives in SPEC, history in `CHANGELOG.md`. Two files hang off
  it and are loaded on demand, not by default: **`docs/BACKLOG.md`** (the open catalogue
  — unverified/deferred and enhancements) and **`docs/REJECTED.md`** (proposals
  evaluated and turned down — read your block's entry before proposing a redesign).
- **`docs/PRINCIPLES.md`** — the design DNA, for design forks. The four-way uncertainty
  policy (keep / fail loud / circuit break / retry) is the part most often misread:
  "err toward keep" is one row of four.
- **`docs/DEVELOPMENT.md`** — the session rail: task classification, the verify gate,
  definition of done, and the branch/PR/merge protocol (§7).
- **`docs/ARCHITECTURE.md`** and **`docs/ROADMAP.md`** — ownership boundaries (an AI
  client orchestrates over MCP; epic #152) and product order. Targets are not shipped
  capabilities.
- **`docs/EVALUATION.md`** — which check a change owes, and private-corpus limits.
  Unrelated source/MCP/UI/docs work owes no live model eval; provider runs need scoped
  authorization.
- **`docs/SCORING.md`** — the screen subsystem contracts and the measured constraints on
  LLM judges. Read before touching a screen prompt, JEV, or an eval.

When you change behavior, update the matching section of `SPEC.md`, `PROGRESS.md` and
`CHANGELOG.md` **in the same commit**. Conventions in `CONTRIBUTING.md`.

**Every doc except `CHANGELOG.md` states the CURRENT state, never the history of how it
got there.** `CHANGELOG.md` is the one file that is a record of *when*; git is the record
of *what happened*. So, everywhere else:

- **Delete a finished item — do not mark it done.** No `DONE 2026-08-04`, no `SHIPPED
  (#57)`, no struck-through entry, no "the historical framing follows". A shipped feature
  leaves `PROGRESS.md` for `SPEC.md` + `CHANGELOG.md`; a resolved backlog entry is deleted.
- **Do not append a dated completion record** to an entry that is still open. Rewrite the
  entry to say what is true now. If a residual survives, the entry *is* the residual.
- **Do not narrate the document's own edit history** — "an earlier draft said", "two
  earlier versions had it wrong", "the counts above are now history". Correct the text and
  delete the wrong version; a correction only needs to exist while a wrong figure is still
  circulating somewhere you cannot edit.
- **Keep a date only when it qualifies a fact that is still live** — a measurement whose
  staleness matters, a decision whose window is open. Not to timestamp completion.
- **The exception is a negative result**: what was tried and failed, and why, is not
  recoverable from git (a failed experiment usually leaves no commit at all). Write it as a
  present-tense constraint — "batching is dead at every size above 1" — in `SCORING.md`
  §"Measured history" or `REJECTED.md`, not as a dated log entry. Same for anything whose
  only record is a **gitignored** artifact, like the eval corpora: state what the corpus
  contains and why, since git cannot.

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

A self-hosted job-source, evidence and tracking system that an AI client (ChatGPT,
Claude, Codex) drives over MCP. **Two services and an MCP server, one shared SQLite
database:**

- **`apps/worker`** — Python 3.11 pipeline: fetch (board adapters + generic
  custom/browser recipe executors) -> screen hard requirements (Ollama default, or a
  CLI/API backend) -> optional `--jev` keep/skip filter (OpenRouter, paid). Also hosts
  the MCP server (`ats_worker/mcp/`).
- **`apps/web`** — Next.js 14 + Prisma tracker UI, plus the key-scoped loopback
  `/api/v1` write API the MCP server calls. Becoming a read-only dashboard except
  Applications and Settings (#158).

A human applies by hand. The old fit scorer and Telegram alerts are removed.

## Run / test / build

`make help` from the repo root — every target is self-documenting.

## Conventions

- **Prisma owns the schema** (`apps/web/prisma/schema.prisma`). The worker reads and
  writes rows but issues **no DDL**. Change the schema there, then `make db-push`.
  Status/category enums live in `apps/web/src/lib/constants.ts`.
- **Worker modules are pure and dependency-injected.** Real services are wired only in
  `ats_worker/run.py`; tests mock everything, with no network and no keys.
- **Web:** mutations go through Server Actions (`lib/*-actions.ts`, one file per
  domain); the `/api/v1` route handlers are thin wrappers over them. Run `make lint` before pushing.
- **Never force-push `main`.**
- **Privacy:** never commit `.env`, `resume/`, `config.yaml`, or `db/` — enforced by
  `.gitignore` and `make check-privacy` in CI.

## Gotchas

- **Ollama runs on the host** (GPU); the worker is native and reaches it at
  `localhost:11434` — see SPEC §6.
- **SQLite is mounted as a directory** (`./db` -> `/data`), not a single file, so the WAL
  `-wal`/`-shm` sidecars are shared between the web container and the native worker. A
  single-file mount silently breaks WAL across the two processes.
- **Coverage gates:** worker `fail_under = 84` (`apps/worker/pyproject.toml`); web gated
  via `jest.all.config.ts`. CI also runs the schema-drift guard.
- Default screen model: local `qwen3.5:4b` (Ollama); the Codex screen defaults to `gpt-5.6-luna`.
  Override via env / CLI — see SPEC §7.1.
