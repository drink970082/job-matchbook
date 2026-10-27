# Candidate preselection before Daily Brief deep review

**Status:** runtime policy/evaluation remain draft. The scoped offline profile and replay
tooling is implemented on a local draft branch; operator review, live evaluation and any
runtime selection remain separate gates.

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
2. Apply the new explicit required-YOE search policy to evidence-supported JD facts;
   preserve unknowns/valid lower-YOE alternatives and do not reactivate old fit ordering.
   Each retained candidate receives role-family classification and an advisory priority
   assessment against versioned, operator-approved preferences and candidate facts.
3. Persist independent dimensions, evidence/input provenance and priority; do not mutate
   pipeline_status or overwrite legacy fit scores, screenings, source or application state.
4. Build an eligible, deduplicated review pool before allocating deep-read slots. Daily
   Brief fully reads selected original JDs, rechecks applications and source evidence,
   and makes final recommendations; invalid selections can receive bounded replacements.
5. Reserve capacity for low-priority audits and unresolved evidence. Deferred jobs remain
   visible with their age and reason; a retained row never silently disappears.

A daily deep-read target such as 20–30 jobs is a hypothesis, not a cap justified by
measured recall. Measure recall and cost at several budgets before choosing one. If
quality and the requested budget cannot both be met, report the tradeoff.

## Two input variants to compare

- **Direct JEV:** complete stored JD plus the compact, versioned English candidate context
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

Assess each unique content/candidate-profile/rubric/provider/resolved-model version once, with retries explicitly
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

A mechanics/cost pilot can freeze one full day's candidates, capped at 120 unique jobs, and
compare both variants: at most 120 extraction calls and 240 initial JEV calls. A repeated
subset of at most 20 jobs with two additional draws per variant adds at most 80 JEV
calls. Reference-model and human-label workload and monetary/subscription budgets must
be specified separately before authorizing the pilot; these bounds authorize nothing.
Provider/version, model/effort, data sent, and resolved model identity must be explicit.
These are total attempt ceilings, including retries and replacement/repair requests,
not successful-job targets. Reserve retry capacity inside them or stop visibly when
exhausted. A day above 120 requires a declared reproducible sample and coverage report;
it is not a complete-day recall experiment. A larger acceptance campaign needs its own
approved workload, not an automatic extension of this pilot.

Report jointly:
- Worth-reviewing recall at several final deep-read budgets, with labeled-set coverage
  and uncertainty; precision/top-of-list usefulness alone cannot establish low misses.
- Misses by role family, experience level, extraction stage and missing-evidence pattern.
- Low-priority audit results, including randomly sampled confident negative decisions.
- Repeated-draw rank/route stability, input completeness, errors, wall time and total cost
  including extraction, ranking, escalation and final ChatGPT work. Record actual provider
  pricing/rate dates, attempt-level usage/charges and per-job/per-arm/run totals, with
  estimates and unknowns distinguished from billed cost. Compare compact
  profile judgments against richer evidence during adjudication to expose compression misses.

Tune on a development split and accept on held-out labels. Agree the minimum recall and
maximum acceptable missed opportunities before observing the held-out results. Merely
keeping jobs retrievable does not eliminate workflow false negatives. Start with shadow
assessments; promotion to daily selection requires measured acceptance and operator
approval. Keep rollback to unranked candidate retrieval.

## Daily selection contract to settle before runtime implementation

The following are proposed requirements for the decision issue, not deployed behavior.
The decision record must resolve named policy values before dependent work starts.

- Define each run with a UTC half-open interval and cutoff, normally 24 elapsed hours;
  local delivery time and DST do not silently change interval semantics. An interrupted
  run resumes its own batch; a later run reconciles since the last successful cutoff.
- The pool is the union of newly retained candidates, newly completed/current rankings,
  pending deferred work and due retries. Old pending rows remain eligible even with no
  recent timestamp change. Initial historic inventory is a separate, explicitly bounded
  backfill choice; never rank all 3,851 stored candidates implicitly.
- Before slot allocation, exclude confirmed prior applications, explicit manual terminal
  decisions and confirmed closed sources. Preserve reasons/counts without rewriting the
  posting. Unknown source state is not closed. Stale/unknown screening or incomplete JD
  goes to visible unresolved routing, never inherits a current eligibility claim.
- Deduplicate exact source/requisition identities before selection. Cross-source matching
  needs corroborated identity; company/title similarity alone marks a possible duplicate,
  not an exclusion. Preserve all provenance and application records without posting links.
