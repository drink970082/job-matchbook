# Source lifecycle for the unscored inventory

**Status:** implemented

**Issue:** [#93 Keep unscored job evidence fresh without losing application history](https://github.com/drink970082/job-matchbook/issues/93)

**Decision owner:** The operator selects the source and request limit for each one-shot refresh. This implementation supports SmartRecruiters only.

## Purpose

Refresh evidence for a bounded slice of already-stored, unscored jobs. Record whether
the source was seen, when it was checked, whether its assessment inputs changed, and
whether the source is known to have closed. Keep source availability separate from
screening, fit, application status, and retention.

The implementation does not broaden intake, backfill old rows, rerun models, or delete
postings. It leaves the existing scorer and screen defaults alone.

## Current state and evidence

- Posting identity is the existing unique pair **(source, external_id)**. Ingest ignores
  later copies of that pair, so it neither updates its description nor records that the
  board listed it again.
- The current expiry stage checks at most 50 rows per pass, only **scored** and
  **notified** rows from adapters exposing **fetch_one**. It discards successful detail
  responses and changes **pipeline_status** to **expired** only for HTTP 404/410. A
  timeout, blocked response, parse error, or other status leaves the row alone.
- **job_postings.updated_at** is also written by pipeline activity. It cannot say when
  the employer source was last seen or checked.
- **job_screenings** and **score_detail** hold assessments independently of source
  freshness. No current field records which posting content an assessment used.
- **upsert_postings** fills a missing **posted_at** with the scrape day. Fetch age
  filtering keeps missing or unparseable dates. A stored **posted_at** therefore is not
  a source freshness clock, and its fallback provenance is not recoverable on existing
  rows.
- The only current per-listing detail adapters are the four modules in **DETAIL_SOURCES**
  (jobvite, oracle, smartrecruiters, and workday). Membership is derived from
  **fetch_one**; this design adds no capability registry.

## Implemented contract

### Identity and source state

Keep **(source, external_id)** as the immutable posting identity. **company_slug** and
company name are lookup context, not identity. A response for a different external ID
must fail loudly and must never update the requested posting.

Add a source-lifecycle snapshot to **job_postings**, owned by Prisma:

| Field | Meaning |
|---|---|
| **source_state** | **unknown**, **available**, or **closed**; the last confirmed source state |
| **source_last_seen_at** | Latest successful board-list or detail response containing the exact posting identity |
| **source_last_check_attempted_at** | Latest attempt, including timeout, block, malformed response, and confirmed closure |
| **source_last_checked_at** | Latest conclusive result (**available** or **closed**); inconclusive attempts do not advance it |
| **source_last_check_outcome** | **not_checked**, **found**, **confirmed_closed**, or **inconclusive** |
| **source_last_check_error_category** | A fixed safe category for the latest inconclusive attempt; never raw provider/page text |
| **source_content_hash** | SHA-256 of the canonical stored assessment inputs: company, title, location, and description |
| **source_content_revision** | Monotonic revision of those inputs, initialized when a complete source payload is first observed |
| **source_content_changed_at** | Time the current revision replaced the former stored inputs |

New rows created from a validated source listing begin **available** with
**source_last_seen_at** set to the ingestion time. Existing rows start **unknown** until
they receive a positive observation. Initialize a content hash and revision on insert
only when the assessment-input fields are present. For an existing row with no hash,
derive the prior-content baseline lazily when that row is selected for refresh; do not
backfill the inventory.

**unknown** means there is no conclusive source result yet; it does not mean open or
closed. **available** means a valid response identified the exact posting. A positive
list/feed observation can set it and advance **source_last_seen_at**; absence from a
board list cannot confirm closure. **source_last_checked_at** and
**source_last_check_outcome** describe the exact-ID detail refresh only. **closed** is
reserved for a source-specific closure signal that has been verified for that adapter.
For the recommended SmartRecruiters pilot, the official
[PostingDetails schema](https://developers.smartrecruiters.com/docs/objects#postingdetails)
defines **active: false** as an unpublished posting. A schema-valid detail response with
the exact requested ID, a matching **company.identifier** when present, and
**active: false** confirms closure: advance
**source_last_checked_at**, leave **source_last_seen_at** and all content/assessment
fields intact, set outcome **confirmed_closed**, and clear the prior error category. A
matching **active: true** response confirms availability only when the canonical content
also passes validation: require a non-empty title and
**jobAd.sections.jobDescription.text**; include qualifications and additional information
when present. Then advance seen/checked time and clear the prior error category.
Missing/wrong-type **active**, identity/company mismatch, or an incomplete live payload
is inconclusive and preserves the prior state and content. HTTP 404/410 remain
inconclusive for SmartRecruiters because the current detail reference does not define
either as an unpublished-posting signal. Other adapters need their own verified terminal
signal; do not generalize SmartRecruiters' field. HTTP 200 with a blank/partial body, an
unrecognized page, login/CAPTCHA/bot wall, redirect to a generic board, timeout, 403,
429, 5xx, and parse failure are inconclusive unless the exact-ID **active: false**
signal above is valid.

An inconclusive retry records its attempt and safe error category, leaves the last
confirmed state and **source_last_checked_at** intact, and leaves an initially unknown row
unknown. The UI and MCP must show both the last confirmed state/time and a newer failed
attempt when both exist; a stale **closed** result must not look like a recent check.

When a later valid response finds a previously closed identity, set **source_state** to
**available** and update **source_last_seen_at**. This reopens source availability only. It does not change
**pipeline_status**, requeue a screen or fit call, erase the former assessment, or alter
an application/history row.

### Content changes and assessment freshness

Compute the hash from the exact assessment inputs stored for that posting, using a
stable canonical representation. Do not hash response metadata, source timestamps, or
the fallback **posted_at**. Do not replace a stored non-empty JD with a missing, empty, or
known-partial response.

On a verified content change, update the stored source fields and increment
**source_content_revision**. Do not call a model or change a posting's pipeline/user state.
Capture the revision used by each future assessment:

- standalone screening stores it beside the **job_screenings** result;
- fit/combined screening stores it beside the corresponding data in **score_detail**.

Freshness is derived for each assessment: matching revisions are current; an older
captured revision is stale; a missing revision is unknown. Existing assessment payloads
remain available for review. A content update makes a previously versioned assessment
stale immediately, without silently rerunning it. On a changed refresh of a legacy row,
the transaction attributes any existing unversioned assessment to the pre-refresh
revision before incrementing the posting revision. This is supported by the current
insert-only dedup path, which does not update a stored JD after assessment. If an
implementation finds another product writer or cannot establish that provenance, it
must leave the revision unknown rather than claim freshness. An unchanged legacy
assessment remains unknown until a new assessment records its revision. A row with no
assessment is still **not_assessed**, not stale.

The separate **job_screenings** and fit result remain separate sources of judgment. A
screen provider error remains a provider error, not source closure. User status,
application links, application notes/history, and source state are not assessment
payloads and are never overwritten by refresh.

### Bounded refresh scope

Add a separate, dependency-injected refresh stage for already-stored postings with no
fit assessment, no linked application, and one of the unscored lifecycle states
**new**, **failed**, **discarded**, or **expired**. Determine fit assessment presence
from the assessment data, not the numeric score alone: a free screening discard may
carry score zero without a fit assessment. A malformed or absent assessment payload
must not crash selection or be treated as a fit verdict. Exclude **applied**,
**removed**, **scored**, and **notified** rows. A posting whose status is not one of the
known unscored states stays untouched and is reported as skipped.

Limit candidates to sources in the existing **DETAIL_SOURCES**. The refresh may reuse
the existing adapter fetch function, but it must consume and validate the returned
posting instead of throwing the response away. Keep the existing scored/notified expiry
stage's behavior intact in this slice.

Select the least-recently-attempted eligible rows first, with a stable ID tie-break.
Make both source selection and the per-pass row limit explicit. The first rollout is one
operator-selected source and a small fixed cap (recommended maximum 25 requests per
pass), then review outcomes before expanding to the other detail adapters. A source
without a supported exact-ID detail fetch remains **unknown**; do not invent an endpoint
or infer support from a board-level listing call.

Normal list/feed ingestion may update **source_last_seen_at** only for an exact existing
identity. It must not overwrite content through the existing dedup path; content refresh
uses the validated detail result and the revision rules above.

Refresh does not add or remove jobs and does not reapply **title_filter**,
**title_exclude**, sponsorship/category gates, or **max_age_days**. Before any later
proposal changes intake policy, inventory those gates and document their date semantics.
In particular, do not use **posted_at** as freshness: it can be the scrape-day fallback
and the original board-date provenance is absent on legacy rows. This slice leaves that
field and all intake defaults unchanged.

### Pilot scope

**SmartRecruiters** is the only supported refresh adapter. A read-only live inventory
check found a **new** row that met the technical
eligibility predicate, with a complete stored description, no fit assessment, and no
application relation. The adapter's per-listing response includes its posting ID, so
the refresh can compare the returned
identity with the requested **(source, external_id)** before writing. Recheck candidate
eligibility immediately before rollout; this inventory observation is not a durable
claim that the row remains eligible. SmartRecruiters' published PostingDetails schema
provides an exact-ID **active** boolean to distinguish live from unpublished postings;
a bounded read-only detail request confirmed that the current endpoint returns the
matching ID, **active: true**, and JD content. No database write or model call was made.
HTTP 404/410 remain inconclusive. The adapter-specific observation seam and
fixture brief is in the linked implementation plan.

### Retention and protected records

Source closure is not a retention policy. The protected identity is the posting row plus
its **(source, external_id)** key and any **application_id** relation. No row,
description, assessment, application, note, or status history is deleted, pruned, or
detached. No age-based cleanup, global backfill, or bulk state transition is part of
this design. Applied and linked records are outside the unscored refresh candidate set;
the implementation must recheck eligibility immediately before writing so a concurrent
application or status change is preserved. Any future retention proposal needs a
separate protected-identity contract and cannot use source closure as deletion authority.

## Alternatives

| Approach | Decision | Reason |
|---|---|---|
| Add a current source snapshot and content revision to the existing posting row | Recommended | Fits the single-user SQLite model and the requested latest-state timestamps; avoids a second identity or history subsystem |
| Append every fetch to a **source_observations** table | Defer | Preserves a full event history but adds storage, retention, query, and migration policy without a current consumer |
| Reuse **updated_at**, **pipeline_status**, or assessment JSON as source state | Reject | Conflates source availability with worker activity, human/application state, or model judgment and cannot reliably identify the inputs an assessment used |
| Treat any 404/410, empty response, or HTTP 200 banner as closure for every adapter | Reject | Adapter behavior differs; partial pages and access controls are not evidence that a requisition closed |
| Re-score every changed posting automatically | Reject | Spends model quota and hides that the stored result used older evidence; the operator must choose any re-assessment |
| Delete old or closed postings during refresh | Reject | Closure and retention are separate; application history and evidence must survive |

## Principles

- **2, 3, and 5:** code classifies explicit source facts; ambiguous opportunity evidence stays visible; source failures are surfaced.
- **6:** a bad posting cannot abort a refresh batch.
- **9, 10, and 11:** Prisma owns any new fields, worker I/O and clock are injected, and SQLite writes stay on the main thread.
- **12 and 13:** no private profile/JD data enters fixtures or docs; keep the design single-user and local.
- **14:** defer event history, broader adapter support, retention, and automatic re-scoring with the reasons above.

## Operational boundary

Each run requires `--once --refresh-unscored --refresh-source smartrecruiters`; the
request limit is explicit and cannot exceed 25. The mode performs no normal fetch,
screen, fit, retry, notification, retention, or database cleanup work. Real inventory
refresh and deployment are separate operator actions. Other adapters remain unsupported
until their exact-ID closure semantics are verified and tested.
