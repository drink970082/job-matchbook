# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional screening **and fit scoring remain supported**.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **Issue #116 screen-isolation repair** — `fix/preselection-screen-isolation`, based on
  current `main` at `a9e5972`. The neutral screen extraction and mode-aware config are
  carried forward with a lazy `score` compatibility facade. Fresh-process regression now
  covers exception/screen imports, legacy prompt reads, fit-backend loading and explicit
  fit-factory access. Fresh-context review found no actionable issue. The dependent
  local stack passes worker coverage (88.61%; 1,300 passed, 1 skipped), web coverage
  (420 tests / 35 suites), worker/web integration (4 passed, 1 skipped; 74 passed), and
  schema checks. The branch remains local because the GitHub connector requires approval
  for remote writes and approval is unavailable. No provider inference or production
  wiring is involved.

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

1. Finish the provider-free #116 facade correction, then repair #110 daily allocation,
   rendered-context exit status and frozen-input provenance. Keep both issues open until
   their exact heads pass independent review. Only then revalidate the #111/#112 repair
   stack against those prerequisites. These corrections use fabricated data and authorize
   no live inference.
2. Orchestrator reviews the repaired heads and their unmerged #109/#110/#116 prerequisites
   before any upstream stack merge. Existing green suites do not establish acceptance.
3. [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94)
   still needs actual unattended access/delivery evidence. It does not block the offline
   corrections. #95 delivery history remains deferred.
4. Live #112 evaluation requires approved candidate inputs, labels/cohort, questions/YOE,
   provider/model, budget/pricing and predeclared acceptance tolerances. The operator owns
   GO and activation; daily throughput need is already selected at approximately 200/day.
5. Parent #113/#114 production persistence/MCP/inventory/batch integration and #115 actual
   unattended acceptance retain their scoped gates. Available offline modules are in SPEC;
   synthetic rehearsal does not satisfy those live deliverables.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.
Astra/Sol owns architecture/docs/acceptance; all implementation/fixes go to Luna/max.
The current runtime Luna/medium screening configuration is a separate concern.

## Current implementation limitations

- #111's unmerged shadow transport has no enforced blocking-call deadline or bounded
  retry backoff. #112's unmerged report accepts unbound provenance declarations, rejects
  legitimate pre-assessment unresolved outcomes and conflates recurring pool membership
  with inference identity. Their [repair contract](superpowers/plans/2026-10-29-preselection-shadow-repair-handoff.md)
  is the next agent scope; neither implementation is accepted or wired into main.

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
