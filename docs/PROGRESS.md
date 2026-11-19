# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional hard-requirements screening is supported; the fit scorer is removed.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **JEV keep/skip filter — deployed, backlog draining until about early December** `[JEV · M]` (#139).
  The worker unit runs `--jev --jev-limit 300 --jev-max-usd 0.10` from `ats-runtime` at
  main; private inputs are `resume/pivot/jev-prod-v1/` (profile `level` line at 3 years).
  About 6,000 screened candidates predate the filter and drain at 300 per daily pass
  (about USD 0.08 per pass); until then most of the inventory lists as
  `unassessed` and is shown. Rollback = drop `--jev` from
  `ats-worker.service.d/20-screen-only.conf` and restart; the table is additive.

- **Fit-scorer residue — unclaimed** `[SCORE · S]`. The scorer is gone (#149, #150);
  what is left needs a decision, not a branch:
  (1) `seniority.py` + `prompts/seniority.txt` + `make eval-seniority` are kept but
  unwired — fold the classifier into the screen or delete it, undecided.
  (2) `onboard-me`'s profile/résumé interview still describes inputs for the retired fit
  scorer; rewrite once JEV settles what it reads.
  (3) `fit_profile` stays an accepted-and-ignored `config.yaml` key; delete it once no
  config carries the block.
  (4) Columns nothing writes any more — `job_postings.score`, `notify_attempts`,
  `deprioritized_at` — and the web's score filter / Matched buckets that read them. The
  web half waits for #158.

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

1. [#135 JEV ranking → MCP](https://github.com/drink970082/job-matchbook/issues/135),
   packages P1–P6 (#137–#142) in dependency order; open drafts #134, #143–#146.
2. [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94)
   still needs unattended access/delivery evidence. #95 remains deferred.

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
- No persistent Brief delivery ledger; MCP write tools are in flight (#154). Cross-day deduplication is
  best-effort; background task/tunnel access still needs workflow-level acceptance.
- Optional model quality remains bounded by corpus provenance. Luna/medium screening
  lacks an effort-identified accuracy run; legacy fit labels include unsupported inputs.
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
The retained [engineering catalogue](ENGINEERING_CATALOGUE.md) is context to revalidate,
not a second priority queue.

## How to update

Claim a branch before substantive changes. Keep only unfinished claims and current
limitations here. Remove a completed claim when it lands. Put capabilities in SPEC,
product order in ROADMAP, measurements/negative results in EVALUATION or SCORING, and
completion history in CHANGELOG. Never publish private corpus rows, résumé or settings.
