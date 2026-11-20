# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional hard-requirements screening is supported; the fit scorer is removed.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **JEV profile in the DB — deployed; acceptance: tonight's JEV pass re-queues nothing
  for a policy change (hash verified equal at deploy); then delete this entry**
  `[WORKER+WEB · M]` (#157).

- **JEV keep/skip filter — acceptance: the first pass after the 7-day window deploys
  attempts only postings from the last 7 days (worker `[jev]` tally); then delete this
  entry** `[JEV · M]` (#139).
  Production runs `--jev --jev-limit 300 --jev-max-usd 0.10` against private packs. JEV
  assesses only the last 7 days of postings, so there is no backlog to drain; the ~5,900
  older screened postings stay `unassessed` and listed. Rollback = drop `--jev` from the
  worker's flags and restart; the table is additive.

- **Web UX pass — one PR per issue, remaining: #210 Activity; #209 (MCP reads via `/api/v1`) is
  research after those land** `[WEB · L]`. Branches `feat/<issue>-*`; each issue body is
  the agreed spec. #205 shipped the proposed Ghosted -> Rejected mapping and 60-day Active
  window unconfirmed by the operator; its data migration
  (`apps/web/prisma/migrate-statuses-205.mjs`) has not run on the deployed DB, which
  holds no pre-#205 status today. #206 adds `candidate_preferences.exclude_contract`:
  the deployed DB needs `make db-push` (back up `db/` first) before the new web or
  worker runs against it.

These references reserve unfinished work; they do not claim the branches are currently
executing or establish merge readiness. Inspect actual refs/worktrees and coordinate
before changing them. No older research authorization schedules new provider calls.

## Do next — the pick order

1. [#152 AI-orchestrated ATS](https://github.com/drink970082/job-matchbook/issues/152):
   its last open slice, #157 (preferences and profile in the DB), is in flight above.
2. [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94):
   one observed unattended run ([DAILY_BRIEF](DAILY_BRIEF.md) checklist).
3. [#135 JEV ranking → MCP](https://github.com/drink970082/job-matchbook/issues/135),
   gated on the keep/skip filter's acceptance (#139). #95 stays conditional.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.

## Current implementation limitations

- The production landing page emits React hydration errors 418/423 before recovering
  on the client. The inventory/detail flow works; the same six errors reproduce with
  the previous production image against the same database.

- Fetch applies candidate/title gates before the agent sees the data. Existing dedup
  ignores repeated source/external IDs rather than generally refreshing their JDs.
- Liveness rechecks (`run_expire`) cover detail adapters only; a stored board-source
  posting is not guaranteed open. Closing it means diffing each board's current listing
  against stored rows, where a fetch failure must never read as "every job closed".
- Imported/manual applications may have no posting link. Deduplicate against the
  applications table, not only `application_id`.
- No persistent Brief delivery ledger. Cross-day deduplication is
  best-effort; background task/tunnel access still needs workflow-level acceptance.
- `--jev-backend extract` is unmeasured and has no shadow mode: one pass replaces the
  production policy hash (every native verdict shows stale) and overwrites native rows
  that cost money to rebuild. Do not switch production to it before a measurement path
  exists.
- Optional model quality remains bounded by corpus provenance. Luna/medium screening
  lacks an effort-identified accuracy run.
  These limitations matter for judgment changes, not as blockers for unrelated work.

## Evaluation and cost

[EVALUATION](EVALUATION.md) maps changes to checks and inventories retained private
artifacts. No live eval was run for the pivot. Subscription-backed Luna assistance is
acceptable; its allowance is finite, and old strong-fit token/cache measurements are not
current Luna/medium budget forecasts. The roadmap does not require draining every row.

A worker pass is fetch -> screen, plus the JEV keep/skip filter under `--jev`. Current operational mode is in
[SPEC §6](SPEC.md#6-architecture). Use fresh telemetry before making workload decisions.

## Other work

[BACKLOG](BACKLOG.md) triages optional and deferred work;
[REJECTED](REJECTED.md) preserves evaluated alternatives and negative results.

## How to update

Claim a branch before substantive changes. Keep only unfinished claims and current
limitations here. Remove a completed claim when it lands. Put capabilities in SPEC,
product order in ROADMAP, measurements/negative results in EVALUATION or SCORING, and
completion history in CHANGELOG. Never publish private corpus rows, résumé or settings.
