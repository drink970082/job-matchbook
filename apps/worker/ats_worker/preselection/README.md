# preselection - offline, provider-free tooling

Synthetic review-batch, assessment-view, rehearsal, candidate-profile, frozen-replay and
shadow-evaluation modules, kept as offline evaluation tooling (ranking is not a product
goal). Nothing on the
production path imports this package: no `run.py`, MCP, scheduler, database, config,
resume or provider wiring. Every fixture is synthetic, so nothing here is a quality or
cost claim. CLIs: the `*_cli.py` modules here and `apps/worker/tools/preselection_*.py`.

## Modules

- **`preselection/review_batch.py` / `preselection/review_batch_cli.py` - offline fixed-batch preparation.** Consume
  only an explicitly marked synthetic pool, injected cutoff/resume window and complete
  caller policy. The pure engine filters confirmed applications/manual terminal actions
  and confirmed source closure, routes unknown/stale evidence to unresolved work, groups
  exact and explicitly corroborated identities before exclusions, and freezes a
  ranked/audit/unresolved batch. Confirmed application/manual evidence follows the
  identity group; mixed source closure is unresolved with per-source evidence. Requisition
  application matching requires the source scope, while an unscoped requisition match is
  visibly ambiguous. Stable posting occurrences are unique before audit sampling. Batch
  and cursor identity includes the injected clock, complete candidate/application inputs,
  merged-member versions and final order. Revalidation preserves cumulative invalidation
  and replacement history, meters analysis/scans/search against cumulative work caps, and
  suppresses any slot that cannot be checked within work/time limits. Its named
  age-service/role-coverage/audit recipe is synthetic, not the operator's production
  policy. The CLI requires an explicit fixture and local state path; it opens no database,
  profile, config, provider or runtime. Read/delivery and downstream resource cost remain
  unknown without acknowledgements.

- **Offline synthetic assessment projection** (`preselection/view.py`,
  `preselection/view_cli.py`). Given an explicitly supplied, schema-1 synthetic snapshot,
  project a bounded view with separate assessment and latest-attempt states. Compare
  source revision/content identity, context, rubric/policy/question/prompt/schema, input
  variant and provider/model identity; stale or incomplete evidence is never a
  qualification result. Only typed component scores, safe version/model labels and
  resolved JD-source excerpts leave the projection. Timestamp digits are ASCII-only;
  malformed latest-attempt metadata is unknown independently of a valid saved result.
  Bounded text remains valid across a trimmed whitespace boundary, and the isolated panel
  visibly labels every displayed shortened value. The explicit fixture CLI has no
  config/profile/database defaults and is not wired into `run.py`, inventory or MCP.

- **Offline synthetic preselection rehearsal** (`preselection/rehearsal.py`,
  `preselection/rehearsal_cli.py`). An explicit scenario, assessment fixture, candidate
  pool fixture and output path drive the real assessment projection and review-batch
  modules through a fixture-backed read adapter. The report records page and per-job JD
  completeness/error evidence, characters, injected elapsed time, source/application
  evidence, bounded revalidation, age/overload alerts, repeated-day occurrence identity
  and a stable-ID fallback from the current validated candidate set. Stale and unknown
  candidates retain their current source/content and invalidation evidence; closed and
  confirmed-application exclusions stay visible, and incomplete revalidation yields no
  fallback recommendations. Batch candidates are validated before cross-fixture identity
  lookups. Missing, empty and partial JD reads remain distinct and fail the completeness
  case. Monitoring keys are allowlisted, and missing optional thresholds remain unknown.
  Provider and missing-private-input faults are labeled simulations;
  provider cost, human reading and delivery stay unknown. This path has no provider,
  profile, resume, config, database, network, MCP, scheduler or production wiring.

