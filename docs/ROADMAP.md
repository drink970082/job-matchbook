# Roadmap — ChatGPT-first job research

**Direction:** Job Matchbook supplies reliable job evidence, tracking and tools;
ChatGPT supplies primary judgment, supplemental search and recommendation delivery.
**Screening and the scorer remain supported optional assistance.** This is not a plan
to delete them or require every posting to receive a fit score.

This file orders future work. It does not claim the features below are shipped or
change CLI defaults. [ARCHITECTURE](ARCHITECTURE.md) defines boundaries;
[SPEC](SPEC.md) defines current behavior; [PROGRESS](PROGRESS.md) owns branch claims.

## Feature ownership and readiness

| Feature | Current state | Direction |
|---|---|---|
| Board/feed discovery and JD hydration | Shipped | Core; improve coverage and evidence quality |
| Applications, history, CSV and watchlist UI | Shipped | Core; preserve data and manual workflows |
| Read-only MCP and full-text chunks | Shipped | Core; improve research-oriented queries |
| Standalone Luna/medium screening | Shipped, operator-selected | Retain as low-cost assistance |
| Fit scorer and Telegram notifications | Shipped; bypassed by operator's screen-only mode | Retain opt-in compatibility; no automatic retirement |
| Browsing unscored jobs in the UI | All-jobs inventory and advisory screening are available | Preserve the safe inventory and application-action boundaries |
| Source lifecycle for unscored rows | Bounded one-shot refresh supports SmartRecruiters; other sources remain unsupported | Extend only with verified source-specific identity and closure signals |
| Daily Brief using ATS plus web | User workflow, unattended acceptance outstanding | Preferred judgment/delivery experience |
| Saved recommendation history and web-job imports through MCP | No write tools | Deferred, separately designed |
| JEV/System One assistance | Offline view, batch replay and synthetic rehearsal are available; live path remains gated | Repair unmerged #111/#112 mechanics before live evaluation |

## Delivery sequence and issues

