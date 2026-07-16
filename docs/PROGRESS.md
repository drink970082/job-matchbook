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

▶ **Next session — start here.** Branch `dev` (5 commits D1–D6 pushed to `origin/dev`;
`master` untouched). Untracked scratch in the tree is not repo state: `audit_list.txt`
(the 8-posting audit source), `rescore_results_full.md` (the 20-row re-score **baseline**
to compare against), `.coverage`. Two independent threads are open, in priority order:

- **A — Fit-score eval harness: BUILT + baselined; prompt edit validated, ship pending 2
  fresh confirmations.** Harness `apps/worker/tools/score_eval.py` + `make eval-score`
  shipped (this commit): read-only (DB `mode=ro`), K=3× → majority keep/near/skip band vs
  the frozen golden labels in code; PASS = 0 hard-violations + ≥85% agreement + <20% flip
  over the gate rows, `marked` → ⚑ watch list. (Tool fix: `max_tokens=8192` + per-draw
  retry — the prod 4096 cap truncates the verbose assessment JSON under adaptive thinking →
  `ScoreError`, which is NOT SDK-retried, so one bad row aborted a paid run.) The ad-hoc
  eyeball loop is retired. **Golden set (gitignored) evolved to keep 10 · near 3 · skip 8 ·
  marked 2 (gate 21)** — six *evidence-based* label corrections (not model-fitting): 652,
  26, 1158, 153, 70 near→**keep** (all target-list per `personal_profile.txt`; the min-1
  "1-3 yr" convention is now *keep-eligible for target domains*, not auto-near); **132
  skip+hard → marked** (its bar is "2+ years **OR** demonstrated excellent skills" — an
  escape clause the seed label missed; the model reads it as a soft bar and splits 50/50 →
  un-judgeable; the min-2 hard invariant stays guarded by the clean floors 666/207/186).
  **Baseline overturned the prediction** — 132/666 already floored; the real miss was the
  near band over-flooring "1-3 yr" (1158/153/70, bimodal skip 28 / keep 83). **The queued
  edit** (un-floor "1-3 yr", keep min≥2) killed that bimodality → both runs recompute to
  PASS (100% agreement · hard clean · flip 19%/10%). **Remaining to ship:** those two runs
  *motivated* the relabels (circular to count) and run-1's flip margin is thin (19%), so
  ship needs **2 FRESH consecutive PASS runs**, then commit `score.txt` (deliberately left
  uncommitted). **Caution:** 6 labels moved post-hoc (each justified, but volume = overfit
  risk); near band thinned 8→3 (grow-from-surprises repopulates). Full findings appended to
  the design doc. Uncommitted working-tree (deliberate): `score.txt`, `personal_profile.txt`
  (gitignored). Scratch (not repo state): `golden_candidates_full.md`, `audit_list.txt`,
  `rescore_*.md`, `.coverage`.
- **B — Operator: apply the shipped D1–D6 fixes to the live DB** (block below). Separate,
  paid, mutates the DB; independent of A, do anytime.

🚧 **Apply the shipped screen/score fixes to the live DB (operator step).** All 6
audited defects (D1–D6) are fixed and on `dev` (see [CHANGELOG](../CHANGELOG.md);
design `docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md`), and
validated **2026-07-14** against the live 1,169-row DB — a free pure-code pass (146 auth
false-negatives recovered, 6 location keeps, 174 bare-foreign leaks now gated) plus a
20-row Claude re-score (measurement-only, not persisted). But the **stored** rows still
carry pre-fix screen verdicts and scores. The next scheduled pipeline pass only reaches
*new* postings, so applying the fixes to the existing queue needs an operator re-run
(reset the affected rows to `new`, or a one-off re-score) — a **paid** Claude pass over
the ~640 kept rows. Not done automatically (mutates the DB + costs $); back up
`db/applications.db` first.

🚧 **Scorer-prompt refinement round 2 + profile framework (designed 2026-07-14, not yet
implemented).** A subagent quality-assessment of the 20-row re-score
(`rescore_results_full.md`) found two issues the S2.1 scorecard still has — both
**universal**, not sample-patching: the fit `must_haves.missing` lists (a) restate one
gap as several verbose paraphrased items (deficit-length inflation) and (b) penalize
skills the résumé shows under a *different name* ("no explicit RAG" when a retrieval
agent is on the résumé). Agreed `score.txt` changes (validate with a fresh re-score
before shipping; must NOT regress the D3 seniority floor):

