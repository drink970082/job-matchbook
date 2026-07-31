# Backlog — the open catalogue

> The *catalogue* half of [`PROGRESS.md`](./PROGRESS.md), split out on 2026-07-30 so a
> session that only needs the current state does not load 600 lines of open items.
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

- **Capture the quota snapshot at pass START, not after the fit phase** —
  `[SCORE · XS · would sidestep the 403 entirely]`. `capture_usage` runs at the end of a
  pass, i.e. immediately after a burst of paid calls on the same account. That is exactly
  the moment a rate limiter would refuse, and the 403 this system keeps hitting is
  consistent with (though not proven to be) one. Capturing before the fit phase costs the
  same single call and lands it when the account is cold.
  **The trade is what the bar shows:** a pre-pass snapshot omits the pass's own spend, so
  the web bar would lag by one pass. Capturing at both ends doubles the call but is still
  free of quota. **Decide only after the WARNING rate has been measured across days** — if
  the retry (PR #63) drops it near zero, this is unnecessary complexity.

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

- **`make eval-screen` measures far less than its headline numbers imply — 19 of the
  "81 gate-eligible rows" can actually fail it** — `[SCREEN · S · found by the PR #24
  pre-merge review 2026-07-28, all three arithmetic claims re-verified]`. The gate is
  real and it caught real defects; what is wrong is reading its per-requirement scores as
  measurements of the model.
  1. **The clearance half is a tautology and CANNOT fail, for any model behavior.** Of
     24 clearance rows, the 20 golden `no bar` rows contain no `CLEARANCE_TOKENS` match
     in excerpt+title, so `_check_clearance` short-circuits on the evidence floor whatever
     the model returns; the 4 that do carry a token are all golden `true`, which
     `judge` excludes from `false_disq` by construction. **Zero rows can produce a
     clearance false disqualification**, so "20/24 → 0" measures the floor's own regex
     over the rows it was tuned on — and no future clearance regression is detectable
     here. Fixing it needs corpus rows that carry a clearance token *and* are golden
     `no bar` (a JD naming a clearance it does not require). **Re-verified independently
     2026-07-29** (the arithmetic, not the write-up): 24 clearance rows, exactly 4 with
     `requires_clearance: true`, and exactly 20 carrying the corpus's own note *"no
     clearance token anywhere; 'security' is the engineering domain"* — the same 20.
     **Fix this one first.** The clearance check that ran 83% wrong for four days is the
     reason this eval exists, and it is the half the eval cannot see.
  2. **The sponsorship half rests on 5 rows, not 21.** Only 10 of the 21 are golden
     non-`refuses`, and 5 of those retrieve no snippet at all, so nothing the classifier
     does can move them.
  3. **4 corpus rows are labeled on evidence the corpus does not contain.** Ids
     456/529/534/538 (all IMC, golden `refuses`) have excerpts of exactly 1606 chars —
     the `_readme` truncation cap — with no `sponsor`/`visa`/`citizen`/`authoriz`/
     `right to work`/`immigration` token anywhere in them. The cap cut the labeled
     sentence off and left a lead window. They are guaranteed misses independent of any
     model or prompt, so every recall figure quoted from this gate is computed partly
     over rows whose stated premise ("the refusal sentence is inside the text handed to
     the model") is false. Re-verified by inspection 2026-07-29: all four excerpts end in
     the `" [...]"` marker (the 1600-char cap plus 6 chars, which is where "exactly 1606"
     comes from) and carry none of those tokens.
     **FIXED 2026-07-29** (`fix/eval-corpus-vocabulary`; SPEC §12, CHANGELOG).
     `--selftest`'s corpus invariants checked that a label is assertable, never that the
     excerpt could support it; `unsupportable_bars` now asserts that a row labeled as a
     **bar** carries that requirement's vocabulary in its own excerpt+title, so this class
     fails loudly instead of silently deflating recall. It found exactly these four and
     nothing else across the other 79 rows.
     **The four excerpts were then REBUILT, and the repair is local data, not a commit**
     (`apps/worker/eval/` is gitignored; pre-repair copy at
     `eval/screen_golden.jsonl.backup-20260729-pre-excerpt-repair`). Each now carries
     *"Please note that immigration sponsorship is not offered for this specific opening"*
     — the sentence the labels always rested on. **`sponsorship_snippets` could not do the
     rebuild**, which is the bullet-JD defect below biting in practice: these JDs are
     period-free blocks, so its +/-1 *sentence* window returned the whole JD and the
     1600-cap cut the refusal off a second time. A +/-780 *character* window centred on
     the match was used instead.
     **RE-RUN 2026-07-29, and the repair paid off: 3 of the 4 flipped from
     structurally-unhittable to HIT** (456/534/538, all 3 draws each); only 529 still
     misses. Recall is now **31/37 (84%)**; the comparable pre-repair figure is 28/37 (76%),
     since those 3 could not be reached by any model or prompt. The false-disqualification
     gate was unaffected as predicted — golden `refuses` rows are excluded from `false_disq`
     by construction. Full report: `apps/worker/eval/last_screen_run.md` (gitignored).
  **Not fixed here** because 1 and 2 are a corpus rebuild plus a re-run, and #24 was
  already merging; the numbers on that PR are honest about what was *run*, not about what
  the corpus can reach.
  **One smaller premise gap in the same tool — FIXED 2026-07-30** (CHANGELOG). It was
  latent, not active: `screen_eval` ignored `OLLAMA_NUM_CTX`, which `run.main` threads
  into both the screener and `screen_posting`, so with that var set the eval would have
  run a different context window than production — but it is commented out in
  `apps/worker/.env`, so both sides ran 8192 either way. It now reads the same var and
  passes it to both. Fixed alongside it: the report header named `"{backend} default"`
  rather than the real `DEFAULT_*_SCREEN_MODEL`, which is exactly what a reader diffs
  across A/B runs. (The `num_ctx*2` JD truncation cap could never diverge — corpus
  excerpts stop at 1606 chars against a 16,384-char cap.)

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

- **Sponsorship recall is a DELIBERATE, pinned trade** — `[SCREEN · open by design]`.
  Retrieve-then-classify shipped 2026-07-28 (false disqualifications 2 → 0; behavior in
  SPEC §7.1, reasoning in CHANGELOG). What stays open is the other direction: the
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

- **The location gate's tiers 2 and 3 — not built** — `[SCREEN · M]`. Tier 1 shipped
  2026-07-29 (evidence-tiered gate, SPEC §7.1 + CHANGELOG; the trade is pinned in CI at 0
  false discards over 1,611 live strings, residual leak exactly 6 strings / 14 rows).
  **Still open:** a free Ollama fallback for the 3.1% of rows the gazetteer cannot
  resolve, and the fit scorer as a second net.

- **Workday prose-date age-gating — COUNTED 2026-07-30: the reduction is ZERO and the
  gate structurally cannot fire. Dead lever, do not re-open it** — `[FETCH · closed]`.
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
  **So the framing below was wrong and is corrected here:** the ~6,703 figure is the
  **28-board** post-stub-gate total, and workday's share of it is 4 — about 0.06%. The
  prose-date parser cannot move that number however it is tuned; the remaining detail-call
  cost lives on the phenom two-step boards. Parse coverage was 100% (14/20/21/30+ days, no
  "Today"/"Yesterday"/locale strings), so the gate is neutralised by the threshold, not by
  parse misses.
  Original entry follows. `parse_stub` dates `"Posted N+ Days Ago"`
  prose (given `now`), so the max-age gate can drop stale workday stubs before the detail
  call (CHANGELOG, SPEC §7.1). Only the confident English `"N[+] Days Ago"` form is
  parsed — a lower bound on age — so "Today"/"Yesterday" and any other locale/wording
  leave `posted_at` None and are kept; a mis-parse can never drop a good posting.
  Unmeasured: how much of the ~6,703 remaining detail calls this actually cuts.
  **It is not waiting on a run** — `max_age_days: 30` is set and the daemon has been
  gating 6 passes/day since 2026-07-28, so the drop is already happening uncounted. The
  free measurement is offline: list the two workday boards (`arrowstreetcapital`, `mlp`)
  and count stubs whose `_stub_age_days` exceeds 30 — list calls only, zero detail calls,
  no DB write. Carried over from `main`; the 2026-07-26 integration dropped it once and
  the §7 review caught it.
- **Citadel's JD is unreachable behind Cloudflare — both rows kept anyway** —
  `[FETCH · decided 2026-07-22 · do not re-derive]`. `browser/citadel.com` and
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
  **REPRICED 2026-07-29:** "a few renders per cycle" is 6x/day now that the daemon runs,
  for a known-zero yield — reopened as part of the one watchlist decision in the
  empty-JD-boards entry below.
- **Stale-mount recovery — sidecar half PROVEN 2026-07-22, detection half still
  unobserved** — `[INFRA · S · needs a real event]`. A live drill with a throwaway container
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
  **DRILLED 2026-07-29, and the drill overturned the reasoning behind PR #47**
  (`fix/health-probe-real-table`; the matrix is in SPEC §6). Three candidate probes x four
  filesystem failures, against a throwaway copy: **`SELECT 1` and a `sqlite_master` read
  are indistinguishable in every mode**, so #47 was inert — once the connection is open both
  read through the same already-open fd, which is the same fact that made `chmod` a bad
  proxy. Nothing detects a break that happens *after* connect, and that is accepted rather
  than fixable. The mode that discriminates is a **missing DB file**, where SQLite silently
  creates an empty database and both weaker probes report healthy forever against a tracker
  with no data; the probe now names a real table (`SELECT 1 FROM job_postings LIMIT 1`), so
  that becomes `no such table` → 503 → autoheal restarts.
  **What is still unobserved is narrower than this entry used to claim:** not "detection",
  but detection of a *real WSL2 stale mount specifically*. The lesson worth keeping is that
  the probe's strength was argued for two rounds and only measurement settled it.
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

- **The feed's workday route reports a detail-fetch collapse on every pass — DIAGNOSED
  2026-07-30, it is DEAD REQS and the entry closes as harmless** —
  `[FETCH · XS · closed]`. All three live passes logged
  `[feed] workday: detail-fetch collapse — 0/1 resolved (scraper may be broken)` and
  `0/2` (the 08:00 pass logged three such lines). The warning is `run_feed`'s deliberate
  signal that a detail source resolved ids but kept **none** — the case it exists to make
  loud rather than silent, so the mechanism is working. What is unknown is whether these
  are genuinely dead reqs (the feed surfaces an `externalPath` the CXS endpoint no longer
  serves, which would be normal and harmless) or the workday `fetch_one` breaking on a
  shape it cannot parse. The counts are tiny — 1-2 ids per group — so this is cheap
  either way; it is listed because "may be broken" repeating six times a day is exactly
  the signal that gets tuned out. **And the repetition is guaranteed, not incidental:**
  workday's `existing_external_ids` prune never matches (the feed carries `externalPath`,
  the DB stores the GUID), so these ids are re-fetched every pass forever.
  **The reason is now self-diagnosing — SPLIT 2026-07-29** (`fix/feed-failure-reason`;
  SPEC §7.1, CHANGELOG). `_detail_fetch` used to file a raise/`None` (dead req) and an
  invalid posting (broken parser) under one `detail_fetch_failed` string, so the record
  could not say which. It now returns `(id, reason)` pairs and an invalid posting is filed
  as `empty_description` — the same string the watchlist path uses for the same condition,
  so one query over `feed_unresolved` covers both paths — and the collapse warning names
  the split (`N unparseable — scraper may be broken` vs `N dead req(s), none unparseable`).
  **The free DB read ran 2026-07-30 and the answer is DEAD REQS.** `feed_unresolved` has
  **zero** `empty_description` rows on the `simplify` feed path — all 213 of those are
  `feed='watchlist'`, i.e. `run_fetch`'s board path, not `_detail_fetch`. The workday host
  is 36 rows, every one `detail_fetch_failed` (27 post-split, 9 pre-split). If the CXS
  parser were returning bodies it could not populate, `_detail_fetch` would file them as
  `empty_description`; it never has. Corroborated three ways: 374 feed-sourced workday
  postings landed since 07-29 against 36 failures; the *same tenants* (walmart, kla, caci,
  vumc) succeed and fail in adjacent passes, where a parser break would fail a tenant
  uniformly; and the failing URLs churn rather than recur (3 of 36 ever seen failing
  twice), the signature of a delisted req.
  **The prune-never-matches claim is CONFIRMED in code and data:** 2,598 workday rows,
  **0** whose `external_id` starts with `/`, so the set difference subtracts nothing and
  every feed-surfaced workday listing pays one CXS GET per pass forever — absorbed
  silently by `ON CONFLICT DO NOTHING`. That is why the line repeats; it is not evidence
  of a fault.
  **The one residual, and it is a labelling limit not a defect:** `detail_fetch_failed`
  still conflates a genuine 404 with a transient timeout or 429, because `_detail_fetch`
  catches bare `Exception` without inspecting status. Neither is a scraper break, so the
  verdict stands.
- **655 rows already in the `new` queue fail today's filters and will each cost a paid
  fit call** — `[SCORE · XS · measured 2026-07-29 · nothing done]`. `prefilter_postings`
  runs at *ingest*; nothing re-applies it to a row already stored, and `screen_posting`
  re-runs only the deterministic intern/location gate, not title or age. So every row
  ingested before its filter existed keeps its place in the queue. Re-running the current
  `title_filter`/`title_exclude`/`max_age_days` over the live queue: **413 of 2,380 from
  2026-07-22 (17%), 118 of 1,579 from 07-23 (7%), 124 of 1,701 from 07-29 (7%)** would be
  refused today. The 07-29 share is the killed hand-run of 2026-07-28 20:57, which
  ingested 1,555 rows on code that predated the feed pre-filter (PR #29).
  At ~0.8 paid messages each that is ~520 messages of scoring on postings the operator's
  own config would not accept — but **that headline overstates the live exposure ~5x, and
  the split is the point.** 531 of the 655 are from 07-22/23, and the score queue is
  most-recently-touched-then-newest, so they are parked by construction and cost nothing
  until someone deliberately drains the backlog. What the daemon will actually reach is the
  **124 rows from 07-29 — ~99 messages, ~5% of a weekly window**, and it will reach them
  within days at ~38 new rows/pass.
  **SWEPT TWICE 2026-07-29, and the counts above are now history — do not re-quote them.**
  A first bulk `UPDATE` at 19:45Z took 336 rows (285 from 07-22, 51 from 07-23) and left
  `score_detail` NULL, so those carry no reason. A second, operator-run pass at 00:07Z on
  07-30 took **275** more and stamps
  `disqualification_reason: "prefilter: refused by the current title/age filters"`; its ids
  are in `db/runs/prefilter-sweep-20260729.json` and the pre-sweep DB copy is
  `db/applications.db.backup-20260729-2242-pre-prefilter-sweep`, so it reverts row-for-row.
  Queue 5,544 -> 5,269. The **124 from 07-29 was down to 3 by then** — the daemon had
  already reached and scored the rest, exactly as this entry predicted.
  **Two things the sweep taught, and they outlast the numbers.** (1) The count is a
  function of *when you run it*: `_too_old` truncates both sides to a date (`[:10]`), so
  every posting ages a full day the instant UTC rolls over — the same queue measured 198 at
  22:39Z and 275 at 00:07Z, 88 minutes apart. (2) **The leak is structural, not a backlog
  artifact.** `prefilter_postings` runs at ingest only and `screen_posting` re-checks
  location/intern but never title or age, so any row that sits long enough ages past
  `max_age_days` and becomes a paid call on a posting the config refuses. The queue
  regrows this on its own, roughly a day's worth at a time; at `--score-limit 60` against
  ~38 fresh rows/pass the daemon dips ~22 rows/pass into exactly that stale region.
  **Follow-up the review recommended and this branch did NOT take:** the web has no
  `prefilter` discard cause (`DISQUALIFY_CAUSE_PATTERNS` in `apps/web/src/lib/actions.ts`,
  the type above it, and `CAUSES` in `DiscoveredJobsTable.tsx`). The rows stay *visible*
  in the Discarded bucket — that filter keys on `disqualified`, not on cause — but they
  cannot be selected, so an operator cannot bulk-remove them. That is ~206 now, plus the
  275 rows still carrying the operator's own 2026-07-29 sweep string once they
  re-discard, against a 1,556-row bucket. One pattern `%prefilter:%` covers both
  populations, since the strings differ (`prefilter: title refused by the current
  filters` vs `prefilter: refused by the current title/age filters`). Six lines of web
  code, left out here only because this branch carries no web change and no web tooling.
  **The TITLE half of this shipped 2026-07-31** (`fix/prescore-prefilter`; SPEC §7.1/§9 +
  CHANGELOG): `run_score`'s free phase-0 sweep re-applies `title_filter`/`title_exclude`
  to already-queued rows, 206 of the 5,941 that survive the deterministic gates.
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
    discards, and under the age-inclusive version the next phase-0 sweep re-kills **26**
    of them (22 on age alone, 2.4% of the requeued set), overwriting the `score_detail`
    they carried. **Get the shape of this right before re-using it as an argument, because
    two earlier versions of this bullet had it wrong:** measured 2026-07-31, 881 of the
    919 die at the location/intern gates *before* the stale check is consulted, so the
    population at risk is only the 38 that survive them. Of those, the age-inclusive
    version re-kills 26 — **12 carrying `degree:` and 14 `authorization:`** — while the
    shipped title-only check re-kills 4 (all `authorization:`). The evidence lost is NOT
    the `location:` verdicts: `deterministic_screen` regenerates those byte-identically
    every pass, so nothing goes missing there. It is the LLM-derived `degree:` and
    `authorization:` ones, which nothing recomputes. Far smaller in count than the first
    estimate of 591, and worse in kind.
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
  If the operator does want a queue TTL, it wants the shape the 2026-07-29 sweep had — a
  deliberate run with a saved id list and a pre-run DB copy, revertible row for row — not
  a silent six-times-a-day deletion.
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
- **`apply.careers.microsoft.com` returns 50 bodyless postings post-split — the largest
  single `empty_description` source and NOT the known partial-drop story** — `[FETCH · S ·
  surfaced 2026-07-30 by the #46 reason split · uninvestigated]`. The split that made the
  feed's collapse diagnosable also made the *watchlist* path's failures countable for the
  first time, and the counts do not match this file's description of them.
  `feed_unresolved` post-split, all `feed='watchlist'`: **`apply.careers.microsoft.com`
  50**, `globalcareers-msci.icims.com` 5, `citadelsecurities` 6, `citadel` 2.
  (`careers.qualcomm.com`'s 81 are all pre-split.)
  **Why 50 is the number to look at:** the entry below describes `phenom/microsoft` as a
  *partial-drop* board losing "4-6 bodyless rows per pass" while serving full descriptions
  for the rest — that is a documented no-op. 50 post-split rows is an order of magnitude
  more than that reading predicts, so either the drop rate has changed or the entry below
  under-counts it. Nobody has looked.
  **MEASURED 2026-07-31, and the premise of this entry is WRONG: nothing is being lost.**
  Twelve of those rows were re-requested against the live detail endpoint — **eleven
  returned a full 5,029-8,376 char `jobDescription`** and one returned `404 Position not
  found`. Then the decisive check: **all twelve are ALREADY in `job_postings`,
  `pipeline_status='new'`, with full descriptions** (ingested 07-22 or 07-29). So an
  `empty_description` row on this host is a *log of one failed detail call on a
  re-fetch*, not a lost posting: `upsert_postings` is `ON CONFLICT DO NOTHING`, so a
  later bodyless re-fetch cannot overwrite the good stored row, and `run_fetch` drops the
  bodyless duplicate and files it here. Same class as the workday
  prune-never-matches finding above — a recurring log line, not a defect. What it does
  cost is one wasted detail GET per already-stored position per pass.
  **A detail-leg retry was built for this on 2026-07-31 and REVERTED, so it is not
  re-proposed.** It rescued nothing (the postings were never lost), and the pre-merge
  review priced it: the retry is a *per-position* budget for a *board-wide* failure —
  exactly the smell PRINCIPLES names — so a board whose detail endpoint throttles or
  permanently 403s costs 14s (up to 90s) and 4 requests per position with no circuit
  breaker: **3h53m to 25h for a 1,000-position board**, against a serial `run_fetch`
  with no deadline and a `pass_lock` that REFUSES rather than queues, so an overrun would
  suppress the next 4-hourly pass entirely. If it is ever wanted, it needs a board-level
  breaker first (stop hydrating this board after K consecutive throttled details), and
  404 must stay terminal.
- **Empty-JD boards ON the watchlist — MSCI icims** — `[FETCH · XS · found 2026-07-22]`. The
  full fetch pass dropped **43 bodyless postings** from `icims/globalcareers-msci`: its
  iCIMS list endpoint carries titles but no description. Same property as the Uber/Netflix
  tier below, except this one is already on the watchlist. Non-destructive now (the guard
  drops them; the next run will also record them in `feed_unresolved`), but it produces
  nothing, so it is a candidate to drop or to route through a detail-fetch once one
  exists. `citadelsecurities`/`citadel` (browser) are the same story (dropped 7 + 3).
  **CONFIRMED RECURRING, every pass, 2026-07-29:** the live daemon logs the identical
  drops on all three passes — `icims/globalcareers-msci` **42**, `citadelsecurities` 7,
  `citadel` 4, `phenom/microsoft` 4-6. They are re-fetched and re-dropped **6x/day**,
  which is what turns a documented no-op into an ongoing fetch cost.
  **The choice is binary, and one decision covers the three zero-yield rows** — `msci`
  plus the Citadel pair above. `watched_companies` has no `active` column, so there is no
  soft-disable: the row stays and keeps paying, or it is deleted. Deleting is the cheap
  call — re-adding is one `onboard-board` run and the rationale is recorded here, whereas
  adding a flag is a schema change, i.e. the thing "No schema migration path" below exists
  to avoid. **`phenom/microsoft` is NOT in this set:** it drops 4-6 bodyless rows per pass
  but serves full descriptions for the rest, so it is a partial-drop board, not an
  empty-JD one.
- **Intake-cut evidence — MEASURED 2026-07-31, the decision is the operator's**
  — `[FETCH · S · Q3 · numbers ready, nothing changed]`. Q3 is the only lever that
  reduces *demand* rather than re-ordering it, and it was never costed. Three findings.
  **1. 37% of the live `new` queue (3,440 of 9,381) dies on the free deterministic
  gates** — it was fetched, stored, and will be discarded without a model ever reading
  it. Per board, the share of its queued rows that die there:

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
- **`score_workers` defaults to 4 for every fit backend — codex rollout cleanup
  regresses under it** — `[SCORE · XS · decision pending]`. Plan Stage 5 made the fit loop
  concurrent (quota-neutral: N parallel `codex exec` calls spend the same messages as
  N serial ones). But the codex quota capture reads its figures from the session
  *rollout*, and its cleanup deletes that rollout **only when exactly one new rollout
  exists** — a deliberate guard against nuking a concurrent session's history. At 4
  workers two or more rollouts always co-occur, so the delete never fires and
  `~/.codex/sessions` accumulates. Telemetry itself stays correct (the snapshot write
  is atomic and its temp file is per-call unique, so concurrent captures cannot tear
  it); only the cleanup degrades. **Decision:** leave it (documented-safe, litter only)
  or default the codex/`claude-code` fit path to 1 worker. Screen concurrency already
  defaults to 1 for `ollama` for an unrelated reason (a single GPU serialises anyway).
  **Still open 2026-07-29:** `run.py` line 231 still defaults `score_workers=4`, and
  nothing in SPEC/CHANGELOG records a decision — the 2026-07-29 audit dropped this entry
  by mistake and it is restored here.
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
## Enhancements — not built, optional

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
  **The backoff is not covering qualcomm, and the reason is that it is not a 429** —
  `[FETCH · XS · observed 2026-07-29]`. Every live pass fails it identically:
  `phenom/careers.qualcomm.com: skipped after error: 403 Client Error: Forbidden ... 
  &start=1060` (also seen at `start=990`, `start=1220`). A **403 deep into pagination**,
  at a varying offset, reads as a block rather than a rate limit, and the bounded-retry
  path only handles 429. So qualcomm is lost on every pass and the salvage never runs.
  **FIXED 2026-07-31** (`fix/phenom-403`; SPEC §7.1/§9 + CHANGELOG). The look happened:
  the failing offsets return **200** when probed cold from a fresh session, so the 403 is
  not about the offset or a missing page — it is a WAF tripping on the pass's cumulative
  request volume, i.e. a throttle with a different status code. It now takes the same
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
- **`custom` `html` mode — BUILT on PR #21, but it ingests NOTHING as documented** —
  `[FETCH · M · reviewed 2026-07-26 · PR #21 CLOSED unmerged 2026-07-29]`. The executor
  works; the value claim does not. No branch carries this now — re-cut it when `custom`
  gains the chained detail call. (#19 closed unmerged 2026-07-28 behind the autoheal redo
  #27; #22 and #23 the same day behind the screen stack #24.)
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

