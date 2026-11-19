# Engineering catalogue — retained investigations

> **Status:** deferred/untriaged technical context. [ROADMAP](ROADMAP.md) owns
> priorities; [BACKLOG](BACKLOG.md) owns current triage. Counts and cost claims inside
> individual entries are samples requiring revalidation, not live deployment state. Do
> not execute old evals, cut intake, add providers or change defaults merely because an
> entry proposes them. [EVALUATION](EVALUATION.md) governs model work. The fit scorer
> is removed; entries describe the screen, fetch, web and infra as they are now.

## Unverified / deferred — behavior may be fine, but nothing proves it, or a decision is pending

- **Medium-effort screen corpus accuracy has no measured provenance** —
  `[SCREEN · XS · evaluation provenance]`. Codex Luna/medium is available and passes
  the bounded production smoke, but the existing expanded 103-row comparison (zero
  false disqualifications, recall 30/37) does not record effort. Runtime success is
  not corpus accuracy evidence. Do not rerun the unchanged evaluation solely to attach
  an effort label to the historical measurement.

- **The blind-backend residual: `sponsorship_labels: null` and `[]` still reach the phrase
  floor** — `[SCREEN · open by decision, the operator's call]`. The fork is stated as one
  in SCORING §3.7. A live-but-blind response is deliberately **not** flagged
  `provider_error`, so the floor stays an independent deterministic signal and a JD that
  literally says *"we do not sponsor work visas"* is still caught with no model data. The
  counter-argument — a blind backend then discards on a substring the model never
  condemned, and scores as a breaker *success* while doing it — is real and unresolved.
  **The lesson worth keeping:** the first cut defined "blind" as "no `screen` object", and
  the 4B drops that wrapper on ~1 call in 100 while returning a complete correct verdict
  flat — so it threw away good answers and made `make eval-screen` unrunnable. No unit test
  knew the flat shape existed. **A shape assumption is only as good as the live run that
  contradicts it**, and the blind check and the verdict reader must share one predicate.

- **`make eval-screen` measures far less than its headline numbers imply** —
  `[SCREEN · S · sponsorship half still thin]`. The gate is real and it caught real
  defects; what is wrong is reading its per-requirement scores as measurements of the
  *model* rather than of the corpus. **The sponsorship half rests on 11 gate-eligible rows
  of 21**, because a golden non-`refuses` row that retrieves no snippet cannot be moved by
  anything the classifier does. Raising it further means hand-picking more rows.
  **The corpus is gitignored, so this entry is the only record of what it contains and
  why.** 103 rows. The conventions below are load-bearing for every row added later:
  - **A clearance token in a NON-security sense is what makes the clearance half able to
    fail at all.** 14 golden-`false` rows carry one: customs clearance (Optiver 727),
    import clearance (TikTok 2992), construction permits (Micron 10203), compliance
    pre-clearance for personal trading (Goldman 11907), university "BACKGROUND
    CHECKS/CLEARANCES" (Penn State 24853-24857), background-check clearance (Motorola
    24978), **CACI 25018/25019/57108 — a defense contractor whose JD says `Minimum
    Clearance Required to Start: None`** — and BlackRock 88648, titled *"Trade Clearance &
    Settlement"*. Without rows like these, `_check_clearance` short-circuits on the
    evidence floor and **no clearance regression is detectable**.
  - **A genuinely *optional* security clearance does not exist in this data.** The whole DB
    has **zero** rows saying "clearance preferred / a plus / not required"; searches that
    seem to find them are matching section boundaries, which is the bullet-JD defect below
    biting the *search* rather than the snippet window.
  - **Operator convention:** *"must be able to obtain and maintain a TS/SCI clearance"* is
    `requires_clearance: **true**`. For a candidate with no clearance who needs
    sponsorship it is a hard bar. The ~38 "ability to obtain" rows are therefore golden
    `true` — they improve **recall** measurement and cannot help the tautology, since only
    golden-`false` rows produce a false disqualification. Excluded as ambiguous: mthree
    25411, ASSYSTEM 25388, CACI 25021 (`DOJ MBI` is an investigation, not clearly a
    clearance).
  - **Duplicate JD shapes are excluded on purpose** — 3 of Jump Trading's 8 identical
    sponsorship rows were taken; the rest repeat one shape verbatim and would inflate the
    count without adding signal.
  - **Candidate selection must be done by hand, and this is the durable lesson.** A regex
    sweep for offer-language returned 91 rows and was wrong on two whole companies:
    Qualcomm matched on *"reasonable **accommodations**"* while its JDs say *"not eligible
    for Qualcomm immigration sponsorship"*, and Microsoft matched despite *"unable to
    sponsor a work visa"*. Read every row before it enters the corpus.
  - **A label must be supportable by the row's own excerpt.** `--selftest`'s
    `unsupportable_bars` invariant asserts that a row labeled as a bar carries that
    requirement's vocabulary in its excerpt+title — without it, an excerpt truncated at the
    1600-char cap silently deflates recall while looking like a model miss. Rebuilding such
    an excerpt cannot use `sponsorship_snippets` (period-free JDs return the whole body and
    truncate again); use a +/-780 *character* window centred on the match.

