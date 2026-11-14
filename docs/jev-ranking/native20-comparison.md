# Native20 offline development comparison

**Status:** exposed development model-proxy evidence; no human truth or quality GO.
All 20 native responses are valid and included. The deterministic accepted P0 projection
produces 16 low and 4 medium priorities, with **20/20 needing review**. Fixed P1
selection gives identical ordered selections for JEV and publication order at all three
budgets. This batch supplies no observed selection advantage.

The [blind assessment](native20-blind-proxy.md) was sealed before native responses were
opened. It contains three worth-deep-reading, sixteen not-currently-worth-deep-reading
and one unresolved judgment. These are same-family model proxies, not independent human
reference labels. Neither preferred judgments nor admissible alternatives were changed
after opening responses. Source completeness, current external postings and
requisition/template grouping remain unverified.

## Projection and descriptive agreement

The accepted projection is unchanged: preference unknown → null; weak → low;
strong plus supported relevance → high; other valid vectors → medium. Mixed/unknown
domain, ambiguity review, unknown preference, or absent/unknown relevance trigger review.
Native model: `typesafe/jev-1.13-20260917`.

| Comparison with frozen proxy | Preferred agreement | Including frozen admissible alternatives |
|---|---:|---:|
| Projected tier | 16/20 | 18/20 |
| Primary-duty domain | 15/20 | 19/20 |

Tier cross-tabulation: fourteen low/low, two medium/medium, two proxy-low/native-medium,
one proxy-medium/native-low, and one proxy-null/native-low. The last two accept low as
a frozen admissible alternative. No native high or null appears.

**Tier agreement is not accuracy.** The blind utility guide includes explicit preference
constraints when judging whether a source deserves a deep read. P0's native preference
question asks how primary duties align with target work, and explicitly says not to rank
eligibility or hiring probability. Background relevance is another separate dimension.
A duty-aligned job with an explicit eligibility conflict can therefore receive medium
while the utility proxy says low. The two non-admissible tier disagreements comprise one
such explicit-conflict case and one duty-boundary case involving avoided model training
versus accepted inference/performance engineering. Those mechanisms are analyst
interpretations of source evidence, not native explanations.

Three preferred-domain disagreements assign one declared analysis domain where the proxy
prefers mixed; all three are frozen admissible alternatives. Another assigns a declared
ML domain where the proxy prefers unknown for research beyond the taxonomy; it is also
admissible. The remaining disagreement assigns agentic applications where the proxy
prefers ML engineering, with data engineering also admissible. The taxonomy boundary is
an inspectable development example, not evidence for rewriting domain definitions.

## Fixed P1 selection and utility bounds

The analysis calls only `select_day` and `metrics_for_selection` from the fixed P1 tool.
It does not feed real data through its synthetic-only validator or call these results
synthetic. Domain membership comes from the frozen blind primary-domain labels for both
arms, independently of JEV; native domain agreement above is assessed separately.
Shared SHA-based reserve, lexicographic domain round-robin, tier ordering and stable
publication/ID tie-breaks remain unchanged.

All 20 sources form one exposed development pool grouped by their identical frozen
source creation day, `2026-11-13`. This is not a complete publication-day cohort. All 20
publication values are date-only; UTC midnight represents their dates solely for ordering,
without inventing intraday publication precision. Missing publication values would sort
last. No row is excluded from this comparison or its utility denominators.

Both arms have the following identical results. “Worth” and bounds below refer only to
the frozen development proxy, conditional on the stored sources.

| K/R | Actual reads / unused slots | Worth / not worth / unresolved selected | Proxy precision bounds | Proxy recall bounds | Resolved-only proxy recall |
|---|---:|---:|---:|---:|---:|
| 10/2 | 10 / 0 | 1 / 8 / 1 | 10–20% | 33.33–50% | 1/3 |
| 20/4 | 15 / 5 | 2 / 12 / 1 | 13.33–20% | 66.67–75% | 2/3 |
| 40/8 | 16 / 24 | 2 / 13 / 1 | 12.5–18.75% | 66.67–75% | 2/3 |

At 10/2 both arms miss one proxy-positive general-software source and one proxy-positive
mixed source. At 20/4 and 40/8 they miss the mixed source only. Reserve positive
recoveries are zero at every setting; the unresolved source is selected at every setting.
Unresolved remains in the precision/recall bounds and is never silently made negative.
The nominal feasibility ceiling `min(K,3)/3` is 1 at each setting; it does not incorporate
reserve-only restrictions and must not be confused with achievable selected recall.

