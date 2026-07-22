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

- 🚧 **Run the pipeline as a daemon** — the recurring 24h scheduler
  (`python -m ats_worker.run`) remains the operator's standing launch step; passes
  are currently run by hand.
- 🚧 **General-purpose pivot (in progress).** Broadening the product from a quant/SWE
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

---

## Open work

Surfaced from the code and history — observations, not a roadmap. **Two axes:**
*severity* sets the bucket (a shipped defect that loses prepared work ≠ an unbuilt
nice-to-have), and within each bucket items run **easiest → hardest** with an effort tag —
**XS** (~an hour) · **S** (~an afternoon) · **M** (~a day + a design call) · **L**
(multi-day / new dependency / architectural). Blocked items name their blocker.

### Defects — shipped behavior that is wrong (should fix)

*Empty — no known shipped defects open.* (All previously tracked defects were fixed;
history in the [CHANGELOG](../CHANGELOG.md).)

### Unverified / deferred — behavior may be fine, but nothing proves it, or a decision is pending

- **Stale-mount recovery is unobserved end-to-end** — `[S · needs a live drill]`. The
  `/api/health` probe + Docker `healthcheck` + `autoheal` sidecar are wired, the
  healthy path is confirmed, and the 200/503 logic has a unit test (`health.test.ts`).
  Unproven: recovery from an *actual* WSL2 stale-bind-mount event — never observed,
  not unit-testable (needs a live event or manual drill). (SPEC §6.)
- **The `custom` and `browser` executors have never produced a posting in
  production** — `[S · needs one live run]`. Both are unit-tested against fixtures and
  both were exercised live by hand on 2026-07-22, but `job_postings` holds **zero** rows
  from either source: 1,169 postings, all from greenhouse/lever/pinpoint/workday. The
  last pipeline run was 2026-07-13; every `custom`/`browser` row (Jane Street,
  D. E. Shaw, Amazon, ByteDance, TikTok, both Citadel entries, and the 2026-07-22
  additions) was added *after* it. So the whole recipe-driven half of the fetch layer
  is unproven end-to-end **through `run_fetch`** — recipe JSON round-tripping out of
  the DB, `enable_browser_sources` gating, per-board error isolation, and upsert of
  recipe-sourced postings have never run together. The first real cycle is the test.
- **Boards deliberately held off the watchlist** — `[XS · decision recorded]`. Nine
  boards were validated but NOT added, for two reasons that are properties of the
  board, not bugs. (1) *Empty JD*: Uber (277 postings), Netflix (463), Morgan Stanley
  (1,350), Brevan Howard (13), Campbell (1) — their list endpoints carry no
  description, and the body-required guard (`_valid_posting`) is applied only on the
  feed path (`pipeline.py:130`), so these would insert title-only rows and be scored
  blind on the paid backend. (2) *Render cost*: Citi (3,567 postings), Barclays
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
- **Workday stub gate cannot use `max_age_days`** — `[S · needs a prose-date parser]`.
  The `drop`-only gate shipped 2026-07-22 cut workday detail calls 14,902 → 6,703
  (-55%) on the 28-board watchlist, but only via `title_filter`/`title_exclude`. The
  list stub's sole date is prose (`"Posted 30+ Days Ago"`, `"Posted Today"`), so
  `parse_stub` sets `posted_at: None` and the age filter errs toward keeping. Parsing
  that string would drop much of the remaining 6,703 on stale boards. Deferred because
  the wording is locale- and tenant-dependent and a mis-parse silently drops good
  postings — the failure mode the null-keeps-it default exists to avoid.
- **`browser` recipes have no `{field}` URL template** — `[S]`. `custom` recipes
  interpolate `{dotted.field}` into `url`; `browser` recipes cannot, so a board whose
  cards carry no `href` (the id is in a `data-*` attribute and routing is JS-side) can
  only produce a broken or empty `job_url`. This is the *sole* blocker for Balyasny
  (`data-id="…_REQ8036"` → `/s/details?jobReq={data-id}`) and Jacobs Levy (5 roles,
  one static page, apply-by-email). Closing it in `_recipe.apply_css_fields` unblocks
  both without touching an adapter.
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

- **Starting work** → add a 🚧 line under [In flight](#in-flight).
- **Closing a gap / shipping a feature** → remove its line here, add a
  [`CHANGELOG.md`](../CHANGELOG.md) entry (history), and update the matching section
  of [`SPEC.md`](./SPEC.md) (the capability map / behavior) — **all in the same
  commit**.
- **Discovering a new gap** → add it to [Open work](#open-work) in the right severity
  bucket, placed **easiest-first** with an effort tag (`[XS/S/M/L · blocker]`). Keep
  severity honest: defects (broken) above unverified properties above enhancements
  (optional).