- **The sponsorship `+/-1 sentence` window degenerates to the whole JD on bullet-list
  postings** — `[SCREEN · S · verified]`.
  `_sentences` collapses whitespace (so newlines and bullets are gone) and splits only on
  `[.!?]`, so a JD whose bullets carry no terminal punctuation is **one sentence** and the
  documented "~400 chars" window becomes the entire description. The clean case is id
  4636: two sentences, then a period-free bullet block, so its *whole* 1606-char excerpt
  comes back as a single snippet. **Three of the four rows first cited here are an
  artifact of measuring on the corpus** — 1154/2807/462 are 2-3 sentence *excerpts*, where
  a +/-1 window covers everything for a trivial reason; their real JDs are longer. So
  re-measure on live `description` values, not excerpts, before quoting a rate.
  This dissolves the per-snippet scoping the IMC 465/490 argument rests on — an offer and
  a scoped refusal inside one period-free block get **one** label — and SPEC §7.1 claims
  this design avoids exactly that ("'paragraph' is unbounded and degenerates to the whole
  JD"). Secondary: snippets are spliced into the prompt untruncated while the JD block is
  capped at `num_ctx*2`, so the snippet payload is uncapped budget. The fix is splitting
  on line breaks as well as `[.!?]`, which changes what every snippet contains and so
  needs a gate re-run — hence recorded rather than done.
  **Measured on live descriptions, the rate is far lower than "degenerates to the whole
  JD" implies.** Over a **random 3,000** of the 9,584 live `description` values >=800
  chars, through the real `_sentences`: the **median**
  longest-"sentence" share of a JD is **13%**; **140 (5%)** have one "sentence" covering
  more than half the description; **1 (0.03%)** is genuinely a single sentence. So the
  catastrophic shape is very rare and the too-wide shape is uncommon — and both were
  previously quoted off 2-3 sentence *excerpts*, where a +/-1 window trivially covers
  everything.
  **Any measurement here must randomize over the id range and say which sample it used.**
  `ORDER BY id LIMIT 600` gives 27% / 14% and a random 3,000 gives 13% / 5% for the same
  property — age of the sample, not the splitter, drives the headline. (A "0.2% single
  sentence" figure once quoted here counted rows whose longest sentence exceeded 95% of the
  JD; the true `len(_sentences(d)) == 1` count is **zero**.)
  **Not fixed, and the reason is measurement hygiene rather than effort.** Shipping the
  splitter alongside a corpus change would move two variables at once and no gate result
  could be attributed to either. It wants its own branch, a settled corpus, and a
  before/after — not a bundle.
  **Independent evidence it is real:** two separate candidate-search heuristics were both
  defeated by these missing boundaries — one ranked Microsoft
  `CTJ - Poly` roles as *soft* clearance because `"…verified US government Clearance"`
  closes one block and `"Preferred Qualifications:"` opens the next. The defect bites
  anything that reasons about JD structure, not only `sponsorship_snippets`.

- **Sponsorship recall is a DELIBERATE, pinned trade** — `[SCREEN · open by design]`.
  Retrieve-then-classify took false disqualifications 2 → 0 (behavior in SPEC §7.1,
  reasoning in CHANGELOG). What stays open is the other direction: the
  `sponsor`-only retrieval vocabulary gives up bars phrased without that word — **7 of the
  13 corpus must-flag sentences** — and each is a miss that keeps the posting and
  reaches JEV or the human. `test_the_narrowed_vocabulary_names_exactly_which_bars_it_gives_up`
  pins the count in **both** directions so the trade cannot drift silently.
  **Do not widen the vocabulary to "fix" it.** Every false positive ever recorded on this
  path came from a word that is not "sponsor" — `citizen` (EEO boilerplate, "a good
  citizen in our monorepo"), `visa` (the payment network), `authoriz` (OAuth/RBAC),
  `right to work` ("…in an environment where"). Widening buys recall in the cheap
  direction and pays for it in the expensive one.
  **Two predictions this file made before the build were wrong, and that is the durable
  lesson.** (1) It said all three regex vetoes become unnecessary once a classifier reads
  the sentence; `_PREFERENCE_ONLY` had to be restored — the 4B calls *"prioritizing
  applicants who … do not require sponsorship"* a refusal, all three draws. (2) It said the
  classifier would close IMC 465/490; what actually closed them was stopping a *miscounted*
  answer from falling through to `NO_SPONSOR_PHRASES`. A design argued from first
  principles still needs the measurement.

- **The location gate's tiers 2 and 3 — not built** — `[SCREEN · M]`. Tier 1 is the
  evidence-tiered gate (SPEC §7.1; the trade is pinned in CI at 0 false discards over
  1,611 live strings, residual leak exactly 6 strings / 14 rows). **Still open:** a free
  Ollama fallback for the 3.1% of rows the gazetteer cannot resolve.

- **Workday prose-date age-gating is a dead lever — the reduction is ZERO and the gate
  structurally cannot fire. Do not re-open it** — `[FETCH · closed]`.
  **Workday's prose ladder tops out at the terminal bucket `"Posted 30+ Days Ago"`** — a
  400-day-old posting and a 30-day-old one emit the identical string. `_stub_age_days`
  reads `30`, `parse_stub` sets `posted_at = now - 30`, and `_too_old`
  (`fetch/__init__.py:83`) tests `(today - posted).days > max_age_days`, i.e. `30 > 30` →
  False → kept. **30 is the largest age this parser can ever emit, so a strictly-greater
  test against `max_age_days: 30` never fires.** `max_age_days: 29` would switch the whole
  `30+` bucket on with no code change — but it tightens every other board too, which is a
  far larger blast radius than the calls it buys here.
  **And it buys almost nothing, because the two workday boards carry 4 postings total.**
  Millennium (`mlp`) lists **zero** — not a broken slug (`200 {"total":0}`, while a bogus
  site id under the same tenant returns `404 S21`); the site is live and publishing
  nothing, so it is a zero-yield watchlist row and joins the msci/citadel deletion
  decision below. Arrowstreet is a 4-posting campus board, 2 of which the title gate
  already drops as `Intern, Summer 2027`.
  **The ~6,703 detail-call figure quoted elsewhere is the 28-board post-stub-gate total**,
  and workday's share of it is 4 — about 0.06%. The prose-date parser cannot move that
  number however it is tuned; the remaining detail-call cost lives on the phenom two-step
  boards. Parse coverage is 100% (14/20/21/30+ days, no "Today"/"Yesterday"/locale
  strings), so the gate is neutralised by the threshold, not by parse misses.
- **Boards behind a bot wall — the stealth transport is the rung, and it is cheap** —
  `[FETCH · reference]`. Citadel was the worked example and is now resolved: both rows
  yield full JDs (`citadelsecurities.com` median **3,432**, `citadel.com` **2,878** chars,
  10/10, zero empty) through `playwright-stealth` applied at context creation. Kept here
  because the *reasoning* generalises to the next walled board.
  **What the earlier probe series got wrong is instructive.** It ruled the next rung out
  as "a stealth plugin / real browser profile / residential proxy — detection evasion plus
  a new dependency, out of scope". Two of those three are indeed out of scope; the first is
  208 KB in an already-optional extra, needs no proxy and no profile, and was the answer.
  **Placement is the whole fix, and the obvious API is the wrong one.**
  `Stealth().use_sync(sync_playwright())` works; the per-page `Stealth().apply_stealth_sync(page)`
  silently under-patches and does not. Six arms failed on the per-page form — with and
  without the SSRF route guard, with and without a UA override, with crawl4ai's full
  launch-flag set, with a 14s fixed dwell. If a future board resists, check the placement
  before concluding the library is spent.
  **`citadel.com` never needed it.** It cleared on unmodified playwright at 2,414 chars
  while `citadelsecurities.com` was still interstitial — so "both rows are 0/10" was already
  stale before this work. Re-measure per host; a wall is not a company-wide property.
  **Next rungs, if one is ever needed:** Patchright is the drop-in Chromium upgrade
  (CDP-level patches, no code change); Camoufox patches Firefox at the C++ level but costs
  200MB+ RAM per instance and ~42s per Turnstile challenge, which is the wrong shape for a
  6x/day pipeline. Every open-source patcher leaks after browser updates.
- **Stale-mount recovery — the recovery leg is proven, detection of a real event is not** —
  `[INFRA · S · needs a real event]`. A live drill with a throwaway container
  (`--label autoheal=true`, always-failing healthcheck) confirmed the recovery leg
  end-to-end: unhealthy at ~17s, `autoheal` logged *"found to be unhealthy - Restarting
  container now"* and restarted it ~31s after start. So label + Docker socket + poll
  interval all work; combined with `health.test.ts` (200/503 logic) the only unproven
  link is **detection** — that a real WSL2 stale mount actually makes Prisma's probe
  fail. A `chmod 000` drill on the live DB left `/api/health` at **200 for 5 minutes**,
  because Prisma holds an open fd and POSIX checks permissions at `open()`, not on reads
  through an existing descriptor. So `chmod` is not a valid proxy, and any failure mode
  that spares open fds would slip past the probe; the observed real symptom is
  `SQLITE_CANTOPEN` (an *open* failure), which would trip it.
  **What the probe can and cannot see was settled by drilling three candidate probes
  against four filesystem failures** (matrix in SPEC §6). **`SELECT 1` and a `sqlite_master`
  read are indistinguishable in every mode** — once the connection is open both read
  through the same already-open fd, the same fact that made `chmod` a bad proxy. Nothing
  detects a break that happens *after* connect; that is accepted rather than fixable. The
  mode that discriminates is a **missing DB file**, where SQLite silently creates an empty
  database and weaker probes report healthy forever against a tracker with no data — so the
  probe names a real table (`SELECT 1 FROM job_postings LIMIT 1`) and that becomes
  `no such table` → 503 → autoheal restarts.
  **What is unobserved is narrow:** not "detection", but detection of a *real WSL2 stale
  mount specifically*. The probe's strength was argued for two rounds and only measurement
  settled it.
  (2) Detection **is** simulable, just not by `chmod`: rename the *directory*
  holding the DB, so a fresh `open()` fails while the existing fd survives — the shape of a
  stale mount. Throwaway copy, throwaway container, same rig as the recovery drill.
  (SPEC §6.)
- **`onboard-me` evals are owed a run** — `[DOCS · S]`. The harness is subagent-driven and
  has not run against the current skill. The behavioral assertion worth a run: an agent
  leads with `make setup` + `make doctor` and reads the status lines instead of treating
  every row as mandatory.
- **`detail_fetch_failed` conflates a 404 with a transient timeout or 429** —
  `[FETCH · XS · labelling limit, not a defect]`. `_detail_fetch` catches bare `Exception`
  without inspecting status, so the reason string cannot distinguish them. Neither is a
  scraper break, so nothing downstream is wrong; the record is just less useful than it
  reads.
  **Do not re-investigate the workday "detail-fetch collapse — scraper may be broken"
  warning it sits behind: that is dead reqs, measured.** `feed_unresolved` carries zero
  `empty_description` rows on the feed path (an unparseable body would file as one), the
  same tenants succeed and fail in adjacent passes, and the failing URLs churn rather than
  recur — the signature of a delisted req, not a parser break. It repeats forever because
  workday's `existing_external_ids` prune never matches (the feed carries `externalPath`,
  the DB stores the GUID; 0 of 2,598 workday rows have an `external_id` starting with
  `/`), so every feed-surfaced workday listing pays one CXS GET per pass, absorbed
  silently by `ON CONFLICT DO NOTHING`. That wasted GET is the only real cost.
- **The feed's age gate judges Simplify's `date_posted`, not the board's `date_updated`** —
  `[FETCH · XS · accepted]`. **Measured on the
  live feed:** of the 1,044 listings refused as stale, **108 carry a `date_updated` inside
  the window** — still being refreshed, and dropped on the older field. Accepted because
  the pre-resolve gate is where the fetch cost is saved and `date_posted` is what the
  feed leads with. The cheap improvement, if it is ever wanted, is judging
  `max(date_posted, date_updated)`. (The other half of this item — that nothing re-checked
  the `posted_at` the board actually returned, so a feed row could be *stored* older than
  `max_age_days` — is closed: `run_feed` now re-runs `prefilter_postings` before the
  upsert. It was leaking ~5% of ingested feed rows.)
- **`max_age_days` silently gained feed scope on upgrade** — `[FETCH · XS · accepted]`. The key previously meant "watchlist
  fetch freshness"; it now also governs feed discovery, which on this config removes ~half the
  feed's surface. That is the intended fix, but an existing checkout gets it with no
  notice — the only announcement is a comment in `config.yaml.example`, which a live
  `config.yaml` never re-reads. There is no per-feed override. Left as-is: a second
  freshness knob for one feed is more config than the problem justifies, and the
  CHANGELOG carries the change. Revisit if a second feed wants a different window.
- **`apply.careers.microsoft.com` files ~50 `empty_description` rows per pass, and nothing
  is being lost** — `[FETCH · XS · wasted fetch only]`. Twelve were re-requested against
  the live detail endpoint: eleven returned a full 5,029-8,376 char `jobDescription`, one
  returned `404 Position not found`, and **all twelve were already in `job_postings`,
  `pipeline_status='new'`, with full descriptions.** So an `empty_description` row on this
  host is a *log of one failed detail call on a re-fetch*, not a lost posting —
  `upsert_postings` is `ON CONFLICT DO NOTHING`, so a bodyless re-fetch cannot overwrite
  the good stored row, and `run_fetch` drops the duplicate and files it here. Same class
  as the workday prune-never-matches finding above. The cost is one wasted detail GET per
  already-stored position per pass.
  **A detail-leg retry was built for this and REVERTED, so it is not re-proposed.** It
  rescued nothing (the postings were never lost), and the pre-merge review priced it: the
  retry is a *per-position* budget for a *board-wide* failure —
  exactly the smell PRINCIPLES names — so a board whose detail endpoint throttles or
  permanently 403s costs 14s (up to 90s) and 4 requests per position with no circuit
  breaker: **3h53m to 25h for a 1,000-position board**, against a serial `run_fetch`
  with no deadline and a `pass_lock` that REFUSES rather than queues, so an overrun would
  suppress the next 4-hourly pass entirely. If it is ever wanted, it needs a board-level
  breaker first (stop hydrating this board after K consecutive throttled details), and
  404 must stay terminal.
- **Eight recipes carry no `posted_at`, and four of them CANNOT** — `[FETCH · XS · measured,
  do not re-derive]`. Where a recipe maps no `posted_at`, `upsert_postings` stamps the scrape
  day (`db.py`), so `max_age_days` can never fire for that board and the displayed date is the
  day we saw it, not the day it was posted. It reads like a recipe oversight. For
  `tiktok`, `janestreet`, `bytedance` and `ibm` it is not: their list payloads carry **no
  date-ish field at all** — a full recursive walk of a live item for `date|posted|created|
  updated|publish|time` returns nothing. There is no recipe fix; it needs a detail call whose
  only purpose is a date, which is not worth one request per posting. Check the payload before
  filing this as a bug on a ninth board.

- **Bodyless rows on `phenom/microsoft`** — `[FETCH · XS]`. It drops 4-6 postings per pass
  whose list entry carries no description, while serving full ones for the rest — a
  partial-drop board, so there is no watchlist decision to make and no board-wide detail
  step to add. Non-destructive (the guard drops them and records them in `feed_unresolved`).
- **Boards deliberately held off the watchlist** — `[FETCH · XS · decision recorded]`. Nine
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
- **SSRF residual shapes** — `[FETCH · M]`. Three shapes remain reachable (browser-path
  redirect GET · DNS-rebinding · statically-internal hostnames — accepted meanwhile,
  SPEC §11). Closing the DNS shapes needs a resolve-then-check with a TOCTOU-safe
  connect; closing the browser-path GET needs an intercept-before-connect mechanism
  Playwright's routing API doesn't expose for navigations.
- **`applications` has no DB `@@unique(company_name, job_title)`** — `[WEB · M · deferred ·
  deliberate; waits on operator]`. Three transactional app-code paths hold the dedupe
  invariant (`addApplication`, `markJobApplied`, `importApplicationsCSV`). The hard
  constraint needs a backup + dedupe migration first — the real table may hold
  legitimate duplicate rows (re-applications), so `prisma db push` can't build the
  index without `--accept-data-loss`. Deferral is operator-confirmed.
- **No schema migration path** — `[INFRA · L]`. `prisma db push` keeps no migration history,
  so a *destructive* change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)