K at or above the pool size does **not** mean reading every source: four frozen mixed
and one unknown domain have reserve-only access. At 20/4 none of those five falls in the
reserve; at 40/8 one does. All ordinary queues are exhausted, so higher-budget arm
comparisons are structurally uninformative about ranking order. The missed mixed positive
is a visible protocol access limitation, not a JEV ranking miss. Identical selections at
10/2 are also one narrow, exposed pool, not equivalence evidence for future pools.

Successful response/source/profile/question binding is verified for 20/20 development
rows. This is not production cache coverage or source completeness. Selected review
burden is 10/10, 15/15 and 16/16; whole-pool burden is 20/20. The upstream source-shape
export excluded 7,656 of 10,625 inventory rows; those are not outcome exclusions from
this frozen 20-row comparison and this batch says nothing about their utility.

## Why the review flag needs investigation

Native ambiguity is review for 19/20. The sole ambiguity-clear source has relevance
absent, so the accepted projection still flags it. Review reasons overlap:
`duties_or_signals_unclear` 19, `domain_mixed` 1, `background_evidence_absent` 2.
No threshold or probability override was applied. Native outputs contain choices and
diagnostics, not explanations; their internal reasons cannot be recovered here.

Private inspection of all 20 frozen judgments, their source/profile evidence and native
vectors yields these testable hypotheses:

- **Scope bleed into ambiguity:** explicit preference conflicts, missing commercial terms,
  or background skill gaps may be interpreted as “unresolved contradictions,” even when
  primary duties and domain are clear. The supplied question does not name those cases
  separately. Repeated review on straightforward reporting/software duties motivates this
  hypothesis; it does not prove the model's reasoning.
- **Genuine boundary ambiguity:** several co-primary implementation/analysis jobs and one
  fundamental-research taxonomy gap plausibly need review under P0. Reducing the review
  rate indiscriminately would erase useful distinctions.
- **Weak criterion anchoring:** ambiguity criteria say “None of these ambiguities” and
  “At least one,” leaving the decision boundary in the question text. A scoped restatement
  might improve consistency, but this batch has no blinded ambiguity reference with which
  to establish excess false positives.
- **Preference/relevance confusion:** training paths and transferable engineering can
  receive weak preference despite credible partial background relevance; conversely broad
  ML alignment can hide an avoided duty subtype. These remain separate dimension-level
  questions. Improving aggregate tier agreement is not a sound tuning target.

The minimum next step is a separately frozen, output-blind proxy assessment of the exact
four P0 dimensions, preserving uncertainty and admissible alternatives. Compare that
reference with this unchanged native arm before writing a new question version. No new
native call is part of this report. If the mismatch is confined to treating known
conflicts or ordinary background gaps as duty/domain ambiguity, a narrow restatement of
the already approved ambiguity definition can be evaluated as prompt maintenance, with
all other dimensions/projection fixed. It must not be tuned to force fewer reviews.

Changing priority to incorporate eligibility constraints, redefining utility/domain
boundaries, or changing reserve-only access is a policy fork requiring a concrete human
decision. This comparison neither resolves nor requires implementing those forks.

## Private reproduction and provenance

Private mode-0600 artifact `native20-comparison-v1.json` was created exclusively and must
not be overwritten. It retains all 20 rows, unchanged blind labels/evidence, native
vectors, P0 projections, selected IDs/metrics and source/request/response/result hashes.
The offline script imports no provider or database module and makes no service writes.
Its verification validated 117 private evidence spans against the frozen files, all 20
native responses through the existing parser, and all source/request/response bindings.

| Binding | SHA-256 |
|---|---|
| Private comparison artifact | `cfd1baa5cdbbd86802060a0c42062bf9a5d9076c614410d0389eb042caf8f598` |
| Frozen blind artifact | `a056e1a9f1416f5ce24e202199100c2d72327665d4760efdf6b2f18b3b981e33` |
| Source array | `996f198e4e799a75a648ae25ab3fe261f84bfea03170bf28c3978846e4074327` |
| Profile/domain binding | `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986` |
| Domain manifest | `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c` |
| Question pack | `b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7` |
| Campaign ledger | `2a66b07130e2e5d7d47ff409c0f0259acfd05cf3806fe31d83c338e28ab25d05` |
| Final ledger event | `0d37dc4280d073abebc4afe3b0a4e0a81f9f7d9ea88addda3cb47c36c72afcc0` |

The private artifact additionally binds the complete source roster/export, exact blind
guide/label hashes, native parser, P1 pure-function source, analysis script, campaign
summary and offline request preparation. Accepted projection policy is
`ranking-projection-v1` from P0 `1308f47`. Historical accounting and campaign ledgers are
unchanged. This offline comparison used zero new provider calls, zero new spend and zero
production persistence. Independent human labels, untouched daily pools and live
selection behavior were not verified; P1/P2 acceptance and rollout remain open.
