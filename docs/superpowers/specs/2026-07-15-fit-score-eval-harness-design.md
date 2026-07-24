# Fit-score prompt: band-regression eval harness

**Date:** 2026-07-15 · **Status:** shipped 2026-07-15 (v1.0.0) — `tools/score_eval.py`, `make eval-score`
**Supersedes the ad-hoc loop** described in PROGRESS.md "Scorer-prompt refinement
round 2" (the paid full re-score + human eyeball pass).

## Problem

Refining `apps/worker/ats_worker/prompts/score.txt` currently means: edit the
prompt → pay for a Claude re-score of a ~20-row sample → **re-decide the truth of
all 20 rows by eye** → repeat. Three things make that loop bad:

1. **The target is never written down.** "id=322 should be a near-miss" lives only
   in the operator's head, so every pass re-spends both a paid API call *and* a full
   human re-read to re-derive it.
2. **The signal is noisy.** The fit call runs `thinking={"type":"adaptive"}` with no
   `temperature`/`seed` (that tier rejects them — 400), so scores swing ±10–15
   run-to-run on borderline rows (round-2: id=322 = 35 then 52; id=6 = 68 then 82;
   id=64 = 76 then 62 — same prompt, same row). Chasing exact numbers is chasing noise.
3. **Confounded changes.** Round-2 moved the prompt *and* the profile together, so the
   score drop couldn't be attributed to either.

The result is a loop that feels infinite: optimizing a noisy number toward a target
that was never recorded, paying full price for the measurement each time.

## Governing decisions

These were settled in brainstorming (2026-07-15) and drive the whole design:

- **Truth = a keep/near/skip band, not the exact score.** You can't overfit a 3-way
  bucket the way you overfit a number, and bands survive the ±15 noise. The exact
  number is treated as noise we do not optimize.
- **The judge is code against frozen labels** — not a fresh human read and not an LLM
  critic (an LLM judge would just re-import the noise). The human labels once; every
  run after that, code decides pass/fail and the human reads only the disagreements.
- **Anti-overfit = a frozen regression guard that grows from live surprises.** ~20
  labeled rows, frozen; you don't "optimize to" it, you keep the prompt *rules*
  general and the set only fires when a change breaks a case you already reasoned
  through. When the live pipeline later emits a surprising score, label that row and
  append it — the set drifts toward the real distribution with no upfront marathon.
- **K = 3 runs per row.** Take the majority band (robust to one bad draw) and measure
  the flip-rate (how often the 3 disagree) — the cleanest signal of prompt fragility.
- **Change exactly one variable per pass** — a general prompt *rule* XOR the profile,
  never both. Directly fixes the round-2 confound.
- **Scorer stays `claude-sonnet-5` (production model).** The eval model MUST equal the
  production model or the eval measures the wrong thing (same reason we rejected
  "iterate on Haiku"). Because `make_claude_scorer` is dependency-injected, the harness
  stays provider-agnostic; if the flip-rate ever proves the noise is genuinely
  blocking, the provider can be revisited then (e.g. an OpenAI model via API, whose
  `seed`+`temperature=0` could cut the noise) — deferred, nothing migrated now.

## Architecture

Three artifacts. That is the whole system.

### 1. The labels file — `apps/worker/eval/golden.jsonl` (gitignored)

The one valuable, durable artifact. Personal data (real postings by DB id + real
résumé/profile context), so `apps/worker/eval/` is added to `.gitignore` alongside
`resume/`, `db/`, `.env`, `config.yaml`. One JSON object per line:

```jsonl
{"id": 151, "band": "keep", "hard": true,     "note": "Quant SW Developer — dead-center target #1, no YoE bar"}
{"id": 132, "band": "skip", "hard": true,     "note": "Quant Dev — '2+ yr' floor (min>=2 rule)"}
{"id": 1158,"band": "near",                   "note": "Quant Dev — '1-3 yr' range (min 1), mild stretch"}
{"id": 824, "band": "skip", "hard": true,     "note": "Platform Engineer — infra-platform anti-target"}
{"id": 184, "band": "keep", "marked": true,   "note": "SWE Fund Admin — insufficient context; watch-list only"}
```

- `band` — the operator's keep/near/skip call. **Truth.**
- `hard` — `true` = a mismatch here is an automatic FAIL (the explicit-YoE floors, the
  obvious mismatches — invariants that must never regress). Omitted/`false` = a soft
  disagreement: counted toward the agreement %, but a couple are tolerated as noise.
- `marked` — `true` = a row the operator **cannot confidently judge** (ambiguous JD,
  not enough context). Provisionally banded, but **excluded from the PASS gate** (not
  counted in agreement %, never a hard invariant) and instead printed in a separate
  **⚑ watch list** so drift is visible without pass/failing the prompt. Also the home
  for "grow from surprises" rows not yet adjudicated.
