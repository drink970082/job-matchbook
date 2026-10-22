# Codex screen + complete read-only ATS MCP — implementation brief

**Status:** implemented, deployed, and verified through the connected ATS plugin.
**Implementer:** GPT Luna, reasoning effort max, using goal mode.
**Reviewer:** GPT Sol / Astra, independent of the implementer.
**Deliverable:** a new feature branch and a PR against `main`; do not merge.

## 1. User intent and exact finish line

The operator wants the worker to fetch and screen hard requirements using Codex Luna,
while ChatGPT performs fit judgment interactively. Stage 2 fit scoring and Telegram
notification must not run in this operating mode. ChatGPT must be able to read the
complete ATS dataset through a self-hosted MCP server. No MCP writes in v1.

The operator ALREADY self-hosts Sure MCP through OpenAI Secure MCP Tunnel and has
confirmed that it works. Reuse that proven transport pattern; do not spend this task
investigating Cloudflare/ngrok or whether ChatGPT can use tunnels. Do not replace or
interrupt the existing Sure server/tunnel. ATS needs its own correctly routed MCP
target. Actual host configuration and account access still require discovery.

Finish means implementation, meaningful automated tests, current docs, runtime smoke
evidence where accessible, pushed branch, and an open PR ready for Sol/Astra review.
Account/host restrictions must be reported precisely; an unavailable ChatGPT smoke
test must remain an explicit acceptance gap, never a claimed success.

## 2. Scope and non-goals

In scope:

- Fetch + screen, with screen backend `codex`, model `gpt-5.6-luna`, effort `medium`.
  Keep the exact Luna model already compared in this repo's screen corpus; validate
  availability with the installed CLI/account. GPT-6 Luna is also current in the OpenAI
  catalog, but changing the model requires a representative quality evaluation, so do
  not silently substitute it. `medium` is the pinned production setting, but the
  committed accuracy evaluation does not record effort, so the exact setting is
  unmeasured.
- Independent persistence of screen results, provenance, and retry/error state.
- Complete, paginated, read-only access to every application-owned Prisma model and
  its fields, including records hidden by the current UI's score buckets.
- Local MCP service, Secure MCP Tunnel instructions/config example, and lifecycle
  documentation. Prefer stdio behind the official tunnel client: no public listener
  or new OAuth provider is needed solely for this private single-user deployment.

Out of scope:

- Creating/importing jobs, applications, watchlist entries, categories, or notes
  through MCP; updating statuses; storing ChatGPT judgments through MCP.
- MCP-triggered fetching, browser automation, arbitrary HTTP requests, arbitrary SQL,
  filesystem access, remote shell, auto-apply, or external messaging.
- Rebuilding fit scoring, changing fit prompts/models, historical bulk re-screening,
  backfilling old JDs, redesigning the web UI, or fixing unrelated backlog items.
- Exposing `.env`, credentials, Codex auth, resume files, config files, or gitignored
  eval artifacts. “Complete ATS data” means application database records, not all
  files or secrets on the machine. Existing JD text and application notes ARE in scope.

## 3. Mandatory boot and branch isolation

1. Read `AGENTS.md`, session-boot skill, `docs/PROGRESS.md` In flight, then
   `docs/DEVELOPMENT.md` §§2–7, `docs/PRINCIPLES.md`, relevant SPEC sections
   (§§6, 7.1, 7.2, 8, 9, 11, 12, 13), `docs/SCORING.md` including measured history
   and hostile directions, and `docs/REJECTED.md` screen-shape entry.
2. The root checkout is `feat/import-csv-dialog` and contains user changes in
   `docs/BACKLOG.md`, `docs/PROGRESS.md`, `docs/SCORING.md`, plus an untracked plan.
   Re-check status, claims, remote state, and any running worker before proceeding.
