# P1 evaluation package

**Status:** offline preparation assigned; real daily pools unavailable; prospective collection preparation selected.
Accepted P0: [1308f47](https://github.com/drink970082/job-matchbook/tree/1308f47/docs/jev-ranking).
Planning: [ef18116c](https://github.com/drink970082/job-matchbook/tree/ef18116c/docs/jev-ranking).
This work owns no production runtime and authorizes no inference.

## Fixed comparison protocol

Use publication-time order (descending, missing last, stable job ID ascending) as arm A;
JEV high/medium/low and the same time/ID tie-break as arm B. Use the same frozen pool,
source eligibility and externally frozen domain mapping for both arms. Domains are the
accepted eight P0 IDs; mixed/unknown have reserve access. Never use legacy fit scores as
labels. Keep all duplicate/requisition/template groups in one split. Previously exposed
22 historical inputs are development only. At least three untouched complete daily
windows need independently reconciled source rosters; DB insertion dates alone are not
source-completeness proof. No outcome-selected replacement or long-input exclusion.

Budget settings are K/R = 10/2, 20/4 (primary), 40/8. R is inside K. For this
synthetic evaluation, reserve eligibility is the entire frozen eligible source roster,
computed before reference labels or ranking outputs. Choose up to R unique IDs by
SHA256 of `jev-p1-exploration-v1|day|job_id` ascending (ID tie-break). Both arms use the
same reserve IDs. It is exploration, not an oracle of which jobs deserve review.

Allocate remaining slots by equal round-robin over lexicographically sorted declared
domains, skipping empty queues and excluding selected reserve IDs. Domain membership
is frozen independently of JEV and reference utility labels; mixed/unknown domain rows
have reserve access only. Up to K unique reads total. Unused reserve capacity may be
filled from ordinary domain queues; no additional exploration beyond R. Report actual
JEV review flags separately: main-lane flagged jobs consume ordinary slots, not extra
reads. P5 separately tests live consumer review behavior.

Arm B keeps missing/null/failed/deferred/stale assessments explicitly after low within
their frozen declared domain, ordered by the same publication-time/ID keys. They remain
unknown, never coerced to low or dropped from the pool, recall denominator or coverage.
Arm A orders the same domain queues solely by time/ID regardless of assessment state.
No ranking state may redefine source eligibility. Empty domains or all-unknown domains
may produce fewer than K reads; disclose actual denominator and unused slots.

Blind guide: read full JD plus approved background/preferences without seeing JEV or
legacy scores. Record domain; worth_deep_reading/not_currently_worth_deep_reading/unresolved;
preferred tier and admissible alternatives; source references and explicit uncertainty.
Missing background evidence is not inability. Labels are model proxies, never human gold.
Freeze labels before opening JEV outputs; ambiguous preference questions go to operator.
No blind model labeling is authorized by this assignment.

## Metrics and accounting

Precision denominator is actual unique reads; report positive/negative/unresolved counts
and precision bounds [positive/n,(positive+selected_unresolved)/n]. Empty reads undefined.
Recall lower bound is selected_positive/(all_positive+unselected_unresolved); upper bound
is (selected_positive+selected_unresolved)/(all_positive+selected_unresolved), with zero
denominators undefined. Also report resolved-only recall with its denominator; no positives
is undefined, never 100%. Feasibility ceiling min(1,K/all_positive) is separate.
Report missed positives by day/domain; current successful-binding coverage; whole-inventory
exclusions; review fraction in pool/selected; reserve positive recoveries. Unresolved bounds
must not be silently replaced by complete-label claims. Paired day differences and counts
are primary; three days do not establish broad statistical reliability.

## Synthetic utility assignment

A minimal stdlib-only standalone script and synthetic tests may implement this exact
selection/metric path, without imports from research or runtime modules. It accepts
explicit domain list and frozen rows; rejects duplicate IDs, invalid enums and missing
required fields; never accesses network, database, profile or production config. Provide
reproducible synthetic CLI output, not fabricated real-quality evidence. No general
experiment platform, provider transport, daemon or runtime dependency.

## Gates and budget proposal

P1 completion requires actual complete daily roster/grouped split hashes, measured full
requests, frozen proxy guide and proposed exact paid/subscription workload. Until cohort
counts exist, no numerical attempt/spend/time proposal can be truthfully finalized.
Inference authorization is zero provider calls, zero model-label jobs and zero money.
Separately authorized public-board snapshot fetching is documented in the collection guide. P2 separately
requires accepted counts/model/attempt/repeat/retry/money/time caps and reconciled historical
ledgers. Study thresholds remain research defaults for pre-registration, not GO evidence.

## Local synthetic reproduction

Run `python3 -m unittest discover -s tools/tests -p test_jev_p1_evaluation.py -v` and
`python3 tools/jev_p1_evaluation.py tools/fixtures/jev_p1.synthetic.json` from repo root.
The JSON report is explicitly synthetic-only. It covers both orderings at all three
fixed K/R settings, per-day metrics, unresolved bounds, coverage and review burden. It
cannot establish real ranking quality or authorize P2. Input domain labels and outcome
labels must have separate frozen provenance for any later real study.

## Verification and remaining evidence

Synthetic utility: 9 tests pass. Collector targeted tests: 9 pass, including fake CLI
and existing-output protection. Worker coverage run: 1493 passed, 1 skipped; total
coverage 85.09% meets the 85% floor. No web/schema changes; no web or live runtime
checks were run. The current collector is a separately activated limited snapshot
surface, not the complete original all-source/day-window acceptance claim. Source
scope and activation details are in [collection](p1-collection.md).

P1 remains open: actual daily artifacts, duplicate-group split hashes, sealed blind
proxy inputs and exact campaign attempt/money/time/subscription proposal are not yet
available. No synthetic or stored-inventory result satisfies those missing criteria.
