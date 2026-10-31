# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional screening **and fit scoring remain supported**.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **Issue #116 offline screen-isolation acceptance** remains open under #130.
  The neutral screen/import boundary and executable before/after demo are present on `main`; #109's scoped
  offline contract acceptance remains open. Real profile/policy approval belongs to
  #131/#109 and does not block this offline closure scope.
  No live model or production change is claimed.

- **Issue #110 offline replay/evaluation implementation** remains open under #130.
  The merged frozen profile/replay path validates supplied payloads, profile/context hashes, day membership and manifest
  consistency, but has no independent roster proving pool completeness. Every replay is
  therefore `INCONCLUSIVE`; #131 owns real completeness/labels and #132 actual cost/token
  evidence. These are not #110 offline closure gates. The unmerged #129 candidate adds
  synthetic YOE policy and
  offline assessment-cost/evaluation mechanics; it supplies no approved profile, labels,
  source roster, actual price evidence or model-quality result. The profile CLI rejects
  path aliases and malformed inputs with bounded errors; replay preserves daily K,
  deterministic recency/role baselines and grouped membership.

- **Issues #111/#112 shadow assessment and evaluation** have an unmerged integration
  candidate in PR #129 (`rehearsal/preselection-124-125`), based on current `main`.
  It retains immutable `RunBinding` and
  schema-4 journals, validates direct/extracted assessment inputs, bounds retries and
  accounting, requires the matching validated cohort before bound assessment execution
  (including resume/cache and standalone extraction), rejects outside jobs and undeclared
  variants/draws. It rechecks cohort content hashes and actual model/limits/retry
  declarations before execution, hashes the split seed, bounds malformed JSON/timestamp errors, and emits
  aggregate-only synthetic evaluation reports from revalidated manifest/journal snapshots;
  report inputs with changed labels, baselines, outcomes or provenance are rejected. A fresh-process direct fake-provider run
  now blocks legacy score/fit/profile/prompt/config/runtime imports and text, YAML and
  `.env` file reads. Worker coverage is 85.11% with the
  existing 85% threshold unchanged. #111 remains open pending scoped
  offline acceptance/merge under #130; #112 remains `INCONCLUSIVE` with no GO. No live/external provider call, real label, approved live policy, production wiring,
  database write or runtime selection is included.
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

1. [#130 offline completion](https://github.com/drink970082/job-matchbook/issues/130)
   is selected first: record scoped #109 contract acceptance, audit all revised offline
   #110/#111/#116 criteria against the exact final #129 head, make an explicit offline
   merge decision, verify the accepted merge and disposition superseded #124/#125.
   Keep issues open until evidence and merge are recorded. Real input, pricing and live
   approvals do not block this hermetic slice; the split itself accepts no contract or merge.
2. [#131 real cohort and labels](https://github.com/drink970082/job-matchbook/issues/131)
   owns approved profile/policy inputs, independent source-pool completeness, real grouping
   and blind/adjudicated labels. It is deferred behind offline completion and requires
   the relevant operator/private-input authorization.
3. [#132 authorized provider pilot](https://github.com/drink970082/job-matchbook/issues/132)
   owns actual request tokenization, adapter compatibility, pricing, usage/charge and
   bounded pilot evidence. It requires #131, accepted offline tooling, #109 real decisions
   and separate live-call authorization; this plan schedules no provider calls.
4. #112 retains comparative/held-out evaluation, workflow-cost comparison, predeclared
   tolerances and explicit GO/NO-GO/INCONCLUSIVE. Closing offline #110/#111/#116 does not
   satisfy #112 or authorize production. #94/#96 live selection gates remain applicable.
5. [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94)
   still needs unattended access/delivery evidence. #95 remains deferred; #113/#114
   production integration and #115 unattended acceptance retain their own gates.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.
Astra/Sol owns architecture/docs/acceptance; all implementation/fixes go to Luna/max.
The current runtime Luna/medium screening configuration is a separate concern.

## Current implementation limitations

- PRs #124/#125 remain unmerged drafts. Their provider-free modules are composed in
  unmerged PR #129 on current `main`; review must preserve `RunBinding`, journal schema 4
  and the 85% worker-coverage gate. No provider inference or #112 GO is authorized.

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