3. Never stash, overwrite, commit, or reset those unrelated root-checkout changes. Do
   not switch a live worker's checkout. Implement in the existing isolated worktree
   `/tmp/ats-codex-screen-readonly-mcp`, branch `feat/codex-screen-readonly-mcp`, based
   on `origin/main`. No stacked PR.
4. The In-flight claim is on the implementation branch. The companion design spec is
   approved with these choices: separate `job_screenings` storage, minimal-state retry
   and cache policy A, official MCP Python SDK v2, and redaction of recipe credential
   values. Do not reopen these forks; routine details within the approved scope do not
   require repeated permission requests.

## 4. Goal-mode execution contract

At implementation start, create a goal explicitly covering the finish line in §1.
Do not set a token budget unless the operator supplies one. Work in the milestone
order below, using focused tests and commits. Keep a concise current checkpoint in
the plan/claim so a continuation can resume without chat history. Never log personal
data or credentials in the checkpoint. Do not mark the goal complete before the
PR and required verification deliverables exist. Follow goal tooling's actual
blocked/paused rules; do not mark blocked on the first unavailable external action.

The implementer runs at max effort. Runtime screen calls use medium effort. These
are separate settings. Do not dispatch review agents or merge in lieu of the user's
planned independent Sol/Astra acceptance.

## 5. Existing code and traps established by investigation

- `apps/worker/ats_worker/run.py`: `--fetch-only` returns before screen/fit/notify;
  `--score-only` skips ingest but still does screen AND fit. Neither flag implements
  the requested mode. `--score-limit 0` means UNBOUNDED, not disabled.
- `run.py:make_screener`, `score/backends_screen.py:make_codex_extract` already support
  Codex screen. Its current model default is `gpt-5.6-sol`; screen CLI does not pin
  effort, unlike fit's `codex_json`. Explicitly pin screen effort and test the argv.
- Screen extracts JOB facts; `score/screen.py` decides hard-constraint failures in
  deterministic code. Reuse it. Preserve unknown/absent checks and quote grounding.
  Do not introduce the rejected replacement verdict vocabulary inside screen JSON.
- Codex screen already disables shell and web, uses read-only sandbox, temp working
  directory, schema-constrained output, and ephemeral sessions. Preserve all of it.
- `pipeline.run_score` currently composes screen and fit. `score.screen_posting`
  already adds `provider_error=True` on hosted extraction failure and keeps the
  opportunity; preserve this distinction and never store an outage as a successful
  completed screen.
- Fetch includes title/age filters and deterministic location/intern disqualification.
  Preserve configured fetch rules in v1, document them, and expose discarded rows
  through MCP. Fetch's existing deterministic gates may mark a just-fetched row
  `discarded`; this is fetch behavior. The standalone screen stage processes only rows
  that remain eligible as `new` and must not change their pipeline lifecycle. Some
  fetch-discarded rows have only stubs; do not fabricate full JDs.
- `db.connect` sets WAL and is designed for writers. DO NOT use it for MCP reads.
- Prisma owns all DDL: `apps/web/prisma/schema.prisma`. Update the worker SQL fixture
  and schema drift guard coverage if the selected result-storage design adds a model.
- `job_postings` dedup key is `(source, external_id)`; `application_id` links to
  `applications`; `status_history` holds application transitions.
- `apps/web/src/lib/actions.ts` defaults to score-derived buckets that hide `new`
  rows. MCP must query its own well-defined read repository, not reuse this filter.
- The worker currently loads resumes before dispatch; fetch/screen-only must run
  without resume files and without fit-backend credentials or Ollama.
- Systemd access failed in the preparation sandbox: `Failed to connect to bus:
  Operation not permitted`. This is NOT evidence that the host service is stopped.

## 6. Milestone A — independent screen lifecycle

