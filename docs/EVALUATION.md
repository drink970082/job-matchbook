# Evaluation policy

Evaluation protects the capability being changed; it is not a requirement to assess the
whole database. The model-backed stages are the hard-requirements screen and the JEV
keep/skip filter. [SCORING](SCORING.md) documents the screen contracts and measured
failure modes. [DEVELOPMENT](DEVELOPMENT.md#5-verify-gate--evidence-not-assertion) owns
verification for code changes.

## Which checks apply

| Change | Required evidence |
|---|---|
| Documentation/roadmap only | Relative links, accurate current/target distinctions and privacy/diff checks; no model run |
| Fetch/MCP/UI/write API with unchanged judgment | Applicable hermetic worker/web/integration tests and runtime behavior; no model run |
| Screen model, effort, prompt or verdict policy | Representative screen facts, repeated draws, false-disqualification and recall report, explicit backend/model/effort/version |
| JEV profile, question packs, model or verdict rule | Hermetic `tests/test_jev.py` plus a fresh proxy measurement on real candidates: skip rate, real applications skipped (must stay 0), required-experience agreement against a blind review, observed cost. A policy-hash change re-queues every verdict; budget the re-drain |
| Offline preselection/ranking tooling | Exact allowlisted rendering, synthetic payloads bound to profile/context hashes, split integrity, inconclusive unknown labels and aggregate-only reports; no provider calls |
| Daily Brief workflow | Real tool traversal, full JD retrieval, application deduplication, citations/unknowns, source failure and unattended delivery verification |

Unit/integration tests, parser/identity checks, isolation, privacy, circuit breaking and
schema checks remain required where applicable. A model evaluation is not a substitute.
No eval run is implied by this policy: obtain the operator's workload/budget authorization
before spending subscription allowance or money. Hermetic checks need no provider or key.

## The JEV filter's evidence

The deployed filter (SPEC §7.1, "JEV keep/skip filter") rests on a model-proxy
measurement, not human truth: preference skips 57-69% of screened candidates per day
with 0 of 7 real applications skipped, and the required-experience question agreed with
a blind review on 50 of 52. Seven applications is a small recall sample. There is no
committed corpus and no `make` target for it; a re-measurement uses the operator's
private data. Ranking within `keep` is not activated (#135).

## Tools and their scope

| Tool / target | Use | Status |
|---|---|---|
| `make eval-screen` / `tools/screen_eval.py` | Screen fact/verdict accuracy; zero false disqualification in any draw, recall reported | Manual, provider-using; needs the private `apps/worker/eval/` corpus |
| `--selftest` on that tool | Gate/parser/rule checks without model calls | Does not certify model quality |
| `preselection_profile.py`, `preselection_replay.py`, `preselection_evaluation.py` | Allowlisted profile rendering, provider-free grouped replay and aggregate shadow reports | Offline tooling; synthetic fixtures; no quality claim |
| `backfill_descriptions.py` | Explicit JD hydration maintenance | Data-quality tool |

Tool paths are relative to `apps/worker/tools`. The eval corpora are gitignored, so a
fresh clone cannot run `eval-screen` beyond `--selftest`.

## Corpus inventory and interpretation

Private corpora are gitignored and host-local. Counts describe the recorded artifacts,
not a freshly audited copy on every host; read and validate the actual file before
proposing or spending on a run. Never repair ID-only labels by fuzzy title remapping.

- **Screen facts:** 103 real-JD excerpts with fixed candidate facts. A K=3 comparison
  has local qwen3.5:4b at 7 false disqualifications (recall 31/37) and Codex
  gpt-5.6-luna at 0 (recall 30/37, flip 3), effort unrecorded, so it does not certify the
  deployed **medium** effort. One passing run is insufficient; use repeated draws.
- **Machine-labelled frames and seniority sets:** useful for sampling, agreement and flip
  rate, not unbiased accuracy claims.

## Negative results to preserve

- Multi-posting batches change per-posting verdicts; token savings do not justify the
  shape. This is distinct from independent single-item concurrency.
- Small local models confuse preferred degrees, clearance boilerplate and refusal
  language. Preserve evidence floors and unknown states.
- A model-labelled comparison favors the labelling model; self-disagreement needs its own
  report.
- Numeric scores fluctuate at band edges; verdict agreement is not calibrated fit.

Detailed evidence stays in [SCORING](SCORING.md) and [REJECTED](REJECTED.md).
