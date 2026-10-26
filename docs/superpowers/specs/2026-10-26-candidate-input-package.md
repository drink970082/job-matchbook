# Candidate input package for preselection and Daily Brief

**Status:** preparation contract — operator prepares and approves private contents in
ChatGPT web before #109 begins. This is not an implemented runtime schema or approval
of model/rubric/spend. #109 must validate the returned package and pin its adapter/schema.

## Source inputs

The operator supplies two semi-customized presentations of the same candidate:
`resume_quant_dev.txt` and `resume_swe.txt`. Preserve both as separate downstream
resume choices; neither is globally more authoritative. `personal_profile.txt` and
`config.yaml` are legacy evidence to review, not current policy to inherit automatically.
No contents were inspected to define this package. Before uploading config, remove
credentials, tokens, webhook/connection URLs and unrelated operational settings. Retain
relevant candidate facts/preferences with their original key paths as source locators.
Do not replace the live config or legacy profile as part of this preparation.

## Six-file private deliverable

| File | Format | Consumer and authority |
|---|---|---|
| `candidate_facts.json` | strict UTF-8 JSON | Canonical deduplicated evidence; ranking gets only approved relevant facts through a later deterministic projection |
| `search_preferences.yaml` | safe, simple UTF-8 YAML | Operator-confirmed current preferences; separate from experience facts and old scoring instructions |
| `resume_quant_dev.txt` | original UTF-8 plain text | Original role-oriented resume for downstream ChatGPT; no silent rewriting |
| `resume_swe.txt` | original UTF-8 plain text | Original role-oriented resume for downstream ChatGPT; no silent rewriting |
| `resume_selection_guide.md` | Markdown | Downstream comparison, unique emphases, limitations and hybrid-role handling; advisory, never an eligibility gate |
| `input_review.md` | Markdown | Provenance inventory, coverage audit, migration decisions, unresolved questions and actual operator approval record |

All files are private artifacts, not repository fixtures. A suggested eventual location
is ignored `apps/worker/resume/preselection/`; #109 verifies ignore coverage before any
import. Keep original sources intact. Public docs contain schemas/examples only.

## candidate_facts.json contract

Top level: `schema_version` (initial `1`), `profile_version` (operator-controlled string),
`as_of` (ISO date), `approval_status` (`draft` or `approved`), `sources`, `education`,
`experiences`, `projects`, `skills`, `constraints`, `unresolved_questions`.
Arrays are empty only when no supported entries exist, not to conceal extraction gaps.

- `sources`: stable source ID, filename, source version/date if known (otherwise null).
  No fabricated hashes; tooling computes actual file hashes after import.
- Every evidence-bearing entry: stable `id`, factual statement/structured values,
  `source_refs`, `verification_status` (`source_supported`, `user_confirmed`, `unresolved`)
  and `use_for_ranking` boolean. Approval of the package does not prove a resume claim
  externally; provenance must retain that distinction.
- `source_refs`: source ID, stable section/item locator, minimal verbatim supporting
  excerpt. A user clarification uses a recorded clarification ID and exact confirmation.
- `education`: degree/field, institution, status, start/end dates with precision recorded.
- `experiences`: organization, title, kind (full_time/internship/part_time/research/other),
  dates and date precision, duties, achievements and technologies. Nested independent
  claims need their own evidence when the parent citation does not support them all.
- `projects`: context (work/academic/personal/other), personal contribution, techniques,
  outcome and scope; link an experience ID if this is the same work, rather than adding
  a second period of employment.
- `skills`: name and supporting experience/project claim IDs, nature of use and caveats.
  Do not infer proficiency, years or production-scale experience from mere mentions.
- `constraints`: factual limitations/corrections on claims, linked to affected IDs;
  these are not employer eligibility decisions or preference weights.
- Unknown fields are null with an unresolved reason. Unresolved/conflicting claims are
  excluded from ranking until resolved; their absence is not negative skill evidence.
  Record partial dates explicitly; never invent day-level precision or double-count
  overlapping employment. Do not use a generic confidence number as evidence.

This is a detailed evidence store, not the full provider payload. #109 defines a
versioned deterministic projection; avoid another independently edited summary file.
Both resume variants contribute facts equally. Duplicate claims retain both sources;
conflicting claims retain alternatives pending operator resolution.

## search_preferences.yaml contract

Top level: `schema_version`, `preferences_version`, `as_of`, `approval_status`, `items`,
`unresolved_questions`. Each item has a stable `id`, `dimension`, `value`,
`strength` (`must_have`, `prefer`, `avoid`, `flexible`, `unknown`), `rationale`,
`source_refs`, `verification_status` (`user_confirmed`, `unresolved`) and
`use_for_ranking`. YAML must use safe plain mappings/lists/scalars, no tags/anchors,
quoted dates/ambiguous strings and no duplicate keys. Null is not false or a refusal.

Cover target and excluded role families, actual desired duties, location/remote/onsite,
relocation, role level, stretch tolerance, full-time/internship preferences, start date,
compensation when specified, work authorization/sponsorship and other operator constraints.
Work-authorization facts and desired employer support are different fields. Do not infer
legal status or eligibility. Unknown employer sponsorship remains unknown even if support
is a must-have. User confirmation is required before old config preferences become active.
No model names, score thresholds, weights, provider settings, watchlists or credentials.
Missing mandatory preference decisions block readiness; optional unknowns may remain if
explicitly acknowledged and conservatively handled.

## Guide and review requirements

`resume_selection_guide.md` compares the two actual resumes: explicit unique emphases,
shared evidence, likely job-duty matches, unsupported claims not to make, and what to do
for hybrid jobs. Selection follows full JD duties, not title alone. It recommends an
existing resume variant or manual tailoring; it does not rewrite the originals or feed
back into JEV as a hard role filter.

`input_review.md` contains:
1. Input/output inventory and versions, missing/incomplete upload detection.
2. Source-to-output coverage table for every material unique claim; explain exclusions.
3. Legacy profile/config items classified as fact, current preference requiring
   confirmation, obsolete scoring policy, operational setting to preserve, or sensitive
   content excluded. Refer to sensitive key names only, never reproduce values.
4. Conflicts, deduplication and corrections with actual user decisions.
5. Blocking questions versus explicitly accepted optional unknowns.
6. Approval record for named output versions, approved only after the operator explicitly
   confirms. Changes after approval reopen approval of the changed versions.

No old scores or screening outputs become ground-truth labels. No JD/eval corpus, labels,
API key or model call is required for this preparation. Actual representative JD pools,
independent human labels, rubric, evaluation thresholds and experiment budgets remain
separate #109/#112 responsibilities; having this package does not complete those gates.

## Handoff acceptance

ChatGPT web checks JSON parsing/YAML structure if tools are available, cross-references,
claim coverage, no invented facts and preservation of both original resumes. If a check
cannot be run, report it as unverified. After return, #109 verifies parsing, privacy,
ignore coverage, hash identity and actual source/consumer compatibility before declaring
any runtime input ready. No unattended import, overwrite, production migration or schema
compatibility claim follows merely from generating these files.
