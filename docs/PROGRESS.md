# Job Matchbook — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is* — the authoritative capability map) and [`../CHANGELOG.md`](../CHANGELOG.md)
> (what landed *when*). **This file is only the delta:** what's in flight and what's
> still open. It carries no completed-feature inventory — that lives in SPEC, and a
> finished item *leaves* this file to land in SPEC + CHANGELOG. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the bottom.

**Current phase:** **v1.0.0 released** (2026-07-22) — tagged on `main`, repo public
as [`drink970082/job-matchbook`](https://github.com/drink970082/job-matchbook), CI
fully green (web / worker / e2e). Feature-set complete and validated live end-to-end;
testing/CI hardened (coverage gates, integration + Playwright e2e, schema-drift and
privacy guards). **"Hardened"
means test/CI hardening, not security hardening** — accepted residuals are documented
in SPEC §11 + `SECURITY.md`; genuinely open items are below.

For *what the system currently does*, read SPEC §4 (goals), §5 (workflow), and §7
(components); for *when each piece landed*, read the [CHANGELOG](../CHANGELOG.md).

---

## In flight

- **Branch `fix/bodyless-guard-and-quota-flags` — landed, unmerged (2026-07-22).**
  Worker code + docs on a local branch, full suite green, not yet PR'd to `main`.
  **Shipped:** body-required guard on the board path (bodyless rows dropped + recorded
  in `feed_unresolved`); thin-JD (< 200 char) rows skip the paid fit call; operator
  flags `--fetch-only` / `--score-only` / `--score-limit N` (see SPEC §7.1, CHANGELOG).
  **Exercised live:** a full `--fetch-only` pass (7,746 postings, 11 sources, 172 boards,
  clean) and one bounded `--score-only --score-limit 50` (41 Codex calls, 4 matches).
  **Open on this branch:** ~3,985 rows still `new` (scoring at scale is an operator
  call); the `custom`/`browser` **scored** path is still unexercised (the bounded batch
  hit the low-id greenhouse/phenom rows); then PR to `main`. Detail in the P0 run entry
  below.
- **Run the pipeline as a daemon** — the recurring 24h scheduler
  (`python -m ats_worker.run`) remains the operator's standing launch step; passes
  are currently run by hand.
- **General-purpose pivot (in progress).** Broadening the product from a quant/SWE
  niche to any field. **Shipped:** user-configurable job categories (`app_settings`,
  first-run modal + header editor, free-form labels); a persona-neutral
  `personal_profile.txt.example` + TARGET/ANTI-TARGET/STAGE docs in `resume/README.md`;
  a full guided **`onboard-me` skill** — an adaptive interview that writes the fit
  profile, résumé text, categories, `candidate` hard-constraints, a starter watchlist
  (delegated to `onboard-board`), and `.env`, then ends on the first pipeline run
  (**Stage 2 — done**; validated with a skill-creator eval suite; see CHANGELOG). By
  design the fit-scoring prompt (`score.txt`) is **left untouched** — generality lives in
  `personal_profile.txt`, and scorer-prompt edits have destabilized verdicts before
  (SPEC §7.1).
  - **Stage 3 — non-tech discovery feeds: deferred.** The watchlist already covers any
    company; decide the need before building (brittle, anti-bot handling, dilutes the moat).
- **Provider choice + universal onboarding — design agreed, spec pending.** Design
  notes:
  [`superpowers/specs/2026-07-22-provider-choice-and-onboarding-notes.md`](./superpowers/specs/2026-07-22-provider-choice-and-onboarding-notes.md).
  Two premises the tool currently fails: the screen runs *only* on host Ollama, so a
  GPU-less user cannot run the pipeline at all; and nothing installs worker deps,
  creates the DB, or reports what is missing, so `onboard-me` starts at a step 2 whose
  step 0 does not exist. **Five tracks**, no code yet:
  1. **Screen backends** — `SCREEN_BACKEND = ollama | codex | claude-code |
     claude-api | openai-api | none`, default `ollama`. Six configs, three adapter
     shapes (HTTP+schema · CLI subprocess+`--output-schema` · deterministic-only).
     **Auto-detection must never select a paid backend.** Also: batch the screen (the
     domain-verdict bleed that parked `DEFAULT_BATCH_SIZE = 1` is a cross-JD
     *judgment* problem and does not transfer to per-JD fact extraction) and run
     screens concurrently (`run_score` screens in a serial loop today).
  2. **Universality fixes** — Telegram is currently *mandatory*
     (`run_once` does `env["TELEGRAM_BOT_TOKEN"]` → `KeyError`), so someone happy to
     review the Discovered Jobs tab cannot run the worker; `make setup` (deps + DB +
     template copies) and `make doctor` (pass/fail preflight); document that `OLLAMA_HOST`
     already supports a remote/cloud Ollama, which `SETUP.md` currently denies.
  3. **`onboard-me` Step 0** — run `make setup`, then `make doctor`, then pick the
     provider path from what is actually installed, before the interview. The skill
     reads `doctor` output instead of carrying its own prereq prose.
  4. **Agent portability** — `SKILL.md` is a cross-agent standard, but the *paths*
     differ: Claude Code reads `.claude/skills/`, Codex reads `.agents/skills/`, so
     both skills are invisible to every agent but Claude Code. Move to
     `.agents/skills/`, symlink `.claude/skills`, add a root `AGENTS.md` (a Linux
     Foundation standard read by 30+ agents; the repo has none).
  5. **Sponsorship screen rework** — the defect below; shares the screen call with
     track 1, so the two should land together.

  **Open questions:** the OpenAI API model string is unchosen; `gpt-5.6-luna` is the
  pick for the Codex screen (`run.py` rejects it, but that verdict was measured on
  *fit scoring* — a calibration-sensitive judgment where its loose spread was fatal —
  and does not transfer to extraction; re-measure, do not assume); and it is unverified
  whether Claude Code discovers skills through a symlinked `.claude/skills`.

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Two axes:**
*severity* sets the bucket (a shipped defect that loses prepared work ≠ an unbuilt
nice-to-have), and within each bucket items run **easiest → hardest** with an effort tag —
**XS** (~an hour) · **S** (~an afternoon) · **M** (~a day + a design call) · **L**
(multi-day / new dependency / architectural). Blocked items name their blocker.

### Do next — the pick order

The buckets below are a *catalogue* sorted by severity. This is the **queue**: what to
take first and why. Each numbered item is independently pickable.

**P0 — the first run against the 172-board watchlist.** The body-required guard shipped
2026-07-22 (CHANGELOG), which was the blocker: every empty-list-endpoint board — the two
Citadel rows included — now yields nothing instead of poisoning the DB with permanent
title-only rows. **Citadel decision: keep both rows as-is** — the guard makes them
non-destructive, the detail leg's circuit-breaker bails after 3 empties, so the residual
cost is a handful of Chromium renders per cycle and the rows self-heal if the Cloudflare
behavior changes. Revisit only if the run shows the renders are expensive.

1. **Run the pipeline** — `[S · FETCH DONE 2026-07-22 (full, clean); scoring in bounded
   batches]`. A `--fetch-only` pass (unbuffered log) completed cleanly (exit 0) over the
   full 172-board watchlist with `enable_browser_sources: true` — the coverage question
   is answered. Intake: **7,746 postings total, 4,035 `new`** across all **11** sources
   (custom 1,411 · greenhouse 704 · browser 662 · workday 588 · phenom 238 · ashby 178 ·
   icims 155 · smartrecruiters 69 · workable 18 · lever 11 · pinpoint 1). Only **one board
   failed**: `phenom/careers.qualcomm.com` 429-rate-limited at deep pagination
   (start=930), isolated, rest continued. **Body guard fired live and held:** dropped
   citadelsecurities 7 · citadel 3 · **MSCI icims 43** (a *new* empty-JD board — see
   below) — and **0** bodyless rows reached `new`. **Scoring** is now bounded, not blind:
   `--score-limit N` caps the paid scorer and thin JDs (< 200 chars) skip it entirely
   (CHANGELOG). First bounded batch (`--score-only --score-limit 50`) ran 2026-07-22:
   50 rows → 9 screen-discarded, 41 fit-scored (**41 Codex messages, ~2% of the weekly
   budget**; 0 thin-JD skips — these all had full JDs), **4 match/match → notified**
   (Akuna x2, DRW, HRT — all on-target; DRW notified at score 58, confirming the
   verdict, not the number, gates notify). Ordering (`score DESC, id ASC`) meant the 50
   oldest `new` rows were the original **greenhouse+phenom** config boards, so **the
   recipe (`custom`/`browser`) scored path is still unexercised** — a targeted score of
   those rows is the next check. The remaining ~4k `new` rows await an operator call on
   scoring at scale. Still open: `custom` is ~a third of the intake — a `title_filter`
   tightening question, not a fetch bug.

**P1 — the repo is public and only its author can run it.** Provider-choice tracks, in
dependency order (design: [In flight](#in-flight)).

2. **Track 2, universality** — `[S]`. Telegram is a hard `KeyError` (`run.py:257`), so a
   user content with the Discovered Jobs tab cannot run the worker at all. Plus
   `make setup` / `make doctor`, and the `OLLAMA_HOST` remote-Ollama correction in
   `SETUP.md`. Cheapest, unblocks the most people, and (1) is a live rehearsal for it.
3. **Track 1, screen backends + track 5, sponsorship gate** — `[M]`. Land together:
   both rewrite the screen call. A GPU-less user currently cannot screen at all, and the
   sponsorship gate — the highest-value check for any sponsorship-needing user — is the
   *only* screen check not using the LLM. Batching + concurrency ride along.
4. **Track 3 (`onboard-me` Step 0)** and **track 4 (agent portability)** — `[S each]`.
   Both are downstream of (2)/(3); 3 needs `make doctor` to exist, 4 is independent and
   can be picked any time.

**P2 — correctness of the scoring path.**

5. **Fit-score gate re-run** — `[S · ~69 Codex messages]`. Gate the 2026-07-22 profile
   edit. Do it *after* (1) so any newly-ingested Java quant-dev row can close the golden
   set's documented Java blind spot in the same pass.

**P3 — coverage and cost, in value-per-effort order.** `browser` `{field}` templates
(`[S]`, unblocks 2 boards) → `custom` HTML mode (`[M]`, drops 6 boards off Chromium and
unblocks Citi/Barclays) → workday prose-date parser (`[S]`, cuts the remaining 6,703
detail calls) → bulk watchlist skill (`[M]`).

**P4 — everything else below.** SSRF residuals, the `@@unique` migration, schema
migration path, deployment/monitoring, dead-link sweep, more adapters, README
screenshot, eval iteration 2. Real, none of it blocking, none of it cheap.

### Defects — shipped behavior that is wrong (should fix)

- **The sponsorship gate misses ~9 of 11 realistic no-sponsorship phrasings** —
  `[M · fix designed, needs a labeled set]`. `NO_SPONSOR_PHRASES`
  (`score/screen.py`) is a closed 12-phrase substring list, so it catches only JDs
  whose wording happens to be on it. Measured against realistic phrasings for a
  candidate with `work_authorization: "needs visa sponsorship"`, these all pass
  through un-disqualified: *"US Citizenship is required"*, *"Must be a U.S. citizen
  or Green Card holder"*, *"requires US Person status as defined by ITAR"*,
  *"permanent work authorization … now and in the future"*, *"unable to offer
  immigration support at this time"*, *"Visa sponsorship is not available for this
  position"*, *"must not require employer-sponsored work authorization"*, *"No H-1B
  transfers"*. Only the two containing a literal listed phrase are caught.

  This is the highest-value gate for any sponsorship-needing user, and it is the
  **one check in the screen not using the LLM** — while degree and clearance, the two
  a phrase list could nearly handle, do. The list is the **D1** fix: the 4B model
  invented `offers_sponsorship: "no"` from silence, so it was taken off the check
  entirely rather than grounded.

  Fix designed (see the notes below): keep the LLM as the primary check but ground
  it in a **verbatim quote** — the model returns the exact JD sentence stating
  sponsorship is unavailable, and code verifies that sentence actually appears in the
  description before acting on it. A hallucinated quote fails the check and the
  posting is *kept*, so hallucination cannot disqualify anything by construction
  rather than by trust — which works on `qwen3.5:4b` too, so D1 needs no
  re-litigating. `NO_SPONSOR_PHRASES` is demoted to a floor that can only *add*
  disqualifications. **Residual risk:** quote-grounding kills hallucination but not
  *misclassification* (a model quoting real-but-irrelevant text — the shape of the
  old "company-sponsored sports teams" false positive, though that was the previous
  substring guard's failure, not the model's). Needs a labeled set
  (*no-sponsorship / offers / silent*) to gate; cheap route is to diff the new screen
  against the phrase list over the ~600 already-scored rows and hand-label only the
  disagreements. (SPEC §7.1.)

### Unverified / deferred — behavior may be fine, but nothing proves it, or a decision is pending

- **Both Citadel watchlist rows return description-less postings — kept anyway** —
  `[S · measured 2026-07-22 · decision recorded 2026-07-22]`. `browser/citadel.com`
  and `browser/citadelsecurities.com` (added
  2026-07-18, never fetched — the last cycle ran 2026-07-13) scrape their listing
  pages fine: 10 postings each, 10/10 on `external_id`, `job_title`, `location` and
  `job_url` (URLs verified well-formed). But **0/10 on `description`** — precisely the
  failure `browser.py:159` predicts: Cloudflare clears once for the listing render,
  then re-challenges the rapid deep-link detail navigations, so every JD comes back
  blank and the 3-empty circuit-breaker bails. `posted_at` is 0/10 too (the cards
  carry no date). The 10-posting count also implies pagination stops at page 1
  (`page.start: 2` renders page 2, gets nothing fresh, breaks).

  Consequence, since the body-required guard shipped: both rows simply **yield nothing**
  — the title-only postings are dropped at `run_fetch` and logged, never written. The
  residual cost is a handful of Chromium renders per cycle (the detail leg's 3-empty
  circuit-breaker bails early).

  **The JD is unreachable at this rung — measured 2026-07-22, do not re-derive.** Three
  probes against `citadelsecurities.com` detail pages, each with the worker's own
  Chromium config (UA + viewport + `--disable-blink-features=AutomationControlled`):
  (a) plain-HTTP GET of the listing → `403`, so the wall is real and it is not a stale
  selector; (b) deep-link `goto` + 15s dwell on `.single-job-post-description` →
  `title='Just a moment...'`, 273-char body, 0 selector matches; (c) same tab,
  **clicking** the card from the already-cleared listing (user gesture + same-origin
  referer) plus a further 30s dwell → byte-identical result. So the detail route is
  challenged regardless of arrival path and does not self-clear in ~45s. Slowing or
  re-ordering the navigations does not help; everything past this rung is a stealth
  plugin / real browser profile / residential proxy, i.e. detection evasion plus a new
  dependency — out of scope for this repo.

  **Decision: keep both rows as-is** — they cost almost nothing and start producing on
  their own if Citadel's Cloudflare behavior relaxes. The only other honest option is
  deleting the two rows; dropping the `detail:` block to take title-only is now a no-op
  (the guard would drop those rows anyway). `quant_job_boards.txt` still lists Citadel as
  unscrapable-by-plain-HTTP, which is true and is why these are browser rows; the wall
  simply also defeats the detail leg.
- **Workday prose-date age-gating — shipped, live reduction unmeasured** — `[S · needs
  a run with `max_age_days` set]`. `parse_stub` now dates `"Posted N+ Days Ago"` prose
  (given `now`), so the max-age gate can drop stale workday stubs before the detail call
  (CHANGELOG, SPEC §7.1). Only the confident English `"N[+] Days Ago"` form is parsed —
  a lower bound on age — so "Today"/"Yesterday" and any other locale/wording leave
  `posted_at` None and are kept; a mis-parse can never drop a good posting. Unmeasured:
  how much of the ~6,703 remaining detail calls this actually cuts (depends on
  `max_age_days` config and how stale each board is) — the enhancement's projected drop
  awaits a live run.
- **Stale-mount recovery is unobserved end-to-end** — `[S · needs a live drill]`. The
  `/api/health` probe + Docker `healthcheck` + `autoheal` sidecar are wired, the
  healthy path is confirmed, and the 200/503 logic has a unit test (`health.test.ts`).
  Unproven: recovery from an *actual* WSL2 stale-bind-mount event — never observed,
  not unit-testable (needs a live event or manual drill). (SPEC §6.)
- **The `custom` and `browser` executors — PROVEN end-to-end 2026-07-22** —
  `[resolved · fetch only]`. Until 2026-07-22 `job_postings` held **zero** rows from
  either source (1,169 postings, all greenhouse/lever/pinpoint/workday), so the whole
  recipe-driven half of the fetch layer was unproven through `run_fetch`: recipe JSON
  round-tripping out of the DB, `enable_browser_sources` gating, per-board error
  isolation, and upsert of recipe-sourced postings had never run together. The
  full 2026-07-22 `--fetch-only` pass exercised all of it: **custom 1,411 `new`** and
  **browser 662 `new`** — the browser rows are google (623), careers.twosigma.com (33),
  and rentec.com (6), all with real JDs (Citadel correctly contributes 0, dropped by the
  guard). So both executors work through `run_fetch`. Caveat: this proves the **fetch**
  path only. The first bounded `--score-only` batch scored the oldest `new` rows, which
  by id were the original greenhouse+phenom config boards — so the scored/notified path
  over **recipe-sourced** rows is **still unexercised**. Closing it needs a score run
  that reaches `custom`/`browser` ids (e.g. a larger `--score-limit`, or scoring a
  source-filtered slice). "Which boards over-produce" is the live follow-up — `custom` is
  ~a third of the intake, google alone is 623 rows.
- **Empty-JD boards ON the watchlist — MSCI icims** — `[XS · found 2026-07-22]`. The
  full fetch pass dropped **43 bodyless postings** from `icims/globalcareers-msci`: its
  iCIMS list endpoint carries titles but no description. Same property as the Uber/Netflix
  tier below, except this one is already on the watchlist. Non-destructive now (the guard
  drops them; the next run will also record them in `feed_unresolved`), but it produces
  nothing, so it is a candidate to drop or to route through a detail-fetch once one
  exists. `citadelsecurities`/`citadel` (browser) are the same story (dropped 7 + 3).
- **Boards deliberately held off the watchlist** — `[XS · decision recorded]`. Nine
  boards were validated but NOT added, for two reasons that are properties of the
  board, not bugs. (1) *Empty JD*: Uber (277 postings), Netflix (463), Morgan Stanley
  (1,350), Brevan Howard (13), Campbell (1) — their list endpoints carry no
  description. Since the body-required guard shipped these are no longer *dangerous*
  to add (they would insert nothing), but they still produce nothing, so adding them
  only buys fetch cost until `custom` gains a chained detail call.
  (2) *Render cost*: Citi (3,567 postings), Barclays
  (1,074), Bloomberg (490), Moody's (249) — a `browser` `detail:` block costs one
  Chromium render per posting with no stub gate (`browser.py:159`), all of it before
  screening. Uber/Netflix/Morgan Stanley become viable if `custom` gains a
  chained detail call; Citi/Barclays if `custom` gains an HTML mode (both above).
- **Fit-score gate not re-run since the 2026-07-22 profile edit** — `[S · costs ~69
  Codex messages · deferred by operator]`. `personal_profile.txt` changed on two
  lines: target #1 widened from "buy-side or prop" to "buy-side / prop / HFT /
  market-making / hedge fund", and the anti-target moved from "Low-latency / HFT / C++
  systems engineering" to "Low-latency systems engineering, in any language, and
  C++/Java systems-level roles where the deliverable is the engine itself rather than
  the research and trading tooling built on it". The point of both edits is that the
  anti-target is a **role**, not an **employer** — an HFT firm is a target-#1 employer;
  the latency seat inside it is not.

  The scorer reads this file verbatim as the domain verdict's target-fit rule, so the
  wording is load-bearing (a past prompt tweak destabilised verdicts where a profile
  edit fixed them). `tools/score_eval.py` has NOT been re-run against the 23-row
  golden set; shipping a profile change wants two consecutive PASS.

  Two specific things to check when it runs. (1) All 23 golden labels were reviewed by
  hand on 2026-07-22 and none rests on the old firm-vs-role conflation — 813 is a
  floor-trader seat, 222 IT/desktop, 824 infra-platform, 592 hardware, 64/125/83
  research/analyst — so no relabelling is expected, and a flip would be a real signal.
  (2) **Blind spot: no golden row is a Java posting**, so the gate cannot detect
  over-rejection of Java-based quant-dev seats at banks (Goldman, Morgan Stanley,
  BlackRock Aladdin, CME, Nasdaq) — exactly the tier-2 employers the watchlist just
  expanded into. Adding one such row to the golden set would close it.

  Note `tools/score_eval.py` has no argparse: any unrecognised flag (`--help`) starts a
  LIVE, quota-spending run. `--selftest` is the free hermetic path.
- **SSRF residual shapes** — `[M]`. Three shapes remain reachable (browser-path
  redirect GET · DNS-rebinding · statically-internal hostnames — accepted meanwhile,
  SPEC §11). Closing the DNS shapes needs a resolve-then-check with a TOCTOU-safe
  connect; closing the browser-path GET needs an intercept-before-connect mechanism
  Playwright's routing API doesn't expose for navigations.
- **`applications` has no DB `@@unique(company_name, job_title)`** — `[M · deferred ·
  deliberate; waits on operator]`. Three transactional app-code paths hold the dedupe
  invariant (`addApplication`, `markJobApplied`, `importApplicationsCSV`). The hard
  constraint needs a backup + dedupe migration first — the real table may hold
  legitimate duplicate rows (re-applications), so `prisma db push` can't build the
  index without `--accept-data-loss`. Deferral operator-confirmed 2026-07-19.
- **No schema migration path** — `[L]`. `prisma db push` keeps no migration history,
  so a *destructive* change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)

### Enhancements — not built, optional

- **Bulk watchlist onboarding as a skill** — `[M · proposed, not built]`. The
  2026-07-22 expansion (49 → 172 boards) ran an ad-hoc pipeline worth encoding:
  read `personal_profile.txt` → parallel company research per target tier → **verify
  every slug independently of the agent that proposed it** → estimate per-board fetch
  cost → gated bulk insert. It is NOT a phase of `onboard-me`: that skill configures
  the *candidate*, and this one consumes its output to find *companies*, so the natural
  shape is a separate skill `onboard-me` recommends as a closing step. Four things the
  run proved are load-bearing: (a) research and verification must be separate passes —
  five agent "verified" claims failed re-running (Workday-needs-a-browser, Wintermute
  bot-blocked, Nasdaq's site name, FactSet's datacenter, Geode SOLVED-but-returns-0);
  (b) squatted slugs are the real hazard — greenhouse `proof` serves a live 216-job
  board belonging to a different company, which poisons the feed more quietly than a
  failure; (c) cost must be estimated *before* insert (a row cheap to add can cost
  3,567 renders to run); (d) the empty-JD check above. `onboard-board` handles one
  board well; nothing handles a hundred.
- **`custom` has no HTML/CSS mode** — `[M]`. Bloomberg, Two Sigma, Citi, Barclays,
  Moody's and Geode are all plain-`requests`-fetchable with no bot wall, yet each is
  forced to rung 3 (`browser` + headless Chromium) purely because `custom` only parses
  JSON / `__NEXT_DATA__`. An `html` mode reusing the browser executor's CSS extractor
  would drop all six to plain HTTP. Related: a `browser` `detail:` block costs **one
  Chromium render per posting** with no stub gate (`browser.py:159`), which is why
  Citi (3,567 postings) and Barclays (1,074) are not on the watchlist.
- **Boards blocked on an executor primitive, not an adapter** — `[L]`. Meta needs a
  fetch-page-then-POST handshake (its GraphQL requires a per-session `lsd` CSRF token
  scraped from the HTML) *and* a scroll hook (the rendered DOM holds 11 of 692 cards
  in a virtualized inner scroller with no URL pagination). Balyasny's Salesforce Aura
  endpoint needs an `aura.context` `fwuid` hash that rotates every release. Recorded
  so the next attempt starts from the known blocker rather than re-deriving it.

- **Discovered Jobs README screenshot** — `[XS]`. The prose is now expanded to Track
  parity (bucket triage, the per-row "why" subline, the fit-assessment modal, bulk
  actions). Still missing: an inline screenshot of the tab to match the "Track"
  images. Needs a seeded throwaway DB (never the real `db/applications.db` — see the
  privacy note in §11/CHANGELOG on the existing screenshots) and a richer fixture than
  the e2e seed, which only populates the Matched + Discarded buckets.
- **Dead-link sweep — board sources uncovered** — `[M · needs a per-board signal]`.
  `run_expire` (shipped) only re-checks **detail sources**, the ones with a per-job
  endpoint. A posting from a board source (greenhouse/lever/ashby/…) goes dead
  silently. Closing it means diffing each board's current listing against the
  ingested rows — a different mechanism, and a *fetch failure* must never be read as
  "the whole board's jobs closed".
- **`onboard-board` skill — eval iteration 2** — `[M · optional]`. Re-run the
  skill-creator eval loop on the add-or-fail flow (with-skill agents add to a
  *throwaway* DB via `--db`) with tougher/undocumented boards — iteration 1 hit 100%
  pass on both configs, so it measured speed (−42% time / −18% tokens), not
  correctness.
- **More board adapters** — `[M · pick a target]`. The adapter pattern
  (`fetch/<source>.py` + `ADAPTERS`/`VALID_SOURCES`, or `fetch_one` in
  `DETAIL_SOURCES`) makes new sources cheap. Leads: LinkedIn's public `jobs-guest`
  endpoint (unauthenticated, zero-dep; personal-use / ToS caveat, keep volume low);
  JobSpy as a possible fallback aggregator.
- **Remaining feed coverage (the `feed_unresolved` long tail)** — `[M · needs
  iCIMS/ByteDance feed routers]`. Resolution sits at ~78% after tier 1. What's left
  is iCIMS + ByteDance — both plain HTTP (iCIMS ships as a list adapter, TikTok as a
  `custom` recipe), but closing the *feed* tail still needs a `resolve_url` host
  router + a per-listing `fetch_one`, which the list adapters don't provide.
  **Dropped:** greenhouse embed-token (job id only, no board slug); SuccessFactors
  (absent from feed).
- **Deployment / monitoring** — `[L · open-ended]`. `ats-web` has a DB-reachability
  healthcheck + `autoheal` (SPEC §6), but there's no metrics/alerting beyond the
  per-job Telegram notification, and the **worker** has no healthcheck — its failures
  show only in the DB/logs. Includes the deferred scraper **canary self-tests** and
  proactive Telegram/banner alerting for silently-broken scrapers (SPEC §9 points
  here).
- **AI fetch+score fallback for unparseable JDs** — `[L · optional]`. Where text
  extraction fails (JS-rendered / bot-walled / odd markup), let the scorer's model
  fetch the job page and score fit directly from the raw page, bypassing
  parse-then-score. Candidate landing spot for the iCIMS/ByteDance tail if a plain
  fetch isn't enough.

#### Architecture / maintainability

- **Cross-service drift — partially guarded** — `[M]`. `test_source_enums_sync.py`
  guards the cheaply-comparable duplicated items (source enums + the low-context
  length literal). **Still unguarded (deliberate scope call — fragile, low value):**
  the `pipeline_status` string literals (scattered across worker + web) and the full
  notify / matched verdict-predicate SQL (`db.py` vs `actions.ts`) — these stay
  documented-not-guarded, hand-duplicated with "must match" comments only.
- **`requirements-dev.txt` duplicates base pins** — accepted (no include mechanism
  exists without adding tooling), but the duplication bit once — see the
  [CHANGELOG](../CHANGELOG.md) geonamescache CI fix. **Standing rule:** any new
  module-load or test-exercised runtime import MUST be mirrored into
  `requirements-dev.txt` in the same commit that adds it to `requirements.txt`.

---

## How to update

This file tracks only *movement*; it should never accumulate a wall of finished
items. When state changes:

- **Starting work** → add an in-flight line under [In flight](#in-flight).
- **Closing a gap / shipping a feature** → remove its line here, add a
  [`CHANGELOG.md`](../CHANGELOG.md) entry (history), and update the matching section
  of [`SPEC.md`](./SPEC.md) (the capability map / behavior) — **all in the same
  commit**.
- **Discovering a new gap** → add it to [Open work](#open-work) in the right severity
  bucket, placed **easiest-first** with an effort tag (`[XS/S/M/L · blocker]`). Keep
  severity honest: defects (broken) above unverified properties above enhancements
  (optional).
