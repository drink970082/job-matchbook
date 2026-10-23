# Source lifecycle implementation plan

**Status:** draft — execution waits for approval of [the source-lifecycle design](../specs/2026-10-23-source-lifecycle-design.md).

**Issue:** [#93](https://github.com/drink970082/job-matchbook/issues/93)

This plan is for Luna/max after the operator approves the design and selects the pilot
source. It does not authorize a production refresh, broad backfill, data cleanup, model
call, service restart, or deployment.

## Sequence

1. **Reconfirm boundaries.** Inspect current intake gates and the **posted_at** fallback
   path in the selected branch. The first release updates only already-stored postings
   without a fit assessment, link to an application, or an applied/removed/scored/notified
   state. It does not change gate defaults or date interpretation.
2. **Add the persisted contract.** Add the selected source snapshot/revision fields to
   **apps/web/prisma/schema.prisma**. Keep the worker fixture schema synchronized through
   the repo's schema guard; the worker issues no DDL. Back up any local database before
   applying schema changes.
3. **Implement bounded refresh.** Add pure candidate selection and result
   classification, with clock/fetch dependencies injected. Validate exact
   **(source, external_id)** identity before any write. Keep request work per-item isolated
   and all SQLite writes on the main thread.
4. **Preserve prior evidence.** Update source content only from a valid exact-ID payload.
   On changed assessment inputs, increment the revision and expose stale prior
   assessments without rerunning screen or fit. Recheck that the row still has no fit
   assessment or application link and remains in an eligible unscored state in the
   write transaction.
5. **Expose the contract.** Add truthful source and assessment-freshness summaries to
   tracker and read-only MCP results. Unknown, stale, provider error, and confirmed
   closed must remain distinguishable. Never expose raw exception text or full JD text
   in list summaries.
6. **Roll out narrowly.** After merge/deployment is separately authorized, run one
   selected adapter against at most 25 existing unscored rows. Record counts for
   found/unchanged, changed, confirmed closed, inconclusive, and skipped. Do not run an
   unrestricted backfill.

## Acceptance evidence

- Same source/external ID is updated as a source observation; another ID or source is
  rejected before any write.
- An unchanged valid JD updates observation/check times without incrementing its content
  revision or marking current assessments stale.
- A changed title, location, or description updates the stored evidence and revision;
  old versioned assessments are stale, their payloads and application/history remain,
  and no screen/fit provider is called.
- Timeout, connection error, 403, 429, 5xx, malformed JSON, redirect/interstitial, blank
  body, and partial body remain inconclusive and do not clear the prior full JD or create
  confirmed closure. Safe error categories are visible.
- Only the selected adapter's verified terminal signal can set confirmed closure.
  A later exact valid result reopens source availability without resetting pipeline or
  user state.
- Rows with a provider error, legacy assessment without a source revision, missing JD,
  and unknown source state are displayed without implying a pass or closure.
- Candidate selection uses assessment presence rather than score alone, includes only
  the known eligible unscored states plus the explicit source and limit, and skips
  malformed/unknown lifecycle values without crashing. Application/status changes
  between fetch and write prevent stale writes.
- Existing intake filters, scrape-date fallback, fit buckets, and applied history are
  unchanged. Closed evidence does not trigger retention or deletion.

Use synthetic fixtures for these cases. A live board fetch, live database write, or
production scheduling run is a separate, explicitly bounded acceptance action.

## Required documentation on implementation

Update the shipped source/assessment contract and its SPEC §9 invariant-to-test row only
when code is accepted. Remove this draft claim from PROGRESS when the work lands and add
the shipped behavior to SPEC and CHANGELOG in that implementation PR.
