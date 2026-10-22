# Codex screen and read-only ATS MCP — design

**Status:** draft — operator signoff required before behavior, dependency, or schema changes.
**Related plan:** [`../plans/2026-10-22-screen-and-readonly-mcp.md`](../plans/2026-10-22-screen-and-readonly-mcp.md)

## Purpose

Run the existing fetch pipeline with a separately persisted hard-requirements screen
using Codex `gpt-5.6-luna` at explicitly pinned `medium` effort. Skip fit scoring and
Telegram notification in that mode so ChatGPT can make fit judgments through a
self-hosted, read-only MCP server. The operator has already verified OpenAI Secure MCP
Tunnel using Sure; provide an ATS server target/profile without changing the Sure
service.

The MCP reads application-owned database records only. It must never accept arbitrary
SQL, mutate records, launch the worker, execute a recipe, access the filesystem, or
reach an arbitrary URL. User-facing actions to create/import records are outside v1.

## Existing facts that constrain the design

- `--fetch-only` already stops before screen, fit, and notify. `--score-only` still
  screens and fit-scores. Neither is the requested fetch+screen mode.
- `run.py` currently loads resumes regardless of mode; a screen-only run should not
  need a resume, Ollama, fit credentials, or a fit-backend call.
- Screen and fit are composed in `pipeline.run_score`; the current screen result is
  ultimately folded into `score_detail`. `score.screen_posting` returns
  `provider_error=True` on provider failure and otherwise reuses the deterministic
  code checks. Keep this metadata distinction; a failed provider call is not a pass.
- `job_postings.pipeline_status` is the application lifecycle. Fit code and UI infer
  meaning from it; screen-only work must leave it unchanged. Do not synthesize a score
  or write a fit-shaped verdict.
- Prisma owns DDL. The worker fixture and schema-drift guard must stay aligned with any
  Prisma model change. SQLite readers should use a separate `mode=ro` repository and
  `query_only`; `db.connect` is configured for the writer and changes journal mode.
- Current Luna evaluation on the expanded 103-row screen corpus reports zero false
  disqualifications, 30/37 recall and three flips, compared with seven false
  disqualifications for Ollama. Earlier 83-row Luna measurements were PASS/FAIL/PASS,
  so the isolated PASS was not reliable evidence. The expanded comparison is the
  current quality result. It does not record reasoning effort; medium is therefore
  the selected runtime setting, not a measured quality setting.
- Previous repo decisions reject per-stage screen retry budgets and end-to-end input
  hashes with an automatic re-run planner (`docs/REJECTED.md`). This feature changes
  the premise by moving screen into an independent recurring stage. The alternatives
  below make that exception visible for operator review.
- The official MCP Python SDK v2 is now its stable line and uses `MCPServer`; Sure's
  example is written against the v1 `FastMCP` API. Python 3.11 meets the v2 minimum.
- A `custom` board's JSON recipe can contain arbitrary request headers, including
  credentials. “Read all ATS data” therefore needs an explicit secret-display rule.

## Principles

- **Principle 1 — keep a human decision seam.** This MCP is read-only; ChatGPT can
  inspect and recommend, while applying or changing ATS state remains a human action.
- **Principle 2 — deterministic code over model judgment.** Keep the existing screen
  contract: the LLM extracts job facts, and deterministic code applies candidate
  constraints. MCP list filters are deterministic and bounded.
- **Principle 3 — err toward keep.** Provider errors remain visible as unscreened and
  never become a clean pass or disqualification. Ambiguous MCP data is returned with
  its raw value/status rather than silently omitted.
- **Principle 4 — spend judgment calls only where judgment is needed.** Screen calls
  are capped per pass; fit calls and notify are unreachable in screen-only mode.
- **Principle 9 — Prisma owns the schema.** Any result table is declared in Prisma;
  worker code performs no DDL.
- **Principles 10–13 — injected dependencies, WAL discipline, privacy, single-user
  simplicity.** MCP reads through a read-only connection, never overlaps worker DB
  writes in a transaction, avoids multi-tenant/auth infrastructure, and never returns
  configured credentials.

## Fork 1 — where standalone screen results live

