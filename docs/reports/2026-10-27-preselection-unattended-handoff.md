# Preselection unattended acceptance handoff

**Status as of 2026-10-27:** unattended acceptance is not complete. This is an execution
handoff only. No Scheduled task was created or observed, no live evaluation/provider call
or operator GO was recorded, and no preselection runtime or delivery path was activated.
This session has read-only MCP access but no Scheduled management interface.

## Current evidence

| Gate | What is available | What is still missing |
|---|---|---|
| #94 Daily Brief | [Task instructions and checklist](2026-10-23-daily-brief-instructions.md); documented interactive preflight and MCP checks | A task created in ChatGPT web/desktop, actual Scheduled tool discovery/private-file access, and an observed unattended run recorded from Scheduled history |
| #112 evaluation | Local offline manifest/report implementation and synthetic tests; its procedure defines prerequisites and open approvals | Human labels/cohort, provider evaluation and measured charges, accepted thresholds, #94 acceptance, and operator GO/NO-GO/inconclusive decision |
| #113 assessments | Local docs-only scope at `8d9d574` | Reviewed Prisma persistence/history design, approved read contract, implementation, and independent review |
| #114 review batches | Local docs-only scope at `f476893` | Approved capacity/fairness/aging/replacement policy, batch persistence and trigger contract, implementation, and independent review |
| #115 unattended rollout | Dependency and acceptance role described in the [preselection design](../superpowers/specs/2026-10-26-fit-preselection-design.md) | Accepted #112 decision, completed/reviewed #113 and #114, #94 evidence, observed unattended shadow behavior, monitoring, and bounded rollback evidence |
| Remote review | Local commits and checks are recorded in [PROGRESS](../PROGRESS.md) | GitHub DNS/token access, remote reconciliation, draft PRs with explicit `main` base, and independent review |

The [#112 procedure](../superpowers/specs/2026-10-27-preselection-evaluation-procedure.md)
marks its fixture synthetic and its decision `not_recorded`. A successful synthetic report
or interactive MCP session is not unattended acceptance or model-quality evidence.

## #94 acceptance still required

Use the actual ChatGPT Scheduled view and run history. Follow the checklist in the linked
task instructions and record each item as observed, failed, or not exercised. At minimum:

- Create the task in ChatGPT web or desktop at 20:00 America/New_York if the account
  supports it; record the displayed timezone and next run. If that time is unavailable,
  record the limitation rather than substituting a paid scheduler or claiming success.
- Confirm the actual task—not only an interactive chat—can discover and use the read-only
  ATS MCP tools, web search, private candidate preferences, and the relevant résumé.
- Observe complete pagination, a multi-chunk full JD, the literal empty-result probe, and
  failure handling from the task's run history. Do not create a production outage. Use the
  documented safe failure probe if it still produces an access failure; if it is
  accessible in Scheduled, exercise another naturally failing source.
- Verify official-source citations and data cutoff, source/freshness unknowns, confirmed
  application exclusion, probable-duplicate review, visible partial failures, and no
  side effects or private-context echo.
- If the workflow handles the useful inventory within the review budget, stop the
  preselection experiment. If it does not, document the measured gap before authorizing
  further evaluation.

The checked-in interactive observations are useful preflight only. They do not establish
Scheduled access, file access, unattended delivery, or 20:00 eligibility.

## #112 decision and dependent work

Before any live evaluation, complete the gates in the #112 procedure: reconcile/review
the local code prerequisites, approve the candidate profile and label guide/cohort,
freeze the split and assessment/selection policy, explicitly authorize provider/model,
attempt and cost ceilings, and set held-out acceptance values. Unknown pricing is not zero;
subscription allowance is not a monetary rate. No one should infer these approvals from
the synthetic fixture or from this handoff.

After accepted held-out evidence, record exactly one decision—GO, NO-GO, or inconclusive—
with rationale. GO authorizes only the scoped review/implementation of #113 and #114. It
does not authorize a production model, schedule, migration, provider activation, or new
runtime default. NO-GO or inconclusive stops dependent production work.

#113 and #114 are currently design-only local branches. Their scopes intentionally leave
the assessment persistence model, read API shape, capacity, fairness, queue aging,
replacement limits, trigger, and cross-day acknowledgement open. Resolve and review those
contracts before implementation. The #95 delivery ledger is not selected; a persisted
selection batch proves selection only, not reading or delivery. Do not promise cross-day
deduplication without an approved acknowledgement design.

## #115 acceptance after dependencies

The operator/orchestrator should use the current #115 issue body once remote access is
restored; it could not be re-fetched in this session. The local preselection design
requires unattended shadow operation, monitoring, and rollback to bounded unranked
retrieval before seeking a separate runtime-activation decision. Record evidence for:

- The exact accepted profile, policy/model identities, resource ceilings, and rollout
  mode; the deployed mode remains explicitly default-off until separately authorized.
- Batch creation/resume, source and application revalidation, age/overflow reporting,
  bounded replacements, failure behavior, and all resource ceilings under unattended
  operation.
- Monitoring for assessment staleness, provider errors, queue age, low-rank misses,
  unfilled capacity, source failures, and unknown cost, with thresholds chosen before
  observing acceptance results.
- A tested rollback path to bounded unranked candidate retrieval that preserves the
  assessment/batch evidence and does not change application history.
- A separate operator decision for runtime activation. Passing #115 must not silently
  change defaults or start a schedule.

The amount of unattended observation and the numeric monitoring thresholds are not
chosen here. Confirm them against the live #115 issue and approved #112 policy before
starting acceptance.

## Immediate next actions

1. Restore GitHub DNS and valid repository authentication. Fetch `main`, current #107 and
   issue bodies #109–#116; verify every local base and prerequisite before publishing.
2. Push the completed local branches and open focused draft PRs with `--base main` once
   remotes are available. Disclose stacked prerequisite commits and included diffs. Keep
   them draft and obtain independent review; no merge is authorized by this handoff.
3. Run #94 in ChatGPT web/desktop and complete its run record. Keep the workflow read-only.
4. If a measured gap remains, finish the #112 approvals, explicitly authorize live
   evaluation limits, run the accepted evaluation, and record GO/NO-GO/inconclusive.
5. Only after GO, review/approve #113's persistence/read contract, then #114's queue
   policy; implement each as a separate reviewed slice. Complete #115 unattended
   acceptance and rollback evidence before seeking runtime activation separately.

This handoff does not report an acceptance pass, delivery success, GO decision, merge, or
deployment.
