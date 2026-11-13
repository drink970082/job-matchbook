# P0 private input binding audit

**Status:** approved profile and accepted eight-domain manifest bound offline.
No private input contents belong in this document. Audit is read-only and offline.

## Retained approved profile

The retained `jev-skill-evidence20-v1/approved-full-profile.json`, reached through the
published research report and its local freeze controller, has schema 1, version
`2.0.4-user-calibrated-v1`, as-of `2026-11-04`, and status `approved`.
It contains 15 background and seven preference blocks; no new candidate facts were added.

| Binding | SHA-256 |
|---|---|
| Exact profile file bytes | `4f31ccade0a097d53487823d763156cabf7e217afee99a28d55fe2535e0b7468` |
| Historical semantic profile identity recorded by frozen manifest | `ba89973742b8801b97d9dedd6df42106e31362d0fa63922793c1ce68d5fd8d74` |
| Historical frozen input manifest file | `5d87dd6e80fc1334a5e9a424adad428b14806e566d3d0e8dd9121a2851a0044b` |
| Historical source snapshot file | `21d68242f9a24b3ac18fa7e2baf04c8e4a2043e9bc3c94ac3005db036b9ff065` |

The two profile hashes describe different encodings/contracts; never interchange them.
A new ranking binding must specify its own canonical profile encoding/hash and retain
this original-byte provenance. The ordinary `resume/pivot/candidate_profile.json` is
version `2.0.1-draft`, status `draft`, and must not silently replace the approved file.

## Accepted domain and question bindings

The operator accepted eight domains by primary duties, with mixed/unknown and no weights.
A private canonical `domain-manifest.json` now records exact IDs/descriptions and neutral
classification semantics. It lives with `question-pack.json`, `profile-binding.json`,
22 complete request bodies, `measurement.json` and reproducible `measure.py` under the
ignored `apps/worker/resume/pivot/jev-ranking-p0-v1/` artifact directory. None is a
production config activation. Approved profile content remains unchanged; the separate
ranking profile binding combines that profile with the domain manifest.

| Canonical binding | SHA-256 |
|---|---|
| Domain manifest | `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c` |
| Combined profile/domain binding | `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986` |
| Four-question pack, including shared instruction prefix | `b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7` |
| Tagged question/context/domain composite | `e1741d3349ff8e0e3016e4abe135eb38c206dde98ad1d47e2471410308f6270f` |
| Complete private measurement report | `5887367ad119846f729da086b9356dfd228561a8e46c6dfe7c0f4f43b13602cc` |

Question instructions and non-domain criteria are read directly from the contract's full
synthetic HTTP request; domain criteria alone are replaced with the accepted manifest.
The pinned research native parser accepts the pack and reproduces the exact wire map.
Canonical encoding is UTF-8 JSON, sorted keys, compact separators, finite numbers only.
Candidate context is canonical JSON of the combined profile/domain binding. State uses
exact company, title, location and full description; no source/profile text is clipped.
The requested endpoint model is `typesafe/jev-1.13`; no new resolved-model identity,
provider acceptance or token count is claimed by offline serialization.

## Available source roster and measurement boundary

The historical snapshot contains 22 rows: two controls and 20 requested main sources.
Its prior selected-skill campaign assessed only 16 main sources; the new ranker must not
inherit that outcome/size-selected subset as its population. The retained rows have full
source fields and hash/revision provenance, but are exposed historical development data,
not three untouched daily held-out rosters. Complete daily roster/grouping acceptance is
P1 work. No new source snapshot or production database was modified by this audit.

The companion [resource audit](p0-resources.md) measures both historical request bodies
and the accepted four-question pack over **all 22** retained rows, including the four
previously unassessed main sources. This is exposed development evidence only. P1 must
still freeze complete daily rosters and grouping; it must not claim these rows held out.

No inference, provider metadata call, DB write, approved-profile edit or deployment was
performed. The only new private files are this offline binding/measurement package.
