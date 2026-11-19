# Setup

Choose a path explicitly. The web app and native worker share SQLite; the read-only MCP
is a separate host process. [SPEC §12](SPEC.md#12-setup-and-deployment) supplies detailed
commands; [ARCHITECTURE](ARCHITECTURE.md) distinguishes implemented paths from targets.

## Prerequisites by path

| Requirement | Needed for |
|---|---|
| Docker + Compose | Containerized web/autoheal |
| Node 24+ | Web development/tests or running web without Docker |
| Python 3.11+ | Native worker and MCP |
| Configured public job sources/network access | Discovery |
| A selected screen backend | Optional screening; no model needed for fetch-only |
| OpenRouter key + private `jev_dir` inputs | Optional JEV keep/skip filter |
| MCP SDK extra, absolute `ATS_DB_PATH`, tunnel/plugin connection | An AI assistant reading local ATS data |
| `ATS_API_KEY_READ_WRITE` / `ATS_API_KEY_READ` in the root `.env` | The loopback write API `/api/v1` (off without a key) |

A local GPU/Ollama and a résumé are not prerequisites for the tracker or fetch-only
discovery. Subscription inference consumes allowance; metered APIs can incur separate
bills.

## Path A — tracker only

```bash
make install && make db-push && make dev
```

Enter/import applications manually. Existing data stays yours; never replace the database
with a test fixture. Docker users can run web with `make up` after configuration.

## Path B — discovery

```bash
make setup
make doctor
make up
cd apps/worker
python -m ats_worker.run --fetch-only --once
```

Fill the private config for intended sources/intake first. `make setup` does not overwrite
existing files. Doctor reports the broader installation; a missing optional screen backend
is not a requirement to enable it. Fetch-only still applies configured title/candidate/age
filters and runs the existing expiry/retry behavior. Dropping `--once` enables the
configured schedule. The web's All-jobs inventory lists every fetched posting.

## Path C — optional standalone screening

```bash
cd apps/worker
python -m ats_worker.run --screen-only --screen-backend codex \
  --screen-model gpt-5.6-luna --screen-effort medium --screen-limit 40 --once
```

Authenticate the Codex CLI on the host. Results live in `job_screenings` without changing posting lifecycle status. Completed
is not synonymous with passed. Numeric limits count provider calls; deterministic checks
need none. Explicit `--screen-unlimited` replaces the numeric limit while preserving
cache/breaker behavior, but does not remove subscription limits. The operator uses that
explicit unlimited mode with one worker; this bounded example is not a deployment change.

## Path C2 — optional JEV keep/skip filter

Set `jev_dir` in `config.yaml` (four private input files, see `config.yaml.example`)
and `OPENROUTER_API_KEY` in `apps/worker/.env`, then add the flags to a screening run:

```bash
python -m ats_worker.run --screen-only ... --jev --jev-limit 300 --jev-max-usd 0.10 --once
```

Calls are metered; `--jev-max-usd` caps settled spend per pass. Verdicts live in
`job_jev_assessments`; MCP `list_jobs` hides a current `skip` by default. Without the key
the stage logs a line and is skipped.

## Path D — AI-assistant access (MCP)

Follow [SPEC §12](SPEC.md#12-setup-and-deployment) for the MCP extra, stdio command,
absolute database path and private tunnel configuration. Connect and test the ATS plugin
in ChatGPT; verify overview, pagination, full JD chunks and application records.
No API key, tunnel identity or private profile belongs in the repo.

Daily Brief instructions/background and a scheduled task are separate user-controlled
configuration. Test an actual unattended run, not only an interactive call. MCP write
tools go through the web's `/api/v1`. To enable them, set `ATS_API_KEY_READ_WRITE` (and
optionally `ATS_API_KEY_READ`) to long random values in the root `.env`, restart the web
container, and give the MCP server the same read-write value as `ATS_API_KEY`; with no
key the API answers `503` and MCP stays read-only.

## Where settings live

| Setting | Location | Lifecycle |
|---|---|---|
| Collection filters, candidate facts, schedule | Private `config.yaml` | Existing intake/screen semantics; edit and restart intentionally |
| Watchlist | Config seed, then DB | After initial seed, manage in web; config edits do not replace DB rows |
| Provider selection/secrets | Private `.env` and CLI flags | Choose an explicit mode; metered providers are opt-in |
| Private résumé/profile | `apps/worker/resume/` | Read by the worker only through `jev_dir` (JEV inputs); otherwise private onboarding material |
| Primary personal judgment rubric | ChatGPT task/project or accessible user-controlled document | Keep current and available to each run; memory is not a versioned config |
| Application history and job evidence | Shared SQLite directory | Back up with SQLite-aware tools; preserve WAL sidecars |

All private config, résumé and database paths are gitignored.
