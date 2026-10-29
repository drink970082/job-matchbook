# Preselection: offline preparation contracts

**Status:** the offline assessment view, batch replay and composed synthetic rehearsal
are available in the repository. This document defines their maintenance contract;
SPEC describes the implemented behavior. Parent production integrations, live evaluation
and runtime activation remain gated. Next assignable work is the
[#111/#112 repair handoff](2026-10-29-preselection-shadow-repair-handoff.md).

## Operator direction and selection

The operator reports that the current workflow cannot process approximately 200 postings
per day and explicitly selects pre-ranking. This is the recorded product need; it is not a
new benchmark or an accepted #112 evaluation. Do not require the operator to justify the
need again. #94 still owns actual unattended access/delivery evidence, but is not a
prerequisite for the bounded preparatory slices below.

The bounded preparation contract permits provider-free, schema-free synthetic work
without waiting for upstream live evaluation. Production persistence, live MCP/UI
integration and rollout remain blocked; no GO is inferred from software tests.

## Work graph

| Slice | Parent | Deliverable | Real implementation dependencies |
|---|---|---|---|
| [#117 / PREP113](https://github.com/drink970082/job-matchbook/issues/117) | #113 | Synthetic assessment snapshot → safe shared read projection → isolated React panel | None of #111/#112/#94; current main and this contract |
| [#118 / PREP114](https://github.com/drink970082/job-matchbook/issues/118) | #114 | Synthetic candidate pool + explicit policy → fixed batch → local page/resume/revalidation report | None of #111/#112/#113/#94; lean candidate inputs below |
| [#119 / PREP115](https://github.com/drink970082/job-matchbook/issues/119) | #115 | Synthetic consumer traverses PREP113/PREP114, records faults/monitoring and rehearses local fallback | Actual PREP113 and PREP114 modules |
| Existing fixes | #111/#112 | Deadline/backoff and evaluation integrity/composition/recurring-pool corrections | Their existing implementation branches; separate changes, not prerequisites for PREP113/PREP114 |

Maintenance must keep the three modules independently importable and their actual
composition testable. #111/#112 repairs remain separate; they are the next assignable
scope and must not modify production integration under the preparation label.

Each slice must be demoable through actual code in its bounded path, not a collection of
empty interfaces, TODOs, mocked versions of the very module under test, or fixed report
fixtures. Its output is useful preparation, not completion of the parent issue.

## Branch and dependency discipline

- Repository: `drink970082/job-matchbook`. Fetch explicit remote-tracking refs and inspect
  actual main; a successful `ls-remote` alone does not refresh local refs.
- The offline modules are part of main. Maintenance branches start from current main;
  the unmerged provider-neutral/evaluation stack is not a dependency of these modules.
- Planning PR #107 remains a separate draft. The #111/#112 source branches remain
  unaccepted and carry their own upstream dependencies; use the repair handoff for them.
- One logical unit per branch/PR. Claim maintenance work in PROGRESS before changing it.
  Implementation acceptance does not close parent live-integration issues.
- Protect the dirty primary checkout; use isolated worktrees. Never switch, reset, stash,
  clean, stage or commit another session's changes. Do not access runtime services.
- Merge authority and exact-head independent review follow DEVELOPMENT. No force pushes,
  live inference, schema migration or deployment are implied by these contracts.

## PREP113 — assessment evidence to an isolated read component

### Complete path

Build a strict fixture-input adapter and pure Python projection, emit a bounded JSON view,
validate/render the same view in TypeScript, and display it in an isolated React panel.
A local fixture command plus a component-render test must drive this path. The panel is
not connected to inventory queries or the deployed UI. No Prisma schema or MCP tool is
added. The serialized view is a preparation contract, not an approved final public API.

### Contract to implement

- Use schema `1` for a local synthetic snapshot. The input holds the caller's expected
  assessment identity, an optional last-success snapshot with captured identity, and
  independent latest-attempt metadata. All text/data is fabricated and marked synthetic.
- The identity comparison includes source revision/content digest, profile/context
  identity, question/rubric/policy version, prompt/schema version, input variant and
  provider/requested/resolved model; include extractor identity only for extracted input.
  Treat missing, malformed or inconsistent identity as unknown. Never read a profile or
  resume to repair it. Identity fields are opaque supplied data, not verification that a
  real call occurred; binding real attempts remains #112 work.
- Assessment state is `not_assessed`, `current`, `stale`, or `unknown`. Latest attempt
  state is separate. A failed later attempt never erases or relabels an older completed
  result. Invalid/unknown data cannot become a positive eligibility badge or a zero score.
- The view includes only validated typed component values, bounded display labels, safe
  offset-aware assessment time, safe version/model labels, and optional JD-source evidence
  references. It omits raw responses, prompts, free-form explanation, candidate evidence,
  profile/context digests and filesystem paths. No private text may be echoed by errors.
- Do not copy candidate-context evidence quotes from #111 into a public panel. Use only
  allowlisted JD evidence fields; reference IDs must resolve in the supplied synthetic
  source. The view must remain useful when all candidate-side evidence is withheld.
- Keep output limits explicit and shared: at most 32 components, 120 characters per
  display label, and 300 per reason/quoted JD excerpt. Reject oversized structural lists
  visibly rather than silently dropping components; bounded display text shortening is
  labeled as such. These are display bounds, not model-input truncation policy.
- Python and TypeScript consume the same fabricated contract cases. Follow the existing
  cross-language triage-fixture pattern. Unknown future schema versions yield an explicit
  unsupported/unknown state; they do not inherit legacy fit/screen values.
- Use existing strict timestamp/revision behavior (positive JS-safe revisions, valid
  offset-aware instants) where reusable without legacy fit imports.

### Cases and allowed files

Cases: absent success; current; changed content/profile/question/model; old result arriving
after a newer expected identity; current success plus newer provider error; missing
identity; malformed payload; invalid timestamp/revision; unsupported schema; injection
text; oversized content; JD reference validation; suppression of synthetic private text.

Expected areas: new pure worker view/fixture CLI and tests; one shared synthetic fixture;
new TS view validator/normalizer, isolated React panel and relevant tests. Existing
`DiscoveredJobsTab`, `DiscoveredJobsTable`, `JobDetailModal`, Server Actions, MCP repository,
server tool registrations and Prisma schema remain outside this preparatory slice.

Acceptance is fixture → real projection → JSON → TS validation/panel render with parity,
not merely testing a hand-written expected JSON. Actual compare-and-publish DB races and
inventory/MCP paging remain parent #113 work after the gate.

## PREP114 — candidate pool to fixed review-batch replay

### Complete path

Build a pure allocation/state module and an explicit local-fixture CLI. Given fabricated
candidate records, an injected clock, an explicit policy and seed, produce a fixed batch,
page/resume it, apply simulated revalidation changes/replacements and report accounting.
Allow an explicitly named local JSON state path for replay only. Open no SQLite DB and
read no profile, config, journal, resume or real posting snapshot.

### Contract to implement

- Distinguish stable posting/content identity from daily occurrence identity. Key an
  occurrence by pool + posting identity + source revision, so the same unchanged job can
  remain pending on two days. Inference/cache identity must never be fabricated to make
  repeated membership unique. All split/group integrity stays visible when supplied.
- Lean input includes source/requisition identity, content/assessment versions and state,
  first-eligible/deferred timestamps, retry due time, role-family IDs, caller-supplied
  priority order, source state, confirmed/manual application evidence, and an independently
  supplied YOE outcome. Do not compute JEV scores, reinterpret private facts, import old
  fit gates or assume missing YOE/screen/source evidence is qualification.
- Form the pool from newly retained, newly assessed, old deferred and due-retry inputs.
  UTC half-open cutoff/resume intervals are explicit; historic backfill is not implicit.
- Exclude confirmed applications, explicit manual terminal actions and confirmed closure
  with recorded reasons. Unknown source state is not closed. Stale/incomplete assessment
  or eligibility evidence goes to visible unresolved/deferred routing. A supplied YOE
  exclusion remains independent of legacy rule/screen triage.
- Exact source/requisition duplicates collapse with provenance; corroborated cross-source
  identity may collapse only with explicit supplied evidence. Title/company similarity
  alone is a review flag. Include unlinked application fixtures.
- Require policy version, K, ranked/audit/unresolved allocations summing to K, tie rule,
  age-service parameters, retry/overload thresholds, seed and replacement/work caps from
  the caller. Missing values fail configuration validation. No production defaults or
  candidate role weights are selected.
- Separate the state engine from policy combination. Implement useful deterministic
  helpers for supplied priority order, oldest-first service, greedy multi-role coverage
  and uniform low-rank auditing. A named synthetic recipe explicitly composes those
  helpers and demonstrates age-sensitive service and unused-slot redistribution; it is
  labeled synthetic, not adopted as the operator's production selection policy. Avoid a
  generic strategy DSL or empty policy stubs.
- Audit sampling is without replacement from a frozen, explicitly reported frame. Keep
  seed and inclusion probabilities. If probabilities cannot be established for a recipe,
  fail that sampling contract; do not pretend convenience sampling is an unbiased audit.
- Freeze ordered entry IDs and captured input versions. Cursors bind batch, snapshot and
  page scope; live input/rank changes cannot reorder earlier pages. Repeated same-batch
  resume is idempotent. A later day does not suppress an item just because it was selected.
- Revalidate simulated content/source/application changes before a recommendation step.
  Preserve invalidated entries and reasons; changed JD revision is stale, not a silent
  replacement. Replacement annotations reference the invalidated slot, preserve original
  cursor/order semantics, and stop at configured replacement/work/time caps.
- Report available/excluded/duplicate/deferred counts, initial selections, replacement
  entries, invalidations, active slots and unfilled slots with explicit denominators.
  Distinguish slot counts from entry counts. `actually_read` and `delivered` stay unknown
  without acknowledgements. Local selection has zero provider calls; downstream human/
  ChatGPT resource cost is external/unknown, not a monetary zero.

### Cases and allowed files

Cases: 0/1/200/>200 fabricated arrivals; all applied/closed; unknown and stale evidence;
old deferred without updates; due/not-due retry; UTC boundaries/DST; rare/hybrid roles;
ties; low-rank positives; source/application changes after selection; overlapping pages;
interruption/resume; repeated days; sustained overload and age service; unused allocations;
replacement exhaustion; invalid cursors and conflicting policy identity.

Expected areas: new pure batch module, fixture CLI, fabricated fixtures, meaningful
unit/integration-style CLI tests and current-state docs. No new DB model, Server Action,
MCP registration, production query, scheduler, worker runtime hook or acknowledgement
ledger. This module remains independent of PREP113 and the shadow/report implementations.

## PREP115 — synthetic consumer, monitoring and fallback rehearsal

### Complete path and staging

Drive the real PREP113/PREP114 modules using a fixture-backed
read adapter and deterministic consumer. It retrieves two or more pages, reads a
multi-chunk fabricated JD, checks fabricated applications, injects source/provider-state
failures and produces an explicit observed-case report. Contract changes require
composition with the actual modules, not duplicate fake algorithms or a canned report.

Use the existing read-tool vocabulary where applicable; a fixture adapter is not a new
live MCP server or a proof that ChatGPT Scheduled supports those calls.

### Contract and acceptance

- Every result identifies `scope=synthetic_rehearsal`, actual fixture cases exercised,
  versions, clock/cutoff, limits, observed results and failure categories.
- Separate `passed`, `failed`, `not_exercised` for synthetic cases. Report real Scheduled
  access/delivery, live provider/model quality and #112 GO as `not_exercised` or
  `not_recorded`. Missing real evidence must not produce a live acceptance PASS.
- Cover multi-page/multi-chunk traversal, empty probe, unavailable source, missing private
  input access represented as a fixture failure, current/stale/unknown/error projection,
  late assessment, exact/probable application identity, bounded replacement, queue age,
  overload, resource-unknown and repeated-day limitations. No real private input is read.
- Circuit-break/outage scenarios inject declared fake states; label them as simulation.
  Do not claim that canned error fixtures prove #111 transport cancellation or a real
  provider outage. Actual timeout/backoff verification remains the existing #111 issue.
- Monitoring limits/cadence come from an explicit synthetic policy. Emit breaches and
  missing limits; do not choose production thresholds. Count the consumer's tool calls,
  read characters/chunks, elapsed simulated time and replacements. Synthetic credits are
  not actual provider money, subscription percentages or price evidence.
- Rehearse turning off local ranking and returning bounded unranked candidates. Preserve
  assessment/batch/application fixture evidence. This is a local fallback rehearsal, not
  rollback of production deployment, schema or services.
- Provide a CLI whose explicit output path receives the synthetic report and private-safe
  observation bundle. No default DB/config discovery, network/provider SDK, Scheduled or
  Telegram calls, automatic issue updates, production writes or runtime activation.

Expected areas: new injected rehearsal driver/CLI, scenario fixtures/tests, and a current
readiness report/checklist. No live consumer integration or deployed tool-schema change.
The operator still completes #94 and eventual parent #115 unattended acceptance.

## Existing #111/#112 repair backlog

The independently reproduced findings are next assignable Luna/max repairs under the
[repair handoff](2026-10-29-preselection-shadow-repair-handoff.md). They do not invalidate
the available provider-free preparation modules:

1. #111: enforce an actual bounded transport/deadline contract and bounded retry backoff;
   do not merely observe expiry after a blocking call returns.
2. #112: bind profile/question/pool/split declarations to verifiable frozen-run/attempt
   provenance rather than accepting any well-shaped digest.
3. #112: admit incomplete/failed extraction outcomes before an assessment attempt exists;
   exercise actual #111 output through the report.
4. #112: distinguish recurring daily-pool membership from stable inference identity.

Source of truth: [#111](https://github.com/drink970082/job-matchbook/issues/111) and
[#112](https://github.com/drink970082/job-matchbook/issues/112). Existing suite at `5f04208`
was independently reproduced at 1,304 passed / 1 skipped, 89.51% coverage; integration
4 passed / 1 skipped. These numbers do not certify new preparatory branches or negate
those defects. Re-run relevant checks on each new head.

## Checks and definition of done

- Worker code: `make test-worker` and worker coverage at the existing 85% floor; targeted
  pure/fixture/CLI and fresh-process forbidden-import/file-access cases as appropriate.
- TS/React: `make test-web` and `make lint`; render the real isolated component. Do not
  claim inventory UI behavior or browser acceptance when the component is not wired.
- Compose only the affected hermetic tiers. PREP115 adds a synthetic executable full-path
  rehearsal; `make test-integration` remains required where cross-service behavior changes.
- Schema/privacy guards and diff checks remain applicable even though schema is untouched.
  Never use a real DB for tests. Report missing dependencies/test infrastructure honestly;
  do not run `db-push` or start runtime services to make a fixture test work.
- Update SPEC (offline capability only, with invariant test references where applicable),
  PROGRESS and CHANGELOG with each implementation commit. Do not document parent live
  integration as shipped. Update the corresponding child issue with real evidence.
- Open focused draft PRs with `--base main`; disclose any stack and new commit range.
  No self-merge/deployment. A passing test suite does not close parent #113/#114/#115.
- Finish with per-issue heads/PRs, commands and observed results, remaining blockers, and
  the next ready ticket. On a gated item, report the exact gate; do not infer permission for unrelated work.

## Human decisions that remain later

Profile content and cross-role priorities; selected inference provider/model/effort;
real label guide/cohort and human workload; recall/miss/YOE false-exclusion tolerances;
actual budgets/prices; production selection allocations/age/replacement policy; reviewed
Prisma persistence/read API; #94 Scheduled access/delivery; #112 decision and eventual
activation scope. None is required to implement the explicit synthetic scopes above.

Principles 2/3/5 preserve facts, opportunity uncertainty and visible failure; 4 preserves
unranked access; 9/11 keep schema/SQLite ownership untouched; 10/12 require injected
services and private-safe fixtures. Rejected alternatives are waiting for GO before any
reusable preparation, and implementing production DB/MCP/scheduling under a fake-only
label. The first wastes independent work; the second bypasses the acceptance gates.
