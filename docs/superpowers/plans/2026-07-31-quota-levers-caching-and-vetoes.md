# Quota levers: prefix caching, harness trim, and the seniority vetoes

**Status:** approved by the operator 2026-07-31; execution started the same day while
they were away. The quota budget and merge authority below were both given *before* any
work began.

> **For a session picking this up mid-run:** phase order and dependencies are under
> [Sequence and dependencies](#sequence-and-dependencies). Where the run actually *is*
> lives in the `PROGRESS.md` In-flight entry and in the quota ledger at
> `docs/superpowers/notes/2026-07-31-quota-ledger.md` — not in this file. The **stop
> conditions** under Ground rules are binding.

## Context

Quota is the standing priority (operator's call, 2026-07-31). The working assumption
underneath every quota decision in this repo — `run.py:61-71` and
`backends_codex.py:48`, "the ChatGPT-subscription quota is MESSAGE-bound, not
token-bound" — is **factually wrong as of April 2026**. OpenAI moved Codex to per-token
credits (Sol 125 / 12.5 cached / 750 per 1M; Terra 62.5 / 6.25 / 375; Luna 25 / 2.5 /
150 — a clean 5 : 2.5 : 1).

Three things follow, measured this session against the live system:

1. **Only ~36% of what each paid call bills is our prompt.** Mean input is 16,775 tokens
   (212 historical rollouts). Our rubric + profile + 2 résumés + JD is ~6,512 of that.
   The rest is codex CLI harness: `base_instructions` 4,503 tok, `<permissions
   instructions>` 1,967, an agent-team role prompt 460, `<multi_agent_mode>` 46, and
   `<recommended_plugins>` 356.
2. **Prefix caching is broken by construction, and the cause is one line.**
   `backends_codex.py:113` opens a fresh `tempfile.TemporaryDirectory()` per call and
   passes it as `-C tmp`. That random path is echoed back into the prompt inside
   `<environment_context><cwd>/tmp/tmpXXXXXXXX</cwd>`, ~2,730 tokens in — **ahead of the
   entire scoring prefix**. Every call therefore diverges from every other call before
   the rubric even starts, so the ~5,500-token stable prefix is re-billed at full fresh
   rate every time. Cached input is 90% off. Historically only 59 of 212 calls recorded
   any cache hit at all.
3. **The seniority layer's misses are code's fault, not the model's.** Of 61 misses in
   the 446-row eval, 34 come from `clamp_years` taking the minimum years figure across
   the *whole* document (a stray "1 year of experience with Kubernetes" in preferred
   qualifications collapses a real 5-year bar), and 9 from `rank_stated_in` demanding the
   exact rank word the model named ("Senior ..." titles where the model normalised to
   `staff`). 70% of misses, recoverable in code with no prompt or model change.

Estimated credits per call at Sol rates, from measured token counts:

| | credits/call | saving | verdict-quality risk |
|---|---|---|---|
| today (no cache hit) | 2.58 | — | — |
| prefix cache hits | 1.27 | **51%** | **none** |
| harness trimmed | 1.80 | 30% | none |
| switch to Luna | 0.52 | 80% | unproven; §8.7 demands a full eval |

Token counts use ~4 chars/token and are approximate; the 5:1 rate ratio, the 59/212 hit
rate and the tmpdir mechanism are measured.

**Goal of this plan:** claim the two zero-risk levers (caching, harness), fix the two
code-side seniority vetoes behind the existing free eval gate, take a first read on Luna,
and correct the stale MESSAGE-bound claims that produced the wrong conclusion twice.

## Operator authorizations (given 2026-07-31, before this plan was written)

- **Quota budget: up to 60 paid calls (~5% of the weekly window).** Hard cap. A running
  ledger is kept at `docs/superpowers/notes/2026-07-31-quota-ledger.md` and updated at
  every spend. At 60, stop and report — do not spend a 61st for any reason.
- **Merge authority: fresh-subagent review then self-merge**, per DEVELOPMENT.md §7.
  Review gets only the diff, the commits and the PROGRESS entry — never this plan or any
  reasoning. Any finding that survives verification blocks the merge.

## Ground rules

- **Work in a git worktree**, never the daemon's tree. The daemon imports from the
  working tree, so an experimental `seniority.py` in `/home/halcyon/root/ats` would demote
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


The four inputs the evals need are gitignored, so a bare worktree cannot run them
(`.gitignore` lines 17, 20, 32).

1. `git worktree add /home/halcyon/root/ats-work -b <branch> main`
2. Symlink from the worktree back to the primary tree:
   `apps/worker/config.yaml`, `apps/worker/resume/personal_profile.txt`,
   `apps/worker/resume/resume_*.txt`, `apps/worker/eval/`, and `db/`.
3. **Validate:** `make test-worker` green in the worktree, and
   `cd apps/worker && PYTHONPATH=. python3 tools/seniority_eval.py --selftest` passes
   (it asserts the corpus loads and every rule/veto still holds).

Phases 1-2 (codex, spends quota) and Phase 3 (Ollama, free) use different resources and
may interleave; each still gets its own branch.

---

## Phase 1 — Restore prefix caching (~2h, ≤12 calls) — HIGHEST VALUE

### 1a. Forensics first, before spending (free)

The 212 rollouts predate the current invocation: `--ephemeral` suppresses rollout files,
and the newest on disk is 2026-07-29 even though the daemon has fit-scored since. So the
59/212 hit rate describes an *older* invocation and must be re-verified, not quoted.

Classify all 212 by `cached_input_tokens > 0` and correlate against the `<cwd>` path, the
timestamp gap to the previous call, and `cli_version`. Expected: hits cluster where two
calls happened to share a prefix. This decides whether 1b is worth spending on.

### 1b. Controlled paid probe (6 calls)

Because `--ephemeral` suppresses the rollout that carries the token accounting, the probe
drops it — deliberately, for measurement only.

- 3 calls, same JD, current code path (random `-C`), no `--ephemeral`.
- 3 calls, same JD, fixed `-C` directory, no `--ephemeral`.

Read `payload.info.last_token_usage.cached_input_tokens` from each rollout.

**Success criterion:** calls 2 and 3 of the fixed-dir arm report
`cached_input_tokens > 0` (expect roughly 11-13k of ~17k) while the random-dir arm stays
at 0. If the fixed arm also reports 0, the cause is elsewhere (session-level caching,
`--ephemeral` itself, or no caching on this plan) — record it and stop Phase 1 there
rather than shipping a change with no measured effect.

### 1c. Implement

In `backends_codex.py`, split the two uses of the temp directory that are currently one:

- **Keep** `tempfile.TemporaryDirectory()` for `schema.json` / `out.json` — those must
  stay per-call unique because `score_workers=4` runs four calls concurrently
  (`pipeline.py:966`).
- **Change** the `-C` argument to a single fixed, empty, mode-0700 directory created once
  (e.g. under `~/.cache/ats-worker/`), so the `<cwd>` echoed into the prompt is identical
  on every call.

Preserve the property the docstring names: `-C` exists so no repo context leaks into a
score. The fixed dir must stay **empty**, must not sit inside the repo, and **no ancestor
directory may contain an `AGENTS.md`** (codex walks upward). Verify that at creation and
fail loudly rather than silently scoring with repo context in the prompt.

### 1d. Validate

- Re-run the 1b probe against the patched code (reuse those calls; do not double-spend).
- `make test-worker` + `make test-coverage`.
- A test pinning that `-C` receives a stable path across two successive `fit()` calls
  while the schema/out paths differ — that is the invariant, and it is cheap to assert
  with the injected subprocess runner the existing codex tests already use.

### 1e. Land

SPEC §7.1 (the codex backend's invocation and its caching property) + CHANGELOG +
PROGRESS in the same commit. PR, review subagent, merge if clean.

---

## Phase 2 — Trim harness overhead (~1h, ≤2 calls)

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

Five candidate changes, **measured one at a time**, then the winning combination. Each is
a small edit to `apps/worker/ats_worker/score/seniority.py`.

| # | change | direction | targets |
|---|---|---|---|
| C1 | `clamp_years` returns `None` when the JD states **no** years figure at all | keep | Goldman 49596 — JD has no number, model invented `2`, clamp passes it through unchanged (`seniority.py:125`) |
| C2 | exclude cap-scoped and age figures from `stated_years` ("less than N", "up to N", "under N", "fewer than N", "no more than N", "N years of age") | keep | T-Mobile 57300 ("Less than 2 years", and "At least 18 years of age"), CenterWell 57296 ("Less than 5 years") |
| C3 | the rank-cancelling veto (b) consults the model's **raw** years, not the clamped value (`seniority.py:149`) | demote | the rank-bearing half of the 34 clamp misses — clamp lowers a bar, then the lowered value silently cancels a rank the JD does state |
| C4 | `rank_stated_in` accepts **any** of the four rank words present in the text, not only the one the model named | demote | the 9 Qualcomm `Senior ...` rows where the model normalised to `staff` |
| C5 | title-token rank floor (SCORING §5.7 "not built, deliberately") | demote | 35 of 61 misses carry a rank word in the title |

**Protocol per candidate:** apply alone -> `make eval-seniority` (~12 min, zero quota) ->
record the confusion matrix and the FP list in a results table -> revert -> next. Then run
the best-scoring combination.

**Gate (the shipped one, unchanged — do not relax it to fit a result):**
precision >= 0.95, demote share >= 0.40, and **zero** false demotions on a `domain=match`
or notified row. C3/C4/C5 raise demotions, which is exactly the direction SCORING §9.3
requires evidence for.

**One addition, because the gate is in-sample.** `YEARS_MARGIN`, `SENIOR_YEARS` and both
existing vetoes were fitted on this same 446-row corpus with no held-out split (the eval's
own docstring says so). The live DB now carries **478** rows with a Sol seniority verdict.
Build a second corpus from the ~32 rows added since the golden set was frozen and report
the winning combination against it separately. It is small and proves little on its own,
but it is the only out-of-sample signal available and it costs one `--build-corpus` run.

**A null result ships nothing and is still worth landing** as a measurement in
SCORING §8 ("measured history"), so the next session does not re-derive it.

---

## Phase 4 — Luna A/B read (≤50 calls, only if Phases 1-2 succeeded)

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

1. **The MESSAGE-bound claims.** `run.py:61-71`, `backends_codex.py:48-50`, SCORING §8.7,
   and `PROGRESS.md`'s "two moves that are NOT levers". The accuracy objection to a
   cheaper model survives on its own evidence; only the quota premise was wrong. Add the
   rate card with its date so the next session can tell when it goes stale again.
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
   route and the daemon picked it up at the 09:17 restart. The 08:50 WARNING predates it.
   `journalctl --user -u ats-worker --since 12:00 | grep quota` — if a WARNING fires with
   a named cause, record it under Defects; if none fires, say so.

---

## Sequence and dependencies

```
Phase 0  worktree  (blocks everything)
   |
   +-- Phase 1  caching      1a free -> 1b probe (6) -> 1c -> 1d -> PR
   |      |
   |      +-- Phase 2  harness trim  (2 calls)   [needs 1's baseline]
   |             |
   |             +-- Phase 4  Luna A/B  (<=50)   [only if 1+2 landed green]
   |
   +-- Phase 3  seniority vetoes  (free, GPU — runs alongside 1/2)
   |
   +-- Phase 5  corrections  (free, any time; do 5.4 early — it is 5 minutes)
```

Quota: 6 + 2 + 50 = 58 of the 60 authorized, leaving 2 for one re-probe.

## Verification summary

| Phase | Command | Pass bar |
|---|---|---|
| 0 | `make test-worker`; `seniority_eval.py --selftest` | green; selftest ok |
| 1 | rollout `cached_input_tokens` on 6 probe calls | fixed-dir arm > 0, random arm 0 |
| 1 | `make test-worker` + `make test-coverage` | green; worker floor 85 |
| 2 | 1 call returns a valid scorecard; `input_tokens` delta | scorecard valid, tokens down ~350 |
| 3 | `make eval-seniority` per candidate + combination | P >= 0.95, demote >= 0.40, **0** false demotions on domain=match/notified |
| 3 | same gate on the ~32-row out-of-sample corpus | reported separately, not gated |
| 4 | Luna vs Sol on the stratified sample | report only — no production change |
| all | fresh-subagent review on each PR | no surviving finding |

## What "done" looks like

Prefix caching measured and either fixed or ruled out with evidence; the harness trim
landed and the prompt hermetic; the seniority vetoes either shipped behind a green gate or
recorded as a measured null; Luna costed on real JDs; and the MESSAGE-bound error
corrected everywhere it is quoted. Quota spend under 60 calls with a written ledger. The
daemon never ran experimental code, and the three operator-only decisions are written up
waiting rather than taken.
