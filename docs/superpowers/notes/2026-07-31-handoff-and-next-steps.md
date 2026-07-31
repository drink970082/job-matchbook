# Handoff — 2026-07-31 unattended run

Written at the end of the session, for whoever picks this up next. Plan:
[`../plans/2026-07-31-quota-levers-caching-and-vetoes.md`](../plans/2026-07-31-quota-levers-caching-and-vetoes.md).
Spend: [`2026-07-31-quota-ledger.md`](./2026-07-31-quota-ledger.md).

## Where the run got to

**Quota: 8 calls spent directly, plus a 249-call luna screen eval that was still running
when the session ended.** Operator raised the cap 60 -> 300 mid-run, then said "don't
worry about the quota". `main` was never touched by experimental code; the daemon ran all
day with no tracebacks and no breaker trips.

| | outcome |
|---|---|
| Seniority veto defects | **shipped** (PR #62) — P 0.964 -> 0.975, R 0.757 -> 0.793, verified over three eval runs |
| `capture_usage` 403 | **shipped** (PR #63) — cause named, retried, upstream-corroborated |
| Prefix caching | **dead, measured** — see the ledger; not a code problem |
| Harness trim (`--ignore-user-config`) | **not done** — worth 1.7%, not 30% as first claimed |
| Luna/terra as the FIT scorer | **not started** — this is the remaining lever with real headroom |
| Luna as the SCREEN model | eval in flight at session end; read `eval/last_screen_run.md` |
| 13 stale "message-bound" doc sites | **not done** |

## The expanded score corpus — built, and NOT yet trusted

`apps/worker/eval/golden_expanded.jsonl`, 162 rows, regenerate with
`apps/worker/tools/expand_golden.py` (read-only on the DB). It is **gitignored**, like the
rest of `eval/`, so it exists only on this host.

It is deliberately a **separate file** from `eval/golden.jsonl`. Those 23 rows carry
HUMAN-curated labels with hand-written notes; these carry **Sol's own verdicts**. Merging
them would silently downgrade the authoritative gate to machine labels — the same trap
`seniority_eval.py` names in its own docstring.

**Self-review — four problems the operator should weigh before this is used as a gate:**

1. **It cannot ever say Sol is wrong.** Labels are Sol's verdicts, so the corpus measures
   *agreement with Sol*, not correctness. For "does terra/luna reproduce Sol's decisions"
   that is exactly the right question. For "is Sol the right model at all" it is circular
   and must not be used.
2. **`adjacent` is oversampled 3x** — 55% of the corpus against 18% of the scored
   population. That is intentional (borderline rows are where a cheaper model fails) but it
   means the headline agreement number will NOT reflect production. **Read it per band, or
   re-weight.** A single blended percentage from this corpus is misleading.
3. **Zero overlap with the 23 human rows**, so there is no calibration point between the
   two label sources — nothing checks whether Sol's labels agree with the humans' anywhere.
   Fix by deliberately including the 23 as a subset and reporting them separately.
4. **The `hard` flag is missing.** 10 of the 23 human rows carry `hard: true`; none of the
   162 do. Check whether `score_eval.py` treats `hard` rows differently before relying on
   this corpus, or the gate may be weaker than the old one despite being 7x larger.

**Cost, which is the other reason not to run it blind:** 162 rows x K=3 = **486 calls per
model**, so a three-way sol/terra/luna A/B is **~1,458 calls**. Recommend K=1 as a
screen-out across all three, then K=3 on the finalist only — K=3 exists to measure
run-to-run flip, which only matters for the model you intend to ship.

## What to do next, in priority order

The operator's standing priority is **score quota first**.

1. **The fit-model A/B (sol vs terra vs luna).** The one lever with real headroom left.
   Terra was rejected before on real JDs (SCORING §8.7: agreement 76% vs 86%, flip-rate 38%
   vs 29%) — the operator has asked to revisit it, and §8.7's own rule is that a re-pick
   needs a full `make eval-score` run, which is what this is.
   `SCORE_BACKEND=codex CODEX_SCORE_MODEL=gpt-5.6-terra make eval-score`.
   **The gate that decides it:** rows where the candidate says do-not-notify but Sol says
   `seniority=match AND domain=match`. A missed alert is the failure this system cannot
   absorb; a few points of score drift is not.
2. **Finish the luna screen eval and read it against the NO-LOCAL-LLM use case**, not
   against quota saving. Those are different goals and the run answers the first.
   A paid screen inverts the economics: today the screen is free and discards ~18% of rows
   *before* the paid scorer, so on a paid screen every queued row costs something. The
   no-local-LLM default probably needs tighter intake, not the same watchlist.
3. **The 13 stale "message-bound" sites.** `run.py:69`, `pipeline.py:811`,
   `backends_codex.py:49`, `SCORING.md` 982/983/990/1278/1500, `SPEC.md` 983/2186, and two
   dated design specs. **CHANGELOG and the dated specs are history — annotate, do not
   rewrite.** The quota premise was wrong; the accuracy objection to a cheaper model
   survives on its own evidence.
4. **Operator decisions, none taken:** the seniority title-token floor (biggest in-sample
   recall win, owns the only out-of-sample false demotion — `BACKLOG.md`), the age-TTL
   sweep, and the 18 zero-yield watchlist boards. `config.yaml` was never touched.

## Traps this run walked into, so the next one does not

- **The reviews caught more in my work than my work caught in the repo.** Three claims were
  asserted without arithmetic that would have refuted them ("34 of 61 misses" — the real
  recovery is 9, reconcilable from the reported recall alone).
- **`--build-corpus` destroys the frozen golden set.** It writes in place, takes all rows
  rather than the new ones, and `eval/` is gitignored. A backup now sits at
  `eval/seniority_golden.jsonl.frozen-446-backup`.
- **The test suite was making live HTTPS calls with the operator's real credentials** —
  invisible because a fast failure looks like a fast pass. Fixed in `conftest`; the suite
  got faster than before.
- **Measure by driving the real call, not a reimplementation.** The 403 hand-probe used a
  different client than the in-pass failure, so it may not have sampled the same thing.
  Same shape as the earlier `now=None` incident.
