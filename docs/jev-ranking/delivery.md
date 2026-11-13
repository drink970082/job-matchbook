# JEV ranking delivery work packages

**Status:** planning baseline. Work is assigned only with an exact accepted document revision.
Read [entry](README.md), [design](design.md), [research](research.md) first.

## Dependency order

P0 contract/reuse audit → P1 frozen research package → P2 authorized evidence → P3 persisted
single-job MCP slice → P4 bounded batch/recovery → P5 consumer acceptance → P6 rollout.
P3 may be prototyped with synthetic inputs before P2 only by an explicit scoped assignment;
that exception does not authorize production integration or JEV calls. Current assignment
is docs/issues only. Every package below is a future assignment, not an active agent task.

## P0 — Contract and integration audit (Sol)

Deliver exact rubric questions/projection, domain vocabulary, boundary examples, logical
result/attempt schema, cursor semantics, cache identity and failure transitions. Inventory
current main's fetch/source revisions, screen result, repository queries, MCP tool schemas
and worker scheduling entry points. Read research PR #134 at a pinned revision; list the
minimal reusable functions and their transitive dependencies. Explain anything rejected.

Resolve bytes/tokens/provider limits with current official evidence; measure complete request
size distribution offline. Choose and justify configurable limits rather than preserve 24KB.
Record actual current intake filters that can hide jobs before ranking; changing ranking
cannot restore those jobs. Do not broaden fetch scope without a separate decision.

Acceptance: one complete synthetic example from stored source through projected MCP output,
plus unknown/stale/overbound examples; schema and provider facts distinguished from proposals;
no unexplained architecture fork; no code changes or calls required. Update this contract
through orchestrator review if a new decision is needed. Reconcile overlapping #113/#114/#115
and legacy research tickets before assigning implementation so two agents cannot own the same
persistence/MCP/batch scope.

## P1 — Freeze a comparable evaluation package (Sol + bounded Luna preparation)

Sol defines cohorts, labels, budgets, questions, thresholds, token/rate evidence requirements
and stop rules. Luna can write minimal manifest/metric utilities using synthetic fixtures once
assigned; avoid a general experiment platform. Prepare development and >=3 held-out day pools,
source-roster reconciliation, grouping, approved input hashes and blind proxy rubric.

Acceptance: reproducible baseline and JEV-input artifacts, complete metric definitions,
fixed K/R and domain allocation, size outliers preserved, missing evidence explicit, public
report template, exact proposed paid workload. Existing approved local input ownership is
respected; no new candidate facts. Preparation does not include model-based blind labeling
unless its subscription workload has been explicitly assigned.

## P2 — Measure the minimal ranker and decide (Sol lead; Luna bounded execution)

Blocked by accepted P1 and separate exact inference authorization. Run A first. Freeze blind
proxy judgments before opening JEV output. Run B only with a new scoped hypothesis/approval.
Include observed provider identity/token/rate/charge data and all failure costs. Reconcile
historical ledgers before extending; no resetting closed epochs.

Acceptance: full research report and NO-GO/INCONCLUSIVE/LIMITED-TRIAL-CANDIDATE decision,
including baseline comparison, important misses, review load, coverage, cost and limitations.
A failure leaves production work blocked; no workarounds built merely to make the experiment
pass. Small study evidence cannot claim human accuracy or unattended delivery.

## P3 — One job from snapshot to stored ranking to MCP (Sol)

Blocked by P0 contract and P2 candidate decision (or explicit synthetic-only exception).
Implement a thin end-to-end path: exact source/profile binding → injected native adapter →
validated projection → additive persistence → list/detail/coverage MCP consumption. Use a fake
provider in tests, no live model calls. Select minimal code from #134; never merge all research
as prerequisite. Preserve independent raw browsing and screen/application state.

Acceptance: synthetic high/medium/low/unknown jobs demonstrable through actual MCP path;
wrong ID and schema cannot become success; private profile absent from public output; cache
hit and changed-input invalidation; current/stale distinctions and low/unranked discovery.
Prisma/schema synchronization, relevant worker/integration tests and MCP tests pass. No UI
redesign required; any changed web query/action receives relevant web checks.

## P4 — Batch completion and recoverable operation (Luna; Sol owns state-machine changes)

