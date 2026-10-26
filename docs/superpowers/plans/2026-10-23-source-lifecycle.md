# Source lifecycle implementation plan

**Status:** shipped 2026-10-25

**Issue:** [#93](https://github.com/drink970082/job-matchbook/issues/93)

This plan records the shipped **SmartRecruiters** source-refresh contract. A production
refresh, broad backfill, data cleanup, model call, service restart, or deployment is
outside its scope.

## Sequence

1. **Keep the boundary.** The current intake gates and **posted_at** fallback
   path in the selected branch. The first release updates only already-stored postings
   without a fit assessment, link to an application, or an applied/removed/scored/notified
   state. It does not change gate defaults or date interpretation.
2. **Persist source and assessment revisions.** Add the source snapshot/revision fields to
   **apps/web/prisma/schema.prisma**. Keep the worker fixture schema synchronized through
   the repo's schema guard; the worker issues no DDL. Back up any local database before
   applying schema changes.
3. **Refresh within a hard bound.** Use pure candidate selection and result
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
6. **Keep operation explicit.** The CLI requires one selected adapter and accepts at
   most 25 requests. The implementation does not run a live refresh or unrestricted
   backfill by itself.

## SmartRecruiters pilot contract

This adapter-specific brief documents the implemented pilot. The existing adapter requests
`GET https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings/{postingId}`
and builds **external_id** from the response's **id** field. Its existing test covers
the requested ID and one parsed detail response, but not identity mismatch or lifecycle
classification. The [official endpoint guide](https://developers.smartrecruiters.com/docs/endpoints)
describes the company listing as active postings and the detail endpoint as lookup by
posting ID. The [official PostingDetails schema](https://developers.smartrecruiters.com/docs/objects#postingdetails)
defines `active` as whether the posting is live or unpublished. Use an exact returned
ID plus `active: false` as the SmartRecruiters terminal signal; keep HTTP 404/410
**inconclusive**, since the [detail API reference](https://developers.smartrecruiters.com/reference/v1getposting)
does not define those responses as unpublishing.

A bounded read-only request against one eligible stored posting confirmed the current
endpoint returns the matching `id`, a boolean `active`, and JD sections. This verifies
the live response shape for an active posting; it does not prove that an inactive posting
will return `active: false`, which remains grounded in the published schema and must be
covered by the synthetic closure fixture.

Keep adapter status outside canonical **POSTING_FIELDS** so normal feed ingestion does
not persist source-specific metadata. Add a small refresh-only adapter seam that returns
the canonical posting and its source-state signal from the same HTTP response; do not
issue a second detail request. The seam is injected into the refresh module and exercised
by synthetic adapter/lifecycle fixtures. Concretely, keep existing `fetch_one` unchanged
for feed ingestion and add a pilot-only `fetch_one_observation` result with the canonical
posting plus a small `available | closed | unknown` signal; leave transport exceptions
for the refresh module's safe error classification. A matching `active: true` response
is available only when the returned ID matches, a returned company identifier agrees
with the requested slug when present, the title is non-empty, and
`jobAd.sections.jobDescription.text` is non-empty. Qualifications and additional
information are optional sections and are included when present. Missing or malformed
`active`, identity/company mismatch, or incomplete live content is inconclusive. An
exact-ID `active: false` may confirm closure even when JD sections are absent; preserve
the stored JD, hash, revision, assessment, and application history.

The synthetic adapter/lifecycle fixtures cover:

- Exact returned **(source, external_id)** with `active: true`, matching company
  identifier when present, non-empty title, and non-empty job-description section:
  update source check/seen timestamps; unchanged assessment inputs do not increment
  revision.
- Exact identity with a changed title, location, or JD: update those inputs, increment
  the content revision, mark older captured assessments stale, and make zero model calls.
- Exact returned ID with `active: false`: confirm closure and update check time without
  replacing the prior content or changing pipeline/application state.
- Different returned ID/source/company, missing identity or `active`, `active: true`
  with a blank/partial core JD, `None`, malformed JSON, or an HTML/interstitial response:
  record an inconclusive safe category and preserve the prior complete JD, hash, revision,
  and confirmed source state.
- Timeout/connection failure, 403, 429, and 5xx: record an inconclusive attempt without
  advancing the conclusive check time or changing confirmed availability.
- 404/410: remain inconclusive; a later exact-ID `active: true` result reopens a prior
  `active: false` closure without resetting pipeline or user state.
- Application/status changes between fetch and write: the transaction skips the stale
  result. Existing application, note, and status-history fixtures remain intact.

The current adapter uses a response with **id** from the requested detail endpoint. The
refresh must still compare it with the row key and reject a mismatch before writing;
the endpoint URL alone is not proof that the response body belongs to the requested
posting.

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

## Documentation contract

`SPEC.md` describes the current source/assessment behavior and maps it to the synthetic
adapter, worker, web, and MCP tests. `PROGRESS.md` tracks the active implementation PR;
`CHANGELOG.md` records this behavior under Unreleased until release.
