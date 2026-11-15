# Dev60 comparison against publication ordering

**Disposition: INCONCLUSIVE development evidence. Do not advance to production.**
Native C produces no additional utility-positive reads over publication ordering at
K=10, 20 or 40 in this frozen pool. The positive identities differ, but gains and losses
cancel at every budget. These are exposed development sources and a blind model-proxy
reference, not human truth, held-out validation or population estimates. Prospective
validation remains pending; this single pool cannot satisfy a three-window gate.

The [source frame](dev60-frame.md) remains unchanged. All 60 sources remain in the
denominators: 15 reference utility positives, 44 negatives and one unresolved. The
reference was sealed before native dispatch. Neither labels nor outcomes changed source
selection, the accepted C pack, profile, domains or priority projection.

## Fixed comparison and utility

Both arms use the accepted P1 `jev-p1-selection-v2` pure selector from
`/tmp/ats-jev-p1/tools/jev_p1_evaluation.py`, explicitly setting
`fill_unused_budget=True`. They share independently frozen reference-domain allocation,
sorted domain round-robin and the same SHA-based initial reserve inside K, with
`EXPLORATION_PREFIX=jev-p1-exploration-v1` and K/R=10/2, 20/4, 40/8. One common pool
is tagged `2026-11-14`, the export-cutoff date, solely to seed selection; it is not a
source-created or publication-day cohort. Real rows pass only through the pure selection
and metric functions, never through the utility's synthetic-input validator.

Publication ordering uses stored publication date/time descending, missing last, then
stable string job ID. Date-only values represent date ordering at UTC midnight without
inventing publication-time precision. Native ordering adds HIGH/MEDIUM/LOW/null priority
before that same date/ID ordering within each reference-domain queue. Review flags do
not affect selection. Unused-budget fill is enabled but is not needed at these budgets.

Both arms have these counts and bounds:

| K/R | Positive / negative / unresolved reads | Precision bounds | Recall bounds over this pool | Resolved-positive recovery |
|---|---|---|---|---|
| 10/2 | 4 / 6 / 0 | 40–40% | 25–26.7% | 4/15, 26.7% |
| 20/4 | 7 / 12 / 1 | 35–40% | 46.7–50% | 7/15, 46.7% |
| 40/8 | 14 / 25 / 1 | 35–37.5% | 93.3–93.75% | 14/15, 93.3% |

Unresolved utility is never treated as negative. Paired positive-read delta bounds use
the same unresolved identity in both arms: **[0, 0] at every budget**. Each budget gains
one positive and loses one different positive versus publication ordering. Total
exchanges in each direction are one, three and two rows respectively. These are equal
counts, not identical selected sets. At K=20 the 46.7% resolved-positive recovery falls
well below the 90% goal, although the budget's arithmetic ceiling is 100%.

Reserve / ordinary / fill reads are 2/8/0, 4/16/0 and 8/32/0. The common initial reserve
recovers one, two and three positives respectively. Native-review annotations on the
selected publication/native sets are 2/1, 2/2 and 7/5. Publication ordering has no native
review flags of its own; these counts annotate both selected sets with the same native
diagnostics and do not establish human-review time saved.

## Assessment differences and limited diagnosis

| Dimension | Exact reference/native agreement |
|---|---:|
| Domain | 52/60 |
| Preference | 46/60 |
| Relevance | 38/60 |
| Ambiguity | 54/60 |
| Projected priority | 47/60 |
| Projected review flag | 52/60 |

Native priorities are 33 LOW, 27 MEDIUM and zero HIGH, versus reference 29 LOW,
28 MEDIUM and three HIGH. Native projection flags 20 rows for review versus 14 in the
reference. Native reasons, which overlap, are absent background evidence on 13,
unclear duties/signals on six and unknown domain on seven. Reference reasons are
absent background evidence on eight and unknown domain on 13. The six native ambiguity
reviews disagree with the all-clear reference; this is disagreement, not measured false
positives against human truth.

Eight domain choices differ: six reference-unknown rows receive named native domains,
and two reference general-software rows receive AI-infrastructure or ML-engineering
domains. Both comparison arms retain the frozen reference domains, so these native
domain changes do not alter their allocation.

The 27 MEDIUM rows contain 11 utility positives, 15 negatives and one unresolved.
Twenty-five also have partial relevance: 24 plausible+partial and one strong+partial.
The remaining two are plausible+supported and therefore still MEDIUM. These diagnostics
do not break priority ties; publication date/ID decides order inside each domain queue.

At K=10 the native arm misses 11 positives: seven MEDIUM and four LOW. At K=20 it misses
eight: four MEDIUM and four LOW. Three and two of those missed MEDIUM rows respectively
have a selected utility-negative row ahead in the same priority/domain queue. This is a
measured tie-order obstruction; domain allocation also limits reads. It does not prove
that utility-negative rows should have lower duty priority. All 15 MEDIUM utility
negatives have explicit search constraints recorded in the frozen reference, sometimes
alongside avoided duties. Native duty preference/background relevance are separate from
eligibility and hiring probability.

