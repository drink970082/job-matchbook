# Versioned preselection assessment exposure

**Status:** design-only scope; database shape and read contract are not approved. No
assessment persistence, MCP/UI behavior, provider activation, or runtime policy is
implemented by this document. Implementation remains blocked on an operator GO in #112
and a reviewed persistence design.

This scope refines issue #113 in the
[preselection design](2026-10-26-fit-preselection-design.md). It follows the
[offline evaluation procedure](2026-10-27-preselection-evaluation-procedure.md), which
records that #112 has produced no live evaluation or GO decision. This document does not
authorize a model call, database write, migration, schedule, or rollout.

## Purpose and boundary

Expose validated, versioned preselection assessment evidence through read-only MCP and
the existing discovered-job inventory. Keep the evidence advisory and separate from
standalone hard-requirement screens, legacy fit scores, source availability, and
application state. The existing review path must remain usable when assessments are
missing, stale, invalid, or unavailable.

Issue #113 covers assessment persistence and display only. Daily batch selection,
deferred-queue allocation, delivery acknowledgement, cross-day suppression, and bounded
replacement belong to #114 or a separately approved design. Assessment visibility must
not hide jobs, change their order, create a qualification verdict, or update
`pipeline_status`, `score`, `score_detail`, `job_screenings`, or application records.

## Existing boundary and unresolved storage design

`job_screenings` stores standalone hard-requirement results and has its own result
contract. `score_detail` stores legacy fit evidence and is coupled to existing fit-bucket
behavior. Neither is an appropriate home for JEV assessments. The #111 attempt journal
is a private local resumability/evaluation artifact; it is not a shared MCP/Web record.

The existing design requires persistent versioned assessments, keeps old evidence
inspectable, and requires Prisma to own any new schema. It does not define the physical
record shape, history/retention policy, or authoritative relationship between durable
assessment records and the #111 attempt journal. Those remain a design gate. Do not add a
column to `job_postings`, reuse `job_screenings` or `score_detail`, or create a new Prisma
model until that gate is reviewed and approved.

The eventual persisted contract must retain enough provenance to distinguish assessments
by source-content revision, candidate-profile/context identity, question/rubric and
weight versions, prompt/schema versions, direct/extracted variant and extraction version
when used, YOE policy version when used, provider and resolved model, and draw/request
identity. Cost evidence must preserve actual, estimated, and unknown separately, with
usage and applicable currency/rate source metadata. The database-vs-journal ownership and
retention of attempt-level details are open; unknown cost must never become zero.

## Read contract to decide before implementation

Prefer a bounded summary on job-list reads and validated detail on a single-job read;
whether those are additive fields on `list_jobs`/`get_job` or a separate read-only MCP
tool remains open. Keep descriptions on the existing explicit chunk-read path. The
contract must:

- Identify assessment state and whether a usable assessment is current for the job's
  present content and the selected assessment-input versions.
- Return only validated typed components, concise evidence references to the job source,
  safe timestamps, and non-secret provenance needed to interpret the result.
- Keep attempted work separate from completed assessment evidence. A failed newer
  attempt must not erase or relabel a prior completed result; both states can be shown.
- Distinguish assessment state (`not_assessed`, `current`, `stale`, or
  `unknown`/integrity-invalid) from latest-attempt state (including failure). Missing or
  malformed identity is `unknown`, never a pass, a rejection, or a zero score.
- Preserve untrusted-JD boundaries: descriptions, extracted facts, and cited source text
  are data, not instructions. MCP remains read-only and bounded.

Do not expose candidate-profile text, résumé content, private evidence packets, prompts,
raw provider responses, journal paths, or unbounded exception text. Candidate identity
hashes and charge detail should not be exposed by default; the reviewed API contract must
name any field that is required outside the local evaluation artifact and justify it.

## Currentness and stale-result precedence

1. Capture the exact job-content revision and assessment input identity before starting
   work. The identity includes the approved profile/context, question/rubric, prompt and
   schema, variant/extraction, policy, provider, and resolved model versions that apply.
2. Publish a completed result as current only when those captured versions still match
   the job and active approved assessment configuration at write time. A delayed older
   completion remains inspectable but cannot replace a newer current result.
3. At read time, independently compare the completed result's captured identity with
   current source content and configured assessment versions. A mismatch is stale; do
   not repair it by silently relabeling the result or falling back to legacy fit/screen
   evidence.
4. Report source availability and application state alongside assessment state when
   needed for a later selection decision, but do not make #113 assessments perform
   #114 selection or deduplication.