Implement an explicit `--screen-only` mode: normal ingest/expiry followed by hard
requirements screening, then return before ANY fit/notify work, including queued
notification delivery and fit quota-refresh side effects. It also skips `run_retry` and
`--rescreen-discarded`: those belong to the legacy fit lifecycle and can requeue or
mutate historical rows. Keep legacy default, `--fetch-only`, and `--score-only`
behavior unchanged. Reject combinations of those three modes, or `--screen-only` with
`--rescreen-discarded`, before network/DB mutations. Do not require resume loading in
either fetch-only or screen-only mode. Continue using the existing per-DB pass lock.

Expose `--screen-effort` / `SCREEN_EFFORT`, validate supported values, and explicitly
forward the selected value to Codex's `model_reasoning_effort`. Preserve existing
backends' behavior. Keep the repo-wide backend default Ollama; provide an operator
deployment example that explicitly selects codex/Luna/medium. No global model change.

Bound hosted screen spend with `--screen-limit` (default 40 in the new mode) and
default concurrency 1 in that mode. A positive cap bounds attempted provider calls,
including failures, not only passes. Never silently interpret zero as unlimited;
reject nonpositive values in this mode. Other modes' existing caps remain unchanged.
Reuse known deterministic outcomes without calling a provider. Log attempted calls,
cache hits, pass/disqualify/unknown outcomes and errors, without raw JD or secrets.
Fresh, never-screened `new` postings use the existing newest-first queue order. Once
those are selected, unused provider-call capacity retries screen errors oldest-attempt
first. The same `--screen-limit` caps provider calls, including failures. Under minimal-
state option A, `--rescreen-screened` clears successful screen cache for eligible `new`
rows and requires `--screen-only --once`; recurring passes must never clear their own
cache. Full-state option B uses fingerprint changes for automatic invalidation instead.

**Screen storage and retry policy are approved:** persist one latest result per posting
in a separate Prisma `job_screenings` row, cache successful outcomes until an explicit
one-shot re-screen, and retry errors on later passes under the per-pass cap and existing
screen circuit breaker.
`docs/REJECTED.md` rejects per-stage screen retry budgets and end-to-end hashes with an
automatic re-run planner. This task changes an important premise: screen is now a
standalone recurring stage, while postings remain `new`, so its result cannot live only
inside fit `score_detail` or be inferred from `pipeline_status`. The companion spec
records the approved policy and the alternative considered:

1. A smaller `job_screenings` table with one latest result per posting, screen payload,
attempt time, state, backend/model/effort and evaluator version. Completed outcomes are
cached until an explicit one-shot operator re-screen command clears results for eligible
`new` rows. Errors remain retryable on a later pass, ordered fairly by oldest attempt,
under the per-pass cap and existing screen circuit breaker. There is no per-row retry
budget, input hash planner, or automatic invalidation when config/prompt/model changes;
the operator requests re-screening after such a change. This preserves the earlier
simplicity decision while providing durable screen output.
2. The full subsystem originally proposed here: a Prisma `job_screenings` table with
fingerprint over posting facts, candidate requirements, prompt/schema/rule versions,
backend/model/effort; automatic invalidation; bounded retries/backoff; and per-input
error state. This avoids stale cached results and repeated errors, but reopens both
previously rejected directions and adds a Prisma model and retry lifecycle.

Preserve the existing screen payload contract; do not introduce a
replacement set of per-check verdict enums. The screen stage must not change
`pipeline_status`, fit `score`, `attempts`, `notify_attempts`, application links, or
`score_detail` (which stays fit/legacy evidence). No fake score, no `scored` status,
and no successful cache entry for a provider error. Fetch's existing filters retain
their status effects; the screen stage only processes rows left eligible as `new`. Do
not automatically requeue or process terminal/already fit-scored historical rows.
Expose old fetch/legacy screen evidence as its original evidence, not as a new Luna run.

Use a transaction per result and re-check row eligibility before storing it if another
writer has changed its lifecycle. A crash after a provider call but before commit may
cause a repeat call next pass: document this at-least-once boundary rather than claiming
exactly-once external execution. Terminal historical re-evaluation is outside v1.