Issues own scope, dependencies and status; this document owns product order. Labels
classify work, not execution readiness. Astra/Sol owns architecture/docs/acceptance;
Luna at max effort owns all implementation and fixes. See [DEVELOPMENT](DEVELOPMENT.md#agent-ownership-and-handoff).

| Order | Deliverable | Dependencies / selection | Execution |
|---|---|---|---|
| Workflow gate | [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94) | Deployed read-only tunnel and account/workspace task access | Orchestrator verifies actual unattended access |
| Conditional extension | [#95 Delivery ledger](https://github.com/drink970082/job-matchbook/issues/95) | #94; observed repeats and write design approval | Deferred |
| Selected preparation | [#96 Luna fit pre-ranking](https://github.com/drink970082/job-matchbook/issues/96) | Operator reports approximately 200/day exceeds current review capacity | Offline #117–#119 capabilities are available; #111/#112 repair is next assignable work; live gates remain |

The source-lifecycle contract is in [SPEC](SPEC.md). The deployed read-only MCP exposes
source state and check timestamps. Legacy rows without source evidence still require
unknown freshness and official-page availability checks in the #94 Brief. #95 remains a
conditional delivery-history extension. The operator selects provider-free #96 preparation;
[#117/#118/#119's plan](superpowers/plans/2026-10-27-preselection-parallel-preparation.md)
separates that work from #94 unattended evidence and #112 live-evaluation/GO gates.
Retaining scorer code does not schedule deployment or a corpus rebuild.

## R1 — Research queries and visible job inventory

The first two implementation batches share an [approved scope and contract](superpowers/specs/2026-10-22-research-inventory-design.md):

- [Batch 1 plan](superpowers/plans/2026-10-22-batch-1-mcp-research.md): bounded screen
  summaries/outcome filters, opt-in literal full-JD search, screen update windows, eligible
  backlog counts and per-result timestamp correction. Existing read-only tools/defaults
  remain compatible. Current-state pagination uses overlap/reconciliation, not a claim
  of exact event delivery or cross-request snapshots.
- [Batch 2 plan](superpowers/plans/2026-10-22-batch-2-job-inventory.md): default inventory
  without fit prerequisites, standalone screen labels, retained fit views and safe existing
  application actions. No new bulk destructive actions for new inventory views.

Acceptance includes an older posting assessed today, frozen-dataset pagination, concurrent
update limitations, visible provider errors, new unscored jobs and identical list/action
scope. Use synthetic data; never hard-code live application counts. Local checks do not
claim deployment or unattended ChatGPT verification.

## R2 — Source quality and collection policy

The bounded source-lifecycle behavior is specified in [SPEC](SPEC.md): eligible unscored
SmartRecruiters rows can be refreshed with 1–25 exact-ID requests, content changes
invalidate prior assessment freshness, and ambiguous responses do not confirm closure.
Other adapters remain outside the supported refresh contract because their identity and
terminal signals differ. The source-only refresh does not change collection gates,
retention, or application history. The deployed MCP exposes lifecycle fields; a Brief can report stored source freshness
only when those fields contain valid evidence.

## R3 — ChatGPT workflow acceptance

#94 validates an actual unattended task after the retrieval/UI batches. Durable private
preferences, full JD reading, application-history deduplication without posting links,
unknown sponsorship/pay and source failure reporting are required. Company/title similarity
is a review signal, not verified requisition identity. No fixed ATS/web recommendation quota.

The [interactive baseline](reports/2026-10-22-ats-chatgpt-research-baseline.md) exercised
MCP pagination, complete JD chunks and application URL comparison. It does not establish
the source freshness cutoff or unattended ChatGPT access; #94 must verify those against
the deployed tunnel and an actual scheduled run.

Use the [Daily Brief task instructions](reports/2026-10-23-daily-brief-instructions.md)
to prepare and accept the scheduled workflow. They are an example, not evidence that the
operator's ChatGPT account has the required scheduling and connected-tool access.

At 20:00 America/New_York disclose the evidence cutoff; the worker pass starting then is
not guaranteed complete. Confirm product/account capabilities in the actual environment.
An interactive chat does not prove unattended tunnel access. If scheduling is unavailable,
record the blocker and manual fallback; do not silently introduce paid API orchestration.
Cross-day recommendation dedup remains best-effort without #95's separately approved ledger.

## R4 — Scorer as the final optional capability

Screen/fit adapters, result contracts, tests and manual eval tools remain supported.
The deployed Luna/medium configuration is standalone screening; fit is not enabled by
these plans. The operator reports that approximately 200 daily postings exceed the current
workflow's capacity and explicitly selects pre-ranking preparation. This reported need is
not a new benchmark, model selection, or accepted evaluation result.

The offline assessment projection, fixed-batch replay and fixture consumer are available
under the [preparation contract](superpowers/plans/2026-10-27-preselection-parallel-preparation.md).
Next assignable Luna/max work is the [#111/#112 repair handoff](superpowers/plans/2026-10-29-preselection-shadow-repair-handoff.md).
Those synthetic corrections do not depend on real provider output, profile approval,
#94 execution or #112 GO. Labels, recall/miss targets, live workload and
provider/model/budget approval remain prerequisites for live evaluation; real persistence,
MCP/UI integration and rollout stay gated. Existing model guards/rubric stay intact until
separately validated. No whole-database scoring, legacy corpus rebuild, model downgrade or
Telegram rollout is required for R1–R3. See [EVALUATION](EVALUATION.md).

## Deferred extensions and pick rule

#95 may precede any model work if repeated recommendations become the actual bottleneck.
Web-job import, agent-invoked refresh and standard search/fetch compatibility remain
unselected ideas. JEV/System One has selected preparatory work, with no automatic live
inference or runtime scheduling. Writes need explicit provenance,
authorization and lifecycle contracts. Prefer source quality, retrieval and verified user
workflows; choose further inference only when those observations justify it.
