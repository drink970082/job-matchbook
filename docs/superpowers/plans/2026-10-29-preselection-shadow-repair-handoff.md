# Preselection shadow and evaluation: next-agent repair contract

**Status:** ready for a separately started Luna/max repair session. This document does
not start that session, run inference or approve a production integration. The offline
assessment view, review-batch replay and synthetic rehearsal are available on main;
SPEC and their tests own those contracts.

## Scope and source of truth

Repair [#111](https://github.com/drink970082/job-matchbook/issues/111), then
[#112](https://github.com/drink970082/job-matchbook/issues/112), using fabricated data and
injected fake providers only. Issue bodies own acceptance and status. The operator's
approximately 200-posting daily throughput need is selected; do not ask them to justify it
again. #94, private-profile approval, provider/model selection, price and #112 GO are live
gates, not prerequisites for these software corrections.

| Source | Verified repair baseline | Meaning |
|---|---|---|
| `feat/preselection-shadow-provider-neutral` | `f49e95ba79243ed7330ce20aab82ac7260f6a6c6` | Unaccepted #111 shadow implementation |
| `docs/preselection-evaluation` | `5f04208a5b63f87d9aa87b29c0b123d899c0fc49` | Unaccepted #112 evaluation implementation, based on #111 |
| `feat/profile-replay-input` | `7a146ca` | Unmerged #110 prerequisite |
| `feat/screening-isolation-prefactor` | `c3bb183` | Unmerged #116 prerequisite |
| `fix/private-profile-input-ignore` | `d4ea0e9` | Separate #109 privacy branch; not accepted by this assignment |

These are reference heads, not assertions about the next session's current state. Fetch
and compare actual remote refs first. The shadow/evaluation modules are not part of main;
do not mistake the available synthetic UI/batch modules for accepted provider machinery.
PR #107 remains a separate draft design, not blanket approval of live model work.

## Branch and ownership rules

- Read AGENTS, session-boot, PROGRESS In flight, DEVELOPMENT and relevant SPEC sections.
  Read SCORING before touching any scorer, prompt or evaluation; existing measured
  failures and forbidden scorer dependencies remain constraints.
- Use isolated repair worktrees. For this continuation of unmerged work, repairs may
  extend the verified #111/#112 source histories instead of pretending those modules
  already exist on main. Claim each actual repair branch in PROGRESS. Inspect divergence
  and other sessions' claims before extending any branch.
- Preserve the source branches and all private files. No force push, history rewrite,
  reset/stash/clean of the primary checkout, runtime checkout changes or deletion of
  unmerged work. Normal fetch/push may need the platform's permitted network path;
  sandbox DNS failure is not evidence that host DNS needs changing.
- One focused repair PR per issue, explicitly targeting main. Disclose included
  unaccepted #110/#116/design prerequisites and the exact new repair range. Their presence
  does not grant merge readiness. The orchestrator separately reviews those prerequisites.
- #112 must consume the actual repaired #111 API/output. A disclosed local stack is
  allowed for draft preparation; carry only the necessary verified repair commits and
  identify them. Never publish a duplicated algorithm as an integration test.
- Luna/max implements and pushes draft PRs; Astra/Sol independently reviews exact heads.
  Do not merge or deploy. This assignment does not repair #109/#110/#116 or launch another
  issue unless a concrete in-scope dependency needs an explicitly explained small change.

## #111: enforce the deadline and bounded retry contract

The baseline `Transport.complete(invocation)` receives no remaining timeout. The caller
checks elapsed time before/after a blocking call. A 10 ms cap with a fake 150 ms call
returns only after roughly 150 ms; a non-returning call is unbounded.

Required behavior:

- Establish one absolute monotonic run deadline, derive the remaining allowance for
  extraction, assessment, retries and backoff, and refuse work after exhaustion.
- Enforce the bound at the transport/execution boundary. Merely adding a timeout argument,
  checking elapsed after completion, or abandoning a still-running worker thread is not
  acceptance. Use a supervised cancellable execution boundary or a transport with an
  enforceable bounded lifetime; unsupported non-cancellable execution must fail before
  the call. Demonstrate the public entrypoint with a blocking/non-returning fake and prove
  bounded return plus cleanup. Do not let executor shutdown silently wait forever.
- Preserve honest started/completed/failed/ambiguous-delivery records, retry linkage,
  reservations, usage and charge-unknown semantics. A timed-out call may have been sent;
  never mark it free/not-sent or automatically replay ambiguous delivery. Persist state
  before execution and retain safe resume/circuit-break behavior after timeout/crash.
- Add an injected, bounded retry/backoff policy. Include waiting in the same deadline,
  check attempt/cost ceilings before retry, and never busy-loop. Tests use injected clocks
  and sleepers; one bounded execution-boundary test may measure real elapsed time with a
  generous non-flaky tolerance and prove worker cleanup.
- Keep full JD/location, one-job payloads, JD-only extraction, exact profile/question/model
  identity and default-off behavior. Do not import legacy score/prompt/Registry helpers.

Evidence must include timeout cleanup, no retry after ambiguous delivery, retryable versus
terminal errors, backoff exhaustion, budget spent on failures, persisted resume, and an
incomplete-extraction result produced by the actual #111 path for #112 composition.

## #112: provenance, pre-assessment outcomes and recurring pools

### Bind declarations to frozen run and attempt evidence

The baseline report accepts changed valid profile/question/pool/split digests against an
unchanged journal. Validate actual content identities from the frozen synthetic inputs
and captured invocation/run records; a canonical hash of the newly submitted manifest
alone does not establish that those inputs produced the recorded calls.

Capture the run/input linkage before attempts and validate it when reporting. Mutating
each declared digest with an unchanged journal must fail visibly. Test swapped/missing
run linkage, altered frozen payloads, mismatched attempts and identical valid input.
Do not claim cryptographic authenticity of an editable artifact; the guarantee is checked
content/provenance consistency. Keep private research payloads out of public reports.

### Admit valid outcomes before assessment exists

An actual incomplete extraction returns `unresolved_input`, an extraction request identity
and no assess attempt. The report must represent that outcome and its real usage/cost,
without inventing an assess call, score or missing-result label. Exercise failed, incomplete
and ambiguous extraction paths as well as actual successful direct/extracted assessments.
Preserve denominators and unresolved/error evidence; do not shrink cohorts to obtain PASS.

### Separate occurrence from stable inference identity

An unchanged posting may remain in two daily pools. Use a pool occurrence identity distinct
from the stable inference/cache/work identity. Preserve genuine cache reuse and draw/variant
identity; do not fabricate a changed work hash merely to satisfy uniqueness.

Test repeated days, deferred/retry membership, identical cached results, changed input
versions and split/group integrity. Count occurrences for workload coverage while charging
each actual attempt once. Repeated occurrences must not bypass held-out/group leakage
guards, manufacture independent labels, double-count cost or imply reading/delivery.

## Required validation and delivery

1. Reproduce each baseline failure with meaningful synthetic tests before changing it.
2. Add real fake-provider #111 → journal → #112 report composition. Do not construct every
   journal by hand or mock the algorithms whose compatibility is being claimed.
3. Run affected worker tests/coverage at the existing 85% floor, required integration,
   fresh-process isolation/private-access guards, schema/privacy and diff checks. Run the
   available main preparation tests too if shared helpers/contracts change. Report actual
   commands and gaps; existing suite totals are not proof of the corrected invariants.
4. Update current-state SPEC/PROGRESS/CHANGELOG and test traceability in the same repair
   commits. Keep new behavior explicitly offline/default off. Maintain bounded redacted
   errors and reports, exact timestamp/revision semantics and unknown cost where required.
5. Push focused draft PRs and update #111/#112 with head/range, reproduced/fixed cases,
   actual results and included dependencies. Return remaining design decisions concretely
   to the orchestrator while continuing any other independent in-scope correction.
6. Finish with a Traditional Chinese handoff: PR URLs/heads, baseline and repaired repros,
   commands/results, stack boundaries, independent-review needs and remaining live gates.

## Exclusions and human gates

Use fabricated profiles (including an explicitly synthetic approved status where the API
requires it), questions, JDs, pools, labels, prices and provider responses. Read no real
résumé/profile/config/database or gitignored evaluation corpus to run these regressions.
No provider SDK/CLI inference, subscription evaluation, paid workload, schema migration,
Prisma production change, existing MCP/inventory wiring, runtime defaults, Telegram,
Scheduled activation, merge, deployment or #95 ledger is authorized.

The operator later supplies/approves real candidate facts and preferences, labels/cohort,
YOE/questions/selection policy, provider/model/effort, pricing/budget, recall/miss/false-
exclusion tolerances, #94 unattended evidence and #112 decision/activation scope. Those
human decisions must not block the fabricated repairs above.