- Define a total deep-read budget K, with explicit ranked, low-rank audit and unresolved
  allocations summing to K. Specify multi-role coverage, deterministic tie breaks and
  unused-slot redistribution. Audit samples use a recorded random seed and known sampling
  probabilities. Include confident low-ranked cases, not only uncertain results.
- Define bounded replacements when post-selection application/source checks invalidate a
  row. Report slots selected, actually read, invalidated and unfilled separately. Tool,
  token/time and monetary ceilings include validation and replacement work; K is not a
  promise that unlimited calls will fill it.
- Define deferred aging, retry due times, maximum waiting-time alert thresholds and what
  happens when arrivals exceed capacity. Age must participate in service allocation;
  displaying age alone does not prevent starvation. No claim that every row is eventually
  read unless a capacity/queue policy actually supports it.
- Use a persisted fixed selection batch (ordered identities plus assessment/input versions)
  for stable pagination and same-batch resume; live score changes cannot reorder its pages.
  Before recommendation, revalidate current content, source and application state. A
  changed row is stale/review-needed, not silently replaced with a different JD version.
- A selection batch records selection, not reading or delivery. Without a consumer
  acknowledgement/delivery ledger, another day's run may repeat selected jobs; do not
  permanently suppress jobs merely because they were offered. Same-run deduplication is
  required. Persistent cross-day reviewed/delivered suppression belongs to #95 or a
  separately approved minimal acknowledgement design; do not add MCP writes implicitly.
  Rollout must either accept measured repetition explicitly or resolve that dependency.

## Assessment identity, failures and isolation

- Identity covers company/title/location/JD, approved candidate facts/preferences,
  extractor/prompt/schema versions where applicable, question/rubric/weight versions,
  provider and resolved model. Changing weights can recombine cached dimensions only
  when their semantics/inputs are unchanged. Missing identity cannot claim cache validity.
- Capture versions before a call and compare them before publishing a current result.
  A delayed old result remains inspectable but cannot overwrite a newer current result.
  Duplicate completion/resume is idempotent. Source/application closure independently
  affects selection even when the content hash has not changed.
- Validate exact question IDs, cardinality, allowed answers, finite score ranges and
  model identity. Missing, duplicated or unknown answers are integrity failures, not
  zero scores or implicit passes. Untrusted JD instructions cannot alter the rubric,
  call tools or obtain private files; send only approved minimized candidate facts.
- Opportunity ambiguity routes to review/defer. Malformed evidence fails visibly per
  item. Authentication/configuration/model mismatch circuits break the batch. Timeouts,
  429 and transient failures use bounded backoff within total attempt/cost/time limits.
  Resume must not reset these counters or duplicate paid calls already recorded complete.
- Partial responses and ambiguous delivery count as spent attempts even if no usable
  score returns. Unknown actual provider cost is reported explicitly and stops further
  calls when the remaining approved budget cannot be established safely.
- Providers and clocks are injected. SQLite writes stay on the owning thread with short
  transactions, WAL and busy timeout; never hold a transaction across network inference.
  Prisma owns any new schema. Default-off isolation and unranked MCP access survive
  missing credentials, provider failures and rollback.

## Evaluation phases and promotion evidence

The 120-row pilot checks mechanics, input coverage, cost and initial failure modes; it
cannot authorize deployment. Runtime acceptance is a separate multi-day campaign.

1. Freeze source/profile versions and a labeling guide before judging variants. Labels
   answer whether the original JD deserves deep review, with positive/negative/unresolved
   evidence and an adjudication process. Labelers are blind to rank/provider output.
2. Compare direct JEV and extraction-plus-JEV against deterministic recency/role-coverage
   selection and the actual current GPT workflow under the same final-review budget.
   Measure end-to-end useful recommendations, misses and total cost, not only cheap scores.
3. Use development and untouched held-out days, grouping duplicate/near-duplicate
   requisitions and shared templates to avoid leakage. Report removed overlaps. Preserve
   complete daily candidate pools for recall@K; do not calculate deployment recall on a
   small randomly split subset with artificially easier competition for K slots.
4. For acceptance, label the full daily pools or predeclare a probability sample with
   inclusion probabilities, weighted estimates and confidence intervals. Top-K plus
   convenience audits cannot establish population recall. Report unresolved labels,
   denominators, positive counts, rare-role coverage and days above the reading budget.
5. Lock thresholds, allocations and the miss tolerance before held-out results. Repeated
   draws include cutoff-near, confident-low, long-JD and hybrid cases; do not select the
   best draw. If intervals/sample size cannot establish the target, report inconclusive,
   not PASS. Include per-field errors and existing applicable hard-invariant gates.
