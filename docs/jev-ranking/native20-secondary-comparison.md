# Native20 accepted-secondary-work comparison

**Status:** exposed development model-proxy evidence; no human truth, held-out quality
claim or GO. Arm C implements the accepted policy that explicitly acceptable secondary
work receives plausible preference and therefore medium priority. It improves preference
agreement with the newly sealed proxy from **12/20 to 15/20**, with no additional
utility-positive read at the constrained 10-read budget. The accepted unused-budget fill
rule recovers the entire 20-row pool at larger budgets; that is mechanical coverage,
not ranking benefit.

Arm B uses `ranking-v1-ambiguity-clarified-v1`. Arm C uses
`ranking-v2-secondary-plausible-v1`, changing only the preference question and pack
version. Both use the same 20 sources, approved profile, manifest and canonical model
`typesafe/jev-1.13-20260917`. Primary/first-choice duties may be strong; explicitly
acceptable secondary or mixed target duties are plausible. Weak is reserved for avoided
or outside-target duties, with explicit avoidances overriding positive alignment.
Unknown remains available for insufficient duty evidence. Priority arithmetic remains
`ranking-projection-v1`; no numerical domain weights or candidate facts are added.

The [new preference-only proxy](native20-secondary-proxy.md) was frozen before Arm C,
without opening previous native outputs, proxies or comparisons. It assigns zero strong,
nine plausible, ten weak and one unknown. It provides no new domain, relevance,
ambiguity, priority or review reference. Those judgments must not be fabricated by
combining it with old references. The [old utility](native20-comparison.md) and
[old rubric](native20-rubric-comparison.md) artifacts remain separately sealed and
unchanged; their preferred judgments are not new-policy preference truth.

## Preference and deterministic projection

| Frozen new proxy | Arm B weak / plausible | Arm C weak / plausible |
|---|---:|---:|
| Weak (10) | 9 / 1 | 9 / 1 |
| Plausible (9) | 6 / 3 | 3 / 6 |
| Unknown (1) | 1 / 0 | 0 / 1 |

All four native preference changes are weak → plausible. Three move toward the new
proxy, and one remains a disagreement because the proxy is unknown. No previously
agreeing preference becomes disagreeing. Agreement with a same-family model proxy is
not calibrated accuracy or human truth, and the exposed batch cannot establish general
performance.

| Native projection | Arm B | Arm C |
|---|---:|---:|
| High / medium / low / null | 0 / 4 / 16 / 0 | 0 / 8 / 12 / 0 |
| Overall `needs_review` | 7/20 | 5/20 |
| Ambiguity review | 4/20 | 2/20 |

Arm C's five overall review flags comprise two ambiguity-review rows, one additional
mixed-domain row, and two additional absent-background rows. These groups are disjoint
in this batch. Lower review burden is not independently validated as correct: the new
proxy labels preference only. No strong/first-choice example is present in that proxy,
so this run provides no affirmative test of intended strong/high behavior.

## Unchanged question text does not ensure unchanged answers

Every request has identical model/state between B and C. Domain, relevance and ambiguity
question objects are identical on every row. Domain and relevance choices also remain
identical on every row, but **two ambiguity choices change review → clear**. Both coincide
with changed preference, which does not establish a causal dependency. One run per arm
cannot distinguish cross-question coupling from run variability.

Diagnostics below compare the exact native probability maps and confidence numbers.
They remain diagnostics; no probability threshold or override determines priority/review.

| Question | Choice changes | Probability-map changes | Confidence changes | Either diagnostic changed |
|---|---:|---:|---:|---:|
| Domain, unchanged text | 0/20 | 10/20 | 8/20 | 10/20 |
| Relevance, unchanged text | 0/20 | 17/20 | 15/20 | 17/20 |
| Ambiguity, unchanged text | 2/20 | 19/20 | 19/20 | 19/20 |
| Preference, changed text | 4/20 | 18/20 | 18/20 | 18/20 |

The private artifact preserves every answer and diagnostic map, allowing the row-level
changes to be inspected without claiming question independence or deterministic native
behavior.

## Actual fixed-budget comparison with approved P1 fill

This replay calls the fixed P1 pure selector and metric functions with
**`fill_unused_budget=True` explicitly** (`jev-p1-selection-v2`). The common initial
SHA-based reserve remains inside K; ordinary slots use the same domain round-robin.
When ordinary queues leave unused slots, deterministic exploration fills from remaining
rows without expanding K. All three selection arms—publication ordering, native B and
native C—use the original utility-blind independently frozen domains and utility labels.
No new proxy or native domain redefines source eligibility or domain membership.

All 20 sources remain in denominators. They form one exposed development pool grouped
by their common frozen source creation day, `2026-11-13`, not a complete publication-day
cohort. Date-only publication values represent date ordering with no inferred intraday
precision. Missing publication values would sort last. Stored-source completeness and
current external postings remain unverified.

All three arms have the same utility counts and bounds at each budget:

| K/R | Reads / unused slots | Worth / not worth / unresolved selected | Proxy precision bounds | Proxy recall bounds | Resolved-only proxy recall |
|---|---:|---:|---:|---:|---:|
| 10/2 | 10 / 0 | 1 / 8 / 1 | 10–20% | 33.33–50% | 1/3 |
| 20/4 | 20 / 0 | 3 / 16 / 1 | 15–20% | 100–100% | 3/3 |
| 40/8 | 20 / 20 | 3 / 16 / 1 | 15–20% | 100–100% | 3/3 |

