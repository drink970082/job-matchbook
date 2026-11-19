# Backlog — current triage

[ROADMAP](ROADMAP.md) owns the product order. This file holds residuals and
optional extensions; [PROGRESS](PROGRESS.md) owns branch claims. Detailed unresolved
investigations live in [ENGINEERING_CATALOGUE](ENGINEERING_CATALOGUE.md), not in the
session boot path. Revalidate an entry against current code and data before selecting it.

## Relevant to the source/tool product

- **MCP free-text arguments that look like JSON are decoded:** the SDK JSON-parses a
  string argument typed `str | None` when it parses as JSON, so a note such as `{"a":1}`
  through `update_application_notes` (or `record_application`'s `notes`) fails
  validation. `set_jev_profile` avoids it with plain `str`; the other text tools do not.

- **Source lifecycle adapter coverage:** the bounded one-shot refresh supports
  SmartRecruiters; other boards need verified source-specific identity and closure
  signals before they can be refreshed safely. No broad backfill is selected.
- **JD quality:** thin/bodyless Microsoft and recipe rows, detail-fetch failures and
  date fallbacks need per-source observation. Full-JD quality feeds the screen, JEV and
  the MCP reader alike. Large legacy backfill counts require fresh dry-runs.
- **Intake policy:** inspect title/location/age gates before moving preferences into the
  DB (#157). Cutting discovery to match a model budget is not the product priority.
- **Usage telemetry:** after a `codex` screen the pass takes one best-effort HTTP usage
  snapshot (`scorer_usage.json`), which has failed intermittently with 403. It is a
  display, not a spend limit; JEV's limit is `--jev-max-usd`.
- **Infrastructure:** retain SQLite directory/WAL mounts, health/autoheal verification,
  schema ownership, privacy boundaries and SSRF residual review for future fetch tools.
- **Data integrity:** application uniqueness/identity, literal URL matches vs normalized
  requisitions, schema migration strategy and excluded web integration coverage remain
  scoped maintenance questions, not reasons to alter application history in this pivot.

## Issue ownership

The open workflow gate and conditional extensions are linked in ROADMAP.
Their status/dependencies live on GitHub; this file retains background and unselected
ideas. Recommendation history (#95) is conditional on observed repeats.

## Screening work

- The expanded Luna screen result has no recorded effort. Do not claim medium-specific
  accuracy or start a large unchanged eval to repair provenance automatically.
- Bullet-list sponsorship snippets, blind/empty answer handling and local-model degree/
  clearance limitations remain relevant when changing the screen. Read SCORING and
  REJECTED before revisiting them.
- More screen providers and cache experiments require a demonstrated need and a specific
  evaluation question.

## Deferred extensions

- MCP writes beyond epic #152's scope: external-job import, saved assessments or Brief
  delivery history.
- Agent-invoked official-page refresh and existing-fetch interaction, with bounded inputs
  and explicit mutation/authorization semantics.
- Standard search/fetch compatibility for clients that require it.
- JEV review *ranking* (#135) beyond the deployed keep/skip filter.
- New boards and bulk onboarding after choosing actual coverage gaps. Follow onboard-board;
  do not add an adapter when a reviewed recipe suffices.

## Cleanup policy

Keep private corpora, human answers, reports and unmerged branch work intact. Preserve
negative findings; remove obsolete universal priorities and instructions to repeat them.
The engineering catalogue is not authority to spend allowance or restart a deferred run.
Do not infer that a planned feature, an old passing experiment or a host-only deployment
script is available in a clean clone.
