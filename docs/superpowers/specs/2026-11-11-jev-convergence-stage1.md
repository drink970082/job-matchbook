# JEV convergence Stage 0/1 contract

**Status:** implemented on branch; approved for the bounded Stage 1 experiment by the
operator's instruction to begin executing the USD 10 convergence plan. This approves no
production activation. Exact private input hashes are frozen separately before dispatch.

## Selected scope

Extend accepted isolated JEV tooling on the unmerged `feat/openrouter-jev-shadow` stack.
The operator requires separation from legacy score/eval modules. Use `preselection/`
contracts, not old score prompts, Registry, eval engines or corpus/label loaders. Pure
neutral infrastructure is allowed. Blocked-import/resource tests cover new entrypoints.
This is #132's bounded provider/repeat preparation, not #112 quality GO or #131 completion.

Execute the existing ten development jobs with the audited v2 eleven-question pack and
profile containing only the three accepted preference clarifications. Three independent
provider draws per job, separate draw identities and fresh calls; cache hits are not draws.
Question/profile snapshots remain unchanged during these 30 planned observations. Exact
model stays `typesafe/jev-1.13` resolved to the verified canonical identity. Transport bounds
remain 24,000 request bytes and the existing approved reply bound; no context truncation.

At most 40 attempts including retries, one in flight, 15 minutes execution for this batch,
USD 0.50 stage ceiling including USD 0.002003148 historical inference spend. Global cumulative
ceiling USD 10, normal dispatch ceiling USD 9, maximum 5,000 attempts; reserve USD 0.15
conservatively before each call and reconcile verified actual charges. No alternative
provider, new judge model, paid extraction, credit purchase, runtime schedule or DB writes.

## Minimal isolated implementation

### Durable campaign budget

Provide a locked, append-only, fsynced local campaign ledger. Every mutation validates the
complete retained event stream and frozen campaign identity/configuration. Record historical
spend explicitly; attempts already dispatched in previous mechanics segments count as ten
historical attempts. Stage 1 includes their cost but its new40-attempt cap counts new calls.
Represent amounts with finite nonnegative Decimal-compatible values, never binary-float
accounting. Persist reservation before allowing dispatch; check pending reservation plus
settled spend against campaign, phase and reserve limits. A campaign restart must not reset
counts/spend. One unclosed reservation stops new paid work, since delivery may be unknown.
Actual settlement is idempotent only for an identical reservation and exact charge; altered
settlement, duplicate IDs or malformed/corrupted/truncated events fail visibly. Unknown
settlement stops further dispatch. Do not rewrite original provider-attempt journals.
Use filesystem locking so two controllers cannot reserve concurrent calls. No network/key
access belongs in this module. The one-off operator harness wraps the existing supervised
shadow transport; a kill between dispatch and settlement leaves visible pending accounting.

### Repeat/stability report

Use only validated native per-job/per-draw assessments from this new cohort. Record schema,
model/profile/question identities and explicit expected job/draw membership. Reject duplicate
draws, mismatched question sets, missing/extra answer IDs and unsupported native values.
Report completed/planned calls, missing draws, per-field counts, agreement with modal answer
and pairwise repeat agreement, plus major preference reversals and contradictions. Do not
allow a pooled average of easy fields to hide a bad decision field. Confidence is descriptive,
not a calibrated correctness estimate. Missing draws remain missing, not agreement.

Initial contradictions: quant-SWE or Python-quant supported with preference=adjacent;
preference=primary with neither first-target role supported; primary-versus-avoided across
repeats. These checks apply only with an explicit supplied policy declaration saying those
role IDs are first-target families. Do not hardcode one candidate's family priorities into
a general-purpose reporter. A model contradiction stays in raw evidence and is queued;
reporting does not repair answers, create quality gold or invent a priority rank. Other
unknown semantic cases remain audit items rather than regex-based verdicts.

## Verification and ownership

Luna/max implements; orchestrator freezes private data, reviews exact code and runs the
operator experiment after acceptance. Demonstrate ledger caps/restart/idempotence/unknown,
corruption and competing reservation behavior; pure three-draw counts and contradictions;
blocked legacy modules/resources. Run targeted tests, full worker coverage >=85%, schema,
privacy and diff checks. Update SPEC current tooling, PROGRESS residual, CHANGELOG and
relevant traceability with code. No real data in public fixtures. No self-merge/deploy.

The report is a development stability measurement, not accuracy, discrimination, complete
pool recall or release acceptance. Failure prompts a scoped diagnosis; no unbounded retry,
automatic question edits or a new campaign that resets spending. Stage 2 remains separate.
