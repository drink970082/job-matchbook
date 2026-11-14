# Frozen 60-source development frame

**Status:** source-only frame and complete native request bodies frozen offline. This
is exposed existing-inventory development data, not held-out validation, a population
estimate, ranking truth or production acceptance. No native outcomes were measured
while constructing this frame.

The frame uses the accepted C question pack, approved profile/domain binding and
accepted secondary-work policy byte for byte. It adds no candidate facts or domain
weights. The user-approved leftover-K fill policy is a separate consumer policy; it
does not alter source sampling or these native questions.

## Read-only snapshot and exclusions

The export pins a SQLite snapshot with a source-table count inside a `mode=ro`,
`PRAGMA query_only=ON`, `BEGIN` transaction. Its actual UTC export cutoff is
`2026-11-14T19:09:47.067650+00:00`. One explicit source-only query reads the full
10,731-row roster; the transaction ends with rollback. No fit/screen status,
application state, model output or previous reference label is queried. There is no
HTTP refresh or production DB write.

Require nonblank company, title, description and source URL. There are 381 shape
exclusions, all blank descriptions. Stored revisions are absent on 7,656 roster rows;
that absence is not an exclusion. The earlier 20-source export's strict revision
requirement excluded 7,656 of its then-10,625 rows; this export does not repeat that
restriction or claim that a legacy row has acquired a stored revision.

Group exact stored `(source, external_id)` identity, company-scoped requisition
identity in that same source namespace, normalized URL, or company plus identical
whitespace-normalized description, using transitive union. Company normalization is
NFKC/casefold/whitespace collapse, without corporate alias inference. Description
normalization collapses whitespace only. URL normalization lowercases the host,
ignores scheme/fragment/trailing slash, sorts query parameters, and removes the
explicit tracking-key list frozen privately; job-identifying parameters remain.
No fuzzy matching or inferred cross-platform requisition identity is used. There are
no conflicting company names within an exact source identity requiring review.

Exclude the previous 20 source IDs, every identical normalized prior description
regardless of company, and every connected duplicate member. This excludes 22 rows.
The private grouping and exclusions retain every member, reason and representative;
excluded duplicates are not silently discarded. The full roster has 9,789 groups,
including 642 groups with multiple members. After shape and prior-source exclusions,
10,328 rows form 9,388 eligible groups. Five selected groups have multiple members;
each contributes one representative.

## Predeclared selection

The selection rule was created exclusively and fsynced before opening the DB. Seed:
`jev-ranking-dev60-v1-source-only-20261114`. Representatives and candidates sort by
stored `created_at DESC`, with ascending SHA256 of `seed|id` for ties. Title regexes
assign the first matching stratum in the precedence below. These are coarse sampling
hints, not domain labels; descriptions and model judgments do not determine strata.

| Title-only stratum, in precedence order | Frozen target | Selected |
|---|---:|---:|
| Quant/trading/research | 20 | 20 |
| AI/ML/agent | 10 | 10 |
| Software engineering | 15 | 15 |
| Data/analyst | 10 | 10 |
| Other | 5 | 5 |

A global maximum of five rows per normalized company applies across all strata.
Predeclared fallback passes raise that cap to ten, then remove it only to fill unmet
strata; no fallback was needed. The 60 sources cover 37 companies:

| Selected rows per company | Company count |
|---:|---:|
| 1 | 27 |
| 2 | 5 |
| 3 | 1 |
| 5 | 4 |

The quant/trading/research regex includes generic research. A requested refinement
arrived after the frame was frozen, so selection was preserved. A subsequent title-only
audit finds 13 of those 20 matching explicit quant/quantitative/trader/trading/alpha/
portfolio wording or “research engineer”; seven match the broader research/strat/
systematic hint. These counts establish neither primary-domain coverage nor quality.

## Source identity and complete requests

Each selected object uses the unchanged ten-field `ranking-source-v1` interface. Its
`captured_time` is this export's actual cutoff. Original source-last-seen time, stored
revision/hash/state and raw-row hash remain in the private provenance sidecar.