### Found by the deep-clean pass, deferred as behavior changes

The cleanup pass (CLEAN-01..09) was scoped to change no observable behavior. These
findings each WOULD change behavior, so none was touched; they are recorded here
rather than left in a PR description. Each cites the evidence that found it.

- **`util.to_iso_date` returns a 10-char slice where its docstring promises `None`** —
  `[FETCH · S · filter change, governed by err-toward-keep]`. `to_iso_date("not a real
  date")` returns `'not a real'`, and `to_iso_date(True)` returns `'1970-01-01'`; the
  sibling `_recipe.normalize_date` guards both (a `\d{4}-\d{2}-\d{2}` match and an
  `isinstance(value, bool)` check). The value feeds `max_age_days` freshness filtering,
  so tightening it DROPS postings that are currently kept — which is exactly the
  direction PRINCIPLES 3 says to justify explicitly. The docstring was left alone in
  CLEAN-07 for this reason: it describes the intended contract, and changing the code to
  match is the real fix.

- **`location_verdict`'s `resolved` / `ask_llm` are documented, tested, and then
  discarded** — `[SCREEN · M · contract contradiction, touches SPEC §9]`.
  `location.py:441-445` states that an unresolved location "must NOT be recorded as a
  passing location check", because leaving the key absent is what lets a later free
  extraction fill the gap. But `resolve_location` drops both fields, and
  `deterministic_screen` (`screening/engine.py`) writes
  `screen["location"] = {"pass": passed, ...}` unconditionally. So either the docstring
  is wrong or the gate is silently blessing unresolved locations. Resolving it changes
  screen outcomes and touches a SPEC §9 clause.