- **Candidate profile and frozen replay - offline tooling only.**
  `ats_worker/preselection/profile.py` validates the closed schema-1 profile, stable
  block IDs, version/date/status and one-paragraph text, then renders all background and
  preference blocks in declared order. An injected tokenizer measures the complete
  context against a soft budget; overflow is reported without truncation. The profile
  CLI reads only an explicit input and reports hashes/counts without profile text; a
  rendered-file mismatch exits nonzero, and rendered output cannot alias the profile
  input. The replay CLI validates a closed snapshot
  containing the profile, exact rendered context, normalized payload for every row, and
  manifest. Source and external IDs are non-empty trimmed text; company, title, URL and
  description must contain non-whitespace text; location and posted-at may be null.
  It recomputes versions, hashes, counts and UTC-day membership from inputs;
  a digest alone is not proof. This establishes consistency of the supplied pool, not
  whether the producer omitted eligible postings. No independent source roster is
  available, so every frozen replay is `INCONCLUSIVE`, even if a partial pool has a
  recomputed manifest. Splits keep complete days, duplicate/template groups and repeated
  `(source, external_id)` identities together; K is allocated to each complete day in
  each split. Unresolved labels remain in the counts and make recall inconclusive.
  Reports contain aggregate metrics and hashes only, with no row/group IDs or source or
  profile text; the split seed is represented by a domain-separated SHA-256 fingerprint,
  while the caller retains the raw seed for reproduction. The daily role-coverage
  baseline uses the same deterministic greedy score and recency/item-ID tie order as the
  full ordering, and its daily orders are reused across requested budgets. The legacy
  ID-only pool also remains inconclusive. This tooling has no
  provider, database, runtime-selection, quality-threshold or acceptance-GO wiring.
  Malformed or excessively nested JSON, oversized integer tokens and timestamps outside
  UTC's representable range return bounded validation errors. Connected-group assignment
  handles large valid inputs without recursion-depth failures; a pool with too few
  independent groups returns a bounded validation error.
- **Preselection shadow assessment and offline evaluation - isolated tooling only.**
  `preselection/extraction.py` validates JD-quoted requirement spans and required versus
  preferred experience facts; its YOE policy returns `exclude`, `not_excluded` or
  `unresolved` with evidence and an explicit policy version. `questions.py` validates the
  versioned question set and exact typed assessment answers. `shadow.py` is default-off
  and accepts an injected transport, model identity, limits, clock and private journal;
  there is no provider adapter or `run.py` wiring. Its bounded worker accounts for
  attempts, retries, elapsed time, usage and actual/estimated/unknown charges. Journal
  schema 4 persists `RunBinding` over the frozen run declaration, profile, question set,
  pool fingerprint and split manifest. Resume rejects changed bound inputs before a
  transport call. Bound assessments require the matching validated `EvaluationInput` cohort;
  job membership, declared variant and per-item draw are checked before journal writes,
  cache reuse or extraction/assessment transport. Standalone extraction with a bound
  journal requires the same cohort and membership check. Execution recomputes frozen
  pool, split and run-declaration hashes, rejecting mutated or replaced cohort contents.
  Actual assessor/extractor models and limits/retry fingerprints must match the frozen
  declaration before persistence, cache reuse or transport. Unbound single-job synthetic calls remain
  available. Instruction-injection fixtures verify JD text cannot alter the system prompt,
  candidate context or typed response contract; they do not establish live model resistance.
  `evaluation.py` validates explicit pseudonymous manifests and their
  matching journal. Report generation reparses the retained canonical manifest, rejects
  changed labels, baselines, outcomes or provenance, and uses the validated snapshot and
  a copied journal throughout calculation. It checks outcomes against successful responses and emits aggregate
  metrics without row IDs, answer values, evidence text or the raw split seed. Its report
  uses a domain-separated seed fingerprint; oversized/deep JSON and UTC-normalization
  overflow return bounded validation errors. The checked-in assessment and evaluation
  fixtures are synthetic. No live provider calls, real cost/quality claims,
  acceptance GO, production wiring, database writes or runtime selection are included.

## Contracts

