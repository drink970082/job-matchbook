# Runtime settings store (#252): design note

Status: proposal, nothing built. Every fork below waits for the operator.
Parent: epic #251 (decisions of 2026-11-20: DB > env > default, write-only keys).
Consumers: #253 (providers), #254 (feeds, browser, interval), #255 (container).

## Today

- `run.main` parses argv once, at startup. Eight env keys become argparse defaults
  (`_ENV_ARGPARSE_KEYS`); the parsed values are closed over by `once()`. A change needs a
  restart.
- `config.yaml` is also loaded once: `feeds`, `enable_browser_sources`, `schedule_hours`.
- Secrets stay in the in-process `env` dict (`SCREEN_API_KEY` in `screen_providers`,
  `OPENROUTER_API_KEY` in `_run_jev`, which also falls back to `os.environ`). They are not
  promoted to `os.environ`, because the codex CLI inherits it.
- Invalid combinations (`api` without a model, `extract` with `none`) are `parser.error`:
  the process does not start.
- The scheduler builds its trigger once from `schedule_hours`.
- `app_settings` holds one key (`categories`). MCP lists its rows but withholds every value
  whose key is not in `SAFE_SETTING_VALUE_KEYS`.
- `doctor.py` resolves env on its own (`{**os.environ, **.env}`).

## Recommendation

1. One typed row `runtime_settings` (id = 1, every column nullable, NULL = not set).
2. A separate table `runtime_secrets (name PK, value, base_url, updated_at)`.
3. One pure function, `settings.resolve(row, secrets, env, config, args) -> Settings`, called
   by `run.py` at the start of every pass. `doctor` calls the same function.
4. `config.yaml` is a resolution layer, not a one-time seed.
5. An invalid combination fails that pass loudly; the daemon stays up.

## Forks

### 1. Where the settings live

| Option | For | Against |
|---|---|---|
| A. Typed row, like `candidate_profile` (recommended) | NULL is "not set, fall through"; types and the schema-drift guard; the worker reads it as it reads the profile | a new setting needs `make db-push` |
| B. Keys in `app_settings` | no schema change; MCP already withholds unknown keys | strings to parse and validate on both sides; mixes a web preference (`categories`) with worker input |

A. There are about 15 settings and they change rarely.

### 2. Secrets

Separate table, so no query that reads settings can return one by accident, and it stays out
of MCP's closed `ENTITY_KEYS`. Rules:

- The web selects only `name` and `updated_at` ("set", with a date). Set, replace and clear
  are the only writes. The audit row records the name and the action, never a value.
- **A key belongs to its base URL.** Changing `base_url` clears the stored key. Otherwise
  anyone who can reach the form could point it at their own server and receive the key on
  the next pass.
- The worker reads values into the per-pass `env` dict only, never `os.environ`.
- The keys are plaintext in the SQLite file. Any process that can read `db/` can read them,
  and so can every copy or backup of it. That is the same trust level as `.env` today, but
  a DB file is copied more casually: say so in SETUP.
- No MCP write tool for settings or secrets in this ticket.

### 3. Precedence of CLI flags

The issue calls env and CLI flags "the fallback layer". Taken literally, a hand-run
`--once --screen-backend none` is ignored when the DB names another backend, with a paid
call as the surprise.

Recommended: split the flags.

- Run shape stays CLI only: `--once`, `--run-now`, `--fetch-only`, `--db`, `--config`,
  `--env`, `--refresh-*`, `--import-companies`.
- Settings flags keep working as the fallback layer (DB > flag > env > config > default). When a DB
  value overrides a flag that was typed, print one line naming the setting.
- Add `--ignore-db-settings` for measured runs: EVALUATION needs a run whose model is the
  one on the command line.

A systemd unit that passes a flag (the example passes `--screen-limit 40`) then keeps its
value until the web sets one.

