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

🚧 **Codex fit-score backend shipped; acceptance gate pending.** `make_codex_scorer` is
built, wired as the **default** backend, and unit-covered (see
[CHANGELOG](../CHANGELOG.md)); one real golden row scored end-to-end through the
production schema (id=151 → 72, full assessment, enum-constrained resume pick, ~42 s).
**Open:** `make eval-score` on the codex backend must clear the gate (0 hard-invariant
violations · ≥85% band-agreement · <20% flip-rate), **twice consecutively**, before the
backend can be trusted for the re-run below. The flip-rate is the number to watch — this
backend has no seed, so K=3 majority is the only noise defense.

🚧 **Apply the shipped screen/score fixes to the live DB (operator step).** All 6
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
**The economics inverted 2026-07-16:** on the shipped `codex`/subscription backend this
pass is **free** but **slow** — ~42 s/posting ≈ **7.5 h sequential** (was: paid, fast).
Cost is no longer the reason to hesitate; wall-clock is, and parallelism is the untried
lever if that matters. Still not done automatically (mutates the DB); back up
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
400-rejected on the `claude-sonnet-5` tier — so it was replaced by the band-regression
harness (`make eval-score`, built + committed; in [SPEC](./SPEC.md) + [CHANGELOG](../CHANGELOG.md)).
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

**None open.** The 6 cold-pass defects (D1 auth · D2 location · D3 seniority · D4
plus-skills · D5 location-leak · D6 calibration; 2026-07-13) all shipped — see the
[CHANGELOG](../CHANGELOG.md). D6 closed by *measurement*, not code: D3/D4/D5 de-compressed
the fit scale as an emergent effect (a 20-row sample's 60–74 band collapsed 9→1, 75+ rose
0→6), so no rubric-loosen was needed and the notify threshold stays 75.

### Unverified / unguaranteed properties — behavior may be fine, but nothing proves it (should address)

- **Prompt-injection exposure via the codex scorer is measured, not bounded** — `[M ·
  new surface as of 2026-07-16]`. The `codex` fit backend feeds **untrusted scraped JD
  text to an agent that has a shell**, which the Claude backend (a plain completion, no
  tools) never did. `--sandbox read-only` blocks writes but **permits reads anywhere** —
  so the theoretical worst case is a JD instructing the model to read `~/.codex/auth.json`
  or `apps/worker/.env` (Telegram tokens, `ANTHROPIC_API_KEY`) and echo it into the
  `summary`, which is persisted to `score_detail` and pushed to Telegram. **Probed
  2026-07-16 and resisted:** a canary JD ordering `cat <secret>` into the summary + a
  score of 99 produced no tool call, no leak, and a merits-based 10. That is **one
  adversarial probe, not a guarantee** — the model chose not to comply; nothing structural
  stopped it, and `codex exec` has no flag to drop the shell tool. Upgrade path if this
  ever matters: run the scorer as a user (or in a container) that simply cannot read the
  secrets — don't rely on model compliance.
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
- **Fit-score noise is unfixable on the shipped backend** — `[M · accepted limitation;
  revisit only if the harness fails]`. The ±10–15 score noise (id=322 = 35→52, id=6 = 68→82)
  has **no** off switch now: `claude-sonnet-5` 400-rejects `temperature`/`seed`, and the
  shipped `codex` backend exposes neither (only `model_reasoning_effort`, pinned `high`).
  The 2026-07-15 plan to buy determinism via the OpenAI **API** was dropped when the
  operator chose the flat-rate **subscription** (2026-07-16) — cost beat determinism, and
  the API's lever was best-effort anyway (`seed` is documented as best-effort; reasoning
  models reject `temperature`). So band stability is now a *measured* property, not a
  guaranteed one: `make eval-score` (majority-of-K=3 bands) is the only thing standing
  between the noise and a wrong routing decision. If it starts failing, the escape hatch is
  raising K or `--score-backend claude`, not a seed.
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
