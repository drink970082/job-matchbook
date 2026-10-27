# Bounded preselection review batches

**Status:** design-only scope; selection policy, batch persistence shape, and resource
values are not approved. No queueing, selection, schedule, delivery, or runtime behavior
is implemented here. Implementation remains blocked on #112 operator GO and the #113
assessment persistence/read contract.

This scope refines issue #114 in the
[preselection design](2026-10-26-fit-preselection-design.md). It also depends on the
[#113 exposure scope](2026-10-27-versioned-preselection-assessment-exposure-design.md).
The [evaluation procedure](2026-10-27-preselection-evaluation-procedure.md) records that
#112 has no live evaluation or GO decision. This document does not authorize model calls,
database writes, migration, scheduling, MCP writes, or rollout.

## Purpose and boundary

Define a persistent, bounded set of postings for a human's daily deep review. A batch must
make paging and resume stable while making overflow, deferred work, invalidation, and
unfilled capacity visible. It consumes already-current assessments and evidence from
#113; it does not launch or enable the #111 shadow provider path.

Issue #114 covers selection-batch creation/read, its queue accounting, and UI/MCP
presentation. It does not approve a model, rubric, rank formula, allocation, work
schedule, or user acknowledgement. It does not mark a job read, delivered, applied,
eligible, or rejected. The existing manual retrieval path remains available when there is
no usable batch.

## Candidate pool and eligibility

The eventual pool must account for all of these groups, not only recently created jobs:

- Newly retained postings and postings with a newly completed current assessment inside
  the run's explicit source/data cutoff.
- Existing deferred items that remain pending, plus retries that are due under the
  approved retry policy.
- An initial historic inventory only when a separately bounded backfill is approved.

Before allocating review slots, omit only confirmed prior applications, explicit manual
terminal decisions, and confirmed closed sources. Keep those reasons/counts without
rewriting posting or application data. Unknown source state is not closed. Stale or
integrity-unknown assessments, incomplete JDs, and unresolved eligibility route to a
visible unresolved/deferred allocation; they do not inherit current eligibility from a
legacy score or standalone screen.

Deduplicate exact `(source, external_id)` requisition identities before slot assignment.
Cross-source candidates require corroborating identity before they can be collapsed;
company/title similarity alone is a possible-duplicate flag for human review. Preserve
all source provenance and application history even when an application has no posting
link.

Each run needs an explicit UTC half-open source/data interval and actual cutoff. Whether
the interval is 24 elapsed hours, how the initial cutoff is chosen, and how late commits
are reconciled remain decisions. Local delivery time and daylight-saving changes must not
silently redefine the interval. A later run resumes/reconciles from a recorded successful
cutoff; it does not assume a timestamp window is an exact-once event log.

## Capacity, fairness, and deferred aging

The decision record must set a total deep-read capacity `K` and explicit allocations for
ranked work, low-rank audits, and unresolved work that sum to the approved capacity.
Those values are open. It must also decide role-family coverage, deterministic tie breaks,
how unused slots are redistributed, and what happens when daily arrivals exceed capacity.
Do not equate an assessment confidence value with calibrated recall or qualification.

Low-rank audits must include confident low-ranked examples as well as uncertain ones. If
the audit is sampled, persist the random seed, sampling frame, and inclusion probability
needed to interpret its results. Never present a convenience sample as full-pool recall.

Deferred items need a stable age origin, visible reason, retry-due time where applicable,
and an approved service allocation in which age affects selection. Age displayed without
an age-sensitive policy does not prevent starvation. The design must set maximum-wait
alerts and overflow reporting before claiming a fairness or eventual-review property.
No policy can claim every row will be reviewed unless measured capacity supports it.

`K` is a deep-read target, not a promise that `K` recommendations can be filled. Keep
separate counts for available, selected, deferred, invalidated, actually read, replaced,
and unfilled slots. All replacements and validation work count toward approved attempt,
time, token, and monetary ceilings. Unknown cost is not zero and must stop new work when
the remaining approved budget cannot be established safely.

## Fixed batch and revalidation

Persist an immutable ordered batch identity and the job/assessment/source versions chosen
for each entry. Page cursors and same-batch resume must read that snapshot; new arrivals or
live assessment changes cannot reorder its existing pages. The physical batch/entry
schema, unique key, retention, and page-token representation remain open and must be
reviewed with the #113 persistence design before implementation.

Before a job is recommended or its original JD is read, revalidate current content,
source availability, and confirmed application state. If the posting content or assessment
identity changed, mark the entry stale/review-needed. Never silently substitute a new JD
revision under an old entry. If a source closed or an application is confirmed after
selection, invalidate the entry and apply only a separately approved, bounded replacement
rule. Record the invalidated entry and replacement as separate provenance; replacements do
not reset page order or resource ceilings.

Selection means selected only. It does not prove a human read the job or that MCP delivered
the batch. Without #95 or an approved acknowledgement contract, another day's run may
repeat an item selected earlier. Same-batch resume is idempotent; cross-day deduplication
must not suppress an item solely because it was previously offered. Do not add an MCP
write tool implicitly.

## Access and presentation

The MCP read path should expose a bounded batch summary and stable page reads, including
the run/data cutoff, batch version, selection rule version, capacity accounting, and
entry state/reason. Deferred and unresolved coverage must remain queryable even when the
ranked page is full. Exact tool names/response fields remain open with #113's read-contract
decision. MCP remains read-only.

The inventory UI should distinguish selected, deferred, stale/review-needed, invalidated,
replaced, read-confirmed (only if a separately authorized acknowledgement exists), and
unfilled capacity. A queue age must be visible with its meaning. Do not label selection as
delivery, reading, eligibility, or application. Keep the ordinary all-jobs search path
available and preserve existing fit buckets, standalone screen evidence, source state,
and application controls.

If a user action creates or refreshes a persisted batch, it is a database write and needs
an explicit Server Action with validated scope and idempotency. No MCP write or implicit
scheduled trigger is included by this design. The owning trigger/composition path is an
open decision; this slice does not create a schedule.

## File responsibilities after approval

No files below are changed by this design-only slice. After policy, dependencies, and
storage are reviewed, implementation is expected to use the owning seams:

| Area | Responsibility |
|---|---|
| `apps/worker/ats_worker/preselection/` | Pure selection/allocation and queue-state rules with injected clock and deterministic tie/sample inputs |
| Worker repository/composition root | Create/resume batches, persist bounded state and revalidate entries without a transaction across external work |
| `apps/web/prisma/schema.prisma` and `apps/worker/tests/fixtures/schema.sql` | Prisma-owned batch/entry persistence and worker schema-drift parity after the record contract is approved |
| `apps/worker/ats_worker/mcp/read_repository.py`, `server.py`, and MCP tests | Bounded, read-only batch summaries/pages and deferred coverage |
| `apps/web/src/lib/actions.ts`, inventory components, and Web tests | Server-side batch writes if approved; stable reads and visible state/capacity accounting |
| `docs/SPEC.md`, `docs/PROGRESS.md`, `CHANGELOG.md`, `docs/EVALUATION.md` | Shipped contract, open residuals, and test traceability in the implementation commit |

The selector module name, worker entry point, transaction ownership, trigger path, Prisma
models, and API fields are deliberately not fixed here. Do not issue `db-push`, activate a
scheduled task, or add MCP mutations as part of scope refinement.

## Acceptance criteria for a later implementation

- **Dependency gate:** #112 contains an operator GO on accepted held-out evidence; #113's
  persistence/read contract is reviewed and implemented; #94 unattended acceptance and
  the prerequisites required by GO are recorded. If evidence is NO-GO or inconclusive,
  do not build selection on top of it.
- **Frozen behavior:** a persisted batch has stable ordered identities, source/assessment
  versions, cutoff, policy version, capacity, and resume semantics. Changes after batch
  creation do not reorder its existing pages. Repeating the same request is idempotent.
- **Coverage:** synthetic cases include new/current, newly assessed old jobs, overdue
  deferred work, due retries, source/application exclusions, unknown/stale/incomplete
  rows, exact duplicates, probable cross-source duplicates, oversubscribed pools, empty
  allocations, and aged items through ties.
- **Fairness and bounds:** approved ranked/audit/unresolved allocations sum to `K`; seeded
  audits are reproducible and retain their sampling frame/probabilities; age changes
  service allocation; max-wait/overflow behavior is visible. Tests prove each selection,
  retry, validation, and replacement ceiling and account for unfilled slots.
- **Revalidation/replacement:** mutate source content, close a source, or add a confirmed
  application between selection and read. Old entries become stale/invalidated with a
  reason; only an approved bounded replacement is added and recorded separately.
- **Cross-day semantics:** same-batch resume does not duplicate work; a previous selection
  alone does not hide a posting in a later batch. The UI/MCP never claims that selection
  was read or delivered without a separate acknowledgement.
- **Resource accounting:** actual, estimated, and unknown costs remain distinct and
  include validation/replacements. Unknown budget state stops new provider work. Batch
  selection itself makes no provider call and cannot enable #111 inference.
- **Access and compatibility:** MCP reads are bounded and read-only; any Web mutation uses
  an approved Server Action. All-jobs/manual retrieval remains possible; existing screen,
  source, fit, application, and legacy bucket semantics remain unchanged.
- **Verification:** applicable worker/web/integration/schema/privacy gates pass. Synthetic
  end-to-end tests cover create, resume, pagination, overflow and invalidation; UI behavior
  is demonstrated with e2e or recorded browser steps. No live evaluation or production
  DB write is required for routine tests.

## Decisions still required

- #112 GO/NO-GO/inconclusive and the accepted assessment/ranking policy.
- UTC run interval and cutoff/reconciliation contract; initial historic backfill bound.
- `K`, ranked/audit/unresolved allocations, role coverage, tie breaks and unused-slot
  redistribution.
- Queue-age origin, retry cadence, service allocation, max-wait alert and overload behavior.
- Per-run page, attempt, wall-time, token and cost ceilings; replacement limit and policy.
- Persistence/history shape shared with #113, selection-batch write owner, and how a UI
  requests a batch without adding an implicit MCP write or schedule.
- Whether cross-day repeats are acceptable or require #95/another acknowledged delivery
  design; what evidence is sufficient to label a job read.

Until these decisions and the dependency gates are recorded, the file map and acceptance
criteria are preparation only.