## 7. Milestone B — complete read-only query layer

Implement a small Python read repository separate from mutable worker DB helpers.
Use SQLite URI `mode=ro`, `PRAGMA query_only=ON`, bounded busy timeout, existing WAL
sidecars and live connections. Never `immutable=1` against the running WAL database,
never create a missing database, set journal mode, seed settings, migrate, or run DDL.
Missing DB/schema should produce an actionable error without filesystem disclosure.

Coverage inventory (re-read current Prisma schema; do not omit models added since
this brief): `job_postings`, `applications`, `status_history`, `watched_companies`,
`feed_unresolved`, `promotion_dismissed`, `app_settings`, and the approved
`job_screenings` result model.
Expose all stored business-data fields through typed details or allowlisted entity
record tools. `custom` fetch recipes can contain arbitrary request headers, including
credentials. Return all ordinary recipe fields and header names, but redact every
header value and conventional secret URL query values. This is the approved exception
to complete business-data reads. Sensitive future settings keys require an explicit
policy, never unreviewed exposure.

Tools should include:

- `get_ats_overview`: counts by pipeline/application/screen state and table totals;
  report unknown legacy statuses too. Counts must reconcile with actual DB rows.
- `list_jobs`, `get_job`, `get_job_description`: search title/company/location,
  source, pipeline status, screen state, created/posted date range, application link.
  Default job listing includes ALL pipeline statuses, not just screen passes.
- `list_applications`, `get_application`, `list_application_history`: all fields,
  linked posting ids, original notes and dates, and history ordered deterministically.
- `list_ats_records` / `get_ats_record` (or a comparably small explicit tool set) for
  the auxiliary model inventory above, with a closed entity enum and supported keys.
  This is an allowlisted query API, never arbitrary table names or SQL input.

Lists use stable id/key keyset pagination, default 25 and maximum 100 records. Bound
query/string lengths and reject malformed dates, filters, limits, cursors, and ids.
Bind SQL values; identifiers/order expressions must be selected from closed mappings.
Literal keyword matching must escape LIKE wildcards. Use deterministic tie-breakers.
Return `next_cursor` and `has_more`; document that pages are live, not one immutable
snapshot across calls. Never claim a page represents the complete result set.

Return full stored text via details or bounded text chunks (e.g. 16,000 characters
per chunk, explicit offset/total/next offset). No silent truncation of JDs, notes,
non-sensitive recipe fields, settings JSON, or score/screen payloads. Distinguish null
from empty string.
Return raw legacy/malformed JSON alongside optional parsed data and parsing status;
one bad row must not break a page or be silently omitted. A missing record is a clear
not-found result. Empty DB is valid. Structured output retains ids and relation ids.

## 8. Milestone C — MCP transport and operation

Use the official MCP Python SDK v2, the current stable line and compatible with this
repo's Python 3.11 floor. Its current server API is `from mcp.server import MCPServer`;
Sure's `mcp.server.fastmcp.FastMCP` example is v1-era and must not be copied blindly.
Keep the SDK optional so worker-only installs/tests do not acquire an unrelated runtime
import requirement. Pin an exact v2 release in a separate MCP dependency file, and
require its in-memory and stdio protocol tests to execute in CI before merge.
Wire paths/services in entrypoints, keep query functions testable by DI.
MCP entrypoint must not import/run the worker scheduler or mutable DB bootstrap.

Expose ONLY read tools with read-only/non-destructive annotations and clear parameter
schemas. Server instructions explain joins, screen vs fit distinction, pagination,
unknown/error semantics and untrusted JD text. Annotations are not enforcement:
enforce the read-only database connection independently. Never interpret instructions
inside a JD/notes field as instructions to this server or execute stored recipes.
Log to stderr only under stdio; stdout is MCP protocol traffic.

