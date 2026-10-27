# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional screening **and fit scoring remain supported**.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **Issue #96 preselection design — `docs/issue-96-preselection`** [ORCH · design draft].
  Define aggressive role classification and optional JEV ranking before deep Daily
  Brief review, with recall audits and bounded evaluation. No model calls or rollout
  selected; provider, rubric, acceptance targets and experiment budget remain open.
  The design specifies daily pool/queue boundaries, version races, bounded failures
  and separate pilot/held-out acceptance gates. [Contract gate #109](https://github.com/drink970082/job-matchbook/issues/109)
  validates the English private [pivot input contract](superpowers/specs/2026-10-26-candidate-input-package.md),
  before implementation/evaluation slices #110–#115; their issue bodies own readiness.
  New context excludes runtime reads of legacy profile/config/Registry; evidence remains local.
  The input contract includes required-YOE exclusion boundaries, conditional authorization
  extension context and attempt-level JEV price evidence; implementation remains separate.
  [Scorer boundary inventory](superpowers/specs/2026-10-26-legacy-scorer-boundary.md)
  assigns live screen vs legacy fit/research ownership. [Prefactor #116](https://github.com/drink970082/job-matchbook/issues/116)
  follows offline #109 input validation and establishes the screen boundary before #110/#111.
  Stacked local preparation follows passing #116 checks; dependent PRs stay draft and disclose
  prerequisite diffs. No scorer deletion or runtime cutover.
- **Issue #116 active-screen isolation prefactor** — `feat/screening-isolation-prefactor`, stacked on the current design branch at `87b2f3b` and locally observed `origin/main` at `670f596`. The live screen engine, prompt/schema, location rules and screen transports are isolated in `ats_worker/screening/`; legacy `score.*` exports remain compatible and fit imports are deferred from screen-only mode. Screen-only skips only legacy `fit_profile` validation while retaining operational config checks. Fresh-process screen-only and explicit legacy-fit demos pass; worker coverage is 92.32%, integration/schema checks pass, and the tracked-path privacy audit passes (the Node wrapper is sandbox-blocked by child-process EPERM). No new preselection/provider behavior, scorer deletion or runtime cutover is included. Keep the dependent slice draft and disclose the planning prerequisite diff.

- **Issue #110 offline profile/replay path** — `feat/profile-replay-input`, stacked on
  the locally passing #116 boundary. The allowlisted candidate profile validator and
  exact renderer are isolated from legacy scorer/profile/resume imports. The offline
  replay validates frozen-pool labels, groups UTC days and shared templates for a
  deterministic split, and compares recency/role-coverage baselines through aggregate
  reports. Synthetic compression and YOE boundary fixtures are included. No real job
  pool, model call, evaluation claim, provider choice or runtime selection is included;
  the profile remains draft. Worker tests pass (1,228 passed, 1 skipped; 92.20%
  coverage), focused integration passes (4 passed, 1 skipped), and schema, privacy
  self-test and 372-path tracked-file audits pass. The full Node privacy wrapper remains
  blocked by sandbox `spawnSync git EPERM`. Review and remote PR creation remain pending.
  Keep the dependent slice draft and disclose prerequisite diffs.

- **Issue #111 provider-neutral shadow contracts** — `feat/preselection-shadow-provider-neutral`,
  based on the local #110 commit. Typed independent questions and strict evidence
  validation, JD-only extraction with exact source spans, required-YOE alternatives,
  direct/extracted default-off fake transport, model/work-item/draw identities and a
  private resumable attempt journal are implemented. Retry links, elapsed/attempt/cost
  limits survive restart; unknown charges and provider/model circuit breakers stop more
  calls. Reports aggregate per run, work item, success, variant, draw and extraction
  stage. Worker coverage passes (1,278 passed, 1 skipped; 90.02%), integration passes
  (4 passed, 1 skipped), and schema drift, privacy self-test, 390-path tracked/untracked
  audit, fresh-process preselection import audit and screen-only/legacy boundary checks
  pass. The full Node privacy wrapper remains blocked by sandbox `spawnSync git EPERM`;
  `make lint` cannot find `next` in this worktree, and web files are unchanged. Independent
  review and remote PR creation remain pending. No provider, rubric, monetary price, live
  evaluation or runtime wiring is selected. Keep the dependent slice draft and disclose
  prerequisite diffs.

- **Issue #112 offline evaluation procedure/report** — `docs/preselection-evaluation`,
  based on local #111 `f49e95b`. The manifest validator and aggregate report join
  pseudonymous blinded-label inputs, daily-pool baseline orders and draw-planned
  assessments to the strict private attempt journal. It checks reported answers against
  successful journal payloads; treats missing/failed positives as misses; separates
  full-pool results from repeated-subset diagnostics; and reports per-arm/draw/stage and
  per-work-item cost distributions with actual, estimated and unknown charges distinct.
  The procedure records the open approvals and proposed caps without authorizing them.
  Synthetic-only targeted tests pass (26); the worker suite passes (1,304 passed, 1
  skipped; 89.51% coverage), integration passes (4 passed, 1 skipped), and the fresh
  import/screen-boundary checks, schema-drift guard, privacy self-test, 395-path
  tracked/untracked audit, compile and diff checks pass. No live evaluation, provider
  call, cost evidence, threshold or GO decision is made. #94 unattended acceptance,
  candidate-profile approval, provider/policy/budget choices and independent review
  remain open. Remote reconciliation and PR creation are unavailable while GitHub
  DNS/token access is blocked.

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

- **Daily Brief instructions for issue #94 — unattended acceptance remains open**
  [ORCH · M · branch docs/issue-94-daily-brief]. Public task instructions, an interactive
  preflight record, and an unattended acceptance checklist are in [the Daily Brief
  guide](reports/2026-10-23-daily-brief-instructions.md).
  The current Codex CLI session can read the ATS MCP tunnel interactively, but has no
  Scheduled management interface; issue #94 still needs a task created in ChatGPT web
  or desktop and one observed unattended run. The deployed MCP supports standalone-screen update windows and source-lifecycle
  summaries/check timestamps. Verify that the actual Scheduled connection discovers
  that schema; legacy postings without source evidence still have unknown freshness.
  Web Scheduled tasks can use uploaded files and connected tools; desktop tasks can run in
  a local project directory or worktree. Verify the actual task can access the private
  preference and résumé files. Exact 20:00 delivery depends on account eligibility.
  The guide excludes confirmed prior applications and keeps probable duplicates flagged
  for review. Interactive access is not acceptance.

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
4. Orchestrator performs scheduled Brief acceptance (#94); #94 need not wait for source
   lifecycle if official pages and freshness limits are checked.
5. Two independent conditional branches after #94: delivery ledger (#95) for observed
   repeats, or last-priority fit pre-ranking (#96) for a throughput gap. Both need a
   separate design; if scheduled ChatGPT suffices, scorer rollout is unnecessary.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.
Astra/Sol owns architecture/docs/acceptance; all implementation/fixes go to Luna/max.
The current runtime Luna/medium screening configuration is a separate concern.

## Current implementation limitations

- The production landing page emits React hydration errors 418/423 before recovering
  on the client. The inventory/detail flow works; the same six errors reproduce with
  the previous production image against the same database.

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