- **The modal and the table coerce `recommended_resume` differently** — `[WEB · XS]`.
  For a non-string value the modal yields `''` (`typeof === 'string'` guard) and the
  table yields `'5'` (`String(...)`). Same for `reasoning`. CLEAN-06 shared the
  assessment parsing but left this divergence, since picking a winner changes what one
  component renders on malformed input; both sites now carry a comment saying so.

- **Nine server actions are covered only by the excluded integration suite** —
  `[WEB · S]`. `jest.config.ts:18` excludes `*.int.test.ts` from the default run, so
  `removeAllInView`, `deleteApplication`, `deleteHistoryItem`, `exportApplicationsCSV`,
  `importApplicationsCSV`, `getCategories` and `setCategories` have no fast-suite guard;
  `getApplicationHistory` has no test at all. CLEAN-05 closed this for `bulkRemove` and
  `bulkReopen` because it refactored them. The rest is test work, not cleanup.

## Enhancements — not built, optional

- **Onboarding ANY user, not just the first one** — `[DOCS · L · discussion recorded,
  nothing decided]`. Tuning the tool for its first user took an afternoon:
  126 golden rows reviewed, four profile rewrites, three paid probes, and a 71-key
  `title_exclude` list that only existed because a session ran ad-hoc SQL over 11,675
  stored titles. The constraints, the measurements, and four open questions are in
  [`superpowers/specs/2026-08-02-universal-onboarding-design.md`](./superpowers/specs/2026-08-02-universal-onboarding-design.md).
  The three that shape any solution: **the free filter matters more than the profile
  prose** (a tuned exclude list cut kept intake 8,851 → 6,099, and seniority tokens
  alone were 21%); **`onboard-me` runs before `onboard-board`, so the DB is empty** and
  every corpus-driven suggestion has nothing to mine. Also settled there: the adapters are industry-general, so the audience limit is
  *discovery*, not fetch; feeds are a source concept deserving an `onboard-feed` skill;
  and filters should become DB-owned so in-flight tuning does not need a worker restart.