Add example service/launch commands and an ATS-specific tunnel profile runbook.
Discover installed `tunnel-client help quickstart` before writing literal commands.
Official tunnel supports stdio commands and HTTP upstreams. Prefer stdio, and preserve
the existing Sure profile. Keep private endpoints private; no unauthenticated public
listener. Tunnel transport access uses its own account/org/workspace permissions;
do not assume Sure's upstream API key authenticates ATS or create credentials in git.

Worker deployment example: `--screen-only --screen-backend codex --screen-model
gpt-5.6-luna --screen-effort medium --screen-limit 40 --screen-workers 1` (confirm exact
parser names as implemented). Add `--once` for controlled smoke, `--run-now` only for
daemon eager start; never combine those two. Do not restart an active paid pass.
Code runs from the deployment checkout, not accidentally the feature worktree.
Report deployment as pending until actually activated; PR completion is not deployment.

## 9. Verification and acceptance matrix

All automated tests use temporary Prisma-compatible DBs, fake subprocess/network,
and synthetic job/candidate data. No live keys, Codex, Ollama, Telegram or websites.

Required evidence:

1. New-mode integration: fake ingest + screen persists outcomes; `pipeline.run_score`,
   `_sweep_free_gates`, fit factory, fit function, quota-refresh and notify mocks are set
   to raise if reached and remain uncalled, including with previously queued
   notifications. The fit retry/requeue stage is also uncalled. No resume needed.
2. CLI tests: mode exclusivity, selected reset/invalidation behavior, limits, environment
   precedence, medium effort in Codex argv, unsupported effort fails before side effects;
   preserve tool-less flags. Under option A, `--rescreen-screened` must require
   `--screen-only --once`; option B automatically invalidates on fingerprint changes.
3. Screen state tests: pass, grounded disqualification, no configured requirements,
   missing/unknown checks, invalid JSON, timeout, missing executable/auth/provider
   failure, changed eligibility, empty and short JD, crash/restart behavior, and
   persistence in `job_screenings`. For minimal-state option A, prove success caching until the
   explicit one-shot re-screen, oldest-attempt-first error retries under the call cap,
   and no automatic invalidation, fingerprint planner, per-row retry budget or backoff.
   For full-state option B, prove every fingerprint input change invalidates and bounded
   retry/backoff parks after three failures. Do not require tests for the unselected
   policy. Prove `score_detail` remains byte-for-byte unchanged and preserve the other
   fit/application fields.
4. Repository tests: every Prisma model/field in the selected schema has an access
   route; all pipeline states reachable, orphaned optional links, Unicode, long text,
   nulls, malformed JSON, unknown legacy status, stable complete pagination over static
   fixtures, malicious filter/cursor/SQL-like input, missing DB/schema and concurrent
   WAL visibility.
5. Read-only tests: SQL write attempts fail at connection level; MCP calls cause no
   application row changes. Do not compare raw DB file hashes during concurrent
   worker writes or claim those prove MCP purity. Verify no startup schema/seed work.
6. MCP protocol smoke using SDK client over stdio: initialize, list tools, invoke
   representative tools and pagination; no write tool appears, no stdout log corruption.
7. Run repo-required gates: `make test-worker`, `make test-coverage`,
   `make test-integration`, `make check-schema`, `make check-privacy`; run web tests
   and lint if web code is touched. Update schema fixtures and invariant traceability.
   Add new MCP tests to the existing gated test path so they cannot be skipped in CI.