| Option | Shape | Trade-off |
|---|---|---|
| A | Write the new result into `job_postings.score_detail` while status stays `new` | No new table, but overloads a fit result column and can be overwritten when a fit pass runs. MCP cannot reliably distinguish the new screen from legacy fit evidence. |
| B | Add a one-to-one Prisma `job_screenings` record per posting | Clear boundary for new screen evidence, retry status and MCP reads. Adds DDL and a worker fixture, and needs an operator-selected invalidation/retry policy (Fork 2). |

**Recommendation: B.** It preserves the meaning of current fit columns and supports
screening independently. The exact fields depend on Fork 2. Keep the current nested
screen JSON shape; do not replace the check vocabulary rejected in `REJECTED.md`.
This changes the Prisma schema, so the operator must choose A or B before implementation.

## Fork 2 — retry, caching, and input changes

The old “screen failure is a score failure” rationale no longer describes the requested
mode. Screen must now complete while fit is skipped, and postings remain `new`; absent
a separate result record every scheduled pass would rescreen and spend on the same row.
However, automatic input invalidation and independent retry budgets were rejected
before. Compare:

| Option | State and repeat behavior | Trade-off |
|---|---|---|
| A — minimal state (recommended) | Store one latest result per posting with status, raw structured screen result on success, sanitized error and `last_attempted_at`, backend/model/effort, and evaluator version. Cache success until the operator runs an explicit one-shot `--rescreen-screened` action for eligible `new` rows. Retry errors on later passes, order them by oldest attempt to avoid starvation, and reuse the existing screen circuit breaker plus a positive per-pass `--screen-limit` (default 40). No per-row retry budget, input fingerprint planner, or automatic invalidation when candidate config, model, prompt or rules change. | Durable no-fit screen results and bounded per-pass work with little new state. A screen can become stale after input changes until the operator explicitly requests a re-screen. A persistent per-row error may be retried over later runs but each run has a hard call cap and the existing breaker. |
| B — full state from the implementation brief | Store a hash of posting, candidate constraints, deterministic rules, prompt/schema, backend/model/effort. Automatically skip identical completed inputs and invalidate on any change. Store retry counts/time per fingerprint, back off, and park after three failures. | Automatically fresh evidence and bounded repeats. Adds a rerun planner and a separate retry lifecycle, both previously rejected; increases DDL, tests and maintenance. |

**Recommendation: A.** The new table is justified because screen becomes independent;
the hash-driven rerun planner is not required to achieve that. An explicit reset makes
staleness a deliberate operator action and follows the prior simplicity decision. This
recommendation intentionally replaces the original plan's automatic fingerprints and
per-input retry budget. The operator must choose A or B before behavior implementation.

For either option:

- A provider error is never stored as a successful screen. Persist only a sanitized
  error category/message and timestamp; do not persist raw prompt, JD, stdout or stderr.
- A posting re-checks `pipeline_status='new'` immediately before result persistence.
- Keep existing score, score detail, attempts, notification attempts, status and
  application link untouched by the screen-only stage.
- Do not reprocess terminal or already fit-scored historical rows in v1.
- Fetch-time title, age, location and internship rules remain as configured. The MCP
  can read discarded postings, including bodyless stubs; it must report stored content
  faithfully and never invent a full JD.
- Screen deterministic-only outcomes are recorded without spending a Codex call.
- The command rejects conflicting `--fetch-only`, `--score-only`, and
  `--screen-only` modes before opening/mutating the database or fetching.
- Keep `SCREEN_BACKEND`'s global default as Ollama. The host deployment opts into
  Codex Luna medium explicitly. Codex subprocess remains tool-less, read-only and
  ephemeral, with web disabled.

## Fork 3 — MCP SDK line

| Option | Trade-off |
|---|---|
| A — official SDK v2 (`mcp.server.MCPServer`) | Current stable SDK and current docs; requires an optional `mcp>=2,<3` runtime dependency and tests under Python 3.11. Differs from Sure's older examples. |
| B — pin official SDK v1 (`mcp<2`) | Matches Sure's demonstrated `FastMCP` import, but pins the maintenance line and its v1 API after v2's breaking rework. |

