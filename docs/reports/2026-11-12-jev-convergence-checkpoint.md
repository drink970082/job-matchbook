# JEV advisory-scoring research checkpoint

**Status:** no production GO. Candidate preference calibration and the bounded Haiku
comparison are authorized. JEV measurements below remain unchanged; the completed
Haiku comparison is reported in the [Haiku checkpoint](2026-11-12-haiku-comparison-checkpoint.md).
Measurements are current to the 2026-11-12 UTC checkpoint.

## Measurements and limits

| Input shape and cohort | Fresh calls | Jobs with identical repeated preference |
|---|---:|---:|
| Full-profile v7, exposed development40, two complete passes |80|39/40|
| Role-only v8, same exposed40, two passes |80|37/40|
| Frozen v8, new100source postings, two passes |200|98/100|
| Separate persona-neutral role facts and seven avoidance predicates, exposed40 |160|40/40|

The last result still contains stable semantic errors, including excluding accepted visual
inference systems work and missing an embedded/device-work avoidance. Splitting a rubric
into separately inspectable predicates improves observability, not established correctness.
Do not keep adding wording or employer/posting exceptions to obtain perfect development
agreement. No candidate-background influence is proved causally: the role-only ablation
also omits eligibility context and unrelated questions.

The100source-posting expansion excludes prior exact IDs, source identities, JD hashes and
company names. It has76normalizedcompany-name groups; aliases/templates are not independently
reconciled. Selection is purposive, with an AI-infrastructure title-stratum shortfall,
one over-bound payload omitted without truncation, and two nonemployment event controls.
It is not a full daily roster, verified live availability or an independent human-gold set.
Original source text is retained; boundary whitespace is normalized for execution only.

Only16cases have pre-model quoted-duty proxy expectations:13single-value and3multi-value.
Eleven of the13single-value cases are admissible on both draws; all3multi-value cases are
admissible. One singleton disagreement is an abstention that may be defensible from sparse
role duties; the original proxy expectation remains available rather than being rewritten
to improve the result. The remaining84cases are quality-unlabelled. These counts are not
human accuracy or population recall. Missing draws are never counted as repeat agreement.
No numeric confidence threshold, family weight or scalar fit score is introduced.

## Accounting and code acceptance

The retained campaign has850attempts including prior history,849provider dispatches and
one proven local pre-dispatch failure. Cumulative accounted cost isUSD0.140438676, with no
pending/unknown/over-reserve charges. The effective attempt cap is1000; the JEV stage
monetary ceiling remainsUSD0.50includingpriorcost and the global ceilingUSD10.

One interrupted dispatched response remains lost. Operator Activity token counts/order
match all21retained neighboring responses; the unmatched row's charge is reconstructed
from the frozen token rate, not presented as an unrounded invoice. Another local failure
is proved by frozen-code replay: the stale dispatch guard rejects before both the fsynced
network marker and `session.post`. Its zero-charge reconciliation appends an evidence/CAS
record while retaining the original unknown event and attempt. No journal rewrite, counter
reset, automatic retry or assumption of zero cost from an absent response is used.

The manual reconciliation change passes1669worker tests with1skip and85.14%coverage;
39focused ledger/import-boundary tests, schema drift, privacy and diff gates pass. The
blocked-resource test executes reconciliation with legacy scorer imports/resources denied.
Web/E2E were not rerun: this change has no Web/runtime surface. Production data, screening,
legacy scoring/evaluation and activation remain outside the experiment.

## Selected native follow-up

JEV remains the intended route. Haiku is only a comparator; its closed bounded epochs
have separate [evidence](2026-11-12-source-id-v3-checkpoint.md), not a model replacement.
The [native return contract](../superpowers/specs/2026-11-12-jev-return-comparison.md)
retains unchanged native v8 on the same34frozen comparator sources×2draws:68/68valid,
29/30new-source repeated preferences, but stable semantic avoidance concerns. The
[return checkpoint](2026-11-12-jev-return-checkpoint.md) records linked1182attempts/
USD0.495215896and the preserved five-ledger bridge. Old stages remain closed. No prompt tuning,
provider fallback, model superiority or human-quality claim follows from this diagnostic.
Independent labels/fixed-requirement design remain separate future gates. No runtime,
merge, deployment or production GO.