For a missing stored revision, the frozen rule permits an opaque
`offline-db-snapshot-v1:<hash>` revision binding the exact raw row and cutoff. The
sidecar explicitly records `stored_source_revision=null` and
`source_revision_origin=derived_db_snapshot`; it never represents that identifier as a
live stored revision. In this selected frame all 60 happen to have positive stored
revisions, so zero derived revisions are needed. All 60 have stored availability
`available`; source availability was not a selection filter and has not been refreshed
or verified. Unknown availability would remain eligible.

All 60 complete System One bodies are serialized offline with the accepted C pack and
full approved context. No source text is truncated. Each canonical source hash binds
its exact body and export cutoff, and the private request manifest binds source hash,
full request hash, byte count and disposition. The local bound is 32,768 bytes; any
overbound item remains in the cohort with its complete body and visible
`deferred_not_sent_over_local_bound` disposition, without replacement.

| Complete request bytes | Value |
|---|---:|
| Count | 60 |
| Minimum | 15,469 |
| Median | 19,257 |
| Nearest-rank P90 | 22,968 |
| Nearest-rank P95 | 23,919 |
| Maximum | 25,500 |
| Total | 1,197,522 |
| Overbound count / bytes | 0 / 0 |

## Private handoff and verification

Ignored private package:
`/home/halcyon/root/ats/apps/worker/resume/pivot/jev-ranking-dev60-v1/`.
`sources.json` contains the 60 source objects. `reference-shard-1.json`,
`reference-shard-2.json` and `reference-shard-3.json` each contain 20 source objects,
partitioned by a separately seeded deterministic order. Shards contain no sampling
strata, company-diversity rules, outcome hints or labels. Approved profile/domain/C
inputs are available as separate unchanged files for reference work.

`selection-rule.json`, `source-roster.json`, `selection.json`, `grouping.json`,
`exclusions.json`, `source-provenance.json` and `freeze-manifest.json` retain the full
private audit trail. `frozen-request-<id>.json` contains each complete body.
`artifact-inventory.json` binds all 77 original package files. New frozen artifacts use
`O_EXCL`, mode 0600 and fsync; the private directory is mode 0700. The one-off exporter
and offline verifier remain ignored in the package. Existing epochs are untouched.

Actual commands: `python3 .../jev-ranking-dev60-v1/freeze_dev60.py` and
`python3 .../jev-ranking-dev60-v1/verify_dev60.py`. Export output reports
`selected_count=60`, `selected_unique_company_count=37`,
`company_cap_fallback_used=false`, `provider_calls=0`, `production_db_writes=0`.
Independent offline verification reports `result=PASS`,
`frozen_original_artifacts_verified=77`, `exact_full_bodies_verified=60`,
`p0_bindings_passed=60`, `reference_shards=[20,20,20]`. It verifies original hashes and
permissions, exact roster text preservation, exclusion/group boundaries, unchanged
approved inputs, source-interface acceptance, every full body and disposition, and
the disjoint shard partition. No provider calls, native outcome checks, live source
checks, token measurements, fees or ranking-quality claims are part of this work.

| Frozen proof | SHA256 |
|---|---|
| Predeclared selection rule | `e270b05900ce3efb0f648235df513a1d2ada07e604ab94a61a1b95e2221816e0` |
| Full source-only roster | `a232b067cfc580d0ace046cdf1e9a1fe98c187ed41c737c6d3c665a2d53cb784` |
| Cohort selection | `15b289977954b212457a5f12a4b34daabb1c07781712be8dec92792f39ad3e7f` |
| Sources array | `5c00064c61c1d1cffca06bdd086e9022f907b8bfd6682f2e1b4b33805f5f61a9` |
| Provenance sidecar | `041f9874aa9df29ff02f1d6bc7a37683c02fea5ede799628255c0411b1097816` |
| Approved profile/domain binding | `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986` |
| Approved domain manifest | `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c` |
| Approved C pack | `e63c5bf3c55904df22af028775f1c25d4f07d94013a563be85804167b0224109` |
| Freeze manifest / all request proofs | `904c235ac4eb22e058b51a9d8081ae8d2b9659e4304994667cc429ff7d668868` |
| Original artifact inventory | `8cca274294927353b7245d1f447e488b30c96fb487b870f27b88c1b90c10190d` |
| Offline verification receipt | `b91ff56aa3c5abd2561396db2858b0a381341be5c1103c6d0d65cb810de9706f` |
