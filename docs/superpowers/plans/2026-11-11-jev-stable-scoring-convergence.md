# JEV scoring: bounded convergence and production-readiness plan

**Status:** proposed execution/acceptance plan, prepared at operator request. The operator
has authorized up to USD 10 for JEV research; this is not a production GO, merge or deployment.
Exact execution versions and batch manifests are frozen before inference. No inference
was performed to prepare this plan. Operational behavior below is a target, not shipped.

## Outcome and boundaries

Deliver stable, useful **advisory pre-ranking**, with a compact uncertainty queue and
visible evidence, rather than a perfect predictor or an opaque 0–100 number. Retain every
posting in the inventory. Existing screening, application history and production scorer
remain independently usable. Never auto-apply or turn a low fit score into a hard discard.
An eligibility unknown remains unknown even when fit is high.

Use the existing OpenRouter JEV 1.13 adapter, pinned resolved model, approved candidate
facts and newly confirmed work-context preferences. Do not switch to a latest-model alias,
other provider or paid judge under this budget. Do not buy credits or modify auto top-up.
An unavailable/inadequate pinned model triggers a report, not an automatic model migration.
Source scope for proposed batches is bounded full job descriptions/source metadata from
read-only ATS access; no applications/notes/old scores as truth and no new résumé sources.
Retain private inputs, labels and exact artifacts locally under ignored resume paths.

Principles 2/3/4/5/12/14 apply: separate facts from judgments, retain uncertain opportunities,
keep assistance optional and bounded, expose failure, preserve privacy and record deferrals.
SCORING's measured failures prohibit trusting synthetic probes as quality proof, assuming
numeric confidence is calibrated, tuning the production fit prompt or mixing multiple JDs
in one inference. One request contains one complete job.

## Required isolation from legacy scoring/evaluation

The operator explicitly requires this campaign to remain separate from the old eval and
score modules. Implement new assessment, review-band and evaluation logic only through
the isolated `preselection/` contracts and dedicated tests/tools. Do not import or invoke
legacy `score/`, its Registry/rubric/prompt/rendering helpers, `score_eval.py`,
`seniority_eval.py`, `extract_shadow.py` or their corpus/label loaders. Do not read legacy
score prompts, score_detail or old evaluation outputs as features, labels or expected truth.
Do not change those modules as a shortcut to supporting this experiment.

Extend the existing import/resource boundary tests to cover every new command and runtime
entrypoint. They must execute successfully with legacy imports and legacy prompt/corpus
file reads blocked. Maintain separate versioned inputs, fixtures, cache/journal identities
and reports. Shared source JD identities and pure neutral infrastructure are permissible
only when they introduce no scoring/evaluation dependency. Any legacy baseline comparison
is a separately identified, immutable report/input at the reporting boundary, never an
import of the legacy evaluation engine or a source of truth. Fail the acceptance gate if
the isolated path requires a forbidden module or resource.

## What a score means

Expose four independent dimensions:

1. Evidence-backed eligibility constraints: conflict / unknown / not excluded by known
   evidence; never manufacture a verified pass from silence.
2. Role and qualitative preference tier, including explicit avoided-duty overrides.
3. Demonstrated skill support, with central required skills lacking evidence called out.
4. Daily-duty interest alignment and an explicit unknown state.

Recommend review bands plus the dimensions, rather than a fabricated precision score:
**priority review / consider / low alignment / needs clarification**. A band is a review
suggestion, not exclusion. Candidate facts/preferences come from the versioned profile;
role definitions stay persona-neutral. No unapproved numerical weights between target families.

Use a transparent, versioned selection policy. Obvious dominance can order items sharing
comparable evidence (e.g. same target, better demonstrated relevant skills). Tradeoffs
between stronger preference and weaker skills must be anchored by the operator's batched
pairwise choices, not silently resolved with invented weights. Until anchored, keep such
pairs tied or visibly unresolved; source-time/identity tie-breaking is not a fit verdict.
Separate missing eligibility facts from judgment uncertainty so that unknown sponsorship
alone does not push the entire inventory into an unusable clarification queue.

**Implementation alternatives:** A) clarify the 11 questions/profile only; B) add a small
consistency/selection layer with explicit evidence and uncertainty states (recommended);
C) a new monolithic score prompt/learned weights (defer: opaque, uncalibrated, harder to
locate drift). Phase 0 specifies B before Luna/max implements any production code.
The current research draft is input to that decision, not an approved executable spec.

