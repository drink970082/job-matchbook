# Native disagreement guard implementation checkpoint

The pure isolated `preselection/preference_guard.py` implements the operator's selected
review/keep behavior. Matching present/absent avoidance labels preserve the base compound
projection, including its unresolved state. Other pairs become unresolved/review. Only
opposite determinate labels are material; unknown uncertainty and numerical-only probability/
confidence changes do not trigger tuning, retries or unnecessary user intervention.

Caller-declared versioned atomic policy pins seven Choice IDs and the exact question hash.
The guard verifies succeeded direct records, each explicit RunBinding, canonical native
response/question hashes, model and shared work/source/draw. Invalid/failed/unbound evidence
fails visibly instead of being imputed unknown. Its own guard version/policy hash includes
the compound policy and full ordered atomic contract. The original compound policy remains
in base_decision. Both raw wrappers and run/question/source/response provenance are retained.
There is no runtime `shadow` import, file/env/network access, score, DB write or runtime wiring.

## Actual verification

Test-first missing-module RED is retained; the final focused synthetic suite has26passes,
including the tri-state table, source/run/profile/question/model/draw failures, complete-vector
aggregation, numerical-only drift, raw preservation, guard identity and blocked-resource
execution. Actual full gate tails:

```text
make test-worker
1756 passed, 1 skipped in 39.71s
python3 -m pytest --cov --cov-report=term-missing
Required test coverage of 85.0% reached. Total coverage: 85.24%
1756 passed, 1 skipped in 53.43s
make check-schema
schema.sql is in sync with apps/web/prisma/schema.prisma
make check-privacy
no private files tracked (450 files checked)
```

Diff check passes. Logs are private under `/tmp/ats-jev-openrouter-review/` as
`preference-guard-{red,focused,worker,worker-coverage}.log`. The definition and SPEC
traceability/current behavior, PROGRESS and CHANGELOG accompany the source commit.

## Remaining work and actual stop

Luna, the required implementer, reports an actual usage limit after these source gates.
This triggers the operator's session-limit stop; no replacement model/owner is used.
Original seven-source live responses have NOT yet been replayed through this new module,
and no new inference is run. No actual-data guard outcome or quality GO is claimed here.
Web/E2E/production behavior and independent human quality remain unverified: this is isolated
tooling with no web/runtime surface. No deployment or merge is selected.

The [bounded fresh-source protocol](../superpowers/specs/2026-11-12-jev-guard-validation20.md)
is prepared at canonical `jev-guard-validation20-v1.preflight/`. It retains4exact controls+
20fresh source rows across five title strata, one company per new slice,7prior-company flags,
full source/metadata/grouping/exclusion/read manifests and explicit uncollected new labels.
Twenty-two full-description reads include two exact-prior-JD skips before outputs; same-
metadata-signature skips are qualified separately. New20IDs, source identities and exact JD
hashes exclude210retained prior sources. All sources fit existing compound/atomic request
bounds in preflight (17967/15473bytes). This is not live availability, complete-day coverage,
independent gold or company/template independence.

Seven predecessor ledger hashes/accounting are verified. Cumulative1196attempts/USD0.496861792
is unchanged, with no pending/unknown/overreserve. The new epoch's96calls/USD0.50remain
unstarted: no final wire/controller/metadata freeze or reservation. Funding remains the
existing cumulativeUSD10authorization. Resume after required capacity returns, first with
original-response offline replay and accepted-code bindings, then private harness/freeze/
zero-key dry-run before bounded calls. Never reset history or retry old failed calls.
