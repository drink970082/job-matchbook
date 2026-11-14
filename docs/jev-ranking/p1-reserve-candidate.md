# P1 unused-budget candidate

**Status:** accepted; v2 is the default, with explicit legacy-v1 selection available.
This changes consumer selection policy, not API spend or ranking labels. The operator selected v2 for subsequent development and prospective validation.

V1 treats R as a hard exploration maximum: mixed/unknown domain jobs cannot enter
ordinary domain queues, so main-queue exhaustion can leave available K slots unused.
V2 first uses the same seeded initial reserve and ordinary domain allocation, then fills
unused K capacity from the remaining source roster in the same pre-label hash order.
Total reads never exceed K or the pool size; no duplicate IDs. R guarantees initial
exploration rather than limiting all exploration. Initial reserve, ordinary and fallback
reads/review flags are reported separately. No native result or utility label controls
fallback eligibility/order. The CLI, `evaluate` and `select_day` default to v2. `--fill-unused-budget` remains
accepted; select frozen v1 with `--reserve-cap`, `--no-fill-unused-budget` or explicit
`fill_unused_budget=False`. Old frozen experiments retain their original code hash
and must not be silently recomputed under changed defaults.

## Existing development-pool counterfactual

On the same frozen20-row proxy pool, both publication-time and JEV arms give:

| K / R | V1 reads / proxy positives | V2 reads / proxy positives |
|---|---|---|
| 10 / 2 | 10 / 1 | 10 / 1 |
| 20 / 4 | 15 / 2 | 20 / 3 |
| 40 / 8 | 16 / 2 | 20 / 3 |

This demonstrates reserve starvation, not ranking superiority: both arms recover the
same extra proxy-positive job. When K covers the whole pool, full recovery is mechanical.
References are same-family model proxies on exposed development data, never human truth
or held-out recall. The original v1 artifact is preserved and not reinterpreted as v2.

Private counterfactual artifact `native20-reserve-counterfactual-v2.json` SHA256
`52e716a11b4e33fab9235c17c0cfa2e313a91d998e70b2f91d211279e5ae707d`.
It binds the original comparison `cfd1baa5cdbbd86802060a0c42062bf9a5d9076c614410d0389eb042caf8f598`
and exact selector code hash. All20 remain in denominators; no reference/output is edited.

## Verification and decision

12 targeted unit tests pass, including all9original v1 cases with explicit legacy selection plus fallback
budget/deduplication/unknown-pool and label-independent selection regressions. Both CLI
modes execute successfully. The synthetic12-row fixture reads11/12 atK20 andK40 in
v1/v2 respectively; atK40unused slots29/28. No collector, timer, database or API changed.

The accepted v2 policy avoids unused budget while preserving total workload. Legacy v1
remains explicitly reproducible. This policy changes neither approved profile facts nor
JEV questions or the independently frozen collector build.