**Provider-free review-batch replay.** The offline `preselection/review_batch.py` path accepts only
an explicit synthetic schema-1 pool. Its policy requires K and allocations whose sum is
K, a deterministic tie rule, seed, role/age/retry/overload parameters, and candidate,
replacement, work and time caps. New arrivals use an explicit UTC half-open
resume/cutoff interval; deferred and due-retry rows are separate inputs, and historical
backfill requires an explicit flag. Occurrences use pool + stable posting identity +
source revision, independently of content/assessment versions, and duplicate stable
occurrences collapse before selection. Candidate identity groups are formed before
filtering so a confirmed application/manual terminal action is retained across exact or
corroborated duplicates; conflicting closed/open source observations remain unresolved
with each member's source/version evidence. Confirmed unlinked applications match by
posting identity or by source-scoped requisition identity; a matching requisition without
source scope is unresolved rather than a global exclusion. Title/company similarity only
raises a review flag. The synthetic recipe combines caller priority order, oldest-first
age service, greedy coverage of supplied role IDs, a seeded uniform sample over a frozen
low-rank frame, and explicit unused-slot redistribution. A batch freezes order and all
input state, including the injected clock, application and duplicate evidence, merged
member versions and final order; cursors bind its batch, snapshot and page scope.
Revalidation marks changed content/source, group, or application evidence, rejects a
changed policy identity, and preserves cumulative invalidation/replacement history and
caps across persisted replay. Work units include candidate/evidence validation,
application/dedup/similarity scans, slot checks and replacement scans/sorts. The supplied
elapsed-time observation accumulates across replay and is checked before each pass starts;
the CLI supplies an incremental duration for the current pass, not a cumulative timestamp.
This fixture-only input is not a measurement of production wall time. If that time
allowance is exceeded or cumulative work is exhausted, the batch is visibly incomplete,
its current candidate projection is empty, and selected slots are unverified rather than
recommended from old evidence. Reported reading, delivery and downstream resource cost
remain unknown.
The fixture CLI writes state only to an explicitly named local JSON path; this contract
does not add production policy, database, MCP, scheduler or worker-runtime wiring.

**Offline synthetic assessment-view projection.** A version-1 snapshot must be marked
synthetic and carry complete expected and captured identities. Matching identities yield
`current`; any identity change, including a late result for older content, yields `stale`;
absent success yields `not_assessed`; malformed, missing, oversized, or unsupported input
yields `unknown` without component values. A later provider error is reported separately
and never replaces a saved success. Invalid or unknown evidence never becomes a zero
score, qualification badge, or private-context display; only allowlisted JD references
are included. Malformed latest-attempt metadata becomes unknown without hiding a valid
saved result. Python and TypeScript share ASCII-digit offset timestamps and accept a
shortened label that drops a trailing boundary space; the panel visibly marks each
displayed shortened value. This contract runs through the explicit local fixture path
only.

## Synthetic rehearsal

The local rehearsal composes the committed assessment-view projection and review-batch
engine. It uses a fixture-backed adapter with explicit scenario, assessment and candidate
pool inputs, then writes a private-safe report to a caller-supplied output path.

Run it from `apps/worker`:

