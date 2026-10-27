# Pivot input contract

**Status:** selected input boundary. Private profile contents remain draft until operator
confirmation. This document defines preparation and #109 requirements, not deployed code,
a chosen provider/rubric, approved evaluation spend or a changed screening policy.

## Single source of active personal context

`candidate_profile.json` is the sole editable source for the new pivot. It contains
English background evidence and current search preferences. `candidate_context.txt` is
a deterministic, concise rendering of that file, regenerated on edits. It is not a
second manually maintained profile. The private draft package lives under ignored
`apps/worker/resume/pivot/`; no personal content is committed to this repository.

The profile schema is deliberately small:

```json
{
  "schema": 1,
  "version": "operator-controlled",
  "as_of": "YYYY-MM-DD",
  "status": "draft",
  "background": [{"id": "stable-id", "text": "English facts with scope limits."}],
  "preferences": [{"id": "stable-id", "text": "English preference and unknown policy."}]
}
```

Status is `draft` or `approved`. Each ID is unique. Date precision is not invented.
Work/internship/academic/open-source contexts, chronology, ownership, relevant tools and
material caveats remain explicit in text. Unsupported skills are unknown, not absent.
Do not strip caveats because they are not positive scoring evidence. Preference strength,
exceptions and unconfirmed decisions remain explicit, rather than inferred from a label.
A profile does not contain rubric weights, thresholds, provider configuration or scores.

Offline `provenance.json` maps block IDs to evidence IDs and exact source hashes. It is
for audits and editing, not a model input. Original evidence remains unmodified. Import
is a one-time editorial operation, not runtime fallback or a permanent dependency on an
older file format. The new profile owns subsequent updates and versioning.

## Exact inputs by stage

| Stage | Model input | Not included in that request |
|---|---|---|
| JD extractor experiment | One full JD plus extraction schema/instructions | Candidate profile, preferences, resumes, evidence archive |
| JEV direct experiment | Candidate context + company/title/location/full JD + narrow typed questions | Both resumes, provenance/review/manifest, raw old inputs, other jobs |
| JEV extracted experiment | Same candidate context + company/title/location/validated JD facts + same questions | Extractor boilerplate, entire evidence archive, other jobs |
| Daily Brief | Candidate context once per run + compact resume guide + bounded ATS metadata, application/source evidence and full selected JDs | Bulk evidence archive, legacy profile/config, repeated candidate context per job |
| Resume choice/tailoring | Read the relevant original resume(s) on demand after full JD review | Do not send both resumes with every JEV call |
| Human labeling | Same frozen candidate context + original full JD + label guide; richer evidence available for adjudication | JEV ranks/answers hidden from blind labelers |

For extracted input, missing coverage is explicit; invalid/incomplete content cannot
become a low score by omission. The stored original JD remains available to final review.
Metadata already present elsewhere in an envelope is not repeated in prose. Posting IDs,
URLs, hashes, timestamps, cache versions and delivery state stay outside JEV state unless
a specific question actually needs them. Preserve these values in local provenance and
Daily Brief where they support identity/source checks. Never remove original source text
from storage to save inference tokens.

## Generated text and token discipline

Render exactly:

```text
AS OF <as_of>
BACKGROUND
<background text, in declared order, one paragraph per block>
SEARCH
<preference text, in declared order, one paragraph per block>
```

Schema/version/status/block IDs are validated and recorded locally, not repeated in the
model state. Use ordinary concise English; paragraph text carries meaning without large
repeated JSON keys, source quotes or explanatory boilerplate. No per-call generated
personal summary, obscure abbreviations or lossy truncation. Model data remains separate
from fixed task instructions and JD text is untrusted data.

The initial candidate-context target is about 2,000 tokens or less, measured using the
selected provider tokenizer before live evaluation. This is a review budget, not a hard
truncate rule or a claim about model capacity. Overflow needs an explicit edit/review;
never silently drop unique experience, ownership boundaries or opportunity uncertainty.
Measure the actual complete request, including question definitions, extraction cost
and provider overhead, before comparing strategies. Local alternate-tokenizer counts
are labeled proxies, not JEV billing. Cache discounts are not assumed.

Freeze questions, profile and JD identities independently. Stable context can precede
variable JD state if the provider supports that shape; cache effects need measurement.
Do not add a separate classification request per job solely for architectural neatness:
independent role and dimensional questions can share one per-job request when supported.
This is distinct from rejected multi-posting inference batches.

Compression is an evaluated transform. Compare selection on the compact profile against
richer evidence during development/adjudication, especially for hybrid and less prominent
experience. Shorter input alone is not a recall or cost success. A profile change can
change ranking even if it only looks editorial; version/hash it and revalidate affected
assessments before calling them current.

## Private files and authority

