# JEV ranking research and launch gates

**Status:** approved research planning baseline; no new inference authorized.
See [design](design.md) and [delivery](delivery.md). Numerical values below are proposed
pre-registration defaults, not measured results or automatic launch approval.

## 1. Question and baselines

Does one-request JEV ranking put useful jobs earlier for ChatGPT under a fixed reading
budget, without hiding important opportunities or expanding total work through review?

A: compare one-request domain/tier ranking against publication-time ordering over the same
inventory and domain allocation. Both see identical source eligibility and deduplication.
B: only after a diagnosed failure in A, change one factor (rubric, guard, selected-skill
support, or input rendering). Complexity must buy measured benefit after extra cost and
review load. No compulsory extracted/Haiku/dual-guard arm.
C: exercise the actual MCP-to-ChatGPT workflow with fixed reading budgets, record useful
shortlist output, details opened, elapsed work, uncertainty and missing opportunities.
An interactive pass does not establish unattended Daily Brief delivery.

Existing repeated-answer reports are regression evidence, not ranking-quality acceptance.
Do not relabel model agreement as accuracy or assume stability means semantic correctness.

## 2. Preparation without provider calls

Sol owns the exact rubric, native question pack, deterministic projection, domain vocabulary,
source eligibility, tie-breaks and review policy. Freeze before inspecting new JEV outputs.
Luna can assemble manifests and metric tools once contracts are fixed. Use existing approved
profile/background; do not add skills, years or résumé sources. Missing approved artifacts
are a preparation blocker, not an invitation to reconstruct them from old score outputs.

Measure complete serialized request bytes, input composition and expected operational volume
offline. Establish actual provider/tokenizer/rate evidence separately before live dispatch.
Do not confuse character approximations with tokens or documented prices with billed usage.
No credentials are needed for dataset inspection, synthetic tests or interface design.

## 3. Cohorts and reference judgments

Use historical exposed sources for development and regressions only. Freeze at least three
complete, untouched daily windows for held-out comparison as the provisional study design;
Sol sizes the workload before approval. Avoid outcome-selected replacement of failed or long
inputs. Independently reconcile source roster and stored JD counts; disclose fetch gaps.
Keep duplicate/requisition/template groups together across development and held-out splits.
Company overlap and near duplicates must be reported, not silently called independent data.

For the studied pools, Sol blind-reads inputs without JEV outputs and records a proxy label:
worth deep reading / not currently worth deep reading / unresolved, with supporting source
references. Freeze preferred tier and admissible alternatives before comparison. A second
review may adjudicate material differences; disclose same-family correlation and unresolved
cases. These remain MODEL PROXIES, never human gold. Subscription usage requires its own
bounded assignment. No mandatory twenty-question human sheet; ask the operator only about
a material preference ambiguity that affects the policy, not every ordinary disagreement.

A complete-pool ranking metric requires reference coverage beyond the selected top list.
If complete labeling is infeasible, predeclare a probability sample and weights; do not
report population recall from a convenience sample. Show unresolved-label bounds separately.
Any test set used for tuning becomes development data. Use a fresh held-out window for a
revised quality claim. Do not spend repeatedly until a preferred result appears.

## 4. Fixed-budget measurements

Provisional total unique deep-read budget K=20/day, with sensitivity at K=10 and K=40.
Predeclare domain allocation before results (equal allocation absent an approved alternative,
redistributing unused slots deterministically). Both arms use the SAME allocation.
Within total K, reserve R=4 at K=20 for review/unranked exploration (R=2/8 at K=10/40).
This is not K plus unlimited review. Report main-lane and reserve-lane results separately.
Freeze exploration selection without seeing labels; use stable seeded sampling or a declared
age-based rule. Deduplicate across domains/lanes before counting consumed slots.

- Precision@K = reference-positive unique jobs selected / actual unique jobs read. Report
  denominator when fewer than K are available and positive/unresolved composition.
- Recall@K = selected reference-positive jobs / all reference-positive jobs in the eligible
  pool. Report undefined if no positives, not 100%. Also report count missed by domain.
