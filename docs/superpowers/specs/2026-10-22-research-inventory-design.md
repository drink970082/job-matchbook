# Research retrieval and visible inventory

**Status:** approved scope — user-approved MCP-first / inventory-second direction;
contracts below are the orchestrator's bounded implementation specification. Material
changes to schema, dependencies, write capabilities or runtime defaults return to the
orchestrator/user before implementation. No implementation is shipped by this document.

## Outcome and ownership

[Issue #91](https://github.com/drink970082/job-matchbook/issues/91) makes read-only MCP
useful for research without fit scoring. [Issue #92](https://github.com/drink970082/job-matchbook/issues/92)
makes that inventory visible in the tracker. Astra/Sol designs and accepts; Luna/max
implements and fixes. Baseline workflow #90 can inform both without blocking initial work.

Principles 2/3 require factual summaries without inventing eligibility; 5/6 require visible
errors; 7/13 favor existing SQLite/tools; 9/10/11 preserve schema ownership, injected clocks
and main-thread DB writes; 12 requires synthetic fixtures, redaction and untrusted-JD
boundaries. Recall and cheap assistance are in tension: expose judgments as advisory and
retain access to jobs regardless of fit. Existing intake rules are not changed here.

## Batch 1 contract

Keep existing ten tool names and existing default search/date/order semantics. Extend
list_jobs with optional screen_outcome, search_scope (metadata default, all_text opt-in),
and screening_updated_from / screening_updated_to (offset-aware RFC3339 instants,
from inclusive, to exclusive). Time windows filter job_screenings.updated_at, including
errors; they are not filters for job creation, arbitrary posting edits or historical events.
Normalize comparison instants to UTC; support the existing stored timestamp formats.
Unknown/unparseable stored times do not silently qualify for a dated result; expose their
count separately. No worker DDL, new provider, vector service or new MCP write tool.

Every list item gains a bounded screen_summary with outcome, reason, assessment time,
model/effort provenance and origin. Reasons must be length-bounded and pass existing
sanitization. Do not return full JD or raw result JSON in list responses.

Authoritative outcome for these filters is the standalone job_screenings row:

| Condition | Outcome |
|---|---|
| No standalone row | not_screened |
| Stored provider_error | provider_error |
| Complete valid result with explicit boolean disqualified=true | disqualified |
| Complete result with explicit disqualified=false, at least one typed boolean pass check, and no contradictory failing check | no_disqualifier_found |
| Missing/malformed/contradictory result, no usable checks, unrecognized stored state | unknown |

A no_disqualifier_found result is not confirmation of sponsorship, pay or universal
qualification; missing individual checks remain unknown. Legacy score_detail.screen is
available as separately labeled legacy evidence, never silently converted to a standalone
result or used to fabricate completion time. Unknown states must remain readable.

Overview adds standalone outcome counts and eligible backlog counts using the worker's
actual eligibility: pipeline_status=new with no standalone row or provider_error. State
which counts cover all rows versus only eligible rows. Count categories are disjoint for
that scope. Read the overview in one short read transaction; response_generated_at is a
query timestamp, not a claim about last fetch completion or source freshness.

Search all_text includes title/company/location/description. Literal substring semantics
must escape %, _ and !; bound input and page sizes. Description remains chunk-only in
responses. Null and empty descriptions remain distinct. Use existing SQLite facilities;
do not claim multilingual tokenization or semantic search. Measure against a synthetic
large fixture and document query cost; a need for new indexing/schema returns to design.

### Clock and traversal boundary

Correct future standalone assessment timestamps at the persistence boundary using a
clock injected from run.py into the pipeline. Sample on the DB/main thread after the
provider result is available, immediately before saving. Preserve DI, provider cache,
call caps/breaker, posting eligibility recheck and screen-only isolation. Existing rows
retain their original timestamps. Do not call this exact commit time; DB lock waits can
separate sampling from commit.

Retain descending immutable posting-id keyset traversal and filter-scoped cursors.
Add a first-page max-id ceiling to the cursor for new traversals; new higher-id inserts
are deferred to a subsequent traversal. Extend cursor scope to every new filter. Preserve
old query defaults; previously issued incompatible cursors may fail with the existing
safe invalid-cursor error, never silently restart a page.

For a frozen dataset all matching rows appear once. Across requests, current row state
may change: this is NOT a snapshot or event log. A screening may enter the filter behind
the cursor, or change twice before a reader sees it. Callers rerun overlapping windows,
dedup by source/external_id plus assessment time, and periodically reconcile the current
inventory. Overlap does not guarantee capture of arbitrary backdated writes or every
transition. Legacy pass-start timestamps require an initial full reconciliation, not a
promise that a short overlap repairs old data. Response/tool docs must state these limits.
No long-lived read transaction, snapshot table or append-only event schema in this batch.

## Batch 2 contract

Add All jobs inventory as the default only when no explicit view selection exists.
Include all non-removed stored pipeline states, including discarded/applied/unknown;
label them accurately. This is not an assertion that all are open or recommended.
Keep legacy Matched/Below bar/Discarded/Failed/Low context views accessible. Existing
explicit view selections remain respected where the app supports them.

Provide standalone outcome filters, metadata/all-text search, existing safe sort controls
and full JD inspection. Show standalone summary separately from fit and legacy evidence.
Use the batch-1 outcome semantics, including unknown/error behavior. Python and TypeScript
may have separate small implementations, but share a committed synthetic contract fixture
and test parity; do not introduce a cross-service request just to reuse code.

Preserve existing per-row actions and application/history behavior. Hidden removed rows
remain hidden by default. Do not add bulk deletion or bulk lifecycle changes to new
inventory views. For any already-supported bulk action reachable with new filters, reuse
the exact list predicate server-side. If a filter is unsupported by a mutation, reject it
explicitly rather than dropping it. Tests cover this even if a button is hidden.

No auto-scoring, auto-apply, new write MCP tools, fit-model changes, fetch gate changes,
retention cleanup, source refresh or background scheduler in these two batches. Keep
assessment time separate from source freshness; do not add a misleading "fresh" badge.

## Alternatives and acceptance

- Reuse Matched as the default inventory: rejected, excludes unscored jobs.
- Snapshot/event-log retrieval now: deferred, adds schema and lifecycle scope before
  demonstrating the need; current-state traversal limits are explicit instead.
- Treat complete/disqualified=false as fully qualified: rejected, missing checks exist.
- Unify pipeline_status and all assessments now: deferred to lifecycle design; preserve
  shipped compatibility and distinct presentation first.
- Add vector search or replace scorer: deferred; literal retrieval is sufficient to test
  the workflow and does not require inference.

Acceptance requires the cases/checks in the linked batch plans, fresh Astra/Sol review
of exact PR head and a demonstrated synthetic MCP/browser path. Runtime acceptance after
deployment is separately reported; local synthetic acceptance is not ChatGPT tunnel or
unattended Task acceptance. Plans never authorize live model evals or destructive cleanup.

## Plans

- [Batch 1 — MCP research](../plans/2026-10-22-batch-1-mcp-research.md)
- [Batch 2 — inventory UI](../plans/2026-10-22-batch-2-job-inventory.md)
