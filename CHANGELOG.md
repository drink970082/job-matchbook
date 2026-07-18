# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The current
system is described in [`docs/SPEC.md`](./docs/SPEC.md).

## [Unreleased]

### Added
- **Codex quota usage bar (web + worker).** The `codex` fit-score backend now captures
  its own quota usage off each scoring call: it reads codex's `/status` accounting
  (`used_percent`, `resets_at`, `window_minutes`, `plan_type`) from the **session rollout**
  the scoring call writes — for **free** (rides the scoring message, no probe; best-effort,
  never breaks a score) — and writes a latest-wins `codex_usage.json` snapshot in the
  shared db dir. (`codex exec --json` stdout carries only thread/turn/item events, **not**
  `rate_limits` — verified on 0.144.5 — and `--ephemeral` suppresses the rollout, so when
  capturing the scorer drops `--ephemeral`, reads the rollout it just wrote, then deletes
  it; assumes sequential scoring.) A new `app/api/codex-usage/route.ts` serves it (adds
  `as_of` from the file mtime; empty state, not an error, before the first pass) and a
  `CodexUsageBar` renders one bar per limit — `used_percent`, "resets in Nd Hh", "as of" —
  on the Discovered Jobs view. It reflects the **last scoring call**, not a live reading:
  a fresh "now" reading would cost a quota message, the exact resource being tracked.
  Capture runs only on the production `run_once` path (a `usage_path` is set), so the
  eval/test path keeps its byte-identical `--ephemeral` gated call. Replaces the parked
  "message-quota usage tracker" plan: the
  observed binding limit is **weekly** (`window_minutes=10080`), not the assumed rolling
  5-hour window, and codex reports usage itself (via `rate_limits`; the bar also renders a
  `secondary` limit if one appears), so no homegrown call-counter or exit-1 stderr
  fingerprinting is needed. Storage is a single shared-mount file (no Prisma schema
  change). (SPEC §7.1, §7.2; design `docs/superpowers/specs/2026-07-17-codex-quota-bar-design.md`.)

### Fixed
- **`run_score` batch persist no longer trusts `len(cards) == len(chunk)`.** A fit
  backend returning fewer/more cards than postings without raising would have
  zip-misaligned in `pipeline.run_score` and silently orphaned the tail rows (stuck
  `new`, re-scored every pass). A `len(cards) != len(postings)` check now routes the
  chunk into the existing singles fallback, so every posting is scored 1:1. Latent
  today (codex raises on a missing `job_ref`; claude loops one-per-posting), hardened
  from the 2026-07-17 scoring-system audit.
- **Notify gate now mirrors the web "Matched" tab on thin JDs.** `db.get_notifiable`
  gained `AND LENGTH(TRIM(description)) >= 200`, so a short (<200-char) `match/match` JD the
  model did not flag `insufficient_context` no longer fires a Telegram alert while the web
  hides it under Low-context — the two now agree. Surfaced by the 2026-07-17 scoring-system
  audit (SPEC §9 corrected). The `200` is hand-synced with the web
  `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH` (a cross-service constant, flagged in both).