## Baseline and labeling honesty

The existing ten-job sample has ten native responses, nine live successes plus one
original contract failure recovered offline, and provider-reported cost USD 0.002003148.
All ten have been inspected and some preferences were clarified after viewing outcomes.
They are **development examples**, never a held-out test or proof of accuracy.

Freeze new evaluation judgments before viewing JEV answers. The orchestrator may draft
source-span-supported proxy judgments to reduce operator workload; mark them
`proxy_reviewed`, not human/blind/adjudicated gold. A second independent read can expose
inconsistency but does not eliminate shared-model bias. The operator confirms a small
stratified calibration sample and disputed preference comparisons in one packet. Only
those exact confirmed decisions become `operator_confirmed`. Existing evaluator label
contracts must be extended/reviewed rather than misusing `human_single` for proxy labels.
Unresolved cases stay unresolved and remain in report denominators.

Keep calibration and evaluation label strata separate. Report proxy concordance separately
from agreement with operator-confirmed decisions; no population accuracy claim from proxy
labels. Sample apparently clear cases too, because reviewing only uncertainty would miss
confident errors. Do not convert previous model scores or the new system's own answers
into ground truth.

## Stages, workloads and promotion gates

| Stage | Workload | Required result before promotion |
| --- | --- | --- |
| 0. Freeze and offline contracts | Current 10 examples, 15 synthetic boundary scenarios, profile/rubric/label-guide/selection/budget versions | Valid schemas and unchanged frozen originals; executable contradiction and policy fixtures; reviewed exact implementation scope; no model-quality claim |
| 1. Small convergence | Start 10 real development jobs, add up to 10 only for missing failure types; 3–5 independent draws; at most 3 candidate rubric versions | Two fresh repeat batches on one frozen candidate meet small-stage stability and discrimination gates; every material error has cause/evidence, not an ad hoc company rule |
| 2. Unseen expansion | 40 new grouped jobs, normally 3 draws; after failure, at most two revised candidates with a fresh validation slice | Broad role/negative/unknown coverage; repeated-draw and review-order targets met; no leakage from labels revealed during tuning |
| 3. Locked independent test | 100–150 previously untouched jobs, grouped by day/requisition/template; at least 3 distinct days; 3 draws | Predeclared held-out gates, uncertainty intervals, subgroup counts and error audit; a failed test is not fixed and re-reported as independent PASS |
| 4. Runtime shadow | 3–5 complete daily pools, target 100–200 jobs/day, at most 800 new unique jobs; extra draws on a predeclared sample | Actual daily competition, source roster reconciliation, no lost jobs, cost/resume/fallback checks and useful review ordering under equal deep-read budgets |
| 5. Controlled activation | Frozen release and private rollout preview; staged advisory-only canary | Explicit final GO/activation decision, green relevant CI, rollback verified; no automatic activation because an experiment passed |

Across phases, initial campaign cap is **5,000 inference attempts including repeats,
variants, failures and retries**, and **1,000 newly exported unique full JDs** beyond the
existing ten. Reuse cohort items across required repeat draws without changing groups.
If complete daily pools exceed those limits, choose other complete days or label the
result partial and stop claiming daily recall. No silent truncation to fit a quota.
Use one in-flight call initially, at most 15 minutes per execution segment, at most four
hours of cumulative active provider execution; source collection/waiting/annotation are
reported separately. No unattended recurring schedule is created by this plan.

### Predeclared practical acceptance targets

These are proposed engineering acceptance values, not assertions about measured quality:

- **Integrity and critical contradictions: zero.** Wrong job/model/profile linkage,
  absent required answer, changing frozen content, an acted-upon policy inversion or an
  unhandled logical contradiction blocks that release. Raw answers remain unchanged; an
  inconsistent result is visibly unresolved, not silently repaired into success. A production
  invariant may prevent inconsistent output; report the raw violation rate separately and
  require it to be at most 5% in the locked test. This permits occasional safely intercepted
  model errors rather than demanding a perfect raw model.
- **Small-stage stability:** at least 95% agreement with the modal answer on decision
  fields across fresh draws, zero known primary-versus-avoided or comparable major review
  band reversals. Report raw counts and grouped flips as well as agreement; many easy
  fields must not hide instability in preference/skills. Two batches cannot reuse cache
  hits as repeated model observations.
