# P3 isolated development slice

**Status:** approved scoped pre-P2 prototype exception, not production activation.
User authorizes existing DB input development, then later validation against prospective
snapshots. Accepted contract: [P0 1308f47](https://github.com/drink970082/job-matchbook/tree/1308f47/docs/jev-ranking).
P1 collector remains independently scheduled from frozen build b1d3ca4; do not change it.

## Scope

Implement source snapshot -> injected fake native JEV -> strict identity/schema validation
-> deterministic P0 projection -> isolated persistence -> actual in-process MCP tool calls.
Use additive Prisma-owned schema definitions, never worker DDL. The production DB is
read-only input; all writes go to a temporary demo copy or synthetic fixture DB. No model
credentials, HTTP transport, scorer/run.py wiring, backfill, notification or deployment.
Existing inventory is development data, never held-out ground truth or ranking-quality
proof. Synthetic fake tiers are labeled explicitly; no legacy fit scores used as labels.

P0 owns exact four questions/projection, complete cache binding and model identity,
source fields including location, independent latest-success/latest-attempt, immutable
sequenced transitions, pinned snapshot cursor and reconciling coverage. Implement only
necessary P3 single-job mechanics; P4 durable batch retry/claim/circuit system is separate.
No generic evaluation framework or UI redesign.

## Required evidence

Hermetic tests and real in-process MCP invocation demonstrate high/medium/low/null,
wrong source/job/model/question rejection, invalid response exclusion, exact cache hit,
source/profile/policy changed binding stale state, failed refresh preserves old result,
low/unranked browsing, privacy-safe outputs and stable pagination across intervening writes.
Additive schema synchronization passes. Worker tests+coverage, MCP/integration checks and
web checks if existing web code changes. No production db-push or --once runtime pass.
Fake CLI demonstration on exported stored sources stays private and labels every result
fake-provider/prototype. Report precise remaining production and quality gates; #139
cannot close as full production acceptance on an isolated prototype alone.

## Implemented mechanics and observed demonstration

The additive Prisma-owned `job_ranking_events` table stores immutable full-state events.
Each event includes the captured source/binding and independent latest-success/attempt
state. This is a minimal physical representation of P0 logical records, not a new
production scheduler or batch-claim system. Runtime ranking modules issue no DDL. The
standalone demo lives under worker tests and provisions only a TemporaryDirectory using
the canonical Prisma-mirrored SQL fixture; it accepts no target database path.

`create_server(..., ranking_reader=...)` explicitly adds three read-only tools:
`list_job_rankings`, `get_job_ranking`, `get_job_ranking_coverage`. Default MCP retains its
ten tools. List/coverage use committed sequence watermarks; detail provides bounded source
chunks and safe provenance, omitting private profile bindings/raw provider identity and
redacting conventional URL secret keys. Freshness is against latest explicitly captured
prototype input; production changes not captured here do not auto-invalidate these events.

Actual command from `apps/worker`:

```sh
/tmp/ats-jev-p3-venv/bin/python -m tests.fake_ranking_prototype_demo   --inputs-dir /home/halcyon/root/ats/apps/worker/resume/pivot/jev-ranking-p3-dev-v1
```

Observed: source_count=20; fake_provider_invocations=20; current=20; succeeded=20;
cache_hit_verified=true; mcp_roundtrip_verified=true; production_db_writes=0;
ranking_quality_evidence=false. Five jobs per high/medium/low/unknown are deliberately
cycled fake scenarios, not predictions. The MCP client reconstructs source text internally
and reports only aggregates; no private source/profile text enters this document.

Independent static review found no unresolved correctness findings in this scope.
Unfiltered ordering follows the approved tier/publication/ID contract; domain allocation
remains an explicit consumer policy using domain filters. Schema sync passes. Verification: 1,568 worker tests pass; merged worker coverage is 85.73% against
an 85% floor. Native-contract regression tests exercise the reused parser rather than
lowering the coverage floor. `make check-schema` passes. `make test-integration` passes
four worker integration cases and 74 web integration tests across eight suites, creating
only a throwaway `/tmp` Prisma database. Diff/link/privacy checks pass. No web UI/e2e
or production `--once` check ran: no UI behavior changed and production calls/writes are
outside this exception.

## Remaining gates

No native HTTP adapter, live inference, production schema push, active-policy global
invalidation, batch claims/retries/cost reconciliation, incremental completion feed or
runtime deployment is supplied by this exception. P1/P2 real-data/quality gates and P4/P5
operational/consumer gates remain. Existing-inventory development is allowed; future
prospective snapshots remain validation inputs, not tuning replacements after inspection.
#139 stays open for acceptance beyond this isolated prototype.
