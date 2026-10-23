# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional screening **and fit scoring remain supported**.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **Source lifecycle for unscored inventory — design draft awaiting operator approval**
  [FETCH · M · branch docs/issue-93-source-lifecycle; issue #93]. The current expiry
  check only covers scored/notified rows and discards successful detail responses;
  duplicate intake rows do not refresh source evidence. Proposed contract and execution
  plan: [design](superpowers/specs/2026-10-23-source-lifecycle-design.md) and
  [plan](superpowers/plans/2026-10-23-source-lifecycle.md). The design keeps source
  availability separate from pipeline/application state and assessment freshness,
  records changed evidence without model reruns, recommends SmartRecruiters for the
  first pilot from the live unscored inventory, and leaves retention and intake policy
  alone. Reconfirm pilot eligibility before rollout. It is a draft, not implementation
  authorization; issue #93's dependencies #91 and #92 are merged.

- **`feat/fit-extraction-shadow` — retained branch claim, deferred research**.
  Isolated extraction/provenance/frame work exists; production cutover, additional model
  runs and labels are not selected work. Candidate-evidence annotation ownership remains
  unresolved. See [evaluation inventory](EVALUATION.md#corpus-inventory-and-interpretation)
  and the [research boundary](superpowers/plans/2026-08-03-fit-scoring-rebuild.md).
- **`feat/fetch-detail-hydration` — retained branch claim, integration unverified**.
  Inspect branch/main divergence before merging. Fresh full-JD quality remains relevant;
  the large backfill and old scored-row counts need a current dry-run. Do not rescore
  legacy verdicts as a side effect. Its working plan is operator-local.
- **`docs/quota-levers-plan`, `fix/seniority-veto-evidence` — retained branch claims,
  deferred experiments**. No default caching, veto-tuning or paid-run sequence. A new
  measured problem is required before resuming; keep the negative cache result.
- **`docs/corpus-expansion-groundwork`, `docs/luna-screen-result` — retained branch
  references, reconciliation required**. Old single-run claims do not supersede the
  repeated/expanded screen results. Do not merge research prose without current review.

These references reserve unfinished work; they do not claim the branches are currently
executing or establish merge readiness. Inspect actual refs/worktrees and coordinate
before changing them. No older research authorization schedules new provider calls.

## Do next — the pick order

1. Orchestrator establishes [workflow baseline #90](https://github.com/drink970082/job-matchbook/issues/90)
   alongside the first implementation batch.
2. Luna/max executes [MCP research queries #91](https://github.com/drink970082/job-matchbook/issues/91)
   using the [batch 1 plan](superpowers/plans/2026-10-22-batch-1-mcp-research.md).
3. After batch 1 acceptance, Luna/max executes [inventory UI #92](https://github.com/drink970082/job-matchbook/issues/92)
   using the [batch 2 plan](superpowers/plans/2026-10-22-batch-2-job-inventory.md).
4. Orchestrator scopes source lifecycle (#93) and performs scheduled Brief acceptance
   (#94); #94 need not wait for all of #93 if official pages and freshness limits are checked.
5. Two independent conditional branches after #94: delivery ledger (#95) for observed
   repeats, or last-priority fit pre-ranking (#96) for a throughput gap. Both need a
   separate design; if scheduled ChatGPT suffices, scorer rollout is unnecessary.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.
Astra/Sol owns architecture/docs/acceptance; all implementation/fixes go to Luna/max.
The current runtime Luna/medium screening configuration is a separate concern.

## Current implementation limitations

- Fetch applies candidate/title gates before the agent sees the data. Existing dedup
  ignores repeated source/external IDs rather than generally refreshing their JDs.
- Liveness rechecks select scored/notified rows for supported detail adapters; a stored
  screen-only/new posting is not guaranteed open.
- Imported/manual applications may have no posting link. Deduplicate against the
  applications table, not only `application_id`.
- No persistent Brief delivery ledger or MCP writes. Cross-day deduplication is
  best-effort; background task/tunnel access still needs workflow-level acceptance.
- Optional model quality remains bounded by corpus provenance. Luna/medium screening
  lacks an effort-identified accuracy run; legacy fit labels include unsupported inputs.
  These limitations matter for judgment changes, not as blockers for unrelated work.

## Evaluation and cost

[EVALUATION](EVALUATION.md) maps changes to checks and inventories retained private
artifacts. No live eval was run for the pivot. Subscription-backed Luna assistance is
acceptable; its allowance is finite, and old strong-fit token/cache measurements are not
current Luna/medium budget forecasts. The roadmap does not require draining every row.

The operator-selected worker remains standalone screen-only; combined fit/Telegram
capabilities and CLI defaults remain available. Current operational mode is in
[SPEC §6](SPEC.md#6-architecture). Use fresh telemetry before making workload decisions.

## Other work

[BACKLOG](BACKLOG.md) triages optional and deferred work;
[REJECTED](REJECTED.md) preserves evaluated alternatives and negative results.
The retained [engineering catalogue](ENGINEERING_CATALOGUE.md) is context to revalidate,
not a second priority queue.

## How to update

Claim a branch before substantive changes. Keep only unfinished claims and current
limitations here. Remove a completed claim when it lands. Put capabilities in SPEC,
product order in ROADMAP, measurements/negative results in EVALUATION or SCORING, and
completion history in CHANGELOG. Never publish private corpus rows, résumé or settings.
