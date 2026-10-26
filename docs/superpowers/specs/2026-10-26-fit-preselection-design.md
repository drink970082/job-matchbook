# Candidate preselection before Daily Brief deep review

**Status:** draft — operator review required before implementation or live evaluation

## Objective and scope

Issue #96 reduces the number of full personal-fit investigations performed by the final
ChatGPT workflow. The operator prefers aggressive classification/ranking followed by
thorough reading of selected jobs, and proposes JEV as one ranking option. Do not make
all uncertain jobs automatically consume final-review capacity, or quietly equate
lower priority with a hard eligibility rejection.

The observed 24-hour production window ending 2026-10-26 22:07 UTC contains 205 new
stored postings: 90 rule rejections, 4 standalone screening rejections and 111 retained
candidates. A later read of those 111 candidate bodies totals 522,601 characters. This
is a workload measurement, not a forecast or proof that Scheduled ChatGPT cannot cope.
The manual Daily Brief read five full ATS JDs; actual Scheduled acceptance (#94) remains
open. This design can be reviewed independently; #96 runtime activation remains gated.

## Proposed flow

1. Preserve the existing rule and standalone-screen stages and their separate evidence.
2. Each retained candidate receives role-family classification and an advisory priority
   assessment against versioned, operator-approved preferences and candidate facts.
3. Persist independent dimensions, evidence/input provenance and priority; do not mutate
   pipeline_status or overwrite legacy fit scores, screenings, source or application state.
4. Daily Brief queries a bounded high-priority set and fully reads the original JDs,
   checks applications and source evidence, and makes final recommendations.
5. Reserve capacity for low-priority audits and unresolved evidence. Deferred jobs remain
   visible with their age and reason; a retained row never silently disappears.

A daily deep-read target such as 20–30 jobs is a hypothesis, not a cap justified by
measured recall. Measure recall and cost at several budgets before choosing one. If
quality and the requested budget cannot both be met, report the tradeoff.

## Two input variants to compare

- **Direct JEV:** complete stored JD plus compact, versioned candidate facts/preferences
  are the state. Ask narrow classification and Score questions, then combine dimensions
  in code. This avoids a separate extractor's omission risk and inference cost.
- **Extract then JEV:** a cheap tool-free extractor emits structured duties, required
  versus preferred skills, seniority and constraints, with source spans. Validate quotes
  against the original JD, preserve missing/unknown fields and record coverage problems.
  JEV judges those fields. This may reduce input size and improve auditability, but a
  missing critical sentence is still an error even when every returned quote is valid.

Compare both against identical frozen source/profile versions. Do not adopt extraction
solely because its output is shorter. JEV's typed answers do not replace a free-text
explanation or source-span extractor. If payload limits prevent complete input, record
incomplete coverage and route visibly; do not silently truncate a job into a low score.

## Questions and routing

- Role family: allow multiple plausible target families or an explicit ambiguous/other
  result. A hybrid posting must not be lost because one mutually exclusive label won.
- Independent dimensions: day-to-day work alignment, essential skill overlap and
  transferable skills, seniority/required experience plausibility, and stated target
  preferences. Use ordered descriptive levels, not a request to invent one overall fit
  number. Weights and priority rules are explicit, versioned code.
- Keep material facts separate from fit. Unknown sponsorship is not a refusal, an
  unmentioned skill is not proven absent, and a preferred qualification is not mandatory.
- A low priority means lower deep-review priority, not rule_disqualified or
  screen_disqualified. Never present a score as a probability of being qualified.
- Probability/confidence can route ambiguous cases; confidence is not measured ATS
  accuracy. Calibrate routing with labeled ATS examples and inspect confident mistakes.
- Invalid responses, provider errors and incomplete extraction get no negative verdict.
  Keep a visible retry/review state and preserve basic MCP/Brief access without rankings.
- Deep-review selection combines ranking, role-family coverage, audit sampling and
  bounded unresolved-case capacity. Do not infer quality from employer prestige.

## Persistence and daily retrieval requirements

Assess each unique JD/candidate-profile/rubric/model version once, with retries explicitly
bounded. Cache reuse is by input identity, not posting ID alone. Changed content or
preferences makes the assessment stale, while old evidence stays inspectable. Extraction
and ranking have separate provenance so an error can be located at its actual stage.

MCP must expose advisory components, freshness, rank-update windows and unranked/deferred
coverage. Fetching only jobs created in the last 24 hours must not lose an older job whose
priority assessment completed today. Use actual cutoff instants and overlap/reconciliation;
no exact-once or cross-day-delivery claim without a delivery ledger. Schema and write
ownership require a reviewed Prisma design before implementation.

## Evaluation and proposed bounds — not authorized workload

Before any provider call, define representative, evidence-supported labels for whether a
job deserves deep review, including hybrid/transferable-skill roles, low-ranked positives,
missing sponsorship, incomplete evidence and plausible stretch roles. Strong-model
judgments can assist review but are not independent human truth. Follow EVALUATION;
do not revive unsupported old ID-only labels or the deferred corpus rebuild.

A bounded pilot can freeze one full day's candidates, capped at 120 unique jobs, and
compare both variants: at most 120 extraction calls and 240 initial JEV calls. A repeated
subset of at most 20 jobs with two additional draws per variant adds at most 80 JEV
calls. Reference-model and human-label workload and monetary/subscription budgets must
be specified separately before authorizing the pilot; these bounds authorize nothing.
Provider/version, model/effort, data sent, and resolved model identity must be explicit.

Report jointly:
- Worth-reviewing recall at several final deep-read budgets, with labeled-set coverage
  and uncertainty; precision/top-of-list usefulness alone cannot establish low misses.
- Misses by role family, experience level, extraction stage and missing-evidence pattern.
- Low-priority audit results, including randomly sampled confident negative decisions.
- Repeated-draw rank/route stability, input completeness, errors, wall time and total cost
  including extraction, ranking, escalation and final ChatGPT work.

Tune on a development split and accept on held-out labels. Agree the minimum recall and
maximum acceptable missed opportunities before observing the held-out results. Merely
keeping jobs retrievable does not eliminate workflow false negatives. Start with shadow
assessments; promotion to daily selection requires measured acceptance and operator
approval. Keep rollback to unranked candidate retrieval.

## Principles, alternatives and open decisions

Principles 2/3/5 require facts separate from judgments, opportunity uncertainty preserved
and visible failures. Principle 4 permits cheap assistance without making access depend
on a fit call. Principles 9/10/12 preserve Prisma ownership, injected providers and private
inputs. This design prioritizes fewer strong-model reads while making missed-opportunity
risk observable; it does not claim a free zero-miss reduction.

Rejected: silently selecting top K with no low-rank audit; equating JEV confidence with
ATS recall; replacing screening with aggressive fit rejection; restoring the old numeric
scorer without evaluation; full-database ranking as the first experiment; reusing a
Fantasy adapter's task accuracy or thresholds as ATS evidence.

Open for operator approval: provider and pinned model, input variant, exact rubric and
candidate-fact source, recall/miss tolerance, deep-read allocation, experiment budget and
runtime scheduling. No new API dependency, paid experiment or production mode is enabled.

## Primary references

- [JEV primitives](https://docs.typesafe.ai/primitives)
- [Composite scoring](https://docs.typesafe.ai/patterns/composite-scoring)
- [Confidence and domain-specific thresholds](https://docs.typesafe.ai/confidence)
- [Repository evaluation policy](../../EVALUATION.md)