`--jev` is a `store_true`, which cannot say "off". Triage becomes one setting:
`off | openrouter-native | extract`; `--jev` means "on with the configured backend".

### 4. `config.yaml`: seed or layer

The issue says seed the DB once. A seed conflicts with the acceptance line "removing it
falls back to env": after a user clears a value the next pass must know it was already
seeded, which needs a marker, and the file and the DB then both hold the value.

Recommended instead: DB > flag > env > `config.yaml` > default. Same effective value on an
existing install, no seed write, no marker. The web shows the effective value and its
source from the last pass record.

### 5. Invalid combinations

Checked at two places with one function: the web refuses to save one; the worker checks
again at the start of the pass. A bad one ends the pass as `failed` with a new closed
category `settings_invalid` naming the setting; nothing is fetched or spent, and the
daemon waits for the next slot. It must not fall back to a default backend silently: a
default could be one the user switched away from.

### 6. Pass interval without a restart

Recommended: the trigger fires hourly and the job returns at once unless
`hour % schedule_hours == 0`. Same wall-clock slots as `cron_hours`, no rescheduling code.
The skipped hours write no pass record. The misfire grace becomes a constant 1800 s.

### 7. What each pass records

`worker_runs.config_json` already records the effective values. Add `sources`:
`{"screen.model": "db", ...}` with `db | flag | env | config | default`. No secret and no
base URL query string. This is what #253 reads to show what the last pass used.

## Settings in scope

| Setting | Fallback today | Default |
|---|---|---|
| screen backend, model, effort | `SCREEN_BACKEND`, `SCREEN_MODEL` / `OLLAMA_MODEL`, `SCREEN_EFFORT` | `ollama`, per provider |
| screen base URL | `SCREEN_API_BASE_URL`, `OLLAMA_HOST` | per provider |
| screen call cap, workers | `SCREEN_LIMIT` / `--screen-limit`, `SCREEN_WORKERS` | 40, 1 |
| triage backend | `--jev`, `JEV_BACKEND` | off |
| triage limit, spend cap | `--jev-limit`, `--jev-max-usd` | 300 (40 `extract`), 0.10 |
| Simplify feed on/off, categories | `config.yaml` | off |
| browser sources | `config.yaml` | off |
| pass interval | `config.yaml` | `config.DEFAULT_SCHEDULE_HOURS` |
| secrets | `SCREEN_API_KEY`, `OPENROUTER_API_KEY` | none |

A hosted triage model is fixed by the packs' measurement; "triage model" in the issue
applies to `extract`, which uses the screen's model. Recommend no separate triage model
column until a second one is measured.

`--screen-unlimited` has no DB value: an unlimited paid cap should need a shell.

## Proof

- Worker: DB beats env; clearing it falls back to env; neither gives the default (issue
  acceptance). Two consecutive passes in one process with a DB change between them.
- Leak test: store a sentinel secret, then call every MCP read tool, every web route
  and read action, and dump `audit_log` and `worker_runs`; the sentinel appears nowhere. Also
  assert it is not in `os.environ` during a pass.
- Changing the base URL clears the key.
- An invalid row: pass `failed / settings_invalid`, no HTTP call.

## Size

| Step | Hours |
|---|---|
| Schema, `resolve`, wiring in `run.py` and `doctor` | 4 |
| Scheduler tick, invalid-settings pass, pass-record sources | 2 |
| Web actions (no form: #253 and #254), audit, leak test | 3 |
| Docs | 1 |

About 10 h, so the issue's 1 day holds only if the forms stay in #253 and #254. No data
migration: an empty table changes nothing for an existing install.

## Questions for the operator

1. Typed row (A) or `app_settings` keys (B)?
2. `config.yaml` as a layer instead of a seed (differs from the issue)?
3. DB over a typed CLI flag, with a printed line and `--ignore-db-settings`?
4. Changing the base URL clears the key: agreed?
5. `settings_invalid` fails the pass instead of falling back: agreed?
