# Job Matchbook — active work

Job Matchbook is an elimination filter for job seekers: every open job the candidate can
actually get, none they can't; AI clients analyze downstream over MCP. Optional hard-requirements screening is supported; the fit scorer is removed.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **One candidate profile; evaluate each posting once — spec approved; implementation
  not started** `[WORKER+WEB+MCP · L]` (epic #223; no implementation branch yet).
  [Spec](superpowers/specs/2026-11-20-candidate-profile-design.md); #224 is next.
- **Workday expiry check builds a malformed URL, so workday never closes**
  `[WORKER · S]` (#266, epic #229; branch `fix/266-workday-expiry`).

These references reserve unfinished work; they do not claim the branches are currently
executing or establish merge readiness. Inspect actual refs/worktrees and coordinate
before changing them. No older research authorization schedules new provider calls.

## Do next — the pick order

1. [#229 Sources tell the truth](https://github.com/drink970082/job-matchbook/issues/229): #231, with #247 (pass record,
   [#246 epic](https://github.com/drink970082/job-matchbook/issues/246)) alongside.
2. [#223 One candidate profile](https://github.com/drink970082/job-matchbook/issues/223): #224 -> #225 -> #226, with #227 after #224.
3. [#251 Runtime settings in the web](https://github.com/drink970082/job-matchbook/issues/251), then [#256 MCP as the downstream contract](https://github.com/drink970082/job-matchbook/issues/256)
   (#209 decided: option A, [note](superpowers/specs/2026-11-20-mcp-read-path-research.md); next a hosted tunnel check, then #257).
4. [#240 Applications](https://github.com/drink970082/job-matchbook/issues/240), then [#236 source extensibility](https://github.com/drink970082/job-matchbook/issues/236).
5. [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94): one observed unattended run.

[ROADMAP](ROADMAP.md) holds the full phase table and the research list.

#95 stays conditional.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.

## Current implementation limitations

- The production landing page emits React hydration errors 418/423 before recovering
  on the client. The inventory/detail flow works; the same six errors reproduce with
  the previous production image against the same database.

- Fetch applies candidate/title gates before the agent sees the data. Existing dedup
  ignores repeated source/external IDs rather than generally refreshing their JDs.
- Board absence closes postings only for greenhouse, lever, ashby, pinpoint and
  workable (SPEC §7.1 `run_fetch`). phenom, browser, icims and custom boards are never
  closed by absence (their lists can be truncated without raising; a recipe-level
  complete-list opt-in is a possible follow-up for custom), nor feed-ingested postings
  of boards off the watchlist, nor legacy rows with no `company_slug`.
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
artifacts. Subscription-backed Luna assistance is
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
