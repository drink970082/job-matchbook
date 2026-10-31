# Offline completion and separate evidence acceptance

**Status:** operator-selected task decomposition; offline completion is first priority.
This accepts the work split, not the underlying contracts, merge, private access or live calls.

## Deliverables and dependency order

1. [#130](https://github.com/drink970082/job-matchbook/issues/130): exact-head final
   offline acceptance, scoped #109 decision, explicit #129 merge decision, accepted merge
   verification and #124/#125 supersession. #110/#111/#116 stay open until this evidence
   exists. Do not make those issue closures prerequisites of their own coordinating review.
2. [#131](https://github.com/drink970082/job-matchbook/issues/131): approved real inputs,
   independent source roster/full daily pools, grouping and blind/adjudicated labels.
3. [#132](https://github.com/drink970082/job-matchbook/issues/132): approved provider/model,
   adapter/tokenizer compatibility, actual tokens/prices/usage/charges and bounded pilot.
4. #112: comparable arms/current workflow, held-out quality/cost/stability evaluation,
   predeclared thresholds and an explicit decision. GO is not activation.

#109's scoped offline contract can be accepted without resolving its real product/input
choices. #94/#96 selection gates apply to live measurement, not fabricated offline review.
#113-#115 retain production implementation/rollout scopes. No issue is closed by this plan.

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

## Completion rule

Offline means accepted, merged code and reproducible synthetic demonstrations, not merely
a green branch. #130 records the full criterion audit, exact-head checks and applicability
of E2E; skips are not passes. Review findings are fixed, not transferred to a live ticket.
After explicit accepted merge, revised #110/#111/#116 can close with residual evidence
linked to #131/#132/#112. Keep #124/#125 until explicitly superseded; do not merge their
stale prerequisite stacks. This split by itself promotes or merges no PR.
