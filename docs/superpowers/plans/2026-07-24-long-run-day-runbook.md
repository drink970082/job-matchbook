# Unattended Long-Run Day - Operator Runbook

**Status:** ready to run - authorized by the operator 2026-07-24. Not yet executed.

> **For agentic workers:** this is an *operations* runbook, not an implementation
> plan. Nothing here changes code. It drives the existing worker against real data,
> real quota and real money, on a day the operator is away. Read the
> [Authority boundary](#authority-boundary) before touching anything, and re-read it
> before every judgment call. Phases use checkbox (`- [ ]`) syntax; tick them in this
> file as they complete so a session that picks this up mid-run knows where it is.

**Goal:** in one unattended day, clear both of the merge blockers on
`feat/universality-and-onboarding` (PR #7) and put a bounded, provenance-stamped
slice of the ~3,985 unscored postings through the pipeline - leaving a written
report and a ready-to-label worksheet for the operator's return.

**Why now:** the standing precondition landed 2026-07-24. The dead-fit-backend and
dead-notify-channel circuit breakers mean a systemic outage now aborts its stage
spending no retry budget and leaves rows recoverable, instead of marching the
matched queue to `attempts >= 3` and destroying finished work within a morning.
Before those shipped, this run was not safe to leave alone.

**Related:** [`../../PROGRESS.md`](../../PROGRESS.md) "Do next" - this runbook is the
current top item. Blocker detail lives in the SCORE and SCREEN entries there.

---

## Run from the right branch

Run everything from **`feat/score-provenance-and-rescreen`**. It carries PR #7's 41
commits plus the scorer-provenance stamp.

This is not a preference. Score ~1,500 rows from `main` or from #7 and they persist
with no `backend`/`model`/`scorer_version`, permanently - there is no retro-fill, and
selecting them later for a re-score becomes impossible. The provenance work exists
for exactly this batch.

Missing from that branch: the workday stub gate's prose-date age-gating and the
`browser` `{field}` url templates, which landed on `main` 2026-07-24 as `8c683a0`
(PR #9). The age-gating cuts detail calls on stale boards and would make phase 1
meaningfully faster. Merging `origin/main` into the run branch first is optional and
the run works either way - but expect the same squash-divergence conflicts PR #5 and
PR #9 both hit (content-identical, resolvable; take the newer side per hunk).

**Known trap, now fixed on `main` but NOT on this branch:** `make eval-score` used to
run `apps/worker/.venv/bin/python`, and that venv lacks `bs4`, so `from ats_worker
import run` raised `ModuleNotFoundError` before the eval started. Fixed 2026-07-24 on
`main` (`76e7fda`, PR #8) to use the host `$(PY)` like every sibling target. The run
branch does not carry that fix unless `main` is merged in, so **every command below
calls `python3` explicitly** and works on either branch. Do not "fix" this mid-run.

## Artifacts

Everything lands in `db/runs/<UTC-stamp>/` - `db/` is gitignored in full, so logs
and reports persist across sessions without touching the repo. One log per phase,
`tee`d so a lost session never loses the record. `score_eval` writes its own output
under `apps/worker/eval/` (also gitignored).

---

## Phase 0 - pre-flight (~10 minutes, before the operator leaves)

- [ ] **Back up the database.** `cp db/applications.db db/applications.db.bak-<stamp>`
      (~76 MB). There is no migration history; this run mutates thousands of rows.
- [ ] `make doctor` - status line per prerequisite.
- [ ] **Confirm `codex login` is live.** Auth is fragile and a logged-out host fails
      the whole pass loudly. A dead login discovered at hour six wastes the day.
- [ ] **Read remaining quota** from `db/codex_usage.json` (the same snapshot the web
      bar reads). Everything below is sized off this number. **Measured 2026-07-24:
      4.0% used, weekly window resets 2026-07-29 15:08** - so it does NOT roll over
      during the run day, and headroom is ~1,920 messages. Re-read it anyway; that
      figure is stale by the time it matters.
- [ ] **Confirm Ollama answers** (`curl -s localhost:11434/api/tags`). A dead screen
      backend does not fail loudly - see the trap under [Monitoring](#monitoring).
- [ ] `mkdir -p db/runs/<UTC-stamp>` for this run's logs.
- [ ] **Run the free hermetic self-test:**
      `cd apps/worker && PYTHONPATH=. python3 tools/score_eval.py --selftest`.
      Catches a broken harness now, at zero cost.
- [ ] **Size the scoring budget** - see [Budget](#budget) - and write the chosen
      chunk count into this file so a later session inherits the decision.

## Phase 1 - fetch (free, ~1-3 h)

- [ ] `cd apps/worker && PYTHONPATH=. python3 -m ats_worker.run --once --fetch-only`

Unbuffered, `tee`d. The body-required guard is live, so an empty-list-endpoint board
now yields nothing instead of poisoning the DB with permanent title-only rows.
Expect a per-board `dropped N posting(s) with no description` line where that fires.

**Gate:** if phase 1 ingests nothing, STOP. Do not spend paid calls on a broken
ingest.

## Phase 2 - bounded scoring (paid - the whole constraint, ~4 h)

- [ ] Repeat until the chunk count from phase 0 is exhausted, or the reserve floor
      is hit:
      `cd apps/worker && PYTHONPATH=. python3 -m ats_worker.run --once --score-only --score-limit 250 --no-notify`

Chunks, not one large call: a crash loses at most one chunk, and quota is readable
between them. Re-read `db/codex_usage.json` after each chunk and log the delta.

**`--no-notify` is deliberate.** `--score-only` skips the ingest but still runs
`run_score` then `run_notify`, so without the flag every match/match posting fires a
Telegram alert - a burst nobody is there to read. Nothing is lost by suppressing it:
the rows stay `scored`, they are in the web Discovered tab immediately, and the first
pass run *without* the flag alerts them normally. Drop the flag if you would rather
wake up to the alerts.

Two things close themselves here if the chunks reach past the oldest ids: the
recipe-sourced scored path (no `custom`/`browser` row has ever been screened or
fit-scored) and provenance coverage on this whole slice.

## Phase 3 - fit-score gate (~138 messages, ~1.7 h) - MERGE BLOCKER

- [ ] `cd apps/worker && PYTHONPATH=. python3 tools/score_eval.py`  (run 1)
- [ ] `cd apps/worker && PYTHONPATH=. python3 tools/score_eval.py`  (run 2)

**Pass bar:** two *consecutive* PASS - 0 hard-invariant violations, >=85%
per-dimension verdict agreement (seniority, domain), <20% verdict flip rate.

One re-run discharges two pending changes at once: the 2026-07-22
`personal_profile.txt` edit, and plan Stage 4 (`66dfb65`, the appended `score.txt`
extraction block feeding `merge_fallback_screen`).

Record both runs' numbers verbatim. **On a FAIL, stop and report** - the revert is
the operator's call (see [Authority boundary](#authority-boundary)).

## Phase 4 - sponsorship diff (free on ollama, minutes) - MERGE BLOCKER

- [ ] `PYTHONPATH=apps/worker python3 tools/sponsor_diff.py --db db/applications.db`

Diffs the quote-grounded screen against the retired phrase list over already-scored
rows, so only the *disagreements* need hand-labeling. Agreements are free labels.

The hand-labeling is the operator's - three classes: *no-sponsorship / offers /
silent*. Save the disagreement list as the worksheet. Keep those labels: they are
per-requirement facts about JDs, the exact shape the (unbuilt) screen-eval fixture
needs, so labeling once feeds both.

What is unmeasured is precision, specifically the misclassification residual where
the model quotes real-but-irrelevant text. Hallucination safety already holds by
construction (`_quote_in`), so it needs no re-litigating.

## Phase 5 - report

- [ ] Assemble into `db/runs/<stamp>/REPORT.md`.

---

## Budget

Codex is **message-bound**, roughly 2,000/week - not token-bound. ~3,985 rows sit
`new`; at `batch_size=1` that is ~3,985 messages and **does not fit**. This day is a
bounded slice, not a drain.

Sizing, from the 2026-07-22 sample (50 rows -> 9 screen-discarded, 41 fit calls):

```
messages ~= rows * 0.82        # ~18% are screen-discarded, which is free
reserve   = 150                # phase 3 needs ~138; never spend into this
chunks    = (headroom - reserve) / 250 / 0.82
```

At a fresh budget that is roughly 1,500 rows scored for ~1,230 messages, leaving
~600. **The reserve is not optional**: a scoring run that eats the gate budget
leaves the merge blocked for another week.

Concurrency is quota-neutral - N parallel codex execs spend exactly the same number
of messages as N serial ones, and only change wall-clock.

## Monitoring

Each phase runs backgrounded with `tee`, so nothing depends on one session
surviving. Poll every **20-30 minutes** - the signals move on that scale, and
tighter polling buys nothing.

**A dead screen backend is quiet, but no longer dangerous** (fixed 2026-07-24, on this
branch). `screen_posting` still errs toward KEEP on a provider failure - right for one
flaky call - but the verdict now carries `provider_error`, so `run_score` leaves that
row `new` instead of fit-scoring it unscreened, and `_BREAKER_LIMIT` consecutive
provider errors with zero successes abort the screen phase. An Ollama outage therefore
costs nothing and parks nothing; the backlog simply waits.

It is still worth watching, because the *pass* silently does less than you asked:
`[screen] provider error, keeping posting unscreened` in the log, and a chunk that
scores far fewer rows than its `--score-limit`. **Response:** restart Ollama and re-run
the chunk - the rows are still `new`, so nothing is lost and nothing is double-paid.

Watch for:

- `[screen] provider error, keeping posting unscreened` - the silent failure above
- `_BackendBreaker` trip lines - a dead fit backend or notify channel, not a bad row
- non-zero exits, and stalls (log mtime not advancing for ~15+ min)
- quota consumed per chunk, against the reserve floor - a jump above ~0.82
  messages/row is the screen dying, not the scorer misbehaving
- fit failure ratios drifting upward

Environment faults worth recognizing: Ollama runs on the host GPU and a WSL2
suspend kills it; a stale WSL2 bind mount shows up as `ats-web` SQLITE_CANTOPEN
(error 14) and is fixed with `docker restart ats-web` - the native worker is
unaffected by that one.

## Authority boundary

**Standing decisions - make these without the operator:**

| Condition | Action |
|---|---|
| Breaker trips | Stop that phase, capture state, do NOT blind-retry. One restart from the next chunk only if the cause is clearly transient (a single 429, a network blip) and budget allows. |
| Quota reaches the reserve floor | Stop scoring immediately, protect the gate budget, proceed to phase 3. |
| One board or Ollama dies | Log, continue, report. A fetch failure is NEVER read as "that board's jobs closed". |
| Phase 1 ingests nothing | Stop. No paid calls on a broken ingest. |
| `[screen] provider error` appears | Restart Ollama and re-run the chunk. Since 2026-07-24 the rows are left `new`, so nothing was spent or lost - but the chunk under-delivered and must be repeated. |
| Anyone asks to switch git branches | Don't. The worker imports from the working tree, so a mid-run switch silently changes the code under the next chunk. |

**Stop and leave for the operator, with evidence - do NOT do these unattended:**

- `git revert 66dfb65` on a gate FAIL. That is a merge decision.
- Merging anything, including PR #7 on a double PASS.
- Editing the golden set - including adding the Java quant-dev row that would close
  its documented Java blind spot. That is manual curation. The gate runs against the
  set as it stands; the Java row is a separate improvement, not a gate requirement.
- `--rescreen-discarded` (the one-shot guard refuses it in daemon mode anyway).
- Any code change. If this run exposes a defect, record it in PROGRESS and stop.

## The report

`db/runs/<stamp>/REPORT.md` must state:

1. Intake counts by source, and every board that failed, with its reason.
2. Scored / discarded / notified counts, and the screen-discard rate.
3. Quota: spent this run, remaining, and the per-chunk deltas.
4. Both `score_eval` runs - agreement per dimension, flip rate, hard-invariant
   violations, PASS/FAIL - quoted verbatim, not summarized.
5. The `sponsor_diff` disagreement worksheet, ready to hand-label.
6. **What did NOT run, and why.** An honest gap beats a false pass.

## If you are picking this up mid-run

Read the ticked checkboxes above first, then the newest log under `db/runs/`. Do not
restart a completed phase - phase 2 in particular is idempotent only in the sense
that `run_score` touches `new` rows, so a re-run scores *different* rows and spends
*more* quota. Re-read the quota snapshot before resuming anything paid.
