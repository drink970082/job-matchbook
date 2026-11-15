# Screened60 preference input isolation

Decision: **reject context-isolation candidate; both component outcomes reported**. Same60 exposed development rows; both singleton arms always reported. Only preference was freshly inferred (60 answers per arm). The other three original C answers are reused solely in explicitly labeled HYBRID diagnostic projections. This is not a fresh four-question ranking.

| Singleton arm | Reference agreement | Diagnostics no longer weak | Diagnostic unknown | Weak controls becoming plausible/strong | Component gates |
|---|---|---|---|---|---|
| full | 52/60 | 0/4 | 0 | 0/29 | fail |
| isolated | 51/60 | 1/4 | 0 | 0/29 | fail |

Original C preference reference agreement: 52/60. Unknown does not count as reference agreement. All120 valid and settled; no rows dropped.

| HYBRID diagnostic | Arm | K/R | Paired positive utility bounds versus C |
|---|---|---|---|
| primary_reference_domain | full | 10/2 | [0, 0] |
| primary_reference_domain | full | 20/4 | [0, 0] |
| primary_reference_domain | full | 40/8 | [0, 0] |
| secondary_flat_UI | full | 10/0 | [0, 0] |
| secondary_flat_UI | full | 20/0 | [0, 0] |
| secondary_flat_UI | full | 40/0 | [0, 0] |
| primary_reference_domain | isolated | 10/2 | [1, 1] |
| primary_reference_domain | isolated | 20/4 | [0, 0] |
| primary_reference_domain | isolated | 40/8 | [0, 0] |
| secondary_flat_UI | isolated | 10/0 | [-1, -1] |
| secondary_flat_UI | isolated | 20/0 | [-1, -1] |
| secondary_flat_UI | isolated | 40/0 | [0, 0] |

Preference answer changes versus C: {"full": {"choice_changed": 0, "confidence_changed": 38, "probabilities_changed": 40}, "isolated": {"choice_changed": 5, "confidence_changed": 50, "probabilities_changed": 51}}. Full to isolated changes: {"choice_changed": 5, "confidence_changed": 50, "probabilities_changed": 51}. Unknown weak-control counts: {"full": 0, "isolated": 0}.

The primary comparator retains independent frozen reference domains and the accepted P1v2 selection. Flat UI retains actual creation/numeric-ID order with no reserve or domain queues. Both retain shared bounds for the same four unresolved utility labels.

Full singleton choices exactly match C in this draw; this supplies no singleton/layout repair.
The isolated view changes five choices: two reference-aligned repairs and three regressions,
with only one repair among the four adjudicated misses. Only candidate_context differs
within pairs, but this one exposed draw does not establish internal model reasoning or
general stability. Neither input isolation nor the singleton component passes the gates.

No production GO, runtime promotion, MCP import or next arm follows from this experiment. No provider calls or production writes were made by comparison.

preparation_freeze_sha256: `7883d6c08a04e9719860a074c383b2adadc60dd3ba2a5adea4226e8e340f5d72`.

protocol_sha256: `babedd01ae10ec7239e702a4c196b9380877a30ea8959683d740bcd01c65d1a4`.

control_sha256: `e8d7a9f00bff37b07a5e21833df33f9337a6f4dc14ab42b92b33af737697ba3d`.

derivation_sha256: `c54b35d41c5e3311c85bfb9378c613013eb83b9c0a4f40f41e37a057829f57c7`.

source_sha256: `bc9be04e500195d8bb2cb80522600192d1c90429522d33091c8522889ec50f66`.

approved_full_profile_sha256: `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986`.

derived_context_sha256: `5c64b0b23010239bb56ff6196068b58988af5e6cdeec2e9d520cf4abbbd9414f`.

C_native_manifest_sha256: `8d74adbf101ad5a64566878b0ce3653841b7cebd9e7fe539193b4aedc740f0c9`.

native120_manifest_sha256: `a917a9d9d94ef7bc8e3446986a8214e99af9cfbc8445aad658f1c4234ca38534`.

comparison_wrapper_sha256: `b4bcf385adfcfbbdc0df20d3acdc42fe8ddd29f1469588d6e08209fc6e578d0c`.

Comparison SHA256: `45bd0ffc0db3c0d616fe79a5343f4898bc7170ad71d67e28414fc117321c34f2`.

## Audited transport and disposition

The two-arm campaign settles120/120 native calls in17.844seconds forUSD0.015086988:
full60costUSD0.009676674 andisolated60costUSD0.005410314. All120fresh answers are
preference-only. Full reports230397input/2988output tokens; isolated128817input/2986output.
Each charge equals inputtokens×USD0.000000042; outputtokens have zero price. Limits
are120attempts/USD0.50/1200seconds/32768requestbytes/no retries. The singleton full-context
reservation isUSD0.0132120576 per attempt. No pending/unknown charge remains.

Root verifies all120 exact wires, raw/native responses, arm-qualified identities, contexts,
per-call costs and361ledger events:120reserves,120receipts,120settlements pluscarry.
All16predecessors remain unchanged; linked cumulative2104attempts/USD0.629873860
includes the historical seed. Seventeen fake transport tests and six comparison tests
pass. Proxy/engineering model usage is separate from these native charges.

C remains the development pack. This experiment does not support deleting background/
qualification fields as the repair, and does not justify another field-filtering or
wording iteration on this exposed frame. A source-fact extraction followed by explicit
preference mapping is a different, unexecuted mechanism; no new experiment or production
promotion is inferred from these results. Normal fetch+screen intake is unaffected.

| Transport proof | SHA256 |
|---|---|
| Runner | `da5fbdc242c9f71cf60ef0688ca648cc2f766f86048a35f5cde68dc0fced0413` |
| Global ledger | `e69337653e0a3e7028b12252f5d124f29a5f6a8bc55305fe5b4eb1584d9ef5c5` |
| Final event | `66655a0ffcfd5c811f44f5e7bc7bf0843a87abf0710fbc61407f0576043c0d5c` |
| Root independent settlement audit | `e3eccceb034915630aef4d4f5bd67a61e9f8859a8b24f156dcb4b17d668426d6` |
