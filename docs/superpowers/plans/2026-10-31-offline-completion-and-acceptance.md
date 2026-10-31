# Offline tooling acceptance and evidence ownership

**Current state:** Provider-free preselection tooling is accepted and merged. PR #129 is
merged as `40842e2993e6e1d791c0f7d91b60a4e1f19dbeec`; the accepted and landed trees both
hash to `0615f8c2c8f97c140a9d1d69f3810b267292a0dd`. Main-branch CI run
[41217912747](https://github.com/drink970082/job-matchbook/actions/runs/41217912747)
passes Worker, Web and E2E. Issues #110/#111/#116 and #130 are closed for their offline
scopes. PRs #124/#125 are closed as superseded. The evidence map below records the live
work that remains with #131/#132/#112; this state grants no private-input or live-call
authorization.

## Evidence ownership and dependency order

1. [#130](https://github.com/drink970082/job-matchbook/issues/130): offline acceptance,
   exact-tree verification and supersession of #124/#125 are complete. The scoped #109
   contract decision and full criterion audit are in the issue record.
2. [#131](https://github.com/drink970082/job-matchbook/issues/131): approved real inputs,
   independent source roster/full daily pools, grouping and blind/adjudicated labels.
3. [#132](https://github.com/drink970082/job-matchbook/issues/132): approved provider/model,
   adapter/tokenizer compatibility, actual tokens/prices/usage/charges and bounded pilot.
4. #112: comparable arms/current workflow, held-out quality/cost/stability evaluation,
   predeclared thresholds and an explicit decision. GO is not activation.

#109's scoped offline contract is accepted; its real product/input choices remain open.
#94/#96 selection gates apply to live measurement, not fabricated offline review.
#113-#115 retain production implementation/rollout scopes. Issue status is recorded in
GitHub; this plan describes evidence ownership only.

## Acceptance responsibility map

Numbering refers to the original mixed criteria; the issue edits retain explicit transfer
notes. Moving evidence does not mark it complete.

| Original responsibility | Offline owner | Remaining real evidence owner |
|---|---|---|
| #110 1-4 boundary, YOE, accounting and profile renderer | #110, accepted under #130 | Actual policy/profile under #109/#131; billed costs #132 |
| #110 5 frozen profile/context, compression and tokens | #110 validates supplied identities/no truncation | #131 approved input/richer evidence; #132 tokenizer/compression measurement |
| #110 6 source payload/manifest | #110 consistency/missing-ID validation | #131 independent roster/completeness |
| #110 7-8 baselines and grouped day splits | #110 deterministic algorithms/fixtures | #131 real policy/grouping/source evidence |
| #110 9 label/adjudication/weights | #110 schema/unknown/denominator handling | #131 human blind labels/adjudication/sampling |
| #110 10 misses/coverage/resources | #110 synthetic reporting and snapshot integrity | #131 representative labels; #132 costs; #112 comparison |
| #110 11-12 edge fixtures/demo | #110 | #131 representative rare/hybrid evidence; #112 accuracy |
| #111 1-4 ownership/isolation/YOE/accounting | #111, accepted under #130 | #131 actual policy/cohort; #132 real pricing |
| #111 5 candidate-context/token coverage | #111 full-payload separation/available usage | #132 selected-provider request tokens |
| #111 6 provider/model/rubric | #111 injected typed identities and declarations | #109 approval; #132 actual provider/adapter/model |
| #111 7-9 answer/extraction/provenance/draws | #111 synthetic validation and frozen bindings | #131 actual inputs; #132 actual measurements |
| #111 10-12 caps/failures/injection/composition | #111 declared synthetic limits and contract tests | #109 budgets; #132 transport/resource evidence; #112 quality |
| #111 13 production isolation | #111 | #113-#115 retain separately gated production work |
| #116 screen/legacy isolation | #116 + scoped #109 + #130 accepted integration | No live policy/provider evidence required |
| #112 all original comparative decision criteria | Offline APIs supplied by #110/#111 | #131/#132 supply evidence; #112 retains decision ownership |

## Acceptance boundary

Offline acceptance consists of merged code, the reproducible synthetic demonstration and
the criterion-level audit under #130. Post-merge Worker, Web and E2E all pass in run
41217912747. Review findings were resolved in the accepted code. Real profile/policy,
source completeness, human labels, provider tokens/prices, model quality and GO remain
with #109/#131/#132/#112. They are not implied by the offline closure, and production
activation remains separately gated.
