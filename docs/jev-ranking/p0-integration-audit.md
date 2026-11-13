# P0 integration and reuse audit

**Status:** audited integration facts and proposed ownership reconciliation; no runtime changes.

## Pinned sources

- Main: `9045b2cd83012bb9f427b1291e56fcc5c37849e2`.
- Research PR #134: `16deac2fd152b57d1648c81dd201f8760315b25d`, verified with `git ls-remote origin refs/pull/134/head`.
- Planning baseline: `ef18116c20b01cc7df7e7a9a8c7594b5a76f3900`.

Paths below are relative to `apps/worker/ats_worker/`. Findings distinguish existing code from decisions required before implementation. This audit used source inspection and issue reads; no provider calls, production writes, service changes or runtime tests.

## Minimal reuse boundary

| Research asset | Functions/types and dependencies | Decision |
|---|---|---|
| `preselection/jev.py` | `NativeJevQuestion`, `NativeJevQuestionSet`, `jev_question_set_from_value`, `ValidatedNativeJevAnswer`, `ValidatedNativeAssessment`, `validate_jev_response`, `native_jev_journal_payload`, `validate_native_jev_journal_payload`; stdlib only | Reuse native contract/parser; journal helpers only where needed |
| `preselection/openrouter_jev.py` | `JEVHTTP`, `JevModelMetadata`, `resolve_jev_model_metadata`, `OpenRouterJevTransport`, bounded response parsing; imports jev plus `Charge`, `ModelIdentity`, `ProviderFailure`, `ProviderReply`, `Usage` from shadow | Reuse protocol/validation after replacing the shadow dependency with narrow production-owned types |
| `preselection/profile.py` | `profile_from_value`, `load_profile_text`, `render_profile`, validated blocks and canonical identities; stdlib only | Reuse approved input/version concepts; never expose candidate text in list output |
| `preselection/preference.py` | `derive_preference`, `PreferencePolicy`, `PreferenceDecision`; stdlib plus jev | Rubric evidence only; its primary/secondary/adjacent/avoided/unresolved tiers are not the new high/medium/low projection |
| guard, skills, extraction, shadow, convergence and replay | Research paths | Preserve evidence; no mandatory production imports |

Importing `shadow.py` transitively loads extraction/profile/questions and research execution machinery. Copying the transport without removing this import violates the minimal boundary. The transport also expects an invocation variant and exact `{state, question_set}` payload. Direct state contains company, title, location, candidate_context and job_description. A thin explicit production invocation must replace this research coupling.

## Existing source, screen and scheduling integration

`source_lifecycle.assessment_input_hash` hashes canonical company/title/location/description and returns null unless company/title/description are complete. `db.upsert_postings` seeds `source_content_hash` and revision 1 for complete inputs. `db.save_source_observation` compares hashes and advances content revision/timestamps. `assessment_freshness` compares captured/current revisions; it does not cover profile, rubric, projection or model identity. Source availability and last-seen/error evidence are separate; recent ranking cannot imply availability.

Standalone screening lives in `job_screenings`. `db.get_screen_candidates` selects new postings with no screen, followed by provider-error retries; `db.save_screening` captures content revision. That queue is not JEV inventory selection. New results must not overwrite `score_detail`, pipeline status, application state or standalone screen state.

`run.py:run_once` wires fetch/feed/source refresh/screen/legacy scoring. `pass_lock` prevents overlapping worker passes. `_run_scheduler` installs wall-clock APScheduler CronTrigger hours; `main` exposes explicit once/run-now execution. Main has no JEV runtime wiring. Batch attempt claims still need their own durable contract: the process lock alone does not establish per-binding exactly-once settlement.

## MCP integration and cursor gap

`mcp/server.py:create_server` wraps `ReadOnlyATSRepository`. Existing tools cover overview, job list/detail/description chunks, applications/history/notes and generic record reads. Extend those surfaces rather than add a parallel read platform.

`mcp/read_repository.py:list_jobs` fixes only an insertion ID ceiling. Its output explicitly reports `snapshot=False`, current-state traversal and live keyset ordering. Mutable assessment filters and this cursor do not satisfy stable ranking snapshots. Ranking requires an immutable query snapshot or equivalent version/commit watermark. Existing assessment-window guidance recommends overlap/dedup/reconciliation and explicitly cannot recover arbitrary backdated writes; a new completion feed must address late commits.

`get_job_description` supplies bounded full-text chunks; list/detail disclose text length and the access tool. Existing overview reports screen/triage counts, not JEV coverage. New coverage categories must reconcile without conflating freshness and attempt state.

## Intake coverage limits

- `fetch/__init__.py:prefilter_postings` applies positive title substrings, exclusion word boundaries and maximum posting age. Unknown dates remain eligible.
- `pipeline.run_fetch` supplies a stub gate that can skip full hydration for deterministic intern/location disqualification. Those discarded stubs can lack full JD.
- Ordinary watchlist rows without required external ID/title/description are dropped; an empty-description unresolved record is recorded when a URL exists.
- `feed/prefilter.py:prefilter` keeps active listings in selected categories and excludes explicit no-sponsorship/citizenship labels; unknown sponsorship remains eligible. Feed ingestion then applies title/age rules, URL resolution, detail acquisition and deduplication.

Ranking cannot recover postings excluded before storage. This audit does not authorize broadening fetch scope.

## Overlapping issue ownership

The actual bodies of [#113](https://github.com/drink970082/job-matchbook/issues/113), [#114](https://github.com/drink970082/job-matchbook/issues/114) and [#115](https://github.com/drink970082/job-matchbook/issues/115) were fetched with `gh issue view --json title,body`.

| Existing issue | Actual remaining scope | Proposed JEV ownership and residual |
|---|---|---|
| #113 | Persistence/history and read surfaces, inventory UI, extraction provenance, compare-and-publish, profile freshness; legacy #109/#112 gates. Offline #117 is accepted, not full integration. | P3 owns approved minimal JEV persistence/MCP only. Keep legacy UI/extraction and other unmet criteria open; no claim that P3 satisfies all #113 criteria |
| #114 | Production daily selection, mandatory YOE exclusion, UI, aging/revalidation, acknowledgments and bounded replacement; #109/#113 dependencies. Offline #118 is accepted. | P4 owns rank batch attempts/recovery, P5 bounded consumption. Mandatory YOE/UI/aging/acknowledgment policies are not silently inherited. Keep remaining legacy scope separate |
| #115 | Actual Scheduled access and delivery under #94, original JD reading, production monitoring/rollback and old #112/#113/#114 gates. Synthetic #119 is accepted. | P5/P6 cover only selected JEV acceptance/rollout. Interactive success cannot close #115 or #94; Scheduled rollout requires separate selection and evidence |

Before shared modules are assigned, record acceptance of this ownership split; no two work packages should own the same persistence/query/batch edit concurrently. Legacy #131/#132/#112 remain separate evidence and must not be closed as experimentally passed. Their mandatory extraction/guard/human-gold requirements do not automatically govern the minimal track.

## Local size bound

At the pinned research revision, `OpenRouterJevTransport.__init__` defaults `max_request_bytes` to 20,000. `complete` measures complete canonical UTF-8 JSON before POST and raises `jev_request_too_large` with `delivery='not_sent'`. This is local protection, not provider capacity evidence. Choosing a replacement still requires offline full-request size distribution and current official provider-limit evidence. Bytes are not tokens.
