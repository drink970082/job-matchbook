# Native20 comparison against the frozen P0 rubric proxy

**Status:** exposed development model-proxy comparison; no human truth, held-out quality
claim or GO. The ambiguity wording clarification improves agreement on this batch while
preserving every native domain, preference, relevance and priority answer. It supports
retaining the clarification for isolated development; it does not establish ranking
usefulness or resolve the remaining dimension disagreements.

Both arms use the same 20 frozen sources, approved profile, domain manifest and canonical
model `typesafe/jev-1.13-20260917`. Arm A is the original question pack. Arm B changes
only the [ambiguity wording](native20-ambiguity-arm.md) and question-pack version to
`ranking-v1-ambiguity-clarified-v1`. Request model/state and the other three question
objects match on every row. **The corresponding three native answers also match on every
row**, beyond merely having equal aggregate counts. The accepted deterministic
`ranking-projection-v1` is unchanged.

The [exact-P0 rubric proxy](native20-rubric-proxy.md) was independently sealed without
opening native Arm A, the original utility labels or their comparison, and before Arm B
ran. It applies the four duty/background dimensions and retains eligibility caveats
separately. It remains a same-family model proxy with correlated-error risk, not human
reference truth. All 20 rows remain in this comparison, with no outcome exclusions.

## Agreement and changes

Agreement is exact equality to the frozen model-proxy judgment, with denominator 20.
These fractions are descriptive agreement, **not accuracy**. The rubric artifact does
not provide per-row admissible alternative vectors; none are invented here.

| Dimension or projection | Arm A agreement | Arm B agreement |
|---|---:|---:|
| Duty-based domain | 14/20 | 14/20 |
| Duty-based preference | 10/20 | 10/20 |
| Background relevance | 7/20 | 7/20 |
| Ambiguity | 5/20 | 16/20 |
| Projected priority | 11/20 | 11/20 |
| Projected `needs_review` | 4/20 | 13/20 |
| Exact sorted review-reason set | 0/20 | 11/20 |
| Complete four-choice vector | 0/20 | 2/20 |

Fifteen ambiguity choices change review → clear; four remain review and one remains
clear. Thirteen flips agree with the proxy and two disagree with it; no other dimension
changes. Overall projected review falls **20/20 → 7/20**, while projected priority
remains sixteen low and four medium on exactly the same rows. The proxy projects ten low,
five medium, four high and one null, with four needing review.

Arm B and the proxy both have sixteen ambiguity-clear and four ambiguity-review choices,
but **the matching counts conceal different rows**:

| Frozen proxy ambiguity | Arm A clear / review | Arm B clear / review |
|---|---:|---:|
| Clear (16) | 1 / 15 | 14 / 2 |
| Review (4) | 0 / 4 | 2 / 2 |

The remaining two proxy-review/native-clear cases concern unresolved primary-duty balance
and a fundamental-research gap in the declared domain vocabulary. The two
proxy-clear/native-review cases describe concrete engineering/solutions work with separate
eligibility caveats. These are evidence-based analyst descriptions of disagreements;
native outputs contain no explanations, so their internal reasons are unknown.

Arm B's seven overall review flags comprise four ambiguity-review rows, one additional
native-mixed-domain row, and two additional native-absent-background rows. These groups
are disjoint in this batch. Five proxy-clear rows therefore still receive projected
review; two proxy-review rows do not. Correctly retaining the independent mixed/absent
triggers explains why four native ambiguity reviews do not mean four overall reviews.
No review flag is suppressed to match a target count.

## Utility remains a separate frozen construct

The [original utility comparison](native20-comparison.md) and its blind labels remain
unchanged. That guide asks which jobs deserve a deep read given the approved search
constraints; the second proxy applies P0's primary-duty alignment and background
relevance dimensions, with eligibility caveats excluded from priority. Neither artifact
relabels or replaces the other.

For example, six original utility-low sources project above low under the duty rubric:
four medium and two high. Conversely two original utility-medium sources project high
under the duty rubric. Those differences show why duty priority cannot be treated as
complete search utility or eligibility clearance. They do not establish which proxy is
human-correct. New domain judgments from the rubric proxy are never substituted into the
original P1 selection experiment.

With original independently frozen domains, labels, reserve and budgets preserved, every
selected ID and its order is unchanged between native arms. Utility-positive reads and
unresolved bounds therefore remain exactly as reported in the original comparison.
Only selected review burden changes:

| K/R | Actual reads | Original utility-positive reads, both arms | Arm A / Arm B selected review flags |
|---|---:|---:|---:|
| 10/2 | 10 | 1 | 10 / 5 |
| 20/4 | 15 | 2 | 15 / 5 |
| 40/8 | 16 | 2 | 16 / 6 |

The one exposed source-created-day development pool is not a complete publication-day
cohort. Date-only publication values retain date ordering without inferred intraday
precision. Mixed/unknown reserve-only access and saturated ordinary queues still limit
the higher-budget comparisons. No allocation rule changes here.

## Interpretation and remaining limits