- **Expanded/held-out stability:** at least 95% pairwise agreement between independent
  draws per decision axis and at most 5% review-band instability; zero material policy
  inversions. Report per-field/per-role denominators, not only an overall average.
- **Discrimination:** at least 85% correct ordering of evidence-supported clear pairs,
  with at least 30 pairs across at least 20 independent job groups in the locked test.
  Report ties/abstentions separately and require at least 70% of those clear pairs to
  receive a justified directional order; do not meet agreement by tying everything.
  Correlated pairs are not independent observations. Operator-confirmed pairs and proxy
  pairs are separate strata; insufficient confirmed evidence yields a scoped, qualified
  result rather than invented human accuracy.
- **Review burden:** decision-relevant unresolved cases at most 20% as an initial usability
  target. Unknown factual fields are reported separately. Never reduce the queue by forcing
  unsupported labels. Exceeding this target calls for narrower scope/better evidence,
  not suppressing uncertainty.
- **Daily retrieval utility:** report operator/proxy-labeled worthwhile items recovered
  at equal K=10/20/40 deep-read budgets against recency and role-coverage baselines, plus
  current ChatGPT workflow on a predeclared manageable slice. K=20 is a measurement point,
  not a fixed recommendation quota. Initial target is at least 90% worthwhile-item recall
  where the pool/budget makes it attainable; report the pool's theoretical budget ceiling,
  compare with the attainable ceiling, and do not demand impossible recall when positives
  exceed K. No material loss versus the current workflow; useful uplift versus at least
  one simple baseline must be evident, not a claim based on mean scores alone.
- **Runtime:** at least 99% interpretable completed assessments on normal input in shadow;
  every failed job remains visible with fallback. Test caps, timeout, duplicate prevention,
  cache invalidation, crash/resume, source-change invalidation and secrets isolation.

Use Wilson/exact binomial intervals where appropriate; use job/group/day clustered
resampling for correlated repeat/pair/ranking observations. Report unresolved and missing
truth coverage, sample selection and all denominators. Thirty examples is not a magic
significance threshold. Zero errors on a small sample does not prove zero risk.

### Preventing biased convergence

- Use development/validation/test groups separated by requisition, near-duplicate/template
  and day; sample both target and avoided/nonengineering roles, hybrids and weak evidence.
- Add hard negatives: prestigious employer but unrelated duties, generic AI branding,
  preferred-only skills, unrelated research/operations, and titles without duties.
- Use matched counterfactuals on a prespecified subset: remove employer prestige/branding,
  reorder equivalent evidence, change incidental identity/name tokens and benign formatting.
  Desired unrelated-invariance tests cannot alter actual job requirements. Report both raw
  differences and changes in review order; do not overclaim fairness across unmeasured groups.
- Test cases where background evidence supports a rare/hybrid path. Consult previously
  approved richer source material only for targeted compression adjudication; new private
  sources need authorization. Missing evidence is never proof of inability.
- Do not use confidence as a calibrated correctness probability or tune one cutoff until it
  looks good. Calibrate any escalation rule on development and confirm it on untouched data.
- At most one coherent change group per experiment, with a written hypothesis, version/hash,
  baseline, expected effect and regression report. Keep a negative-results ledger.
- Three candidate versions without convergence trigger a structural diagnosis; do not keep
  spending on wording churn. One failed locked test permits diagnosis and a new test pool,
  subject to the unchanged budget, not endless testing on the exposed holdout.

## Operator intervention: one compact packet per convergence cycle

The orchestrator resolves evidence/rubric questions first, then groups remaining cases by
root cause. Present **at most ten representative decisions in one packet**, ideally 5–8,
covering repeated preference dilemmas once instead of every job. Include: exact JD excerpt,
approved background evidence, the conflicting proposed decisions, downstream consequence,
recommendation and an accept/avoid/depends or pairwise choice. Include at least three
apparently clear random/stratified cases to detect confident errors, rather than selecting
only model disagreement. If more than ten issues remain, report their count/coverage and
resolve the highest-impact representative categories first; do not silently drop the rest.

Collect clarification on unsolved preference tradeoffs and review capacity in this packet.
User decisions are versioned and applied to future runs; original test artifacts never
change. Pause only work depending on a truly unresolved preference or missing authorization;
continue independent offline investigation. Routine technical choices and already accepted
preferences do not become repeat approval questions.

## USD 10 accounting and stop policy

