# Dev60 native transport receipt

**Status:** complete; 60/60 native responses validate and settle. This is a development transport measurement, not a quality GO or production rollout.

The epoch sends the frozen 60-source development frame once per source, using the unchanged Arm C pack `ranking-v2-secondary-plausible-v1`, profile and domain bindings. Requested model `typesafe/jev-1.13` resolves to pinned canonical `typesafe/jev-1.13-20260917`. Exact dispatched bodies match all 60 prebuilt bodies, measuring 15,469–25,500 bytes.

The source frame and merged blinded reference labels were sealed before any native POST. The runner verifies the source freeze, exact bodies, merged-reference hash and execution-control hash before dispatch; it never parses reference labels for runner decisions. The fsynced carry event binds these proofs before the first reservation. Each reservation is fsynced before HTTP receives its body. Reference comparison is a separate analysis.

Limits were 60 attempts, USD 0.50 new spend, 1,200 seconds and 32,768 request bytes, with no retries or replacement inputs. Exclusive ledger creation blocks duplicate invocation. Unknown delivery or charge would retain its reservation and stop. No repeated dispatch occurred.

| Measurement | Result |
|---|---:|
| Dispatched / native-valid / settled responses | 60 / 60 / 60 |
| Valid native answers | 240 |
| Pending / unknown / overreserve | 0 / 0 / 0 |
| Provider input / output tokens reported | 277,120 / 15,275 |
| New settled cost | USD 0.011639040 |
| Mean cost per source | USD 0.000193984 |
| Dispatch-loop elapsed time | 9.185 seconds |
| Linked cumulative attempts / settled cost | 1,864 / USD 0.591323404 |

Fresh pre-dispatch metadata was observed at `2026-11-14T19:20:44Z`: 262,144 context tokens, USD 0.000000042/input token and zero output-token price. The API omits request pricing. Request fee zero remains an explicit inference from the [official Jev billing description](https://openrouter.ai/docs/guides/community/jev) and [official pricing FAQ](https://openrouter.ai/pricing), with exact source bodies, URLs and hashes retained privately. Every response's reported charge exactly equals its input-token count multiplied by USD 0.000000042. Output usage is retained despite zero output-token price. The elapsed measurement excludes metadata preflight and credential loading.

The runner conservatively reserves USD 0.0528482304 before each dispatch, using the full model context for all four questions and a 20% margin. It settles only after native model identity/schema, usage and exact decimal cost validate; sequential settlement releases unused reservation. The linked starting carry is 1,804 attempts / USD 0.579684364. All 13 closed predecessor ledgers remain unchanged.

| Projection or native value | Result |
|---|---:|
| Projected LOW / MEDIUM / HIGH priority | 33 / 27 / 0 |
| Overall projected `needs_review` | 20 / 60 |
| Native ambiguity clear / review | 54 / 6 |
| Native preference weak / plausible / strong | 33 / 26 / 1 |

The 20 overall review rows are the union of **13 absent-background-relevance**, **six ambiguity-review** and **seven unknown-domain** reasons. These reason counts overlap and must not be added as distinct rows. Overall deterministic review is separate from the six native ambiguity-review answers. Priority and review arithmetic remain unchanged.

Fourteen injected offline tests passed before execution, including the 60-attempt cap, reservation before HTTP, exact bytes, native validation, missing pricing or fee evidence, budget and elapsed bounds, oversize requests, unknown charge, model mismatch, transport failure, duplicate invocation, and missing or changed reference/control seals before HTTP construction. Post-run independent verification checks all 60 exact requests, all 60 raw native responses / 240 answers, response/result/settlement bindings, the entire 181-event ledger chain and all exact decimal costs. It finds 60 reservations, 60 response receipts and 60 settlements, with no pending, unknown or overreserve. All 13 ancestor hashes and all 60 result-manifest file bindings verify.

This is one draw on an exposed development frame. Native schema validity and agreement with blinded proxy references do not establish held-out quality, accuracy, recall or rollout readiness. Prospective held-out validation remains untouched. This campaign writes private JSON artifacts only and does not import Dev60 results
into prototype tables. The separate test-only recorded-native replay mode remains
available for its explicitly bound20-source campaigns. No production database, schema, service, timer or deployment changes accompany the epoch. The completed epoch refuses another execution; no additional calls are included.

| Frozen proof | SHA256 |
|---|---|
| Source array | `5c00064c61c1d1cffca06bdd086e9022f907b8bfd6682f2e1b4b33805f5f61a9` |
| Source freeze manifest | `904c235ac4eb22e058b51a9d8081ae8d2b9659e4304994667cc429ff7d668868` |
| Merged blinded references | `5882fc912ff1383e962fffa6c9cf979649f3c1a9269c80b5b56774ed868607bd` |
| Unchanged C question pack | `e63c5bf3c55904df22af028775f1c25d4f07d94013a563be85804167b0224109` |
| Runner | `ecea07726dc028a2edac23703a5bf9435ffb3aca2717a3eb30fb23a14dbf8a14` |
| Fake tests | `8077dd6fe4f5521e0805f570a5c2a5ffc323bee15ad46b2b053dfbe975ee980d` |
| Repo native parser | `51a0860d959ac792003cc209d85df34979d7e12bd1b4b95f905d889ceaff0acd` |
| Offline preparation, including all 13 ancestors | `3375e488cf76064f12c38c85238269e8db7cae9be2e0401ecc03d61e217e3b0c` |
| Exact-body preparation receipt | `9ff1435c13cba7d894e756d1d6d981b02324a430b9b415278819aecddc7ccca9` |
| Execution control | `985a584145e699e8142dffdbd53d8c1a4ceb9c9cfb490e075abb360aa4d2f14b` |
| Execution metadata | `fa9325349fb025e17e334fb3682a74cd11f6f525144f98269ce98c9cc49ea693` |
| Parent C ledger | `eaea44645278c609dcf07997557ddab4f4dcbe918bf811e05da4bd29bb24ad89` |
| Parent C final event | `23896682024b4cf00c94c8c75630b01abd18214fd883e37aad70de5b34b725a1` |
| Native60 ledger | `2489c8c8aab0865afc56543a94f5d093975f3de9a778f7fb9f93b337fa9d5af8` |
| Native60 final event | `4d0b2f770347347ff8475b864e24b49e94e5ba707e12120c01693f05efb8d0b5` |
| Native60 summary | `d8f49bdc606a4efc556948d6640ee5797045611163b779404ae8f8df5c337bbf` |
| Native result manifest | `5b945c3d5145c36e0571c9d1733e8a98f1d4b32300a8357264e9bdc938eb95f7` |
| Independent settled verification | `eb087d83f4ba267364cb7a3e110702d217530ccb35be174469cfb7b0a00fe052` |