- **Crisp / de-dup misses** — each `missing` item is ONE distinct checkable requirement;
  collapse facets of one gap into a single item; prefer crisp skills over prose sentences.
- **Seniority axis = explicit level only** — the `too_junior`/`too_senior` floor fires
  only on a *stated* level (a YoE number, or senior/lead/staff/principal). Implied
  ownership/responsibility ("independently own production systems") is a
  `must_haves`/`domain` matter (dings toward a near-miss), NOT seniority (which floors to
  0–30). Preserves the explicit-bar floors (id=904 "4+ yrs", id=177 "3+ yrs", traders
  "2+ yrs"); un-floors implied-senior in-track roles (id=322).
- **Read the résumé for substance, not keyword** — credit a capability the résumé
  demonstrates under a different name (a retrieval agent ⇒ "RAG"). Do NOT infer from
  adjacency (Python ⇒ mypy) — that hallucinates skills and hides real résumé gaps.
- **No structurally-impossible misses** — don't list "no full-time tenure / not a proven
  top performer at a prior job" as a missing must-have for roles open to new grads.

**Résumé vs profile — governing rule (decided):** the **résumé is authoritative for
skill / experience evidence** (it is what a recruiter sees). The **profile shapes the fit
score but never overrides the résumé as skill evidence** — it may push fit *up* (genuine
interests / motivation — the one legitimate upward lever, since interest ≠ skill), *down*
(honest caveats), or *sideways* (positioning / direction), but must never inject skills
the résumé does not back. Corollaries: **courses live on the résumé** (a selective
"Relevant Coursework" line), not the profile; and a "no explicit X" for a skill genuinely
absent from the résumé is useful **résumé-gap signal** (fix the résumé), aligned with the
recruiter-first view.

**Config vs profile — seam (decided):** `config.yaml` **serves the machine only** —
operational settings (companies, title_filter, threshold, schedule) plus the structured
hard constraints that feed the **deterministic** screen gates (degree / auth / clearance /
location / internships, incl. D1/D2). It is **not** retired or dissolved into prose (that
would regress the deterministic gates). The **profile serves the LLM fit score only**;
de-duplicate by dropping the hard-constraint restatements (auth / location narrative) from
the profile, since config owns them. (The earlier "profile absorbs config" idea is
dropped.)

**Good-profile framework — what the profile should contain:**
1. **Target direction** — roles / functions / firm-types wanted, priority-ordered (judges
   domain-fit against intent, not just history).
2. **Anti-targets** — what to avoid even if qualified (correctly marks HFT / pure-trading /
   floor / IT-ops roles as a poor fit *for you*).
