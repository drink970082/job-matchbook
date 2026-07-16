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

- **Stale-mount recovery is unobserved end-to-end.** The `/api/health` probe, Docker
  `healthcheck`, and `autoheal` sidecar are wired, the *healthy* path is confirmed
  (`ats-web` reports `healthy`, the sidecar monitors), and `/api/health`'s 200/503 logic
  now has a unit test (`health.test.ts`). What stays unproven is recovery from an *actual*
  WSL2 stale-bind-mount event — never observed, and not reproducible in a unit test (needs
  a live event or a manual drill). (SPEC §6.)
- **No schema migration path.** `prisma db push` keeps no migration history, so a
  *destructive* schema change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)

### Enhancements — not built, optional

- **Trim `config.yaml` to machine-only filters.** Config should hold *only* what a
  deterministic machine filter uses (companies, `title_filter`, threshold, schedule,
  `exclude_internships` — decided in code from the title). Any constraint actually
  *adjudicated by the LLM* should not live in config at all — it belongs on the résumé /
  profile that feeds the model. Today `config.Candidate` (degree / auth / clearance /
  locations / dealbreakers) is handed to the **LLM screen** (`config.py` docstring), so by
  this rule those fields leave config and become résumé/profile evidence. Revisits the
  config-vs-profile seam in [In flight](#in-flight): keep the seam's split, but move the
  boundary to *deterministic vs LLM-handled* rather than *hard-constraint vs fit*. Check
  which of the D1/D2 gates are genuinely deterministic (stay) vs LLM-screened (move) before
  cutting anything.
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