- Review burden = review-flagged fraction of pool and fraction of budget consumed; enumerate
  positive jobs recovered through reserve slots. Unlimited review never satisfies recall.
- Ranking coverage = current successful bindings / declared assessable full-JD inputs;
  separately disclose every excluded/deferred/unassessable source and whole-inventory coverage.
- Cost = all observed rank/retry/failure/extra-model charges plus consumer work where measurable;
  distinguish estimates, subscription consumption and unknowns. Report per-job, per-day,
  successful-result and complete-workflow totals with source dates.
- Stability = small predeclared repeat subset, top-list/tier changes and important misses;
  not probability-number jitter or automatic whole-pool duplicate calls.

Use paired per-day comparisons and grouped uncertainty estimates where data permits.
Three windows cannot establish universal reliability; show small-sample limitations.
A 90% recall target may be impossible when positives exceed K: report the ceiling K/P,
then return a budget/scope decision, never redefine positives after seeing output.

## 5. Provisional acceptance matrix

Before spending, Sol proposes exact locked thresholds, time/cost caps and sample size for
operator/orchestrator review. Do not silently turn these planning defaults into a GO result.

| Gate | Proposed test and evidence |
|---|---|
| Ranking benefit | P@K above time ordering in aggregate with per-day differences for >=3 untouched windows; disclose every regression |
| Opportunity recovery | >=90% proxy-positive recovery within TOTAL K including R; show feasibility ceiling and unresolved-label bounds |
| Review load | Fixed R inside K; report overflow, do not treat flagged jobs as already reviewed |
| Operational coverage | >=99% of declared assessable inputs ranked within frozen window; all other inputs have explicit visible states |
| Integrity | No wrong-job success, stale-as-current result or invalid enum persistence in adversarial contract tests |
| Consumer | Stable pagination, full-JD access, reconcilable coverage and low/unranked access demonstrated through real tool path |
| Economics | Within separately approved per-day/run money, attempt and elapsed caps; costs include failures and retry |
| Recovery | Disabling new ranking restores source browsing; latest-success/attempt semantics survive failure and restart |

Mechanical integrity is a hard gate, not statistical accuracy. Proxy-backed quality results
can justify a LIMITED TRIAL only. Full rollout additionally needs observed usefulness in the
actual operator workflow and a separately approved operating budget/schedule. Human labels
are not required to run this track, but absence of human ground truth limits claims.

## 6. Failure-driven decisions and stop rules

| Observation | Next action, not automatic implementation |
|---|---|
| No advantage over time ordering | Inspect false-high/false-low cases and input quality; propose one falsifiable change or NO-GO |
| Stable wrong preference | Check rubric interpretation; repeats do not fix meaning |
| Missing JD content | Repair source acquisition separately; don't tune ranker to invented facts |
| Missing profile evidence | Keep uncertainty; only operator can add background facts |
| Too many ties | Measure utility loss before testing within-domain finer score |
| Too much review | Diagnose ambiguity and capacity; don't hide review by coercing low tiers |
| Long requests blocked locally | Test evidence-based higher bound first; no generic split framework |
| Provider/config/budget failure | Stop dispatch as specified; no model switch, cap increase or new epoch without authorization |
| Held-out failure after tuning | Record failure, retire holdout for future tuning claims; no silent extra trials |

Each authorized campaign has a frozen maximum attempts, money, wall time, repeats, provider,
model, input/profile/question hashes and retry policy. A failed campaign does not authorize
another. Preserve existing ledgers/epochs. Do not spend solely to revalidate refactoring.

## 7. Required report and decision

Deliver a privacy-safe summary plus local artifact manifest: cohort counts/exclusions,
versions, baseline and JEV metrics by day/domain, important misses, review burden, costs,
coverage failures, limitations and disposition. No private JDs/profile snippets in public
issues. Decision is NO-GO, INCONCLUSIVE, or LIMITED-TRIAL-CANDIDATE. A later rollout decision
must name exact model/rubric/build, budget, schedule, canary scope, rollback trigger and
operator approval. Tests passing or available budget cannot substitute for that decision.
