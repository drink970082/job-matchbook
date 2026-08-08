# Job Matchbook — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.
>
> What stays here is what a session needs *now*: in flight, the pick order, the quota gap,
> and open defects. The rest is two files it can load on demand —
> [`BACKLOG.md`](./BACKLOG.md) (the open catalogue: unverified/deferred + enhancements)
> and [`REJECTED.md`](./REJECTED.md) (proposals evaluated and turned down; read your
> block's entry before proposing a redesign).

**Current phase:** released and running unattended. `v1.0.0` is tagged on `main`, the repo
is public as [`drink970082/job-matchbook`](https://github.com/drink970082/job-matchbook),
CI is green (web / worker / e2e), and the worker runs as a systemd user unit on a
wall-clock schedule. **"Hardened" means test/CI hardening, not security hardening** —
accepted residuals are in SPEC §11 + `SECURITY.md`.

**`make eval-screen` is RED on `main`** at 2-3 degree false-disqualifications. That is a 4B
model ceiling, not a wording gap, and the count is not run-to-run stable — do not diff it,
and do not spend another prompt rewrite on it (see Defects).

**QUOTA IS THE STANDING PRIORITY (operator's call).** Work that is not a quota lever waits.
The gap, the three levers that move it, and the two measured dead ends are in
[Quota — the gap and the three levers](#quota--the-gap-and-the-three-levers). **The reframe
that section turns on: the backlog is not a debt to repay** — this system surfaces ~15
postings a week to a human, it does not owe every row a verdict, so the problem is *which*
rows get the paid call, not how many. **96% of paid fit calls buy a "no"** (75%
`domain=mismatch`, 54% `seniority=too_junior`), which is why the free seniority
pre-ordering exists.

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

- **The golden fit corpus is being rebuilt, and it is blocked on human review**
  `[SCORE · M · blocks the `eval-score` gate; the tools are on `main`]`.
  The blind labeler and the sheet generator exist (`tools/label_run.py`,
  `tools/build_review_sheet.py`). **Phase 5 does not** — folding reviewed answers back
  into `golden.jsonl` with inline posting payloads is unbuilt, so nothing consumes
  `eval/golden_review_answers.json` today.
  **Where the review stands:** the 287 *reachable* rows of `golden_expanded.jsonl` are
  labelled blind on both backends (574 calls, 0 errors). 203 consensus rows are accepted
  without review; the queue is **84 rows — 59 disagreements plus 25 seeded audit rows**
  drawn from the consensus set. **24 answered, 60 open.** Serve the sheet with
  `python3 apps/worker/eval/review_server.py` (binds 127.0.0.1:8765 only; autosaves).
  **Consensus is not truth**, which is what the audit sample is for — row 25206 (UPS,
  generic enterprise app support, labelled `match`) is the standing example of both
  backends agreeing and both being wrong.
  **The 40 earlier answers in that file grade nothing.** Both backends independently
  agree with them on 24/37, which fits two different stories — the rules changed under
  those answers, or the profile still does not capture the judgment — and this run
  separates neither. They are displayed as context and never pre-selected.
  **Backend split, for whoever works the queue:** agreement 228/287 (79%); domain
  241/287, seniority 273/287. claude-code is the more conservative side (215 `mismatch`
  to codex's 184, and it would notify on 19 rows against codex's 27).
  **Measured cost, over 100 live calls:** claude-code spends **0.29pp of the 5-hour
  session window per call** and ~0.02pp of the weekly, so the *session* window binds,
  not the weekly one; a 287-row pass lands near 93% of it. Codex is 0.053%/call.
  `eval/` is gitignored — this state lives on the operator's host and nowhere else.

- **Quota levers: prefix caching and the seniority vetoes**
  `[SCORE · M · Phase 1 closed as a negative; Phase 3 open]`.
  Branches, one per phase: **`docs/quota-levers-plan`** (this claim, the plan, the
  ledger), **`fix/seniority-veto-evidence`** (Phase 3), and a Phase 1 branch for the
  caching fix. Plan and full sequence:
  [`superpowers/plans/2026-07-31-quota-levers-caching-and-vetoes.md`](./superpowers/plans/2026-07-31-quota-levers-caching-and-vetoes.md);
  spend is logged per call in
  [`superpowers/notes/2026-07-31-quota-ledger.md`](./superpowers/notes/2026-07-31-quota-ledger.md).
  **The finding that motivates it:** every "message-bound quota" claim in the code and
  docs was wrong. The sites are `SCORING.md` §4.5/§5.6/§8.5 and `SPEC.md` §7.1/§10 —
  **grep the claim, don't trust a line ref**, which is how the first sweep missed two
  paraphrases that mattered more than the literal hits (`tools/score_eval.py` telling every
  drift report a smaller batch "keeps most of the quota win", and the long-run-day
  runbook's **Budget** section sizing a run in messages — its row counts still hold, its
  ceiling does not). The
  ChatGPT-subscription quota has been **per-token credits since April 2026**, not
  message-bound (Sol 125 / 12.5 cached / 750 per 1M; Luna 25 / 2.5 / 150 — 5 : 2.5 : 1).
  `SCORING.md:986-991` already flagged message-bound as an unmeasured working assumption
  and named the missing instrument; the instrument turns out to be the codex **rollout
  files**, which carry exact per-call `input_tokens` / `cached_input_tokens`.
  Two consequences, both measured over 158 production calls: our prompt is only **~39%**
  of what a call bills (6,512 of 16,775 tok; 7,332 is itemised codex CLI harness and
  ~2,931 is unattributed), and **prefix caching is capped by one line** —
  `backends_codex.py:118` opens a fresh `TemporaryDirectory()` passed as `-C` at `:138`,
  and that random path is echoed into the prompt at `<environment_context><cwd>` ahead of
  the whole scoring prefix. Every cache hit stops at **exactly 11,008 tokens** (86 x 128),
  42 times out of 42, so the ~5,500-token rubric+profile+résumé prefix is re-billed fresh
  on every call — and only **27%** of calls cache anything at all (positions 0-5 of every
  burst miss 100% of the time under `score_workers=4`).
  **THE CACHING FIGURES ARE CORRECT BUT OUT OF DATE — they describe a CLI that is not
  installed.** 11,008, the 42, and the 27% all re-derive exactly from
  `db/codex-token-accounting/rollout-token-usage.jsonl` (53 of 198 `gpt-5.6-sol` rows
  cached anything = 27%, and 42 of those cached exactly 11,008), so
  they are not wrong — they are **0.144.x** measurements. The installed CLI is **0.146.0**,
  where Phase 1b measured `cached_input_tokens = 0` on both arms of a controlled probe: no
  cache is operating, so there is nothing for the `-C` change to fix and no headroom to
  reclaim. Quote them as history, never as current headroom. The stable-`-C`
  lever was therefore **not shipped**. Full negative in
  [`superpowers/notes/2026-07-31-quota-ledger.md`](./superpowers/notes/2026-07-31-quota-ledger.md).
  The per-token billing finding above is unaffected — that one reproduced.
  **Work happens in separate worktrees** so the daemon never imports experimental code;
  `main` stays checked out and running in the primary tree. Worktrees and branches are
  removed when the run finishes.

- **Both eval corpora are too small to answer the questions being asked of them — expansion
  in flight** `[SCORE + SCREEN · M · branch `docs/corpus-expansion-groundwork`]`.
  Neither eval is code-bound; both are corpus-bound.
  **Score:** `eval/golden.jsonl` is 23 rows, and the standing `gpt-5.6-terra` rejection
  (76% gate vs sol's 86%) is a **two-row** gap on it. Re-running that A/B cannot separate the
  models. Target ~120 rows, drawn from the `keep`/`adjacent` bands where models actually
  diverge; `tools/expand_golden.py` builds the 499-row Sol-labelled sampling frame (machine
  labels — a frame, never a gate).
  **Screen — the sharper one, because it is a portability requirement.** The sponsorship
  half rests on 11 effective rows of 21 (BACKLOG has the corpus conventions). That blocks
  the real question: the
  GPU-less path (`SCREEN_BACKEND=codex`) shipped on the call that "no new gate needed"
  (screen-backends design §327), so users without a GPU run an **unmeasured** screen today.
  `gpt-5.6-luna` is the cheapest model on that path and has never been measured — its
  standing rejection is for *fit scoring*, which §10 argues does not transfer. Bar is the
  gate's own: zero false disqualifications. Plan:
  `~/.claude/plans/what-are-small-dev-vectorized-elephant.md`.
  **Luna was measured twice, and one run would have told you the wrong thing.**
  `SCREEN_BACKEND=codex SCREEN_MODEL=gpt-5.6-luna`, K=3, 83 rows. Run 1 **PASS** (0 false
  disqualifications, recall 29/37); run 2 **FAIL** (1, recall 28/37). The gate is
  **any-draw, not majority** by design (`screen_eval.py:149` — "a check that discards a
  good posting one time in three is not a passing check"), so a ~1-in-3 per-draw fault is
  caught by K=3 only ~70% of the time: **run 1's zero was a 30% miss, not evidence of
  absence.** Run 2 is the trustworthy one. Never promote a screen backend off a single run.
  **A SIBLING BRANCH SAYS THE OPPOSITE — reconcile before merging it.** Another session's
  unmerged `docs/luna-screen-result` (commit `8b25e97`) is titled *"luna passes the screen
  gate and beats the local 4B"* and records *"PASS with ZERO false disqualifications"*.
  That is **run 1**, the same 249-call run this session found already on disk — not an
  independent confirmation. Run 2 reversed it. Whoever merges that branch must fold in this
  entry rather than land both, or `main` will carry a PASS claim the replication refutes.
  **What it actually shows, against the 4B's own documented RED set (67/68/672/738):**
  the 4B fails all four on **3/3 draws each — 12 bad draws of 12**. Luna, over both runs,
  produced **1 bad draw of 24** (id 672 only, `X..`), clearing 67/68/738 outright. That is
  ~25x fewer, so "model ceiling" survives as a description — but the residual is not purely
  size, since a frontier model still trips 672 (*"advanced degree … preferably a Ph.D."*).
  **The shipping read is better than the FAIL headline.** A degree false-disqualification
  no longer deletes a row — `needs_confirmation` routing sends it to the paid scorer — so
  luna's residual costs **one paid fit call**, not a lost job, while being strictly better
  than what GPU-owning users run today.
  **On the expanded 103-row corpus, and this is the decisive comparison** — same corpus,
  same day, both backends:

  | backend | false disqualification (the gate) | recall | flip |
  |---|---|---|---|
  | `ollama` qwen3.5:4b | **7** — 4 degree + **3 clearance** | 31/37 (84%) | 0 |
  | `codex` gpt-5.6-luna | **0** | 30/37 (81%) | 3 |

  **The 3 clearance failures are rows the eval could not see until today**, and they are
  not subtle: the 4B disqualifies on *"BACKGROUND CHECKS/CLEARANCES"* in a university
  employment boilerplate (Penn State, x2) and on BlackRock's **job title**, *"Associate,
  Trade Clearance/Settlement"*. All 3/3 draws. It is matching the word, not the meaning.
  Luna is clean on **all 14** new clearance rows and on 672, every draw.
  **Luna's full record is 3 runs: PASS / FAIL / PASS**, the single failure being one draw
  of three on id 672 — so **1 bad draw in 9** against the 4B's 3-of-3 on four separate
  rows, every run. It is not perfectly stable and should not be described as such; it is
  roughly an order of magnitude better on exactly the failure this gate exists to catch.
  **And it is nearly free, which was the open cost question.** 249 luna screen calls
  (83 rows x K=3) moved the reported window from **41% to 41%** — under the endpoint's
  1-point resolution, so <1%, against ~12% had they billed like fit messages (~0.8
  msg/row). Screening on `codex`/luna therefore costs a GPU-less user almost nothing
  against the weekly budget; it is the *fit* call that is expensive. Do not read the 0 as
  exactly zero — integer percent hides anything under a point — but the order of magnitude
  is settled.
  **THE TERRA QUESTION — the original rejection was right about the wrong thing.**
  The human gate is vacuous (see Defects), so both arms ran against a
  40-row stratified subset of the Sol-labelled frame (15 `keep`, 25 `near`, fixed seed),
  via the new `GOLDEN_SET` override. K=3, `codex` backend:

  | arm | agreement with the stored sol verdicts | flip-rate (self-disagreement) |
  |---|---|---|
  | `gpt-5.6-sol`, fresh | 34/40 (85%) | **22%** |
  | `gpt-5.6-terra` | 32/40 (80%) | **35%** |

  **Read the two columns differently, because only one of them is label-independent.**
  *Agreement* is measured against sol's own stored verdicts, so it structurally favours
  sol — and even so, **sol re-run agrees with itself only 85% of the time.** That 6-row
  self-disagreement IS the noise floor the original comparison never had, and terra's 80%
  sits inside it. **The "76% vs 86%" gap that rejected terra does not reproduce as a
  meaningful difference.**
  *Flip-rate* compares each model against itself, needs no labels, and **does** reproduce:
  terra 35% vs sol 22%, against terra 38% vs sol 29% on the earlier corpus. Terra is ~1.5x
  less self-consistent, measured twice, fifteen days apart, on different corpora.
  **So the rejection stands, on stability rather than on accuracy** — which matters because
  the notify gate is a verdict predicate, and a model that changes its mind on a third of
  rows moves rows across it at random. Do not re-run the agreement comparison as the
  deciding test; run flip-rate, which needs no golden set at all.

- **General-purpose pivot — Stage 3 deferred.** **Stage 3, non-tech discovery feeds:** the
  watchlist already covers any company, so decide the need before building (brittle,
  anti-bot handling, dilutes the moat).
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
| `FETCH` | `fetch/` adapters, recipe executors, `feed/`, `run_fetch`/`run_feed`/`run_expire`, watchlist | 15 — the long tail lives here; no defects. The one that matters most: 50 bodyless Microsoft postings, the largest `empty_description` source |
| `SCREEN` | `score/screen.py`, `score/location.py`, `screen.txt`, the screen backends | 4 — **1 residual** (a 4B ceiling, not a coding defect; it costs a paid fit call rather than a deleted job) plus what the eval can actually reach and the snippet window degenerating on bullet JDs. `make eval-screen` gates the prompt |
| `SCORE` | `run_score`, fit backends, `score.txt`, scorecard schema, quota | 4 — **quota is the binding constraint**: the cap is `--score-limit 40` because `60` projected to ~138% of the weekly budget, and 655 queued rows fail today's filters |
| `NOTIFY` | `notify.py`, `get_notifiable`, `run_notify`, Telegram | 0 — no defects |
| `ORCH` | `pipeline.py` shape, `db.py` transitions, retry budgets, threading, scheduler | 2 — no defects; scheduler/cadence and the un-hydrated stub discards |
| `WEB` | `apps/web` — Prisma schema, server actions, UI | 2 |
| `INFRA` | Docker, healthcheck/autoheal, CI, migrations, deployment | 4 |
| `DOCS` | `docs/`, README, `AGENTS.md`/`CLAUDE.md`, `.claude/skills/` (+ the `.agents/skills` link), evals | 4 |

The five *evaluated-and-rejected* records in
[`REJECTED.md`](./REJECTED.md) are named by block
rather than tagged (`Fetch capability registry…`, `Notification outbox…`, `Score shape
changes…`, `Screen shape changes…`, `Orchestration-layer shapes…`) — read the one for
your block before proposing a redesign of it.

**Open defects: three**, all in [Defects](#defects--shipped-behavior-that-is-wrong-should-fix)
— a vacuous fit gate, an intermittently missing quota snapshot, and a 4B degree ceiling
that is a model limit rather than a coding error.

### Provider generality

**Operator's call: this is a general-purpose tool, and neither the hardware nor the
provider is part of the product.** The target matrix is four AI backends —
`claude-api`, `claude-code`, `openai-api`, `codex` — for BOTH stages, plus a local
option (Ollama) on the screen. PRINCIPLES 4 was rewritten in the same change from a
hardware statement ("runs on the host GPU") to a cost-tier one, and SPEC §3/§4 follow.

**Quota is a PRODUCT constraint, not this deployment's quirk.** The reasoning that
settles it: the operator's own plan is the GENEROUS end — a flat-rate weekly window of
roughly 2000 messages — and the backlog still does not fit inside it. Anyone on a
tighter or metered plan is worse off by definition. So the levers already underway
(free seniority vetoes cutting paid CALLS, prefix caching cutting TOKENS) are product
work, not personal tuning, and they generalize: fewer calls and fewer tokens help all
four backends identically. Nothing in the quota plan needs replanning.

What does NOT generalize is the reporting layer — `capture_usage` is per-provider, and
two of the four have no usage endpoint story yet.

**The open gap, and it is a stated contract violation (SPEC §4):**

- **Fit scoring supports two of the four backends** — `[SCORE · M · blocks the goal]`.
  `run.make_scorer` dispatches `codex` and `claude` only; `SCORE_BACKEND=openai` is
  explicitly rejected. A user with a Claude Code subscription and no API key, or with
  only an OpenAI key, can screen but cannot score — and scoring is the stage that
  matters. The screen stage is already complete at five backends, so the whole
  remaining gap is **two fit adapters**.
  **The contract is already clean:** `make_scorer`'s own docstring says both twins
  expose the same `fit(postings, resumes) -> list[dict]` shape, so "only this line
  changes"; `backends_claude.py` is 67 lines. This is a longer LIST, not a new
  abstraction — do not build a provider base class or a registry.
  **The honest cost is four parts per adapter, and the adapter is the small one:**
  1. the adapter itself;
  2. a `_scorer_meta` branch — it already warns that falling through writes a
     silently WRONG provenance stamp;
  3. `capture_usage` support, or an explicitly documented "none". A backend with no
     quota bar is a backend the user flies blind on.
  4. **an `eval-score` run on the golden set.** Fit is judgment and judgment is
     calibration-sensitive: `run.py` already rejects `gpt-5.6-luna` for fit on MEASURED
     grounds (~3x looser spread). Shipping a fit backend without measuring it repeats
     the exact mistake the screen side made — six options, one measured.

- **Four of the five screen backends have never been measured** —
  `[SCREEN · M · shipped unvalidated]`. `tools/screen_eval.py:23` is explicit that the
  gate is meaningful only when eval-model == production-model, and it defaults to
  ollama/qwen3.5:4b. So `make eval-screen` gates the path the operator runs and nobody
  else's. A GPU-less user on `SCREEN_BACKEND=codex` runs an accuracy path with no
  measurement behind it. The harness already accepts `SCREEN_BACKEND` and per-backend
  models, so this is run-and-record, not build.

### Do next — the pick order

The buckets below are a *catalogue* sorted by severity. This is the **queue**: what to
take first and why. Each numbered item is independently pickable.

> **Only Q3 is open.** Anything in the catalogue below that is not a quota lever waits.
> The reasoning is in
> [Quota: the gap and the three levers](#quota--the-gap-and-the-three-levers) immediately
> after this queue; read it before picking, because two of the obvious moves (a cheaper
> fit model, a slower cadence) are measured dead ends.
>
> **Q3. Cut intake — `[FETCH · S]`.** The only lever that reduces *demand* rather than
> re-ordering it: `title_filter`, `max_age_days`, and dropping low-yield boards. The feed is
> the firehose (3,212 rows on a spike day against ~730 on a normal one). The zero-yield
> watchlist rows — `mlp` (measured at 0 postings), `globalcareers-msci`, both Citadels — are
> the trivial end of it and are one decision. Numbers in
> [`BACKLOG.md`](./BACKLOG.md)'s intake-cut entry; **the call is the operator's.**
> **Board-side filtering is not a general lever** — it was probed per board and only Amazon
> takes it (now US-only: 768 fewer rows/pass, identical survivor set). TikTok/ByteDance
> accept city codes only, Workday silently IGNORES an unrecognised country facet, and
> greenhouse ignores location params outright. Table in `BACKLOG.md`.
>
> **Also open, not queued:** #21 ships dead. The
> [long-run-day runbook](./superpowers/plans/2026-07-24-long-run-day-runbook.md) phases 1-2
> (bounded fetch + scoring at scale) remain unrun — read them before any large paid pass
> for the quota math, monitoring cadence and authority boundary.
>
> **One piece of live state a pass will not fix:** ~3,880 requeued discards sit in `new`
> outside any reachable window. At `--score-limit 40` against ~205 rows/pass of fresh
> intake, no scheduled pass reaches them — they are parked, not queued, and draining them
> is a deliberate operator run (`--rescreen-discarded` + `--score-max-id`, and
> `--no-notify` is not optional: `run_notify` has no per-pass cap, so a recovery run
> without it fires every newly-matched row at Telegram in one burst).

### Quota — the gap and the three levers

**READ BEFORE QUOTING ANY "messages" FIGURE BELOW.** Every per-row and per-week number in
this section is denominated in **messages** (`~0.8 paid messages/row`, `~2,000/week`).
The quota is **per-TOKEN credits** (measured 2026-07-31; SCORING §4.5). The *ratios* and
row counts still hold — they came from counting calls — but the ceiling and the
"% of a weekly window" arithmetic do not, and must be re-derived against credits before
they size a decision. Not rewritten in place because the credit-side denominator has not
been measured yet; the rollout instrument that would measure it is no longer available
(SCORING §4.5).

**Measured live 2026-07-31** (`db/applications.db`, read-only): backlog **9,381** `new`;
intake **728 rows on 07-30** (07-29 was 3,212 — a feed spike, not the norm); scored **251
on 07-30, 197 on 07-29**. Capacity at `--score-limit 40` x 6 passes is **240 rows/day =
~1,680/week**, about 92% of the weekly window at the measured ~0.8 paid messages/row.

**So it is roughly 730 in, 250 out per day, and the backlog grows ~480/day.** Steady-state
demand is ~2,800–4,900 fit calls/week against capacity near ~1,344 — behind by ~2–3x. No
cap setting fixes that: `60` blew the budget at ~138%, `40` fits at ~92% but covers fresh
intake only. **Every figure here rests on `db/scorer_usage.json`, which is the file that
still goes missing on roughly a fifth of passes — see Defects.**

**THE REFRAME, AND IT IS THE POINT: the backlog is not a debt to repay.** This system's job
is to surface ~15 postings a week to a human who applies by hand. It is not a queue
processor and it does not owe every row a verdict. A posting that is never scored costs
nothing unless it was one worth applying to. Read the gap that way and it is not a 3x
shortfall in throughput — it is that the ~250 rows/day the budget *can* buy are currently
drawn nearly at random with respect to whether they deserve the call. **96% of paid calls
buy a "no" and 54% are `too_junior`** (SCORING §5.7): the budget is being spent
proving that jobs that were never viable are not viable.

**The three levers, and only these three.**
1. **Prioritize** — the free seniority pre-ordering. Adds no capacity; roughly doubles the
   yield of the capacity there is. Shipped; what remains is measuring the demote rate and
   paid-call yield on live passes, since both are still projections (SCORING §5.7).
2. **Cut intake** (Q3). The only lever that reduces demand rather than re-ordering it.
3. **Accept the parked backlog.** The oldest rows are already unreachable by
   construction — the queue is most-recently-touched-then-newest
   (`COALESCE(updated_at,'') DESC, id DESC`), so a bounded pass scores current intake and
   never walks the backlog. Only a deliberate operator run reaches it: `--score-only`
   (skips ingest, drains from the top of the id range), with the
   [runbook](./superpowers/plans/2026-07-24-long-run-day-runbook.md) phases 1-2 for the
   quota math and monitoring cadence. Rows predating scorer provenance carry no
   `backend`/`model`/`scorer_version` stamp, so "unstamped" selects them (SPEC §9).
   Treating them as owed is what makes the arithmetic look hopeless.

**Two arithmetic traps in this section.** (1) **`--score-limit` is not a pure quota
budget** — an LLM screen-discard and a thin-JD row each consume a slot while spending
nothing (~18% of screened rows on live passes, 8.2% over DB history; SPEC §7.1), so the
cap bounds *slots*, not spend. (2) **The ~18% free-discard rate and SCORING §5.7's 54% are
different denominators** — most of that 54% is the deterministic location gazetteer, not
the model screen. They are not reconciled; do not average them.

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

- **The authoritative fit corpus is rotted: 22 of `golden.jsonl`'s 93 rows name postings
  that no longer exist** — `[SCORE · M · needs human labelling]`. The labels are hand-written
  and **not recoverable by remapping** — matching a row's note back to a live posting by
  title is ambiguous (two different golden rows fuzzy-match the same candidates), and
  binding a hand-written verdict to the wrong posting is worse than an empty gate. There is
  no `DELETE FROM job_postings` anywhere in the worker or the web; the set was curated
  against a DB state that no longer exists.
  **Two things are fixed, and neither is the corpus.** (1) Rows may carry an inline
  `posting` payload and the eval falls back to it, making the corpus self-contained the way
  `screen_golden.jsonl` already is — that asymmetry is exactly why the screen corpus
  survived and this one decayed; `tools/label_golden.py` writes the payload for every new
  row. **It rescues none of the 22** — all 70 rows carrying a payload are also live in the
  DB — so it is forward protection, not mitigation. (2) An unreachable row **fails** the
  gate instead of silently shrinking it, so the rot no longer has to be remembered:
  `make eval-score` is RED on its own, **exit 1 and not merely a FAIL in the report** —
  a FAIL that does not reach the exit code is a gate CI cannot enforce.
  **The repair job is 20 rows, not 22.** The other two (132, 184) are `marked` watch-list
  rows, which the gate excludes from PASS by policy; they are reported without gating,
  because failing on them would mean the corpus could never go green however many gate
  rows were relabelled.
  **`GOLDEN_SET`/`SCORE_EVAL_OUT` run an A/B against a substitute corpus meanwhile.** A
  substituted corpus is not the gate: anything built from the strong scorer's own verdicts
  measures agreement, not correctness, so a genuinely better challenger scores as a
  regression. The blind two-backend relabel under In flight is the rebuild.

- **`capture_usage` misses the quota snapshot on roughly a fifth of passes, and the quota
  is the binding constraint** — `[SCORE · XS · mitigated, cause unnamed]`. The failure is
  a real, intermittent, in-pass one: the codex usage endpoint answers **HTTP 403** under
  load and the snapshot is simply not written for that pass. It is no longer silent —
  `run_once` prints `[quota] WARNING: no <backend> usage snapshot written`, every route to
  a `False` return names itself, and the snapshot carries an offset-aware `as_of` so a
  stale reading is legible without an `ls -la`. A 4-attempt retry on a growing 2/8/20s
  schedule is the mitigation; at the observed per-call failure rate it still leaves ~20%
  of passes uncovered.
  **The cause is not established, and hand calls cannot establish it.** Called by hand the
  endpoint alternates 403 / 200 / 403 inside forty seconds — consistent with a limiter
  near its threshold (Cloudflare rate-limit rules commonly answer 403, not 429) — but the
  hand client is not the in-pass client, so it may not sample the same thing at all. **The
  measurement that would settle it is the WARNING rate across passes over days**, not more
  hand calls. Two candidates remain unobserved rather than excluded: a 200 whose
  `used_percent` comes back null under load, and a truncated body (`IncompleteRead`, which
  subclasses neither `OSError` nor `ValueError`).
  **The remedy that sidesteps the question** — capture usage at pass START, before the
  account is hot — is in `BACKLOG.md`.

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
  **The cost is bounded, not the ceiling.** `needs_confirmation` routing means these rows
  are no longer deleted: each buys one paid fit call and the strong model's extraction
  decides. The 4B ceiling itself is unfixable at this size — what changed is what a
  misreading costs. The count sits in a 2-4 band across runs; a single run's count is not
  a trend.

### The rest of the open catalogue lives in two other files

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
items. The full rule — current state only, no dated completion records, no narrating the
document's own edit history — is in [`CLAUDE.md`](../CLAUDE.md) / `AGENTS.md`.
When state changes:

- **Starting work** → add an in-flight line under [In flight](#in-flight). **When it
  lands, that line leaves** — an entry saying "MERGED as `abc1234`" is a completion
  record, and completion records live in git.
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
