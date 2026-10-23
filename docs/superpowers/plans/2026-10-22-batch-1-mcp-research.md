# Batch 1 — research-ready read-only MCP

**Status:** implementation complete for issue #91; ready for Astra/Sol acceptance. Deployment
remains separate. Owner: Luna at max effort. Orchestrator and acceptance: Astra/Sol.
[Issue #91](https://github.com/drink970082/job-matchbook/issues/91).

## Goal and inputs

Enable ChatGPT to find useful candidates, inspect advisory screen outcomes, retrieve
older jobs with newly saved assessments and search JD text without scoring the database.
Read [approved contract](../specs/2026-10-22-research-inventory-design.md), ROADMAP,
PROGRESS In flight, DEVELOPMENT and relevant SPEC MCP/standalone-screen sections.
Use current main, not an old runtime checkout or somebody else's dirty worktree.

Dependencies: none in code; [baseline #90](https://github.com/drink970082/job-matchbook/issues/90)
can run alongside. One issue, one branch `feat/mcp-research-queries`, one PR targeting main.
The branch claim remains in PROGRESS while the PR is under review. Do not implement batch 2
in this PR.

## Starting points to inspect

These paths describe the current code, not permission to skip reading it:

- `apps/worker/ats_worker/mcp/read_repository.py`: bounded inputs, filter-scoped cursor,
  list_jobs/get_ats_overview, redaction and short-lived read-only connections.
- `apps/worker/ats_worker/mcp/server.py`: tool annotations, validation, tool docs and safe errors.
- `apps/worker/ats_worker/db.py`: get_screen_candidates and save_screening transaction.
- `apps/worker/ats_worker/pipeline.py`: run_screen persists results with pass-start now.
- `apps/worker/ats_worker/run.py`: external clock wiring and standalone mode isolation.
- `apps/worker/tests/test_mcp_repository.py`, `test_mcp_protocol.py`,
  `test_screen_pipeline.py`; existing run/DB tests and schema guard.
- Prisma schema is authoritative; no schema change is planned. Existing source/evidence
  refresh and legacy score_detail remain outside this issue.

## Execution steps

1. **Encode the public contract in synthetic cases.** Build a small JSON fixture usable
   by Python now and TypeScript in batch 2. Include no row, successful checked result,
   explicit disqualification, missing checks, unknown checks, malformed JSON, contradictory
   result and provider error. Add legacy evidence separately. No real JD/profile data.
2. **Implement safe summaries and filtering.** Follow the design's outcome table. Bound
   and sanitize reason strings; retain model/effort/assessment provenance. Ensure SQL count,
   filter and projected summary agree, including malformed JSON (no SQL JSON exception).
   Avoid loading all rows into Python then paginating; filtering must apply before LIMIT.
3. **Add opt-in full-text search.** Keep metadata default. Escape literal LIKE metacharacters,
   add description to all_text, preserve body chunking and null/empty distinctions. Exercise
   a generated large fixture, record query behavior and payload bound; do not add FTS/schema
   or a provider to fix performance without returning the design question.
4. **Add assessment windows and scoped cursor changes.** Implement inclusive/exclusive UTC
   instant handling, explicit invalid values, ID ceiling and stable id order. Do not sort by
   mutable assessment time under an id cursor. Include all new filters in cursor scope.
   Metadata fields/tool docs describe current-state traversal, reconciliation and source-
   freshness limitations. Keep old default query behavior except additive output metadata.
5. **Correct future standalone timestamps.** Inject a clock callable at the run.py boundary;
   persist samples on the DB thread after results arrive. Tests use controlled clocks and
   results finishing across the pass boundary. Preserve existing deterministic `now` callers
   via explicit test injection/compatibility as needed; production must use the new clock.
   No row backfill, clearing cache, changes to provider scheduling or fit pipeline timestamps.
6. **Add accurate overview counts.** Use the actual worker candidate predicate. Report fresh
   and retry-eligible counts, standalone outcomes with explicit scope, unknown-time count
   and response time. Ensure one consistent overview read; no source freshness fabrication.
7. **Wire the MCP schema and exercise the protocol.** Expose only the optional new fields,
   update descriptions/instructions, test validation through the actual server. Existing
   ten tools, redaction and read-only DB guarantees remain covered.
8. **Update docs and open PR.** Update shipped SPEC clauses + invariant traceability,
   CHANGELOG and current PROGRESS limitations only for work actually implemented. Include
   synthetic demo, commands/results, constraints, performance observation and issue link.
   Do not change other issue status or claim deployment. Return to Astra/Sol for acceptance.

## Required boundary cases

| Case | Expected evidence |
|---|---|
| Old posting, assessment saved today | Found in today's update window regardless of posting date |
| Pass starts before window, result finishes inside it | Newly sampled save timestamp is inside window |
| Provider error and retry completion | Both latest states discoverable when present; no invented historical events |
| Same timestamp across many jobs | Frozen traversal returns every matching id exactly once |
| Insert/update/delete between pages | Ceiling respected, no snapshot promise; overlap/reconciliation case documented/tested |
| Same cursor with different search/outcome/window | Rejected, no cross-filter page reuse |
| Equivalent timezone offsets and boundary instants | UTC-equivalent results, from inclusive/to exclusive |
| Legacy/unparseable timestamps | No fabricated time; reconciliation guidance and unknown count |
| JD-only literal %, _ or ! match | Escaped substring match; no wildcard injection/full-body list leakage |
| Complete result without usable checks | unknown, not a confirmed pass |
| Removed/scored/discarded rows with no screen | Not counted as eligible screen backlog |
| Posting changes eligibility during provider call | Save eligibility guard still wins; no resurrection |
| DB unavailable or malicious stored text | Safe bounded errors, no credentials/filesystem paths/instructions |

## Checks and acceptance packet

Run `make test-worker`, `make test-coverage` (floor 85%), `make test-integration`
for clock/stage wiring, and `make check-schema` to verify unchanged schema assumptions.
Run `make check-privacy` and diff whitespace/link checks. No live eval or provider call.
Use an isolated synthetic DB and local stdio MCP client for list → next page → get_job →
all JD chunks, plus an error path. Do not run production `--once` merely for a query change.

Astra/Sol checks exact head, all required boundary cases and an independent protocol
reproduction. Any fix goes to Luna/max. Close #91 only on accepted merged implementation;
local pass does not certify deployed tunnel or unattended ChatGPT. Deployment requires a
separate rollout decision and report. Do not merge/deploy yourself.

## Stop / handback conditions

Return to orchestrator if current code differs materially, an index/schema/event log is
needed, legacy timestamp formats cannot satisfy the declared contract, or literal-search
performance is unacceptable. Preserve progress as a draft PR with the precise unresolved
question. No silent scope expansion, no private data commits, no fit model changes and no
subscription-consuming evals. If assigned in goal mode, the bounded goal is #91's PR and
acceptance evidence, not an invitation to start subsequent issues.
