# P3 existing-inventory development inputs

**Status:** source-only export for the accepted isolated fake-provider prototype.
This is existing DB development data, not ranking truth, full-source completeness proof
or held-out validation. P1 prospective collection/activation is unchanged.

## Selection and provenance

Observed at `2026-11-13T18:54:19.227689Z` using SQLite `mode=ro`, `PRAGMA query_only=ON`
and a read transaction. The source-only inventory contains 10,625 rows. Require nonempty
stored descriptions and a stored source revision: 2,969 rows qualify. There are 381 blank
descriptions and 7,656 missing revisions; all 381 blanks also lack a revision, so the
union exclusion count is 7,656, not their sum. These are input-shape exclusions only;
a nonempty description is not proof of a full JD.

Select the latest 20 qualifying rows by `created_at DESC, id DESC`, with no score,
screening, JEV output, domain classification or application-state filter. All 20 have
stored creation time `2026-11-13T05:00:17.000Z`. Full stored source text is preserved.
There are zero exact-description duplicate groups within the selected batch. Near
requisition/template grouping is unverified and unnecessary for this fake mechanics demo.

## Private package and interface

Ignored local package: `apps/worker/resume/pivot/jev-ranking-p3-dev-v1/`.
It contains source-only full roster, selected `sources.json`, per-source canonical hashes
and exclusions in `export-report.json`, the one-off read-only `export.py`, and unchanged
P0 `profile-binding.json`, `domain-manifest.json` and `question-pack.json`. Data files are
mode 0600. No source/profile text is included in public docs.

The CLI input is a JSON array. Each source has `schema=ranking-source-v1`, integer
`job_id`, company/title/location/description/source_url strings, nullable publication_time,
UTC captured_time and source_revision string. Location null becomes empty string;
captured time uses source_last_seen_at, falling back to created_at. No source hash or
snapshot ID is inserted into the source object; per-source hashes live in the manifest.
Canonical hashes use sorted-key compact JSON, `ensure_ascii=False`, finite values and UTF-8.

| Artifact | SHA-256 |
|---|---|
| Complete ordered source-only DB roster | `e92952eff5f62c68afc7f886912686a8587f11ec3f78bc6507fe290901d161ef` |
| Selected 20-source array | `996f198e4e799a75a648ae25ab3fe261f84bfea03170bf28c3978846e4074327` |
| Export report | `4d165d905a237894ab5b9d6afa72a02cb79b01bb20ddcd0d9fab8cb4992ff535` |
| Combined approved profile/domain binding | `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986` |
| Accepted eight-domain manifest | `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c` |
| Accepted four-question pack | `b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7` |

The approved background remains version `2.0.4-user-calibrated-v1`. No new candidate
facts or domain preferences were added. The roster file contains only source columns:
id/source/external_id/company_name/job_title/location/job_url/description/created_at/
posted_at/source_state/source_last_seen_at/source_content_hash/source_content_revision/
source_content_changed_at, in deterministic selected ordering above.

## Actual command and limits

Executed `python3 /home/halcyon/root/ats/apps/worker/resume/pivot/jev-ranking-p3-dev-v1/export.py`.
Actual output: roster=10,625; eligible=2,969; excluded_any=7,656; selected=20;
duplicate_groups=0; provider_calls=0; production_db_writes=0. Rerunning the private exporter
reselects current DB inventory and refreshes the local report/cutoff; use the pinned hashes
above for this exact prototype input. The exporter imports only stdlib, never a provider,
score/screen parser or runtime pipeline. It writes only the private development package.

The fake-provider CLI must mark results as synthetic prototype behavior. This export
contains no reference labels and cannot establish ranking usefulness, provider capacity,
source availability, eligibility or production acceptance. No provider call, fetch,
formal model-based labeling, DB modification, scheduling or deployment ran during export.

## Offline pilot resource preparation

Exact accepted four-question native requests were serialized offline for the frozen
20-source array above, using the unchanged approved combined profile/domain binding.
The original export and source files were not regenerated. Distribution: n=20,
min=15,686, median=18,391, nearest-rank P90=20,564, P95=20,602, max=22,146 bytes.
Zero exceed 24,000 or the accepted 32,768-byte local bound. Any future overbound item
remains deferred/not_sent, never silently excluded. Exact token counts and resolved
provider identity remain unverified. Requested model is `typesafe/jev-1.13` only.

Private `pilot-offline-preparation.json` retains each source/request SHA and byte count,
plus the ten closed ledger paths/hashes/final events. Its SHA-256 is
`367beef9b9da05f22db9d3fdd3705bcb66ac2558f78af2851ff202e4f87669af`.
Executed the private package's `prepare-pilot-offline.py`; no provider or DB imports are
used. All ten ledger byte lengths, expected file hashes, final events and chained event
hashes match the frozen predecessor proofs. Latest settlements include the historical
explicit zero-cost reconciliation of one earlier unknown settlement; no unknown charge
was silently treated as zero.

The ten ledgers contain 1,734 reservations with USD 0.566321728 settled cost, plus their
first ledger's declared historical seed of 10 attempts/USD 0.002003148. Thus the carried
cumulative total reconciles to **1,744 attempts/USD 0.568324876**, with zero pending,
unknown or overreserve entries. The ten individual pre-ledger seed attempts were not
reverified from their original provider records; their frozen declared carry is explicit.
No prior ledger or epoch was reopened or modified. Remaining historical budget does not
authorize a new 20-call pilot, repetitions, retries, new epoch or any spend.
