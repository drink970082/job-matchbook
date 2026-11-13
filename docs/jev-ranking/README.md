# JEV ranking delivery — start here

**Status:** approved product direction and planning baseline; execution remains gated.

JEV is the ranking system. It produces domain-specific review priorities that ChatGPT
retrieves through read-only MCP, together with full source evidence and coverage state.
ChatGPT performs deeper interpretation and final recommendations; the user applies.

## Read order and source of truth

1. Repository AGENTS and DEVELOPMENT, then PROGRESS's In flight registry.
2. [Design](design.md): ownership, contracts, lifecycle and failure behavior.
3. [Research](research.md): hypotheses, datasets, metrics, stopping rules and gates.
4. [Delivery](delivery.md): dependency graph, Sol/Luna work packages and handoff template.
5. The assigned GitHub issue and the exact accepted revision of these documents.

These documents define the selected JEV delivery track. Issues own scope, dependencies,
acceptance and status; these documents own shared contracts and execution detail.
SPEC remains the authority for shipped behavior. None of the target contracts here is
claimed to be deployed. Architectural changes return to the orchestrator; do not silently
resolve a conflict by implementing an older research plan.

## Authority and current limits

The operator approved organizing the proposed architecture and roadmap into docs/issues.
Current work is documentation only. This does not authorize production implementation,
new paid or subscription inference, database changes, service restarts, deployment,
research PR #134 merge, or a historical-inventory scoring run. Future assignments must
name their exact permitted side effects. Previously unused research budget is not new
execution permission. No heavy human worksheet is a prerequisite for this track.

For this track the operator's explicit assignment overrides the repository's general
Luna-only implementation convention: **Sol handles large/uncertain work, Luna handles
bounded work once its contract is fixed.** The orchestrator designs, accepts and delegates;
it does not implement or run experiments. No automatic child-agent dispatch is required
by reading this document.

## Existing evidence, not inherited requirements

Research code and reports live on `feat/openrouter-jev-shadow`, draft PR #134, recorded
handoff commit `16deac2`. Read the actual branch before selecting code. [Pinned research tree](https://github.com/drink970082/job-matchbook/tree/16deac2/docs/reports) supplies the reports below. Do not merge the
whole PR as a product prerequisite. Reports under that revision:

- `docs/reports/2026-11-12-jev-convergence-checkpoint.md`: stable semantic mistakes.
- `docs/reports/2026-11-12-jev-guard-validation100-checkpoint.md`: 416 valid calls,
  94/100 repeated final tiers, 34/100 review cases; no accuracy or guard superiority proof.
- `docs/reports/2026-11-13-sol-low-blind20-crosscheck.md`: 15/20 preferred-tier matches,
  9/20 review after model cross-check; model proxies, not human truth.
- `docs/reports/2026-11-13-jev-fixed-skill-evidence20-checkpoint.md`: 16/16 main repeated
  vectors, selected requirements only, no complete automated extraction proof.

These are reported historical observations, not tests rerun by the planning session.
Private manifests, profiles, JD corpora and ledgers stay outside git. The previous campaign
reports 1,744 attempts and USD 0.568324876, with no pending/unknown/overreserve. Preserve
all ten linked ledgers and closed epochs; future authorized research must reconcile them
before extending accounting, never reset the budget. Codex usage is separate, not free.
Locate approved private artifacts through the operator-local handoff; public docs contain
no private source excerpts or résumé facts. Do not invent a replacement profile if absent.

## Relationship to other plans

#96 remains the broader pre-ranking umbrella. #131/#132/#112 describe older cohort,
provider and comparative scopes; they are not automatically completed by this track.
Their mandatory extracted arm, human-gold workflow, inherited execution framework and
legacy selection prerequisites are not requirements of the selected minimal JEV track.
Their evidence may be reused with provenance; obsolete ticket text must not authorize
calls or override this handoff. A later reconciliation may close obsolete scopes as
superseded, never as experimentally passed. #94 unattended Daily Brief acceptance remains
separate: interactive MCP success does not prove Scheduled access.

The skill composition/splitting proposal remains deferred. Old score modules, prompts,
evals and labels are neither implementation dependencies nor quality truth for JEV.

## Issue index

Parent: [#135 — JEV ranking delivery](https://github.com/drink970082/job-matchbook/issues/135). All packages are unassigned.

| Package | Owner | Issue |
|---|---|---|
| P0 | Sol | [Freeze JEV ranking contracts and audit integration/reuse](https://github.com/drink970082/job-matchbook/issues/136) |
| P1 | Sol + bounded Luna | [Prepare frozen ranking cohorts, baseline and evaluation contract](https://github.com/drink970082/job-matchbook/issues/137) |
| P2 | Sol lead; Luna bounded execution | [Evaluate minimal JEV ranking under an authorized fixed budget](https://github.com/drink970082/job-matchbook/issues/138) |
| P3 | Sol | [Deliver one-job JEV ranking persistence through MCP](https://github.com/drink970082/job-matchbook/issues/139) |
| P4 | Luna; Sol for state-machine decisions | [Run bounded ranking batches with visible recovery over MCP](https://github.com/drink970082/job-matchbook/issues/140) |
| P5 | Sol | [Validate ChatGPT consumption of ranking through real MCP](https://github.com/drink970082/job-matchbook/issues/141) |
| P6 | Luna execution; Sol acceptance | [Prepare and accept a controlled JEV ranking rollout](https://github.com/drink970082/job-matchbook/issues/142) |