Identity comparison must be exact and version-aware. Completion time, posting ID,
provider name alone, or a matching display score is not a cache key. Duplicate completion
of the same request must be idempotent. No database transaction may span provider work.

## Inventory presentation

The inventory should show a compact assessment state without changing existing screen,
fit, source, or application labels. The detail view may show validated assessment
components, job-source evidence references, assessment time, applicable version labels,
variant, provider/resolved-model identity, and a safe failure category. Older evidence may
be inspected as stale history once the storage contract supports it.

The page must keep all currently visible jobs accessible regardless of assessment state.
Do not apply a new sort, selection rule, filter default, badge-as-eligibility
interpretation, bulk action, or automatic application action under #113. If #112 GO
selects an aggregate priority formula, it may be displayed with its version and remain
informational; changing inventory order or using it to select daily work belongs to #114.
If no approved rubric yields a meaningful priority value, show independent components
and leave priority display for a later decision.

## File responsibilities after approval

No files below are changed by this design-only slice. After the data model and API shape
are approved, implementation is expected to touch only the owning seams:

| Area | Responsibility |
|---|---|
| `apps/web/prisma/schema.prisma` and `apps/worker/tests/fixtures/schema.sql` | Prisma-owned assessment persistence and worker schema-drift parity, after the record/history design is approved |
| `apps/worker/ats_worker/preselection/` and the composition root | Validate and persist completed shadow outputs with injected storage; preserve the default-off provider boundary and short writes |
| `apps/worker/ats_worker/mcp/read_repository.py`, `server.py`, and MCP tests | Bounded, validated, read-only exposure with current/stale/unknown handling |
| `apps/web/src/lib/actions.ts`, inventory/detail components, and Web tests | Read and render assessment state without changing legacy buckets or mutation behavior |
| `docs/SPEC.md`, `docs/PROGRESS.md`, `CHANGELOG.md`, `docs/EVALUATION.md` | Record shipped behavior and its real test traceability in the same implementation commit |

The exact persistence adapter/module, API field names, version-history query, and Prisma
relation are intentionally not selected here. Any web write action or MCP write tool is
outside #113's read-only exposure contract and needs a separate design.

## Acceptance criteria for a later implementation

- **Gate and defaults:** #112 records operator GO after accepted evidence; the #94
  unattended acceptance and any other stated prerequisites are resolved. The feature
  remains disabled by default. No model call or provider activation occurs in tests or
  read paths.
- **Storage:** approved Prisma schema and worker fixture remain in sync. Current and
  stale versions remain distinguishable; successful history is preserved; duplicate
  completion is idempotent; write transactions are short and never span inference.
- **Integrity and precedence:** synthetic tests cover exact identity matching, changed
  JD/profile/question/model versions, older completion arriving late, duplicate resume,
  invalid payloads, missing identity, and a failed newer attempt beside an older success.
  Unknown, stale, and failure states never become qualified or rejected.
- **MCP:** list responses stay bounded; a detail read returns only the selected
  assessment contract; job descriptions remain chunk-only; malformed records produce an
  explicit unknown/safe error; no write tool or private prompt/profile data is exposed.
- **Web:** inventory and detail show assessment state separately from latest-attempt
  failure (including not-assessed/current/stale/unknown assessment states);
  prior rows do not appear current while a new filter/page is pending; assessment state
  does not alter fit buckets, status, application controls, or availability of a job.
- **Compatibility:** existing screen outcome, triage, source freshness, fit score and
  application behavior retain their current semantics. Legacy and standalone evidence
  are not used to fill missing JEV fields.
- **Verification:** worker, web, integration, schema-drift and privacy gates pass as
  applicable; tests exercise the synthetic contract; no live model/evaluation call or
  private profile fixture is required. Any UI runtime claims include observed manual or
  e2e evidence.

## Decisions still required

- Physical Prisma record/history shape, retention, deletion behavior, and the source of
  truth for attempt-level usage/charge evidence.
- Whether list and detail MCP output is additive or uses a separate tool; exact safe
  provenance and cost fields; whether profile identifiers are labels only or a reviewed
  digest.
- Which typed components, if any, can be displayed as an aggregate priority after the
  rubric and ordering policy are approved.
- The accepted #112 result, #94 unattended workflow, provider/model, profile approval,
  questions/YOE policy, budgets, and recall/miss thresholds.

Until these decisions and the #112 GO gate are recorded, the file map and acceptance
criteria are preparation only.