```sh
python -m ats_worker.preselection.rehearsal_cli \
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

Not exercised: Scheduled/unattended execution, live provider quality, timeouts, circuit
breaking and cost (fault cases are simulations), real reading and delivery
acknowledgements, and any production selection policy, schema, MCP integration, worker
runtime hook or rollback.

## Invariant -> test traceability

| Invariant | Test(s) |
|-----------|---------|
| The synthetic rehearsal validates batch rows before associated evidence lookups, composes actual assessment and batch modules, allowlists monitoring output, reports per-selected-JD completeness/errors, scopes requisition evidence, and derives fallback only from complete current revalidation while retaining stale/unknown evidence and current exclusions | `apps/worker/tests/test_preselection_rehearsal.py` (`test_explicit_cli_composes_real_assessment_and_batch_modules`, `test_missing_monitoring_limit_is_reported_unknown_without_a_default`, `test_unknown_monitoring_value_is_not_echoed_by_the_cli`, `test_malformed_pool_candidate_fails_through_bounded_cli_validation`, `test_selected_job_description_completeness_is_per_candidate_and_visible`, `test_unscoped_requisition_evidence_stays_ambiguous_across_sources`, `test_fallback_fails_closed_when_current_revalidation_is_incomplete`) |
| Provider-free review-batch and rehearsal imports do not load legacy scoring/profile modules or read legacy prompts, resumes or personal profile files | `apps/worker/tests/test_review_batch.py::test_fresh_import_does_not_load_runtime_db_network_or_scorer_modules`, `apps/worker/tests/test_preselection_rehearsal.py::test_consumer_import_does_not_need_runtime_or_private_data_modules` |
| Profile/replay imports and direct fake-provider shadow assessment run with legacy score/fit/profile/prompt/config/runtime imports and text/YAML/`.env` file reads blocked | `apps/worker/tests/test_preselection_import_boundary.py` (`test_profile_replay_and_cli_import_without_legacy_modules_or_text_reads`, `test_shadow_assessment_runs_with_legacy_imports_and_resources_blocked`) |
| Candidate profile rejects duplicate IDs, invalid schema/text and Unicode line or paragraph separators; context measurement never truncates; deeply nested input returns a bounded error | `apps/worker/tests/test_preselection_profile.py` (`test_profile_rejects_invalid_or_unallowlisted_values`, `test_profile_rejects_duplicate_ids_across_both_sections_and_duplicate_json_members`, `test_context_budget_is_measurement_only_and_never_truncates`, `test_profile_cli_bounds_deeply_nested_json_errors`) |
| Frozen replay validates supplied profile/context/source payloads and manifest, preserves daily/split/group membership and unresolved rows, reports only aggregate evidence, rejects blank required source text, and stays inconclusive without an independent source roster | `apps/worker/tests/test_preselection_profile.py::test_rendered_context_cli_mismatch_is_a_failure_and_errors_are_redacted`, `apps/worker/tests/test_preselection_replay.py` (`test_k_is_allocated_once_per_complete_utc_day_inside_each_split`, `test_full_snapshot_cli_validates_complete_daily_pools_and_emits_aggregate_provenance`, `test_snapshot_cli_marks_recomputed_partial_pool_inconclusive`, `test_full_snapshot_allows_nullable_normalized_source_fields`, `test_full_snapshot_keeps_repeated_source_identity_in_one_split`, `test_full_snapshot_requires_non_empty_source_identity_fields`, `test_full_snapshot_requires_nonblank_source_text_fields`, `test_full_snapshot_requires_posted_at_even_if_the_manifest_is_recomputed`, `test_snapshot_rejects_actual_input_or_manifest_tampering`, `test_snapshot_rejects_profile_change_even_when_context_is_rerendered`, `test_unknown_labels_remain_in_pool_and_make_recall_inconclusive_without_denominator_shrink`, `test_snapshot_cli_never_emits_untrusted_role_labels`, `test_snapshot_cli_reports_malformed_unicode_as_a_bounded_input_error`, `test_snapshot_cli_bounds_deeply_nested_json_errors`, `test_replay_cli_emits_only_report_and_no_source_identifiers`) |
| Profile CLI refuses to overwrite its input through a same path, symlink or hard link; JSON integer conversion limits produce bounded profile and replay CLI errors; seed output is a domain-separated SHA-256 fingerprint; role-coverage greedy order preserves reference ties, runs once per day across budgets, and handles a large day | `apps/worker/tests/test_preselection_profile.py` (`test_profile_cli_refuses_rendered_output_aliasing_profile_input`, `test_profile_cli_bounds_oversized_json_integer_errors`), `apps/worker/tests/test_preselection_replay.py` (`test_replay_report_fingerprints_seed_without_echoing_raw_seed`, `test_role_coverage_order_matches_reference_greedy_ties_and_prefixes`, `test_baseline_orders_are_built_once_per_day_across_budgets`, `test_role_coverage_order_scales_to_large_single_day_without_reordering_ties`, `test_snapshot_cli_bounds_oversized_json_integer_errors`) |
| Out-of-range timestamp normalization fails as a bounded frozen-input validation error | `apps/worker/tests/test_preselection_replay.py::test_replay_cli_bounds_timestamp_utc_normalization_overflow` |
| Deeply nested JSON returns bounded CLI errors; large connected day/group inputs do not cause recursion tracebacks, and a one-component pool is rejected with a bounded validation error | `apps/worker/tests/test_preselection_profile.py::test_profile_cli_bounds_deeply_nested_json_errors`, `apps/worker/tests/test_preselection_replay.py` (`test_snapshot_cli_bounds_deeply_nested_json_errors`, `test_replay_cli_bounds_large_connected_component_without_recursion`) |
| Shadow requirements and YOE policy use validated JD spans; direct/extracted fake-provider runs account for attempts and reject changed bound inputs and outside-cohort jobs before transport; evaluation validates outcomes against schema-4 journal provenance, fingerprints split seeds and reports aggregates only; malformed JSON and UTC overflow return bounded errors | `apps/worker/tests/test_preselection_extraction.py` (`test_synthetic_required_yoe_boundary_truth_table_uses_supported_jd_facts`, `test_yoe_policy_keeps_unknown_alternatives_unresolved_and_never_calls_them_passes`), `apps/worker/tests/test_preselection_shadow.py` (`test_instruction_injection_stays_in_jd_and_cannot_change_typed_contract`, `test_direct_assessment_payload_contains_exact_profile_one_full_job_and_questions`, `test_extractor_gets_only_full_jd_and_extracted_assessment_omits_original_jd`, `test_retry_is_counted_and_resume_reuses_success_without_duplicate_call`), `apps/worker/tests/test_preselection_evaluation.py` (`test_report_rejects_changed_validated_content_with_retained_provenance`, `test_report_uses_verified_snapshot_when_original_inputs_change_mid_report`, `test_synthetic_report_counts_recall_failures_fields_and_draw_stability_without_ids`, `test_cli_bounds_oversized_and_deep_json_errors`, `test_evaluation_and_journal_timestamps_bound_utc_normalization_overflow`, `test_run_binding_is_immutable_and_journal_schema_four_round_trips_it`, `test_run_binding_rejects_invalid_identity_and_late_journal_binding`), `apps/worker/tests/test_preselection_shadow_evaluation_integration.py` (`test_real_shadow_rejects_profile_or_questions_that_differ_from_bound_run_before_transport`, `test_bound_journal_rejects_changed_inputs_when_binding_argument_is_omitted`, `test_bound_journal_can_reuse_success_on_resume_without_binding_argument`, `test_frozen_cohort_rejects_outside_job_before_any_side_effect`, `test_bound_run_rejects_missing_or_incompatible_cohort`, `test_standalone_bound_extraction_cannot_bypass_cohort`, `test_execution_rechecks_frozen_content_models_and_budgets_before_side_effects`) |
| Synthetic review batches use explicit K/policy and UTC intervals, keep stable posting identity separate from unique daily occurrence, group duplicates before terminal filtering while retaining member evidence, scope requisition application identity, freeze clock/inputs/final order and cursor identity, preserve unchanged source-state conflicts as active unresolved evidence, and cumulatively preserve invalidation/replacement history; work/time exhaustion visibly suppresses unchecked recommendations | `apps/worker/tests/test_review_batch.py` (`test_occurrence_identity_uses_pool_posting_and_source_revision_only`, `test_new_arrivals_use_half_open_resume_cutoff_and_historic_scope_is_explicit`, `test_exact_and_corroborated_duplicates_collapse_but_similarity_only_flags`, `test_confirmed_exclusion_survives_exact_and_corroborated_duplicate_grouping`, `test_requisition_application_evidence_is_scoped_or_visible_as_ambiguous`, `test_stable_posting_occurrences_are_unique_before_audit_sampling`, `test_clock_and_final_order_are_bound_to_batch_and_cursor_identity`, `test_revalidation_marks_changed_versions_and_replaces_within_caps_without_reordering`, `test_real_cli_revalidation_preserves_an_unchanged_duplicate_state_conflict`, `test_revalidation_work_cap_limits_full_analysis_and_hides_unverified_slots`, `test_revalidation_work_cap_counts_candidate_search_and_sorting`, `test_revalidation_time_cap_short_circuits_before_candidate_validation`, `test_real_cli_persisted_revalidation_keeps_history_and_cumulative_caps`, `test_committed_fixture_runs_real_projection_and_keeps_text_out_of_the_view`) |
| Synthetic assessment projection compares the complete opaque identity, keeps freshness separate from latest attempt, preserves saved results after malformed or failed attempts, bounds/redacts the view, matches ASCII timestamp and boundary-truncation behavior across Python/TypeScript, and labels shortened text in the panel | `worker/tests/test_preselection_view.py::test_fixture_cli_keeps_saved_success_when_latest_attempt_state_is_unhashable`, `web/src/lib/__tests__/assessment-view.test.ts`, `web/src/components/__tests__/AssessmentPanel.test.tsx` |
