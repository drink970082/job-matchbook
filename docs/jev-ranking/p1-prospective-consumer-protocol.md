# Prospective consumer comparison protocol

**Status:** analysis protocol for existing normally screened inventory and later
fresh worker intake; independent collection timers are disabled. No runtime, screening, predicate or model-arm change.
This does not turn point snapshots into complete daily windows or establish a GO threshold.

This protocol does not require adding a new eligibility gate ahead of the operator’s
existing screen view. Extra fact-review admission below is a separately declared study
analysis; it must not silently redefine that existing post-screen pool.

Use the accepted [P0 contract](https://github.com/drink970082/job-matchbook/blob/1308f47/docs/jev-ranking/p0-contract.md),
[limited collection scope](p1-collection.md) and [P1 v2 comparison](p1-evaluation.md).
Use normal worker fetch+screen output. Seal the same post-screen read pool for both
ordering arms; screen judgments are advisory inputs, not utility-reference truth.
Existing inventory is development evidence and can be used immediately. Future normal
intake can provide fresh validation without a separate collector or three-day wait.

## Freeze before judgments

For each worker intake/export seal available source receipts, identities, parsed sources,
capture cutoff, source hashes, original filter reasons and missing/failed records.
Reconcile raw → parsed/excluded/unresolved before forming a consumer pool. Group exact
source/requisition identities and review near-template candidates, including spelling
variants, before splitting. Preserve every member and reason. Shared/repeated requisitions
across observations are repeated opportunities, not independent new examples.

Bind the existing approved inputs byte for byte:

| Input | SHA256 |
|---|---|
| Approved profile/domain binding | `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986` |
| Domain manifest | `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c` |
| Accepted C questions | `e63c5bf3c55904df22af028775f1c25d4f07d94013a563be85804167b0224109` |

Any changed profile/source requires a separately identified evidence version; never claim
an old judgment is current merely because its timestamp is recent. Independently freeze
admission evidence and duty-domain allocation before native results or utility labels.
Utility labelers do not supply admission facts. Existing Dev60 labels, sources and
filtered or unfiltered outcomes remain development-only and unchanged.

## What current screening can establish

The existing `job_screenings` row stores latest state/result, backend/model/effort,
evaluator version, timestamps and nullable `source_content_revision`. It has **no
profile/requirements hash or immutable complete-request binding**. MCP
`source_lifecycle.screen_freshness` compares source revisions only; `current` does not
mean current candidate requirements, verified extraction or eligibility. Missing
revisions are unknown, and provider errors remain distinct. The screen summary is
advisory. Triage categories describe supported stored evidence shapes, not independently
verified source truth.

`db.save_screening` reads the posting revision when saving rather than receiving a
separate captured-input hash/revision. Supported refresh/screen CLI paths share the pass
lock; this inspection establishes no normal-CLI race or regression. Candidate changes
intentionally require explicit rescreening under the existing advisory-cache policy.
The configured screen checklist also covers only a subset of the approved profile's
constraints. A complete screen pass therefore cannot certify all requirements, and a
stored failure cannot automatically exclude a prospective source. No API field currently
certifies full source-and-profile binding. This is an evaluation-evidence limit, not a
requirement to change the cache or migrate the schema.

Recorded screen evaluations do not certify every current result or deployed effort. Treat cached conclusions as leads for evidence review, not an
oracle. Legacy geography filters deserve the same caution: a deterministic location
parser acts on a board location string, which may be ambiguous, incomplete or contradicted
by the full source. A rule label or discarded pipeline state alone proves no conflict.

Code references: [schema](../../apps/web/prisma/schema.prisma),
[screen persistence](../../apps/worker/ats_worker/db.py),
[MCP summaries](../../apps/worker/ats_worker/mcp/read_repository.py),
[freshness helper](../../apps/worker/ats_worker/source_lifecycle.py),
[screen engine](../../apps/worker/ats_worker/screening/engine.py),
[screen evaluation limits](../EVALUATION.md#corpus-inventory-and-interpretation).

## Admission before K, with explicit evidence

Use a small private study evidence receipt, not a new production predicate. For any
proposed exclusion record source identity/revision and exact captured-source hash,
approved profile binding hash and existing constraint ID, exact source field/span/quote
with surrounding qualifiers, reviewer/decision time, and the explicit conflict reason.
Record any supporting stored-screen pointer and its limitations separately. Verify the
quote against the frozen source and the condition against the existing accepted
constraint; mandatory/preferred, alternatives, ranges, location scope and silence must
retain their stated meaning. This is source-fact review, not a new skill/eligibility rule.

| Evidence at the frozen cutoff | Consumer admission |
|---|---|
| Independently checked explicit conflict with an existing approved hard constraint, fully source/profile bound | Visible `excluded_confirmed_conflict`, reason and provenance retained; outside ordinary and reserve K |
| No confirmed conflict, including missing/ambiguous/stale screen or unsupported cached rejection | Admit with explicit unresolved requirements; eligible for ordinary allocation where domain is known and for exploration/fill |
| Contradictory evidence, missing source body or unassessable ranking input | Keep visible and unresolved; never infer failure or qualification; missing/deferred ranking state remains eligible for exploration/fill |

Do not turn native LOW, absent relevance, unknown domain, a proxy utility-negative label
or a screen pass into a hard-eligibility fact. Do not add a years, geography, sponsorship,
salary or employment-type predicate to make the study succeed. If no independently
verified conflict receipt exists, the item remains admitted/unknown. No new screening
call is required by this document. A future schema/API binding feature would be separate
work; this protocol does not claim it exists.

Preserve collector filter exclusions as their own stage. Audit any claimed geography
conflict against the captured full source and accepted constraints before describing it
as confirmed. Unsupported historical/filter conclusions stay unresolved in the full
capture accounting. Do not silently repair the active collector, erase those identities
or call retained-only recall full-capture recall. A remaining unverifiable filter loss
keeps the corresponding completeness/recall claim INCONCLUSIVE.

## Same admitted pool, two fixed orderings

Freeze one identical admission partition and independent domain map per observation for
both arms. Apply admission before initial reserve, domain allocation and K counting.
Use K/R=10/2, **20/4 primary**, 40/8, R inside K and explicit
`fill_unused_budget=True`. Reserve uses ascending
SHA256(`jev-p1-exploration-v1|day|job_id`), then stable ID, with the actual observation's
UTC date as `day`. Equal round-robin over sorted accepted domains supplies ordinary
slots; mixed/unknown domains retain reserve and unused-budget fill access.

Arm A orders publication time descending, missing last, stable ID ascending. Arm B adds
the unchanged priority ordering before those same keys. Missing/null/failed/deferred/
stale native states stay explicit after LOW, never disappear. Date-only publication
values imply date ordering only. Review flags are reported, not extra reads. Deduplicate
before budget counting; disclose fewer than K available reads and unused slots. A model
failure or overbound full request gets no outcome-selected replacement or truncation.

## Denominators and disposition

Report each observation separately before any pooled summary:

- All captured raw identities and expected/captured/failed boards, with structural,
  collector-filter, duplicate-member and missing-body counts. Keep this capture denominator
  even when some sources cannot enter a complete native request.
- The grouped pre-admission study frame, confirmed-conflict exclusion count/reasons,
  admitted count, unresolved admission count and unassessable count. Partition counts
  must reconcile; exclusions never vanish from coverage.
- For each K and arm, actual unique reads, reserve/ordinary/fill reads, positive/negative/
  unresolved utility counts, P1 precision/recall bounds, resolved-positive denominator,
  missed positives by domain, review burden and current binding coverage.
- Separately report admitted-pool utility recovery and full pre-admission-frame recovery,
  including independently labeled positives among exclusions. Audit those excluded rows
  without JEV or admission decisions shown to utility labelers. Unlabeled/unassessable
  rows remain unresolved; if full-capture utility cannot be bounded, say INCONCLUSIVE.

This separates admission losses from ranking gains. Never use utility labels to repair
the admission partition, assume every exclusion is a utility negative, or retrofit a
filtered Dev60 quality result. Paired differences share the same unresolved identity;
show uncertainty bounds, actual feasibility ceilings and repeated-source dependence.

Before any native inference, actual snapshot counts, full request sizes, grouped scope,
blind guide and bounded inference workload must be sealed separately. Ordinary worker exports do not by themselves establish complete-day intake or
untouched held-out evidence. No final numerical
GO thresholds or production activation follow from this protocol. Missing evidence keeps
the relevant result INCONCLUSIVE; no new user preference decision is needed now.

Verification for this document is static inspection of the named schema/helpers and
existing P0/P1 contracts. No DB audit, provider call, timer/service change, schema change,
new predicate or production behavior is performed or claimed.
