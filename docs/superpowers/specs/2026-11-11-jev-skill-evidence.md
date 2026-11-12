# Selected convergence slice: skill evidence and safe batch continuation

**Status:** implemented on branch; approved for bounded development measurement under the
operator's continuing USD 10 research authorization. No production activation/GO is granted.
This extends the retained stage attempt cap100→200 using a distinct append-only authorization,
not a new ledger. Historical counters and all monetary/global ceilings stay unchanged.

## Measured problem and selected approach

Preference arbitration has full agreement on the latest ten-job/three-draw development
sample. A single overall skill question still produces unsupported central-gap judgments:
a mandatory alternative language can be missed and preferred techniques treated as core.
Stable repetition is not proof of correctness. Keep those raw outcomes, but stop using a
monolithic skill label as an authoritative account of unmet central requirements.

Select bounded, exact-source per-requirement comparison followed by pure evidence summary.
The main eleven-question pack returns descriptive strong/partial/limited/unknown skill
support, separate from a small sidecar of quoted requirements. Do not add a learned score,
numeric weights or import legacy score/eval vocabularies. Facts are curated proxy evidence
for development, not human gold or a shipped automatic requirements extractor.

Rejected for this slice: further wording-only tuning of an omnibus critical-gap label;
and an unbounded extractor/another paid judge model. A general runtime requirement collector
remains separate work; the sidecar does not establish automatic population-scale operation.

## Source-only implementation

`preselection/skills.py` exposes frozen data classes:

- `ProfileEvidenceRef(block_id, quote, start, end)`: exact Python string offsets in the
  referenced approved background block, never preference text as proof of skill.
- `SkillRequirement(question_id, quote, start, end, obligation, centrality, profile_evidence)`:
  exact offsets in the full supplied JD. Obligation is required/preferred/unclear; centrality
  is central/supporting/unclear. A whole alternative-language clause is one requirement,
  not several mandatory languages. Related factual annotation remains operator-proxy.
- `SkillEvidencePolicy(version, question_set_sha256, profile_sha256, jd_sha256, requirements)`:
  bind all exact inputs and unique question IDs. Atomic packs contain exactly those Choice
  questions with direct/transferable/not_evidenced/unknown criteria. No silent extra facts,
  missing questions, invalid spans or duplicate references within a requirement. The same
  exact background evidence may legitimately support several different requirements. Empty candidate reference lists
  are permitted but do not prove inability or source completeness.
- `derive_skill_evidence(native_payload, question_set, expected_model, jd_text, profile, policy)`:
  revalidate native wrapper/model/question identity and source/profile hashes before deriving
  a separate report. No file/key/provider/DB access, prompt compiler, ranking or eligibility.

Source spans use non-bool integer offsets, 0<=start<end<=length and exact substring equality;
quotes must be nonempty. Profile references name existing unique background blocks; refs
must match their text exactly. Bound strings/counts/versions and canonical policy identity
are validated. Do not trust a frozen dataclass without checking its contents.

Interpret support at the competency/depth the JD actually requests. Direct means evidence
of that requirement, transferable means relevant evidence without establishing the same
competency/depth, not_evidenced means supplied background lacks support, unknown is ambiguous.
An alternative clause is satisfied by a valid option; no preferred requirement becomes a
mandatory gap. A direct/transferable answer without any declared validated background
reference remains visible as unlinked positive evidence and resolves to uncertainty, not an
unsupported positive all-clear. Preserve the raw support value. This affects the core summary
only for explicit/possible core requirements; preferred unlinked positives stay separate. No claim of inability, years, visa status or salary follows from these labels.

Report per-requirement support/provenance and a summary with these semantics:

1. Any required+central fact with transferable/not_evidenced -> core_requirement_unverified.
   This is an evidence gap, not a failed candidate or automatic exclusion.
2. Otherwise a required+central unknown support or a potentially required/central fact
   with unclear obligation/centrality -> unresolved, never a manufactured all-clear.
3. All explicit required+central facts direct, with no unresolved possible-core fact ->
   core_evidence_supported for those selected requirements only.
4. No explicit or possible required+central facts -> no_explicit_core_requirement, not a
   verified pass. Preferred facts never create core gaps; supporting facts stay separate.

Keep all support=unknown requirement IDs visible, including preferred/supporting facts,
without making them core gaps; also retain possible-core uncertainty. A known gap may
determine the summary while other unresolved requirement IDs remain visible.
Include policy/profile/JD/question/response identities, referenced IDs and explicit
`selected_requirements_only` / `operator_proxy_not_gold` provenance. Do not overwrite raw
native values or the main descriptive support label. All completeness/accuracy claims remain
unmeasured and evidence selection bias is disclosed.

## Append-only batch continuation

Generalize only existing `extend_stage_attempts`: retain a history indexed by authorization
hash rather than allowing one amendment. Exact same auth+cap+CAS is idempotent even after
later events; conflicting reuse of an authorization fails. Distinct authorization requires
CAS against the actual latest event and strict cap increase within global remaining attempts.
Preserve old single-amendment replay, original config/anchor, money, counts and stop flags.
Reject malformed/duplicate/reordered events and extension on pending/unknown/over-reserve.
No cost ceiling or account balance changes belong here. Snapshot keeps current effective cap.

## Bounded workload and freeze

Use unchanged approved background/preferences and original ten full development JDs.
Main v6: ten jobs × three fresh draws (30 calls), replacing the main skill question's
critical-gap choice with descriptive four-way support; role/duty/policy semantics unchanged.
Sidecar: up to six existing audited jobs × three fresh draws (18 calls), at most five quoted
requirements per job and one complete job/profile per request. Distinct per-job question
packs require distinct frozen run/cohort bindings and native question hashes; no unbound
real-provider bypass. Optional follow-up repeat/probe must remain within80newattempts for
this slice and within the cumulative200stage cap,5000global attempts,USD0.50stage/USD10global.
One in flight; each batch <=15minutes; no automatic retry. Original24KBrequest/128KBreply
bounds, exact model/rate preflight, conservative reserve and unknown-charge stops remain.
No new résumé source, old score/application note or other paid provider. No truncation.

Requirement/JD/profile facts, source spans and proxy expected support are frozen before
new sidecar answers; these ten jobs have prior exposure and are never independent gold.
The operator is asked only batched genuinely ambiguous personal facts/preferences; technical
classification and source-span checks are handled without repeating accepted decisions.

## Verification and ownership

Luna/max owns source/tests; orchestrator owns docs, private facts/question packs and live
execution. Test summary truth table, alternatives represented as a whole requirement,
exact Unicode/string offsets, required/preferred ambiguity, background-vs-preference refs,
wrong hashes/model/native values and raw immutability. Test multiple amendments, restart,
exact repeat after later events, conflicting auth, stale CAS and unchanged costs/counters.
Blocked legacy imports/resources must still allow actual new evidence derivation and ledger
continuation. Full worker-only pytest coverage>=85%, schema/privacy/staged-diff checks;
no web change. No merge/deploy or large unseen-cohort expansion in this slice.