**Recommendation: A.** Pin the supported major range, keep the dependency out of
worker-only runtime installs, and test tools in-process plus stdio protocol. Use stdio
through an ATS-specific Secure MCP Tunnel profile; do not change Sure's target/profile.
If the tunnel client or account is unavailable during implementation, document the
exact manual setup and leave ChatGPT end-to-end verification open.

## Fork 4 — recipe credential visibility in complete reads

The database includes a watchlist recipe, and arbitrary headers there may be secrets.
The MCP should return all ordinary recipe fields but redact values of every header
(`headers` map), preserving the header names. It should also redact conventional secret
query keys if exposed through URLs (`token`, `key`, `secret`, `auth`, `signature`,
`password`, case-insensitive). Application notes and job text remain fully readable,
as requested. `app_settings` currently stores categories only; future entries must be
filtered by an explicit allowlist before they can be exposed.

**Recommendation: redact recipe credentials and state this as the one exception to
complete database reads.** Returning the raw recipe would expose request credentials to
the model through an MCP result. The operator should confirm whether that boundary is
acceptable. No credentials should appear in fixtures, logs, docs or MCP error text.

## Read-only query and MCP contract

Use a dedicated repository and live SQLite read-only URI (`mode=ro`) with
`PRAGMA query_only=ON`; never `immutable=1`, `CREATE`, `PRAGMA journal_mode`, settings
seeding, migrations or writes. Use bound values and closed mappings for entity names
and sort keys. Lists are keyset paginated (default 25, max 100) with stable tie breaks,
`next_cursor` and `has_more`. Pages are live and not a cross-call snapshot. Long fields
return explicit chunks with offsets/total; no silent truncation. Preserve null/empty
distinction, malformed legacy JSON with parse status, unknown statuses, and orphaned
optional links.

Expose the current application-owned Prisma models: jobs, applications, status history,
watchlist, unresolved feed entries, dismissed promotion suggestions, application
settings, and the selected screening result model. Include full job descriptions,
application notes, status history, links, raw screen/score payloads and all record
fields subject to the credential rule above. Tools cover overview/counts, filtered job
listing/details, application listing/details/history, and allowlisted auxiliary entity
listing/details. Never accept arbitrary SQL/table names.

Server instructions identify job text and notes as untrusted data, describe fit vs
screen evidence, pagination, legacy/unknown states, and how to retrieve full JD chunks.
Tool descriptions explain their use and parameter bounds. Only read tools are
registered, but connection-level read-only mode is the enforcement boundary.

## Acceptance evidence

- Synthetic DB tests prove each model and field has a read path, including `new` and
  discarded jobs, all pages, full text chunks, history order, malformed JSON, unknown
  status, nulls, and orphan links.
- MCP client tests prove initialize/list/call over in-memory client and stdio; no write
  tool exists; SQL writes fail at connection level; a call does not alter an application
  row. WAL reads see committed writer changes.
- Screen-mode tests prove it fetches then screens, records an output independently,
  exits before fit/notify, skips resume loading, enforces per-pass call limit, preserves
  legacy modes and never treats provider errors as success.
- Existing measured Luna quality is the baseline; no redundant eval. State clearly that
  medium effort has no separately recorded quality measurement. A new eval is only
  needed if model, prompt/schema/rules, corpus or provenance materially changes.
- Schema, worker tests/coverage/integration, privacy and MCP protocol gates pass. A
  bounded live smoke spends at most five screen calls. Do not activate a daemon from a
  feature worktree. Report whether the production host and ChatGPT tunnel were actually
  verified; never infer either from tests.

## Operator decisions requested

1. Screen result storage: choose A (`job_postings.score_detail`, with its fit-column
   collision risk) or B (a separate one-to-one Prisma `job_screenings` row). Recommendation B.
2. Screen persistence/retry: choose A (minimal result + explicit re-screen) or B
   (automatic fingerprint invalidation + per-input retry state). Recommendation A.
3. MCP package: approve official SDK v2, or request v1 for compatibility with Sure's
   current example. Recommendation v2.
4. Recipe credential visibility: approve redacting recipe header/secret query values
   while returning all other ATS business data, or specify another boundary.

After those decisions are recorded, change this header to `approved`, then implement the
approved path. Other details—tool names, cursor encoding, exact schema field names—are
implementation choices inside the approved contract.
