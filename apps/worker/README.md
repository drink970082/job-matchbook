# worker (ats-worker)

The Python pipeline service of the ATS project — one of two services in this
repo (the other is the [`../web`](../web) app). On a schedule it **fetches**
postings from company ATS boards and **screens** each against your hard requirements
(degree, work authorization, clearance, location, internships; local Ollama by default),
optionally followed by the JEV keep/skip filter (`--jev`). Your AI assistant reads the
results over MCP; you apply by hand and record it there or with the web's "Mark Applied".

```
fetch ──► screen
(boards)  (hard requirements; results in job_screenings)
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

**Adding a company is a watchlist row, not code.** Use the `onboard-board` skill: it
tries a known platform, then a plain-HTTP `custom` recipe, then a `browser` recipe.
MCP `add_source` adds known-ATS boards only. Write a new adapter only for a platform none of those can read:

1. `fetch/<source>.py` with `SOURCE` and `fetch` (lists a board), `fetch_one` (one job
   by id, for a feed-only source), or both.
2. In `fetch/__init__.py`: the `from . import (...)` list, `__all__` and one
   `ADAPTERS` line; add it to `RECIPE_SOURCES`, `STUB_GATE_SOURCES` or
   `STUB_GATE_NOW_SOURCES` only if its `fetch` takes that kwarg.
3. If it is watchlist-capable: `config.VALID_SOURCES` (and `RECIPE_SOURCES` if it
   takes a recipe), mirrored in the web's `src/lib/constants.ts`.
4. If the discovery feed should reach it (always, for a feed-only source): a host
   route in `feed/resolve.py:resolve_url`.
5. A row in the SPEC source-coverage matrix.

`test_source_enums_sync.py` fails CI if the source lists in steps 2, 3 and 5 disagree.
Nothing checks step 4 (a feed-only adapter without a route is dead code) or a missing
stub-gate entry (that only costs a skipped optimization).

## Config-time inputs (you provide)

1. `config.yaml` — company list + an optional `title_filter` (title-keyword
   pre-filter) + the `candidate` screening block (degree / work authorization /
   clearance / locations / internships; the screen records a verdict per posting in
   `job_screenings` and never deletes one) + schedule. See the committed sample.
2. `.env` — copy `.env.example` → `.env` and set `OLLAMA_HOST` (or pick another
   `SCREEN_BACKEND`; only the metered API backends need a key).

## Run

The worker runs **natively on the host** — needs the Python deps installed, and
Ollama running on the **host** (uses the GPU):
```bash
ollama pull qwen3.5:4b && ollama serve
pip install -r requirements.txt
python -m ats_worker.run --once     # single test pass
python -m ats_worker.run            # daemon: wall-clock slots, NO pass at launch
python -m ats_worker.run --run-now  # ... plus one pass right now
```

`docker compose up` (from the repo root) only starts the **web** stack — the
worker isn't containerized (the CLI screen backends authenticate from the host's own
login, and the default screen is pinned to the host by Ollama's GPU). See
`docs/SPEC.md` §6.

## The screen pass

Every pass fetches as usual, runs the hard-requirements screen and records the result in
`job_screenings` (`--screen-only` is an accepted alias). It needs no résumé. Successful
results are cached until an explicit one-shot re-screen; provider errors can retry on a
later pass. Codex selection defaults to Luna at medium:

Before the first use against an existing database, apply the Prisma-owned schema from
the repository root with `make db-push`; this adds the `job_screenings` table. The worker
does not issue DDL.

```bash
cd apps/worker
python -m ats_worker.run --once --screen-backend codex \
  --screen-model gpt-5.6-luna --screen-effort medium --screen-limit 40 --screen-workers 1
```

The default cap is 40 provider calls per pass. To explicitly screen all eligible work,
replace `--screen-limit 40` with `--screen-unlimited`; the two flags are mutually
exclusive. Unlimited mode overrides the environment/default cap and keeps success
caching, the provider breaker and the per-DB pass lock. Zero is still an invalid numeric
limit.

The expanded 103-row evaluation measured Luna at zero false disqualifications
(30/37 recall, three flips) against seven for qwen3.5:4b (31/37, no flips).
That historical evaluation does not record effort, so medium is not separately
measured. Do not rerun an unchanged evaluation.

## MCP server

`python -m ats_worker.mcp` (after `pip install -r requirements-mcp.txt`) is the stdio MCP
server your AI client starts: read tools over a read-only SQLite connection, plus write
tools through the web's `/api/v1` when `ATS_API_KEY` is set. Install, write-key and client
connection steps (Claude Code, Codex, ChatGPT through a tunnel) are in
[SETUP Path D](../../docs/SETUP.md#path-d--ai-assistant-access-mcp); the tool contracts are
in [SPEC §7.1](../../docs/SPEC.md#71-worker-appsworkerats_worker).

## Module map

- **Entry points:** `run.py` (pipeline pass / daemon), `doctor.py` (preflight),
  `mcp/` (`python -m ats_worker.mcp`, the MCP server).
- **Pipeline stages:** `fetch/` (board adapters + recipe executors), `feed/`
  (discovery feeds), `screening/` (hard-requirement screen + backends), `jev.py`
  (keep/skip filter, ranks via `ranking/`), orchestrated by `pipeline.py`.
- **Shared infrastructure:** `config.py`, `db.py`, `util.py`, `usage.py` (quota
  telemetry), `source_lifecycle.py`, `prompts/`.
- **Offline, provider-free:** `preselection/` (profile, replay, review batches,
  assessment view, rehearsal and their `*_cli.py` entry points). Nothing on the
  production path imports it.

## Tests

```bash
python -m pytest        # pure unit tests; no network / Ollama / Codex / Claude needed
```
All external services are dependency-injected, so the suite runs anywhere Python +
pytest exist. For MCP protocol tests, install `requirements-mcp.txt` first; CI installs
that pinned SDK and exercises both in-memory and stdio clients.
