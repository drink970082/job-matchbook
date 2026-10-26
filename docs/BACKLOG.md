# Backlog — current triage

[ROADMAP](ROADMAP.md) owns the R1–R4 product order. This file holds residuals and
optional extensions; [PROGRESS](PROGRESS.md) owns branch claims. Detailed unresolved
investigations live in [ENGINEERING_CATALOGUE](ENGINEERING_CATALOGUE.md), not in the
session boot path. Revalidate an entry against current code and data before selecting it.

## Relevant to the source/tool product

- **Source lifecycle adapter coverage:** the bounded one-shot refresh supports
  SmartRecruiters; other boards need verified source-specific identity and closure
  signals before they can be refreshed safely. No broad backfill is selected.
- **JD quality:** thin/bodyless Microsoft and recipe rows, detail-fetch failures and
  date fallbacks need per-source observation. Full-JD quality is useful to ChatGPT even
  when no scorer runs. Large legacy backfill counts require fresh dry-runs.
- **Intake policy:** inspect title/location/age gates before moving preferences to
  ChatGPT. Cutting discovery to match the old fit budget is not the product priority.
- **Visibility:** show unscored jobs, standalone screen evidence and unknown/provider
  error states; expose queue counts and source/assessment freshness. Part of R1.
- **Usage telemetry:** the generic combined pipeline still has best-effort HTTP snapshot
  capture with intermittent 403 failures; screen-only bypasses it. Host-only monitoring
  must not be mistaken for a shipped generic telemetry fix or a hard spend limit.
- **Infrastructure:** retain SQLite directory/WAL mounts, health/autoheal verification,
  schema ownership, privacy boundaries and SSRF residual review for future fetch tools.
- **Data integrity:** application uniqueness/identity, literal URL matches vs normalized
  requisitions, schema migration strategy and excluded web integration coverage remain
  scoped maintenance questions, not reasons to alter application history in this pivot.

## Issue ownership

The open workflow gate and conditional extensions are linked in ROADMAP.
Their status/dependencies live on GitHub; this file retains background and unselected
ideas. Fit pre-ranking (#96) is last priority and may never be enabled if scheduled
ChatGPT meets the need. Recommendation history (#95) is conditional on observed repeats.

## Optional scorer work

- Keep screening and fit code, prompts, adapters and hermetic tests. Do not delete them
  as cleanup. Current Luna/medium deployment is screening; optional fit remains separate.
- The expanded Luna screen result has no recorded effort. Do not claim medium-specific
  accuracy or start a large unchanged eval to repair provenance automatically.
- Legacy fit gate labels need supported inline inputs and human review before a fit
  behavior change can rely on them. Finishing the blind-review/rebuild campaign is not
  selected work. Inventory and gate scope are in [EVALUATION](EVALUATION.md).
- Bullet-list sponsorship snippets, blind/empty answer handling and local-model degree/
  clearance limitations remain relevant when changing the screen. Read SCORING and
  REJECTED before revisiting them.
- More providers, score calibration, cache experiments and seniority-veto tuning require
  a demonstrated need and a specific evaluation question; none blocks R1–R3.

## Deferred extensions

- Narrow MCP writes for external-job import, saved assessments or Brief delivery history.
- Agent-invoked official-page refresh and existing-fetch interaction, with bounded inputs
  and explicit mutation/authorization semantics.
- Standard search/fetch compatibility for clients that require it.
- JEV/System One shadow classification or review ranking; no default paid dependency.
- New boards and bulk onboarding after choosing actual coverage gaps. Follow onboard-board;
  do not add an adapter when a reviewed recipe suffices.

## Cleanup policy

Keep private corpora, human answers, reports and unmerged branch work intact. Preserve
negative findings; remove obsolete universal priorities and instructions to repeat them.
The engineering catalogue is not authority to spend allowance or restart a deferred run.
Do not infer that a planned feature, an old passing experiment or a host-only deployment
script is available in a clean clone.
