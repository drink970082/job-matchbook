# Job Matchbook — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.
>
> **Split 2026-07-30, because every session reloads this file.** What stays here is what
> a session needs *now*: in flight, the pick order, the quota gap, and open defects. The
> rest is two files it can load on demand — [`BACKLOG.md`](./BACKLOG.md) (the open
> catalogue: unverified/deferred + enhancements) and [`REJECTED.md`](./REJECTED.md)
> (proposals evaluated and turned down; read your block's entry before proposing a
> redesign).

**Current phase:** **v1.0.0 released** (2026-07-22) — tagged on `main`, repo public
as [`drink970082/job-matchbook`](https://github.com/drink970082/job-matchbook), CI
fully green (web / worker / e2e). Feature-set complete and validated live end-to-end;
testing/CI hardened (coverage gates, integration + Playwright e2e, schema-drift and
privacy guards). **"Hardened"
means test/CI hardening, not security hardening** — accepted residuals are documented
in SPEC §11 + `SECURITY.md`; genuinely open items are below.

**Since then the work has been accuracy, then readiness to run unattended.** The screen's
three hard-requirement checks were each acting on a model verdict with no evidence behind
it; `make eval-screen` now measures that and gates the prompt, and the
false-disqualification count over 81 labeled live rows went **11 → 2-3** (the residual is a
4B ceiling and the count is not run-to-run stable — see Defects). Five PRs landed
2026-07-28: the screen stack (#24), a per-host pass lock (#20), wall-clock scheduling with
no eager startup pass (#25), a systemd user unit (#26), and an autoheal healthcheck that
can actually fail (#27). **`make eval-screen` is RED on `main`** at 2-3 degree
false-disqualifications; that is the documented ceiling, and queue item 3 is its remedy.

**The system has been running unattended since 2026-07-28 22:19 EDT** (PR #29 — feed
pre-filter, newest-first score queue, read-only lock fallback). The first three passes ran
2026-07-29 with no restarts, missed slots, tracebacks or breaker trips. **What they proved
is that the constraint is no longer correctness, it is QUOTA:** three passes spent 10% of
the weekly Codex window, which projects to ~140% at 6 passes/day. The open decisions are
therefore about spend and intake, not about whether the pipeline works — see In flight.

**Measured 2026-07-30, and it points at a free lever rather than a cheaper model:** 75% of
paid fit calls come back `domain=mismatch` and 54% come back `seniority=too_junior`, so 96%
of them buy a "no". Seniority is the half a *free* local extraction can reach, and it was
measured on 07-30 and passed — see the first In-flight entry.

**QUOTA IS THE STANDING PRIORITY as of 2026-07-31 (operator's call).** Work that is not a
quota lever waits. The gap, the three levers that move it, and the two measured dead ends
are in [Quota — the gap and the three levers](#quota--the-gap-and-the-three-levers); the
pick order is Q1-Q3 at the top of the queue. **The reframe that section turns on: the
backlog is not a debt to repay** — this system surfaces ~15 postings a week to a human, it
does not owe every row a verdict, so the problem is *which* rows get the paid call, not how
many.

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

- **Cut paid fit calls with a FREE seniority extraction — BUILT 2026-07-31, landed and
  unmerged** `[branch feat/seniority-preorder · SCORE · M]`. The layer, its eval gate
  (`make eval-seniority`), the `deprioritized_at` ordering column, the
  `candidate.years_experience` key and the in-pass wiring are all on that branch; suite
  870 green, `seniority.py` at 98%, total coverage 95.04%. **Re-measured on this build,
  446 rows: P 0.964 / R 0.757, 44% demoted, 0 provider errors, and 0 false demotions on
  either `domain=match` or notified rows** — the gate that decides the layer. The
  pre-merge review's fixes (a rank veto, and a stated years figure beating a rank word)
  cost recall 0.829 -> 0.757 and demote share 0.484 -> 0.442; both can only ever REMOVE
  a demotion, and the eval's in-sample limits are stated in SCORING §5.7.
  Behavior lives in SPEC §7.1 and SCORING §5.7; the shape decisions (the operator chose
  a real column over a backdated `updated_at` or a `score_detail` sniff) are in
  `docs/superpowers/specs/2026-07-31-seniority-preordering-design.md`.
  **Two deploy steps are NOT done and the feature is inert until they are:** `make
  db-push` to add the column to the live DB (back it up first — Prisma keeps no
  migration history), and a daemon restart between slots to pick the code up. The
  measurement that motivated it follows, unchanged.
  **The original entry:** `[SCORE · M · measured]`.
  **The finding is the verdict matrix.** Over the 396 rows scored in the 7 days to
  2026-07-30: `domain` came back **mismatch 298 (75%) / adjacent 72 (18%) / match 24
  (6%)**, and `seniority` came back **too_junior on 214 (54%)**; 175 (44%) are both.
  All 14 notified rows are `domain=match`; the other 10 match rows split 7 `too_junior`
  + 3 `insufficient_context`, exactly as the §6 predicate implies. **96% of paid calls
  buy a "no".**
  **The lever this points at is seniority, not domain.** SCORING §4.2 measures seniority
  ONLY against a bar the JD states explicitly (a years number or a senior/lead/staff/
  principal rank; no bar stated → `match`). That is the closed-vocabulary bounded
  extraction SCORING §9.1 lists as *weak-model-capable*, and the same shape change that
  fixed degree in §8.1 — model lists `stated_min_years` / `stated_rank`, **code**
  compares against the candidate's STAGE. `domain` cannot move here: it needs the profile
  and the résumé, and §9.1 puts it strong-model-only.
  **It must be a re-ordering, not a new filter.** The queue is most-recently-touched-first
  (below); sending free-layer `too_junior` rows to the BACK leaves them in `new` alongside
  the existing 9,218 — observable, searchable, reversible — so a false negative costs a
  delay, not a deleted posting. No new `pipeline_status`, no skip-reason column, no paid
  audit sample. **This framing is load-bearing:** the 396 labels are *Sol's verdicts, not
  human labels*, so the training/validation set inherits Sol's errors. Good enough for a
  prioritizer; **not** good enough for a terminal discard.
  **THE FREE STEP RAN 2026-07-30 AND IT PASSED — `qwen3.5:4b`, zero quota, zero DB
  writes.** Over 446 rows (same corpus, ~50 larger by then; **251** `too_junior` / 195
  `match`), the model emitting only `{stated_min_years, stated_rank}` and CODE applying
  `>= 2 years OR rank in {senior,lead,staff,principal}` scored **P 0.921 / R 0.924**
  (TP 232, FP 20, FN 19, TN 175), 0 provider errors, 11 blind responses all kept.
  **252 of 446 rows (56.5%) demote, so ~52% of paid fit calls are deferrable.** Ordering
  the whole 9,314-row backlog costs **4h05m of GPU and $0.00** (1.58 s/row, single worker
  — the GPU serialises, so concurrency buys nothing).
  **The number that decides it is not the P/R — it is WHICH rows the false positives are.**
  Of the 20 wrongly demoted, Sol scored 15 `domain=mismatch` and 5 `adjacent`; **zero are
  `domain=match` and zero were notified.** Every row Sol called `seniority=match` AND
  `domain=match` — the whole §6 notify payoff set — survives undemoted. A false demotion
  costs a delay on a posting the notify gate was going to drop anyway, which is the
  weakest possible failure and exactly what the prioritizer framing above requires.
  **The dominant error is §8.1 repeating verbatim, and the fix is a veto, not a prompt.**
  13 of the 20 FPs are degree-conditional ladders (*"Master's and no experience; or
  Bachelor's and 3 years"*) where the model reports one rung instead of the minimum across
  rungs; 4 are numbers lifted from a **Preferred** block, 3 are caps read as minima.
  Clamping the model's number down to the smallest years-figure the JD literally states —
  a keep-direction veto, SCORING §9.2 lever 4, deterministic, can only ever lower a bar —
  measures **FP 20 → 7, P .921 → .967, R .924 → .825**. The 7 survivors are the
  preferred-vs-required and cap cases, i.e. the §9.1 4B ceiling; do not spend a prompt
  rewrite on them.
  **Determinism is real; it is NOT confidence.** At production settings (`temperature=0,
  seed=0`) the extraction is bit-reproducible — 0 flips in 79 re-draws — so unlike the
  paid backend (SCORING §8.6) one run *is* the trend. The corollary is the trap: the 20
  FPs are **systematic and will never average out**. Under sampling perturbation
  (`seed=7, temp=0.3`) flips concentrate on exactly the disagreement rows and 4 of 6
  re-drawn FPs flip to Sol's answer, so these are low-confidence boundary cases. **Do not
  quote the 0/79 as robustness.**
  **Two rows where SOL drifted from its own rubric and the free layer was right:** ids
  65540 and 58344, Amazon SDE2 postings Sol called `too_junior` reasoning from
  "autonomous contributor" — SCORING §4.2 says verbatim that implied ownership or autonomy
  is NOT seniority, and `SDE2` is not one of the four ranks. Corroborates the standing
  warning that these are Sol's labels, not truth.
  **Invention was not the failure mode.** `stated_rank` was fabricated **0 times in 62**;
  `stated_min_years` 3 times in 272 (1.1%), only 1 of which created a bar, and Sol agreed
  on all 12 invention-driven demotions. The model also correctly declined *"work closely
  with more senior developers"* and *"seek guidance from senior engineers"* as rank bars.
  Mis-selection from a stated ladder is the problem, not hallucination.
  **Free money left on the table:** 6 of the 19 FNs are the model returning an empty
  object on postings whose TITLE reads "Senior …" / "Sr …". A title-token floor would
  collect them, but that is a *discard*-direction floor, so SCORING §9.3 applies and it
  needs its own measurement.
  **One shape decision left for the build.** Folding the clause into the existing screen
  prompt makes it cost literally zero extra calls, but that prompt's degree/authorization/
  clearance extractions are gated by `make eval-screen` — treat it as a separate change
  with its own eval run, and do NOT assume these numbers survive the merge.
  **Measured this session** (`db/applications.db`, `db/scorer_usage.json`): backlog 9,218
  `new` (9,131 with `description` ≥ 200), oldest 2026-07-22; 7-day flow 5,326 new /
  451 discarded / 382 scored / 14 notified, **380 paid fit calls**; quota snapshot
  `used_percent 32`, weekly window, resets 2026-08-05; all 434 scored rows are
  `gpt-5.6-sol`.
  **Unreconciled, and do not average the two:** 383 of those 451 discards are the
  deterministic **location** gazetteer (India 207, Mexico 47, China 43, Taiwan 33, …), not
  the model screen. So the 54% "discard rate" over rows that left `new` and the ~18%
  per-pass model-screen rate in the entry below are different denominators. Steady-state
  demand is somewhere in **~2,800–4,900 fit calls/week** until they are reconciled.
  **Also unverified, and the gap estimate rests on it:** how much of that 32% is the
  pipeline versus evals and interactive use. 380 calls → 32% puts the weekly ceiling at
  ~1,190 only if *all* of it were scoring; the real figure is higher. Until that is
  split, the shortfall is 1.4×–2.4× and no tighter.
  **`used_percent` is an integer** and `limits[]` carries no credits/units field
  (`score/usage.py:144` passes the provider value through unmodified), so a single call
  moves it ~0.05% — **the two-call token-bound-vs-message-bound experiment is not
  runnable.** Whether the quota is token- or message-bound remains open.
  **Ruled out this session, with reasons, so they are not re-proposed:** swapping the fit
  model to a cheaper tier (at the low end of the capacity range a 2× model still does not
  reach steady state, let alone the ~4,200-call backlog — and SCORING §8.7 requires a full
  real-JD eval anyway); a compressed "candidate card" replacing the résumés (unproven
  quota premise, and SCORING §8.4 makes candidate evidence the most destabilising input to
  `domain`); a cheap-model → strong-model cascade (SCORING §9.3's second-vote hazard); a
  stronger local screen (only 1 confirmation route in the 7 days, and it cannot touch
  `domain`); and shadow-running the existing prefilters for the reduction — `fetch.
  prefilter_postings` is title keep/exclude + `posted_at` age and `feed/prefilter.py` is
  active/category/sponsorship metadata, so **those 396 rows are already their output**.
  **Was blocked on this path — UNBLOCKED 2026-07-30.** `score_eval.py` pinned the model
  to `run.DEFAULT_CODEX_SCORE_MODEL` and ignored `CODEX_SCORE_MODEL` (which `run.py` does
  read), so no model A/B was runnable; it now reads `CODEX_SCORE_MODEL` /
  `ANTHROPIC_SCORE_MODEL` the same way (CHANGELOG). Needed only if step 1 fails.
  One unrelated defect surfaced and is NOT part of this work: `config.yaml`'s
  four-value `work_authorization` cannot express F-1 OPT (authorised now, sponsorship
  later — `authorized-no-sponsorship` skips the check entirely, `needs visa sponsorship`
  discards jobs workable today). (The second — SCORING §2.4/§6 omitting the `notified`
  status the DB actually uses — was corrected 2026-07-30.)

- **Scoring the `new` backlog at scale — deferred, and now PARKED BY CONSTRUCTION**
  `[SCORE · S · quota-bound]`. Per-row cost is **~0.8 paid messages**, measured over the
  first three live passes (the free screen discards ~18%, not the ~60% an earlier
  estimate assumed — that estimate is retired). The 3,959-row backlog is therefore on the
  order of **~3,200 messages**, more than a full weekly budget.
  **The queue as of 2026-07-29, and the shape is the point:** 5,660 `new` = **3,959 from
  2026-07-22/23** (the original backlog) + **1,701 from 07-29**. All 148 rows the three
  live passes scored were ingested that same day; **not one backlog row was touched**.
  That is newest-first working as designed, but the consequence is now measured rather
  than predicted: today's pool alone takes ~13 days to clear at ~22 rows/pass, and the
  2026-07-22/23 rows only begin after that. Treat the backlog as parked until a
  deliberate operator run, not as something the schedule will eventually reach.
  Run it with `--score-only --score-limit N` from `apps/worker`
  (`PYTHONPATH=. python3 -m ats_worker.run --once ...`); the
  [runbook](./superpowers/plans/2026-07-24-long-run-day-runbook.md) phases 1-2 carry the
  quota math and monitoring cadence.
  **Selector for the pre-2026-07-24 backlog:** rows scored before scorer provenance
  landed carry no `backend`/`model`/`scorer_version` stamp, so "unstamped" picks them
  out (SPEC §9).
  **CHANGED 2026-07-28 — read this before quoting an old `--score-limit` recipe.** The
  `new` queue is now read **most-recently-touched, then newest id**
  (`COALESCE(updated_at,'') DESC, id DESC` — PR #29; SPEC §7.1
  + CHANGELOG), because the old `score DESC, id ASC` was oldest-first for this queue
  (every `new` row has score NULL) and a scheduled bounded pass would have spent ~2 weeks
  on this backlog before reaching a job discovered today. Consequences for anyone
  draining it by hand: a bounded pass now takes the **newest** rows, so `--score-limit N`
  no longer walks the backlog at all — it scores current intake. To work the backlog
  deliberately, use `--score-only` (which skips ingest, so nothing newer arrives first)
  and accept that it now drains from the **top** of the id range. The old
  "one board at a time" sampling caveat still applies, mirrored.

- **Run the pipeline as a daemon — RUNNING UNATTENDED since 2026-07-28 22:19 EDT
  (PR #29). First three passes measured 2026-07-29; the mechanism works, the BUDGET
  does not.**
  `systemctl --user ats-worker` is `enabled` + `active (running)`, linger is on, and the
  daemon reports `passes at 0,4,8,12,16,20:00 America/New_York (every 4h, wall-clock)`.
  Zero restarts, no missed slots, no tracebacks, no circuit-breaker trips, no lock
  contention. 7 jobs notified on day one.

  | pass (EDT) | ingested | scored | paid fit calls | duration |
  |---|---|---|---|---|
  | 00:00 | 703 | 60 | 49 | 55 min |
  | 04:00 | 86 | 60 | 52 | 55 min |
  | 08:00 | 84 | 60 | 47 | 60 min |

  **QUOTA IS THE BINDING CONSTRAINT — CAP SET TO `40` ON 2026-07-30** `[SCORE · XS ·
  operator's call, MADE]`. Over the window's first **7 passes** (23% by 04:50 on 07-30,
  window resets 2026-08-05) that is **~3.3%/pass at `--score-limit 60`**, so `60`
  projected to **~138%/week** — the quota would have died around day 6 of 7. `40`
  projects to **~92%**, which is under budget but NOT roomy: it covers fresh intake only,
  so nothing drains, and the choice made is *keeping up*. Queue item 6 carries the rest.
  **Do not read `db/scorer_usage.json` without checking its mtime** — see the
  `capture_usage` defect below; a 07-30 reading of "23%" was in fact 8 hours old, and the
  live figure at 12:41 was **32%**.
  **Lowering the CADENCE does not help, and this is the counter-intuitive part.** Half
  the passes ingest twice as much each, so paid calls/week are unchanged — quota is a
  function of newly discovered postings, not of pass count (already stated below, now
  observed). The only levers that reduce spend are a lower `--score-limit` (parks more
  work) and tighter `title_filter`/`max_age_days`/watchlist (less intake).
  **The earlier ~0.4-paid-messages-per-row estimate was wrong: it is ~0.8.** It assumed
  the free screen discards ~60%; live it discards **~18%** (11/8/13 of 60). Any future
  quota arithmetic should use the measured rate, not the estimate. **The first In-flight
  entry measures a different 54% over a different denominator — 383 of those discards are
  the deterministic location gazetteer, not the model screen — and the two are NOT
  reconciled.** Do not average them.
  **Four things had to land first, and three of them were not the schedule.** (0)
  `apscheduler` was missing from the system python3, so the daemon would have
  crash-looped. (1) The feed pre-filter, or 59% of feed intake would have been re-fetched
  and re-screened six times a day. (2) The newest-first score queue, or a bounded pass
  would have spent ~2 weeks on the backlog before reaching a job found today. (3) The
  read-only lock fallback, since an unattended daemon is exactly where a silently wedged
  pass hides. Cadence choice below supersedes the 2026-07-23 choice of 4/day, which was
  decided but never written into the config — the file sat at `24` for five days while
  this entry claimed `6`. One thing is still not expressible.
  **The schedule is a clock as of 2026-07-28** (`feat/wall-clock-schedule`; SPEC §7.1/§9/§12
  + CHANGELOG). It used to be an interval — `add_job(once, "interval", hours=…)` plus an
  eager `once()` before `start()` — so passes fired at *launch time + N* and every restart
  both re-phased the day and cost a full pass. Now `CronTrigger(hour=cron_hours(h),
  minute=0)` puts them on 0/4/8/12/16/20, the eager pass is gone (`--run-now` restores it),
  and `schedule_hours` is bounded to divisors of 24. The config-shape question resolved to
  **no new key**: the slots are derived from the existing int, so `_reject_unknown_keys`
  never had to change.
  **What does NOT get more expensive: the paid scorer.** `upsert_postings` is
  `ON CONFLICT DO NOTHING` and `run_score` only touches `new` rows, so quota is a function
  of *newly discovered postings*, not of pass count. What multiplies is fetch: 6x the
  board HTTP, workday detail calls, Simplify re-reads, `feed_unresolved` re-attempts and
  Chromium renders per day (`run_expire`'s 50/pass becoming 300/day is the one welcome
  multiple). That reprices two open items below — the missing 429 backoff
  (`phenom/qualcomm` already 429s at **one** pass/day) and pruning permanently-dead
  `feed_unresolved` URLs now retried 6x daily. Both were dormant while the config sat at
  24h and the feed was off; both are live as of 2026-07-28.
  **Overlap — CLOSED 2026-07-28** (branch `feat/pass-lockfile`, PR #20; SPEC §7.1/§9 +
  CHANGELOG). APScheduler's `max_instances=1` never let the scheduler overlap itself; the
  real exposure was a hand-run pass landing inside a scheduled one, and `run.pass_lock`
  (a non-blocking `flock`, stale-safe by construction) now refuses the second one
  outright. The claim/lease shapes stay rejected (see
  [`REJECTED.md`](./REJECTED.md)).
  **Residuals (a) and (b) — BOTH FIXED 2026-07-30** by keying the lock on the resolved
  `--db` (`<db>.pass.lock`, beside the DB; SPEC §7.1/§9 + CHANGELOG). (a) two checkouts on
  two DBs no longer block each other; (b) the expensive direction — a daemon whose temp
  dir differs from an operator's shell (cron's sanitized env, `PrivateTmp=yes`, an
  exported `TMPDIR`) acquired a *second* lock and double-spent paid quota on the same
  rows — is closed by construction, since both sides now name the DB. The unit's
  `Environment=TMPDIR=/tmp` pin and its "do not set PrivateTmp" warning are gone with it.
  `resolve()` is the load-bearing detail (`apps/web/prisma/applications.db` is a symlink
  to `db/applications.db`). Caught in passing: the suite reached `main()` on the DEFAULT
  `--db` and left a lock file in the live `db/`; the autouse fixture now redirects
  `DB_PATH` too.
  **(c) An unwritable lock file used to wedge the daemon SILENTLY — FIXED 2026-07-28**
  (PR #29; CHANGELOG). `pass_lock` opened `O_RDWR`, so one
  accidental `sudo python -m ats_worker.run` left a root-owned lock file — never
  unlinked, by design — and every later pass got `EACCES`. The eager pass used to kill
  the daemon at startup, loudly; once that pass was dropped the `RuntimeError` was raised
  *inside* the APScheduler job, where the executor catches and logs it, so the daemon
  stayed up, reported a healthy schedule and never completed a pass. It now falls back to
  `O_RDONLY` — `flock` needs no write access — which keeps the guard exclusive and costs
  only the pid diagnostic, announced on both the holding and the contending side.
  **Residuals (a) and (b) are FIXED above** (2026-07-30, the db-keyed lock); (c) is the
  2026-07-28 `O_RDONLY` fallback and stands.

- **General-purpose pivot — Stage 3 deferred.** Stage 2 shipped (CHANGELOG). **Stage 3,
  non-tech discovery feeds:** the watchlist already covers any company, so decide the need
  before building (brittle, anti-bot handling, dilutes the moat).
  **Standing design rule:** generality lives in `personal_profile.txt`, *not* in the
  fit-scoring prompt — every `score.txt` change is gated behind `score_eval` (SPEC §7.1,
  SCORING §8.4).

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Two axes:**
*severity* sets the bucket (a shipped defect that loses prepared work ≠ an unbuilt
nice-to-have), and within each bucket items run **easiest → hardest** with an effort tag —
**XS** (~an hour) · **S** (~an afternoon) · **M** (~a day + a design call) · **L**
(multi-day / new dependency / architectural). Blocked items name their blocker.

**Third axis — which part of the system.** Every entry's tag opens with a block name
(`[FETCH · XS]`, `[SCREEN · S]`), so the bucket ordering stays severity-first while a
single `grep -r '\[FETCH' docs/PROGRESS.md docs/BACKLOG.md` gives that block's whole
queue. Eight blocks, matching the pipeline walkthrough — the counts below span this file
*and* [`BACKLOG.md`](./BACKLOG.md), where all but the defects now live:

| Tag | Covers | Open now |
|---|---|---|
| `FETCH` | `fetch/` adapters, recipe executors, `feed/`, `run_fetch`/`run_feed`/`run_expire`, watchlist | 15 — the long tail lives here; no defects. 2026-07-30 closed two by measurement (the workday feed collapse is dead reqs; the workday prose-date age gate is a structural no-op) and opened one that matters more — 50 bodyless Microsoft postings, the largest `empty_description` source, surfaced by the #46 reason split |
| `SCREEN` | `score/screen.py`, `score/location.py`, `screen.txt`, the screen backends | 4 — **1 residual** (a 4B ceiling, not a coding defect, and since 2026-07-29 it costs a paid fit call rather than a deleted job) plus two of the three the #24 pre-merge review opened: what the eval can actually reach, and the snippet window degenerating on bullet JDs. The blind-backend floor fix closed 2026-07-29. `make eval-screen` gates the prompt |
| `SCORE` | `run_score`, fit backends, `score.txt`, scorecard schema, quota | 5 — **1 defect** (`capture_usage` stopped writing the quota snapshot, silently, 2026-07-30) and **quota is the binding constraint**: the cap is `40` as of 2026-07-30 because `60` projected to ~138% of the weekly budget (In flight), and 655 queued rows fail today's filters |
| `NOTIFY` | `notify.py`, `get_notifiable`, `run_notify`, Telegram | 0 — no defects |
| `ORCH` | `pipeline.py` shape, `db.py` transitions, retry budgets, threading, scheduler | 2 — no defects; pass overlap closed 2026-07-28 by the lockfile, leaving scheduler/cadence and the un-hydrated stub discards |
| `WEB` | `apps/web` — Prisma schema, server actions, UI | 2 |
| `INFRA` | Docker, healthcheck/autoheal, CI, migrations, deployment | 4 |
| `DOCS` | `docs/`, README, `AGENTS.md`/`CLAUDE.md`, `.claude/skills/` (+ the `.agents/skills` link), evals | 4 |

The five *evaluated-and-rejected* records in
[`REJECTED.md`](./REJECTED.md) are named by block
rather than tagged (`Fetch capability registry…`, `Notification outbox…`, `Score shape
changes…`, `Screen shape changes…`, `Orchestration-layer shapes…`) — read the one for
your block before proposing a redesign of it.

**Open defects: two.** One is a model ceiling rather than a coding error — 3 rows where
the 4B reads a soft degree bar as hard. The other is new on 2026-07-30 and is a real
coding defect: `capture_usage` silently stopped writing the quota snapshot, which is the
instrument the spend decisions are made on. Everything else found in the 2026-07-23 →
07-28 sweep has shipped a fix (thirteen in total, counting the 2026-07-29 `.env.<suffix>`
privacy-guard gap; see [Defects](#defects--shipped-behavior-that-is-wrong-should-fix)).

**Fixing a check does not un-discard the rows it already killed — RESOLVED 2026-07-30.**
The recovery ran: 73 paid calls recovered 52 scored rows, 4 of them matches. Queue item 2
has the numbers and the two ways the estimate was low.

### Do next — the pick order

The buckets below are a *catalogue* sorted by severity. This is the **queue**: what to
take first and why. Each numbered item is independently pickable.

> **THE QUEUE IS EMPTY — items 1-6 are all DONE** (6 and 2 on 2026-07-30; 3 on 07-29;
> 1, 4, 5 on 07-28). **QUOTA IS THE STANDING PRIORITY — operator's call, 2026-07-31.**
> Anything in the catalogue below that is not a quota lever waits. The order is fixed and
> the reasoning is in [Quota: the gap and the three levers](#quota--the-gap-and-the-three-levers)
> immediately after this queue; read it before picking, because two of the obvious moves
> (a cheaper fit model, a slower cadence) are measured dead ends.
>
> **Q1. Fix the instrument — `capture_usage`, `[SCORE · XS]`. VISIBILITY HALF DONE
> 2026-07-30; the root cause is what is left.** The quota snapshot stopped being written
> and nothing said so; it has already made one `--score-limit` decision come out ~17
> points optimistic. Every number in the quota analysis rests on this file, so it went
> first even though the other two levers are worth more. Shipped: a WARNING on a `False`
> return and an `as_of` stamp in the snapshot. **Still open: why the fetch fails inside a
> pass but succeeds standalone** — now waits on the next failing pass to announce itself
> rather than on someone thinking to check an mtime. Entry under
> [Defects](#defects--shipped-behavior-that-is-wrong-should-fix).
>
> **Q2. Build the free seniority pre-ordering — `[SCORE · M]`.** Measured 2026-07-30 and it
> passed (In flight, first entry). It adds no capacity; it makes the capacity you have land
> on rows worth spending it on, which is worth roughly 2x. Ship it as a re-ordering with the
> keep-direction veto included, as a standalone call first.
>
> **Q3. Cut intake — `[FETCH · S]`.** The only lever that reduces *demand* rather than
> re-ordering it: `title_filter`, `max_age_days`, and dropping low-yield boards. The feed is
> the firehose (3,212 rows in one day on 07-29 against ~730 on a normal one). The zero-yield
> watchlist rows — `mlp` (measured at 0 postings), `globalcareers-msci`, both Citadels — are
> the trivial end of it and are one decision, recorded below.
> **Items 1, 4 and 5 were DONE 2026-07-28**: the screen stack merged as #24 and the
> autoheal redo as #27, together with the pass lockfile (#20), the wall-clock schedule
> (#25), the systemd unit (#26) and the feed pre-filter (PR #29). The
> surviving items keep their original numbers because other entries in this file cite
> them by number.
>
> 2. **DONE 2026-07-30 — the recovery ran.** 764 rows in `id <= 1417` were re-screened;
>    **691 re-discarded for free, 73 reached the paid scorer** (of which 23 arrived via
>    #42's `demote_for_confirmation` path), and **52 came back scored**. Four are
>    seniority+domain `match` and will alert on the next normal pass, `--no-notify` having
>    held them back: **Optiver 723** (the *"is supportive of US immigration sponsorship"*
>    row this item was named for), Optiver 738, Tower Research 964, WorldQuant 1074.
>    **The paid cost was 73 calls, not the ~46 predicted** — the dry run measured only the
>    213 hydrated degree/clearance/authorization discards, while the pass also requeues
>    rows discarded in that id range for *other* reasons, which is the "measured floor,
>    not a ceiling" caveat below coming true at ~1.6x. ~5% of the weekly window.
>    **The side effect landed bigger than recorded, too:** `requeue_discarded` moved
>    **4,644** hydrated discards to `new` (not the 3,092 measured on 07-28 — the pool had
>    grown), so `new` went 5,287 -> 9,218 and the 3,880 rows outside the id window now sit
>    there. The note below says "a later pass re-kills them"; **at `--score-limit 40`
>    against ~205 rows/pass of fresh intake, no scheduled pass will ever reach them** —
>    they are parked, not queued. 632 un-hydrated stubs were left alone by design.
>    A pre-run backup is at `db/applications.db.backup-20260730-1119-pre-discard-recovery`.
>    The recipe, for the record:
>    ```
>    cd apps/worker && PYTHONPATH=. python3 -m ats_worker.run --once --no-notify \
>        --rescreen-discarded --score-max-id 1417
>    ```
>    `--score-max-id` bounds the pass to `id <= N`, applied BEFORE `--score-limit`. 1417 is
>    the top of the degree/clearance/authorization discard range (ids 7-1417) and the
>    pre-existing paid backlog starts at 1419, so the bound selects the recovery targets and
>    structurally cannot reach the backlog. No `--score-limit` is wanted here: a budget would
>    re-introduce the newest-first problem inside the selection. Like `--rescreen-discarded`,
>    the flag requires `--once`, and a negative value is a parser error rather than "no bound".
>    **`--no-notify` is not optional here.** `run_notify` has no per-pass cap, so without it
>    every newly-matched recovered row fires a Telegram alert in one burst. The rows stay
>    `scored` and alert on a later normal pass.
>    **What the ~46 does and does not cover.** It is measured over the **213 hydrated**
>    degree/clearance/authorization discards, which are a subset of the **736** such
>    discards in ids 7-1417 (the rest are un-hydrated stubs `requeue_discarded` skips by
>    design). Rows in that id range discarded for *other* reasons are also requeued and
>    re-screened for free; the location half of those re-discards for free too (PR #35
>    tightened that gate one-directionally with a clean discard side), but **the survivor
>    count for the non-location, non-d/c/a remainder was never measured**. Treat ~46 as the
>    measured floor, not a ceiling.
>    Re-screening the live DB read-only against the three fixes (free, local Ollama, no
>    writes): of 213 hydrated discards whose reason names degree/clearance/authorization,
>    **46 now keep** — **~46 Codex messages, ~2.3% of a weekly budget**. 20 Microsoft
>    phantom-clearance rows, 6 degree, ~20 authorization.
>    **Two of the authorization recoveries are postings that OFFER sponsorship and were
>    being deleted** — Optiver 723 *"is supportive of US immigration sponsorship for this
>    role"* and Bridgewater 34 *"we do provide immigration sponsorship for this position"*;
>    `_OFFERS_SPONSORSHIP` never matched "do provide". One sampled recovery (IMC 529) is a
>    genuine recall loss, already a known miss in the eval report.
>    **Why the old `--score-limit 736` recipe had to be replaced — do not resurrect it.**
>    It was exact under `ORDER BY score DESC, id ASC`: the 736 degree/clearance/authorization
>    discards occupy ids **7-1417** and the pre-existing backlog starts at **1419**, so
>    the first 736 rows of the queue were the targets and nothing else. As of 2026-07-28
>    (PR #29) the queue is `COALESCE(updated_at,'') DESC, id DESC`, which inverts exactly
>    that. `requeue_discarded` stamps `updated_at`, so the good news is the pass cannot
>    wander into the paid backlog — every requeued discard sorts ahead of it. The bad news
>    is that all **3,232** of them do, tied on the same timestamp and broken by `id DESC`,
>    while the 46 targets are among the **lowest** ids in that set. `--score-limit 736`
>    would therefore score the 736 *newest* requeued discards and reach **zero** targets.
>    Reaching the oldest one needs the whole 3,232 — the cost the bound existed to avoid.
>    **This item needed a selector, not a limit — BUILT 2026-07-29** (`--score-max-id`,
>    the id-bound shape; inverting the queue for one operator flag was the alternative and
>    was rejected as a second ordering to reason about). The measurement below is
>    unaffected — it is a property of the rows, not of the ordering. What is left is the
>    run, which spends ~46 messages.
>    **The side effect to accept first:** `requeue_discarded` is unfiltered — it moves all
>    **3,092** hydrated discards out of `discarded` permanently, and the 2,356 outside the
>    window sit as `new` until a later pass re-kills them (free: 3,066 are location, a code
>    path that did not change). 186 un-hydrated stub discards are skipped by design.
> 3. **DONE 2026-07-29** — a degree/clearance-only screen fail is routed to the strong
>    model instead of discarding (`score.demote_for_confirmation`; SPEC §7.1 + §9
>    traceability, CHANGELOG). Built as an in-pass routing decision plus a
>    `needs_confirmation` marker in `score_detail`, **not** a new `pipeline_status`:
>    screen and fit run in the same pass, so no row would ever be stored in that state,
>    and adding one would mean new buckets in `constants.ts` and the UI for something
>    never observed. The residual degree defect below is now one paid fit call per row
>    rather than a deleted job.
> 5. **DONE 2026-07-28** (PR #29) — `run_feed` now runs the same
>    `prefilter_postings` call `run_fetch` does, before the resolve. See SPEC §7.1 (feed
>    ingestion) + CHANGELOG for the measurement and for the two silent mistranslations
>    (`title` vs `job_title`, epoch vs ISO date) the tests now pin.
> 6. **DONE 2026-07-30 — `--score-limit` is `40`** (`~/.config/systemd/user/ats-worker.service`
>    and `deploy/ats-worker.service.example`; restarted 11:07 EDT, between slots).
>    Re-measured at the decision, over **7 passes**: 23% of the weekly window by 04:50 on
>    07-30, i.e. **~3.3% per pass**, so 42 passes/week projects to **~138%** — close to
>    the 3-pass sample's ~140%, which was right for the wrong reason.
>    **The first arithmetic done here was WRONG and the lesson is about the instrument,
>    not the sums:** `db/scorer_usage.json` carries no `as_of` field, so "23%" was read as
>    current when it was 8 hours and one pass stale (`capture_usage` had silently stopped
>    writing — defect below), which understated the burn as ~2.9%/pass and ~121%/week.
>    **Check the file's mtime before quoting it.** `40` projects to **~92%**: under
>    budget, but the ~8% left over is one recovery run, not a comfortable margin — item
>    2's run then spent ~5%. Intake over the last 24h
>    was **~205 rows/pass** (median ~85 — it is spiky), so the cap, not intake, binds:
>    every pass saturated it. The cost is that `40` parks ~20 more rows/pass than `60`
>    (~120/day), and the backlog grows either way. The **choice made is *keeping up*, not
>    *catching up***; draining is a deliberate operator run.
>    **Found while checking the restart window:** the daemon had been running pre-#48 code
>    since 21:12 on 07-29, so every `blind response, no 'screen' object` line was a
>    posting kept unscreened and handed to the *paid* scorer. The restart picked the fix
>    up — after any screen-path merge, restart between slots or keep paying for it.
>    It was one number in
>    `ExecStart` (`~/.config/systemd/user/ats-worker.service`), then
>    `systemctl --user daemon-reload && systemctl --user restart ats-worker` **between
>    slots** — a restart mid-pass kills an in-flight `codex exec` and spends the quota for
>    nothing (the unit configures no graceful shutdown; see `deploy/*.example`).
>    **Do not reach for the cadence instead:** halving the passes doubles the intake each
>    one carries, so paid calls/week do not move. Only a lower cap or less intake
>    (`title_filter`, `max_age_days`, dropping low-yield boards) reduces spend.
>
> **Also open, not queued:** #21 ships dead. The
> [long-run-day runbook](./superpowers/plans/2026-07-24-long-run-day-runbook.md) phases 1-2
> (bounded fetch + scoring at scale) remain unrun — read them before any large paid pass
> for the quota math, monitoring cadence and authority boundary. Phases 3-4 are done.

### Quota — the gap and the three levers

**Measured live 2026-07-31** (`db/applications.db`, read-only): backlog **9,381** `new`;
intake **728 rows on 07-30** (07-29 was 3,212 — a feed spike, not the norm); scored **251
on 07-30, 197 on 07-29**. Capacity at `--score-limit 40` x 6 passes is **240 rows/day =
~1,680/week**, about 92% of the weekly window at the measured ~0.8 paid messages/row.

**So it is roughly 730 in, 250 out per day, and the backlog grows ~480/day.** Steady-state
demand is ~2,800–4,900 fit calls/week against capacity near ~1,344 — behind by ~2–3x. No
cap setting fixes that: `60` blew the budget at ~138%, `40` fits at ~92% but covers fresh
intake only. **Every figure here rests on `db/scorer_usage.json`, which is the file that
silently stopped updating — see Q1.**

**THE REFRAME, AND IT IS THE POINT: the backlog is not a debt to repay.** This system's job
is to surface ~15 postings a week to a human who applies by hand. It is not a queue
processor and it does not owe every row a verdict. A posting that is never scored costs
nothing unless it was one worth applying to. Read the gap that way and it is not a 3x
shortfall in throughput — it is that the ~250 rows/day the budget *can* buy are currently
drawn nearly at random with respect to whether they deserve the call. **96% of paid calls
buy a "no" and 54% are `too_junior`** (In flight, first entry): the budget is being spent
proving that jobs that were never viable are not viable.

**The three levers, and only these three.**
1. **Prioritize** (Q2). Adds no capacity; roughly doubles the yield of the capacity there
   is. Measured and ready.
2. **Cut intake** (Q3). The only lever that reduces demand rather than re-ordering it.
3. **Accept the parked backlog.** The 2026-07-22/23 rows are already unreachable by
   construction — the queue is most-recently-touched-first, so only a deliberate operator
   run reaches them. Treating them as owed is what makes the arithmetic look hopeless.

**Two moves that are NOT levers, both measured, do not re-propose them.** A *cheaper fit
model*: SCORING §8.7 — it lost on real JDs on both gate axes (agreement 76% vs 86%,
flip-rate 38% vs 29%) after winning a synthetic probe, and §9.1 puts calibrated numbers and
domain judgment on the strong-model-only side; even at 2x the calls it does not reach steady
state. A *slower cadence*: halving the passes doubles each one's intake, so paid calls/week
do not move — quota is a function of newly discovered postings, not of pass count.

**P3 — coverage and cost, in value-per-effort order.** `custom` HTML mode (`[M]`, drops
6 boards off Chromium and unblocks Citi/Barclays) → bulk watchlist skill (`[M]`). The
workday prose-date parser shipped but its *reduction* is not banked — it age-gates the
remaining 6,703 detail calls only as far as `max_age_days` and board staleness allow, and
how far that is has never been measured (see Unverified / deferred).

**P4 — everything else below.** SSRF residuals, the `@@unique` migration, schema
migration path, deployment/monitoring, dead-link sweep, more adapters, README
screenshot, eval iteration 2. Real, none of it blocking, none of it cheap.

### Defects — shipped behavior that is wrong (should fix)

- **`capture_usage` silently stopped writing the quota snapshot, and the quota is the
  binding constraint** — `[SCORE · XS · found 2026-07-30]`. `db/scorer_usage.json` was
  last written **04:50 on 07-30** despite two later passes that both fit-scored (the
  08:00 daemon pass, 49 paid calls, and the 12:00-ish recovery run, 73). Called by hand
  against the very same resolved path it returns `True` and writes correctly (live
  reading 32% where the file still said 23%), so the fetch is failing *inside the pass*
  and nothing says so: `capture_usage` is best-effort by contract and swallows every
  exception, `run_once` ignores the return value, and the file has **no `as_of` field**,
  so a stale snapshot is indistinguishable from a fresh one at a glance — only the mtime
  tells you, and the web renders the bar from that mtime while the CLI shows nothing.
  **This is how the first `--score-limit` arithmetic came out ~17 points optimistic.**
  Two things to fix, and they are separable: (1) find why the fetch fails under a pass
  but not standalone — a concurrent `codex exec` touching `~/.codex/auth.json` is the
  first suspect; (2) regardless of (1), make the failure
  *visible* — log at WARNING when `capture_usage` returns False, and stamp `as_of` into
  the snapshot so a stale reading is legible without an `ls -la`. (2) is the one that
  matters more: the instrument being wrong is survivable, the instrument being
  **silently** wrong is what cost the decision.
  **(2) SHIPPED 2026-07-30** (`chore/small-fixes-and-progress-split`; SPEC §7.1 +
  CHANGELOG): `run_once` prints `[quota] WARNING: no <backend> usage snapshot written`
  on a `False` return, and the snapshot carries an offset-aware `as_of` stamped at write
  time. **(1) is still open and is now the whole of this defect** — the next failing
  pass announces itself, so the diagnosis has a trigger instead of needing an mtime
  check. The web route still derives its own `as_of` from the file mtime (same instant,
  and it must keep working for pre-stamp snapshots), so the two agree; a reader of the
  raw file no longer has to.

- **The 4B misreads a soft degree bar as a hard one — 2-3 rows, and it is a MODEL CEILING,
  not a wording gap** — `[SCREEN · XS · residual of the 2026-07-28 degree fix]`.
  The defect itself is fixed (9 of 38 discards were false; `degree_levels` +
  `degree_required` with CODE taking `min(rank)` — CHANGELOG, SPEC §7.1). What survives:
  ids 67/68 (*"DESIRABLE CANDIDATES: Ph.D. candidates"* — one JD shape, counted twice)
  every run, plus in *some* runs a third soft-bar row — 738 (*"PhD or equivalent industry
  experience"*) or 672 (*"advanced degree … preferably a Ph.D."*) — coming back
  `degree_required: true`. **Do not diff the count**; it moved 3 → 2 between two
  back-to-back runs on identical code (SPEC §7.1 has the reason).
  **Do NOT spend a fifth prompt rewrite on it.** Four attempts are on record (two
  rewordings reached 4 then 5 and stopped converging; the shape change plus a sharpened
  clause reached 3 while *raising* recall). Probing the raw output settled why: the same
  model **invents** a `master's` level on genuine sole-PhD roles, so it is unreliable in
  both directions — a ceiling, not mis-instruction.
  **The remedy shipped 2026-07-29** (queue item 3, `needs_confirmation` routing): these
  rows are no longer deleted, they buy one paid fit call each and the strong model's
  extraction decides. The 4B ceiling itself is unchanged and unfixable at this size — what
  changed is what a misreading costs.
  **RE-MEASURED 2026-07-29 (post-#45 corpus repair): the count is 4, at the top of its
  band, and this run was internally STABLE** — ids 67, 68, 672 and 738, every one
  disqualified on all 3 draws, with a whole-run flip count of **0**. So the earlier "moved
  3 → 2 between back-to-back runs" instability did not reproduce here; a single run's count
  is still not a trend, and the standing instruction not to diff it holds. The repair did
  not touch degree rows, so 4 is a draw from the same distribution rather than a
  regression.

**Thirteen others found in the 2026-07-23 → 07-29 sweep have shipped fixes** and their
records are in CHANGELOG + SPEC (§7.1, §9 traceability, §11); they are not repeated here.
**One consequence outlives them:** the ~20 rows the clearance defect already killed are
still `discarded` — queue item 2 recovers them.

**The pattern, and the reason PRINCIPLES exists.** Nine of the thirteen were the same
policy error — a *systemic* condition handled as a per-item verdict — now named in
[`PRINCIPLES.md`](./PRINCIPLES.md) ("the four kinds of uncertainty") and obeyed by every
pipeline stage. The 2026-07-27/28 pair is a *different* class: a per-item verdict acted on
**without checking what the JD says**. They part company on the remedy — clearance is
lexical, so code can floor it on a token; degree is semantic, so no floor exists and the
answer is routing, not a regex.

### The rest of the open catalogue lives in two other files

Everything below the defects moved out on 2026-07-30 — this file is reloaded by every
session and most of it was reference material, not state.

- **[`BACKLOG.md`](./BACKLOG.md)** — the open catalogue: *Unverified / deferred*
  (behavior may be fine but nothing proves it, or a decision is pending) and
  *Enhancements* (not built, optional). Same tags, same easiest-first ordering. Pick
  work from here once the queue above is exhausted — or, while quota is the standing
  priority, only where an entry is a quota lever.
- **[`REJECTED.md`](./REJECTED.md)** — proposals evaluated and turned down, with the
  measurement that killed each. **Read the entry for your block before proposing a
  redesign of it.**

---

## How to update

This file tracks only *movement*; it should never accumulate a wall of finished
items. When state changes:

- **Starting work** → add an in-flight line under [In flight](#in-flight).
- **Closing a gap / shipping a feature** → remove its line here, add a
  [`CHANGELOG.md`](../CHANGELOG.md) entry (history), and update the matching section
  of [`SPEC.md`](./SPEC.md) (the capability map / behavior) — **all in the same
  commit**.
- **Discovering a new gap** → a **defect** (shipped behavior that is wrong) goes in
  [Defects](#defects--shipped-behavior-that-is-wrong-should-fix) here; anything else
  goes in [`BACKLOG.md`](./BACKLOG.md), under *Unverified / deferred* or
  *Enhancements*. Either way place it **easiest-first** in its section and tag it
  `[BLOCK · XS/S/M/L · blocker]` — block first, from the eight in the
  [Open work](#open-work) table (`FETCH` · `SCREEN` · `SCORE` · `NOTIFY` · `ORCH` ·
  `WEB` · `INFRA` · `DOCS`), then effort, then any blocker. Keep
  severity honest: defects (broken) above unverified properties above enhancements
  (optional). A defect claim wants an **executed repro** pasted in, not a reading of
  the code; a rejected proposal is worth its own record under
  [`REJECTED.md`](./REJECTED.md) so it is not
  re-derived, and belongs in the entry named for its block.
