# worker (ats-worker)

The Python pipeline service of the ATS project — one of two services in this
repo (the other is the [`../web`](../web) app). On a schedule it **fetches**
postings from company ATS boards and **screens** each against your hard requirements
(degree, work authorization, clearance, location, internships; local Ollama by default).
You review in the web UI, apply by hand, then one-click "Mark Applied".

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

Add a board (most new companies need only a watchlist row via the `onboard-board`
skill, not an adapter):

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
   clearance / locations / internships; auto-discards conflicting postings) +
   schedule. See the committed sample.
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

## Optional read-only MCP service

Install the pinned optional SDK only for MCP use, then launch the stdio service from
the worker directory:

```bash
cd apps/worker
python -m pip install -r requirements-mcp.txt
ATS_DB_PATH=/absolute/path/to/applications.db python -m ats_worker.mcp
```

Omit `ATS_DB_PATH` when the repository's default Prisma database path is correct.
Apply the Prisma schema first (`make db-push` from the repository root) so all eight
models, including `job_screenings`, exist. The service opens SQLite read-only and
query-only, offers bounded reads for all eight
Prisma models, and binds no TCP listener. It does not start the worker or change data.
Job descriptions and application notes use chunked reads; watchlist recipe headers and
conventional secret URL query values are redacted. The MCP server has no separate
user-authentication layer, so only connect it to a trusted ChatGPT workspace.

To connect through [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
use a separate ATS profile. Install the current tunnel client from Platform tunnel
settings or its official release. The current guide documents `help quickstart`, the
`sample_mcp_stdio_local` init sample, `doctor --profile ... --explain`, and `run --profile ...`.
For that documented profile flow, enter the runtime key without putting it in shell
history and initialize a distinct profile from `apps/worker`:

```bash
cd apps/worker
read -r -p 'OpenAI tunnel ID: ' ATS_TUNNEL_ID
read -r -s -p 'Tunnel runtime API key: ' CONTROL_PLANE_API_KEY
printf '\n'
export CONTROL_PLANE_API_KEY
tunnel-client init --sample sample_mcp_stdio_local --profile ats-local \
  --tunnel-id "$ATS_TUNNEL_ID" --mcp-command 'python -m ats_worker.mcp'
tunnel-client doctor --profile ats-local --explain
tunnel-client run --profile ats-local
```

Set `ATS_DB_PATH` in the environment first if the checkout's default database path is
not the intended file. The command runs from `apps/worker` so the Python module resolves;
keep the existing Sure target/profile untouched. Confirm the tunnel client's healthy and
ready state, then in ChatGPT Plugins choose **Add custom MCP server → Connection: Tunnel**.
Select the same tunnel, configure authentication, review and accept the risk warning,
create the plugin, and install it before use. OpenAI's current guide requires a tunnel
id, runtime API key, and Tunnels Read + Use access. Keep the key out of logs and repository
files.

If the installed client is outside PATH, use its absolute executable path in these
commands. The operator deployment uses a dedicated ATS profile and systemd user service;
its doctor checks, health/ready endpoints and outbound control-plane polling pass.
The existing Sure profile/service is unchanged. Local stdio verification reads all eight
models, pagination and a complete multi-chunk JD. The operator confirms a successful
ChatGPT `get_ats_overview` invocation; the connected ATS plugin also passes remote reads
through all ten tools, including job details, application notes/history and complete
multi-chunk text. For another deployment, enable its ATS plugin and observe a completed
tool invocation before claiming the connection is verified. Start with the installed
client's `help quickstart` if its release differs from the guide; do not reuse a profile
intended for another server.

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
