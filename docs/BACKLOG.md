# Backlog — the open catalogue

> The *catalogue* half of [`PROGRESS.md`](./PROGRESS.md), kept separate so a session that
> only needs the current state does not load hundreds of lines of open items.
> PROGRESS keeps the live delta — in flight, the pick order, the quota gap, open
> **defects** — and points here; everything below the defects lives in this file.
> Evaluated-and-rejected proposals are a third file,
> [`REJECTED.md`](./REJECTED.md) — read the entry for your block before proposing a
> redesign of it.
>
> **Conventions are PROGRESS's**, unchanged: entries are tagged
> `[BLOCK · XS/S/M/L · blocker]`, run easiest-first within a section, and severity is
> honest — unverified properties above enhancements. The eight blocks and the
> per-block open counts are in [PROGRESS's Open work
> table](./PROGRESS.md#open-work). Adding, closing and moving entries: [How to
> update](./PROGRESS.md#how-to-update).

## Unverified / deferred — behavior may be fine, but nothing proves it, or a decision is pending

- **`GATE_MIN_FRACTION = 0.5` is a made-up number, and the choice is deferred to the
  scoring redesign** — `[SCORE · XS · decision pending]`.
  `score_eval.py`'s gate floor: PASS requires that at least half the corpus rows actually
  reached the gate. It exists because `marked: true` is a one-word edit per line and
  marked rows are gate-exempt in both directions, so marking the unreachable rows would
  turn the gate green having relabelled nothing (and `verdicts_match({}, {})` is True, so
  `--batched` reported PASS over ZERO rows). The floor closes that.
  **Unlike the gate's other thresholds — >=85% agreement, <20% flip-rate — it has no
  measurement behind it.** It is a don't-be-absurd line, not a calibrated one. It is also
  slack against every real number: 69/93 = 74% today, 91/93 = 98% after the relabel, so
  it fires only on the marking path.
  **Operator's call: leave it** — the scoring subsystem is being redesigned and tuning
  this now may be wasted. Revisit when the redesign settles what the gate measures; the
  fallback if the fraction is unwanted is `n_gate > 0` alone, which still closes the
  PASS-over-zero-rows case but reopens the marking path.

- **Capture the quota snapshot at pass START, not after the fit phase** —
  `[SCORE · XS · would sidestep the 403 entirely]`. `capture_usage` runs at the end of a
  pass, i.e. immediately after a burst of paid calls on the same account. That is exactly
  the moment a rate limiter would refuse, and the 403 this system keeps hitting is
  consistent with (though not proven to be) one. Capturing before the fit phase costs the
  same single call and lands it when the account is cold.
  **The trade is what the bar shows:** a pre-pass snapshot omits the pass's own spend, so
  the web bar would lag by one pass. Capturing at both ends doubles the call but is still
  free of quota. **Decide only after the WARNING rate has been measured across days** — if
  the shipped retry drops it near zero, this is unnecessary complexity.
  **The rate has been measured once and it is not yet decidable — read the denominator
  before quoting it.** Only **three** passes in the whole journal both fit-scored and ran
  with the WARNING live (passes that fit-score 0 rows never make the guarded call, so they
  are in neither numerator nor denominator): 2 of those 3 missed the snapshot. At n=3 the
  match with the ~2-in-3 per-call rate the hand probes suggested is worth nothing.
  **And it measures the PRE-retry rate** — the retry has never executed in a live pass,
  because every scoring pass in that journal predates the merge. The question this entry
  gates on ("does the retry drop it near zero") has no data behind it and cannot get any
  until the daemon runs again. **Do not decide this entry off the 2/3.**
- **The seniority title-token floor: measured 2026-07-31, ambiguous, and the decision is
  the operator's** — `[SCORE · XS · decision pending]`. SCORING §5.7 declined to build a
  floor for the *"Senior ..."* titles the model returns an empty object on, asking for its
  own measurement first. The measurement ran and split:

  | | in-sample (446 rows) | held-out (32 rows) |
  |---|---|---|
  | shipped rules only | P 0.975, R 0.793 | 0 false demotions |
  | + title floor | P 0.970, **R 0.900** | **1 false demotion, 0 recovered** |

  It is **the largest recall win available** — 35 of the 61 misses carry a rank word in
  their title, and it recovers 27 of them — and it owns the **only** out-of-sample false
  demotion any candidate produced across every combination tried (Onto Innovation `Senior
  Software Engineer`, `domain=mismatch`, model returned nothing, floor fired alone). Both
  corpora still pass the gate; 32 rows carrying 3 positives cannot settle it.
  **The argument against is not the number, it is the shape:** a floor that fires on a
  title with no model verdict behind it is the unevidenced-demotion pattern the vetoes
  exist to prevent, and the one dataset that could contradict it does.
  **If it is ever built, one narrowing is already measured:** a title naming *both* levels
  ("Jr/Sr Engineer") states no single bar, and guarding on a junior token removed a false
  demotion at zero recall cost (Micron `Jr/Sr Engineer, STPG PE System`).
  Reproduce with `make eval-seniority`; the rejected sibling (widening
  `rank_stated_in`'s vocabulary) is recorded in SCORING §5.7 as provably redundant.

- **The blind-backend residual: `sponsorship_labels: null` and `[]` still reach the phrase
  floor** — `[SCREEN · open by decision, the operator's call]`. The defect this came from
  shipped a fix 2026-07-29 (SPEC §7.1 + §9, CHANGELOG); the fork it left open is stated as
  one in SCORING §3.7. A live-but-blind response is deliberately **not** flagged
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
  postings** — `[SCREEN · S · found by the PR #24 pre-merge review 2026-07-28, verified]`.
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
  13 corpus must-flag sentences** — and each is a miss costing one paid fit call that
  reaches the human. `test_the_narrowed_vocabulary_names_exactly_which_bars_it_gives_up`
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
  Ollama fallback for the 3.1% of rows the gazetteer cannot resolve, and the fit scorer as
  a second net.

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
- **Citadel's JD is unreachable behind Cloudflare — both rows kept anyway** —
  `[FETCH · decided · do not re-derive]`. `browser/citadel.com` and
  `browser/citadelsecurities.com` scrape their listing pages fine (10 postings each,
  clean on id/title/location/url) but **0/10 on `description`**: Cloudflare clears once
  for the listing render, then re-challenges the deep-link detail navigations.
  Three probes settled it — plain-HTTP listing GET → `403`; deep-link `goto` + 15s
  dwell → `Just a moment...`; **clicking** the card from the already-cleared listing
  (user gesture + same-origin referer) + 30s dwell → byte-identical. The detail route
  is challenged regardless of arrival path and does not self-clear; everything past
  this rung is a stealth plugin / real browser profile / residential proxy — detection
  evasion plus a new dependency, out of scope here.
  **Decision: keep both rows.** Since the body-required guard shipped they simply yield
  nothing (dropped at `run_fetch`, logged), costing a few Chromium renders per cycle,
  and they self-heal if Citadel's Cloudflare behavior relaxes. The only other honest
  option is deleting them; dropping the `detail:` block to take title-only is now a
  no-op, since the guard would drop those rows anyway.
  **The real price is 6x/day** now that the daemon runs, for a known-zero yield — which is
  why these rows are part of the one watchlist decision in the empty-JD-boards entry below.
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
- **`onboard-me` evals are owed a run — two scenarios, two different reasons** —
  `[DOCS · S]`. The harness is subagent-driven and has not run since either change landed.
  **id 4 `fresh-checkout-no-telegram-remote-ollama` — written, never run.** Step 0's
  *factual* claims were verified against shipped code (all 9 doctor row labels match live
  output), but the *behavioral* assertion — that an agent leads with `make setup` +
  `make doctor` and reads the status lines instead of treating every row as mandatory —
  is unproven.
  **id 2 `profile-and-docx-resume-design` — passed before, now at risk.** `7e2e93f` moved
  the profile-authoring rules out of `SKILL.md` into `references/profile.md` behind a
  read-this-first pointer. The structural assertions are safe — the six section headers
  and the `<w:t>` extraction rule stayed in the body (grep-verified) — but
  `profile_targets_correct` (ANTI-TARGETS scoped to the disliked day-to-day, not a bare
  title that overlaps a target) now depends on the agent actually opening the reference.
  That is the one assertion progressive disclosure could regress here, and only a run
  shows it. If it fails, pull the ANTI-TARGETS rule back inline rather than reverting
  the split.
- **The recipe-sourced `custom`/`browser` SCORED path is still unexercised** — `[SCORE · S]`.
  The 2026-07-22 full fetch proved both executors work through `run_fetch` (custom
  1,411 `new`, browser 662 — CHANGELOG). But the one bounded `--score-only` batch hit
  the oldest ids, which were the original greenhouse+phenom config boards, so no
  recipe-sourced row has ever been screened, fit-scored or notified. Closing it needs a
  score run that reaches `custom`/`browser` ids — a larger `--score-limit`, or a
  source-filtered slice.
- **Route a local `degree`/`clearance` fail to the strong model as `needs_confirmation`**
  — `[SCREEN · shipped 2026-07-29 · one residual open by decision]`.
  **The behavior, the pre-fix 83%/24% rates and why `authorization` is excluded are
  now in SCORING §5.3** — read it there; those rates are pre-fix and must not be re-quoted
  as current.
  **What stays here is one deliberate hole:** a degree/clearance-only fail on a JD thinner
  than the low-context threshold is kept *without* confirmation, because it takes the
  thin-JD path and spends no fit call. A thin JD cannot support a degree-bar reading either
  way, and those rows are already held back from notify and shown for human review.
  **And one shape decision, so it is not re-proposed:** routing is an in-pass decision plus
  a `score_detail` marker, **not** a new `pipeline_status` — screen and fit run in the same
  pass, so no row is ever stored in that state, and a real status would mean new
  `constants.ts` values and UI buckets for something nobody can observe.

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
- **Queued rows age past `max_age_days` and become paid calls the config would refuse** —
  `[SCORE · XS · title half shipped, age half open]`. The leak is structural, not a
  backlog artifact: `prefilter_postings` runs at *ingest* only, and `screen_posting`
  re-checks the deterministic intern/location gate but never title or age. So any row that
  sits long enough ages out of the config and still costs a fit call. The queue regrows
  this on its own, roughly a day's worth at a time. `run_score`'s free phase-0 sweep now
  re-applies `title_filter`/`title_exclude` to already-queued rows, which covers the title
  half.
  **Measuring it is timing-sensitive:** `_too_old` truncates both sides to a date
  (`[:10]`), so every posting ages a full day the instant UTC rolls over — the same queue
  measured 198 and 275 rows 88 minutes apart across that boundary. Any count here is a
  snapshot.
  **The AGE half is REFUSED, and this is the reasoning so it is not re-proposed as an
  obvious symmetry.** It looks like the same fix and is a different thing:
  - a title refusal is **recoverable** — widen `title_filter`, run `--rescreen-discarded`,
    the row survives phase 0 and comes back. An age refusal is **not**: the row only gets
    older, so raising `max_age_days` never catches up with it.
  - **474 of the 587 age-refusals were INSIDE the window when they were ingested.** They
    aged out *waiting in the queue*, so discarding them is a queue-TTL policy, not "the
    config refuses this posting". At the measured ~200-250 rows/day of drain it would
    terminally delete on the order of 5,300 rows over 30 days.
  - it would fight the one escape hatch. `--rescreen-discarded` requeues 919 hydrated
    discards; 881 of them die at the location/intern gates *before* the stale check is
    consulted, so the population at risk is the 38 that survive. Of those, the
    age-inclusive version re-kills 26 — **12 carrying `degree:` and 14 `authorization:`** —
    overwriting the `score_detail` they carried, against 4 (all `authorization:`) under
    the shipped title-only check. The evidence lost is NOT the `location:` verdicts:
    `deterministic_screen` regenerates those byte-identically every pass. It is the
    LLM-derived ones, which nothing recomputes — small in count, bad in kind.
  **One variant was NOT considered when this was refused, and it may be the right
  answer — it is queued, not declined.** Judge age against the row's **own
  `created_at`** rather than `now`:
  `max_age_days=cfg.max_age_days, now=(posting.get("created_at") or "")[:10]`. That is
  recoverable in exactly the sense the refusal demands — the verdict for a given row is
  computed against a fixed timestamp, so it never changes with elapsed time, and widening
  `max_age_days` plus `--rescreen-discarded` brings the row back. It cannot delete ~5,300
  rows over 30 days because it is not a function of elapsed time at all. It refuses the
  **112 rows that were ALREADY past `max_age_days` when they were ingested** — which is
  precisely the population the title half exists for, rows that entered under a looser
  knob — and after that only genuinely-stale arrivals. The refusal above treats "age" as
  indivisible; it splits cleanly along the line its own measurement draws. A second
  unconsidered option: sort stale rows last in phase 0's queue order instead of
  discarding them — non-destructive by construction. (No column for that exists on this
  branch; it would need one, or an ordering key.)
  If the operator does want a queue TTL, it wants the shape a deliberate sweep has — a
  saved id list and a pre-run DB copy, revertible row for row — not a silent
  six-times-a-day deletion.
- **The feed's age gate judges Simplify's `date_posted`, not the board's `date_updated`** —
  `[FETCH · XS · found by the pre-merge review 2026-07-28 · accepted]`. **Measured on the
  live feed:** of the 1,044 listings refused as stale, **108 carry a `date_updated` inside
  the window** — still being refreshed, and dropped on the older field. Accepted because
  the pre-resolve gate is where the fetch cost is saved and `date_posted` is what the
  feed leads with. The cheap improvement, if it is ever wanted, is judging
  `max(date_posted, date_updated)`. (The other half of this item — that nothing re-checked
  the `posted_at` the board actually returned, so a feed row could be *stored* older than
  `max_age_days` — is closed: `run_feed` now re-runs `prefilter_postings` before the
  upsert. It was leaking 127 of the 2,568 rows ingested 2026-07-29.)
- **`max_age_days` silently gained feed scope on upgrade** — `[FETCH · XS · found by the
  pre-merge review 2026-07-28 · accepted]`. The key previously meant "watchlist fetch
  freshness"; it now also governs feed discovery, which on this config removes ~half the
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
- **Empty-JD boards ON the watchlist — the Citadel pair** — `[FETCH · XS]`.
  `browser/citadelsecurities.com` (7) and `browser/citadel.com` (4) still drop every
  posting bodyless, re-fetched and re-dropped **6x/day**. **Do not delete them:** both are
  recoverable, not zero-yield (see the Citadel entry above), and what they wait on is the
  stealth browser transport, not a watchlist decision.
  **`icims/globalcareers-msci` has left this set.** It was never an empty-JD board, only a
  board with no detail step: its iCIMS list endpoint carries no description at all, but the
  job's own page does — 92 live postings, median **7,032** chars. The fix was a platform
  capability serving every iCIMS tenant, not a decision about this row (`SPEC.md` §7.1).
  **`phenom/microsoft` was never in this set:** it drops 4-6 bodyless rows per pass but
  serves full descriptions for the rest, so it is a partial-drop board.
- **Intake-cut evidence — the numbers are ready, the decision is the operator's**
  — `[FETCH · S · Q3 · one board-side filter applied, rest declined]`. Q3 is the only lever
  that reduces *demand* rather than re-ordering it. Three findings.
  **1. Boards differ enormously in how much of what they fetch dies free.** Measured over
  a 9,381-row queue, 37% died on the free deterministic gates — fetched, stored, and
  discarded without a model ever reading them. Per board, the share of its queued rows
  that died there (a snapshot; the sweep below has since harvested this population):

  | board | queued | free-killed | waste |
  |---|---|---|---|
  | Micron | 678 | 484 | 71% |
  | Oracle | 126 | 77 | 61% |
  | Jane Street | 162 | 94 | 58% |
  | TikTok | 1,367 | 782 | 57% |
  | BlackRock | 148 | 84 | 57% |
  | Cisco | 551 | 303 | 55% |
  | Snowflake | 101 | 52 | 51% |
  | Goldman Sachs | 281 | 134 | 48% |
  | ByteDance | 155 | 75 | 48% |
  | Amazon | 987 | 357 | 36% |
  | Google | 759 | 13 | **2%** |
  | Qualcomm | 150 | 0 | **0%** (0% null locations) |
  | AMD | 103 | 0 | **0%** (0% null locations) |

  Google, Qualcomm and AMD are the control: a board CAN be nearly all-relevant, so a
  57-71% waste rate is a property of that board's geography mix, not of the gate.
  **Susquehanna looks like a 0% control and is NOT one — read this before using the
  table.** All 151 of its queued rows carry a **NULL location**, and
  `resolve_location(None, ...)` errs toward keep, so the gate cannot evaluate that board
  at all. Its 0% means "unjudgeable", not "all relevant" — and the consequence runs the
  other way: those rows sail past the free gate and go on to pay full model cost, which
  makes SIG one of the more expensive boards per row rather than an exemplary one. Every
  other board in the table has ~0% nulls. Check the null-location share before reading any
  0% as a good sign. The cheapest
  intake cut is a per-board location constraint or dropping the worst offenders — but
  note this is *fetch* cost only, since the gate is free and (as of 2026-07-31) no longer
  spends a budget slot either.
  **Only ONE of the five `custom` boards can be filtered board-side, and the four
  negatives are the useful part.** The idea was to push the location
  constraint upstream into each board's own query so the wasted rows are never fetched.
  Scope was `custom` boards only — the three `workday` offenders (Micron 484, Cisco 303,
  BlackRock 84) need `appliedFacets` with opaque per-tenant GUIDs and were ruled out
  without probing. Live results:

  | board | free-killed | board-side country filter? |
  |---|---|---|
  | Amazon | 357 | **yes** — `normalized_country_code[]=USA`, 2,036 → 1,267 hits (38%) |
  | TikTok | 782 | no — `location_code_list` takes **city** codes only |
  | ByteDance | 75 | no — same API as TikTok |
  | Jane Street | 94 | no — static `main.json`, no query params at all |
  | Oracle | 77 | no — opaque `GeographyId`, level unverifiable |

  **The TikTok negative is the load-bearing one, because it is the biggest board.** Its
  `city_info` exposes a clean city → state → country hierarchy (`CT_` → `ST_` → `CN_`), so
  a country filter looks available: US is `CN_6`. It is not. Measured against the live
  endpoint, `location_code_list: ["CN_6"]` returns **0**, `["ST_1002078"]` returns **0**,
  and only city codes work — `["CT_114"]` (New York) 181, `["CT_114","CT_157"]` (+Seattle)
  491, against a 3,651 baseline. Filtering TikTok therefore means enumerating US city
  codes, which silently drops every US city not on the list and rots the moment
  `candidate.locations` changes — the failure being indistinguishable from a quiet board.
  Declined on that basis, not on effort.
  **Oracle looked possible and could not be confirmed.** `selectedLocationsFacet` and
  `locationId` both narrow 2,314 → 1,544 with a clean 25/25 US sample, but the value is a
  15-digit `GeographyId` scraped off one requisition, the facet list is not requestable
  (`expand=filters.facets.items` → HTTP 400), and 50 rows carry 24 distinct ids — so
  whether that id means "United States" or a region that happens to contain 1,544 jobs is
  unknown. Same class as the Workday GUIDs, for the smallest payoff of the five.
  **Amazon is verified rather than assumed:** 300 of 300 rows sampled across offsets 0,
  100 and 1,100 come back `USA`, `hits` holds at 1,267, and pagination is unaffected.
  **And the null-field trap was checked explicitly, because this file teaches that
  lesson two findings up.** Walking the **whole unfiltered board** (2,035 rows, offsets
  0-2,000) and reading `normalized_country_code` on every row: **0 rows carry no country
  code.** The split is `USA 1267 · IND 371 · CAN 111 · ISR 47 · IRL 41 · GBR 28 · BRA 26 ·
  AUS 23 · MEX 22 · CHN 20 · DEU 15 · ESP 14 · …`, summing to 2,035 — so the filter is an
  exact partition, not a heuristic, and there is no unjudgeable bucket to drop silently.
  That is the difference between this and the Susquehanna 0% above, where a NULL field
  meant "cannot be evaluated" rather than "matches nothing". The
  38% API-side cut lines up with the 36% free-kill rate this table measured for Amazon.
  **That agreement is a coincidence, not a check** — the 36% is over rows that reached the
  *gate*, the 38% over rows *fetched*; different numerators over different denominators.
  The real corroboration is the A/B below, which compares the two survivor sets directly.
  **The Amazon filter is applied** — `watched_companies.recipe.url` for `custom/amazon`
  ends `&normalized_country_code%5B%5D=USA`, verified by driving the real `fetch_company`
  with the stored recipe rather than the probe: 1,267 postings, all USA, so ~768 rows/pass
  are no longer fetched, parsed or stored. Revert by deleting the parameter. (`requests`
  merges `params=` with a URL that already carries a query string, so the
  `offset`/`result_limit` pagination the recipe adds is unaffected.)
  **The A/B through the production fetch + gates says the filter is LOSSLESS — this is the
  number that settles it:**

  | arm | fetched | past `title_filter`/age | past the free gate |
  |---|---|---|---|
  | unfiltered | 2,035 | 640 | **411** |
  | filtered | 1,267 | 411 | **411** |

  Identical survivor set. Of the **768** rows the filter removes from the fetch, **0**
  would have survived every free gate — so nothing is lost, and the 229 rows the location
  gate used to kill for Amazon (640 → 411) are simply never fetched now. `prefilter_postings`
  was called with an explicit `now=`; its default silently disables the age rule.
  **Do not re-quote the 37% as a live figure.** Driving `deterministic_screen` over the
  queue after the free-gate sweep gives **0 free-gate kills on 4,430 `new` rows** — what
  remains is the survivor set by construction. The harness was positive-controlled before
  that 0 was believed: fed 200 rows already `discarded` with a `location:` reason, it
  re-killed 200/200. A 0% means the waste was harvested, not that the gate stopped working.
  **Beyond `custom`: `workday` and `greenhouse` are both measured NOs, and they cover 129
  of the 172 watchlist rows.** Queue share by source:
  `custom` 1,599 · `workday` 738 · `greenhouse` 571 · `browser` 529 · `phenom` 239 ·
  `icims` 148 · `ashby` 128 · rest <30 each.
  **Workday (28 boards) has no country tier, and fails in the dangerous direction.** The
  well-known global Workday country GUID for the USA
  (`bc33aa3152ec42d4995f4791a106ed09`, the reason the "per-tenant GUID" objection looked
  beatable) was applied as `appliedFacets: {"locationCountry": [...]}` to Micron, Cisco and
  BlackRock: totals came back **2,725 → 2,725**, **1,018 → 1,018**, **257 → 257**, with
  Japan and London rows still present. **An unrecognised facet key is silently ignored, not
  rejected** — so this ships looking like it works. The response's own `facets` array is
  the authority, and Micron advertises only `timeType`, `workerSubType`, `jobFamilyGroup`
  and `locationMainGroup`; the last expands to a flat **site-level** list
  (`Boise, ID - Main Site`, `Bengaluru, India`, `Arzano (NA), Italy`) keyed by per-tenant
  GUIDs. Filtering Workday therefore means enumerating individual sites per tenant — the
  TikTok city-enumeration shape, and worse, because the ids are not portable between
  boards. Read `facets` before believing any Workday filter.
  **Greenhouse (101 boards) accepts no filter at all**, same silent-ignore shape:
  `boards-api.greenhouse.io/v1/boards/optiverus/jobs` returns **180** jobs with
  `?location=United States`, `?country=US` and `?offices=US` alike. Its board genuinely
  carries the waste (Amsterdam 33, Sydney 31, Shanghai 28 of 180) — there is simply no
  lever. That is what a board-embed API is *for*: it serves the whole board.
  **So the generalisation is that this does NOT generalise.** Amazon worked because
  `amazon.jobs` is a faceted *search* API; the ATS platforms are not. `browser` (529),
  `phenom` (239), `icims` (148) and `ashby` (128) are unprobed — worth a look only if
  someone is already in that adapter, since the remaining per-board upside is a fraction
  of Amazon's 768 rows/pass and every negative so far has cost a live probe to establish.
  **Whatever is applied, record the board's own pre/post total** (`total_path` for TikTok/
  ByteDance, `hits` for Amazon). A server-side filter that over-narrows reads exactly like
  a healthy quiet board, which is the confusion the eighteen zero-yield rows below already
  caused once.
  **2. Eighteen watchlist rows have produced ZERO postings, ever** — `ashby/hebbia-ai`,
  `ashby/uniswap`, `browser/citadel.com`, `greenhouse/aurosglobal`, `b2c2`, `crabel`,
  `davinciderivatives`, `exoduspoint`, `genevatrading`, `mwinternshipprogram`,
  `radixexperienced`, `simplextrading`, `walleyecapital-external-students`,
  `weissassetmanagement`, `lever/tgsmc`, `lever/voleon`,
  `workday/mlp/wd5/mlpcareers`, `workday/wellington/wd5/Campus`.
  **It read as nineteen first, and the extra one is a lesson about the query, not the
  board:** matching postings to watchlist rows by `company_name` wrongly included
  `greenhouse/headlandstechnologiesllc`, whose watchlist name is *"Headlands
  Technologies"* while its one ingested posting says *"Headlands Tech Holdings"*. Match
  on `(source, slug)` — the watchlist's actual key — not on the display name. Zero is not proof of a
  broken slug — a small board may genuinely carry nothing past `title_filter` — but each
  costs a fetch six times a day for nothing. This supersedes the three-row deletion
  decision below: it is eighteen, not three.
  **The mechanism is now MEASURED, and it is age, not `title_filter` — 2026-07-31.**
  Fifteen of these boards were probed live through the production `fetch_company`: every
  slug resolved, every adapter returned cleanly, **not one was broken**. Three serve
  genuinely nothing (`lever/voleon`, `lever/tgsmc`, `workday/mlp/wd5/mlpcareers`). The rest
  serve postings that **pass** `title_filter` and then die on `max_age_days` — Virtu 48
  served / 31 title-ok / 0 surviving, Geneva Trading 14 / 10 / 0, Radix experienced 7 / 6 /
  0, Maven 36 / 18 / 1. So the zero is a freshness effect on a slow-moving board, not a
  title-vocabulary one, and a board can sit at zero for weeks while being entirely healthy.
  Counts as of that date: **5 of 39 `config.yaml` rows and 16 of 172 `watched_companies`
  rows** at zero lifetime ingest.
  **Do not measure this with "rows ingested in the last N days".** `upsert_postings` is
  `ON CONFLICT DO NOTHING`, so a board with stable inventory inserts nothing while serving
  normally — that metric reports healthy boards as dead. It read as "15 of 39 stale" before
  being re-run on `(source, slug)` and on lifetime counts.
  **3. The current filters would refuse 775 of the queued rows that survive the free
  gates (13% of 5,941)** — **587 on AGE**, 206 on title, 18 on both (569 age-only, 188
  title-only). At the measured ~0.8
  paid messages/row that is ~620 messages, over 30% of a weekly window, spent on postings
  the operator's own config refuses today. A pre-screen re-apply of `prefilter_postings`
  collects all 775 for free.
  **A first pass at this measurement said "438, and essentially none on age", and it was
  an artifact — the lesson is worth more than the number.** `_too_old(posted_at, now,
  max_age_days)` parses `now` with `date.fromisoformat(str(now)[:10])` and returns
  **False on ValueError** ("unparseable -> keep"), so calling `prefilter_postings`
  without an explicit `now` — its own default — silently disables the age rule entirely
  and reports only title refusals. The err-toward-keep default is right for production
  and quietly wrong for measurement. Any offline use of this helper must pass `now`.
  **Yield, for scale:** 18 rows notified in the system's entire history, **5** of them on
  a watchlist `(source, slug)` — Optiver x2, Tower Research, WorldQuant and Goldman Sachs.
  Whether any of those came via the *watchlist* rather than the *feed* is **not
  recoverable from the DB**: nothing records the ingestion path, and both paths write the
  same `(source, external_id)`. Do not let a board-drop decision rest on it. Per-board
  *notify* yield is not measurable yet either — 9,381 rows have never been scored — so
  the decision rests on intake cost and waste share.

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
- **Every paid codex fit call deposits the résumé in `~/.codex/state_5.sqlite`** —
  `[SCORE · XS · privacy, operator's call]`. `--ephemeral` is unconditional
  (`backends_codex.py`) and `~/.codex/sessions/` is empty, so no session *rollout* is
  written — but the prompts persist in the CLI's own state DB anyway: of 318 rows in its
  `threads` table, **208 carry the `=== RESUME` block inline**, in **three** columns
  (`first_user_message`, `preview`, `title`). `preview` and `title` are what a session
  picker renders, so this store is *more* exposed than the rollouts it replaced. It sits
  outside the repo, so `.gitignore` and `make check-privacy` have never covered it.
  **Deleting is riskier than reaping a log file** — this is live CLI state, so a row delete
  wants the CLI stopped and a file copy taken first. Verify read-only before acting:
  `select count(*) from threads where first_user_message like '%=== RESUME%'`.
  (`score_workers=4` is unaffected and correct: the concurrency concern here was a rollout
  cleanup that no longer exists.)
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
  index without `--accept-data-loss`. Deferral operator-confirmed 2026-07-19.
- **No schema migration path** — `[INFRA · L]`. `prisma db push` keeps no migration history,
  so a *destructive* change (drop/rename a column) has no backfill or rollback and
  can lose retained `applications` / `status_history` data. Back up
  `db/applications.db` before schema changes. (SPEC §8.)
- **The claude scoring backend has never run in this deployment** — `[SCORE · XS ·
  residual of #33]`. `ANTHROPIC_API_KEY` is not set here, so `--score-backend claude`
  cannot execute at all; the quota half of #33 is verified against the live
  `/api/oauth/usage` endpoint, but no claude *scoring* pass has ever been observed —
  `make_claude_scorer` and the `backend: "claude"` snapshot path are covered by tests
  only. Separately and by design, that endpoint reports the Claude Code SUBSCRIPTION
  budget while the scorer bills the metered key; the bar states this outright and the
  honest source for actual spend would be the `anthropic-ratelimit-*` response headers
  off each call — a different shape (short-window headroom, not a weekly budget), not
  built. (SPEC §7.1 "Quota telemetry", §7.2.)
  **Check the SDK floor before the first live run.** `make_claude_scorer` calls
  `thinking={"type": "adaptive"}` and `output_config={"format": {"type": "json_schema"}}`,
  while `requirements.txt` floors at `anthropic>=0.40` — old enough to reject both kwargs.
  The worker runs on system python3, not `apps/worker/.venv` (which has 0.107.1), so
  confirm the installed version there and raise the floor to match. A first run that dies
  on a `TypeError` proves nothing about the backend.

### Found by the deep-clean pass, deferred as behavior changes

The cleanup pass (CLEAN-01..09) was scoped to change no observable behavior. These
findings each WOULD change behavior, so none was touched; they are recorded here
rather than left in a PR description. Each cites the evidence that found it. Two of the
original seven — the `todayISO` UTC rollover and `removeAllInView`'s missing `lowcontext`
branch — shipped 2026-08-03 and left for CHANGELOG.

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
  discarded** — `[SCORE · M · contract contradiction, touches SPEC §9]`.
  `location.py:441-445` states that an unresolved location "must NOT be recorded as a
  passing location check", because leaving the key absent is what lets a later free
  extraction fill the gap. But `resolve_location` drops both fields, and
  `deterministic_screen` (`screen.py:112-114`) writes
  `screen["location"] = {"pass": passed, ...}` unconditionally. So either the docstring
  is wrong or the gate is silently blessing unresolved locations. Verified directly on
  2026-08-01. Resolving it changes screen outcomes and touches a SPEC §9 clause.

- **`no_sponsorship_quote` is a required schema field with no consumer, and the prompt
  makes a false promise about it** — `[SCORE · S · prompt-byte change, needs
  eval-screen]`. `score/prompts.py:97` requires the field and `prompts/score.txt:33`
  tells the model it "is verified against the posting and a sentence that does not
  appear there is discarded". `_quote_in` was deleted (see `screen.py:687`); nothing
  reads the field. Removing either changes prompt BYTES, hence model output
  distribution, hence the Claude cache prefix — so it needs `make eval-screen`, not a
  cleanup patch. Overlaps `fix/sponsorship-positive-evidence`.

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

- **Onboarding ANY user, not just the first one** — `[DOCS · L · discussion recorded
  2026-08-02, nothing decided]`. Tuning the tool for its first user took an afternoon:
  126 golden rows reviewed, four profile rewrites, three paid probes, and a 71-key
  `title_exclude` list that only existed because a session ran ad-hoc SQL over 11,675
  stored titles. The constraints, the measurements, and four open questions are in
  [`superpowers/specs/2026-08-02-universal-onboarding-design.md`](./superpowers/specs/2026-08-02-universal-onboarding-design.md).
  The three that shape any solution: **the free filter matters more than the profile
  prose** (a tuned exclude list cut kept intake 8,851 → 6,099, and seniority tokens
  alone were 21%); **`onboard-me` runs before `onboard-board`, so the DB is empty** and
  every corpus-driven suggestion has nothing to mine; and **the scorer already names the
  profile line it used** (99% of 502 stored domain notes state `ANTI: yes/no`, 54% state
  the tier) — the diagnosis done by hand this session was sitting in `score_detail` all
  along. Also settled there: the adapters are industry-general, so the audience limit is
  *discovery*, not fetch; feeds are a source concept deserving an `onboard-feed` skill;
  and filters should become DB-owned so in-flight tuning does not need a worker restart.
- **Bulk watchlist onboarding as a skill** — `[DOCS · M · proposed, not built]`. The
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
- **429 backoff exists only in `phenom`** — `[FETCH · XS · the one board that actually
  rate-limited is covered]`. Shipped 2026-07-23 (CHANGELOG): bounded retry + salvage of
  the pages already walked, in the adapter that lost `careers.qualcomm.com` on the
  2026-07-22 pass. The other paginating adapters are still bare. Deliberately so —
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
- **Balyasny + Jacobs Levy — primitive shipped, boards not yet added** — `[FETCH · XS ·
  operator step]`. The `{field}` URL template landed 2026-07-23 (CHANGELOG), which was
  the *sole* blocker for both: Balyasny (`external_id: {attr: "data-id"}` →
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
  discard is stored with `description=''` on purpose, and `--rescreen-discarded` skips it
  (requeueing one parks it `scored`/0 permanently). Skipping is not a rescue: nothing
  re-hydrates an existing row, because `upsert_postings` is `ON CONFLICT DO NOTHING` and
  the stub gate only decides whether to hydrate *before* insert. Both states are terminal,
  and on a phenom-heavy watchlist that is a large share of the discard table — exactly the
  rows a `candidate.locations` edit is meant to reclaim. **The fix has a precedent in this
  repo:** `run_fetch` DROPS bodyless board rows rather than storing them, precisely so the
  id stays re-fetchable. Doing the same for stub-gate discards (or storing them with a
  re-fetch marker) would make them genuinely recoverable. `run_once` now prints the
  skipped count so the gap is visible rather than silent.
- **Discovered Jobs README screenshot** — `[DOCS · XS]`. The prose is now expanded to Track
  parity (bucket triage, the per-row "why" subline, the fit-assessment modal, bulk
  actions). Still missing: an inline screenshot of the tab to match the "Track"
  images. Needs a seeded throwaway DB (never the real `db/applications.db` — see the
  privacy note in §11/CHANGELOG on the existing screenshots) and a richer fixture than
  the e2e seed, which only populates the Matched + Discarded buckets.
- **Dead-link sweep — board sources uncovered** — `[FETCH · M · needs a per-board signal]`.
  `run_expire` (shipped) only re-checks **detail sources**, the ones with a per-job
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
  iCIMS/ByteDance feed routers]`. Resolution sits at ~78% after tier 1 — a figure from the
  last run the feed was on; the table now holds **0 rows** and re-measures on the first pass
  after the 2026-07-28 re-enable. What's left
  is iCIMS + ByteDance — both plain HTTP (iCIMS ships as a list adapter, TikTok as a
  `custom` recipe), but closing the *feed* tail still needs a `resolve_url` host
  router + a per-listing `fetch_one`, which the list adapters don't provide.
  **Dropped:** greenhouse embed-token (job id only, no board slug); SuccessFactors
  (absent from feed).
- **Deployment / monitoring** — `[INFRA · L · open-ended]`. `ats-web` has a DB-reachability
  healthcheck + `autoheal`, and the worker is **supervised and running** as of
  2026-07-28 (a systemd user unit, journald for logs — SPEC §6). What is still missing is
  *detection*, and it matters more now that nobody is watching each pass:
  `Restart=always` brings a crashed worker back, but a worker that is up and quietly
  producing nothing — a dead board adapter, a screen backend answering blind — still
  shows only in the DB.
  There is no metrics/alerting beyond the per-job Telegram notification. Includes the deferred scraper **canary self-tests** and
  proactive Telegram/banner alerting for silently-broken scrapers (SPEC §9 points
  here).
- **AI fetch+score fallback for unparseable JDs** — `[FETCH · L · optional]`. Where text
  extraction fails (JS-rendered / bot-walled / odd markup), let the scorer's model
  fetch the job page and score fit directly from the raw page, bypassing
  parse-then-score. Candidate landing spot for the iCIMS/ByteDance tail if a plain
  fetch isn't enough.

