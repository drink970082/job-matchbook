# Backlog — current triage

[ROADMAP](ROADMAP.md) owns the product order. This file holds unselected work:
residual defects, unverified behavior and optional extensions; [PROGRESS](PROGRESS.md)
owns branch claims and current limitations, [REJECTED](REJECTED.md) the levers already
measured dead. Counts below are samples: revalidate an entry against current code and
data before selecting it.

## Relevant to the source/tool product

- **MCP free-text arguments that look like JSON are decoded:** the SDK JSON-parses a
  string argument typed `str | None` when it parses as JSON, so a note such as `{"a":1}`
  through `update_application_notes` (or `record_application`'s `notes`) fails
  validation. `set_jev_profile` avoids it with plain `str`; the other text tools do not.

- **Source lifecycle adapter coverage:** the bounded one-shot refresh supports
  SmartRecruiters; other boards need verified source-specific identity and closure
  signals before they can be refreshed safely. No broad backfill is selected.
- **JD quality:** thin/bodyless Microsoft and recipe rows, detail-fetch failures and
  date fallbacks need per-source observation. Full-JD quality feeds the screen, JEV and
  the MCP reader alike. Large legacy backfill counts require fresh dry-runs.
- **Intake policy:** inspect title/location/age gates before moving preferences into the
  DB (#157). Cutting discovery to match a model budget is not the product priority.
  Onboarding a new user's free filters is an open design discussion in
  [#203](https://github.com/drink970082/job-matchbook/issues/203).
- **Usage telemetry:** after a `codex` screen the pass takes one best-effort HTTP usage
  snapshot (`quota.json`), which has failed intermittently with 403. It is a
  display, not a spend limit; JEV's limit is `--jev-max-usd`.
- **Infrastructure:** retain SQLite directory/WAL mounts, health/autoheal verification,
  schema ownership and privacy boundaries.
- **Data integrity:** application uniqueness/identity (no DB
  `@@unique(company_name, job_title)`; three transactional code paths hold the dedupe,
  and the real table may hold legitimate re-applications, so the constraint needs a
  backup and dedupe migration first), literal URL matches vs normalized requisitions,
  and schema migration strategy (`db push` keeps no history) remain scoped maintenance
  questions, not reasons to alter application history.

## Fetch

- **`run_expire` reads a non-404 closed answer as alive.** Every stored row of the four
  detail sources yields a well-formed key, but only a 404/410 closes. smartrecruiters'
  `fetch_one` returns `None` on `active: false`; jobvite returns `None` when the page has
  no JobPosting JSON-LD (a closed job that redirects to the career home); oracle builds a
  posting even from an empty requisition payload. All three count as alive. Whether each
  board answers a really closed job with 404, 200-inactive or a redirect is unverified
  live; workday answers a nonexistent `/job/` path with a JSON 404.
- **Wasted re-fetch GETs.** Workday's `existing_external_ids` prune never matches (the
  feed carries `externalPath`, the DB stores the GUID), so every feed-surfaced Workday
  listing costs one CXS GET per pass; Microsoft files about 50 `empty_description` rows
  per pass for positions already stored with full JDs. Both are cost only. Relatedly,
  `detail_fetch_failed` cannot tell a 404 from a timeout or 429 (bare `except`).
- **Feed age gate judges Simplify's `date_posted`**, not `date_updated`: about 10% of
  feed listings refused as stale were still being refreshed. Cheap fix if wanted:
  `max(date_posted, date_updated)`. `max_age_days` governs both watchlist and feed, with
  no per-feed override.
- **Rate limits:** bounded retry + salvage exists only in `phenom`; port it when a second
  board 429s. Whether it survives a live phenom WAF trip (a 403 deep in pagination) is
  unmeasured.
- **`custom` offset paging with `body_param` sends the row offset as the page
  number.** `_page_request` writes `n` into the body param, and `fetch` advances `n` by
  `len(postings)` for `type: offset`, so a board that expects a page index (apple) skips
  pages: 978 of 1,008 stored apple rows were not seen on the last pass. This is one of
  the reasons `custom` is excluded from absence closure.
- **A well-formed recipe can still miss the live payload:** the recipe schema rejects
  bad keys and values at write time, but an `item_path` or field path that matches
  nothing in the real response only shows at fetch time, as an empty board or
  `feed_unresolved` rows. A dry run before add is #239.
- **`custom` has no chained detail call.** It is what Uber/Netflix/Morgan Stanley need
  (list JSON without a body), and what makes an `html` mode useful: an `html` recipe can
  only produce a description if the listing card carries the full JD, so without it
  every row is dropped as bodyless. An `html` executor must accept a list-form
  `description`, raise on `page: {type: url}` (silently returning page 1 looks like
  success), let `type: page` start at 1 (most server-rendered pagers are 1-indexed),
  decode `resp.content` rather than `resp.text` (bodies without a `charset` mojibake),
  and test for a non-empty description, not just the field set.
- **Boards blocked on an executor primitive:** Meta (page-then-POST with a per-session
  `lsd` token, plus a virtualized scroller); Balyasny's Salesforce Aura endpoint (a
  `fwuid` that rotates each release). Jacobs Levy and Balyasny's static listing are
  reachable with the `{field}` URL template and await an `onboard-board` run.
- **Un-hydrated stub discards have no way back:** a stub-gate discard is stored with an
  empty description, and `upsert_postings` never re-hydrates, so a later
  `candidate.locations` edit cannot reclaim it. `run_fetch` already drops bodyless rows
  to keep them re-fetchable; doing the same (or a re-fetch marker) would fix it.
- **Feed coverage tail:** iCIMS and ByteDance feed listings need a `resolve_url` host
  router plus a per-listing `fetch_one`.
- **`util.to_iso_date`** returns a 10-char slice of an unparseable string (and
  `1970-01-01` for `True`) where its docstring promises `None`. Fixing it drops postings
  now kept by `max_age_days`, so it needs the PRINCIPLES 3 justification.
- **SSRF residual shapes** (SPEC §11): browser-path redirect GET, DNS rebinding and
  statically-internal hostnames. The DNS shapes need resolve-then-check with a
  TOCTOU-safe connect; the browser GET needs an intercept-before-connect mechanism
  Playwright does not expose for navigations.

## Screening work

- **Location gate: country aliases and regions.** `Russia`, `Turkey`/`Türkiye`, `Korea`
  and `Ivory Coast` resolve to no country (alias gaps in `_country_code`), and only North
  America / Americas are regions (`Europe`, `EMEA` name no members), so a user who lists
  one of those discards postings in it. Matters more since #206 removed the assumed US.

- The expanded Luna screen result has no recorded effort. Do not claim medium-specific
  accuracy or start a large unchanged eval to repair provenance automatically.
- **Sponsorship sentence window on bullet lists:** `_sentences` splits only on `[.!?]`
  after collapsing whitespace, so a period-free bullet block is one "sentence". On a
  random 3,000 live descriptions the median longest-sentence share is 13% and 5% exceed
  half the JD. The fix (split on line breaks too) changes every snippet, so it wants its
  own branch, a settled corpus and a before/after gate run. Snippets are also spliced
  into the prompt uncapped.
- **`location_verdict`'s `resolved` / `ask_llm` are discarded:** its docstring says an
  unresolved location must not be recorded as a pass, but `resolve_location` drops both
  fields and `deterministic_screen` always writes `location.pass`. Resolving it changes
  screen outcomes and a SPEC §9 clause. A free model fallback for the ~3% of strings the
  gazetteer cannot resolve (location tiers 2-3) is unbuilt.
- Blind/empty answer handling and local-model degree/clearance limitations remain
  relevant when changing the screen; the blind-backend fork is SCORING §3.7. Read SCORING
  and REJECTED before revisiting them.
- More screen providers and cache experiments require a demonstrated need and a specific
  evaluation question.

## Web, docs and skills

- `deleteApplication`, `deleteHistoryItem`, `exportApplicationsCSV`,
  `importApplicationsCSV`, `getCategories` and `setCategories` are covered only by the
  excluded integration suite (`*.int.test.ts`); `getApplicationHistory` has no test.
- `onboard-me` evals are owed a run against the current skill; `onboard-board` eval
  iteration 1 hit 100% on both configs, so a second iteration needs harder boards.
- A **bulk watchlist onboarding** skill (target profile -> company research -> slug
  verification by a separate pass -> per-board cost estimate -> gated insert). Squatted
  slugs (a live board belonging to another company) and render cost are the hazards
  `onboard-board` does not cover at scale.
- A README screenshot of the read-only jobs view, from a seeded throwaway DB.

## Monitoring

- The worker is supervised and `ats-web` has a DB-reachability healthcheck + autoheal,
  but nothing detects a worker that is up and producing nothing (a dead adapter, a blind
  screen backend): no metrics, alerting or scraper canaries. The healthcheck's response
  to a real WSL2 stale mount is unobserved; renaming the DB's directory under a
  throwaway container simulates it (SPEC §6).

## Issue ownership

The open workflow gate and conditional extensions are linked in ROADMAP.
Their status/dependencies live on GitHub; this file retains background and unselected
ideas. Recommendation history (#95) is conditional on observed repeats.

## Deferred extensions

- MCP writes beyond epic #152's scope: external-job import, saved assessments or Brief
  delivery history.
- Agent-invoked official-page refresh and existing-fetch interaction, with bounded inputs
  and explicit mutation/authorization semantics.
- Standard search/fetch compatibility for clients that require it.
- New boards and bulk onboarding after choosing actual coverage gaps. Follow onboard-board;
  do not add an adapter when a reviewed recipe suffices. Unexplored sources: LinkedIn's
  public `jobs-guest` endpoint (ToS caveat, low volume) and JobSpy as an aggregator.

## Cleanup policy

Keep private corpora, human answers, reports and unmerged branch work intact. Preserve
negative findings; remove obsolete universal priorities and instructions to repeat them.
This file is not authority to spend allowance or restart a deferred run. Do not infer
that a planned feature, an old passing experiment or a host-only deployment script is
available in a clean clone.
