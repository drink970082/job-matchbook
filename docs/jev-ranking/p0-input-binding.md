# P0 private input binding audit

**Status:** approved historical profile located; domain-manifest binding unresolved.
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

## Domain vocabulary is not yet an approved artifact

The approved profile has only schema/version/as_of/status/background/preferences fields.
It contains target-family prose, but no versioned domain manifest with exact IDs and
criterion descriptions. Historical preference policies bind role-family questions;
these are separate research projection contracts, not a manifest approved for the new
four-question ranker. Converting or merging these families requires an explicit mapping
acceptance; the audit does not create that approval by inference.

A concrete seven-family vocabulary recommendation grounded in existing approved prose
has been supplied privately to the orchestrator. It adds no background facts or domain
weights. Its exact IDs/descriptions and mapping need acceptance before the domain
question, complete question-pack hash and new minimal request bytes can be frozen.

## Available source roster and measurement boundary

The historical snapshot contains 22 rows: two controls and 20 requested main sources.
Its prior selected-skill campaign assessed only 16 main sources; the new ranker must not
inherit that outcome/size-selected subset as its population. The retained rows have full
source fields and hash/revision provenance, but are exposed historical development data,
not three untouched daily held-out rosters. Complete daily roster/grouping acceptance is
P1 work. No new source snapshot or production database was modified by this audit.

The companion [resource audit](p0-resources.md) measures exact historical request bodies.
It does not claim the accepted four-question minimal-ranker distribution: exact domain
criteria and a declared new measurement roster are still missing. Once those bindings
are accepted, offline serialization can reuse the approved profile and all declared
historical development rows without model calls; P1 must separately freeze daily pools.

No inference, provider metadata call, DB write, profile edit or deployment was performed.