3. **Career stage (factual)** — grounds the seniority verdict; context, not a skill claim.
4. **Self-positioning** — how you identify when a title is ambiguous ("builder/dev, not a
   pure researcher") — drives the `domain: adjacent` calls.
5. **Interests / motivation** — genuine fit factors; the one legitimate *upward* lever.
6. **Honest downward caveats** — where the résumé might over-read ("C++ coursework-depth").
   - **Out of the profile:** skills / tech / courses omitted from the résumé (→ put them on
     the résumé); anything meant to inflate qualification beyond the résumé; hard
     constraints already in config. Keep it **concise + stable** — it is a cached prefix on
     every score call.

**Status — round-2 superseded by the eval-harness approach (2026-07-15).** The four
`score.txt` edits + the regenerated `personal_profile.txt` remain uncommitted on the `dev`
working tree; two paid 20-row re-scores were run (`rescore_round2_review.md`, untracked).
Round-2 did **not** cleanly pass — but the decisive finding was about the *method*, not the
prompt: the loop was **unmeasurable**. The fit score is a **noisy readout** (±10–15
run-to-run on borderline rows — e.g. id=322 = 35 then 52, id=6 = 68→82; `temperature`/`seed`
are rejected 400 on the `claude-sonnet-5` tier so the noise can't be turned off) with **no
deterministic assessment→score mapping** (roughly `f(#must_haves.missing, domain bucket)`,
both re-chosen each run), and the round-2 measurement was **confounded** (prompt *and*
profile moved together). Conclusion: stop chasing exact scores; judge **bands** against a
**written, frozen** golden set with a noise-tolerant stopping rule (thread A above +
`docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md`). The one low-variance
lever round-2 found — seniority keyed on an *objective stated level* — is now the golden
set's labeling convention (stated **minimum ≥ 2 yrs → skip**; "1-3" → near; "0-2"/ceiling/
no-bar → keep-eligible).

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Graded by
severity:** a shipped defect that silently loses prepared work is a different kind of
thing from an unbuilt nice-to-have, and the two should not read at the same weight.

### Defects — shipped behavior that is wrong (should fix)

**None open.** The 6 defects from the 2026-07-13 cold-pass audit (D1 auth, D2 location,
D3 seniority, D4 plus-skills, D5 location-leak, D6 calibration) all shipped — see the
[CHANGELOG](../CHANGELOG.md). **D6 closed by measurement, not code:** the 2026-07-14
re-score showed the fit scale de-compressed as an *emergent* effect of D3/D4/D5 (in a
20-row sample the 60–74 near-miss band collapsed from 9 rows to 1, and 75+ rose from 0
to 6 — genuine fits clear the notify threshold, weak/too-junior fits sink), so **no
rubric-loosen or threshold-drop was needed** and the notify threshold stays 75.

### Unverified / unguaranteed properties — behavior may be fine, but nothing proves it (should address)

- **Stale-mount auto-recovery is unverified end-to-end.** The `/api/health` probe,
  Docker `healthcheck`, and `autoheal` sidecar are wired and the *healthy* path is
  confirmed (`ats-web` reports `healthy`, the sidecar monitors), but recovery from an
  *actual* WSL2 stale-bind-mount event has not been observed, and `/api/health` has
  no automated test. (SPEC §6.)
- **Chart-data actions have no automated test.** `getStatusFlow`,
  `getTimelineData`, and `getCategoryData` (`lib/actions.ts`, feeding the
  Sankey / heatmap / donut) are exercised by no unit, integration, or e2e test —
  only their components render. A regression in the aggregation would pass CI.
- **No schema migration path.** `prisma db push` keeps no migration history, so a
  *destructive* schema change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)

### Enhancements — not built, optional

- **Alternative fit-score provider (cost / determinism).** The fit scorer is
  dependency-injected (`score.make_claude_scorer`), so a provider swap is a clean seam
  (a `make_openai_scorer` twin, wired only in `run.py`). Two possible future motivations,
  **both gated on the iron rule `eval-model == production-model`** (tuning a prompt against
  a model you don't ship is a bigger confound than round-2's profile confound): (a) **run
  the scorer on a ChatGPT/Codex subscription** (e.g. `codex exec`) to get off pay-as-you-go
  — but `codex exec` is a coding *agent* (heavy per call, fragile at strict-JSON output, and
  subscription auth is shaky in the unattended 24h cron), so the OpenAI **API** is the better
  interface if switching at all; (b) **an OpenAI model via API**, whose `seed` +
  `temperature=0` could cut the ±15 noise the `claude-sonnet-5` tier can't turn off. Revisit
  only if the harness **flip-rate** shows the noise is genuinely blocking; deferred, nothing
  migrated. (Context: the eval-harness design, thread A.)
- **Remaining feed coverage (the `feed_unresolved` long tail).** Feed-coverage Tier 1
  landed (greenhouse-EU host, Oracle, Workable, Jobvite + a per-listing detail-fetch
  path), lifting resolution ~67% → ~78% of the filtered feed. **Measurement snapshot
  (2026-06-18, live `listings.json`):** 18,207 raw → 1,394 after prefilter; 460
  unresolved by platform — Oracle 116 ✅, ByteDance/TikTok 85, iCIMS 42, greenhouse
  EU-host 23 ✅, embedded-greenhouse 54, greenhouse embed-token 17, Jobvite 14 ✅,
  Workable 7 ✅, long-tail bespoke ~remaining. Two robustness/coverage steps then landed:
  (1) the **detail-fetch robustness framework** (validate scraped postings; record
  raise/`None`/invalid failures to `feed_unresolved` as `detail_fetch_failed`; collapse
  warning) so scrapers fail *loudly*; (2) **embedded greenhouse** ✅ — an enriching
  resolver scrapes the board token from the company page and reuses the greenhouse
  adapter (recovers the server-side-embed subset; JS-injected embeds stay recorded).
  **Deferred after recon proved them not feasible via `requests`:** **iCIMS** (~42 —
  every request returns a "Human Verification" bot wall; needs a real browser, a heavy
  dep that contradicts the requests-only worker) and **ByteDance/TikTok** (~85 — no
  accessible clean API; the JD is rendered only inside fragile Next.js `__next_f` flight
  data with unreliable location, a hack not worth shipping). Revisit only with a
  headless-browser strategy. **Dropped:** greenhouse embed-token (URL has only a job id,
  no recoverable board slug); SuccessFactors (absent from the feed).