Blocked by P3. Extend the same end-to-end path across bounded batches with attempt claims,
limits, retries, systemic circuit break, durable latest-success/latest-attempt states and
visible pending/deferred/failed counts. Prevent duplicate dispatch on overlapping schedulers.
No historical backlog drain or service scheduling change during implementation.

Acceptance: fault-injection demos for timeout after send, crash after response before commit,
429/5xx, invalid key, size bound, exhausted budget and failed refresh. Resume does not reset
caps or reclassify unknown cost as free. One bad item does not lose unrelated work. MCP shows
honest status through every transition; deterministic synthetic accounting reconciles.

## P5 — ChatGPT consumes ranking under a fixed budget (Sol)

Blocked by P4 and separately authorized live canary if real inference is needed. Exercise
real MCP list/detail/coverage tools, including rank updates during pagination, late completions,
unranked reserve, stale results, no results and duplicate roles. Run C at fixed total K.

Acceptance: privacy-safe transcript/checklist, unique items read, data cutoff, source checks,
missed opportunities and actual usefulness reported; current model/source/profile bindings
verified. Interactive and unattended acceptance explicitly separate. If Scheduled execution
is in rollout scope, verify that exact connection sees tools/profile and observe unattended
run under #94; no claim based on interactive-only success.

## P6 — Controlled rollout and maintenance handoff (Luna execution; Sol acceptance)

Blocked by P5 plus operator approval of exact build/model/rubric, initial scope, schedule,
attempt/money/time caps and rollback. Prepare enable/disable commands, additive DB safeguards,
health counters and canary comparison before requesting activation approval. No default
legacy scorer deletion. Expand canary only after review of real benefit and failures.

Acceptance: source browsing survives disabled ranking; rollback demonstrated; canary meets
accepted gates; operator workflow usefulness recorded; docs reflect actual deployed behavior;
minimal owned production modules separated from archived research; follow-up defects recorded.
No self-merge/deploy by implementer. Merge and activation remain distinct acts.

## Assignment template (mandatory)

- Issue and exact design/research/plan commit.
- Owner model: Sol for uncertainty; Luna for fixed bounded implementation. Effort explicitly
  chosen at assignment; this does not change runtime model selection.
- Dependency evidence and accepted gate result, not merely links to open tickets.
- Allowed files/surfaces and side effects; forbidden provider/DB/deployment operations.
- Approved inputs/model/budgets if inference is permitted; otherwise fake provider only.
- Acceptance scenarios, required commands and expected artifacts.
- Stop/escalate conditions: unresolved policy, new dependency, data loss risk, scope expansion.
- Return exact commit/PR, actual commands/results, docs changed, unverified items and risks.

Implementation branches start from current main with a PROGRESS claim. Tests remain hermetic.
Run relevant DEVELOPMENT gates (worker/coverage, integration, schema, MCP, web/lint/e2e when
changed, privacy). Behavioral changes update SPEC/invariant traceability, PROGRESS and CHANGELOG
in the same commit. A fresh reviewer checks the exact implementation head before merge.
Planning issues are not closed by this docs PR; owners close deliverables only on acceptance.

## Issue index

Parent: [#135 — JEV ranking delivery](https://github.com/drink970082/job-matchbook/issues/135). All packages are unassigned.

| Package | Owner | Issue |
|---|---|---|
| P0 | Sol | [Freeze JEV ranking contracts and audit integration/reuse](https://github.com/drink970082/job-matchbook/issues/136) |
| P1 | Sol + bounded Luna | [Prepare frozen ranking cohorts, baseline and evaluation contract](https://github.com/drink970082/job-matchbook/issues/137) |
| P2 | Sol lead; Luna bounded execution | [Evaluate minimal JEV ranking under an authorized fixed budget](https://github.com/drink970082/job-matchbook/issues/138) |
| P3 | Sol | [Deliver one-job JEV ranking persistence through MCP](https://github.com/drink970082/job-matchbook/issues/139) |
| P4 | Luna; Sol for state-machine decisions | [Run bounded ranking batches with visible recovery over MCP](https://github.com/drink970082/job-matchbook/issues/140) |
| P5 | Sol | [Validate ChatGPT consumption of ranking through real MCP](https://github.com/drink970082/job-matchbook/issues/141) |
| P6 | Luna execution; Sol acceptance | [Prepare and accept a controlled JEV ranking rollout](https://github.com/drink970082/job-matchbook/issues/142) |
