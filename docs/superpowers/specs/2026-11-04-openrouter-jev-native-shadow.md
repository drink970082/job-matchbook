# OpenRouter JEV native shadow contract

**Status:** approved for the offline implementation slice described below. The operator
selected OpenRouter/JEV, directed reuse of the Fantasy implementation, and approved the
native-adapter handoff and continued implementation. This approves code and hermetic
verification, not a provider invocation, private source-pool read, live rubric or rollout.

## Problem

The accepted shadow mechanics use generic typed answers with generated explanation and
source evidence. OpenRouter System One JEV returns native Choice/Score/Noul values,
probabilities/confidence and usage instead. Manufacturing explanation/evidence would
misrepresent the provider result. Reusing Fantasy's async/internal-retry service unchanged
would bypass ATS's supervised process and per-attempt accounting.

## Selected boundary and alternatives

Select an explicit native response contract and a thin synchronous injected OpenRouter
transport sharing ATS shadow supervision. Preserve the current generic contract unchanged.
Reject adapting native answers by inventing free-text explanation/source spans. Reject a
separate unsupervised runner or importing the Fantasy application/database. No dependency
addition: synchronous HTTP is injected and production wiring is deferred.

These choices follow PRINCIPLES 2/3 (fact/unknown integrity), 4 (optional assistance),
5/10 (visible failure and dependency injection), 7 (no new dependency), 9/11 (no DDL or
production DB path), and 12 (synthetic fixtures; private input never committed).

## Files and responsibilities

Implementation is confined to `apps/worker/ats_worker/preselection/`: a native contract
module, an OpenRouter wire adapter module, and the existing `shadow.py`/`evaluation.py`
seams. Tests/fixtures live under `apps/worker/tests/`; fixture content must be synthetic.
No `run.py`, pipeline, config, screen/scorer, Prisma schema, Web, service or runtime-default
changes. SPEC/PROGRESS/CHANGELOG and this implementation plan describe current behavior.

The native contract has a version/hash distinct from generic questions. Each question
has an ID, independent instruction and native criteria. Choice has named criteria; Score
has ordered criteria; Noul returns a bounded probability. Multiple independent role
questions support hybrid roles. No implicit numeric weights, qualification probability,
confidence threshold or overall fit score is selected.

Native validation must retain native values, probabilities and available confidence.
Unknowns remain explicit. No evidence/explanation is synthesized. Transport model/usage/
cost metadata remains separate from answer semantics. Preserve complete native responses
in private journals and use validated typed values for existing aggregate evaluation.

## Request and provider boundary

The injected transport performs one synchronous HTTP POST per attempt to the fixed
OpenRouter System One endpoint. It sends `model`, one-job `state`, and the native question
map. Do not send generic output schemas or demand generated explanation. Keep all task
instructions distinct from untrusted job/candidate data. Complete JD/context are retained;
reject oversize input rather than truncate. Extraction is not a JEV capability and is
rejected by this transport. A separately injected extraction transport is a future scope.

The injected caller owns the key, HTTP function, timeout and explicitly observed model/
rate metadata. Importing/constructing the modules never reads credentials/environment,
private files, production data or opens a socket. No implicit client SDK retries or
redirects. Exactly one externally visible call must correspond to one outer durable
attempt record. An ambiguous connection failure remains delivered/unknown and must not
silently retry. Explicit retryable statuses use ATS outer backoff and bounds.

Any metadata helper also uses injected synchronous HTTP and bounded responses; no hidden
metadata/model-resolution lookup inside inference completion. A caller must supply the
expected canonical model and price evidence before execution, not assume a model slug or
rate from tests. Freeze the request/response contract, model and rate in provenance.

Usage/cost must be finite, nonnegative and well typed. Missing charge stays unknown;
provider-reported charge is distinguished from rate estimation and audited invoice
charge. Do not assume free output/cached calls or treat byte length as actual tokens.
Bounds for reply size, serialization and parsing must fail visibly without leaking
headers/keys/raw private error bodies. The original supervised wall-clock boundary
covers transport and validation.

## Shared execution and evaluation

Native invocations must use distinct prompt/schema identity and native question hash.
Frozen RunBinding, cohort membership, variants/draws, model/limits/retry enforcement,
cache identity, process supervision and journal accounting still apply before dispatch.
No separate unchecked JEV path. Adding a native bounded JSON worker-wire representation
must not deserialize provider objects or weaken the generic reply boundary.

The journal retains native reply shape and contract identity. Evaluation joins native
values to the successful journal response and frozen outcomes without fabricating
citations or omitting raw native probabilities from private artifacts. Reports remain
aggregate-only; no GO or production state is written. Existing generic journal/report
compatibility remains covered. Any required journal schema change must reject ambiguous
old/new provenance explicitly, not reinterpret past generic answers as native replies.

## Acceptance

- Native request/response tests cover Choice/Score/Noul, hybrid independent questions,
  distributions, finite ranges, unknowns and malformed/missing/extra answers.
- One injected POST has one outer attempt; explicit retries, ambiguous delivery,
  missing/unknown costs, model mismatch, timeout, bounded reply and resumed limits remain
  visible and conservative. No hidden retry or automatic extraction/model substitution.
- Fake synchronous adapter runs inside the real supervised no-process/no-thread boundary;
  frozen outside-cohort/mutated-binding cases fail before side effects or cached reuse.
- Private journal round-trip/cache/report joins retain native answers and uncertainty;
  changed recorded answers/provenance are rejected. Original generic tests still pass.
- Fresh-process import/resource boundary, worker suite/coverage (85% floor), synthetic
  integration, schema/privacy and diff checks pass. No actual provider call is needed.
- A composed synthetic native request through transport, journal/resume and aggregate
  report is driven, not merely isolated parsing. Report actual commands/results.

## Remaining live scope

Provider account availability, exact resolved model/rates, complete-request tokenizer,
cohort completeness, approved live questions, human labels, precise pilot caps and
#94/#96 gate disposition remain #109/#131/#132/#112 work. This code does not establish
ATS quality, observed real spend, #112 GO or activation. The standalone worker/screener
and current deployed Web stay unchanged.
