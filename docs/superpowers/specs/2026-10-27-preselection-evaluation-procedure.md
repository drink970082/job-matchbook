# Preselection evaluation procedure and offline report

**Status:** procedure and report builder prepared; no live evaluation, model call, cost
measurement, threshold selection or GO/NO-GO decision has been made. The checked-in
fixture is synthetic and demonstrates mechanics only. #94 unattended Daily Brief
acceptance remains open. Candidate profile approval and evaluation choices below remain
open.

This document defines a reproducible offline report format for the provider-neutral
preselection experiment. It follows the evaluation phases in the
[preselection design](2026-10-26-fit-preselection-design.md), the private input rules in
the [candidate-input contract](2026-10-26-candidate-input-package.md), and the frozen-pool
contracts in `preselection/replay.py` and `preselection/shadow.py`.

## What the report builder does

`apps/worker/tools/preselection_evaluation.py` accepts two explicitly named local files:

1. An evaluation manifest containing hashed daily-pool and work-item identities, blinded
   labels, same-pool baseline orders, planned draw numbers, assessment values and ranks.
2. The private #111 attempt journal, including all extraction/assessment attempts,
   retries, usage and charge states.

It makes no provider calls, opens no database, reads no profile or résumé, and never
records a promotion decision. It validates the frozen run and matching journal; compares
completed answers with the successful journal payload; and writes aggregate JSON to
stdout. The report omits work-item and group hashes, labels' evidence hashes, answer
values and provider response payloads. It records a canonical evaluation-manifest hash,
input identities and an attempt-journal hash so a private report can be tied back to its
source files.

The fixture under `apps/worker/tests/fixtures/preselection_evaluation.synthetic.json`
uses only fabricated hashes, labels, answers and model identities. Its calculated recall,
cost and stability figures are not evidence about a person, a provider or ATS jobs.

## Gates before any live evaluation

Complete these gates in order. Passing this report's parser or producing synthetic
metrics does not satisfy any gate.

1. **Accept #94 first.** Create the Daily Brief task in ChatGPT web or desktop and
   observe an unattended run. Verify actual task access to the approved private profile
   and relevant résumé files, ATS retrieval and current schema, complete JDs, source and
   freshness evidence, confirmed-application exclusion, probable-duplicate review, visible
   failures and delivery. Interactive MCP access alone is not acceptance. If this workflow
   handles the useful inventory within the agreed review budget, stop the preselection
   experiment; no scorer rollout is needed.
2. **Review the code prerequisites.** #109, #110 and #111 are currently local-only
   commits with no remote PR or independent review. Reconcile the actual remote base,
   obtain review and accept the prerequisite slices before using them for live calls.
3. **Approve the candidate input.** The inspected profile is a private `2.0.1-draft`.
   Confirm the profile contents/version/hash, exact rendered context, résumé-choice guide,
   current required-experience and authorization facts, and unresolved role-family
   priorities. Draft status is not approval.
4. **Approve the labeling protocol.** Freeze the guide and its hash before labeling.
   Labelers see the same compact candidate context and original full JD but no provider,
   arm, rank or answer. Record `positive`, `negative` or `unresolved`, human source and a
   private evidence-packet hash. Human adjudication resolves disagreements; unresolved
   rows remain unresolved and never become negatives. The report accepts human labels
   only when the manifest attests that they were blinded. Do not use model consensus as
   human truth.
5. **Approve the cohort and split.** Freeze complete daily candidate pools, source cutoffs,
   deduplication and shared-template groups. Assign whole daily pools and connected
   duplicate/template groups to development or held-out; a pool or group cannot cross
   splits. Include every candidate competing for that day's budget. The report's
   `pool_id_sha256` identifies one complete daily pool, and ranks and budgets are scoped
   within each pool. If a pool exceeds the proposed 120-job bound, this report has no
   probability-sample weighting contract; do not call its sampled recall population
   recall. Prepare and approve a separate sampling protocol/report first.
6. **Freeze both arms and the policy.** Use the same approved profile/context, original
   JD, question set and candidate facts for direct and extracted JEV. The JD extractor
   sees only the JD and extraction schema. Freeze the extraction and YOE policy, typed
   question set, selection/rank policy, tie-break rule, provider/model/effort identities
   and request limits before development tuning. Do not change weights, ranks, questions
   or exclusion policy after inspecting held-out results.
7. **Approve resource ceilings and prices.** Specify the provider, requested and resolved
   model, allowed data, attempt-level actual/estimate/unknown charge reporting, rate source
   and date, retry reserve, wall-time limit, per-run monetary/subscription limit, and
   separate human-label, adjudication, reference-model and final Daily Brief work. Unknown
   price is not zero. Do not treat token proxies or subscription quota percentages as
   monetary charges.
8. **Set acceptance values before held-out review.** The operator chooses the minimum
   useful-opportunity recall, maximum misses overall and by rare/hybrid role, tolerated
   unresolved-label rate, YOE false-exclusion tolerance, final deep-read budgets and
   handling of confidence intervals. The tool reports metrics and descriptive intervals;
   it does not set these thresholds or decide GO.
9. **Keep deployment as a separate decision.** After accepted held-out evidence, the
   operator records GO, NO-GO or inconclusive and its rationale. A GO only authorizes the
   next explicitly scoped review of #113/#114; it does not itself authorize production
   wiring, MCP/UI exposure, scheduling, database writes or activation.

## Proposed pilot bounds

The design's bounds are proposals, not authorization:

- One complete day's pool, at most 120 unique jobs.
- At most 120 JD-extraction attempts, then at most 240 initial assessment attempts (one
  direct and one extracted assessment per job).
- A repeated subset of at most 20 jobs with two additional draws per arm adds at most 80
  assessment attempts.
