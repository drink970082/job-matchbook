# Source-ID fact/skill separation research

**Status:** closed bounded research epoch; see the [checkpoint](../../reports/2026-11-12-source-id-separation-checkpoint.md). Execution was scoped under the operator's standing continuous
USD10research directive, using the already approved Haiku/Anthropic route. This changes
neither provider/model nor production behavior. The initial60-attempt comparison stays
closed; its failed attempts, raw replies, charges and exposed sources remain retained.

## Decision and bounds

The direct six-axis experiment demonstrates two distinct limits: free-text quotes can
be paraphrased, and personal context/compound avoidance judgments can contaminate role
classification. Its30jobs are now exposed development material, not untouched validation.
More wording or employer-specific fixes are not selected. Test a structural protocol:

1. One persona-neutral job-fact request, containing no candidate background/preferences.
2. One independent skill comparison with the exact approved background only, omitting
   preferences and retaining the full JD. It is not a paid judge of the first answer.
3. Versioned ordinary rules derive preferences from job facts; raw outputs stay separate.
   No weights, confidence thresholds, scalar fit score, automatic discard or eligibility
   pass. Unstated facts remain unknown; selected skill coverage is not all-clear.

Use15sources (5exposed controls/10new source-name-excluded postings), two fresh draws of
each pass: max60additionalattempts including errors, one in flight, no retries, two450second
execution segments, USD1new-stage cap inside cumulativeUSD10. Same frozen Haiku5.5alias,
advertised20261007backend, Anthropic-only route, low-effort reasoning with reasoning text excluded,4096total output tokens,
24KBrequest/128KBreply/45second HTTP timeout. No new private resume sources or legacy
score/eval inputs. Exact data/proxies/question sets/policy and wire mode freeze before calls.

A linked stage ledger carries910priorattempts/USD0.221028176from the initial comparison
and all JEV history. Both predecessor ledgers/final hashes are frozen and checked before
new reservations; old selected stages are not resumed. No failed attempt or prior bill
is reset. Global5000attempt/1000new-JD scope and USD10/USD9global/ordinary ceilings remain.
Source-ID wire profile is `source-ids-haiku-low-reasoning-4096-v1`; quote mode remains
2048tokens/reasoning disabled. Conservative full-context cost isUSD0.51024before a20%
margin, below theUSD0.65reserve after fresh public-rate/context revalidation; the new
stage ceiling is prior spend plusUSD1. This is private operator orchestration, not an
unattended multi-stage budget service or a new production model selection.

## Source-ID transport seam

Keep the existing quote mode byte-identical. Add explicit caller-frozen
`evidence_mode='source_ids'` and `require_candidate_evidence` options to the pure wire
builder and injected transport; default quote mode remains unchanged. The caller binds
mode/minimums, citation-index version and every exact wire hash in the run declaration's
label-guide hash, and uses separate question-set versions/journals for the two passes.
Do not silently claim the generic Invocation cache identity encodes transport options.

A pure immutable citation index assigns stable J/C IDs to lossless source blocks with
exact source/start/end/text, including repeated paragraphs. Every source character remains
reconstructable; no truncation or semantic shortening. Resource-bound blocks<=1000Unicode
characters, preserving whitespace. Heading/blank-only blocks are noncitable. Candidate
context is citable only under canonical BACKGROUND; SEARCH/preferences, AS OF and headers
remain present but noncitable. An empty profile has zero citable C IDs.

Generic recognized headings annotate duty/qualification/unknown and local heading strength
required/preferred/unknown, not clause requiredness or a job verdict. Normalize only the
heading comparison, deleting apostrophes and folding other punctuation/whitespace/case.
Unrecognized text stays unknown. Do not infer skills, duty prevalence or eligibility from
these annotations. Keep original source text untouched.

The model sees full lossless `{id,section,text}` source arrays. Each answer's evidence is
`{jd:[IDs],candidate_context:[IDs]}` with actual-source enum constraints: JD1–3, candidate
0–2 or1–2when required; zero available C IDs forces an empty array unless candidate evidence
is required, which fails before HTTP. No model-authored quote text or offsets. Local
normalization rejects unknown/header/wrong-source/duplicate IDs and derives exact source
references for the ordinary typed validator. Metadata/raw reply remain distinct from
normalized references. Real source IDs prove provenance, not semantic entailment.

## Interpretable fact policy

The fact pass describes financial-markets quant scope, whether programmatic implementation
is primary, main work types and language scope. Definitions distinguish financial quant work from
nonfinance quantitative metrics; implementation from qualifications; pure UI from backend
work; model training from inference systems; IT operations from maintaining software; and
mandatory/core C++ from alternatives. It never sees personal aversions or ability gaps.
The skill pass asks only demonstrated support and one selected explicit central required
competency. Preferred-heading evidence alone cannot manufacture a central mandatory gap.

Rules retain positive role evidence alongside avoidance/uncertainty. A main-duty claim
backed only by known qualification sections is unverified, not repaired. Quant-primary
requires financial-quant evidence; ETL mixed with BI and coded alpha remain acceptable.
UI-only, chip/embedded, explicit very-low-level core C++, confirmed primary nonengineering
operations/sales/reporting, excluded-domain modeling and moderation remain the operator's
avoidances. Inference systems are not vision-model training. Mixed/contradictory work stays
unresolved instead of manufacturing a forced rejection. No company names enter the policy.
Unknown eligibility remains separate from work preference/skill support.

## Acceptance

Luna/max implements the narrow pure citation-index/transport option. Test lossless Unicode/
whitespace/repeated-text offsets, exact heading provenance, unavailable IDs and required
sources, quote-mode stability, one supervised generic source-ID roundtrip, known failure
accounting and actual execution with legacy modules/resources blocked. Full worker
coverage>=85%, schema drift, privacy and staged diff gates apply with SPEC traceability.
The orchestrator freezes source/proxy/policy/body identities, accepts code, and runs bounded
calls. Report newly exposed versus control cases, missing/invalid fields, source validity,
repeat consistency and semantic proxy errors separately. No human accuracy, population
recall, production GO or causal model-superiority claim follows from this small slice.