- **Bulk watchlist onboarding as a skill** — `[DOCS · M · proposed, not built]`. A
  one-off watchlist expansion (49 → 172 boards) ran an ad-hoc pipeline worth encoding:
  read the candidate's target profile → parallel company research per target tier → **verify
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
- **429 backoff exists only in `phenom`** — `[FETCH · XS · the one board that actually
  rate-limited is covered]`. `phenom` has bounded retry + salvage of the pages already
  walked (it lost `careers.qualcomm.com` to a 429 once). The other paginating adapters
  are bare. Deliberately so —
  12 of the 13 sources have never rate-limited, and a per-source
  `requests_per_second` / `max_concurrency` policy across all of them buys nothing
  measured. Port the same ~15 lines to a second adapter **when a second board 429s**,
  not before.
  **A phenom 403 deep into pagination is a throttle, not a block, and the retry for it is
  unproven** — `[FETCH · XS]`. Qualcomm fails every pass at a varying offset
  (`403 Client Error: Forbidden ... &start=1060`, also `start=990`, `start=1220`), yet
  those same offsets return **200** when probed cold from a fresh session — so it is a WAF
  tripping on the pass's cumulative request volume, not a missing page. It takes the same
  bounded-retry-then-salvage path as a 429; a 403 on the FIRST page still raises, since
  there is nothing to salvage and a board refusing from the start is a block. What is NOT
  measured is whether the retry actually succeeds against a live WAF trip — reproducing
  one needs ~1,000 requests at a third party, which was not run. The next live pass is
  the measurement.
