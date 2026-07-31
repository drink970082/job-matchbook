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

1. **RE-MEASURE TERRA. Operator's explicit instruction, 2026-07-31 — do not skip it and do
   not treat the old result as settled.** Terra's rejection (SCORING §8.7: agreement 76% vs
   86%, flip-rate 38% vs 29%) was recorded against a 23-row human golden set and an older
   model revision; §8.7's own rule is that a re-pick needs a full `make eval-score` run,
   and that is what this is. Run all three so the baseline is fresh rather than quoted:

   ```
   SCORE_BACKEND=codex CODEX_SCORE_MODEL=gpt-5.6-terra make eval-score
   SCORE_BACKEND=codex CODEX_SCORE_MODEL=gpt-5.6-luna  make eval-score
   SCORE_BACKEND=codex CODEX_SCORE_MODEL=gpt-5.6-sol   make eval-score
   ```

   Terra is the operator's preferred candidate (half sol's credit rate, twice luna's
   capability). **Report terra on its own merits** — the gate is whether it reproduces
   Sol's *verdicts*, specifically rows where it says do-not-notify while Sol says
   `seniority=match AND domain=match`. Score drift is noise; a missed alert is not.
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

## Zero-cost title filter — measured 2026-07-31, and there is a free win sitting in the queue

Against the live 5,729-row `new` queue and the current config (26 `title_filter` terms,
9 `title_exclude`):

| | rows | share |
|---|---|---|
| would be EXCLUDED by `title_exclude` | **1,298** | **23%** |
| kept by `title_filter` | 4,431 | 77% |
| matching NEITHER list | 0 | 0% |

**Every one of the 1,298 is matched by a single term: `senior`.** The other eight exclude
terms (`intern`, `co-op`, `sales`, `principal`, `staff`, `director`, `vice president`,
`head of`) never fire on the queue — not because they are useless but because they are
doing their job at INGEST, so nothing carrying them ever lands. `senior` is the exception
because it was added AFTER those rows were ingested.

**So the highest-value zero-cost action is not a new term — it is sweeping the queue with
the terms already configured.** ~23% of everything waiting is already excludable for free.
#58 re-applies title filters before paying to score, but it only reaches the rows a pass
examines, so the backlog keeps them.

**And a corollary worth stating:** 0 rows match neither list, so the queue offers no
evidence for adding new terms. Any further intake cut has to come from `max_age_days`,
the watchlist, or per-board location rules — not from more title terms. Do not tune
`title_filter` blind; there is nothing in the data asking for it.

## The `companies:` block in config.yaml is STALE — the watchlist moved to the DB

`db.py:88` states it outright: "The watchlist is DB-owned (table `watched_companies`), so
the web UI manages it." The DB holds **172** rows; `config.yaml` holds **39**, used only
as an idempotent seed via `seed_watchlist`. Nothing in `run.py` fetches from
`cfg.companies`.

So the operator's recollection is right, and the practical consequences are:

- **Editing `companies:` in `config.yaml` does not change what gets fetched.** Anyone
  dropping the 18 zero-yield boards must do it in the DB (or the web UI), not the config.
- The 39 in config are a stale subset of the 172 and will mislead the next reader.
- **Decision for the operator:** either prune `companies:` to a documented minimal seed
  (or empty) so it stops reading as the source of truth, or delete it and point
  `seed_watchlist` at a fixture. Not done here — it touches operator data.
