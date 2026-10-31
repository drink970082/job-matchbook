# Evaluation policy

The scorer is retained optional assistance. Evaluation protects the capability being
changed; it is not a requirement to score the whole database or a prerequisite for the
ChatGPT-first roadmap. [SCORING](SCORING.md) documents existing contracts and measured
failure modes. [DEVELOPMENT](DEVELOPMENT.md#5-verify-gate--evidence-not-assertion) owns
verification for code changes.

## Which checks apply

| Change | Required evidence |
|---|---|
| Screen/scorer boundary prefactor with unchanged prompt/schema/model/verdict | Hermetic import/file-read isolation, screen payload/verdict parity, mode-specific operational versus fit config validation and explicit legacy compatibility; no automatic live model run |
| Offline candidate profile/replay tooling | Exact allowlisted rendering and byte comparison, complete synthetic source payloads bound to profile/context hashes and daily-membership manifest, per-day K allocation, split integrity, inconclusive unknown labels and aggregate-only reports; no provider calls |
| Documentation/roadmap only | Relative links, accurate current/target distinctions and privacy/diff checks; no model run |
| Fetch/MCP/UI with unchanged judgment | Applicable hermetic worker/web/integration tests and runtime behavior; no live fit eval merely because the repo has a scorer |
| Screen model, effort, prompt or verdict policy | Representative screen facts, repeated draws, false-disqualification and recall report, explicit backend/model/effort/version |
| Fit model, rubric, prompt or verdict policy | Supported representative human labels, repeated-draw stability, existing hard-invariant gate and comparison against current behavior |
| JEV/System One experiment | Shadow classification with explicit unknown/abstain handling, per-field errors, observed cost and no new hard filtering |
| Daily Brief workflow | Real tool traversal, full JD retrieval, application deduplication, citations/unknowns, source failure and unattended delivery verification |

Unit/integration tests, parser/identity checks, isolation, privacy, circuit breaking and
schema checks remain required where applicable. A model evaluation is not a substitute.
No eval run is implied by this policy: obtain the operator's workload/budget authorization
before spending subscription allowance or money. No provider/key is needed for hermetic
checks. A corpus-dependent selftest can still need private local data.

## Selection gate for fit experiments

The operator selects [#96](https://github.com/drink970082/job-matchbook/issues/96)
preparation, reporting that approximately 200 postings/day exceed the current workflow's
capacity. [The independent preparation plan](superpowers/plans/2026-10-27-preselection-parallel-preparation.md)
defines the available assessment view, batch replay and synthetic consumer. The
[#111/#112 repair handoff](superpowers/plans/2026-10-29-preselection-shadow-repair-handoff.md)
scopes provider-free implementation separately from acceptance. PR #129 is an unmerged
integration candidate for direct/extracted shadow assessment and aggregate synthetic
evaluation. These software checks do not measure model quality, actual price, population
recall or unattended delivery. #94 evidence, approved inputs/labels/policy, provider/model/
resource limits and predeclared acceptance values remain required for live evaluation; the
operator still owns #112 GO and activation separately. Runtime model/effort remains
unchanged.

## Retained tools and their scope

| Tool / target | Use | Status |
|---|---|---|
| `make eval-screen` / `tools/screen_eval.py` | Screen fact/verdict accuracy; zero false disqualification in any draw, recall reported | Retained manual, provider-using evaluation |
| `make eval-score` / `tools/score_eval.py` | Legacy fit contract: zero hard violations/errors, agreement >=85%, flip-rate <20%; existing prompt gate requires two passing runs | Retained manual; corpus readiness must be established before interpreting a PASS |
| `make eval-seniority` / `tools/seniority_eval.py` | Optional pre-ordering against stored strong-model labels | Agreement/stability diagnostic, not independent human truth |
| `--selftest` on those tools | Gate/parser/rule checks without model calls | Retained; does not certify model quality |
| `label_golden.py`, `label_run.py`, `build_review_sheet.py`, `expand_golden.py` | Curate or review a corpus for a specifically chosen experiment | Not an automatic backlog-drain or relabelling workflow |
| `pick_frame.py`, `extract_shadow.py` | Frozen-input extraction research | Deferred research; not wired into production scoring |
| `preselection_profile.py`, `preselection_replay.py` | Allowlisted profile rendering and provider-free grouped replay with recency/role-coverage baselines | Offline tooling only; synthetic fixtures; no runtime selection or quality claim |
| `preselection/extraction.py`, `questions.py`, `shadow.py`, `evaluation.py`; `preselection_evaluation.py` | JD-span/YOE evidence, typed questions, injected direct/extracted fake-provider runs, schema-4 bound journals and aggregate reports with split-seed fingerprinting and bounded input errors | Unmerged PR #129 candidate; synthetic/provider-free verification only; no real price, quality claim, GO or runtime wiring |
| `backfill_descriptions.py` | Explicit JD hydration maintenance | Data-quality tool, not an instruction to rescore or mutate applications |

Tool paths are relative to `apps/worker/tools`. Do not delete these scripts, their
hermetic tests or private reports just because their previous research campaign is no
longer the roadmap. Do not re-enable a rejected batching mode to save allowance.

## Corpus inventory and interpretation

Private corpora/reports are gitignored and host-local. Counts below describe the recorded
research artifacts, not a freshly audited copy on every host. Read/validate the actual
file before proposing or spending on a run. Database cleanup makes ID-only labels more
fragile, not more authoritative; never repair them by fuzzy title remapping.

- **Screen facts:** the recorded expanded set has 103 real-JD excerpts and fixed
  candidate facts. K=3 comparison reports local qwen3.5:4b at 7 false disqualifications,
  recall 31/37; Codex gpt-5.6-luna at 0, recall 30/37, flip 3. The recorded Luna effort
  is missing. This does not certify the deployed **medium** effort. Earlier 83-row Luna
  runs disagree; one passing run is insufficient. Keep facts supported by the exact
  excerpt and use repeated draws on any new change.
- **Human fit gate:** records describe a 23-row baseline and a later 93-row file with
  22 unreachable posting references. Those describe different corpus states; neither
  count proves today's input is ready. Missing payloads must fail visibly, not shrink
  the gate. Preserve supported inline posting payloads; human relabelling is needed
  before promoting an expanded authoritative gate.
- **Blind fit review:** the recorded 287-row two-backend comparison has 203 consensus
  rows and 84 review cases (59 disagreements plus 25 seeded audits); 24 review cases
  have answers, 60 remain open. Older 40-answer material is context, not accepted labels.
  Consensus is not human truth. Reviewed-answer ingestion remains unbuilt. Do not make
  finishing that campaign a prerequisite for source, MCP or UI work.
- **Shadow extraction:** a 250-row stratified frozen frame, provenance hashes and
  extraction tools exist. The code is isolated from production; remaining model-family
  comparisons, labels and cutover are deferred. Candidate-evidence annotations have no
  approved extraction home; do not route `personal_profile.txt` wholesale as job facts.
- **Machine-labelled frames/seniority sets:** useful for sampling, agreement and flip
  rate, not unbiased accuracy claims. Counts and old per-call budget estimates must not
  be projected onto the current CLI/model/effort without a new measurement.

Retain the medium-effort provenance gap as a limitation, not an instruction to rerun an
unchanged large eval. The operator values Luna's subscription economics; that choice is
compatible with honest uncertainty about model accuracy and remaining allowance.

## Negative results to preserve

- Numeric scores fluctuate at band edges; verdict agreement is not calibrated fit.
- The old multi-posting fit batches change verdicts. Their token savings do not justify
  reviving that shape. This is distinct from independent single-item concurrency.
- Small local models confuse preferred degrees, clearance boilerplate and refusal
  language. Preserve evidence floors and unknown states.
- A Sol-labelled comparison favors Sol; model self-disagreement needs a separate report.
- Old CLI prefix-cache measurements are version-specific; the controlled no-cache probe
  supplies no current optimization headroom. Do not repeat it without a changed premise.

Detailed evidence stays in [SCORING §8](SCORING.md#8-measured-history---do-not-re-run-these-experiments),
[REJECTED](REJECTED.md), and the
[quota ledger](superpowers/notes/2026-07-31-quota-ledger.md). These constrain experiments;
they do not select the next product feature.
