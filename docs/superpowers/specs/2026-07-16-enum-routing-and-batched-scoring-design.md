# Enum-verdict routing + batched fit scoring — design

**Status:** shipped 2026-07-16 (v1.0.0) — Part A (verdict routing +
`insufficient_context`) only; the batched-scoring half failed its acceptance guard
and is parked at `batch_size=1` (SPEC §13). · **Date:** 2026-07-16 ·
**Backend context:** the codex
(ChatGPT-subscription) fit scorer shipped 2026-07-15/16 (see CHANGELOG). This spec
addresses the two problems that surfaced when it met the golden set.

## Why

Two independent findings from the codex cutover, both now driving one coherent change:

1. **The notify gate flips run-to-run, and it's a rubric artifact, not a backend
   defect.** The fit `score` quantizes to the rubric's band edge (~72–74) and the
   `>=75` notify threshold sits exactly on that edge, so repeat draws straddle it
   (gate flip-rate 29–38% across two configs, both FAIL). The **enum verdicts**
   (`seniority`, `domain`) were **100% stable across every draw**; only the number
   moved. The score is a lossy re-encoding of a judgment that is already stable. →
   **Route on the verdicts, not the number.**

2. **Subscription quota is message-bound, and the queue can't fit.** Plus meters a
   rolling 5-hour *message* window (~15–90 on `gpt-5.6-sol`). A ~640-row re-score is
   640 messages → spans 7+ windows. Each call also re-pays a ~13–14k-token fixed
   prefix (Codex scaffolding + rubric + profile + résumés) for one ~900-token job,
   with **zero** prompt-cache credit. → **Batch multiple JDs per call**: 10/batch
   turns 640 messages into 64 and cuts tokens ~6×.

These meet at one instrument: a repurposed **verdict-accuracy** eval harness that
validates both the routing predicate and that batching doesn't corrupt per-JD scores.

## Decisions already made (via brainstorming)

- **Route on enum verdicts**, score kept for display/ranking only — not gating.
- **Tight predicate:** notify iff `seniority.verdict == "match" AND domain.verdict
  == "match"`. Precision over recall — accepts silently missing adjacent-domain
  strong fits (e.g. id=6), which the harness must NOT penalize (see Part C).
- **Batching folded into this spec**, gated behind the harness (batched verdicts
  must match single-scored ground truth before it ships).

## Part A — `match/match` routing

One definition of "matched", used by both the worker (what pings) and the web UI
(what shows as matched), so the two never disagree.

**Predicate** (over `score_detail.assessment`):
```
seniority.verdict == "match"  AND  domain.verdict == "match"  AND  NOT insufficient_context
```
`insufficient_context` stays excluded from auto-notify — thin JDs keep routing to
human review (unchanged behavior, already a separate signal).

**Worker** (`ats_worker/pipeline.py` `run_notify` + `ats_worker/db.py`):
- Replace the `db.get_by_status(conn, "scored", min_score=threshold)` selection with a
  new `db.get_notifiable(conn)` that selects `pipeline_status='scored'` rows where the
  SQLite `json_extract(score_detail, '$.assessment.seniority.verdict') = 'match'` AND
  the domain extract `= 'match'` AND the `insufficient_context` extract is not 1.
- `run_notify` drops its `threshold` parameter. `cfg.threshold` is no longer read for
  gating (see "Retire the threshold").

**Web** (`apps/web/src/lib/actions.ts`):
- Add `matchedIds()` — a raw `$queryRaw` returning ids whose `score_detail` verdicts
  are match/match (mirroring the existing `lowContextIds` / `disqualifyCauseIds`
  json_extract helpers, since Prisma's typed `where` can't reach into the JSON).
- `matched` bucket → `id IN matchedIds()`; `belowbar` → active + scored + `id NOT IN
  matchedIds()` + not low-context. Both stop keying off `MATCH_SCORE_THRESHOLD`.

**Retire the threshold from gating.** `cfg.threshold` (worker) and
`MATCH_SCORE_THRESHOLD` (web) no longer gate anything. Grep confirms `MATCH_SCORE_THRESHOLD`
is used only in `actions.ts` bucket filters — remove those uses. If any score-coloring
in the UI still wants a reference line, keep the constant for display only with a
comment; otherwise delete it. `config.yaml`'s `threshold:` key becomes inert — leave it
parsed-but-unused with a deprecation comment (removing a config key is a separate,
schema-touching change; YAGNI here).

## Part B — batched codex fit scoring

Batch the **fit** call only (the codex cost). The SCREEN (Ollama, per-posting, free)
is unchanged and still gates: only screen-survivors reach a fit batch.

**Restructure `run_score`** from a per-posting loop into three phases:
1. Screen every `new` posting (Ollama, per-posting — unchanged), collecting the
   non-disqualified ones and persisting disqualifications immediately as today.
