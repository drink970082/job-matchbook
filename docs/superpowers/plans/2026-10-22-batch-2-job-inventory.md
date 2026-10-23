# Batch 2 — browse the inventory without fit scoring

**Status:** Issue #91 is accepted and merged as PR #99. The #92 implementation is in
[PR #100](https://github.com/drink970082/job-matchbook/pull/100) on
`feat/job-inventory-view`; review is pending and it remains unmerged.
Owner: Luna at max effort. Orchestrator and acceptance: Astra/Sol.
[Issue #92](https://github.com/drink970082/job-matchbook/issues/92).

## Goal and dependency

A user can open Discovered Jobs, find a new unscored posting, inspect its JD and advisory
screen result, and use existing tracking actions without running fit. Read the
[approved contract](../specs/2026-10-22-research-inventory-design.md),
[batch 1 plan](2026-10-22-batch-1-mcp-research.md), its actual merged diff and shared
synthetic outcome fixture. Read DEVELOPMENT/PROGRESS and current SPEC UI contracts.

The implementation branch `feat/job-inventory-view` is based on fresh `origin/main` after
#91 was accepted and merged; it is claimed in PROGRESS and is not stacked on another
feature branch. Astra/Sol rechecked the plan against Batch 1's actual implementation and
the shared fixture before implementation; no unresolved semantic mismatch remains.
No MCP dependency at web runtime: Prisma reads the same database directly.

## Starting points to inspect

- `apps/web/src/lib/actions.ts`: JobBucket, getJobPostings, predicate builders and mutation
  paths; existing bulk removal/reopen safety and application transaction behavior.
- `apps/web/src/components/DiscoveredJobsTab.tsx`, `DiscoveredJobsTable.tsx`, `Dashboard.tsx`:
  view/default/filter propagation, table result text, JD modal and per-row actions.
- `apps/web/src/components/__tests__`, actions tests, existing browser fixtures and Prisma
  schema. The standalone relation exists; no new schema is planned.
- Python MCP summary contract and the shared synthetic cases introduced by batch 1.

## Execution steps

1. **Establish All jobs query tests.** Include all non-removed pipeline states, particularly
   new with no fit. Preserve every legacy bucket's existing membership. Handle unknown
   stored states visibly. All jobs queries/counts must bypass matchedIds/belowBarIds/
   lowContextIds fit-derived scans; malformed legacy score_detail cannot break inventory.
   Tests use synthetic applications and assert preserved associations.
2. **Add standalone summary projection.** Parse result JSON defensively, use the shared
   outcome cases and distinguish standalone from legacy screen/fit evidence. Display model,
   effort and assessment time only when available. Never infer source freshness/open status
   from assessment time or claim a malformed record passed.
3. **Implement inventory filters and search.** Add standalone outcome and metadata/all-text
   controls with batch-1 semantics. Filter before pagination and use stable tie-breaks for
   sorting. Reset page appropriately on filter/search changes and prevent stale responses
   from replacing newer selections. Keep null/empty description behavior meaningful.
4. **Make inventory the default UI.** Default to All jobs only without an explicit existing
   view selection. Default its sort to created_at descending then id descending, so recent
   unscored jobs precede older scored rows; preserve explicit sort choices and existing fit-
   view defaults. Include more than a page of older scored rows in the initial-view test.
   Preserve explicit selections where supported. Keep Matched/Below bar/
   Discarded/Failed/Low context accessible as compatibility views; do not remove their
   evidence or useful actions. An empty inventory explains the result without saying all
   jobs are unsuitable or encouraging an automatic rescore.
5. **Audit action boundaries.** Existing supported actions use the same server-side scope
   as the list, including new filters, or reject unsupported filter combinations. Do not
   rely only on hidden buttons. Existing table-wide bulk selection/actions must not leak
   into All jobs: suppress them and pass sufficient view/filter context to reject unsupported
   new-view mutations server-side. Preserve validated existing-view bulk flows. Per-row
   mark-applied/discard/reopen follows existing eligibility and transaction rules; do not
   delete or overwrite application/history records.
6. **Drive the browser and update docs.** Demonstrate initial view, filter/search, changing
   pages, opening a long JD and existing application actions on synthetic data. Update
   SPEC behavior/traceability, CHANGELOG and PROGRESS for shipped scope. Open a focused
   PR referencing #92 with screenshots or observed steps, checks and limitations.

## Required acceptance cases

| Fixture/action | Expected result |
|---|---|
| Recent new/unscored job plus >1 page of older scored jobs | On the first All jobs page by discovery recency; full JD opens |
| Malformed legacy score_detail on any row | All jobs query/count still works without fit-derived ID scans |
| new + complete disqualified | Visible with explicit advisory reason, no lifecycle mutation |
| provider error / malformed / missing checks | Error or unknown label, never a positive eligibility badge |
| legacy score_detail without standalone row | Legacy evidence shown separately, standalone remains not_screened |
| scored/notified and existing legacy buckets | Existing fit access and bucket behavior retained |
| applied / removed / unknown pipeline state | Applied is labeled, removed excluded, unknown shown honestly |
| description-only search with LIKE metacharacters | Same literal semantics as MCP; full body not dumped in table |
| more rows than one page / equal sort keys | Correct counts and stable pagination on frozen fixture |
| change search/filter while request pending | No stale table overwrite or invalid leftover page |
| bulk action plus restrictive new filter | Exact matching scope or explicit rejection; never broader mutation |
| record with existing application/history | Existing protections and transactions preserved |
| no provider configured | Entire inventory/JD/manual-action demo works without inference |

## Checks and handoff

Run `make test-web` and `make lint`. Run `make test-e2e` against synthetic data, or use
DEVELOPMENT's documented manual-browser alternative with exact steps and observations.
Check shared fixture parity in the worker's relevant targeted tests; no live model test.
Run privacy/diff/link checks and applicable schema guard if schema-facing assumptions
change. CI gates still apply. Do not use the production database for destructive UI tests.

Astra/Sol accepts the exact head using an independent browser demonstration and checks
bulk-action scope, outcome parity and retained application workflows. Send all code/test
fixes to Luna/max. Close #92 only after accepted merge; deployment and live user visibility
are separately reported. No automatic web restart, DB cleanup or schema push.

## Boundaries and handback

No source-lifecycle rewrite, fit ranking, model guard changes, imports, ledger or MCP
writes. The host-only Codex status monitor is not a portable-monitor redesign in this PR.
If the action architecture cannot safely express new filter scope, surface a bounded
refactor proposal to Astra/Sol before widening the change. A new dependency/schema or
material UI scope expansion needs revised design. Goal mode, when explicitly assigned,
ends at this issue's reviewable PR/evidence; it does not start #93–#96 automatically.