- `candidate_profile.json`: editable English facts/preferences; authoritative new input.
- `candidate_context.txt`: generated provider/Brief view; never edit independently.
- `resume_quant_dev.txt`, `resume_swe.txt`: current resume variants, English, preserved
  from the operator-supplied newer source; not assumed identical to old repository copies.
- `resume_selection_guide.md`: concise English downstream presentation advice only.
- `provenance.json`, `input_review.md`, `token_report.json`: local audit, unresolved
  decisions, actual approval and measured size; never sent as routine ranking context.

The source evidence archive may retain original-language quotations. Active profile,
guide and review are English. Translated confirmations are not represented as verbatim
English originals; source IDs preserve where their meaning came from. Rewriting historic
quotes is not required to make runtime input English.

No new pivot reader loads legacy `personal_profile.txt`, `config.yaml`, a Registry,
old `fit_profile`, score tiers, prompts or eval corpora to fill profile gaps. A missing
new profile is a visible configuration error, not permission to fall back. Old Registry
synchronization never gates new confirmed facts. Existing operational config and optional
legacy scorer remain their own compatibility path; this contract does not migrate,
remove or reconfigure the deployed worker or grant new hard-filter authority.


## Required-experience policy and authorization context

The new search input can declare a hard exclusion for an explicit mandatory professional
experience floor. Apply the configured threshold to supported JD facts, not a fit score,
candidate-years-plus-margin formula or seniority title. With a synthetic threshold of 2:
`2+`, `at least 2` and required `2-4` exclude; `0-2`, `1-3`, `up to 2`, `2 preferred`,
unstated/ambiguous years and an applicable lower-YOE alternative do not. Skill-specific
required professional experience counts; degree duration and unrelated year figures do
not. A lower preferred requirement cannot cancel a higher mandatory one. Qualification
alternatives must be preserved and matched to supported candidate facts; unknown pathway
applicability stays unresolved. Record the exact JD evidence, required/preferred status,
range/alternative structure and policy version. Never reuse the old scorer's global
minimum-of-all-numbers heuristic as a new hard filter.

This exclusion is explicit operator policy, separate from advisory JEV priority. It
requires a new scoped extraction/validation plus deterministic comparison in Luna's
implementation; the current standalone screen has no equivalent YOE exclusion. Existing
legacy seniority assistance only reorders fit work and is not the implementation of this
contract. Preserve rejected rows/evidence and basic inventory access, and report exclusion
separately from a low ranking. No deployed screening verdict or triage label changes are
implied by editing this profile.

Authorization facts must distinguish current permission, candidate-reported eligibility
for an extension, approved extension, maximum total duration and remaining duration.
Record only supplied facts. A potential extension is conditional, not already granted;
never derive remaining time without actual dates. Unknown employer sponsorship remains
unknown. Do not request or publish private authorization documents for these fixtures.

## JEV price evidence

Acceptance records the provider/resolved model, price currency, billing unit and effective
rate date/version; retain the actual quoted/billed price source used by the run. Per
attempt record request identity, input/output and cached usage where available, reported
charge, status, latency and retry linkage. Include failed/timeout/repaired attempts and
any additional provider fees. Keep provider-billed charges distinct from token-rate
estimates; missing cost is unknown, never zero. Non-token pricing uses its actual unit.

Aggregate cost per unique job, successful assessment, direct/extracted arm, repeated draw
and full run, including extraction/escalation. Report actual batch/day cost and only
explicitly labeled daily-volume projections. Compare against quality/recall and total
workflow cost. A cheap average cannot hide expensive failures or exceed the approved
attempt/time/money limits. Fake-provider tests cover partial usage, missing prices,
retries and resume without double counting. No price is hardcoded from an old provider
or assumed from a local tokenizer; actual provider pricing is checked at run time.

## Scorer isolation prerequisite

The [scorer boundary inventory](2026-10-26-legacy-scorer-boundary.md) and #116 separate
active screen support from old fit/research imports before new pivot implementation.
Do not reuse the old glob-based resume loader, system-prefix builder, fit schema,
SCORER_VERSION, fit_profile hashes or extraction/corpus tools for this profile. Existing
operational config still owns deployed intake/screening until a separately selected
cutover; it is not a fallback source for the new profile.

## #109 acceptance boundary

Validate the new JSON, exact rendered text, English content, IDs, scope/unknown handling,
provenance links/hashes, file privacy and version-scoped operator approval. Do not require
old files or six old preparation outputs as runtime dependencies. Resolve ambiguous
cross-family priority before giving it numeric weights; otherwise leave that dimension
neutral. Provisionally retained salary/eligibility ambiguity is not a confirmed positive.

The offline profile validator/renderer and synthetic replay fixtures live in #110;
request construction and cache integration remain unselected. Relevant schema and
DI/Prisma rules still apply to persisted assessments. #109 still owns rubric/model,
selection policies and experiment budgets; representative JD pools, independent labels
and #94 unattended acceptance remain separate prerequisites.