2. Chunk the survivors into batches of `batch_size` (default 10).
3. One fit call per batch → N scorecards → persist each.

**Scorer interface.** `make_codex_scorer` gains a batched entry point returning one
scorecard per input posting, keyed so results can't be silently misaligned:
- Prompt: the shared system sections (rubric + profile + résumés) once, then N JD
  blocks, each prefixed with an explicit `job_ref` (the posting id).
- Schema (`--output-schema`): `{"results": [ {job_ref:int, ...<_SCORE_SCHEMA>...} ]}`,
  every input `job_ref` required back. `_score_schema` is reused per element so
  batched and single output are structurally identical (harness comparability).
- **Alignment guard:** map results by `job_ref`; if any input id is missing or an
  extra/unknown id appears, raise `ScoreError` for the batch.

**Failure handling — the safety net.** A batch that raises `ScoreError` (parse failure,
missing `job_ref`, timeout) does **not** fail 10 postings. It falls back to scoring
that batch's postings **singly** (the existing 1-JD path). One malformed batch costs
latency, not correctness. A single-scoring failure marks just that one posting failed,
as today.

**Sizing.** `max_tokens` must fit N verbose scorecards; default `batch_size=10` with a
generous output cap, both `--batch-size` / `CODEX_BATCH_SIZE`-overridable. `batch_size=1`
is exactly today's path (no special-casing).

**Scope:** batching is codex-specific. The `claude` backend keeps single-scoring — its
cached prefix already makes the marginal posting nearly free, so batching buys it little
and single-scoring keeps the A/B simple.

## Part C — eval harness → verdict-accuracy gate

The harness stops bucketing `score`→keep/near/skip (the thing we no longer route on)
and instead regression-tests the **verdicts we now depend on**.

**Golden relabel** (`apps/worker/eval/golden.jsonl`): each row gains ground-truth
`seniority` ∈ {match, too_junior, too_senior} and `domain` ∈ {match, adjacent,
mismatch}. Derived by one scorer pass capturing verdicts + human confirmation against
the existing `note`s (several already implied — target-domain keeps → domain match;
the min-2 skips → seniority too_junior). The `band` field is retained for reference but
no longer gates.

**Gate** (`tools/score_eval.py`):
- Score each row K×, capturing verdicts. Compute **verdict agreement** (does the
  majority verdict equal ground truth, per dimension) and **verdict flip-rate** (do
  the K draws disagree). Expectation: flip-rate ≈ 0 (verdicts were stable); agreement
  is the real signal now.
- Derive the **notify decision** (`match/match`) from the verdicts and report it
  per row, but the PASS gate is on **verdict accuracy**, not on reproducing the human
  notify intent — this is what keeps the accepted recall loss (id=6-type adjacent
  keeps) from failing the gate.
- Hard-invariant rows (the min-2 / wrong-domain skips) must never come back
  `seniority==match AND domain==match`. That's the safety floor.

**Batching validation (the fold-in gate):** the harness runs the golden set **both
single and batched** and asserts the batched verdicts match the single verdicts
per row. Batching ships only if they agree. This is the measurement that makes the
quota win safe.

## Testing

- **Worker unit:** `get_notifiable` selects match/match-and-not-thin, excludes
  match/adjacent, adjacent/match, thin JDs, and disqualified. `run_notify` pings
  exactly the notifiable set. Batched scorer: N-in/N-out alignment, `job_ref`
  mismatch → ScoreError, batch failure → single-fallback path, `batch_size=1`
  equivalence. All hermetic (subprocess mocked), as today.
- **Web unit:** `matchedIds` / bucket filters over a seeded DB — a match/match row
  scoring 60 is `matched`; a match/adjacent row scoring 90 is `belowbar`.
- **Acceptance:** `make eval-score` verdict-accuracy gate PASSes (twice consecutive,
  per the existing shipping rule) AND batched==single verdicts on the golden set.

## Risks & non-goals

- **Coarser routing** (accepted): match/adjacent strong fits won't ping. Documented,
  chosen. Revisit only if real missed pings are observed.
- **Batch context bleed** (the thing being measured): if batched verdicts drift from
  single, batching does not ship — routing (Part A) still lands independently.
- **Non-goal:** removing `config.yaml threshold:` / a Prisma schema change. Left inert.
- **Non-goal:** batching the `claude` backend or the Ollama screen.

## Rollout order

1. Part A (routing) — worker + web + threshold retirement. Independently shippable;
   fixes the flip-rate immediately.
2. Part C (harness reframe + golden relabel) — needed to gate both A and B.
3. Part B (batching) — behind the harness's batched==single check.

Each is its own green commit (SPEC/PROGRESS/CHANGELOG updated with it).
