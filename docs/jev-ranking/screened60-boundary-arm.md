# Screened60 preference boundary arm

One predeclared C→D wording experiment on the same60 exposed development rows. Only preference wording/criteria changed; sources, approved profile, model, question types and other three question objects were fixed. All60 must remain valid, settled and proofbound. This selects a development candidate only; it is not final GO or production approval.

Decision: **reject development candidate**. Preference agreement 52/60 → 55/60. Gates: proof_all60=True, overall_preference_agreement=True, four_adjudicated_LOW=False, weak_controls=True, primary_K20=False, flat_UI_K20=False.
Four adjudicated LOW misses: 0/4 no longer weak; 0 unknown. Unknown is reported separately from reference agreement. Weak-control unknowns: 0.

| Analysis | K/R | C positive/negative/unresolved | D positive/negative/unresolved | Paired D−C bounds |
|---|---|---|---|---|
| Primary reference-domain P1 | 10/2 | 4/5/1 | 4/5/1 | [0, 0] |
| Primary reference-domain P1 | 20/4 | 10/8/2 | 9/9/2 | [-1, -1] |
| Primary reference-domain P1 | 40/8 | 16/22/2 | 16/22/2 | [0, 0] |
| Secondary flat UI | 10/0 | 5/5/0 | 4/5/1 | [-1, 0] |
| Secondary flat UI | 20/0 | 10/9/1 | 8/10/2 | [-2, -1] |
| Secondary flat UI | 40/0 | 12/25/3 | 12/26/2 | [-1, 0] |

The additional actual consumer is a NEW COMPOSITION: global HIGH→MEDIUM→LOW, equal-domain round robin within each priority tier, actual UI creation/numeric-ID tie order, shared deterministic reserve and accepted leftover fill. It uses each arm’s native domain mapping. Its changes include arm-dependent allocation and cannot be read as pure priority effects. All three budgets and all comparisons are reported.

| K/R | C actual P/N/U | D actual P/N/U | C actual−C flat | D actual−C flat | D actual−C actual | D actual−D flat |
|---|---|---|---|---|---|---|
| 10/2 | 5/4/1 | 5/4/1 | [0, 1] | [0, 1] | [0, 0] | [1, 1] |
| 20/4 | 8/10/2 | 8/10/2 | [-3, 0] | [-3, 0] | [0, 0] | [-1, 1] |
| 40/8 | 14/23/3 | 14/23/3 | [2, 2] | [2, 2] | [0, 0] | [2, 3] |

Per-question agreement (C→D): domain 43→44/60, preference 52→55/60, relevance 33→34/60, ambiguity 54→53/60.
Projected priorities D: {"low": 33, "medium": 25, "null": 2}; review flags 29→29/60. Both valid preference=unknown results with projected priority=null remain included; nullable priority does not fail the all60 result-proof gate. Same4 unresolved utility labels remain bounded; no rows dropped. Exact selections, lanes, review burden, all native probability/confidence changes and regressions are in the private report.

Frozen acceptance SHA256: `ad4d4e664cb1fe64c24d0b4b84ae0c0642fe26d75b410c2dd3fc0066d603847c`.
Frozen comparison rule SHA256: `37e506ae7897c21ff8bb2c6fc3cf3a1825033d22c4fcbf2deecaf37ee1fb7e20`.
Consumer policy addendum SHA256: `4e4325284afd053f34ed15f4a6b1830cb386067d3a76afea682f02655592bcdb`.
Comparison SHA256: `805324714d08d5c996ab04d6b91bb1cd63279607843d72131483487af85d7318`.
D results manifest SHA256: `e499973a02aa38245276f031979164904719ee96ab78d5d577004030d5f3d9c9`.

No provider calls or production database writes were made by this comparison. No next arm is authorized by these results.

## Transport and retained decision

The bounded native run settles60/60 valid results and240answers forUSD0.012012714
in8.251seconds, with zero pending/unknown charges. Limits are60attempts/USD0.50/
1200seconds/32768requestbytes, no retries. Reported tokens are286017input/15229output;
each cost exactly equals inputtokens×USD0.000000042. The181-event ledger contains
60reservations,60response receipts and60settlements plus carry. All15predecessor
ledgers remain unchanged; linked carry becomes1984attempts/USD0.614786872, including
the historical seed. Proxy/engineering-model usage is separate from these native charges.

Root reran14fake guards, verified all60 wires/native responses/costs and the full
ledger chain, and reran the10comparison tests. An independent runner audit also passes.
No production code, DB, service or current-development marker changes accompany the
experiment. C remains the development pack; the D question pack is rejected. The new
consumer composition is not selected for the primary20-read budget: it returns8known
positives versus Cflat10, with paired bounds[-3,0], rather than a demonstrated gain.
Its K40 benefit does not justify silently increasing the accepted reading budget.

The four unchanged weak readings and both K20 regressions rule out this boundary-wording
patch as a repair. Do not iterate its wording or pick a favorable alternate budget as
a quality pass. Further work needs a separately stated mechanism/hypothesis; these
exposed labels/metrics remain unchanged and provide no productionGO.

| Transport proof | SHA256 |
|---|---|
| D question pack | `f072df9d93cbd015086bca48f46ee33f691578662aafd7f63ab3b0e546d7f01d` |
| Runner | `06b5c156006c4b9d1ecc6953c30b3ce3ca9f015659ed256f8b5c5493e5a1a87f` |
| D ledger | `8b0a6922a59e5669962951d73fcb6d6b736269c2f34a94daf2e68424b01097ed` |
| D final event | `2d6f49cb85a42b2f2ed612488d05ed79c873cf889d21d89f199f5597e9e01d14` |
| Root independent settled verification | `427566172bd75ce8dcf89f3cb4a84b39d0256f1645c6c10515624d77d1680b31` |
| Retained C development marker | `21b19e4e6bfdd8bc2e59f316ee0d42451b02cc933ff6ef5b444abd5fec0434d0` |