**A narrow ambiguity maintenance change is supported for further isolated development.**
The clarification restates the approved distinction between uncertainty about job duties
or domain and ordinary background gaps, known eligibility negatives or broad but clear
duties. In this single paired batch it moves thirteen choices toward the presealed rubric
proxy, two away, and leaves the other dimensions unchanged. This is stronger evidence
than simply observing fewer review flags. Preserve the versioned Arm B pack and its
residual disagreements; do not claim a generally fixed ambiguity classifier or rewrite
priority policy from this result. No repeated runs or untouched pools establish stability
or generalization.

The unchanged dimensions expose separate limitations:

- **Preference:** nine weak judgments and one plausible judgment agree. Disagreements
  include all five proxy-strong cases (three native weak, two plausible), three
  proxy-plausible/native-weak cases, one proxy-unknown/native-weak case, and one
  proxy-weak/native-plausible case. Engineering transfer versus a specific avoided duty,
  secondary-family strength, implementation-depth uncertainty and eligibility-scope bleed
  are hypotheses to inspect separately. An ambiguity fix does not repair them.
- **Relevance:** eleven proxy-supported cases remain native partial, and two proxy-partial
  cases remain native absent. The latter have concrete UI implementation evidence in the
  approved background; whether the native answer ignored transfer or required a narrower
  stack match is unknown. The approved rubric asks for credible relevance, not complete
  qualification coverage. The supported/partial boundary still involves judgment about
  which duty-specific gaps are material.
- **Domain:** six disagreements remain, involving engineering versus analysis balance,
  ML versus agentic implementation, and research beyond the declared vocabulary. One
  proxy's exact choice cannot establish the objectively correct boundary.

These observations do not require a new preference policy merely to state P0's existing
scope clearly. A future dimension-specific maintenance experiment can test a precisely
frozen restatement of that scope without changing profile, domains or projection. The
current evidence cannot distinguish a wording problem from native capability limits or
proxy judgment error for every residual. Use the residual evidence to define the next
hypothesis, rather than editing prompts until they reproduce these 20 labels.

A human policy decision is needed if the intended behavior changes—for example making
eligibility constraints determine duty priority, assigning new numeric preferences among
secondary families, redefining domain coverage, or reallocating reserve access. Subjective
transfer cases may benefit from human adjudication, but this model-proxy disagreement is
not itself evidence that those policies should change. Allocation remains untouched.

## Verification and provenance

The exclusive mode-0600 private artifact is
`apps/worker/resume/pivot/jev-ranking-p3-dev-v1/native20-rubric-arm-comparison.json`.
It retains all 20 rubric records, separate original utility labels, both native vectors
and deterministic projections, per-row changes/agreement, exact request/response/result
hashes, ledger proofs and unchanged-selection metrics. It must not be overwritten.

Executed the private `compare-native20-rubric-arms.py` offline script. Actual output:
20 rows retained; **239 rubric evidence substrings verified**; all 40 native responses
validated through the existing parser; both 61-event ledgers hash-chain validated;
20 reserves, responses and settlements per arm; zero unknown or pending. Per-row
model/state and other-three-question invariance passes. Both original proxy seals and the
original comparison artifact remain unchanged. This analysis creates only its new private
script/artifact and public report; it makes no provider call, production write or native
artifact/ledger modification.

| Binding | SHA-256 |
|---|---|
| New private arm comparison | `9a6850b8083d97053027a01c3be59c0c14d6ae9b9e122d2d604d6097346a1e03` |
| Frozen exact-P0 rubric proxy | `6ac37f58e152dd2e5e614b6f56c4cd23e9aefa00eb7b910c0d601a9d2504cec7` |
| Original utility comparison | `cfd1baa5cdbbd86802060a0c42062bf9a5d9076c614410d0389eb042caf8f598` |
| Original utility blind proxy | `a056e1a9f1416f5ce24e202199100c2d72327665d4760efdf6b2f18b3b981e33` |
| Arm B question pack | `0bcbb9eebb28a98959baed4e1fc6776b278c82cc88511100ab86a431d539c978` |
| Arm B manifest | `97a7149e8438232bb700b873bf1cd85f63da15c0a7b081ce09ba9b3e17dd33b5` |
| Arm B campaign ledger | `51a68b6006471d19a9f2341ec937ff4223b1df2409cc59f97b3053c31f5f56d6` |
| Arm B final ledger event | `6f0e05d5b8868ff8ccd7db8e22168585d3e86dffddfb0986a1216754e6c5f108` |

The artifact additionally binds the exact source/profile/domain files, both question
packs, parser, selector, analysis script, proxy guide and record hashes, request
preparation and both campaign summaries. Arm B settled **USD 0.003771096** for twenty
valid responses; reconciled cumulative carry is **1,784 attempts / USD 0.575766268**,
zero pending/unknown. Arm A remains USD 0.003670296. Native delivery/accounting is
verified; independent human judgments, source completeness, held-out selection quality,
model stability and production consumer behavior are not verified by this comparison.
