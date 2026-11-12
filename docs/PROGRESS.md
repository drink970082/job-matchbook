# Job Matchbook — active work

Job Matchbook is a job-source, tracking and tool layer for ChatGPT-led research and
recommendations. Optional screening **and fit scoring remain supported**.
[ROADMAP](ROADMAP.md) owns product order; [ARCHITECTURE](ARCHITECTURE.md) separates
current implementation from target responsibilities; [SPEC](SPEC.md) describes shipped
behavior. Completed work belongs in CHANGELOG, not this queue.

## In flight

- **OpenRouter JEV native shadow integration — `feat/openrouter-jev-shadow`**.
  The implementation is on the branch and draft PR #134 is awaiting review. It provides
  native Choice/Noul/Score transport, durable accounting and a
  direct-only evaluation mode for pilots that collect no labels. A separate mechanics-only
  pilot is authorized for 10 real JDs and the existing 11 questions, with at most 12 model
  attempts including retries, 15 minutes, USD 1 and 24 KB per request. Explicit token-price
  and platform-fee evidence must bound cost; an absent API request-price field is not
  treated as a free call. The private mechanics evidence contains 10 provider responses
  and 110 format-validated answers: nine live successes and one original failed attempt
  whose retained response validates offline after the usage-metadata fix. The original
  failure remains recorded. The 10 dispatched attempts have no retries or unknown charges;
  their provider-reported total is USD 0.002003148, not invoice-audited. Quality labeling,
  independent grouping and comparative evaluation remain open. There is no GO or production
  wiring. The operator authorizes a cumulative USD 10 JEV research ceiling, including
  prior inference spend, toward stable production-ready advisory scoring. The
  [convergence plan](superpowers/plans/2026-11-11-jev-stable-scoring-convergence.md)
  proposes small development, independent expansion, locked tests and runtime shadow,
  with batched operator adjudication and separate proxy/operator-confirmed evidence.
  Stage 0/1 execution is now selected under the
  [approved bounded contract](superpowers/specs/2026-11-11-jev-convergence-stage1.md):
  an isolated campaign ledger/repeat reporter and ten development jobs × three fresh
  draws, maximum40newattempts/15minutes/USD0.50includingpriorcost. The new isolated
  campaign ledger and repeated-draw reporter are implemented on this branch and accepted
  for bounded Stage 1 execution after worker and blocked-legacy checks. Private v2 profile/questions and the 10×3 cohort are frozen before
  calls; no deployment GO. The implemented
  [duty classification plus preference arbitration](superpowers/specs/2026-11-11-jev-preference-arbitration.md)
  keeps raw answers separate from derived tiers. Frozen v6 development observations
  cover ten jobs × six fresh calls in two batches: preference, engineering-primary,
  avoidance and overall skill descriptors all agree; work-interest alignment is split
  high/moderate on one vague-duty job and remains explicitly uncertain. Six source-bound
  skill sidecars cover16selectedrequirements with identical three-draw support; annotations
  remain proxy/selected-only, not human gold or an automatic requirements collector.
  The retained ledger has177new/187totalattempts, cumulativeUSD0.038861424includingpriorcost,
  no pending/unknown/overreserve, and two distinct-auth cap amendments preserving history.
  The effective cap is200; the78-call skill slice is complete under its80newattemptlimit.
  [Forty-job provider-free preparation](superpowers/plans/2026-11-12-jev-validation40-preparation.md)
  freezes new source payloads from30companies with no model calls or labels yet. The
  operator now directs continuous execution until intervention/session-limit/USD10exhaustion,
  with no overfitting, unnecessary complexity or invented missing JD facts. Forty-job
  pre-model proxy labeling/grouping and then120freshcalls are selected under a retained
  cap200→400amendment; routine milestones do not require renewed permission. Exact
  duplicates are excluded; grouping/labels and declared mobile/sales coverage gaps remain.
  Thirteen over-bound full payloads were omitted, never truncated. Do not run expansion
  before source/label/batch bindings and its append-only cap authorization are frozen. The
  operator explicitly requires isolation from legacy score/eval modules, prompts, corpora
  and score-derived truth; new entrypoints must pass blocked-import/resource checks.

- **#131 real cohort and blind/adjudicated labels** — deferred pending version-scoped
  completion of the independent quality-evidence work. Candidate-content review and
  approval records remain private/local. A partial 10-item mechanics snapshot is frozen
  locally with labels not collected; it does not satisfy #131's full roster, grouping or
  blind/adjudicated quality-truth gates. Missing evidence remains `INCONCLUSIVE`.
- **#132 authorized provider research** — the mechanics evidence remains separate from
  the newly authorized cumulative USD 10 convergence campaign. Exact batches/model/input
  bindings and resource reservations must be recorded before further inference. No
  quality-label, quality-estimate or GO claim is established by spending authorization. Preserve explicit
  rate/fee evidence and the missing API request-price field as separate provenance;
  full-request tokenization and observed charges remain pilot evidence, not established
  defaults. The mechanics sample and local audit are available; the staged convergence
  plan governs preparation of new calls rather than an unattended recurring schedule.
- **#112 comparative evaluation and GO/NO-GO** remains `INCONCLUSIVE`. It consumes the
  accepted offline tooling plus #131/#132 evidence, compares against the current workflow,
  and owns the final decision. No runtime selection or activation is authorized.
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

1. [#131 real cohort and labels](https://github.com/drink970082/job-matchbook/issues/131)
   owns approved profile/policy inputs, independent source-pool completeness, real grouping
   and blind/adjudicated labels. Start only after version-scoped approval of the exact
   inputs and private-input access; no private file has been read for this work.
2. [#132 authorized provider pilot](https://github.com/drink970082/job-matchbook/issues/132)
   owns actual request tokenization, adapter compatibility, pricing, usage/charge and
   bounded pilot evidence. It requires #131, accepted offline tooling, #109 real decisions
   and separate exact provider/model/resource-limit authorization; no provider call is
   scheduled.
3. #112 retains comparative/held-out evaluation, workflow-cost comparison, predeclared
   tolerances and explicit GO/NO-GO/INCONCLUSIVE. Closing offline #110/#111/#116 does not
   satisfy #112 or authorize production. #94/#96 live selection gates remain applicable.
4. [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94)
   still needs unattended access/delivery evidence. #95 remains deferred; #113/#114
   production integration and #115 unattended acceptance retain their own gates.

[ROADMAP](ROADMAP.md) links every issue and dependency. Issues own status; this file
owns active branch claims. Documentation plans do not launch agents or deploy services.
Astra/Sol owns architecture/docs/acceptance; all implementation/fixes go to Luna/max.
The current runtime Luna/medium screening configuration is a separate concern.

## Current implementation limitations

- Frozen replay validates supplied artifacts but cannot establish independent real source
  pool completeness or human labels. Replay therefore remains `INCONCLUSIVE` until #131
  supplies those inputs. No provider inference, observed price, #112 GO or runtime selection
  is authorized; #132 and #112 retain those gates.

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