8. Live screen quality evidence: consume the current expanded-corpus measurement in
   `docs/PROGRESS.md`; do not repeat an unchanged eval. On the same 103-row corpus and
   day, Ollama/qwen3.5:4b had 7 false disqualifications (4 degree + 3 clearance),
   recall 31/37 and flip 0; Codex/gpt-5.6-luna had 0 false disqualifications, recall
   30/37 and flip 3. Luna's earlier 83-row record remains PASS/FAIL/PASS, with one
   false-disqualification draw on id 672. The expanded same-day comparison is the
   current quality evidence; the earlier single PASS is not an independent replication.

   The recorded evaluation does not identify reasoning effort, so it does not establish
   medium-effort quality. Keep medium explicitly unmeasured. Run one bounded screen
   corpus pass only if the screen prompt/schema/deterministic rules or corpus have
   changed since that measurement, or provenance establishes that the evaluated model
   or effort differs from the production target. If effort provenance remains unknown,
   report that limitation without treating unknown as a mismatch or rerunning solely to
   label the historical result medium. Any required pass uses no production writes.
   Preserve the zero-false-disqualification bar and safety grounding. Do not tune fit
   prompts, buy a full fit eval, or assert Luna quality from API docs.
9. Live deployment gate: once quality passes, one controlled fetch+screen smoke with
   at most 5 provider calls, then inspect DB effects and zero fit/notify calls. Read
   representative real data without copying JD/notes/PII into PR logs. Final steady
   state cap is 40; no unlimited backlog run. The user's requested Codex operation
   authorizes this bounded screen work, not unrelated bulk evaluation/spending.
10. ChatGPT gate: using ATS tunnel, read overview, a `new` job, a discarded job, full
    multi-chunk JD, application/history and auxiliary records. Observe one completed
    tool invocation from ChatGPT. If browser/account access is unavailable, provide
    exact manual steps and mark this gate NOT VERIFIED for Sol/Astra/operator.

Do not silently change effort/model to pass a failed quality gate. A model rejection
or repeatable false-disqualification regression is a review finding: finish the
reviewable code/tests, leave production activation pending, and report the evidence.

## 10. Documentation, PR, and reviewer handoff

Update SPEC current behavior/data model/setup/invariants + real invariant→test rows,
SCORING screen-only lifecycle and medium-effort rationale (no invented measurement),
PROGRESS live claim/residuals, CHANGELOG, dependency/run instructions, privacy/access
boundaries and examples in the same behavior commits. Every doc except CHANGELOG is
current state. Do not mark the PR as shipped or delete the active claim before merge;
the merger removes it when the work lands. No unrelated backlog edits.

Push feature branch and open a PR explicitly with `--base main`. Use a body file for
multiline `gh` content. Include problem/result, design spec + plan, schema impact,
screen model/effort/cap, test output tails, live quality findings, deployment status,
ChatGPT verification status and exact remaining acceptance steps. No real private
record dumps. Verify PR base, CI status and diff scope. If network/auth prevents push
or PR creation, report the exact failure, preserve commits and supply ready PR text;
do not claim an open PR exists.

Sol/Astra should independently review the diff and tests against this finish line,
especially: hidden rows, full text retrieval, accidental writes or model/tool execution
through MCP, false success caching, unbounded quota, fit/notify leakage, legacy-mode
regressions and unintended changes to another session. Implementer must not merge.

## 11. Sources and evaluation limits

- Official custom MCP connection/protocol/access documentation:
  https://developers.openai.com/api/docs/guides/custom-mcp-server
- Official private tunnel/stdin-HTTP upstream and permissions documentation:
  https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- Official MCP Python SDK v2 install and server-run documentation (current stable line,
  Python 3.11+, and MCPServer API):
  https://py.sdk.modelcontextprotocol.io/get-started/installation/
  https://py.sdk.modelcontextprotocol.io/run/
- Sure reference implementation (tool wrapping, not an ATS implementation):
  https://github.com/we-promise/sure-mcp-server
- Luna model/effort reference:
  https://developers.openai.com/api/docs/models/gpt-5.6-luna

Official docs establish supported settings, not this account's model availability or
screen accuracy. Preparation was code/document inspection only: no model eval,
production worker pass, MCP installation, DB mutation, service restart or ChatGPT
connection was performed. This brief itself does not implement the feature.
