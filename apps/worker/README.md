# worker (ats-worker)

The Python pipeline service of the ATS project — one of two services in this
repo (the other is the [`../web`](../web) app). On a schedule it: **fetch**
postings from company ATS boards → **score** each against your resume (local
Ollama) → **tailor** a one-page LaTeX resume for high scorers (Claude +
tectonic) → **notify** you on Telegram. You still apply by hand, then one-click
"Mark Applied" in the web UI.

```
fetch ──► score ──► tailor ──► notify
(boards) (Ollama) (Claude+    (Telegram)
                   tectonic)
```

Postings live in the `job_postings` table of the SQLite db shared with the
Next.js app. Prisma owns the schema; the worker only reads/writes rows.

## Supported boards

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
   pre-filter) + the `candidate` screening block (experience / degree / work
   authorization / clearance / locations + freeform dealbreakers; auto-discards
   conflicting postings) + score threshold + schedule. See the committed sample.
2. `resume/master.tex` and `resume/resume.txt` — your résumé content, used for
   keyword/fit scoring and tailoring. See `resume/README.md`.
3. `.env` — copy `.env.example` → `.env` and fill in `ANTHROPIC_API_KEY`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OLLAMA_HOST`.

## Run

**Docker (recommended)** — from the repo root:
```bash
# Ollama runs on the HOST (uses the GPU):  ollama pull qwen2.5:7b && ollama serve
UID=$(id -u) GID=$(id -g) docker compose up --build
```
The worker shares the `./db` directory and `./resumes` volume with the web app.
The db is mounted as a **directory** (not a single file) so SQLite WAL works
across both containers.

**Local (no Docker)** — needs `tectonic` on PATH and the Python deps installed:
```bash
pip install -r requirements.txt
python -m ats_worker.run --once     # single test pass
python -m ats_worker.run            # scheduler (immediate pass + every N hours)
```

## Tests

```bash
python -m pytest        # pure unit tests; no network / Ollama / Claude / tectonic needed
```
All external services and `tectonic`/`pypdf` are dependency-injected, so the
suite runs anywhere Python + pytest exist.
