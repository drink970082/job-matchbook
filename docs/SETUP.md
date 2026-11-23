# Setup

Choose a path explicitly. The web app and native worker share SQLite; the MCP server is a
separate host process your AI client starts. Path D connects an assistant end to end;
[SPEC §12](SPEC.md#12-setup-and-deployment) carries the longhand worker/deployment
commands, and [ARCHITECTURE](ARCHITECTURE.md) distinguishes implemented paths from targets.

## Prerequisites by path

| Requirement | Needed for |
|---|---|
| Docker + Compose | Containerized web/autoheal |
| Node 24+ | Web development/tests or running web without Docker |
| Python 3.11+ | Native worker and MCP |
| Configured public job sources/network access | Discovery |
| A selected screen backend | Optional screening; no model needed for fetch-only |
| Target roles in the candidate profile + OpenRouter key or a screen backend | Optional triage (JEV keep/skip) |
| MCP SDK extra (`requirements-mcp.txt`) and an MCP client (Claude Code, Codex, or ChatGPT via a tunnel) | An AI assistant reading local ATS data |
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
cache/breaker behavior, but does not remove subscription limits.

## Path C2 — optional triage (JEV keep/skip)

Triage reads the candidate profile: fill in your education, experience and at least one
target role (plus open to / not interested) in Settings or with MCP
`set_candidate_profile`. It uses the committed default question packs
(`apps/worker/ats_worker/triage_packs/`); nothing else to set up.

Then pick the keep/skip backend (`--jev-backend` / `JEV_BACKEND`):

- `openrouter-native` (default) — metered OpenRouter calls, needs `OPENROUTER_API_KEY`,
  `--jev-max-usd` caps settled spend per pass. SPEC's measurements are for the
  operator's private packs; the default packs are unmeasured on either backend.
- `extract` — the screen backend answers the same packs (no OpenRouter key; it receives
  your profile). Unvalidated; `--jev-limit` (default 40 postings) is the only cap.

```bash
python -m ats_worker.run --screen-only ... --jev --once                       # native
python -m ats_worker.run --screen-only ... --jev --jev-backend extract --once # extract
```

Verdicts live in `job_jev_assessments`; MCP `list_jobs` hides a current `skip` by
default. Native without the key logs a line and skips the stage.

State your years of experience in `yoe-context.txt`: the example experience question
skips a posting whose required minimum is above them.

**What works with what you have** (screen = hard requirements; keep/skip = `--jev`):

| You have | Screen (`SCREEN_BACKEND`) | Keep/skip |
|---|---|---|
| nothing | `none` (deterministic gates only, low recall on sponsorship) | off |
| a GPU, or any Ollama host | `ollama` (default, free) | `extract` |
| ChatGPT subscription | `codex` (`codex login`) | `extract` |
| Claude subscription | `claude-code` (`claude` logged in) | `extract` |
| an API key (OpenAI, Gemini, ...) | `api` + `SCREEN_MODEL` + `SCREEN_API_KEY` (+ `SCREEN_API_BASE_URL` for non-OpenAI), metered | `extract` |
| a local OpenAI-compatible server (LM Studio, vLLM) | `api` + `SCREEN_MODEL` + `SCREEN_API_BASE_URL`, no key | `extract` |
| an OpenRouter key | `api` + `SCREEN_API_BASE_URL=https://openrouter.ai/api/v1` + `SCREEN_API_KEY` + `SCREEN_MODEL`, metered | `openrouter-native` (same key as `OPENROUTER_API_KEY`) or `extract` |

## Path D — AI-assistant access (MCP)

The MCP server is a stdio process started by your AI client. It reads the shared SQLite
database read-only; with a write key it can also log applications, update statuses and
notes, override keep/skip, manage the watchlist and set preferences and the JEV
profile, all through the
web's `/api/v1`. It has no user authentication of its own: connect it only to a client or
workspace you trust, and it exposes whatever its tools return to that chat.

**1. Install and check the server** (after Path A or B, so the schema exists):

```bash
make db-push                                   # from the repo root
cd apps/worker
python -m pip install -r requirements.txt -r requirements-mcp.txt
python -m ats_worker.mcp                       # stdio; Ctrl-C to stop
```

`ATS_DB_PATH=/absolute/path/to/applications.db` overrides the database; omit it when the
checkout's default (`apps/web/prisma/applications.db`) is right. The server must start
from `apps/worker`, or with `PYTHONPATH` pointing there, so the module resolves.

**2. Optional: enable writes.** Set `ATS_API_KEY_READ_WRITE` (and optionally
`ATS_API_KEY_READ`) to long random values in the root `.env` and restart the web app;
then give the MCP server the same read-write value as `ATS_API_KEY`. `ATS_API_URL`
overrides the web address (default `http://127.0.0.1:3000`). With no key the API answers
`503` and the server offers only its read tools.

**3. Connect a client.** Replace `/abs/path/to/checkout` with your checkout.
The same commands, a Claude Desktop config and starter prompts are in
[`apps/web/templates/mcp/`](../apps/web/templates/mcp/), which the web app's setup
checklist shows with Copy buttons.

Claude Code or Codex CLI on the same machine:

```bash
claude mcp add ats -e PYTHONPATH=/abs/path/to/checkout/apps/worker \
  -- python3 -m ats_worker.mcp
codex mcp add ats --env PYTHONPATH=/abs/path/to/checkout/apps/worker \
  -- python3 -m ats_worker.mcp
```

Add `ATS_DB_PATH=...` or `ATS_API_KEY=...` the same way (`-e` / `--env`) when you need
them. Use the Python that has the requirements installed (a venv's absolute path works).

ChatGPT, through [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels):
install the tunnel client from the Platform tunnel settings (it needs a tunnel id, a
runtime API key and Tunnels Read + Use access), then initialize a dedicated profile from
`apps/worker` without putting the key in shell history:

```bash
cd apps/worker
read -r -p 'OpenAI tunnel ID: ' ATS_TUNNEL_ID
read -r -s -p 'Tunnel runtime API key: ' CONTROL_PLANE_API_KEY; printf '\n'
export CONTROL_PLANE_API_KEY
tunnel-client init --sample sample_mcp_stdio_local --profile ats-local \
  --tunnel-id "$ATS_TUNNEL_ID" --mcp-command 'python -m ats_worker.mcp'
tunnel-client doctor --profile ats-local --explain
tunnel-client run --profile ats-local
```

Do not reuse a profile meant for another server. Once the client reports healthy and
ready, in ChatGPT Plugins choose **Add custom MCP server -> Connection: Tunnel**, select
the tunnel, configure authentication, accept the risk warning, then create and install
the plugin. If your tunnel client release differs, start from its `help quickstart`. Keep
the runtime key out of logs and the repo; for unattended use, run the tunnel client
under a service manager.

**4. Verify.** Ask the assistant to call `get_ats_overview`, page through `list_jobs`,
and read a long job description to its last chunk. A connection counts as working only
after you see a completed tool call.

For a scheduled daily brief, follow [DAILY_BRIEF](DAILY_BRIEF.md); the server also offers a
`daily_brief` prompt for interactive use. Test an actual unattended run, not only an
interactive call.

## Where settings live

| Setting | Location | Lifecycle |
|---|---|---|
| Candidate profile (title filters, max age, hard requirements, background, preferences) | Config seed, then DB | `config.yaml` seeds it once; after that edit it in Settings or with MCP `set_candidate_profile` (config edits are logged and ignored) |
| Schedule, feeds, browser opt-in | Private `config.yaml` | Edit and restart intentionally |
| Watchlist | Config seed, then DB | After initial seed, manage it in the web Sources tab (paste a careers URL, remove), through MCP (`add_source`/`remove_source`), or with the onboard-board skill for custom/browser recipes; config edits do not replace DB rows |
| Provider selection/secrets | Private `.env` and CLI flags | Choose an explicit mode; metered providers are opt-in |
| Private résumé/profile | `apps/worker/resume/` | Not read by the worker (a legacy `jev_dir` there seeds the profile once); private onboarding material |
| Downstream analysis rubric (optional) | ChatGPT/Claude task, project or accessible user-controlled document | Keep current and available to each run; memory is not a versioned config |
| Application history and job evidence | Shared SQLite directory | Back up with SQLite-aware tools; preserve WAL sidecars |

All private config, résumé and database paths are gitignored.
