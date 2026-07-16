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

🚧 **Ship the fit-score prompt edit — validate, then commit `score.txt`.** The
band-regression eval harness is **built and committed** (`apps/worker/tools/score_eval.py`
+ `make eval-score`; recorded in [SPEC](./SPEC.md) and the [CHANGELOG](../CHANGELOG.md)):
read-only, scores each frozen golden-set row K=3× and judges the majority keep/near/skip
**band**, PASS = 0 hard-violations + ≥85% agreement + <20% flip. Harness code is on
`origin/dev` (`master` untouched); what's left is the ship gate for the *prompt*.
`score.txt` (uncommitted, working tree) holds the validated 4-edit prompt — crisp / de-dup
misses · seniority keyed to an *explicit stated level* only · credit a capability the
résumé shows under a different name · no structurally-impossible misses.
**Deliberately uncommitted:** the runs that motivated the golden relabels are circular to
count as validation, so ship needs **2 fresh consecutive PASS runs** of `make eval-score`,
then commit `score.txt`. **Watch:** 6 golden labels moved
post-hoc and the near band thinned 8→3 (repopulate it from fresh surprises). Golden set +
`personal_profile.txt` are gitignored; full method + baseline findings in
`docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md`. Scratch, *not* repo
state: `golden_candidates_full.md`, `audit_list.txt`, `rescore_*.md`, `.coverage`.

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
400-rejected on the `claude-sonnet-5` tier — so it was replaced by the band-regression
harness above. The four prompt edits it produced survive as the `score.txt` now pending
harness validation; the low-variance lever it found (seniority keyed to an objective stated
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

**None open.** The 6 cold-pass defects (D1 auth · D2 location · D3 seniority · D4
plus-skills · D5 location-leak · D6 calibration; 2026-07-13) all shipped — see the
[CHANGELOG](../CHANGELOG.md). D6 closed by *measurement*, not code: D3/D4/D5 de-compressed
the fit scale as an emergent effect (a 20-row sample's 60–74 band collapsed 9→1, 75+ rose
0→6), so no rubric-loosen was needed and the notify threshold stays 75.

### Unverified / unguaranteed properties — behavior may be fine, but nothing proves it (should address)

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

- **`posted_at` for dateless boards** — `[S · accepted limitation]`. Pinpoint exposes no
  board date, so `posted_at` falls back to the scrape date for Pinpoint (and any dateless
  row). No fix unless a board adds a date — documented, low value.
- **More board adapters** — `[M · pick a target]`. The adapter pattern (`fetch/<source>.py`
  + `ADAPTERS`/`VALID_SOURCES`, or `fetch_one` in `DETAIL_SOURCES`) makes new sources cheap;
  JobSpy noted as a possible fallback aggregator.
- **Fit-score cost / determinism levers** — `[M · gated on harness flip-rate]`. The scorer
  is DI'd (`score.make_claude_scorer`), so a provider swap is a clean seam (a
  `make_openai_scorer` twin wired in `run.py`). Two overlapping levers, **both gated on
  `eval-model == production-model`**: (a) get off metered pay-as-you-go via a flat-rate
  Claude/ChatGPT subscription — but a coding-agent CLI (`codex exec`) is heavy, fragile at
  strict JSON, and shaky auth in the 24h cron, so the OpenAI **API** is the better interface;
  (b) an OpenAI model whose `seed` + `temperature=0` could kill the ±15 noise `claude-sonnet-5`
  can't turn off. Revisit only if the harness flip-rate shows the noise is genuinely blocking.
  (Context: eval-harness design.)
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
