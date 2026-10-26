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
| Browsing unscored jobs in the UI | Fit buckets limit visibility | Priority feature |
| JD refresh and liveness for unscored rows | Incomplete | Priority data-quality work |
| Daily Brief using ATS plus web | User workflow, unattended acceptance outstanding | Preferred judgment/delivery experience |
| Saved recommendation history and web-job imports through MCP | No write tools | Deferred, separately designed |
| JEV/System One assistance | Not implemented in ATS | Optional experiment, after a measured need |

## Delivery sequence and issues

Issues own scope, dependencies and status; this document owns product order. Labels
classify work, not execution readiness. Astra/Sol owns architecture/docs/acceptance;
Luna at max effort owns all implementation and fixes. See [DEVELOPMENT](DEVELOPMENT.md#agent-ownership-and-handoff).

| Order | Deliverable | Dependencies / selection | Execution |
|---|---|---|---|
| Early, alongside batch 1 | [#90 Research workflow baseline](https://github.com/drink970082/job-matchbook/issues/90) ([report](reports/2026-10-22-ats-chatgpt-research-baseline.md)) | None | Orchestrator read-only workflow evidence |
| Batch 1 | [#91 Research MCP queries](https://github.com/drink970082/job-matchbook/issues/91) | Scoped plan on main | Luna/max implementation, Astra/Sol acceptance |
| Batch 2 | [#92 Visible job inventory](https://github.com/drink970082/job-matchbook/issues/92) | #91 accepted/merged | Luna/max implementation, Astra/Sol browser acceptance |
| Next design | [#93 Source lifecycle](https://github.com/drink970082/job-matchbook/issues/93) | #91, #92; separate schema/policy design | Orchestrator designs before Luna assignment |
| Workflow gate | [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94) | #90, #91, #92; need not wait for all #93 | Orchestrator verifies actual unattended access |
| Conditional extension | [#95 Delivery ledger](https://github.com/drink970082/job-matchbook/issues/95) | #94; observed repeats and write design approval | Deferred |
| Final optional capability | [#96 Luna fit pre-ranking](https://github.com/drink970082/job-matchbook/issues/96) | #94; demonstrated throughput gap | Deferred; unnecessary if scheduled ChatGPT suffices |

#93 and #94 may progress alongside each other. Until lifecycle improvements ship, the
Brief verifies official pages and discloses freshness limits. #95 and #96 are independent
conditional branches after #94, not mandatory stages. Model experimentation remains last
priority; retaining scorer code does not schedule its deployment or a corpus rebuild.

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

#93 requires a separate scoped design. Inventory fetch/title/location gates before any
change; separate collection scope from personal judgment without silently broadening intake.
Define last-seen/check/content revision and availability independently of assessments and
user actions. Mark old judgments stale after JD changes rather than rerunning all models.
Keep age retention separate from closure, protect applications and associated evidence,
and preserve thin/missing/fallback-date information. Do not revive old mass backfills.

Acceptance: supported unscored jobs can refresh; changed JD and stale assessment are
recognizable; timeout/blocked/ambiguous responses are not confirmed closure; application
history remains intact. Expand adapter coverage deliberately rather than claiming all
sources have identical closure signals.

The [source-lifecycle design](superpowers/specs/2026-10-23-source-lifecycle-design.md)
and [implementation plan](superpowers/plans/2026-10-23-source-lifecycle.md) are drafts
awaiting operator approval; no production implementation has started.

## R3 — ChatGPT workflow acceptance

#90 starts early with a small manual ATS+web research sample and records tool friction.
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
these plans. First observe whether scheduled ChatGPT can retrieve and judge useful
candidates at the needed volume. If yes, #96 need not produce any scorer rollout.

Only a demonstrated bottleneck selects a bounded pre-ranking experiment. Astra/Sol defines
representative evidence-supported cases and recall/top-of-list usefulness criteria; Luna/max
implements after scope/workload approval. Existing model guards/rubric stay intact until
separately validated. No whole-database scoring, legacy corpus rebuild, model downgrade or
Telegram rollout is required for R1–R3. See [EVALUATION](EVALUATION.md).

## Deferred extensions and pick rule

#95 may precede any model work if repeated recommendations become the actual bottleneck.
Web-job import, agent-invoked refresh, standard search/fetch compatibility and JEV/System
One remain unselected ideas, not scheduled dependencies. Writes need explicit provenance,
authorization and lifecycle contracts. Prefer source quality, retrieval and verified user
workflows; choose further inference only when those observations justify it.