- **Recipe validation happens a full pass late** — `[FETCH · S]`. `config.py` checks only
  that a `custom`/`browser` row *carries* a recipe mapping, and `get_watchlist` skips
  one whose JSON is malformed. Everything else — a bad `mode`, an `item_path` that
  matches nothing, a `fields` map whose dotted paths miss, a `url` template naming a
  field that doesn't exist, an empty CSS selector — fails **silently at fetch time**:
  the executor yields postings with blank titles/descriptions, `_valid_posting` drops
  them, and the operator learns about it one full pass later from a
  `feed_unresolved` row. A `validate_recipe(recipe)` called from both config load and
  the web's watchlist-add action moves that to write time, and belongs in the same
  boundary as the existing SSRF check on recipe-fetched URLs. Skip a `version` field
  until a second recipe shape actually exists.
- **Balyasny + Jacobs Levy — primitive exists, boards not yet added** — `[FETCH · XS ·
  operator step]`. The `{field}` URL template was the *sole* blocker for both: Balyasny (`external_id: {attr: "data-id"}` →
  `/s/details?jobReq={external_id}`) and Jacobs Levy (5 roles, one static page,
  apply-by-email). Writing the two watchlist rows is a separate operator step — use the
  `onboard-board` skill, which now has the template available to it.
