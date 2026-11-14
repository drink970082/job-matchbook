# Native20 bounded development trial

**Status:** complete; 20/20 native responses validate, with 19/20 native ambiguity-review answers and 20/20 projected review flags. Transport succeeds; this is not a quality GO or rollout authorization.

The existing frozen 20 development inputs were sent once each to OpenRouter's native System One route. All 80 answers validate against the frozen four-question pack and repo native parser, including the resolved model identity. Exact request bodies are 15,686–22,146 bytes, below the 32,768-byte bound. Source, profile, question and domain bindings remain unchanged. A blind proxy assessment was sealed before dispatch; the runner hashes its seal without parsing its labels. The separate blind comparison remains advisory proxy evidence.

| Measurement | Result |
|---|---:|
| Dispatched / settled / native-valid | 20 / 20 / 20 |
| Pending / unknown / overreserve | 0 / 0 / 0 |
| Provider input / output tokens reported | 87,388 / 5,080 |
| Settled new cost | USD 0.003670296 |
| Mean cost per job | USD 0.0001835148 |
| Runner elapsed time | 2.894 seconds |
| Linked cumulative attempts / settled cost | 1,764 / USD 0.571995172 |

The elapsed measurement covers the bounded dispatch loop, excluding metadata preflight and credential loading. Reported output-token usage is retained even though output-token pricing is zero. Every individual reported cost exactly equals that response's input-token count multiplied by USD 0.000000042.

| Native question | Aggregate values |
|---|---|
| Domain | analysis/decision support 9; general software engineering 6; agentic LLM applications 2; ML engineering 2; mixed 1 |
| Preference | weak 16; plausible 4 |
| Relevance | partial 17; absent 2; supported 1 |
| Ambiguity | review 19; clear 1 |

The independent P0 projection flags all 20: 19 ambiguity-review answers plus absent
background evidence on the sole ambiguity-clear answer. The native ambiguity answer alone marks 19 rows for review. The remaining row has `ambiguity=clear` but `relevance=absent`, which independently triggers the unchanged deterministic projection; overall projected `needs_review` is therefore 20/20. These counts are observed outputs, not acceptance thresholds or evidence of reliable decision quality. These are development rows with one draw each. Native schema validity and a sealed proxy comparison cannot establish held-out quality, accuracy, recall or rollout readiness.

Fresh pre-dispatch metadata, observed `2026-11-14T02:23:23Z`, resolves requested `typesafe/jev-1.13` to `typesafe/jev-1.13-20260917`: 262,144 context tokens, USD 0.000000042/input token, zero output-token price. The metadata omits a request-price field. Request fee zero is an explicit inference from the [official Jev billing description](https://openrouter.ai/docs/guides/community/jev) and [official pricing FAQ](https://openrouter.ai/pricing), which specify input-token billing and platform fees on credit purchases, never individual requests. Exact source bodies, URLs and hashes remain private.

The runner durably reserved USD 0.0528482304 before each dispatch: full context for each of four questions, input and output rates, plus 20% margin. Settlement occurred only after native identity/schema, usage and cost validation; sequential settlement released unused reservation. Limits were 20 attempts, USD 0.50 new spend, 1,200 seconds and no retries or replacement inputs. The runner has a total elapsed-time watchdog. Its fixed exclusive ledger prevents another invocation from dispatching duplicates; uncertain delivery or charge would retain the reservation and stop. The ten predecessor ledgers remain unchanged, preserving their 1,744 attempts / USD 0.568324876 carry and zero pending or unknown.

Ten injected offline tests pass, covering valid native output and exact wire bytes, durable reservation before HTTP, missing pricing or fee evidence, budget, elapsed bound, oversized request, unknown charge, duplicate invocation, model mismatch and transport failure. Post-run offline verification revalidated all 20 frozen requests, all 20 responses and 80 answers, each response/result/settlement hash binding, the ledger event chain, exact decimal costs and all ten ancestor hashes. It found 20 reserves, 20 response receipts, 20 settlements, no pending or unknown reservations, and no overreserve.

Reproduce the fake checks with the existing private runner directory and `/tmp/ats-jev-p3-venv/bin/python -m pytest test_native20.py -q`. Running `run_native20.py` without arguments performs metadata-only preflight. The completed `--execute` invocation must not be repeated; its duplicate guard now refuses dispatch. Native results remain private JSON artifacts. Default RankingStore remains fake-only; a separately enabled offline native-replay mode
uses only new temporary fixture databases. Production database, schema, services, timers
and deployment are unchanged.

| Proof | SHA256 |
|---|---|
| Runner | `90d917dde44485e9d23745c3e1f0e61f324d9c29a74f2add55e6e15589445f7b` |
| Fake tests | `7abe4dcb8175f29452adabaf77e2d838d35937ec177ee9269320d2a4e4aa3ce9` |
| Repo native parser | `51a0860d959ac792003cc209d85df34979d7e12bd1b4b95f905d889ceaff0acd` |
| Frozen source array | `996f198e4e799a75a648ae25ab3fe261f84bfea03170bf28c3978846e4074327` |
| Profile binding | `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986` |
| Question pack | `b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7` |
| Domain manifest | `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c` |
| Offline preparation | `367beef9b9da05f22db9d3fdd3705bcb66ac2558f78af2851ff202e4f87669af` |
| Blind proxy seal | `a056e1a9f1416f5ce24e202199100c2d72327665d4760efdf6b2f18b3b981e33` |
| Model metadata body | `240340cb91843314ed7e02abafb62da16c12b6afa7473ff00daca3eed83fd850` |
| Official Jev billing body | `1818f19e63cbde6492fe49b73a6bc306b2e42337ac174e4fa1ed18d6db109ef6` |
| Official pricing body | `5351e9056493ed694a62b648463a558d0aff6f82319db03452403422eda8ab00` |
| Native20 ledger | `2a66b07130e2e5d7d47ff409c0f0259acfd05cf3806fe31d83c338e28ab25d05` |
| Final ledger event | `0d37dc4280d073abebc4afe3b0a4e0a81f9f7d9ea88addda3cb47c36c72afcc0` |
