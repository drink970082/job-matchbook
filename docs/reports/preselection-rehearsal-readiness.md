# Synthetic preselection rehearsal

The local rehearsal composes the committed assessment-view projection and review-batch
engine. It uses a fixture-backed adapter with explicit scenario, assessment and candidate
pool inputs, then writes a private-safe report to a caller-supplied output path.

Run it from `apps/worker`:

```sh
python -m ats_worker.preselection_rehearsal_cli \
  --scenario tests/fixtures/preselection_rehearsal_scenario.json \
  --assessment-fixture tests/fixtures/preselection_assessment_contract.json \
  --pool-fixture tests/fixtures/review_batch_contract.json \
  --output /tmp/preselection-rehearsal.json
```

The committed scenario exercises two review pages, multi-chunk synthetic descriptions,
current/stale/unknown assessment views, a saved success with a later provider error, a
late stale result, exact and probable application evidence, an empty source probe, a
separate unavailable-source error, an overdue retry, an aged deferred candidate, bounded
replacement with one unfilled slot, repeated-day occurrence identity, and a stable-ID
unranked fallback. Provider outage and unavailable private input are injected fixture
states; neither causes a provider call or a private-file access. Missing monitoring limits
are recorded as unknown, not filled by defaults.

The report counts fixture tool calls, JD chunks and characters, pages, injected elapsed
seconds, candidate ages, overload, replacements, versions and bounded error categories.
The synthetic provider call count is zero; actual provider price, human reads and delivery
acknowledgements remain unknown. The local fallback preserves assessment, batch and
application evidence in the report, but does not exercise any production rollback path.

## Gates that remain open

- ChatGPT Scheduled access and unattended execution are not exercised.
- Live provider/model quality, timeout behavior, circuit breaking and cost are not
  exercised; the fault cases are simulations only.
- Real reading and delivery acknowledgements are not recorded.
- No #112 evaluation GO, production selection policy, rollout, schema, MCP integration,
  worker runtime hook or rollback is exercised.
- Parent issue #115 remains open for operator acceptance and real delivery evidence.
