# Screened60 development frame

**Status:** 60 source snapshots and complete native request bodies frozen offline,
before blind labels or inference. This uses the operator's normal retained screened
inventory. It is development evidence, not untouched validation, verified eligibility,
complete intake or ranking-quality acceptance.

At `2026-11-15T02:19:46.727589+00:00`, SQLite `mode=ro`, `query_only=ON` and a read
transaction captured 10,733 postings. The deployed MCP classification helper supplies
both `screen_outcome=no_disqualifier_found` and strict `triage=candidate`; their
intersection contains 6,152 rows. Selection does not merely inspect a false disqualified
flag. All selected rows remain in pipeline state `new`.

The web's default Discovered view is All jobs, ordered `created_at DESC,id DESC`, without
a screen filter. The corresponding retained screened view adds the no-disqualifier or
candidate filter. This frame applies both predicates, then uses that exact default
creation-time/ID ordering. It does not use legacy fit scores, duty/domain judgments,
title quotas, company caps, JEV/native ranking outcomes or utility-reference labels
to select sources. Stored screen outcomes explicitly define the advisory input pool.

## Selection and provenance

The selection rule was created exclusively and fsynced before the DB connection. Exclude
the previous 80 development IDs or identical whitespace-normalized descriptions: 84
candidate rows. A further 35 same-normalized-company/title matches to that prior exposure
are excluded conservatively. Those 35 are research-exposure precautions, **not proven
duplicate identities**. Normalization is NFKC/casefold/whitespace collapse for company
and title, whitespace collapse only for exact descriptions.

The remaining pool has 6,033 rows. Select its newest 60 by `created_at DESC,id DESC`,
with no additional source-shape, availability or freshness filter. All 60 happen to have
complete required source fields; no replacement was necessary. They cover 23 companies.

| Selected provenance | Count |
|---|---:|
| Stored positive DB source revisions | 60 |
| Source-only screen freshness `current` | 60 |
| Stored source availability `available` | 60 |
| Frame-local export revisions required | 0 |

Unknown screen freshness and source availability were eligible. Their absence from the
selected batch follows newest-first ordering; it is not a filter. Cached screens remain
advisory and have no profile/requirements binding hash. Source-revision equality does
not certify candidate requirements, employer availability or every screen judgment.
No live-current or fully-qualified claim follows from this table.

Each source uses the canonical ten-field `ranking-source-v1` interface, preserving the
full description. `captured_time` is the actual export cutoff. The separate provenance
retains actual nullable DB revision, stored source hash/state/last-seen time, source-only
screen freshness and explicit absence of profile binding. The rule permits a positive
frame-local export revision only when the actual DB revision is null, clearly separated
in provenance from a production revision. This fallback is unused here.

Similarity checking is an audit, without collapse or reselection. It records selected
sources' company/exact-description, company/token-and-spelling-normalized-description,
and company/title candidate links across the full roster. Seven exact-description and
seven token/spelling groups touch selected sources and other roster rows; 15 company/title
candidate groups touch selection. There are zero company/exact-description duplicate
groups within the 60 and zero selected token/spelling matches to the prior80. These
simple checks do not prove exhaustive requisition/template independence. Full membership
remains private for later review.

## Complete requests and blind handoff

Approved profile/domain/C question files are copied byte for byte. Requested model remains
`typesafe/jev-1.13`; this export does not resolve or call a provider. All 60 full System
One bodies include the complete source text and approved context. The 32,768-byte local
bound retains any oversized body visibly deferred, without truncation or replacement.

| Serialized request bytes | Value |
|---|---:|
| Minimum / median | 15,225 / 19,042 |
| Nearest-rank P90 / P95 | 22,957 / 23,634 |
| Maximum / total | 26,699 / 1,172,194 |
| Overbound count / bytes | 0 / 0 |

Private package:
`/home/halcyon/root/ats/apps/worker/resume/pivot/jev-ranking-screened60-v1/`.
`sources.json` contains the 60 sources; `reference-shard-1.json`,
`reference-shard-2.json` and `reference-shard-3.json` contain 20 source objects each.
They contain no screening evidence, sampling hints, labels or outcomes. Normal stored
screen evidence is separate in `selected-screen-evidence.json`; it is never appended to
the JD or supplied as a blind-label hint. The full source/screen roster, exclusions,
similarity links, provenance and exact bodies remain private.

Actual command: `python3 .../jev-ranking-screened60-v1/freeze_screened60.py`.
Offline verification reports `PASS`, 76 original artifacts verified, 60 canonical P0
source bindings, 60 exact complete bodies, and disjoint source-only shards `[20,20,20]`.
It checks newest-first selection against the frozen roster, unchanged source text,
request hashes/bytes/dispositions and mode-0600 artifacts. The package directory is
0700; frozen artifacts use exclusive creation and fsync. No HTTP/model call, production
DB write, prompt change, service change or inference occurs in this frame preparation.
No private reference labels or native outputs were read.

| Frozen proof | SHA256 |
|---|---|
| Predeclared selection rule | `96a03562e031f84da8de46eaf7bdc8f0e91f440184d53b496c86b84e2249d650` |
| Full source/screen roster | `dd08d9bda3a44eadb0ec1c3852facdf3fdb52d4b4f67d82f135835e7691be79e` |
| Selected source array | `bc9be04e500195d8bb2cb80522600192d1c90429522d33091c8522889ec50f66` |
| Separate source provenance | `026bf58c18bf35fd1a6de98b4fa0e6c23e59ec7ba76fc85f55d5d47d219dc401` |
| Similarity audit | `e02a2c2192175d1584a945fb9662a6dd5e10c6ef389d21f01b1ae90d5a4eeb7d` |
| Freeze manifest / request proofs | `6d4f605706a11506bcabc677c51fbdc49a12c638b165999e0f22a73c4cc7c94d` |
| Offline verification receipt | `9d817ee5e6f380e0483bd82b3925d8d60dd683c7f6f84ce6dc965e11e5162cad` |

Approved binding hashes remain profile/domain bundle
`bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986`, domain manifest
`c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c`, and C pack
`e63c5bf3c55904df22af028775f1c25d4f07d94013a563be85804167b0224109`.
