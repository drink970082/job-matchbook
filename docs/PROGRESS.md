# ATS — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.

**Current phase:** v0.2.0, **validated live end-to-end.** Feature-set complete;
testing/CI hardened (coverage gates, integration + Playwright e2e, schema-drift
guard). **"Hardened" here means test/CI hardening, not security hardening** — a few
unverified properties remain open (see [Open work](#open-work)). On **2026-07-13**
the full `fetch → screen → score → notify` pipeline ran against live services for
the first time: one cold pass over 39 boards → **1169** postings fetched, **~45%**
screened out (internship/location/visa), **642** fit-scored by Claude with **zero
failures**, **11** matches (score ≥75) delivered to Telegram (~$8 one-time,
~cents/day steady-state; the `recommended_resume` swe/quant_dev pick and the
Telegram `Resume:` line were both confirmed live). The recurring 24h scheduler
(`python -m ats_worker.run`) is the operator's remaining launch step. (Recent
changes: see the [CHANGELOG](../CHANGELOG.md).)

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

✅ **RESOLVED 2026-07-17 — domain rubric redesigned to target-fit; gate now PASSES
100%.** The long saga below is the history; here is where it landed. The fit-score
**domain** verdict was the unstable dimension (a vibe with no criteria — the thing that
flipped on the golden set and bled under batching). It was rebuilt as a **three-check
target-fit rule** (ANTI-TARGETS · TARGET priority from day-to-day work · RÉSUMÉ-evidenced
field) collapsing to match/adjacent/mismatch against the operator's `personal_profile.txt`
(see [SPEC](./SPEC.md) §13 + `CHANGELOG`). `make eval-score` (K=3 × 21 rows, `gpt-5.6-sol`)
went **76% → 100% agreement, hard 10/10, flip-rate 24–38% → 5%**, and a **second consecutive
PASS (95%) cleared the ship-gate**, and the **live backfill ran 2026-07-17 (DONE)** —
all ~630 stored rows re-scored under the new rubric, **0 failures, $0** (parallel `codex`
at concurrency 4 covered the whole queue, ending at 59% of the weekly message budget,
never touching the claude fallback); the queue is now **39 notified · 419 below-bar · 711
discarded**, and the web UI's verdict pills / thin-JD flags are populated. Lone wobbler
across the two eval runs: id 26 (a borderline Aquatic Quant-Researcher
seat that wavers match↔mismatch — research-central, not the clean twin of the stable id 652
it first looked like); it stays within gate tolerance but is a candidate to `mark`
(watch-list) if it flaps a future run. **Two lessons banked:** (1) the "analyst penalty" (build-heavy Analyst/Trading-
Analyst seats scoring `adjacent`) was a **profile** tension, not a rubric bug — the model
faithfully applied POSITIONING's "mostly engineering" bar and read those seats as
analysis-central; the fix was loosening the profile's tier-3 analyst qualifier, and it
*stabilized* the ambiguous NLP row (id 111) that an equivalent **rubric** tweak had
*destabilized into a false-notify*. Fix the source (profile), not the symptom (prompt).
(2) The golden set is not frozen truth — several labels were written under the old
"background" rubric and were **corrected to ground truth** during this pass (125/64 →
mismatch, 26/111 → match as the profile evolved, 813/222 seniority → too_junior from
stated bars). The golden set + profile are **operator-local (gitignored)**, so the
committed artifact is `score.txt`; the eval's validity is tied to the local profile +
labels. **Batching stays dead** (confirmed twice, §13 + [Open work](#open-work)); the
quota problem routes to pacing + the usage tracker. Below: the full history.

🚧 **Codex fit-score backend shipped; gate FAILED on flip-rate in BOTH configs tried —
root cause is the *rubric*, not the backend, and config-spinning is the wrong lever.
Routing half now RESOLVED (2026-07-16): notify (`db.get_notifiable`) and the web
matched/belowbar buckets (`matchedIds()`) route on the stable enum verdicts
(`seniority=match AND domain=match AND NOT insufficient_context`), not the flip-prone
score — the gate no longer sits on the rubric's quantization boundary, so flip-rate is
moot for the routing decision (see SPEC §9). Harness half now RESOLVED too
(2026-07-16): the golden set (`apps/worker/eval/golden.jsonl`) carries
ground-truth `seniority`/`domain` verdicts on every row, and `make eval-score` gates
on **verdict accuracy** — 0 hard-invariant violations (a `hard`+`skip` row must never
come back `match`/`match`), ≥85% per-dimension agreement, <20% verdict flip-rate over
K=3 draws — not the score band (see [SPEC](./SPEC.md) §13). Flip-rate is now measured
on the enum verdicts, which were 100% stable across every draw in both gate runs
below, so the reframed gate is expected to pass where the old band-regression gate
structurally couldn't — not yet re-run under the new definition to confirm. **Batched**
fit scoring (design `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-
design.md`, Part B) **implemented 2026-07-16, but PARKED at `batch_size=1`
(default-off)** — the live acceptance guard FAILED. `fit` is batch-first
(`fit(postings, resumes) -> list[dict]`, one scorecard per input in order; a single
score is `fit([posting], resumes)[0]`); `run_score` screens every `new` row first
(unchanged, per-item) and batch-fits only the survivors, in chunks of `batch_size`
(`--batch-size`/`CODEX_BATCH_SIZE`, **codex-only** — `claude` still loops
one call per posting, its cached prefix already making that cheap); each codex batch
tags every JD block with `job_ref` (the posting id) and realigns results by that tag,
not list position (a missing/duplicate/unknown `job_ref` raises `ScoreError` for the
**whole batch**); and any batch failure — `ScoreError` or any other exception — falls
back to scoring that batch's postings **singly**, so one malformed batch costs latency,
not correctness. All of this is **unit-tested** (alignment, fallback, `batch_size=1`
equivalence). **Live-validated 2026-07-16 — FAILED:** the batched==single verdict-drift
guard (`tools/score_eval.py --batched`, gpt-5.6-sol, `batch_size=10`, 23 golden rows,
Part C/B4) — which asserts batched verdicts match single-scored verdicts on the golden
set — read **19/23 agree**, short of the design's acceptance bar. All 4 drift rows are
on the **domain** verdict — concatenating JDs into one codex call bleeds domain
judgment across batch-mates: id 111 `match/adjacent`→`match/match`, id 125
`match/adjacent`→`match/match`, id 132 `too_junior/adjacent`→`too_junior/match`, id 184
`match/match`→`match/adjacent`. 111 and 125 are gate-eligible and their
`adjacent→match` drift crosses the notify predicate — under batching they'd have been
**wrongly notified** (132 stays not-notified, floored by `too_junior` seniority; 184 is
a `marked` row) — exactly the failure mode this guard exists to catch. Per the design's
rollout rule ("if batched verdicts drift, batching does not ship"), **batching does not
ship**: `run.py`'s `DEFAULT_BATCH_SIZE` is now **1** (was 10) — the validated per-JD
path (one JD per codex exec, no cross-JD context to bleed). The batching code and this
guard stay in place for a future fix (smaller batches / stronger per-JD prompt
isolation); opt back in via `--batch-size`/`CODEX_BATCH_SIZE` once the drift is
resolved. **The quota win this was meant to unlock does not apply at the parked
default** — tracked in [Open work](#open-work).**
**Follow-up 2026-07-17 — the verdict holds, but read [Open work](#open-work) for the
corrected reasoning.** The `--drift-probe` experiment (K=3 per row at b=1/5/10) confirmed
the drift is **real context bleed that scales with batch size** (3/4 → 2/4 → 1/4 rows held
a verdict at b=1 → b=5 → b=10) and closed the "smaller batches" escape hatch: **b=5 is not
a partial fix**, it turns id 111 stably *wrong*. Three corrections to the paragraph above:
the bleed is **not** confined to `domain` (id 132's *seniority* bleeds at b≥5); **id 125
would NOT have been "wrongly notified" by batching** (it reads `match/match` on 3/3 single
draws — unbatched notifies it too, so it is a label-calibration miss in both modes); and
**two of the four drift rows (132, 184) are `marked`** watch-list rows the accuracy gate
excludes, which the guard should never have counted (fixed).
`make_codex_scorer` is built, wired as the default, unit-covered, and **tool-less** (see
[CHANGELOG](../CHANGELOG.md)). Two gate runs, both FAIL (`<20%` flip required), each
`hard 10/10 ✅`:
- `gpt-5.6-sol` / effort `high` / with-tools → **agreement 86% · flip 29%**
- `gpt-5.6-terra` / effort `low` / tool-less → **agreement 76% · flip 38%** (worse)

Two lessons. (1) **terra lost on the golden set** — a synthetic single-prompt probe had
favored it, so the golden set overrode the probe and the default reverted to `sol`. (2) That
second run changed *three* variables at once (model, effort, tools), so it can't cleanly
attribute the regression — a **methodology error** to avoid repeating: change one axis per
gate. Shipping config is now `sol` + effort `low` + tool-less (the low-effort and tool-less
wins are justified independently of the gate — quota + security); **this exact combo is
un-gated**, but see below for why another spin isn't the move.

**Why no more config spins:** every flip in both runs is a draw landing on the rubric band
edge (`sol`→74, `terra`→72), one to three points under the `>=75` notify threshold. The model
does **not** emit a continuous score; it picks a rubric band and emits that band's edge (74
vs ~94, skipping the middle), so **the threshold sits on a quantization boundary the prompt
itself defines** — the least stable point available. The enum verdicts (`seniority`/`domain`)
were **100% stable across every draw**; only the number moved. So the noise is a *lossy
re-encoding of a stable judgment*, and **it would have failed the same way on Claude** (round
2: comparable 24% flip, id=6 68→82 crosses the same seam). Two models, two effort levels,
tools on and off — same failure, same place. **This is exactly the "unmeasurable tuning loop"
round 2 already diagnosed and abandoned.** Real fix is upstream and needs a **design call**:
move the notify threshold off the 74/75 seam · widen the rubric's band edges away from it ·
or **route on the stable enum verdicts instead of the number**.
One row (id=397) is a separate, honest calibration disagreement — stably `near` (68/70/72)
against a `keep` label, no flip involved.

✅ **DONE 2026-07-17 — the live DB re-score ran; the queue now carries the new
rubric + structured scorecard.** All ~630 stored `scored` rows were re-screened +
re-fit-scored (parallel `codex`, concurrency 4, **0 failures, $0**, ended at 59% of the
weekly message budget — the paced hybrid's claude tail was never needed), so the
Below-bar why-cells, verdict pills, and thin-JD/low-context routing are now populated.
Final queue: **39 notified · 419 below-bar · 711 discarded**. The DB was backed up first
(`db/applications.db.bak-*`). The history below (economics, pacing, batching-parked) is
kept for the record; the operator re-run it describes is now complete. The recurring 24h
scheduler remains the only standing launch step.

🗄️ *History (resolved) — the operator re-run this item tracked.* All 6
audited defects (D1–D6) are fixed and on `dev` (see [CHANGELOG](../CHANGELOG.md);
design `docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md`), and
validated **2026-07-14** against the live 1,169-row DB — a free pure-code pass (146 auth
false-negatives recovered, 6 location keeps, 174 bare-foreign leaks now gated) plus a
20-row Claude re-score (measurement-only, not persisted). But the **stored** rows still
carry pre-fix screen verdicts and scores. This re-run is also what **populates the new
UI**: every stored row predates the S2.1 structured `assessment` scorecard and the case-#2
`insufficient_context` flag, so today the Below-bar why-cell falls back to legacy
`reasoning` and case-#2 low-context routing is empty — the verdict pills / thin-JD flag
only light up once rows carry the new `score_detail`. The next scheduled pipeline pass
only reaches *new* postings, so applying the fixes to the existing queue needs an operator
re-run (reset the affected rows to `new`, or a one-off re-score) over the ~640 kept rows.
**The economics inverted 2026-07-16 on the shipped `codex`/subscription backend:**
the pass costs no money — but Plus meters a rolling **5-hour window** (~15–90 messages
on `gpt-5.6-sol`). Unbatched (`batch_size=1`, **the parked default — see
[above](#in-flight)**), ~640 rows is 640 messages and **cannot finish in one window**
(spans 7+). **Correction 2026-07-17:** the observed *binding* limit is actually **weekly**
(codex's own `rate_limits`: `window_minutes=10080`), not the assumed rolling 5-hour window
(a 5h `secondary` may also exist but was null when observed), and codex reports remaining
budget directly — now surfaced by the shipped [codex quota usage bar](../CHANGELOG.md)
(SPEC §7.2). **Pace against the bar's real `used_percent`/reset, not the estimated window
math above.** **The batching win that would have dropped this to ~64 `codex exec` calls
(~10× fewer messages, ~6× fewer input tokens from amortizing the scaffolding prefix
over 10 JDs/call) is unrealized and — as of 2026-07-17 — **permanently off the table:**
the live batched==single verdict-drift guard (`tools/score_eval.py --batched`) ran
2026-07-16 and **FAILED** (19/23 agree), and the `--drift-probe` follow-up **confirmed
real context bleed that scales with batch size** and killed the `batch_size=5` middle
ground (see [above](#in-flight) and [Open work](#open-work)). So the operator re-run
stays on the unbatched, multi-window math **for good**, not until a fix lands.
Parallelism does NOT help either way (the cap is messages, not wall-clock); chunking
across the weekly reset does — which makes pacing against the now-visible weekly budget
(the shipped [usage bar](../CHANGELOG.md), SPEC §7.2) the load-bearing lever. At the cap
Codex hard-blocks and `codex exec` exits 1 with no distinct rate-limit code, so a pacing
script must match stderr text. Still not done automatically (mutates the DB); back up
`db/applications.db` first, and confirm `codex doctor` shows auth ✓ — a mid-pass logout
fails rows loudly (never 0s), but it still wastes the run.

**Profile framework (decided; guides the gitignored `personal_profile.txt`, not yet
finalized).** Governing rule: the **résumé is authoritative for skill / experience
evidence** (what a recruiter sees); the **profile shapes the fit score but never injects a
skill the résumé lacks** — it may push fit *up* (genuine interest — the one legitimate
upward lever, since interest ≠ skill), *down* (honest caveats), or *sideways* (positioning /
direction), nothing more. Corollary: courses and any "no explicit X" gaps are **résumé**
matters (put courses on the résumé; treat a genuine gap as fix-the-résumé signal), not
profile content. **Config vs profile seam:** `config.yaml` serves the machine only —
companies, title_filter, threshold, schedule + the structured hard constraints feeding the
**deterministic** screen gates (degree / auth / clearance / location / internships) — and
stays as-is, *not* dissolved into prose (that would regress the gates); the profile serves
the LLM fit score only, so drop the hard-constraint restatements (auth / location) it
duplicates from config. **The profile holds:** target direction (priority-ordered) ·
anti-targets · factual career stage · self-positioning · genuine interests / motivation ·
honest downward caveats — and **excludes** skills / tech / courses omitted from the résumé,
any inflation beyond the résumé, and hard constraints already in config. Keep it concise +
stable (a cached prefix on every score call).

*Superseded 2026-07-15:* the round-2 "tune the prompt against eyeballed 20-row re-scores"
loop was found **unmeasurable** — the fit score is a ±10–15 noisy readout (id=322 = 35→52,
id=6 = 68→82) with no deterministic assessment→score map, and `temperature`/`seed` are
400-rejected on the `claude-sonnet-5` tier — so it was replaced by a band-regression
harness (`make eval-score`, built + committed; in [SPEC](./SPEC.md) + [CHANGELOG](../CHANGELOG.md);
later reframed 2026-07-16 to gate on verdict accuracy instead of score bands — see
[In flight](#in-flight)).
The four prompt edits it produced **shipped** (`score.txt`, `0de0068`) — the harness read a
24% flip-rate that analysis traced to score *noise*, not a prompt fault (all majority bands
were correct), so it landed on judgment and the harness stays as the standing regression
gate for future prompt edits. The low-variance lever it found (seniority keyed to an objective stated
level) is now the golden set's labeling convention (stated **min ≥ 2 yrs → skip**; "1-3" →
near; "0-2" / ceiling / no-bar → keep-eligible). Full write-up in the eval-harness design doc.

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Two axes:**
*severity* sets the bucket (a shipped defect that loses prepared work ≠ an unbuilt
nice-to-have), and within each bucket items run **easiest → hardest** with an effort tag —
**XS** (~an hour) · **S** (~an afternoon) · **M** (~a day + a design call) · **L**
(multi-day / new dependency / architectural). Blocked items name their blocker.

### Defects — shipped behavior that is wrong (should fix)

- **Telegram notify ≠ web "Matched" tab on thin JDs (low-context divergence)** — `[XS ·
  from the 2026-07-17 scoring-system audit]`. The worker's notify gate
  (`db.get_notifiable`) and the web's `matchedIds()` share a **byte-identical enum
  predicate** (`seniority=match AND domain=match AND NOT insufficient_context`) — but the
  web's *displayed* **Matched** bucket also **subtracts low-context rows**
  (`lowContextIds()` = `LENGTH(TRIM(description)) < 200` **OR** `insufficient_context`),
  whereas the worker notify has **no description-length check**. So a short (<200-char)
  `match/match` JD the model did **not** flag `insufficient_context` (a thin-but-confident
  blurb) **fires a Telegram alert** yet shows under **Low-context**, not **Matched** — the
  "UI ≠ alerts" hazard the SPEC §9 claimed couldn't happen (SPEC now corrected). The eval
  harness doesn't cover this axis (no `insufficient_context`/length in the golden set).
  **Fix (small, but a behavior fork — operator's call):** either add
  `AND LENGTH(TRIM(description)) >= 200` to `get_notifiable` so the worker also holds back
  thin JDs (mirrors the UI; suppresses those alerts), **or** drop the description-length
  signal from the web's low-context exclusion and rely only on the shared
  `insufficient_context` flag (makes thin match/match JDs notifiable + shown in Matched).
  The length-gate mirror preserves current UI behavior; pick per whether a thin-but-
  confident match should alert.
- **`run_score` batch persist trusts `len(cards) == len(chunk)`** — `[XS · latent, from
  audit]`. `pipeline.py` zips `chunk` with `cards`; a backend returning *fewer* cards
  without raising would silently orphan the tail rows (stuck `new`, re-scored next pass).
  Latent only — codex raises on a missing `job_ref` and claude loops one-per-posting, so
  both guarantee length-or-raise today. Cheap defensive guard: `if len(cards) !=
  len(postings): fall back to singles` before the zip.

*(Both surfaced by the 2026-07-17 audit of the verdict-routing scoring system; the audit
also **verified-good**: the enum predicate is identical across worker/web, no numeric-score
routing remains, the screen strictly gates the paid fit call, normalization fails loud on
missing/out-of-enum fields, no failure path defaults to a match, and the domain rule's
match/adjacent/mismatch collapse is total with no under-defined `adjacent`. The
model-authored `summary` riding into the DB + Telegram is a bounded text-only injection
surface — already mitigated by the tool-less codex boundary, tracked under [Unverified
properties](#unverified--unguaranteed-properties--behavior-may-be-fine-but-nothing-proves-it-should-address).
`config.threshold=75` is parsed-but-inert dead config — harmless, documented in SPEC §7.1.)*

The 6 cold-pass defects (D1 auth · D2 location · D3 seniority · D4
plus-skills · D5 location-leak · D6 calibration; 2026-07-13) all shipped — see the
[CHANGELOG](../CHANGELOG.md). D6 closed by *measurement*, not code: D3/D4/D5 de-compressed
the fit scale as an emergent effect (a 20-row sample's 60–74 band collapsed 9→1, 75+ rose
0→6), so no rubric-loosen was needed and the notify threshold stays 75.

### Unverified / unguaranteed properties — behavior may be fine, but nothing proves it (should address)

- **JD prompt-injection can still skew a score (credential leak is closed)** — `[S ·
  low impact; accepted]`. The `codex` backend feeds **untrusted scraped JD text** to what
  is natively an agent, a surface the Claude backend (plain completion, no tools) never
  had. **Closed structurally 2026-07-16:** the scorer runs `--disable shell_tool` +
  `web_search="disabled"`, so the model holds no tool it could use to read
  `~/.codex/auth.json` / `.env` and echo a secret into `summary` (persisted + pushed to
  Telegram). Verified behaviorally — a canary JD ordering `cat <secret>` into the summary
  leaked nothing, and the capability is gone, not merely declined. (The official docs
  claim exec can't be disabled; wrong as of 0.144.4.) **What remains:** a JD could still
  try to talk the model into a *wrong number* ("ignore the rubric, score 99") — the same
  probe also demanded 99 and got 0, and the blast radius is one bogus Telegram alert, not
  a secret. Not worth further work unless a real posting is seen doing it.
- **Stale-mount recovery is unobserved end-to-end** — `[S · needs a live drill]`. The
  `/api/health` probe + Docker `healthcheck` + `autoheal` sidecar are wired, the healthy
  path is confirmed, and the 200/503 logic now has a unit test (`health.test.ts`). Unproven:
  recovery from an *actual* WSL2 stale-bind-mount event — never observed, not unit-testable
  (needs a live event or manual drill). (SPEC §6.)
- **No schema migration path** — `[L]`. `prisma db push` keeps no migration history, so a
  *destructive* change (drop/rename a column) has no backfill or rollback and can lose
  retained `applications` / `status_history` data. Back up `db/applications.db` before
  schema changes. (SPEC §8.)

### Enhancements — not built, optional

- **Batched fit-scoring: the quota win is OFF THE TABLE — bleed confirmed at every batch
  size >1** — `[M · closed as won't-fix pending a fundamentally different approach]`.
  Batching (`fit_fn` chunked via `batch_size`, design Part B) stays implemented,
  unit-tested, and **default-off** (`DEFAULT_BATCH_SIZE=1`). The 2026-07-17 drift probe
  (below) **confirmed real context bleed and showed it scales with batch size**, killing
  the `batch_size=5` middle ground that was the last salvage. The operator re-score of
  the ~640-row live queue therefore stays on the unbatched, multi-window path (~640
  messages, 7+ windows) **permanently, not provisionally** — the ~64-message / ~6×
  input-token win described in the economics passage does not exist to be recovered. The
  only named fix, *stronger per-JD prompt isolation*, is in tension with the win itself:
  on this backend, one-JD-per-call **is** the isolation. **The message-quota problem now
  routes entirely to the usage tracker + pacing** (next item) rather than to batching.
  The code and both guards stay for a future backend that isolates JDs natively.

**Answered 2026-07-17 — was the drift BATCHING (context bleed) or the JD (draw noise)?
BLEED, confirmed, and it scales with batch size.** Built `tools/score_eval.py
--drift-probe` (K=3 per row, one batch size per run via `CODEX_BATCH_SIZE`; SPEC §13) and
ran all three settings (36 codex calls, one window). Rows holding one verdict across K=3:
**3/4 → 2/4 → 1/4** at b=1 → b=5 → b=10 — a clean monotonic gradient. The answer is
**both mechanisms are present, but bleed is real and decisive:**
- **id 111 — bleed.** Stable *correct* (`match/adjacent` ×3) at b=1; **stably _wrong_**
  (`match/match` ×3) at b=5, crossing the notify predicate. A stable wrong answer is
  worse than a flip — it never announces itself. This alone kills `batch_size=5`.
- **id 184 — bleed, cleanest case.** Stable in *both* modes at *different* values
  (`match/match` ×3 at b=1/b=5 vs `match/adjacent` ×3 at b=10). Draw noise cannot
  produce a deterministic mode-dependent shift.
- **id 132 — bleed is NOT confined to `domain`.** Seniority held `too_junior` ×3 at b=1
  but bled to `match` at b=5/b=10 (majority `match/match` — a `too_junior` row that would
  notify). The guard had concluded "all 4 drift rows are on the domain verdict"; that was
  an artifact of its single draw. Its *domain* flip at b=1 is genuine draw noise, exactly
  as its own golden note predicted ("model splits 50/50 (34 vs 70, a full band)").
- **id 125 — NOT a batching victim.** Reads `match/match` on **3/3 single** draws, so
  unbatched scoring notifies it too. The claim that batching "would have wrongly notified"
  it is wrong — it is a stable calibration disagreement with its `adjacent` golden label,
  present in both modes. (Its label note concedes it was "lifted from skip".)

**Two defects found in the `--batched` guard itself** (one fixed, one inherent): it
**counted `marked` rows** — 132 and 184, both watch-list rows the K=3 accuracy gate
excludes, one documented as a 50/50 split — so its `19/23` held them to a stricter
standard than the gate they are exempt from (**fixed 2026-07-17**: marked rows still ride
in their real batches, since their bleed can corrupt a gate-eligible batch-mate, but no
longer decide PASS; gate-eligible drift is `19/21`). And **one draw per row per pass**
structurally cannot separate bleed from noise — that is what `--drift-probe` is for. The
guard's *verdict* (batching does not ship) stands and is now better-founded; its
*reasoning* was partly wrong. Related: [[batching-bleeds-domain-verdicts]].
- **Codex quota usage bar — SHIPPED 2026-07-17** (was "message-quota usage tracker",
  `[M]`). The design corrected two premises of the original plan: codex needs **no**
  homegrown estimator — it reports usage itself (its `/status` `rate_limits`:
  `used_percent`/`resets_at`/`plan_type`, on every response) — and the observed binding
  limit is **weekly** (`window_minutes=10080`), not the assumed rolling 5h window. So the
  scorer captures usage **free** off each scoring call, writes a
  `codex_usage.json` snapshot to the shared db mount, and the web renders a bar on the
  Discovered Jobs view (`CodexUsageBar` + `app/api/codex-usage`). It's a budget indicator
  (last scoring call, not live — a live reading would cost a message). **Dropped as
  unneeded:** the JSONL call-counter, the exit-1 + stderr "capped" fingerprinting, the
  Prisma-table/log-location fork (one shared-mount file, no schema change), and the active
  pacing gate (YAGNI — the bar makes hand-pacing operable; revisit only if unattended
  multi-window re-scores become routine). **Capture mechanism corrected 2026-07-17 (v1
  shipped broken):** the first cut read `codex exec --json` stdout, but `--json` streams
  only thread/turn/item events — **not** `rate_limits` (verified 0.144.5). The figures live
  only in the session rollout, which `--ephemeral` suppresses. Fixed: the scorer drops
  `--ephemeral` when capturing, reads the rollout it just wrote, then deletes it (assumes
  sequential scoring). Proven correct by the 2026-07-17 live re-score (~30 rollout reads,
  0 misses). See CHANGELOG + SPEC §7.1/§7.2, design
  `docs/superpowers/specs/2026-07-17-codex-quota-bar-design.md`. [[codex-scorer-gotchas]]
- **`posted_at` for dateless boards** — `[S · accepted limitation]`. Pinpoint exposes no
  board date, so `posted_at` falls back to the scrape date for Pinpoint (and any dateless
  row). No fix unless a board adds a date — documented, low value.
- **More board adapters** — `[M · pick a target]`. The adapter pattern (`fetch/<source>.py`
  + `ADAPTERS`/`VALID_SOURCES`, or `fetch_one` in `DETAIL_SOURCES`) makes new sources cheap;
  JobSpy noted as a possible fallback aggregator.
- **Fit-score noise is unfixable on the shipped backend** — `[M · accepted limitation;
  revisit only if the harness fails]`. The ±10–15 score noise (id=322 = 35→52, id=6 = 68→82)
  has **no** off switch now: `claude-sonnet-5` 400-rejects `temperature`/`seed`, and the
  shipped `codex` backend exposes neither (only `model_reasoning_effort`, pinned `high`).
  The 2026-07-15 plan to buy determinism via the OpenAI **API** was dropped when the
  operator chose the flat-rate **subscription** (2026-07-16) — cost beat determinism, and
  the API's lever was best-effort anyway (`seed` is documented as best-effort; reasoning
  models reject `temperature`). So score stability is now a *measured* property, not a
  guaranteed one: `make eval-score` (majority-of-K=3 verdicts, reframed 2026-07-16 — see
  [In flight](#in-flight)) is the only thing standing between the noise and a wrong
  routing decision. If it starts failing, the escape hatch is
  raising K or `--score-backend claude`, not a seed. **Note (2026-07-16):** the noise
  itself is unchanged, but it no longer *gates* anything — notify and the matched/
  belowbar buckets route on the stable enum verdicts, not the noisy score (see the
  first item under [In flight](#in-flight)), so this item is now scoped to display/
  ranking fidelity, not routing correctness.
- **Deployment / monitoring** — `[L · open-ended]`. `ats-web` has a DB-reachability
  healthcheck + `autoheal` (SPEC §6), but there's no metrics/alerting beyond the per-job
  Telegram notification, and the **worker** has no healthcheck — its failures show only in
  the DB/logs.
- **Headless-browser fetch (Playwright)** — `[L · new dep; unlocks the two below]`. iCIMS
  (~42, "Human Verification" bot wall) and ByteDance/TikTok (~85, JD only in client-side
  Next.js flight data) both need a real browser. Plan: an *optional*, config-gated Playwright
  `fetch_one` path (headless Chromium) kept isolated so the requests-only adapters + core
  pipeline stay dependency-light — render, then reuse per-source extractors (iCIMS
  `window._jibe`, ByteDance position data). Each source its own spec.
- **Remaining feed coverage (the `feed_unresolved` long tail)** — `[L · blocked on
  headless]`. Tier 1 landed (greenhouse-EU host, Oracle, Workable, Jobvite,
  embedded-greenhouse + a detail-fetch robustness framework that records failures loudly),
  lifting resolution ~67% → ~78%. What's left is iCIMS + ByteDance (need the headless path
  above). **Dropped:** greenhouse embed-token (job id only, no board slug); SuccessFactors
  (absent from feed). (Full 2026-06-18 platform breakdown in git history.)
- **AI fetch+score fallback for unparseable JDs** — `[L · blocked on headless]`. Where text
  extraction fails (JS-rendered / bot-walled / odd markup), let Claude fetch the job page and
  score fit directly from the raw page, bypassing parse-then-score. Candidate landing spot
  for the iCIMS/ByteDance tail if the headless fetch alone isn't enough.
- **External reference — `github.com/MadsLorentzen/ai-job-search`** — `[reference · mine,
  don't adopt wholesale]`. A Claude-Code-native, human-in-the-loop application *framework*
  (skills + slash commands + LaTeX CV/cover-letter gen, flat-file state, no backend) — the
  mirror image of our automated `fetch → screen → score → notify` pipeline, so nothing is
  drop-in. Four pieces worth mining:
  - **Their fit rubric (`04-job-evaluation.md`) cross-checks our `score.txt`:** 5 explicit
    dimensions (Technical 30% · Experience 25% · Behavioral 15% · Career-alignment 30% ·
    Location = hard pass/fail) with named bands (Strong 75+ / Good 60 / Moderate 45 / Weak 30).
    Confirms two of our choices — location as a separate deal-breaker, and a career
    "energize vs. drain" filter ≈ our TARGET/ANTI-TARGETS. **But a weighted-average-of-5-
    subscores would multiply band edges** — the exact quantization-boundary noise the fit-rubric
    design call is trying to move *off* (see [In flight](#in-flight)). A fork to weigh, not a copy.
  - **Their `/rank` independently validates "batching is dead" (above).** Its "batch scoring"
    is **N parallel agents, ~5 jobs each, every job scored from its own fetched content** —
    isolated contexts, never concatenated JDs. A second project landing on isolate-don't-
    concatenate corroborates [[batching-bleeds-domain-verdicts]]. Their triage-vs-authoritative
    split (cheap posting-only score; full eval re-runs on apply) ≈ our screen-vs-score split.
  - **Sources: only LinkedIn is worth taking.** Their LinkedIn public `jobs-guest` endpoint
    (unauthenticated, zero-dep, location as a flag; personal-use / ToS caveat, keep volume low)
    is a viable new adapter — folds into **More board adapters** above. Their Danish boards and
    freehire.dev are not for us; **the source strategy stays the universal codex/claude scraper,
    not per-board CLIs** (operator call).
  - **Fetch hygiene worth mirroring:** "a dead / redirected / expired posting is marked
    `expired`, never scored from the title." Their CI `security_guards.py` (asserts no
    secrets / PII committed) echoes [[user-security-privacy-prefs]] — a small privacy-guard test
    alongside `check_schema_drift` is a cheap future option.
  - *Skip:* LaTeX/CV gen, `/setup`·`/interview`·`/upskill`, salary tool, `/html-report`, the
    no-DB architecture — out of scope or already done better here.

---

## How to update

This file tracks only *movement*; it should never accumulate a wall of finished
items. When state changes:

- **Starting work** → add a 🚧 line under [In flight](#in-flight).
- **Closing a gap / shipping a feature** → remove its line here, add a
  [`CHANGELOG.md`](../CHANGELOG.md) entry (history), and update the matching section
  of [`SPEC.md`](./SPEC.md) (the capability map / behavior) — **all in the same
  commit**.
- **Discovering a new gap** → add it to [Open work](#open-work) in the right severity
  bucket, placed **easiest-first** with an effort tag (`[XS/S/M/L · blocker]`). Keep
  severity honest: defects (broken) above unverified properties above enhancements
  (optional).
