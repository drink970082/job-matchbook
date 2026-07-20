# worker (ats-worker)

The Python pipeline service of the ATS project — one of two services in this
repo (the other is the [`../web`](../web) app). On a schedule it: **fetch**
postings from company ATS boards → **score** each against your resume (hard
requirements screened locally on Ollama; fit scored by the Codex CLI by
default, Claude as a metered alternate) → **notify** you on Telegram for every
high scorer. You still apply by hand, then one-click "Mark Applied" in the web
UI.

```
fetch ──► score ─────────────► notify
(boards) (Ollama screen +      (Telegram)
          Codex/Claude fit score)
```

Postings live in the `job_postings` table of the SQLite db shared with the
Next.js app. Prisma owns the schema; the worker only reads/writes rows.

## Supported boards

11 watchlist-capable sources are registered in `fetch/ADAPTERS`: the five
detailed below, plus `smartrecruiters`, `workable`, `icims`, `phenom` (same
pattern — a public per-board API) and `custom`/`browser` (generic recipe
executors driven by a declarative recipe in `config.yaml`, not a fixed public
API). Two more sources, `oracle` and `jobvite`, are feed-resolution-only (no
public list endpoint, so they can't be enumerated as a watchlist company).

Set per company in `config.yaml`. `slug` is the handle in the board's public URL.

| `source` | Public API | Example slug source |
|----------|------------|---------------------|
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | `boards.greenhouse.io/acme` → `acme` |
| `lever` | `api.lever.co/v0/postings/{slug}` | `jobs.lever.co/foobar` → `foobar` |
| `ashby` | `api.ashbyhq.com/posting-api/job-board/{slug}` | `jobs.ashbyhq.com/example` → `example` |
| `workday` | CXS list + per-job detail (N+1) | `acme.wd5.myworkdayjobs.com/External_Careers` → `acme/wd5/External_Careers` |
| `pinpoint` | `{slug}.pinpointhq.com/postings.json` | `acme.pinpointhq.com` → `acme` |

Most sources take a single-token `slug`. `workday` packs three parts as
`tenant/datacenter/site` (it does a cheap list call then one detail call per
posting for the description).

Add a board by writing one `fetch/<source>.py` adapter (`parse_jobs` + `fetch`)
and registering it in `fetch/ADAPTERS` (and in `config.VALID_SOURCES`).

## Config-time inputs (you provide)

1. `config.yaml` — company list + an optional `title_filter` (title-keyword
   pre-filter) + the `candidate` screening block (degree / work authorization /
   clearance / locations / internships; auto-discards conflicting postings) + score
   threshold + schedule. See the committed sample.
2. `resume/*.txt` — one or more labeled résumé versions (plus an optional
   `personal_profile.txt` about-me context), used for keyword/fit scoring.
   See `resume/README.md`.
3. `.env` — copy `.env.example` → `.env` and fill in `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `OLLAMA_HOST`. Fit-scoring auth is `codex login` (Codex
   CLI, the default `SCORE_BACKEND`, no env var needed) or `ANTHROPIC_API_KEY`
   only when `SCORE_BACKEND=claude`.

## Run

The worker runs **natively on the host** — needs the Python deps installed, and
Ollama running on the **host** (uses the GPU):
```bash
ollama pull qwen3.5:4b && ollama serve
pip install -r requirements.txt
python -m ats_worker.run --once     # single test pass
python -m ats_worker.run            # scheduler (immediate pass + every N hours)
```

`docker compose up` (from the repo root) only starts the **web** stack — the
worker isn't containerized (its default fit-score backend shells out to the
Codex CLI, which authenticates from the operator's host `~/.codex`, and it's
already pinned to the host by Ollama's GPU). See `docs/SPEC.md` §6.

## Tests

```bash
python -m pytest        # pure unit tests; no network / Ollama / Codex / Claude needed
```
All external services are dependency-injected, so the suite runs anywhere
Python + pytest exist.