- `note` — human-readable why (also the audit trail for future-you).
- JSONL so *growing from a live surprise* is literally appending one line.

**Score→band mapping** reuses the existing rubric boundaries — **no new thresholds to
invent**:

| model score | band |
|---|---|
| ≥ 75 | keep  (= the notify threshold) |
| 60–74 | near (= the rubric's "partial fit") |
| < 60 | skip |

**Seed = a fresh, stratified 23-row set (labeled 2026-07-15), not the old 20-row
sample.** Drawn from the ~642 screen-passed rows, stratified by (stored band ×
role-archetype) to guarantee coverage of every family plus the boundary, and
force-including the highest-value regression cases: the infra-platform anti-target
(id=824, the "'platform' ≠ infra platform" case) and the explicit-YoE floors. Final
split **keep 5 · keep-marked 1 · near 8 · skip 9**.

**Labeling convention — the seniority floor is objective, keyed on the JD's stated
*minimum* years** (the low-variance lever; everything else stays a judgment call):

| stated minimum required YoE | band contribution |
|---|---|
| 0 — incl. "0-2 yrs", "up to N" ceilings, or no bar | keep-eligible (new grad fits) |
| 1 — e.g. "1-3 years" | near (mild stretch; candidate sits at the floor) |
| ≥ 2 — "2+", "min 2", "3+" | **skip (hard)** — real gap for a sub-2-year candidate |

The final band still combines this with domain/must-haves (e.g. id=26 clears the YoE
floor via a min-0 ceiling but lands `near` because its domain is a research seat —
adjacent per builder-not-researcher). This convention is currently encoded in the
**labels only**; the prompt's floor still keys on "3+" as its example, so the first
baseline run is expected to flag 132/666 as prompt-vs-label disagreements — that
disagreement is the signal to tighten the prompt (see the queued edit in PROGRESS).

### 2. The harness — `apps/worker/tools/score_eval.py` (committed, generic, no personal data)

Reuses the exact production wiring, **read-only — never writes the DB**:

1. `env = run.load_env("apps/worker/.env")` → `ANTHROPIC_API_KEY`.
2. `resumes, profile = run.load_resumes("apps/worker/resume")`.
3. `score_fit = score.make_claude_scorer(key, "claude-sonnet-5", profile=profile)`.
4. Read each labeled `id` from `db/applications.db`:
   `SELECT job_title, company_name, description, location FROM job_postings WHERE id=?`
   → the `posting` dict `score_fit` expects.
5. For each row, call `score_fit(posting, resumes)` **K=3×**, each through
   `score._normalize_score` → an int score → bucket to a band.
6. Per row: majority band; `flip` = the 3 bands weren't unanimous; `ok` = majority band
   == label (and, for `hard` rows, this must hold). `marked` rows are scored the same
   way but routed to the watch list, not the gate.
7. Tally over the **non-marked** rows: overall agreement %, hard-invariant violations,
   flip-rate. Print one verdict line + a separate **⚑ watch list** of the `marked` rows
   (their majority band each run, no pass/fail). Write the full table to
   `apps/worker/eval/last_run.md` (gitignored, same shape as the existing `rescore_*.md`).

Stdlib only (`sqlite3`, `json`, `statistics`, `collections.Counter`) — `anthropic` is
already in the venv. **Zero new dependencies.** Run with `apps/worker/.venv/bin/python`
(has the SDK). Target ~100 lines. Invocation gets a `make eval-score` target.

Example output:

```
id   human  runs            maj    flip  ok
904  skip   skip,skip,skip  skip    -    ✓  (hard)
177  skip   skip,skip,skip  skip    -    ✓  (hard)
322  near   near,near,skip   near   ⚠    ✓
427  keep   keep,near,keep   keep   ⚠    ✓
...
agreement 18/20 · hard 6/6 · flip-rate 15% → PASS
```

### 3. The stopping rule (written, so the loop terminates)

A candidate prompt **PASSES** when, on **two consecutive runs**:

| gate | value | why |
|---|---|---|
| hard-invariant violations | **0** (mandatory) | floors are non-negotiable |
| overall band agreement | **≥ 85%** | leaves headroom for irreducible noise — do NOT demand 100% |
| flip-rate | **< 20%** | a prompt that flips a lot is fragile |
| consecutive passes | **2** | one pass can be luck |

Agreement/flip/hard are computed over the **22 gate-eligible rows** (23 seed − 1
`marked`); the `marked` watch list never counts toward pass/fail. Two consecutive
passes because a single pass can be a lucky draw of the noise.

## The loop (replaces the current one)

1. Change **exactly one variable** — a general prompt *rule*, or the profile, never both.
2. `make eval-score` (60 calls ≈ cents).
3. Read only the ✗/⚠ rows. Three outcomes:
   - model genuinely wrong → adjust a *general* rule (not a per-row patch), goto 1;
   - the label was wrong → fix the label (rare);
   - it merely flipped → that row is inherently ambiguous; note it, **don't chase it**.
4. Meets the stopping rule on two consecutive runs → ship; move the PROGRESS.md item to
   CHANGELOG + SPEC per the docs discipline.

## Cost model — how it kills the two named failure modes

- **"Least paid API / least human."** The *judge* is now free code against frozen
  labels, not a paid call + a full human read. Human cost = label-once + read-only-the-
  diffs. API cost = a fixed **60 calls per candidate prompt** (~cents; production itself
  is already ~cents/day), and only when a variable actually changed — cache prior runs,
  don't re-score an unchanged prompt.
- **"Infinite loop on a small batch."** The stopping rule is a written, code-checked
  gate that *tolerates noise by design*, so the agent optimizes the aggregate metric and
  halts instead of chasing rows below the noise floor. Overfitting is bounded because
  edits are to general rules and the `hard` invariants pin the already-reasoned cases.

## First payoff

Run the harness once on the **current uncommitted round-2 `score.txt`** to get an
objective PASS/FAIL — replacing the confounded eyeball comparison that left round-2
unresolved. Then flip *one* variable at a time (old profile vs new; edits on vs off) to
finally answer "was it the prompt or the profile?"

## Out of scope (deliberately not built)

- A dev/holdout split — too few rows to be statistically meaningful; the regression-
  guard + grow-from-surprises model is the anti-overfit mechanism instead.
- Any eval framework (promptfoo, DVC, a config schema) — a ~100-line script covers it.
  Add only when the golden set grows past ~50 rows and hand-reading diffs stops scaling.
- Provider migration / `codex exec` — deferred; the scorer stays pluggable so this can
  be revisited on evidence if the flip-rate proves noise is blocking.
- An LLM-as-judge — would re-import the noise the band metric exists to sidestep.

## Implementation & findings (2026-07-15)

Built and exercised. `apps/worker/tools/score_eval.py` + `make eval-score` shipped
(committed); the ad-hoc loop is retired. The `score.txt` edit under test remains
**uncommitted** pending two *fresh* confirmation runs (see status below).

- **Tool robustness.** The production scorer caps `max_tokens=4096`; under adaptive
  thinking the verbose `assessment` notes truncate the JSON mid-string → `ScoreError`,
  which is **not** an SDK-retried transient, so one bad row aborted a whole paid run. Fix:
  the eval scorer uses `max_tokens=8192` (measurement-neutral — the cap changes only
  whether the JSON *completes*, not the model's score) plus a per-draw retry. (Latent prod
  note: production at 4096 can likewise truncate a verbose row and silently mark it failed
  — rare, not fixed here.)
- **Baseline overturned the prediction.** 132/666 already floor correctly (skip/skip/skip)
  — the prompt already handled min≥2, so the "expect 132/666 to disagree" premise was
  wrong. The real failures were near-band: the "1-3 yr" ranges (1158/153/70) were being
  *over*-floored, bimodal skip(~28)/keep(~83) — the worst fragility, and the flip driver.
- **Queued edit validated (one variable).** Un-flooring "1-3 yr" ranges (keeping min≥2 as
  the floor) killed the 1158/153/70 bimodality → stable keep; 100% agreement, hard clean,
  flip 19%/10% on two recomputed passes. **Not yet shipped:** the two runs in hand
  *motivated* the relabels below (circular to count them), and run-1's flip margin is thin
  (19%). Ship needs **2 fresh consecutive PASS runs**, then commit `score.txt`.
- **Labeling-convention refinements (ratified this session).**
  - *A min-1 range is keep-eligible for a target domain*, not auto-near. A "1-3 yr" bar on
    a dead-center target role (1158/153/70, all target #1/#2) is a **keep** — the mild YoE
    stretch is dominated by domain fit. Supersedes the seed table's flat "1 → near"; and
    652/26 likewise corrected near→keep as target-list roles (model's keep was right, the
    labels too strict).
  - *A stated YoE bar with an explicit alternative path is NOT a hard floor.* id=132's bar
    is "2+ years **OR** demonstrated excellent skills" — the model reads the escape clause
    correctly and splits 50/50 (34 vs 70, a full band), so the row is genuinely
    un-judgeable → **`marked`** (watch list). Clean floors with no escape — 666 ("minimum
    of 2 years"), 207 ("3+"), 186 (senior) — remain the min-2 hard-invariant guards.
- **Golden set now keep 10 · near 3 · skip 8 · marked 2 (gate 21).** Six labels moved
  after seeing scores (each evidence-based — profile target-list, JD escape clause — *not*
  model-fitting); flagged as an overfit caution, and the near band thinned 8→3
  (grow-from-surprises is the repopulation path).