Relevance is conservative relative to the proxy: 15 of its 17 supported rows become
partial; native returns two supported, 45 partial and 13 absent. All three reference
strong+supported rows become plausible+partial. However, those three reference HIGH rows
are utility negatives, while every utility positive has reference plausible preference.
Changing relevance alone would not promote those positives under the accepted arithmetic.
The absence of HIGH is therefore not a sufficient explanation for low utility recovery.

One utility-positive source is lost against the baseline at all three budgets; native
assigns it a different domain, weak preference and absent relevance. Other low-positive
disagreements concern mixed trading/tool-building or implementation/reporting duties.
The private diagnosis preserves exact source/profile evidence and per-positive queue
positions. It cannot reveal the model's internal reasoning. Whether supporting
implementation makes a primary duty mix acceptable can require a real preference-boundary
decision; missing specialist background must remain separate from a duty avoidance.

The narrow next action is to adjudicate these private disagreements and check how the
consumer applies already-approved eligibility constraints and reading budgets. Preserve
the current labels/pack while doing so. A finer score, new wording arm or broader
preference rule does not follow automatically from this result. This experiment shows
no utility benefit at the tested budgets and supplies no production GO.

## Reproducible private evidence

Private package: `apps/worker/resume/pivot/jev-ranking-dev60-v1/` under the operator's
main checkout. `compare_dev60.py`, `comparison-rule.json`, `comparison.json`,
`diagnose_dev60.py` and `diagnosis.json` retain the fixed protocol, all 60 row comparisons,
native diagnostics, selections, bounds and private evidence. Output creation is exclusive,
0600 and fsynced. Existing source/reference/pack and provider ledgers are untouched.

After the runner's settled audit, the comparison verifies the sealed native manifest,
summary, all 60 result/request/response hashes, strict native identity/schema, exact
frozen request bytes, source/profile/domain/pack bindings and per-response/total costs.
It checks 60/60 valid and settled, zero pending reservation/unknown. It compares ledger
hash/final-event attestations in the runner proof and summary but does not open or
independently reverify the ledger. No new native call occurs here.

Actual verification: `python3 .../test_compare_dev60.py` reports **7 tests passed**,
covering 60-row budget/selector integration, shared reserve, observable ranking effects,
unknown-domain fill, shared-unresolved paired bounds, changed input/proof seals and
priority/review arithmetic. `python3 .../compare_dev60.py --native-manifest-sha256
5b945c3d5145c36e0571c9d1733e8a98f1d4b32300a8357264e9bdc938eb95f7`
runs once and writes the comparison; `python3 .../diagnose_dev60.py` writes the
descriptive audit. Source availability, human label validity, prospective stability and
production behavior are not verified by these offline checks.

| Proof | SHA256 |
|---|---|
| Frozen reference labels | `5882fc912ff1383e962fffa6c9cf979649f3c1a9269c80b5b56774ed868607bd` |
| Comparison rule | `90fa6dfaa236d1005885e379df09200c3de8998766141ea1aeeb6c02af3e67c8` |
| Settled native result manifest | `5b945c3d5145c36e0571c9d1733e8a98f1d4b32300a8357264e9bdc938eb95f7` |
| Comparison script | `ac8f5f629204317361c1da2407218fb613a2abc8eb1b9058238ec1ace0283f8b` |
| Comparison tests | `bf796fdb81965b91dc7a6cd5c02f9890dce3d3e96579e7869b0680dfe6b97832` |
| Comparison artifact | `78f1fde03ec5d35ed4ff1f690bd297a7d7d5da94886efe35bf2b3a71b28cdfb3` |
| Private diagnosis | `21e603f97c374580a22dbd0a7be0152933619dbbc3aaa88df1fdee65e1174729` |

## Narrow private adjudication addendum

Full-source review of the four utility-positive native-LOW rows supports
plausible+partial, hence MEDIUM, under the existing approved policy in all four cases.
This is an advisory interpretation, not replacement reference truth. The source lost
against publication ordering at every budget describes software implementation;
specialist-domain gaps do not establish avoided duties or absent background relevance.
One other case combines explicit implementation with reporting. Two combine explicitly
primary execution work with repeated implementation duties, supporting the existing
mixed-plausible criterion without calling the work first-choice engineering. No new
candidate facts, blanket role acceptance or human preference decision is needed to apply
the current rules. Original labels, outputs and metrics remain unchanged.

Those two execution-work rows are near duplicates: their complete descriptions differ
only in a spelling variant. Exact whitespace-normalized grouping misses that variant.
The four rows therefore represent three duty patterns; the frozen 60-row counts are
preserved. Future validation needs near-template/requisition review before splitting.

P0 separates ranking from eligibility and leaves reading allocation to the consumer; it
does not implement a universal eligibility-before-K predicate. The concrete consumer
recommendation is to admit sources using supported, current, source/profile-bound
eligibility evidence before reserve/domain/K allocation, with confirmed conflicts in a
visible excluded-with-reason view. Unknown or stale evidence stays visible for review;
native priority and proxy utility labels cannot substitute for eligibility facts. Apply
the same admission scope to both ordering arms. This recommendation adds no predicate or
filtered comparison here.

Private `adjudication.json` validates 14 exact source spans and binds all original inputs;
SHA256 `cb09f56c41df575edd87046d037d37e3c42ff90650dbfbab3c07f32c4f7e2964`.
No additional native call or cohort change occurred. Prospective capture remains the
next evidence gate.
