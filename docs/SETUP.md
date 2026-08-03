# Setup

The friendly front door. This page gets you oriented, helps you decide *which*
setup you need, and flags the things that surprise people. For the authoritative,
always-current command list, follow the links into
[**`SPEC.md` §12**](./SPEC.md#12-setup-and-deployment) — that section is the source
of truth and this one intentionally doesn't duplicate it.

Two things to internalise before anything else:

- This is **two services sharing one SQLite database**: a **web app** (the
  tracker/dashboards, runs in Docker) and a **worker** (the fetch→screen→score→notify
  pipeline, runs **natively on your host** — *not* in Docker).
- You can run **just the web app** (a clean manual tracker) and skip the whole
  pipeline. Do that first if you're evaluating.

## Before you start — prerequisites

| You need | For | If you don't have it |
|----------|-----|----------------------|
| Docker + Compose (≥ 24) | The web app | Required for the web app |
| Node 20+ | Web dev/tests (and non-Docker run) | Required unless you only use Docker |
| Python 3.11+ | **The worker** (native) | Required for the pipeline |
| **Ollama** reachable (local GPU, or remote via `OLLAMA_HOST`) — or any of five other screen backends | The hard-requirements screen | Required for the pipeline in some form; no GPU and no Ollama at all? set `SCREEN_BACKEND` to `codex`/`claude-code`/`claude-api`/`openai-api`/`none` instead (SPEC §7.1) |
| **Codex CLI + a ChatGPT subscription** | Fit scoring (the **default** backend) | No subscription? Use `SCORE_BACKEND=claude` + an `ANTHROPIC_API_KEY` (metered) |
| A Telegram bot | Match alerts (**optional**) | Skip it — matches still land in the web Discovered-Jobs tab, just without a push alert |

## Three things that surprise everyone

1. **`docker compose up` starts only the web app.** The worker is deliberately
   *not* containerised (it needs host-side Ollama and your `codex login`). You start it
   yourself: `cd apps/worker && python -m ats_worker.run`.
2. **The default fit scorer needs a ChatGPT subscription**, not an API key. Run
   `codex login` once on the worker host (`codex doctor` should show auth ok). No
   subscription → switch the backend to `claude-code` (Claude Code CLI, also
subscription-billed, no key), or `claude-api` and supply `ANTHROPIC_API_KEY`.
3. **The screen doesn't need Ollama at all, and Ollama doesn't need a local GPU.**
   The worker reaches Ollama at `localhost:11434` by default; set `OLLAMA_HOST` to
   point at a remote or cloud Ollama if the worker host has no GPU, or skip Ollama
   entirely with `SCREEN_BACKEND=codex`/`claude-code`/`claude-api`/`openai-api`/`none`.

## Path A — tracker only (~5 min)

Just the web app, no pipeline. You add applications by hand; the Discovered-Jobs
queue stays empty until you set up the worker.

```bash
make install && make db-push && make dev     # → http://localhost:3000
```

(Same commands as the [root README](../README.md#quick-start); the longhand is
`cd apps/web && npm install && npx prisma generate && npx prisma db push && npm run dev`.)

## Path B — full pipeline

Fastest start: **`make setup`** — installs web + worker deps, creates the DB, and copies
the gitignored config templates (`config.yaml`, `.env`) *only where they don't already
exist*. Fill those in, add your own `resume/resume.txt` (deliberately not templated — a
placeholder there would be scored as your real résumé), then run **`make doctor`** to
check what's present before the first pass. (Or follow the longhand numbered steps in
[**`SPEC.md` §12**](./SPEC.md#12-setup-and-deployment).)

Two things worth knowing before you start: unknown or typo'd `config.yaml` keys
fail loud at startup (a stale field can never silently do nothing), and the first
run to aim for is `python -m ats_worker.run --once` — a single pass whose matches
land in the Discovered-Jobs tab (and Telegram too, if you configured a bot). Drop
`--once` to run on a schedule.

## Where each setting lives (this trips people up)

Config is split across a file and the database, with different lifecycles:

| Setting | Lives in | Notes |
|---------|----------|-------|
| Candidate hard-constraints, `title_filter`, `schedule_hours` | `config.yaml` | File-only; edit and restart the worker. |
| **Watched companies** | `config.yaml` **→ then the DB** | The `companies:` list is a **one-time seed**. After the first run it's managed in the web app's **Watchlist** tab; later edits to the file are ignored (re-seed with `--import-companies`). |
| Secrets + backend choice (Telegram / Ollama / `SCREEN_BACKEND` / `SCORE_BACKEND` / API keys) | `.env` | Gitignored. `SCREEN_BACKEND` picks the hard-requirements screen — `ollama` (default, free, local) or `codex`/`claude-code`/`claude-api`/`openai-api`/`none`; `none` is low-recall on sponsorship (SPEC §7.1). |
| Résumé + profile | `apps/worker/resume/*.txt` | Gitignored personal data; every `*.txt` is loaded as a résumé version. |

All of `config.yaml`, `.env`, `resume/`, and `db/` are gitignored — the repo ships
only `*.example` templates.