- These are attempt ceilings, including retries/repairs, not successful-result quotas.
  Retry capacity must fit inside the total; exhausted limits stop visibly.
- Human labels/adjudication, reference-model work, and final ChatGPT review have separate
  ceilings. A larger campaign needs its own explicit workload and budget approval.

The initial draw must be planned for every item in a complete pool. Later draws may be
planned only for the predeclared repeated subset. Those reports are marked
`predeclared_repeated_subset`, with `population_recall_reportable: false`; recall on that
subset and its Jaccard stability are diagnostics, not full-pool acceptance evidence.

## Manifest contract

Schema `1` is closed: unknown or missing members fail. The top-level object contains
`schema`, `run`, `items`, `baseline_orders` and `assessments`.

`run` contains a run/protocol ID and phase; pool, profile, question-set, label-guide,
split-manifest and attempt-limits SHA-256 identities; split algorithm and seed; a
`labeling_blinded` boolean; selection-policy version; exact direct/extracted and
extractor provider/requested/resolved model identities; variants; global draw numbers;
per-pool final-review budgets; and question `field_ids`. The tool requires both direct
and extracted arms and the matching journal budget identity. Human labels require
`labeling_blinded: true`. For a synthetic-only fixture, `labeling_blinded` is false and
every source is `synthetic_fixture`; the report marks it synthetic.

Each `items` row contains a work-item hash, one daily-pool hash, a private duplicate or
shared-template group ID, split, timezone-aware observation timestamp, planned draw
numbers, positive/negative/unresolved label, human label source, evidence-packet hash,
role families, field-level reference answers and optional required-YOE expected action.
Every item includes the initial draw.
Field answers are limited to finite scalar values or unique string arrays. No job title,
company, URL, JD, candidate text or raw label evidence is accepted.

Each `baseline_orders` row covers one complete pool. `recency` and `role_coverage` are
full orderings of every item in that pool. The validator recomputes both deterministic
orders using the frozen timestamps, role-family coverage and work-item hash tie-break.
An optional `daily_brief` ordering contains
the items selected by the accepted current workflow and may be shorter than the pool.
Supply it for every pool or none. The report compares each ordering at the same
per-pool budgets. Daily Brief resource use is not in the provider journal and must be
reconciled separately; the tool never calls it zero-cost.

Each `assessments` row is unique by work-item, arm and draw. `completed` rows carry a
request-identity hash, a deterministic priority rank and exactly the frozen answer
fields. Values must match the successful journal response. `unresolved` and `failed`
rows carry no rank or answer values and must link to the corresponding journal request.
An absent row is reported as missing; it remains a miss in a full-pool recall denominator.

The attempt journal is loaded through #111's strict schema and file-permission checks.
Every attempt must use the frozen models, work items, arms and draws. Completed and
unresolved assessments must match a journal success or ambiguous delivery as applicable;
an extracted assessment also requires one successful shared extraction. Charges are
reported as actual, estimate or unknown, with rate metadata; unknowns are counted
separately. Shared extraction cost appears once in the extracted arm and once per job in
its private per-work-item distribution, not once per draw.

## Report interpretation

The report contains cohort label coverage and source counts; per-split/pool counts;
recency and role-coverage baseline metrics and optional Daily Brief metrics; and, for each
arm and planned draw:

- Assessment coverage, including completed/unresolved/failed/missing counts.
- Recall, absolute positive misses, Wilson 95% descriptive interval, and precision among
  resolved selected labels at each declared per-pool budget. Unresolved selected labels
  remain visible but do not enter the precision denominator. All unselected label counts
  are shown, separated into ranked beyond budget, unresolved, failed and missing outcomes;
  on a fully labeled pool this accounts for every low-priority item, not only the top-K.
- Role-family recall, per-field answer errors and missing answers, and required-YOE
  action errors/false exclusions.
- Repeated-draw top-budget Jaccard over the predeclared repeated-item overlap. It is
  explicitly not population stability when only a subset was repeated.
- Attempts, retries, elapsed time and token usage; actual/estimated/unknown charges by
  run, arm (including extraction once), successful assessment request, draw, stage and
  private per-work-item distribution. Missing usage, elapsed time or price is never
  substituted with a zero charge.

Wilson intervals are descriptive and unadjusted for grouped daily pools and repeated
draws. The report is not a powered sample-size calculation or an automatic PASS. The
full-pool label report exposes every low-ranked/unselected job and its human label. It
does not implement a separate random audit of a confidence-specific negative state; if
that state is selected as an acceptance check, define and perform its sample blind to arm
and append aggregate findings to the operator's separate decision record. The report's
decision is always `not_recorded`.

The design also calls for comparison to the accepted current GPT workflow. The optional
`daily_brief` order supplies its same-budget selections, but its full retrieval, citations,
failure handling, delivery and resource evidence remain #94 acceptance artifacts and
must be reviewed alongside this report. The deterministic recency and role-coverage
orders are computed offline and have zero provider calls.

## Run the offline report

Keep the input manifest, journal and output in a private local directory. The journal
contains provider response payloads and may contain evidence quotes; do not publish it.
The report command reads only the two explicitly supplied paths and makes no network
calls:

```sh
umask 077
python3 apps/worker/tools/preselection_evaluation.py \
  /private/path/evaluation-input.json \
  --journal /private/path/attempt-journal.json \
  > /private/path/evaluation-report.json
```

Review the report's `cohort.label_evidence_status`, label coverage, per-draw population
scope, baseline identities, model identities, attempt-journal hash and all unknown cost
counts before interpreting it. A parser success proves schema/accounting consistency
only. An incomplete or synthetic report cannot support promotion.
