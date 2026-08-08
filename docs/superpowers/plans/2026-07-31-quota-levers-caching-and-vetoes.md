# Quota levers: prefix caching, harness trim, and the seniority vetoes

**Status:** Phase 1 is closed as a negative — see its header before reading any of its
figures as available headroom. Phase 3 (the seniority vetoes) is the live part; the
operator is no longer away, so the standing 60-call budget and merge authority below have
lapsed and a paid run wants a fresh ask.

> **For a session picking this up mid-run:** phase order and dependencies are under
> [Sequence and dependencies](#sequence-and-dependencies). Where the run actually *is*
> lives in the `PROGRESS.md` In-flight entry and in the quota ledger at
> `docs/superpowers/notes/2026-07-31-quota-ledger.md` — not in this file. The **stop
> conditions** under Ground rules are binding.

## Context

Quota is the standing priority (operator's call, 2026-07-31). The working assumption
underneath every quota decision in this repo — `run.py:69` (in the comment block running
68-77), `pipeline.py:811` and `backends_codex.py:49`, "the ChatGPT-subscription quota is
MESSAGE-bound, not token-bound" — is **factually wrong as of April 2026**. OpenAI moved
Codex to per-token credits (Sol 125 / 12.5 cached / 750 per 1M; Terra 62.5 / 6.25 / 375;
Luna 25 / 2.5 / 150 — a clean 5 : 2.5 : 1). The full list of affected sites is in
Phase 5.1; it is thirteen, not three.

Three things follow, measured this session against the live system:

1. **Our prompt is only ~39% of what each paid call bills.** Mean input is 16,775 tokens
   over 212 historical rollouts; our rubric + profile + 2 résumés + JD is ~6,512 of that
   (6,512 / 16,775 = 38.8%). The itemised codex CLI harness accounts for 7,332 —
   `base_instructions` 4,503, `<permissions instructions>` 1,967, an agent-team role
   prompt 460, `<multi_agent_mode>` 46, `<recommended_plugins>` 356. **The remaining
   ~2,931 tokens (17.5%) are unaccounted for** — they do not appear as `response_item`s
   in the rollout, so the likeliest home is the `--output-schema` payload and tool/format
   definitions. Do not attribute them until something measures them.
2. **Prefix caching is capped by one line, and separately it mostly does not fire.**
   `backends_codex.py:113` opens a fresh `tempfile.TemporaryDirectory()`, passed as
   `-C tmp` at `:133`. That random path is echoed into the prompt at
   `<environment_context><cwd>/tmp/tmpXXXXXXXX</cwd>`, 10,893 chars in — **ahead of the
   entire scoring prefix**. Measured consequence: all 42 production cache hits cached
   **exactly 11,008 tokens** (= 86 x 128, a block boundary), never one token more, so our
   ~5,500-token scoring prefix is re-billed fresh on every call without exception. And
   only **27%** of production calls cache anything at all — positions 0-5 of every burst
   miss 100% of the time (0/27) under `score_workers=4`.
3. **The seniority layer's misses are code's fault, not the model's.** Of 61 misses in
   the 446-row eval, 34 come from `clamp_years` taking the minimum years figure across
   the *whole* document (a stray "1 year of experience with Kubernetes" in preferred
   qualifications collapses a real 5-year bar), and 9 from `rank_stated_in` demanding the
   exact rank word the model named ("Senior ..." titles where the model normalised to
   `staff`). 70% of misses, recoverable in code with no prompt or model change.

Credits per call at Sol rates (125 fresh / 12.5 cached / 750 output per 1M), over the
measured median production call of 17,757 input + 639 output tokens:

| | credits/call | saving | verdict-quality risk |
|---|---|---|---|
| **as it runs today** (27% hit at the 11,008 cap) | **2.365** | — | — |
| fixed `-C` only, hit rate unchanged | 2.198 | 7% | none |
| fixed `-C` + cache warming (~90% hit) | 1.027 | **57%** | none |
| `--ignore-user-config` (356 tok) | 2.320 | **1.7%** | none |
| switch to Luna | 0.52 | 80% | unproven; §8.7 demands a full eval |

**Two of those rows were wrong in the first draft and the corrections change the
priorities.** The caching row said 51% for the `-C` fix alone; the forensics showed the
`-C` fix is worth 7% and the *hit rate* is worth the other 50%, so Phase 1 carries both
changes. The harness row said 30%, which implied removing 6,240 tokens — but Phase 2's own
text says `base_instructions` and the permissions block are **not** addressable from here,
so all `--ignore-user-config` removes is `<recommended_plugins>`: **356 tokens, 1.7%**.
Phase 2 is therefore roughly an hour of work for under 2% of spend, and it is retained for
its *hermeticity* argument — the paid prompt currently varies with the operator's
`~/.codex/config.toml` — not as a quota lever.

The 5:2.5:1 rate ratio, the 11,008-token cap, the 27% hit rate and the tmpdir mechanism
are measured. Token-count *estimates* derived from character counts use ~4 chars/token and
are approximate; the rollout `input_tokens` figures are exact.

**Goal of this plan:** claim the caching lever (the only large zero-risk one), fix the
code-side seniority vetoes behind the existing free eval gate, take a first read on Luna,
make the paid prompt hermetic, and correct the stale MESSAGE-bound claims wherever they
are quoted.

**What this does NOT propose, and why it belongs here anyway.** Under token billing,
batching N JDs into one call amortizes the whole prefix across N and would be a larger
lever than anything above — which inverts the reasoning at `SPEC.md:983`,
`SCORING.md:982-990`, `pipeline.py:811` and `run.py:68-77`, all of which argue *from*
message-counting. SCORING §8.5 still kills batching, on measured verdict-bleed grounds
that are independent of billing, so the conclusion does not move. Two things worth
recording: the repo already hedged this itself (`SCORING.md:986-991` calls message-bound
"a working assumption with no measurement behind it" and names the obstacle — an integer
`used_percent` that a single call moves by ~0.05%), and the missing instrument turns out
to exist: the codex **rollout files** carry exact per-call `input_tokens`,
`cached_input_tokens` and `output_tokens`. Also note that a working prefix cache captures
most of what batching would have won, at 90% off the prefix, without the bleed.

## Operator authorizations (given 2026-07-31, before this plan was written)

- **Quota budget: up to 60 paid calls (~5% of the weekly window).** Hard cap. A running
  ledger is kept at `docs/superpowers/notes/2026-07-31-quota-ledger.md` and updated at
  every spend. At 60, stop and report — do not spend a 61st for any reason.
- **Merge authority: fresh-subagent review then self-merge**, per DEVELOPMENT.md §7.
  Review gets only the diff, the commits and the PROGRESS entry — never this plan or any
  reasoning. Any finding that survives verification blocks the merge.

## Ground rules

- **Work in a git worktree**, never the daemon's tree. The daemon imports from the
  working tree, so an experimental `seniority.py` in the primary checkout would demote
  real rows on the next pass. `main` stays checked out and untouched at the primary path;
  the daemon keeps running throughout.
- **One branch + one PR per phase.** Cut from `main`, `--base main` explicitly, claim it
  with a `PROGRESS.md` In-flight entry, remove the entry when it lands.
- **Verify gate is DEVELOPMENT.md §5**: worker code -> `make test-worker`, logic changes
  also `make test-coverage` (floor 85). Paste the output into the PR.
- **Stop conditions.** Any of these ends the run and reports rather than continuing:
  quota ledger reaches 60; `make test-worker` red; an eval gate fails on a change (that
  change simply does not ship); the daemon logs a traceback or a breaker trip.
- **Out of scope while the operator is away** — all three are irreversible or theirs to
  call, and are recorded rather than done: the age-TTL sweep (terminally deletes ~5,300
  rows over 30 days), dropping watchlist boards (intake policy, and `config.yaml` is
  operator data), and persisting demotion evidence (needs a `schema.prisma` change and
  `make db-push` against the live DB).

---

## Phase 0 — Isolated worktree (free, ~15 min)

**First commit of Phase 0: copy this plan to
`docs/superpowers/plans/2026-07-31-quota-levers-caching-and-vetoes.md`.** DEVELOPMENT.md
§7 makes the repo the handoff medium — a plan that lives only in `~/.claude/plans/` is
invisible to every other session and lost if this one dies mid-run.


The five inputs the evals need are gitignored, so a bare worktree cannot run them
(`.gitignore` lines 3, 17, 20, 32).

1. `git worktree add <worktree-path> -b <branch> main`
2. Symlink from the worktree back to the primary tree:
   `apps/worker/config.yaml`, `apps/worker/resume/personal_profile.txt`,
   `apps/worker/resume/resume_*.txt`, `apps/worker/eval/`, and `db/`.
3. **Validate:** `make test-worker` green in the worktree, and
   `cd apps/worker && PYTHONPATH=. python3 tools/seniority_eval.py --selftest` passes
   (it asserts the corpus loads and every rule/veto still holds).

> **The isolation is CODE-ONLY, and step 2 is why.** `db/` and `apps/worker/eval/` are
> symlinks back to the primary tree, so anything run inside the worktree writes to the
> **live** database and the **live** eval artifacts. The worktree stops experimental code
> from being imported by the daemon; it does not sandbox data. Every command in this plan
> that touches the DB must be read-only (`mode=ro`), and see the `--build-corpus` warning
> in Phase 3 for the concrete instance where this bites.

**One worktree per concurrent track, not one for the whole run.** DEVELOPMENT.md §7 says
never switch branches while a long run is in flight, and a single shared worktree forces
exactly that whenever two phases overlap. Phase 3's GPU run and the Phase 1/5 doc work
each get their own.

---

## Phase 1 — Restore prefix caching — CLOSED, DO NOT EXECUTE

**There is no cache to restore on the installed CLI.** Everything below was written
against codex-cli 0.144.x. On 0.146.0, Phase 1b measured `cached_input_tokens = 0` on
*both* arms of the controlled probe: nothing caches, so the `-C` change has nothing to
fix and there is no headroom to reclaim. The stable-`-C` lever was not shipped, and the
6-call probe budget below buys a result that is already known. Read 1a's figures as a
description of a CLI that is not installed, never as current headroom; the full negative
is in [`../notes/2026-07-31-quota-ledger.md`](../notes/2026-07-31-quota-ledger.md).
The per-token billing finding that motivates the *rest* of this plan is unaffected — that
one reproduced.

### 1a. Forensics first, before spending (free) — the 0.144.x measurements

The 212 rollouts predate the current invocation: `--ephemeral` suppresses rollout files,
and the newest on disk is 2026-07-29 even though the daemon has fit-scored since. So the
59/212 hit rate describes an *older* invocation and had to be re-verified, not quoted.

Result, over the 158 of those that are production fit calls (identified by the random
`/tmp/tmpXXXXXXXX` cwd):

- **Every hit cached exactly 11,008 tokens.** One value, 42 times; `11008 = 86 x 128` and
  OpenAI caches in 128-token blocks. 10,893 chars sit before `<environment_context>`, so
  this is the divergence point, exactly where the random cwd lands.
- **Hit rate 27%**, and **positions 0-5 of every burst miss 100% of the time** (0/27)
  under `score_workers=4`. Gap-to-previous-call does not separate hits from misses (HIT
  median 4.9s vs MISS 4.0s), so this is not a cache-TTL story.

So there are **two** defects, not one, and the second is worth ~7x the first. Phase 1
carries both.

### 1b. Controlled paid probe (6 calls)

Because `--ephemeral` suppresses the rollout that carries the token accounting, the probe
drops it — deliberately, for measurement only. Two consequences to handle rather than
discover:

- **`--ephemeral` is hardcoded** (`backends_codex.py:132`), so the "current code path" arm
  is already a patched build. It is a valid control for the *ceiling* question because
  both arms are patched identically apart from the cwd, but it is not literally production.
- **Dropping `--ephemeral` leaves the résumé + JD prompt on disk** in the rollout — the
  exact reason `:127-131` made it unconditional. **Delete the 6 probe rollouts as the last
  step of 1b**, and treat that as part of the probe, not cleanup to do later.

Run **sequentially**, not concurrently, and only in a window with no scheduled pass in
flight — the daemon's own calls share the same 11,008-token prefix and would warm it
underneath the control arm.

- 3 calls, same JD, random `-C` (current shape), no `--ephemeral`.
- 3 calls, same JD, fixed `-C` directory, no `--ephemeral`.

Read `payload.info.last_token_usage.cached_input_tokens` from each rollout.

**Success criterion — this probe tests the CEILING, not the hit rate.** The hit rate can
only be measured over a real pass. Expect:

- random-`C` arm: `cached_input_tokens` = **11,008** on calls 2-3 (the measured cap), or 0
  if nothing warmed;
- fixed-`C` arm: **> 11,008**, ideally ~16,500 — everything except the per-JD payload.

A fixed arm that also caps at exactly 11,008 means the cwd is not what bounds the prefix;
record that and **stop Phase 1c** rather than shipping a change with no measured effect.

### 1c. Implement — two changes, not one

**(i) A stable `-C`.** In `backends_codex.py`, split the two uses of the temp directory
that are currently one:

- **Keep** `tempfile.TemporaryDirectory()` for `schema.json` / `out.json` — those must
  stay per-call unique because `score_workers=4` runs four calls concurrently
  (`pipeline.py:966`).
- **Change** only the `-C` argument (`:133`) to a single fixed, empty, mode-0700 directory
  created once under `~/.cache/ats-worker/`, so the `<cwd>` echoed into the prompt is
  identical on every call.

Preserve the property the docstring names: `-C` exists so no repo context leaks into a
score. The fixed dir must stay **empty**, must not sit inside the repo, and **no ancestor
directory may contain an `AGENTS.md`** (codex walks upward). Verified free at plan time:
the `~/.cache/` chain is clean. Assert it at creation and fail loudly rather than silently
scoring with repo context in the prompt.

**(ii) Warm the prefix before fanning out.** Positions 0-5 of every burst miss the cache
without exception, which is `score_workers=4` racing with nothing populated. Issue the
pass's **first** fit call serially, then fan out the remainder to the pool. Costs one
call's worth of wall-clock per pass and nothing in quota. This is the change worth ~50%;
(i) alone is worth ~7%.

### 1d. Validate

- Re-run the 1b probe against the patched code (reuse those calls; do not double-spend).
- `make test-worker` + `make test-coverage`.
- Two tests. First: `-C` receives a stable path across two successive `fit()` calls while
  the schema/out paths differ. The existing codex tests monkeypatch
  `score.subprocess.run` with a `_fake_codex(capture=...)` helper that already records
  `cmd` (`tests/test_score.py:1491-1509`), so this is an assertion on `cmd`, not new
  scaffolding. Second: the fan-out issues its first call before the pool starts.
- **Measure the hit rate over a real pass** after merge — the probe cannot. Compare
  `cached_input_tokens` across one full daemon pass before and after.

### 1e. Land

SPEC §7.1 (the codex backend's invocation and its caching property) + CHANGELOG +
PROGRESS in the same commit. PR, review subagent, merge if clean.

---

## Phase 2 — Trim harness overhead (~1h, <=2 calls)

`--ignore-user-config` drops `<recommended_plugins>` (356 tok) and — the reason that
matters more than the tokens — makes the paid prompt **hermetic with respect to the
operator's `~/.codex/config.toml`**. Today the fit prompt's content varies with which
plugins happen to be installed on the host, which is an uncontrolled scoring input in a
system that gates everything else on reproducibility.

1. Read `codex exec --help` for what the flag disclaims (auth still resolves via
   `CODEX_HOME`; the `-c` overrides this code passes are on the command line and survive).
2. Add the flag; **1 call** to confirm a valid scorecard still comes back and the
   `-c model_reasoning_effort` / `model_verbosity` overrides still apply.
3. Compare `input_tokens` against the Phase 1 baseline on the same JD.
4. `make test-worker`; update the `backends_codex.py` docstring, SPEC §7.1, CHANGELOG.

`base_instructions` (4,503 tok) and the permissions block (1,967 tok) are inherent to
`codex exec` and are **not** addressable here — the only route around them is the metered
OpenAI API, which trades quota for money and is the operator's call. Record that, do not
build it.

---

## Phase 3 — The seniority vetoes (free, GPU only, ~3h)

Baseline is established and reproduces bit-for-bit: TP 190 / FP 7 / FN 61 / TN 188,
precision 0.964, recall 0.757, demote share 0.442, PASS.

Five candidate changes to `apps/worker/ats_worker/score/seniority.py`.

**Measured by one model run, not five.** All five are pure CODE changes downstream of the
extraction, and the extraction is bit-reproducible at temperature=0/seed=0. So the model
runs **once** over the 446 rows and every candidate — and all 31 combinations — is scored
offline from the stored raw output. The offline scorer asserts baseline parity
(TP 190 / FP 7 / FN 61 / TN 188) before reporting anything; a mismatch means the
reimplementation is wrong and every number under it is void.

| # | change | direction | targets |
|---|---|---|---|
| C1 | `clamp_years` returns `None` when the JD states **no** years figure at all | **both** — see below | Goldman 49596 — JD has no number, model invented `2`, clamp passes it through unchanged (`seniority.py:125`) |
| C2 | exclude cap-scoped and age figures from `stated_years` ("less than N", "up to N", "under N", "fewer than N", "no more than N", "N years of age") | keep | T-Mobile 57300 ("Less than 2 years", and "At least 18 years of age"), CenterWell 57296 ("Less than 5 years") |
| C3 | veto (b) fires only when the model's **raw** years figure is itself below the margin — **not** a raw-for-clamped swap, see below | demote | the rank-bearing half of the 34 clamp misses — clamp lowers a bar, then the lowered value silently cancels a rank the JD does state |
| C4 | widen `rank_stated_in` — **but not to all four ranks**, see below | demote | the 9 Qualcomm `Senior ...` rows where the model normalised to `staff` |
| C5 | title-token rank floor (SCORING §5.7 "not built, deliberately") | demote | 35 of 61 misses carry a rank word in the title |

**Three corrections the pre-merge review of this plan forced, all verified before being
accepted. They are recorded rather than silently patched, because two of them would have
produced a confident measurement of nothing.**

- **C3 as first written was a provable no-op.** The original text said "consult the raw
  years instead of the clamped value at `seniority.py:149`". But `clamp_years` returns
  `None` **iff** its input is `None` (`seniority.py:122-125`), so none-ness is invariant
  under clamping and line 149's `if years is not None` cannot change. Verified directly:
  `raw=12 -> clamped=1`, `raw=5 -> clamped=1`, `raw=None -> clamped=None` — none-ness
  identical in every case. The *phenomenon* is real (clamp lowers a bar below the margin,
  :144 stops firing, :149 then cancels a rank the JD does state), but the fix has to
  compare **magnitude**: fall through to the rank branch when the raw figure is at or
  above the margin even though the clamped one is not.
- **C4 as first written deletes the veto it amends.** Accepting *any* of
  `RANKS = ("senior", "lead", "staff", "principal")` means the word "lead" — which appears
  as a verb in a large share of JDs ("lead projects", "lead a team") — would validate a
  model-invented `principal`. That is precisely what veto (a) exists to stop
  (SCORING §5.7: "a rank the model supplied from nowhere demoted a row with no evidence at
  all"). C4 is therefore narrowed to the **observed normalisation confusion only**: accept
  `senior`/`sr.` as evidence for a model-reported `staff` or `lead`, and nothing else.
  SCORING §9.3's *first* bullet — "widening a floor's vocabulary re-opens the
  false-discard direction, which is the expensive one" — applies to C2 and C4 and is the
  bar they have to clear.
- **C1 is not keep-direction.** Making `clamp_years` return `None` where it returned a
  number bypasses the `return "match"` short-circuit at :149 and falls through to the rank
  branch at :151, which can return `too_junior`. So C1 can *create* demotions, unlike the
  two shipped vetoes that SCORING §5.7 says "can only ever REMOVE a demotion". It gets the
  demote-direction evidence bar, not the keep-direction one.

**Gate (the shipped one, unchanged — do not relax it to fit a result):**
precision >= 0.95, demote share >= 0.40, and **zero** false demotions on a `domain=match`
or notified row. C1/C3/C4/C5 all raise demotions, which is exactly the direction
SCORING §9.3 requires evidence for.

**The out-of-sample step, and the hazard it nearly caused.** The gate is in-sample:
`YEARS_MARGIN`, `SENIOR_YEARS` and both shipped vetoes were fitted on this same 446-row
corpus with no held-out split (the eval's own docstring says so), and the live DB now
carries **478** rows with a Sol seniority verdict.

> **DO NOT run `seniority_eval.py --build-corpus` to get the delta.** It writes
> unconditionally to `apps/worker/eval/seniority_golden.jsonl`
> (`tools/seniority_eval.py:52, 79-106`) with no output-path flag, it selects **all 478**
> rows rather than the ~32 new ones, `apps/worker/eval/` is symlinked to the primary tree
> by Phase 0, and `eval/` is gitignored — so it would overwrite the frozen 446-row
> baseline **in the daemon's tree, unrecoverably**, destroying the very baseline this
> phase's parity check depends on. A backup was taken before any of this ran:
> `apps/worker/eval/seniority_golden.jsonl.frozen-446-backup`.

Build the held-out slice by reading the DB directly into a **separate** file and scoring
the winning combination against it. It is ~32 rows, it proves little alone, and it is the
only out-of-sample signal available.

**A null result ships nothing and is still worth landing** as a measurement in
SCORING §8 ("measured history"), so the next session does not re-derive it.

---

## Phase 4 — Luna A/B read (<=50 calls, only if Phases 1-2 succeeded)

Not a production switch — §8.7 requires a full `make eval-score` run for that, and it is
an operator decision. This is a first read at ~1/10 the usual cost.

- Sample ~50 rows from the 478 that already carry Sol verdicts, **stratified to
  oversample** the 40 `domain=match` and 24 notified rows. Only the Luna half needs
  running; Sol's verdicts are already on disk, which halves the cost.
- Report per-verdict agreement, and the one metric that decides it: **rows where Luna
  says do-not-notify but Sol says `seniority=match` AND `domain=match`.** A missed alert
  is the failure this system cannot absorb; a few points of score drift is not.
- Also record credits consumed, from the rollouts, to confirm the 5:1 ratio holds on real
  JDs rather than on the rate card.
- Deliverable is a written report plus a recommendation. **No default change.**

---

## Phase 5 — Corrections and records (free, ~1h)

1. **The MESSAGE-bound claims. The first draft of this list was wrong in both
   directions** — it named SCORING §8.7, which contains no message-bound claim at all
   (§8.7 argues from agreement and flip-rate and already says "half the *credit* rate"),
   and it missed eight real sites. The verified list, from
   `grep -rniE "message-bound|not token-bound"`:

   | file | line(s) |
   |---|---|
   | `apps/worker/ats_worker/run.py` | 69 (the claim itself; the comment block runs 68-77) |
   | `apps/worker/ats_worker/pipeline.py` | 811 |
   | `apps/worker/ats_worker/score/backends_codex.py` | 49 |
   | `docs/SCORING.md` | 982, 983, 990, 1278, 1500 |
   | `docs/SPEC.md` | 983, 2186 |
   | `docs/superpowers/plans/2026-07-24-long-run-day-runbook.md` | 177 |
   | `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md` | 22 |
   | `docs/superpowers/specs/2026-07-17-codex-quota-bar-design.md` | 11 |

   **`CHANGELOG.md:1566` and `:2740` are history and must NOT be rewritten** — they record
   what was believed when it was written, which is exactly what a changelog is for. The
   two dated design specs are likewise historical records of a decision; annotate rather
   than edit them.

   The accuracy objection to a cheaper model survives on its own evidence; only the quota
   premise was wrong. Add the rate card **with its date** so the next session can tell when
   it has gone stale again. `SCORING.md:986-991` deserves particular care: it already
   flagged message-bound as "a working assumption with no measurement behind it" and named
   the missing instrument. The correction is not "the repo was sloppy" — it is that the
   instrument existed all along in the codex rollout files.
2. **The In-flight seniority entry** says the layer is "shipped, unmeasured in production"
   and that no pass has run with it on. Two have: 04:42 EDT (16 deprioritized, 7
   fit-scored of 40) and 08:44 EDT (9 deprioritized, **34** fit-scored of 40, 6 sent for
   confirmation). 25 rows carry `deprioritized_at`.
3. **New BACKLOG entries** for what this session found but is not doing:
   `[SCORE · XS]` demotion evidence is not persisted — `mark_deprioritized` (`db.py:324`)
   writes only a timestamp, so a live demotion can only be audited by re-running the
   extraction; `[SCORE · M]` the metered-API route as the only way past
   `base_instructions`; `[FETCH · S]` the 18 zero-yield watchlist rows and the age-TTL
   decision, both awaiting the operator.
4. **Check the `capture_usage` diagnostics.** #60 shipped cause-naming on every `False`
   route and the daemon picked it up at the 09:17 restart, so only passes **after** that
   carry a named cause — the 08:50 WARNING predates it and explains nothing.
   `journalctl --user -u ats-worker --since 09:17 | grep -i quota` (not `--since 12:00`:
   that window both excludes 09:17-12:00 and, at the time this step was written, had not
   happened yet). If a WARNING fires with a named cause, record it under Defects; if none
   fires across a pass that actually fit-scored, record that too — a quiet pass that spent
   nothing is not evidence either way, which is the whole reason the WARNING was added.

---

## Sequence and dependencies

```
Phase 0  worktree  (blocks everything)
   |
   +-- Phase 1  caching      1a free -> 1b probe (6) -> 1c(i)+(ii) -> 1d -> PR
   |      |
   |      +-- Phase 2  harness trim  (1 call)    [needs 1's baseline]
   |             |
   |             +-- Phase 4  Luna A/B  (<=45)   [only if 1+2 landed green]
   |
   +-- Phase 3  seniority vetoes  (free, GPU, own worktree — runs alongside 1/2)
   |
   +-- Phase 5  corrections  (free, any time; do 5.4 as soon as a pass has fit-scored)
```

**Quota budget, reconciled to the 60-call cap:**

| | calls |
|---|---|
| Phase 1b probe | 6 |
| Phase 1b re-probe, if the first is ambiguous (allowed once) | 6 |
| Phase 2 | 1 |
| Phase 4 Luna A/B | 45 |
| **worst case total** | **58** |

The first draft said "6 + 2 + 50 = 58, leaving 2 for one re-probe", which was wrong twice:
Phase 1's header said `<=12` while the sequence said 6, and a re-probe costs 6 calls (3
per arm), not 2. Phase 4 is sized to what is actually left rather than to a round number.

**A caution on the unit.** The cap is denominated in *calls*, but the plan's own thesis is
that billing is per *token* — so the call-to-window conversion is not stable across this
run. After Phase 1 lands, credits per call drop by up to 57%, and a Luna call costs about
a fifth of a Sol call. Treat "60 calls" as the operator's authorization verbatim and the
window percentage as an estimate that moves in the operator's favour.

## Verification summary

| Phase | Command | Pass bar |
|---|---|---|
| 0 | `make test-worker`; `seniority_eval.py --selftest` | green; selftest ok |
| 1 | rollout `cached_input_tokens` on 6 probe calls | fixed-`C` arm **> 11,008**; random arm 11,008 or 0 |
| 1 | `make test-worker` + `make test-coverage` | green; worker floor 85 |
| 1 | probe rollouts deleted after reading | no résumé/JD prompt left on disk |
| 1 | post-merge: `cached_input_tokens` across one full daemon pass | hit rate materially above 27% |
| 2 | 1 call returns a valid scorecard; `input_tokens` delta | scorecard valid, tokens down ~350 |
| 3 | offline scorer, baseline parity first | reproduces 190/7/61/188 exactly, else void |
| 3 | gate per candidate and per combination | P >= 0.95, demote >= 0.40, **0** false demotions on domain=match/notified |
| 3 | same gate on the ~32-row held-out slice | reported separately, not gated |
| 4 | Luna vs Sol on the stratified sample | report only — no production change |
| all | fresh-subagent review on each PR | no surviving finding |

## What "done" looks like

Prefix caching measured and either fixed or ruled out with evidence; the seniority vetoes
either shipped behind a green gate or recorded as a measured null; Luna costed on real JDs;
the paid prompt hermetic; and the MESSAGE-bound error corrected at all 13 live sites while
the CHANGELOG and dated design specs keep their historical wording. Quota spend under 60
calls with a per-call ledger. The daemon never ran experimental code, the frozen 446-row
corpus survives intact, and the three operator-only decisions are written up waiting
rather than taken.

## Provenance of this plan

Written 2026-07-31 and revised the same day after Phase 1a's forensics and a
fresh-subagent pre-merge review (DEVELOPMENT.md §7). The review found five blocking
defects: an inert C3, a `--build-corpus` step that would have destroyed the frozen golden
corpus, a credits row for Phase 2 that its own text refuted, a MESSAGE-bound site list
wrong in both directions, and a C4 that deleted the veto it amended. All five were
verified before being accepted, and the reasoning is kept inline above rather than
silently patched out — two of them would otherwise have produced a confident measurement
of nothing. No design spec was written first (DEVELOPMENT.md §3); for follow-on work of
this size that is the step to add.