Treat USD 10 as the **cumulative campaign ceiling including the earlier USD 0.002003148**,
not USD 10 per run/session and not an instruction to consume all funds. Remaining nominal
ceiling is USD 9.997996852. Existing OpenRouter key access is limited to its authorized field;
no other credentials/configuration are read.

| Envelope | Maximum USD |
| --- | ---: |
| Small convergence, including prior spend | 0.50 |
| Unseen expansion | 1.50 |
| Locked independent evaluation | 3.00 |
| Runtime shadow | 2.00 |
| Repairs/repeats across phases | 2.00 |
| Unspent safety reserve | 1.00 |
| Total | 10.00 |

Stop ordinary dispatch at USD 9 including pending conservative reservations; the final
USD 1 is not automatically released for extra experiments. Keep one append-only campaign
ledger above per-run journals, reserve cost before dispatch, atomically record starts and
settlement, and retain original failed/ambiguous records. Concurrent workers/restarts must
not reset count, elapsed or spend. Each segment has a frozen manifest plus campaign linkage.
Retries count against all caps; at most one outer retry only for demonstrably not-delivered
transient requests. Unknown delivery/charge stops new paid calls for reconciliation;
unknown is not zero. Verified provider overcharge versus reserve also stops dispatch.

Before each batch freeze current exact model/rates/currency/unit and documented request
fee basis. Reject model changes, absent rate evidence, request over 24,000 bytes or replies
over the approved bound. Do not truncate context. The observed context-window×question-count
reservation can conservatively cap each request; it is not a byte-to-token estimate.
If new full payloads do not fit, diagnose/review a new bound before sending.

At the ten-job observed mean, one assessment was USD 0.0002003148; 5,000 similar attempts
would be about USD 1.001574. This is a **projection**, not a rate guarantee, account-balance
check or invoice reconciliation. The USD 10/5,000-attempt hard limits, reservations and
batch envelopes govern execution even if model pricing/usage differs. Top-up fees are
outside these inference observations; no credit purchase is authorized here.

Latest public metadata check for selected JEV 1.13 reports resolved model
`typesafe/jev-1.13-20260917`, USD 0.000000042/input token, zero output-token rate and
262,144-token context. The API omits fixed request price; do not treat omission as zero.
OpenRouter's explicit per-request/platform billing documentation supplies separate fee
provenance. Sources: [JEV model metadata](https://openrouter.ai/api/v1/model/typesafe/jev-1.13),
[JEV documentation](https://openrouter.ai/docs/guides/community/jev),
[pricing](https://openrouter.ai/pricing). Metadata must be refreshed/frozen at execution;
model-catalog defaults or new releases do not change this selection.

## Implementation sequence, artifacts and release gate

1. Record exact approved profile additions, draft question choices, invariant set, label
   provenance, acceptance values, source scope and the USD 10 authorization privately.
2. Produce a scoped design/implementation handoff for the global budget ledger,
   evidence/label modes, contradiction reporter and review-band policy. Existing #131/#132/
   #112 acceptance must be explicitly reconciled: proxy-only evidence cannot close the
   old blind-human-label criteria, and sampled pools cannot close completeness criteria.
3. Luna/max implements hermetic changes on an isolated branch with synthetic fixtures;
   orchestrator reviews exact commits. Relevant worker coverage, integration/schema/privacy
   gates and same-commit SPEC/PROGRESS/CHANGELOG apply. No live call bypasses the supervised
   transport merely because the experiment harness lacks a feature.
4. Run stages 1–4 with predeclared evidence and batch intervention; do not rerun unchanged
   successful checks or exhaust unused budget without a measurement question.
5. Present a concrete release candidate: frozen code/model/profile/rubric/policy versions,
   role-level quality/stability/error reports, user-confirmed coverage and unresolved limits,
   observed cost, source freshness, comparison with current workflow, integration tests,
   canary behavior, disable switch and rollback steps.
6. **GO means scoped advisory release readiness**, not auto-deploy. Merge/deploy/production
   activation remain the final operator decision after a reviewable release is prepared.
   If confidence supports only selected role groups, release that documented scope with
   fallback elsewhere. If held-out discrimination/recall is weak or unknowns dominate,
   remain in shadow and report NO-GO/INCONCLUSIVE with the specific residual.

The target is stable, interpretable separation with bounded human effort. Perfection,
zero unknowns, a universal scalar ranking and spending the entire USD 10 are not goals.