At 10/2 Arm B selects the same set as publication ordering. Arm C replaces one selected
source, leaving the utility counts unchanged. Both exchanged sources are original
utility negatives. Every arm still misses one general-software and one mixed-domain
utility positive. At 20/4 and 40/8 every arm reads the full pool, so no utility positive
is missed; ordering can differ without changing this full-pool result. The apparent
100% proxy recall at those budgets is forced by reading all sources and does not prove
ranking quality. The unresolved label remains unresolved in every metric.

The same lane counts apply to all three arms:

| K/R | Initial reserve | Ordinary domain reads | Unused-budget exploration fill |
|---|---:|---:|---:|
| 10/2 | 2 | 8 | 0 |
| 20/4 | 4 | 11 | 5 |
| 40/8 | 8 | 8 | 4 |

Initial-reserve positive recoveries are zero. At 20/4 and 40/8 the additional mixed-domain
positive is recovered through the accepted fill lane. These are distinct mechanisms:
policy v2 restores access to otherwise unread rows; preference wording changes their
native tiers. They must not be credited to each other.

Selected review burden is 5/10, 7/20 and 7/20 for native B; 3/10, 5/20 and 5/20 for
native C. Publication ordering has no intrinsic native review vector: on its selected
rows B flags 5/10, 7/20 and 7/20, while C flags 4/10, 5/20 and 5/20. This separates
changed selection from changed flags. Both native arms have verified successful bindings
for 20/20 development rows, not a claim about production cache coverage or completeness.

## Five residual preference disagreements

All five remain visible privately with exact evidence; none was relabeled after output.
The descriptions below summarize source mechanisms without publishing job/profile text.
Native responses supply no explanations, so these are analyst hypotheses rather than
claims about internal model reasoning.

- **Three proxy-plausible/native-weak cases:** general application development with
  unspecified implementation depth; mixed application/workflow delivery plus reporting;
  and financial application development in a nonpreferred language with an explicit
  training path. Acceptable general engineering does not become avoided solely through
  language, setting or being secondary. The first two have genuine scope uncertainty;
  plausible versus unknown can preserve that uncertainty without inventing an avoidance.
  Background or eligibility leakage is possible but unproved.
- **One proxy-weak/native-plausible case:** primary visual-model training remains
  distinct from the expressly accepted visual-model inference/performance context.
  Broad ML alignment should not erase an explicit primary-duty avoidance. The frozen
  source evidence motivates an avoidance-precedence/evidence-use check; it does not
  authorize a keyword rejection rule.
- **One proxy-unknown/native-plausible case:** generic software duties plus hardware
  integration do not establish either acceptable general implementation or primary
  embedded work confidently enough for the proxy. The reference remains unknown.
  Hardware mention alone cannot justify weak, and no new candidate fact or policy
  decision is necessary to preserve the uncertainty.

The accepted policy resolves the first-choice/secondary distinction; these residuals do
not presently expose a new unavoidable human policy fork. The existing unknown state
handles insufficient scope evidence. The next practical work is to retain the five as
exposed development checks, preserve the accepted C policy and allocation, and verify
behavior on a small independently frozen new source batch before claiming usefulness.
Additional edits aimed only at matching these 20 labels would not resolve capability,
proxy-error or generalization limits. A human decision is needed only if intended duty
avoidances or acceptable work actually change, or unresolved evidence cannot be
represented under the accepted uncertainty policy. This report makes no such change.

## Private artifact and verification

Exclusive mode-0600 artifact:
`apps/worker/resume/pivot/jev-ranking-p3-dev-v1/native20-secondary-comparison.json`.
It retains all 20 new preference-only records, exact B/C answers and diagnostics,
per-row changes, deterministic projections, all three selection arms and lane metrics,
request/response/result hashes, policy and ledger proofs. It must not be overwritten.

Executed private `compare-native20-secondary.py`. Actual verification: **106 new-proxy
evidence spans**, all 40 B/C native responses through the existing parser, both complete
61-event ledger chains with twenty reserves/responses/settlements each, exact request
bindings and unchanged three question objects. All older proxy/comparison seals and
ledger hashes remain unchanged. No provider call, new spend, production write or native
artifact/ledger modification occurred in this offline analysis.

| Binding | SHA-256 |
|---|---|
| New private comparison | `1635884baff05c65e60235f8d90329918156d109b7c325914bcc7931a43e4016` |
| New sealed preference-only proxy | `57d9077ab3f06031c5433531865a997bde1e097c7b22767202a64c637b558071` |
| Arm C question pack | `e63c5bf3c55904df22af028775f1c25d4f07d94013a563be85804167b0224109` |
| Accepted policy record | `d88e779258c74cb1d8d6f59b5bc056641cb40bec1577710404746f81547b38e2` |
| Arm C manifest | `250ce046937234580d5f8460db8b4fe5bf17a915af86a9f9976ecf46778ea605` |
| Arm C ledger | `eaea44645278c609dcf07997557ddab4f4dcbe918bf811e05da4bd29bb24ad89` |
| Arm C final ledger event | `23896682024b4cf00c94c8c75630b01abd18214fd883e37aad70de5b34b725a1` |

The private artifact additionally binds exact source/profile/domain files, predecessor
seals, both arm packs/manifests/preparation/summaries, new proxy policy/record hashes,
analysis script, native parser and actual P1 v2 selector source. Arm C settles twenty
valid responses for **USD 0.003918096**; cumulative accounting is **1,804 attempts /
USD 0.579684364**, zero pending/unknown. One run per arm, same-family proxy labels,
exposed sources and incomplete-source uncertainty limit the conclusions. Independent
human judgment, untouched daily-pool quality and production behavior remain unverified.