- **`custom` `html` mode — built once, ingests NOTHING as documented** —
  `[FETCH · M · no branch carries it]`. The executor works; the value claim does not.
  Re-cut it when `custom` gains the chained detail call.
  **The blocker is one line elsewhere:** `pipeline._valid_posting` requires a non-empty
  `description`, and `custom` has **no `detail:` mechanism and no `fetch_one`** (both
  greppable, both zero hits), so an `html` recipe can only produce a description if the
  *listing card itself* carries the JD body. Every example the branch ships —
  `config.yaml.example`, `SKILL.md`, the test fixture — omits `description`. Driven
  through the real `run_fetch`: `dropped 3 posting(s) with no description`, **0
  inserted**, plus 3 `feed_unresolved` rows per cycle. The unit tests miss it because they
  assert the field *set*, never that `description` is non-empty.
  So the six boards (Bloomberg, Two Sigma, Citi, Barclays, Moody's, Geode) are **not**
  unblocked: what they need is a chained detail fetch, which is exactly what `custom`
  lacks. `SKILL.md`'s Step 3 validation criterion omits `description` too, so the skill
  actively certifies a broken row as valid.
  **Two honest ways out:** merge the executor with the docs corrected to say it works only
  where listing cards carry the full JD body, or hold it until `custom` gains the chained
  detail call (already an open item — same primitive Uber/Netflix/Morgan Stanley need).
  **Other confirmed defects on that branch:** `description: [path, path]` raises
  `AttributeError` in `html` mode though `SKILL.md` documents the list form as shared;
  `page: {type: url}` is silently ignored rather than raising as `browser` does, so a
  multi-page board returns page 1 and looks successful; `type: page` starts at 0 with no
  `start:`, and most server-rendered pagers are 1-indexed; `resp.text` mojibakes non-ASCII
  when a board omits `charset` (confirmed `MÃ¼nchen`), which matters far more for `html`
  than for JSON since the payload *is* the prose — pass `resp.content`; `browser` lost its
  pre-loop `item`-selector validation in the refactor (`parse_jobs([], …)` now returns
  `[]` where `main` raised); the equivalence test passes coincidentally on a clean
  three-card fixture (the two executors genuinely differ on de-dup and empty ids); and
  `SKILL.md`'s Step 3 snippet still `json.load`s a payload that is now a `str`.
  Related and unchanged: a `browser` `detail:` block costs **one Chromium render per
  posting** with no stub gate (`browser.py:159`), which is the other reason Citi (3,567
  postings) and Barclays (1,074) are off the watchlist.
- **Boards blocked on an executor primitive, not an adapter** — `[FETCH · L]`. Meta needs a
  fetch-page-then-POST handshake (its GraphQL requires a per-session `lsd` CSRF token
  scraped from the HTML) *and* a scroll hook (the rendered DOM holds 11 of 692 cards
  in a virtualized inner scroller with no URL pagination). Balyasny's Salesforce Aura
  endpoint needs an `aura.context` `fwuid` hash that rotates every release. Recorded
  so the next attempt starts from the known blocker rather than re-deriving it.
- **Un-hydrated stub discards have no way back** `[ORCH · S]`. A stub-gate
  discard is stored with `description=''` on purpose. Nothing
  re-hydrates an existing row, because `upsert_postings` is `ON CONFLICT DO NOTHING` and
  the stub gate only decides whether to hydrate *before* insert. Both states are terminal,
  and on a phenom-heavy watchlist that is a large share of the discard table — exactly the
  rows a `candidate.locations` edit is meant to reclaim. **The fix has a precedent in this
  repo:** `run_fetch` DROPS bodyless board rows rather than storing them, precisely so the
  id stays re-fetchable. Doing the same for stub-gate discards (or storing them with a
  re-fetch marker) would make them genuinely recoverable. `run_once` now prints the
  skipped count so the gap is visible rather than silent.
- **Discovered Jobs README screenshot** — `[DOCS · XS]`. The prose is now expanded to Track
  parity (bucket triage, the per-row "why" subline, bulk actions). Still missing: an inline screenshot of the tab to match the "Track"
  images. Needs a seeded throwaway DB (never the real `db/applications.db` — see the
  privacy note in SPEC §11 on the existing screenshots) and a richer fixture than the
  e2e seed. Wait for the read-only dashboard (#158) to settle the tab's shape.
- **Dead-link sweep — board sources uncovered** — `[FETCH · M · needs a per-board signal]`.
  `run_expire` only re-checks **detail sources**, the ones with a per-job
  endpoint. A posting from a board source (greenhouse/lever/ashby/…) goes dead
  silently. Closing it means diffing each board's current listing against the
  ingested rows — a different mechanism, and a *fetch failure* must never be read as
  "the whole board's jobs closed".
- **`onboard-board` skill — eval iteration 2** — `[DOCS · M · optional]`. Re-run the
  skill-creator eval loop on the add-or-fail flow (with-skill agents add to a
  *throwaway* DB via `--db`) with tougher/undocumented boards — iteration 1 hit 100%
  pass on both configs, so it measured speed (−42% time / −18% tokens), not
  correctness.
- **More board adapters** — `[FETCH · M · pick a target]`. The adapter pattern
  (`fetch/<source>.py` + `ADAPTERS`/`VALID_SOURCES`, or `fetch_one` in
  `DETAIL_SOURCES`) makes new sources cheap. Leads: LinkedIn's public `jobs-guest`
  endpoint (unauthenticated, zero-dep; personal-use / ToS caveat, keep volume low);
  JobSpy as a possible fallback aggregator.
- **Remaining feed coverage (the `feed_unresolved` long tail)** — `[FETCH · M · needs
  iCIMS/ByteDance feed routers]`. Resolution was ~78% after tier 1 (a sample; re-measure
  from `feed_unresolved`). What's left
  is iCIMS + ByteDance — both plain HTTP (iCIMS ships as a list adapter, TikTok as a
  `custom` recipe), but closing the *feed* tail still needs a `resolve_url` host
  router + a per-listing `fetch_one`, which the list adapters don't provide.
  **Dropped:** greenhouse embed-token (job id only, no board slug); SuccessFactors
  (absent from feed).
- **Deployment / monitoring** — `[INFRA · L · open-ended]`. `ats-web` has a DB-reachability
  healthcheck + `autoheal`, and the worker is **supervised** (a systemd user unit,
  journald for logs — SPEC §6). What is still missing is
  *detection*, and it matters more now that nobody is watching each pass:
  `Restart=always` brings a crashed worker back, but a worker that is up and quietly
  producing nothing — a dead board adapter, a screen backend answering blind — still
  shows only in the DB.
  There is no metrics/alerting at all. Includes the deferred scraper **canary self-tests**
  and proactive alerting for silently-broken scrapers (SPEC §9 points here).