### Changed
- **Domain verdict redesigned from "background" to "target-fit" (`prompts/score.txt`).**
  The old one-line domain prompt ("is their background in this role's domain?") had no
  criteria for `adjacent`, so the verdict was a vibe that drifted (a coin-flip on the
  golden set's borderline rows and the dimension that bled under batching). It is now a
  deterministic collapse of **three checks** recorded in the note — (1) ANTI-TARGETS,
  (2) which TARGET priority (from the role's day-to-day work, not its title), (3) whether
  the RÉSUMÉ evidences the field — against the operator's `personal_profile.txt`. This
  keeps the single `domain` enum (no schema change) but makes the match/adjacent line —
  which the notify predicate turns on — a checkable rule instead of a judgment call.
  **The fit-score verdict-accuracy gate (`make eval-score`, K=3 × 21 rows) PASSES at
  100% agreement / hard 10/10 / 5% flip** under the redesigned rubric (2026-07-17,
  `gpt-5.6-sol`). Flip-rate collapsed from 24–38% (pre-redesign) to 5%. The golden set
  and profile that validate it are operator-local (gitignored), so the committed artifact
  is the rubric; the eval's validity is tied to the local profile + golden labels.
  - **The "analyst penalty" was a profile tension, not a rubric bug.** Build-heavy
    "Analyst"/"Researcher" seats (e.g. a prop-desk Trading Analyst) scored `adjacent`
    because the model applied the profile's POSITIONING ("mostly engineering fits, mostly
    research doesn't") and read them as analysis-central — demoting them below the
    engineering-facing-analyst tier. The fix was in the **profile** (loosen the tier-3
    analyst qualifier to include seats with substantial tooling/pipeline building even if
    analysis-central), not the prompt: a prompt tweak that tried to force it (deliverable-
    based check) backfired — it destabilized an ambiguous row into a false-notify and
    over-corrected another. Same defect, opposite outcomes: fixing the profile *stabilized*
    the ambiguous row (100% agreement), fixing the rubric destabilized it.

### Added
- **Drift probe (`tools/score_eval.py --drift-probe`) — answers whether the batched
  verdict drift is context bleed or draw noise. It's bleed, and it scales with batch
  size.** The `--batched` guard draws each row once per pass, so it structurally cannot
  tell "batch-mates corrupted this verdict" from "this JD is a coin-flip on any re-draw"
  — every drift row was `adjacent`-domain borderline, consistent with either. The probe
  re-draws the 4 drift rows **K=3×** at one batch size per run (`CODEX_BATCH_SIZE`; `1` =
  single/probe-rows-only, `>1` = batched over the **whole** golden set so probe rows keep
  their real batch-mates — scoring the 4 alone would replace the very context under test).
  **Run 2026-07-17 (`gpt-5.6-sol`, b=1/5/10, 36 calls, one window):** rows holding one
  verdict went **3/4 → 2/4 → 1/4**. **`batch_size=5` is not a safe middle ground** — it
  turns id 111 from stably *correct* (`match/adjacent` ×3 single) into stably **wrong**
  (`match/match` ×3), crossing the notify predicate; a confident wrong answer is worse
  than a flip. id 184 is stable in *both* modes at *different* values (noise can't do
  that), and id 132's **seniority** bleeds at b≥5 — so the corruption is **not** confined
  to `domain`. Batching stays parked at `batch_size=1` for good; the quota win is off the
  table via batching (SPEC §11, §13).

### Fixed
- **`--batched` guard counted `marked` rows, holding them to a stricter standard than
  the gate they're excluded from.** Two of its four "drift rows" (132, 184) are
  watch-list rows the K=3 accuracy gate deliberately drops — 132's own golden note reads
  *"model splits 50/50 (34 vs 70, a full band)"* — so its headline `19/23` blamed
  batching for known label noise. `marked` rows now still ride in their real batches
  (their bleed can corrupt a gate-eligible batch-mate, so removing them would weaken the
  test) but no longer decide PASS; they're reported under a separate watch-list heading.
  Gate-eligible drift is **19/21**. The guard's verdict (batching does not ship) is
  unchanged and now better-founded. Also corrected in the docs: **id 125 was never a
  batching victim** — it reads `match/match` on 3/3 *single* draws, so unbatched scoring
  notifies it too; it's a stable calibration disagreement with its `adjacent` label, not
  a batching regression.
- **Codex fit-score backend — the ChatGPT-subscription twin (`make_codex_scorer`),
  now the default.** Fit scoring moves off metered Claude onto the Codex CLI running
  on the operator's ChatGPT subscription: a full ~640-row re-score becomes a
  flat-rate pass instead of a paid one, which is what the cost of re-scoring the
  queue actually turns on. `run.make_scorer` picks the backend
  (`--score-backend`/`SCORE_BACKEND`, `codex` default | `claude`); both twins expose
  the same `score_fit(posting, resumes) -> dict` contract, send the same prompt
  sections (`_scorer_system_sections`, extracted so a prompt edit lands on both) and
  the same JSON schema (`_score_schema` → codex's `--output-schema`), so scores stay
  comparable and the band-regression harness can judge one against the other.
  Each call is one ephemeral, read-only, repo-less `codex exec` turn (`--ephemeral`
  so a 640-row pass leaves no session files; `-C <tmpdir>` + `--skip-git-repo-check`
  so the JD is the only input), with the JSON read back from `--output-last-message`.
  Auth is the operator's `codex login` state, not an env key — `ANTHROPIC_API_KEY` is
  needed only for `--score-backend claude`. A non-zero exit **always** raises
  `ScoreError` and never yields a `0`: codex purges `~/.codex/auth.json` after
  repeated auth failures, so a logged-out cron must fail loudly rather than silently
  score the whole queue 0. `make eval-score` follows the production backend
  (`SCORE_BACKEND=claude` A/Bs the old path), keeping the gate's
  `eval-model == production-model` rule true.
  Runs **tool-less** — `--disable shell_tool` + `web_search="disabled"` — a security
  boundary rather than a tuning choice: a JD is untrusted scraped text and `codex exec`
  is natively an agent whose shell `--sandbox read-only` still lets read *any* file, so
  a posting could otherwise ask it to read `~/.codex/auth.json`/`.env` and echo a secret
  into `summary` (which we persist and push to Telegram). Verified behaviorally with a
  canary JD; also worth **~3.1 k fewer input tokens/call** (12,755 → 9,659). The official
  docs claim exec can't be disabled — wrong as of 0.144.4. Model `gpt-5.6-sol` (the CLI
  default) with `model_reasoning_effort=low`/`model_verbosity=low`. A synthetic probe
  favored `gpt-5.6-terra` (tighter spread, half the credits), but on the golden set terra
  scored **worse** (gate 76%/38% flip vs sol's 86%/29%), so sol stands; `luna` was rejected
  (~3x looser) despite the docs recommending it for classification. Effort buys nothing on
  this task shape but is pinned anyway because the default is server-controlled and was seen
  flipping `low`→`medium`→`low` mid-session; verbosity is a no-op under `--output-schema`.
  **Revises the 2026-07-15 direction on two points, from evidence:** (1) it uses the
  **subscription CLI, not the OpenAI API** — the API was chosen for `seed` +
  `temperature=0`, but `codex exec` exposes neither, so the score noise is **not** fixed
  and the harness, not a seed, is what says whether it moves a band; (2) the "fragile at
  strict JSON" objection is **withdrawn** — `--output-schema` enforces the nested,
  enum-constrained production schema exactly as Claude's structured outputs do (verified
  end-to-end). The "heavy" objection stands, and the real bound turned out to be **quota,
  not latency**: Plus meters a rolling 5-hour message window (~20–110 on terra), so a
  ~640-row re-score spans several windows and parallelism can't help. Each call also pays
  a fixed ~9.7 k input tokens of Codex scaffolding for ~80 tokens of JSON with **zero**
  prompt-cache credit — the opposite of Claude's cached prefix.
- **Fit scorer `insufficient_context` signal (case #2).** The Claude fit scorer now
  returns a top-level `insufficient_context` boolean (schema-required, normalized to
  `False` when absent, persisted in `score_detail`): true when the JD is too thin,
  boilerplate, or truncated to assess with confidence. It routes the posting to the
  **Low-context** bucket independently of the 0–100 score, so a full-length-but-empty JD
  the LLM couldn't judge gets human review rather than a trusted number — complementing
  case #1 (a short JD body). `lowContextIds` unions the two signals
  (`LENGTH(TRIM(description)) < N OR json_extract(score_detail,'$.insufficient_context') = 1`).
- **Batched codex fit scoring — the fit call is now list-in/list-out, and `run_score`
  batches the survivors instead of scoring one posting per call.** `fit(postings,
  resumes) -> list[dict]` (both backends) now takes a **list** of postings and returns
  one scorecard per input, in the same order; a single score is
  `fit([posting], resumes)[0]` — `score_posting`'s own call site, unchanged from the
  caller's perspective. `run_score` (`pipeline.py`) is restructured into three phases:
  (1) SCREEN every `new` posting (Ollama, per-item, unchanged) and persist a
  disqualified one `discarded` immediately — it never reaches the fit call; (2) chunk
  the survivors into batches of `batch_size` (default 10) and make **one** `fit_fn`
  call per chunk — on `codex` this is one `codex exec` scoring up to 10 JDs at once,
  each tagged `=== JOB job_ref=<posting id> ===`, with the schema wrapping results as
  `{"results":[{job_ref,...}]}`; results are realigned to the input postings **by
  `job_ref`, not list position** (an LLM isn't guaranteed to preserve order across N
  items), and a missing/duplicate/unknown `job_ref` raises `ScoreError` for the
  **whole batch**; (3) **safety net** — a batch call that raises `ScoreError` *or any
  other exception* (e.g. a transient `claude`-backend API error surfacing through the
  same call site) falls back to scoring that batch's postings **singly**, so one
  malformed batch costs latency, not correctness, and a single that still fails marks
  only that one row `failed`. `batch_size` is configurable via
  `--batch-size`/`CODEX_BATCH_SIZE` (shipped default was 10, since parked to 1 — see
  below); `batch_size=1` degrades to exactly the pre-batching one-call-per-posting
  path (no special-casing). Batching is **codex-only** — the intended quota win,
  since the ChatGPT-subscription cap is message-bound, not token-bound, and at
  `batch_size=10` a ~640-row re-score would drop from 640 messages to ~64 (10/batch),
  cutting total input tokens ~6× (the fixed scaffolding prefix amortizing over 10 JDs
  per call instead of 1) — **see the outcome below: this win is not realized at the
  parked default.** The `claude` backend still loops one
  call per posting regardless of `batch_size`: its cached system prefix already makes
  the marginal posting cheap, so batching would only save request count, which
  doesn't matter on metered billing. `tools/score_eval.py` gains a `--batched` mode —
  a separate, **live**, quota-spending guard, never run from CI/selftest — that scores
  the golden set once single and once batched and asserts the per-row `(seniority,
  domain)` verdicts are identical (PASS = 0 drift), which is what proves a batch's
  JDs don't corrupt each other's score via context bleed from their batch-mates.
  **This guard ran live 2026-07-16** (gpt-5.6-sol, `batch_size=10`, 23 golden rows)
  **and FAILED — 19/23 agree.** All 4 drift rows are on the **domain** verdict —
  concatenating JDs into one codex call bleeds domain judgment across batch-mates: id
  111 and 125 `match/adjacent`→`match/match`, id 132
  `too_junior/adjacent`→`too_junior/match`, id 184 `match/match`→`match/adjacent`.
  111/125 are gate-eligible and their `adjacent→match` drift crosses the notify
  predicate — batching would have **wrongly notified** them (132 stays not-notified,
  floored by `too_junior`; 184 is a `marked` row). Per the design's rollout rule,
  **batching does not ship by default**: `run.py`'s `DEFAULT_BATCH_SIZE` is **1** (was
  10) — default-off, degrading to the pre-batching one-call-per-posting path — with
  the batching machinery and this guard left in place for a future fix (smaller
  `batch_size` / stronger per-JD prompt isolation). Opt back in via
  `--batch-size`/`CODEX_BATCH_SIZE` once the domain-verdict drift is resolved. Unit-
  tested: `job_ref` alignment, the fallback path, `batch_size=1` equivalence. Design:
  `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`
  (Part B; the batched==single validation is part of Part C).

### Changed
- **Notify and the web matched/belowbar buckets now route on the fit verdicts, not
  the score.** The `>=75` notify threshold sat exactly on the rubric's band-edge
  quantization point — score flip-rate 29–38% across two codex configs (see
  `PROGRESS.md`) — while the `seniority`/`domain` enum verdicts held 100% stable
  across every re-draw. Both sides now gate on one predicate: `seniority.verdict ==
  "match" AND domain.verdict == "match" AND NOT insufficient_context`. **Worker:**
  `db.get_notifiable(conn)` selects `pipeline_status='scored'` rows matching the
  predicate via `json_extract`; `run_notify` drops its `threshold` parameter and no
  longer calls `db.get_by_status(..., min_score=)` for gating. **Web:** a new
  `matchedIds()` raw-query helper (mirrors `lowContextIds()`) returns the matching
  ids; `matched` = active (`scored`|`notified`) ∩ `matchedIds()`, `belowbar` = active
  ∖ `matchedIds()` — the same predicate the worker uses, so the UI and the Telegram
  alert can never disagree. `MATCH_SCORE_THRESHOLD` is **removed** from
  `apps/web/src/lib/constants.ts` (zero remaining references). The fit **score is now
  display/ranking only** — it gates nothing. `config.yaml`'s `threshold:` key and the
  worker's `cfg.threshold` are now **inert** (parsed but unread; left in place for a
  later cleanup). Design:
  `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`
  (Part A; the eval-harness verdict-accuracy reframe is Part C, below — Part B
  batched fit scoring shipped separately, see below).
- **`make eval-score` gates on verdict accuracy, not score-band regression.** Follows
  the routing cutover above: since notify/matched no longer read the score, the harness
  stops judging whether the score reproduces a keep/near/skip band and instead judges
  the thing routing now depends on — the per-dimension `seniority`/`domain` verdicts.
  The golden set (`apps/worker/eval/golden.jsonl`, gitignored) is relabeled with
  ground-truth `seniority` (match/too_junior/too_senior) and `domain`
  (match/adjacent/mismatch) verdicts on every row. `tools/score_eval.py` scores each row
  K=3×, takes the majority verdict per dimension, and PASSes iff: 0 hard-invariant
  violations (a `hard`+`skip` golden row must never come back `seniority==match AND
  domain==match`) **AND** ≥85% per-dimension verdict agreement **AND** <20% verdict
  flip-rate across the K draws — all over the gate-eligible (non-`marked`) rows. The
  derived `match`/`match` notify decision is still reported per row for visibility but
  is **not** the gate, so the accepted recall loss (adjacent-domain keeps) can't fail
  it. Design: `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`
  (Part C), superseding the score→band design in
  `docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md`.
- **Discovered-Jobs bucket taxonomy split + table redesign.** The old `discarded`
  bucket conflated two very different things — hard disqualifications *and*
  below-threshold scored rows — behind a `discardType` (nearmiss/disqualified/all)
  sub-filter. Split into clean, mutually-exclusive buckets: `JobBucket` is now
  **matched · belowbar · discarded · failed · lowcontext**. **belowbar** = live
  (`scored`|`notified`) rows with `score < MATCH_SCORE_THRESHOLD` — *all* of them,
  including deep misses far below the bar, so nothing scored is orphaned;
  **discarded** = disqualified **only** (`pipeline_status='discarded'` with the screen's
  `disqualified:true`) — a below-bar scored row no longer lands here. The old
  `DiscardType` sub-filter is replaced by a disqualification-**cause** filter
  (`DisqualifyCause` ∈ authorization/location/degree/clearance/internship), implemented —
  like `lowContextIds` — as a raw-query id set matching the worker's keyed
  `disqualification_reason` via `json_extract(...) LIKE` the cause pattern, layered as
  `id IN` on the discarded query (and `removeAllInView`). `getJobPostings` /
  `removeAllInView` take `cause?` instead of `discardType?`, and `getJobPostings` now
  returns each row's `created_at` + `posted_at`. `NEAR_MISS_FLOOR` is kept only as a
  documented score-band marker (no longer a query boundary). **Table redesign**
  (`DiscoveredJobsTable`): the bucket tabs (Matched · Below bar · Discarded · Failed ·
  Low-context) moved to their **own row** above the filters; columns folded to Company
  (name + location + source chip) · Role (title + a bucket-aware "why" subline — below-bar
  seniority/domain **verdict pills** (too_junior / adjacent / mismatch, color-coded) + the
  top missing must-have, falling back to the legacy one-line `reasoning` for pre-S2.1 rows;
  the disqualification reason; thin-JD char count; or the pipeline error) · Score (with the
  `recommended_resume` label — SWE / Quant Dev — beneath it) · Dates (Posted / Fetched) ·
  Actions; the cause dropdown replaces the discard-type Select. The per-row dismiss now
  writes `removed` (hidden, like bulk Remove) instead of `discarded`, so the
  disqualified-only Discarded bucket can't be polluted by a hand-dismissed row. Reuses
  existing shadcn/ui tokens and the modal's verdict-pill palette (no new colors).
  Covered by updated unit (`actions.test.ts`), integration (`actions.int.test.ts` —
  belowbar bucket, discarded = disqualified-only, cause filter, created_at/posted_at) and
  component (`DiscoveredJobsTable.test.tsx` — Below-bar tab, cause dropdown, why-cell,
  dates) tests.
- **Round-2 fit-score prompt** (`score.txt`, `0de0068`). Four refinements to how the score
  is reasoned: crisp / de-duplicated `missing` must-haves; `seniority` keyed to an *explicit
  stated level* only (a range starting at 0–1 or a cap is not a bar); credit a capability the
  résumé demonstrates under a different name; never list a requirement structurally impossible
  for the role's own target candidate. Shipped on judgment — the band-regression harness read a
  24% flip-rate that analysis traced to score *noise* (all majority keep/near/skip bands were
  correct), not a prompt fault; the harness stays as the standing regression gate for future
  prompt edits.

### Removed
- **`dealbreakers` from the candidate screen config.** It was the *only* screen
  requirement the local 4B model actually **adjudicated** (a free-text `{pass, note}`
  judgment); every other screen gate — degree, work authorization, clearance, location,
  internships — is decided by **deterministic code**, with the model only *extracting* a
  JOB fact for degree/clearance. Dropping it makes every screen *decision* deterministic.
  Removed the `Candidate.dealbreakers` field + parsing, the `_candidate_block` clause, the
  `_screen_verdict` gate + `_passed` helper, the `SCORE_C_DEALBREAKERS` prompt fragment,
  `screen.txt`'s `c_dealbreakers` section, and the `config.yaml` key. The misleading
  `Candidate` docstring (which claimed the model gives each field a pass/fail verdict) is
  corrected to match the code: `config.Candidate` serves the **screen only** — the Claude
  fit score reads the résumé + profile, never the config.

### Added
- **Low-context tab in Discovered Jobs.** Postings whose JD is too thin to screen/score
  with confidence now get their own bucket instead of being silently scored alongside
  confidently-parsed rows. Detection is *derived at query time* — no schema change, no
  worker change: a single raw `LENGTH(TRIM(description)) < LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`
  query (new constant, default 200) yields the low-context id set, layered as `id IN` on
  the new `lowcontext` bucket and `id NOT IN` on Matched/Discarded/Failed so the buckets
  stay **mutually exclusive**. Scope is the scored/notified rows that actually received a
  fit score; disqualified/failed/applied/removed rows keep their own buckets. New tab in
  `DiscoveredJobsTable`, `JobBucket` gains `'lowcontext'`; tune via the one constant in
  `lib/constants.ts`. Covered by unit (`actions.test.ts`), integration
  (`actions.int.test.ts`, mutual-exclusivity assertion) and component
  (`DiscoveredJobsTable.test.tsx`) tests.
- **Tests for two untested CI blind spots.** (1) The chart-data aggregations
  `getStatusFlow` / `getTimelineData` / `getCategoryData` (`lib/actions.ts`, feeding the
  Sankey / heatmap / donut) now have integration coverage against the throwaway SQLite
  (`charts.int.test.ts`) — status-chain dedup + collapse, per-day `T`-split counts,
  `null`→`Others` bucketing. (2) The `/api/health` liveness probe now has a unit test
  (`health.test.ts`, `@jest-environment node`) asserting 200 on a reachable DB and 503
  when Prisma throws. `jest.setup.ts` is guarded (`typeof window !== 'undefined'`) so the
  shared jsdom setup is a no-op under node-env files.
- **Fit-score band-regression eval harness** (`apps/worker/tools/score_eval.py` +
  `make eval-score`). Read-only (opens the shared DB `mode=ro`, never writes DDL/DML),
  reuses the exact production scorer wiring (`load_resumes` →
  `make_claude_scorer("claude-sonnet-5")` → `score_fit` → `_normalize_score`), scores
  each row of a frozen hand-labeled golden set K=3× and judges the **majority
  keep/near/skip band** — not the noisy exact score — against the label in code. PASS =
  0 hard-invariant violations + ≥85% band agreement + <20% flip-rate over the gate rows;
  `marked` rows route to a ⚑ watch list, excluded from the gate. Uses `max_tokens=8192` +
  a per-draw retry so a truncated response (adaptive thinking overruns the prod 4096 cap
  and is *not* an SDK-retried transient) can't abort a paid run. Replaces the retired
  ad-hoc "edit prompt → paid re-score → eyeball 20 rows" loop; the golden labels
  (`apps/worker/eval/`) stay gitignored (real postings). Design:
  `docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md`.

### Changed
- **Fit score reasoning redesigned into a structured `assessment` scorecard (S2.1;
  closes D3 + D4).** The Claude fit call now emits an `assessment` object — enum-
  constrained `seniority`/`domain` verdicts + notes, split `must_haves` {met, missing} /
  `nice_to_haves` {missing}, and a one-line `summary` — replacing the flat
  `matched_keywords`/`missing_keywords` lists and the prose `reasoning` blob in
  `score_detail`. The prompt scores from those verdicts: a material seniority gap floors
  the score at 0–30 (**D3** — a new grad no longer earns a mid score on a 3+-year role,
  e.g. id=904/177), and missing `nice_to_haves` barely move it (**D4** — a missing "plus"
  like C++ no longer tanks a strong core fit, e.g. id=427). `JobDetailModal` renders the
  scorecard (verdict chips, must/nice-have chips, summary) with the legacy
  matched/missing/reasoning path kept as a fallback for old rows; discarded rows carry no
  assessment. No DB migration (old rows keep their shape). Design:
  `docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md` §S2.1.

### Fixed
- **Fit-scale calibration validated — no change needed (D6).** Re-scoring a 20-row sample
  (flagged rows + a stratified sample) with the post-D3/D4/D5 prompt showed the score
  scale de-compressed on its own: the 60–74 near-miss pile-up collapsed (9→1 in the
  sample) and genuine good-fits reached ≥75 (0→6), while weak/too-junior roles sank. The
  deferred fork (loosen rubric vs lower the notify threshold) resolves to neither — the
  threshold stays **75**. Spot-checks confirmed D3 (id=904 62→25, id=177 63→28, id=322
  72→25, all `too_junior`) and D4 (id=427 66→81, C++/UNIX demoted to nice-to-haves).
- **Location no longer leaks into the fit score (D5).** The JOB section sent to the
  Claude fit call omits the `Location:` line (`_job_block(..., include_location=False)`),
  and the prompt tells the model to ignore geography. The same role posted per city now
  scores identically — geography is the screen gate's job, not the fit number's (it had
  ranked Cumberland London above Chicago, id=324 vs 323). The SCREEN call still receives
  location. Design: `…/2026-07-13-screen-score-quality-fixes-design.md` §D5.
- **Location gate resolves every token via geonamescache (D2).** `resolve_location` no
  longer inspects only the last token through `pycountry` (countries only) — it resolves
  **every** token to a country (US state / country name via pycountry, else a city via
  **geonamescache**, highest-population match), keeps if any is US or an allowed country,
  and discards only when ≥1 token resolves and none are allowed. Fixes both directions of
  the audit: a multi-city US role is kept (Tudor "NYC, London, Singapore", id=1009, was
  discarded) and a bare foreign city is dropped (DRW "London", id=324; WorldQuant "Hanoi
  OR Ho Chi Minh City", id=1071 — the ` OR ` split is now case-insensitive). Adds
  `geonamescache>=3.0.1`; supersedes the last-token/pycountry approach in
  `docs/superpowers/specs/2026-07-07-location-gate-design.md`. Design: `…/2026-07-13-screen-score-quality-fixes-design.md` §D2.
- **Authorization screen no longer disqualifies on boilerplate (D1).**
  `_check_authorization` replaced its loose `_SPONSOR_HINTS` substring guard — which
  fired on "company-sponsored sports teams" (Tower, id=986) and an EEO "citizenship"
  line (WorldQuant, id=1071), killing reachable US roles — with an explicit
  no-sponsorship **phrase** gate (`NO_SPONSOR_PHRASES`) over the JD text. The 4B model's
  invented `offers_sponsorship: "no"` is no longer consulted; a role is disqualified only
  when the candidate needs sponsorship *and* the description literally states no
  sponsorship. Design:
  `docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md` §D1.

### Added
- **Multi-resume fit scoring.** The worker loads every `resume/*.txt` as a labeled
  resume version (plus optional `personal_profile.txt` context); one Claude call
  scores the best-fitting version and names it (`recommended_resume`, enum-constrained),
  surfaced in the Telegram alert and the job detail modal. Single-resume setups are
  unchanged. (`--resume` → `--resume-dir`.) **Validated live 2026-07-13:** first
  full production pass — two resume versions (`swe`, `quant_dev`) over a 642-posting
  cold run, zero scorer failures; `recommended_resume` confirmed in `score_detail`
  and the Telegram `Resume:` line. (Closes the last "unexercised live" gap in
  `docs/PROGRESS.md`.)
- **Development mechanism for AI sessions: `docs/PRINCIPLES.md` + `docs/DEVELOPMENT.md`.**
  PRINCIPLES captures the project's fourteen design principles (each with rationale,
  repo exemplar, and violation smell) plus the decision procedure (forks go to the
  user; rejected alternatives get recorded). DEVELOPMENT pins the six-step session
  rail — boot, task classification, design gate, implement, evidence-based verify
  gate, same-commit docs — with a session-kickoff prompt template. `CLAUDE.md` and
  SPEC §14 now point at both. Design spec:
  `docs/superpowers/specs/2026-07-09-dev-mechanism-design.md`.

### Removed
- **Résumé tailoring removed — the pipeline now ends at score → notify.** Dropped the
  Claude+tectonic per-posting tailoring stage entirely: the state machine collapses
  `new → scored → tailored → notified` to `new → scored → notified`, and the score
  threshold (75) that used to gate tailoring now gates the Telegram alert. Telegram
  sends a message-only alert (company / role / score / link); the user applies by hand.
  - **Worker:** deleted `tailor.py` + `prompts/tailor.txt`; removed `run_tailor`,
    `db.save_resume`, the tailor wiring/flags (`--anthropic-model`, `--master-tex`,
    `--resume-dir`) and `max_single_page_rounds`. `run_notify` now processes
    `scored ≥ threshold` and `notify_posting` is a single atomic `sendMessage`. Dropped
    the `pypdf` dependency and the `tectonic` install (+ bundle prewarm) from the worker
    image. Fit-score `matched_keywords`/`missing_keywords` are **kept** — they still feed
    the Discovered-Jobs match analysis.
  - **Web + shared schema:** dropped `resume_tex`/`resume_path`/`resume_pages` and the
    `tailored` pipeline status from `schema.prisma` (apply with `make db-push` —
    destructive, back up `db/applications.db` first); deleted the `/api/resume/[id]` PDF
    route and the "Download Resume" UI in `DiscoveredJobsTable` / `JobDetailModal`;
    retargeted `ACTIVE_PIPELINE_STATUSES` → `{scored, notified}` and the
    promotion-traction SQL → `{notified, applied}`.
  - Worker (314) + web (137) + Playwright (4/4) suites and the coverage / schema-drift
    gates stay green. Design spec:
    `docs/superpowers/specs/2026-07-06-tailoring-removal-design.md`. (SPEC §1, §5–§13.)

### Fixed
- **A transient Telegram send error no longer buries a high-scoring match.** A notify
  failure used to park the row in terminal `failed` — gone from the default
  Discovered-Jobs view, never re-notified. `run_notify` now treats a send error as
  transient: the row stays `scored` (`attempts+1`, `pipeline_error` recorded) and the
  next scheduled pass retries the send; the 3rd cumulative failure parks it `failed`
  (the Failed tab), so a persistently-broken channel (revoked token, wrong chat id)
  still surfaces instead of retrying silently forever. A successful send clears
  `pipeline_error`; delivery is at-least-once (a duplicate ping beats a lost match).
  Design spec: `docs/superpowers/specs/2026-07-09-notify-retry-design.md`.
- **`apply-loop` e2e now confirms the Mark-Applied dialog.** The spec clicked the
  row's Mark-Applied icon but never confirmed the `ApplyCategoryDialog` the
  discovered-jobs overhaul (`d4b46ea`) added, so it timed out with the dialog open. It
  now clicks the dialog's confirm button; the Playwright suite is back to **4/4**.

### Changed
- **Location screen is now a deterministic code gate off the board field, not the 4B
  model.** The screen asked qwen3.5:4b to extract `{city,region,country}` from the JD
  and matched that; the 4B intermittently missed obvious foreign locations (a live run
  kept an on-site `Shanghai, China` role) and err-toward-keep leaked them to the paid
  Claude score. Location now resolves in code (`resolve_location`, `pycountry`) against
  `posting["location"]`: foreign roles that carry a country token are discarded before
  scoring; US-state-only and remote strings keep; ambiguous/missing keeps. Location left
  the LLM screen entirely (a `locations`-only candidate makes no Ollama call), and the
  scoring prompt split into `prompts/score.txt` + `prompts/screen.txt`. New dep:
  `pycountry`. (SPEC §5, §7.)
- **Scoring: the hard-requirements SCREEN now runs first and gates the Claude fit
  score.** `score_posting` previously called Claude on every posting and only *then*
  ran the local screen, so a posting bound for `discarded` (foreign on-site role,
  internship, missing-clearance, …) still paid for a Sonnet fit call. The order is now
  screen → gate → score: a disqualified posting records `score` 0 and **skips the paid
  Claude call entirely**; only postings that pass the screen are fit-scored. No change
  to screen logic or the score for surviving postings; disqualified rows still carry
  the per-requirement screen verdict + reason. Worker suite green (315). (SPEC §5, §7.)
- **Scoring: fit assessed by Claude Sonnet 5 (reason-first) instead of the local
  4B model; removed the fragile local years/seniority screen gate.** The
  hard-requirements screen (degree, work authorization, clearance, locations,
  dealbreakers, internships) stays on local Ollama, with code applying the
  candidate's configured constraints; only the fit SCORE moved to Claude, via a
  cached résumé+rubric system prefix, adaptive thinking, and schema-constrained
  JSON output (`reasoning` before `score`). New `ANTHROPIC_SCORE_MODEL` /
  `--anthropic-score-model` (default `claude-sonnet-5` — structured outputs
  require it; `claude-sonnet-4-6` doesn't support `output_config.format`),
  reusing `ANTHROPIC_API_KEY`. The now-inert `candidate.years_experience` config
  field was dropped (nothing screens on it anymore). (SPEC §3, §7.1, §10.)
- **Repo-wide over-engineering cleanup (behavior-preserving).** Removed dead code
  (worker `db.discard`/`db.mark_applied` + their tests, the `_row_to_dict` helper —
  `dict(row)` covers it, an unreachable `load_config` bytes branch, and the never-read
  `run_score`/`run_tailor` params) and unused web exports (`TERMINAL_STATUSES`, the
  `Status`/`Category`/`Source` type aliases). Dropped four web dependencies:
  `date-fns` + `date-fns-tz` (zero imports) and the redundant *direct* declarations of
  `playwright` + `@testing-library/dom` (kept transitively via `@playwright/test` and
  `@testing-library/react`). Deduped three duplicated types (components now `import type`
  them from their server-action modules), shared one `StageRow` renderer across
  `StatusFunnel`'s two groups, reused `<Pagination>` in `ApplicationTable`, and tidied a
  few test helpers. No capability change; worker + web suites and the coverage gate stay
  green. (Several audit findings were deliberately *not* applied — see commit history.)
- **Discovered Jobs UX: full pagination, debug filters, per-row reason, apply-time
  category.** (1) A proper paginator (first/last, numbered pages with ellipsis,
  go-to-page) replaces the bare Prev/Next (`components/Pagination.tsx`, reused by the
  Discovered table). (2) New filters for review/debug: a **Min score** input (all
  buckets) and, in the Discarded bucket, a **type** filter (All / Disqualified /
  Low score) — `getJobPostings` gains `minScore` + `discardType`. (3) Each discarded
  row shows its reason inline (red `✕ <disqualification reason>`, amber `low score`,
  or `discarded manually`) so you don't open each one. (4) **Mark Applied** now opens
  a category picker (`ApplyCategoryDialog`); `markJobApplied(id, category)` records the
  chosen category instead of always `Others`. (SPEC §7.2, §9.)
- **Discovered Jobs collapsed to three score-aware buckets + pagination.** While
  scoring is the focus, the per-status (`queue/all/scored/tailored/…`) and min-score
  dropdowns were too granular. The table now has three buckets: **Matched** (live +
  score ≥ `MATCH_SCORE_THRESHOLD`, default 75 — mirrors the worker's tailoring
  threshold), **Discarded** (explicitly discarded *or* live-but-below-threshold), and
  **Failed** (pipeline failures, for monitoring). `getJobPostings` now takes a
  `bucket` instead of `status`/`minScore` and is **paginated** (`page`/`size`, default
  25) — previously it loaded every row into one page, which could exhaust browser
  memory. (SPEC §7.2, §9.)
- **Experience screen is now strict — but only on a *hard-required* minimum.** A role
  whose hard-required minimum exceeds the candidate's years is screened out (was: only
  when ≥4 years beyond). With 1 YoE, "2-3"/"2-5 years" *required* roles (lower-bound 2)
  are now disqualified; "0-2"/"1-3" still pass. To avoid false-discards on early-career
  roles, the extraction prompt now reports `null` when the years are merely *preferred*
  / "a plus" / "or equivalent", or are a **cap** ("no more than 3 years", early-career)
  rather than a floor; and a deterministic keep-guard never discards on years when the
  JD welcomes early-career candidates (new grads / entry-level / "graduates will be
  considered"). The senior-title check is not relaxed by the guard.
  (`score._check_experience` + `_EARLY_CAREER_HINTS`, `prompts/score.txt`; SPEC §7.1.)
- **Feed performance: a full pass dropped from ~tens of minutes to ~1 minute.** Profiling
  showed the feed was network-bound and dominated by N+1 boards. Two fixes: (1) the feed
  now fetches **SmartRecruiters and Workday per surfaced job** (their new `fetch_one`)
  instead of listing the whole board — a 1500-posting SmartRecruiters board cost ~11 min
  of per-job detail calls just to keep the 1–2 jobs the feed wanted. Workday's per-job id
  is the job's `externalPath` (the CXS per-job endpoint), which also resolves Workday URLs
  the old `jobReqId`-suffix parsing rejected (a small coverage gain; the watchlist still
  lists the whole board). (2) `run_feed` now fetches **concurrently** — a `ThreadPoolExecutor`
  fans out the embedded-greenhouse I/O resolves and the per-group fetches, with all SQLite
  reads/writes kept on the main thread; `run.py` gives each worker thread its own
  `requests.Session` (keep-alive) and a shorter timeout. Measured: a fresh full feed pass
  went from ~47 min to ~47 s.

### Fixed
- **Internship/co-op roles now reliably screened out, via an explicit config flag.**
  The "no internships/co-op" case was a free-text LLM dealbreaker the 4B model often
  missed, leaking internships into the queue. It is now a first-class structured
  constraint — `candidate.exclude_internships: true` — decided deterministically from
  the job title (whole-word `intern`/`internship`/`co-op`, so "internal"/
  "international" don't match), independent of the LLM and of free-text dealbreakers.
  Same philosophy as the other hard-constraint gates (the 4B model is unreliable, so
  decide in code). (`score._is_internship`, `config.Candidate.exclude_internships`;
  SPEC §7.1.)

### Added
- **Discovered Jobs: sort by Best match or Newest posted (new `posted_at`, captured
  from greenhouse/lever/ashby/workday); bulk Remove (terminal, hidden + worker-inert)
  on Matched & Discarded, bulk Reopen + "Remove all in view" on Discarded; Discarded
  reframed as a near-miss audit view (default 60–74); job titles link to the posting.**
- **Embedded-greenhouse feed resolution.** Companies that host greenhouse jobs on their
  own domain with `?gh_jid=` apply URLs now resolve: a new *enriching resolver*
  (`feed/embedded_gh.py`) fetches the company page, scrapes the greenhouse board token
  (`…/embed/job_board?for=<token>`), and yields `("greenhouse", token, gh_jid)` so the
  existing greenhouse adapter ingests it (dedups with direct greenhouse). It stays out
  of the pure `resolve_url`; `run_feed` calls it as an injected I/O fallback (wired only
  in `run.py`). Recovers the server-side-embed subset; JS-injected embeds return None and
  stay recorded on the unresolved board. Recon deferred the other two Tier-2 sources:
  iCIMS is bot-walled ("Human Verification") and ByteDance/TikTok exposes no clean API
  (JD only in fragile Next.js flight data) — both need a headless browser, so they're
  left recorded, not built.
- **Detail-fetch robustness (prep for Tier-2 scrapers).** Silently-broken scrapers are
  now made visible: a fetched detail posting is validated (non-empty
  `external_id`/`job_title`/`description`) before it counts, and any failed surfaced id
  (a raise, a `None`, or an invalid posting) is recorded in `feed_unresolved` as
  `detail_fetch_failed` — appearing on the existing unresolved board, grouped by host —
  instead of vanishing into `run_feed`'s swallowed per-listing exception. A detail source
  that resolves ids but keeps none also prints a one-line collapse warning. Source-agnostic
  (lives in `pipeline.run_feed`/`_detail_fetch`); no adapter changes, no schema change.
  Canary self-tests and proactive Telegram/banner alerting are deferred.
- **Feed coverage Tier 1 — Oracle / Workable / Jobvite + Greenhouse-EU host.** Lifts feed
  resolution from ~⅔ to ~78% of the filtered-active feed (measured against the live
  `listings.json`: 460 → ~300 unresolved). New: a **per-listing detail-fetch path** in
  `run_feed` (a source exposes `fetch_one` and is listed in `fetch.DETAIL_SOURCES`) for
  boards with no public list endpoint, alongside the existing per-board list adapters.
  Adapters: **Oracle Cloud HCM** (`recruitingCEJobRequisitionDetails`, +116, feed-only),
  **Jobvite** (schema.org JSON-LD, +14, feed-only), and **Workable** (widget list API,
  +7, watchlist-capable → added to `VALID_SOURCES`). One-line **Greenhouse EU host**
  (`job-boards.eu.greenhouse.io`) fix (+23). Feed-only sources can't be enumerated as a
  watchlist company, so they stay out of `VALID_SOURCES` and are excluded from promotion
  suggestions. Deferred (fragile scraping): iCIMS, embedded greenhouse, ByteDance/TikTok.
  Added a source coverage matrix to SPEC §7.1.
- **Feed coverage expansion + promotion suggestions + unresolved viewer.** Building on
  the discovery feed: (1) **Workday** feed resolution (the feed exposes the per-tenant
  `jobReqId`, matched as a substring of the board's `externalUrl` since the adapter keys
  on the GUID) and a new **SmartRecruiters** board adapter (two-step list+detail), lifting
  feed coverage from ~⅓ to ~⅔ of the filtered-active feed; (2) **promotion suggestions** —
  non-watchlisted companies whose feed-discovered postings repeatedly pass threshold
  (`tailored`/`notified`/`applied`) or get applied to are surfaced in the Watchlist tab
  with **Approve** (→ add to watchlist) / **Dismiss** (→ `promotion_dismissed`); (3) a
  read-only **Unresolved** tab grouping the `feed_unresolved` backlog by host + reason.
  Postings now carry a `company_slug` (set at ingest) so promotion grouping needs no URL
  re-parsing. Sources supported: six (added `smartrecruiters`).
- **Discovery feed (SimplifyJobs) + DB-backed watchlist.** A new opt-in feed path
  ingests the SimplifyJobs `New-Grad-Positions/listings.json` (a public GitHub data
  file, *not* a scraped board): it pre-filters cheaply on the feed's own metadata
  (`active`, `category` keep-list, explicit-no-`sponsorship`), resolves each apply
  URL back to its board `(source, slug, external_id)`, and **reuses the existing
  board adapters** to fetch the JD — keeping only the feed-surfaced postings so the
  score/tailor/notify pipeline runs unchanged. v1 resolves
  `lever`/`ashby`/`greenhouse`-direct (~⅓ of the filtered-active feed); the rest
  (Workday, SmartRecruiters, embedded-greenhouse, other ATSes) is recorded in a new
  `feed_unresolved` table as a prioritised backlog, never silently dropped. New
  worker package `ats_worker/feed/` (`simplify`/`prefilter`/`resolve`), pipeline
  stage `run_feed`, and an optional `feeds:` config block. (SPEC §5–§9.)
- **Watchlist moved into the database** (`watched_companies`) and is now managed in
  a new **Watchlist** tab in the web app (list / add / remove). The worker reads its
  watchlist from the DB and **auto-seeds it once** from `config.yaml`'s `companies:`
  when the table is empty (`--import-companies` forces a re-seed); `companies:` is
  now a one-time seed rather than the live source.
- Two more board adapters — **Workday** (CXS list + per-job detail; the `slug`
  packs `tenant/datacenter/site`) and **Pinpoint** — bringing supported sources
  to five.
- **Hard-constraint candidate screening**: an optional `candidate` block in
  `config.yaml` (years of experience, degree, work authorization, security
  clearance, locations, plus freeform dealbreakers). The local scorer screens each
  posting *semantically* and auto-discards conflicting roles, keeping the reason and
  per-requirement verdicts for the UI; a **Reopen** action reverses a discard.
- Integration test tiers (worker `run_once` over a temp SQLite; web Server Actions
  over a real throwaway Prisma DB) and a **Playwright** end-to-end suite.
- **Container self-healing for the WSL2 stale-bind-mount failure.** A new `GET
  /api/health` route opens the DB (`SELECT 1`) behind a Docker `healthcheck`, and an
  **`autoheal`** sidecar restarts `ats-web` whenever Docker marks it unhealthy —
  recovering from the `SQLITE_CANTOPEN` (Error code 14) a stale bind mount causes
  after the WSL2 VM suspends/resumes. (SPEC §6.)
- **`make seed-dev`** (`apps/web/prisma/seed-dev.mjs`) — appends a realistic spread
  of sample applications (varied statuses, categories, dates, and `status_history`
  trails) to the local DB for populating the dashboard. Unlike the e2e fixture it
  **never clears** existing rows, so it is safe to run against a DB holding real
  worker `job_postings`.

### Changed
- Default scoring model is now **`qwen3.5:4b`** (local Ollama) and default
  resume-tailoring model is **Claude `claude-sonnet-4-6`** — both overridable via
  CLI flag or env var.
- The repo ships only `*.example` templates; the real resume, `config.yaml`, and
  secrets stay gitignored.
- CI now gates coverage on both suites, runs a schema-drift guard (worker SQL
  fixture vs. `prisma/schema.prisma`), and runs a gated Playwright e2e job.

### Fixed
- Workday pagination and adapter robustness; hardened hard-constraint screening;
  HTML-to-text now collapses non-breaking spaces; config errors surface clearly.

### Documentation
- Added an authoritative system spec ([`docs/SPEC.md`](./docs/SPEC.md)), a progress
  tracker ([`docs/PROGRESS.md`](./docs/PROGRESS.md)), and an auto-loaded `CLAUDE.md`;
  slimmed the README and reduced `docs/SETUP.md` / `docs/pipeline-design.md` to
  pointers.
- Separated the three docs by role: **SPEC** = the current capability map ·
  **PROGRESS** = live delta only (in-flight + open work, graded by severity) ·
  **CHANGELOG** = chronological history. PROGRESS dropped its completed-feature
  tables (the capability inventory now lives solely in SPEC), recalibrated its
  summary (no "feature-complete and stable"), and surfaces the shipped notify
  data-loss defect as a graded defect rather than one bullet among nice-to-haves.
- Added a user-facing **Feature status** matrix to the README with an honest
  *Tested* axis (✅ / ⚠ / —) that distinguishes shipped from verified — fixing the
  old all-`✅` over-claim. Building it surfaced an untested gap: the chart-data
  actions (`getStatusFlow`/`getTimelineData`/`getCategoryData`) have no test
  coverage (now tracked in SPEC §9 and PROGRESS).

## [0.2.0] — 2026-06-08

### Added
- **Semi-automated job-hunt pipeline** (`apps/worker/`): a Python worker that
  scans Greenhouse / Lever / Ashby boards, scores each posting against your
  resume with a local Ollama model, auto-tailors a one-page resume for high
  scorers (Claude + `tectonic`), and notifies you on Telegram.
- **Discovered Jobs** tab in the web app: a scored, filterable queue with a
  job-description + match-analysis dialog, per-job tailored-resume download
  (`GET /api/resume/[id]`), and one-click "Mark Applied" that promotes a posting
  into a tracked application.
- `job_postings` model in the Prisma schema (deduped on `(source, external_id)`,
  advancing through a `pipeline_status` state machine).
- Repository scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`, this changelog,
  `.editorconfig`, a root `Makefile`, GitHub Actions CI, and a PR template.

### Changed
- Promoted `docker-compose.yml` to the repository root; it now orchestrates both
  the web app and the worker from one place (`docker compose up` from root).
- Moved `SETUP.md` and the pipeline design doc under `docs/`.
- Prisma datasource is now driven by `DATABASE_URL` so the same schema serves
  local dev and the directory-mounted Docker volume shared with the worker.

### Fixed
- Web `lint` step (and therefore CI) failed before running: the flat
  `eslint.config.mjs` used Next 15 / ESLint 9 imports (`eslint/config`,
  `eslint-config-next/typescript`) incompatible with the pinned Next 14 /
  ESLint 8 toolchain. Replaced with a standard `.eslintrc.json`
  (`next/core-web-vitals`) run via `next lint`.

## [0.1.0] — initial tracker

### Added
- Next.js + Prisma + SQLite application tracker: status KPIs, searchable and
  paginated table with inline status editing and history, CSV import/export,
  and dashboards (activity heatmap, category donut, status funnel, Sankey).
- Dockerized web app with a bind-mounted database.
