# P1 cohort readiness

**Status:** complete daily held-out pools unavailable; prospective collection selected, collector preparation active.
Accepted P0 source: `1308f47`. This is an offline data audit, not a quality evaluation.
No labels or JEV outputs were read for this audit.

## Observed data

SQLite was opened using `mode=ro` and `PRAGMA query_only=ON`; a read transaction pinned
the source inventory observed at `2026-11-13T18:21:19.532907Z`. There are 10,625 stored
jobs, with `created_at` from `2026-07-13T15:31:46.000Z` through
`2026-11-13T05:00:17.000Z`; latest source-seen time is also `2026-11-13T05:00:17.000Z`.
Source availability counts are 7,874 available and 2,751 unknown. These are stored
observations, not proof that every board was fetched successfully or every JD is complete.

| UTC created-at day | Stored rows | Known research-exposed IDs | Descriptions under 1,000 characters |
|---|---:|---:|---:|
| 2026-11-13 | 174 | 0 | 1 |
| 2026-11-12 | 188 | 9 | 0 |
| 2026-11-11 | 212 | 12 | 0 |
| 2026-11-10 | 150 | 9 | 1 |

All rows in these four day groups have nonempty descriptions and source revisions.
Length is only an audit signal; a long body does not prove full source capture. November
13 is still an open UTC day at this cutoff. Zero known exposure does not prove untouched:
the audit only checks retained source-snapshot membership, not every possible interaction.

Read-only inspection of 35 retained source-snapshot JSON files identifies 330 known
research-exposed IDs. These are selected historical cohorts, not independently reconciled
daily intake rosters. Among the latest four stored day groups, 20 exact-description
hash groups contain duplicates and one group crosses day boundaries. Requisition and
near-template grouping remain unverified. A date-only split can leak repeated sources.

## Provenance and what the hash establishes

Private audit report: ignored `apps/worker/resume/pivot/jev-ranking-p1-v1/readiness-audit.json`.
Its file SHA-256 is `58f7ee1bd0dd58e4782db50ba77d33f08db007c5e8a50cb368222c6b7863df5b`.
The ordered source-only DB roster hash is
`1a0d7bfca4bb171d356cf03e1f03838b265a5850b84d80a822580f6fda577c5c`:
rows ordered by ID, JSON array tuples, `ensure_ascii=False`, compact separators, UTF-8;
columns are id/source/external_id/company_name/job_title/location/job_url/description/
created_at/updated_at/posted_at/source_state/source_last_seen_at/source_content_hash/
source_content_revision. No score, screening output or model response enters this hash.
This hash identifies the observed DB projection; it cannot recreate missing board records.

The sorted retained source-snapshot filename/hash manifest SHA-256 is
`2ab6385d13610318319dd8137e2774daa4caa782b420cb71ac5e87a4ae132c26`.
Private source contents and candidate facts are absent from this document.

## Why P1 cannot declare three complete untouched daily pools

No independent daily/roster artifact was found in the existing approved private input
tree. The current DB has 172 watchlist rows but no immutable fetch-run/raw-intake roster
table. Current source-seen fields are mutable latest observations. Stored `created_at`
groups omit pre-insert title, age, geography and other intake exclusions, fetch failures,
bodyless sources and already-known jobs. Aggregate board-health logs cannot reconstruct
those missing identities or prove population completeness. Historical selected snapshots
also contain exposed sources. These limitations prevent the requested held-out claim;
counts above are inventory evidence only.

## Selected prospective preparation and activation gate

The operator selected prospective collection. Prepare a bounded collection surface for
review before activation; no model workload or deployment is authorized. It should observe
ordinary intake without invoking a model, scoring backlog, changing filter decisions or
restarting/scheduling services as a side effect. Capture at least three fully closed,
untouched UTC daily windows after the accepted development cutoff. Operator approval must
name the collector build, whether it observes existing scheduled intake or performs new
fetches, exact windows, source scope, storage location and request/time/storage caps.

For each window retain an immutable manifest of the watchlist/config revision, expected
boards/feed pages, run start/end/cutoff, pagination completion and per-source success or
typed failure. Retain identity rosters before each exclusion, reason-coded exclusions,
source/JD hashes and revisions, hydration outcomes and deduplication links. Reconcile
expected sources to observed/failing sources, then raw identities to retained/excluded/
unresolved identities. A failed or partial source remains explicit, never silently replaced
by another day. Collection completeness is relative to this frozen scope, not all jobs
on the internet. Any permitted partial-scope study needs explicit acceptance and disclosure.

Before model outputs or proxy labels, lock duplicate/requisition/template groups and
keep each group on one side of development/held-out. Carry all size outliers and missing
content with explicit assessability reasons. Freeze the source roster, approved P0 input
hashes, allocation K/R, baseline ordering, proxy guide, unresolved-label handling and
statistical limits. Record exact manifests and checksums; seal held-out data against
inspection for tuning. P1 must separately justify source-content completeness and sample
size, rather than infer them from row counts. No collector, fetch, schedule, proxy-label
workload or provider inference is activated by this recommendation.

A retrospective stored-inventory-only study is a different, weaker scope. It can be
proposed as development evidence, but cannot be renamed three complete untouched daily
pools or satisfy that gate without an explicit changed evaluation contract.

## Verification limits

Executed read-only SQLite queries and source-snapshot ID/hash inspection. No production
DB write, provider/fetch call, label generation, service change or deployment occurred.
Completeness, untouched status, near-duplicate grouping and fresh held-out usefulness
remain unverified for the reasons above. P1 remains open.