6. Gate promotion on useful-opportunity recall, source/eligibility safety, total resource
   savings and unattended workflow acceptance. Specify monitoring intervals, drift/miss
   triggers and rollback to bounded unranked retrieval; rollback does not delete evidence.

## Candidate input boundary

The [pivot input contract](2026-10-26-candidate-input-package.md) defines a single
English candidate/search profile and its deterministic compact text view. #109 validates
that new profile and its private evidence; it does not require old profile/config or
Registry access. Original evidence and both resume variants remain outside routine JEV
requests. Downstream ChatGPT reads resume variants on demand after full JD review.
Compression correctness, total request tokens and profile-version identity are acceptance
criteria; old scorer prompts, fit tiers and corpus labels are not new-system inputs.

## Scorer ownership and permitted reuse

The [legacy scorer boundary inventory](2026-10-26-legacy-scorer-boundary.md) owns the
file/symbol disposition, target import direction, allowed files per slice and executable
boundary cases. Live screening in score/ is not retired wholesale. Old fit context,
normalization, fallback, seniority ordering, research extractors and quota-based accounting
are retired from the new pivot but kept behind explicit compatibility/manual entrypoints.

#116 extracts the active screen seam and isolates eager legacy imports/resources before
new implementation. It does not select a model, edit screen prompts/verdicts, add YOE or
change production config. #109 may accept this provider-independent prefactor separately;
#110 then implements the new profile/replay path, and #111 the new shadow inference path.
No new code uses load_resumes, old fit_profile or old score schemas as convenient helpers.

## Delivery sequence and assignment gates

Each child issue carries its own acceptance cases and blocking dependencies. No issue
creation grants provider spend, production activation or approval of unresolved design.

1. Orchestrator locks the contracts, candidate-fact source, rubric, provider/model,
   schema ownership, allocations and campaign budgets. Scoped offline-tool approval may
   precede model choice; remaining dependent slices stay blocked explicitly.
2. Luna completes boundary prefactor #116, then builds a provider-free frozen-pool evaluation/replay path, with synthetic fixtures,
   baseline selection, grouped splits, label validation and coverage/cost reports.
3. Luna adds an isolated default-off shadow assessment path with direct/extracted variants,
   identity validation, durable attempt limits and fake-provider failure/resume tests.
4. Orchestrator runs only explicitly authorized pilots/campaigns and records go/no-go.
   A rejected or inconclusive approach stops dependent production implementation.
5. If selected, Luna delivers versioned assessment persistence through read-only MCP and
   UI, with stale-result protection; no live provider activation is implied.
6. Luna delivers bounded daily selection batches through MCP/UI, queue aging, application
   deduplication, replacement accounting and cross-day limitation visibility.
7. Orchestrator accepts unattended shadow operation, monitoring and rollback, then seeks
   the separately scoped runtime activation decision. This does not auto-close #94/#96.

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

## Implementation issue map

Issue bodies own readiness and acceptance; this table records dependency order.
All implementation slices require their scoped design approval first.

| Issue | Owner | Dependencies |
|---|---|---|
| [#109: Lock preselection contracts and scoped implementation gates](https://github.com/drink970082/job-matchbook/issues/109) | Orchestrator | None (planning only) |
| [#116: Isolate active screening from legacy fit imports and prompts](https://github.com/drink970082/job-matchbook/issues/116) | Luna/max | #109 scoped boundary approval |
| [#110: Build an offline preselection evaluation and daily-pool replay path](https://github.com/drink970082/job-matchbook/issues/110) | Luna/max | #109, #116 |
| [#111: Add an isolated bounded JEV shadow assessment workflow](https://github.com/drink970082/job-matchbook/issues/111) | Luna/max | #109, #110, #116 |
| [#112: Evaluate preselection in shadow and record a go/no-go decision](https://github.com/drink970082/job-matchbook/issues/112) | Orchestrator | #109, #110, #111; #94 live gate |
| [#113: Expose versioned preselection assessments through MCP and inventory UI](https://github.com/drink970082/job-matchbook/issues/113) | Luna/max | #109, #112 GO |
| [#114: Deliver bounded daily review batches with deferred-queue coverage](https://github.com/drink970082/job-matchbook/issues/114) | Luna/max | #109, #113 |
| [#115: Accept unattended preselection rollout and bounded rollback](https://github.com/drink970082/job-matchbook/issues/115) | Orchestrator | #112, #113, #114; #94 |

## Primary references

- [JEV primitives](https://docs.typesafe.ai/primitives)
- [Composite scoring](https://docs.typesafe.ai/patterns/composite-scoring)
- [Confidence and domain-specific thresholds](https://docs.typesafe.ai/confidence)
- [Repository evaluation policy](../../EVALUATION.md)
