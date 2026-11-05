# OpenRouter JEV native shadow implementation plan

**Scope:** execute the approved [native-shadow contract](../specs/2026-11-04-openrouter-jev-native-shadow.md)
on `feat/openrouter-jev-shadow`, based on `9045b2c`. Luna/max implements; orchestrator
checks the exact final diff and evidence. No live calls, secrets, private source pools,
production DB, schema/runtime/default changes, deployment or merge are included.

## Selected interfaces

- `preselection/jev.py`: native versioned question pack, canonical identity, Choice/Noul/
  Score answer validation and native validated dataclasses. Native criteria do not imply
  generic scores, invented evidence or generated explanation.
- `preselection/openrouter_jev.py`: injected synchronous HTTP, exact one-attempt
  completion, separate explicit model/rate resolution, native request envelope and
  bounded response/error handling. Infer no price from old fixture data.
- `preselection/shadow.py`: explicit native builder/validator branch and bounded JSON
  worker-wire tag; keep the generic branch and existing frozen execution protections.
- `preselection/evaluation.py`: join native normalized values against retained native
  journal replies and expose monetary-evidence provenance without leaking raw inputs.
- Tests/fixtures: synthetic native contracts, single-attempt HTTP behavior, supervised
  bound execution, journal/cache/resume and aggregate report composition. Existing
  generic suites remain unchanged unless adding native compatibility assertions.

## Order and completion evidence

1. Add failing native contract/request tests, then implement validators and injected
   transport. Verify finite ranges, exact IDs, unknowns and safe failure metadata.
2. Add failing composed native shadow/journal/report test, then implement the explicit
   native seam. Keep existing generic invocation identities/semantics stable.
3. Prove no hidden retry, conservative unknown charge/delivery, frozen input/model/
   budget enforcement and cached native revalidation. Keep raw probabilities locally.
4. Execute worker suite and coverage (85% floor), worker synthetic integration,
   schema/privacy/diff gates and a native fixture-to-report demonstration.
5. Update SPEC behavior snapshot/traceability, current PROGRESS claim and CHANGELOG
   in the code commit. Open a focused draft PR for the offline #132 adapter slice with
   exact head, commands/results and unresolved live prerequisites. Do not close #132.

`Charge.kind=actual` means the monetary amount reported for that attempt rather than a
token-rate estimate; it does not assert invoice audit. The OpenRouter source is explicitly
`openrouter.response.usage.cost`, and aggregates must label its provider-reported nature.
Keep the existing actual/estimate/unknown durable charge enum for compatibility.

## Out of scope

New deployed composition/CLI key loading, extracting JDs via JEV, automatic provider
substitution, pilot data access, live question approval, new threshold/weights, source
roster completeness, measured real request tokenization, live spend, #112 GO or rollout.