- **Feed performance ✅ (full pass ~tens of min → ~1 min).** Profiling found the feed was
  network-bound and dominated by N+1 boards (one SmartRecruiters board: ~11 min to keep
  1–2 jobs). Fixed by routing SmartRecruiters **and Workday** through per-job `fetch_one`
  in the feed (fetch only surfaced ids; Workday by `externalPath`, which also lifted
  Workday resolution) + concurrent fetching in `run_feed` (`ThreadPoolExecutor`, DB on the
  main thread; per-thread `Session` + shorter timeout). The previously-demoted Workday
  CXS-direct work thus landed — for speed, and it *gained* coverage rather than costing it.
- **Headless-browser fetch (Playwright) — the next step to unlock iCIMS + ByteDance
  (~127 listings).** Both deferred Tier-2 sources need a real browser: iCIMS gates every
  request behind a "Human Verification" bot wall, and ByteDance/TikTok renders the JD
  only client-side (no clean API; only fragile Next.js flight data server-side). Plan:
  add an *optional* Playwright-backed `fetch_one` path (new dep + headless Chromium),
  kept isolated and config-gated so the requests-only adapters and the core pipeline stay
  dependency-light — render the page, then reuse the per-source extractors (iCIMS
  `window._jibe`, ByteDance position data). The detail-fetch robustness framework already
  makes these fail loudly, and each remains its own spec.
- **`posted_at` board coverage.** The posting date is captured for
  greenhouse/lever/ashby/workday; Pinpoint exposes no board date, so `posted_at` falls
  back to the scrape date for Pinpoint rows (and any other dateless row).
- **More board adapters.** The adapter pattern (`fetch/<source>.py` + `ADAPTERS` +
  `VALID_SOURCES`; or `fetch_one` for a per-listing source in `DETAIL_SOURCES`) makes
  new sources cheap; JobSpy was noted as a possible fallback aggregator.
- **Deployment / monitoring.** `ats-web` now has a DB-reachability healthcheck +
  `autoheal` auto-restart (SPEC §6), but there are still no metrics or alerting
  beyond the per-job Telegram notification, and the **worker** has no healthcheck;
  failures there are visible only in the DB / logs.
- **Paid subscription instead of pay-as-you-go API calls.** Related to the
  provider-swap seam above (`score.make_claude_scorer`) but a distinct lever: check
  whether a flat-rate Claude/ChatGPT subscription can front the fit-score calls
  instead of metered API billing, for cost predictability at higher volume. Same
  `eval-model == production-model` gate applies before switching.
- **Separate tab for low-context Discovered Jobs.** Some fetched postings lack
  enough parseable structure (thin/malformed JD) to screen or score with
  confidence; they currently sit in the same Discovered Jobs queue as normal rows.
  Give them their own tab/bucket in the web UI so they're visibly distinct instead
  of silently scored (or dropped) alongside confidently-parsed postings.
- **AI fetch+score fallback for unparseable job descriptions.** For postings where
  structural text extraction fails (JS-rendered pages, bot-walled boards, odd
  markup), explore letting Claude — via API or a paid subscription — fetch the job
  page itself and score fit directly from the raw page, bypassing the normal
  parse-then-score pipeline. Candidate landing spot for the iCIMS/ByteDance
  long-tail above if a headless-browser fetch alone isn't enough.

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
  bucket. Keep the ordering honest: defects (broken) above unverified properties
  above enhancements (optional).
