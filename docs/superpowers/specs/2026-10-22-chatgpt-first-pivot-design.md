# ChatGPT-first Job Matchbook direction

**Status:** approved product direction; implementation slices require their own scoped designs.

## Decision

Job Matchbook is the durable job-source, evidence, tracking and collaboration-tool layer.
ChatGPT chat and Daily Job Brief own primary personal judgment, supplemental search and
recommendation delivery. Retain optional screening **and fit scoring**. The operator
considers Luna/medium affordable within an existing approximately US$20/month ChatGPT
subscription; removing the scorer to avoid all allowance consumption is not the goal.
Subscription allowance is finite and distinct from a metered API bill.

The shipped Luna/medium configuration is standalone screening. Existing fit defaults,
model guards, private inputs and eval contracts remain unchanged. This decision does not
assert that Luna/medium is already validated or enabled for fit.

## Scope

This change records the direction and reorganizes documentation, roadmap, feature
ownership and evaluation obligations. It changes no service, CLI default, schema, provider
adapter, production data or private corpus. Match/notify capabilities are retained optional
paths, not mandatory stages of discovery or features to delete in this cleanup.

[ARCHITECTURE](../../ARCHITECTURE.md), [ROADMAP](../../ROADMAP.md) and
[EVALUATION](../../EVALUATION.md) express the current decision and outstanding work.
[SPEC](../../SPEC.md) remains the shipped implementation reference.

## Principles and trade-offs

- Principles 1 and 12: the human applies; private background stays user-controlled;
  scraped text is evidence, never instructions.
- Principles 2 and 3: use deterministic tools for identity, dates and state; expose
  uncertain facts rather than inventing passes or hiding opportunities. ChatGPT may make
  contextual career judgments without claiming those are source facts.
- Principle 4: retain cheap optional assistance; do not require strong-model scoring of
  the whole database or mistake subscription inclusion for unlimited inference.
- Principles 5, 6 and 10: query/source failure must be visible, isolated and testable.
- Principles 9 and 11: Prisma owns schema, SQLite/WAL discipline and application records
  remain intact; any future persistent assessments need explicit provenance and lifecycle.

The tension is between reducing ChatGPT's reading workload and preserving recall.
Resolve it initially with searchable evidence and advisory labels, not an unvalidated
hard-discard model. Preserve current gates until a separately reviewed collection-policy
change defines how exclusions remain visible and what is intentionally collected.

## Alternatives

1. **Delete all screen/scorer code and require no background inference:** not selected.
   It removes useful inexpensive assistance and contradicts the operator's retention choice.
2. **Keep the scorer/Telegram pipeline as the product's mandatory center:** not selected.
   It duplicates ChatGPT judgment and makes source/UI access depend on fit work.
3. **Replace scoring immediately with JEV:** deferred. A typed decision adapter is useful
   only after an ATS-specific experiment; it still has API cost and cannot supply full
   personal-fit explanations. Existing Fantasy JEV adapters are reference code, not ATS
   production capability or evidence of job-screen accuracy.
4. **ChatGPT-primary with optional scorer assistance:** selected. Keep durable facts and
   tracking in ATS; make primary judgment a user-facing ChatGPT workflow.

## Boundaries and acceptance

- Read-only MCP remains read-only; no imports, saved assessments or delivery receipts
  are implied. Application-history deduplication must work without posting links.
- Existing combined CLI behavior and tests remain supported; no runtime deployment or
  model change occurs merely because the roadmap changes.
- Old experiments lose roadmap priority, not their negative findings, private artifacts,
  branch ownership or protection against known regressions.
- Feature-readiness documentation distinguishes shipped functions, operator deployment,
  target architecture and deferred proposals. Docs links and command descriptions agree.
- No live model evals, relabel runs, corpus deletion or production cleanup are required
  to accept this documentation decision.
