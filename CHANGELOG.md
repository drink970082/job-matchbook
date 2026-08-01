# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The current
system is described in [`docs/SPEC.md`](./docs/SPEC.md).

## [Unreleased]

### Added

- **A `prefilter` disqualification cause in the Discarded bucket, so the swept rows can be
  bulk-removed.** `run_score`'s free phase-0 sweep re-applies the operator's own
  `title_filter`/`title_exclude` to already-queued rows, and it is the bulk producer of
  discards — 1,504 rows carry that reason as of 2026-07-31, against a bucket the operator
  reviews by hand. They were already *visible* (the bucket filter keys on `disqualified`,
  not on cause) but not *selectable*, so there was no way to clear them. Adds the value to
  `DisqualifyCause`, one `%prefilter:%` pattern, and one entry in the UI's `CAUSES`;
  `disqualifyCauseIds` is reused unchanged (SPEC §7.3).
  **It is deliberately not a hard-constraint cause.** Every other cause names a
  requirement the *candidate* fails; this one names the operator's own config refusing the
  posting, which is why the label reads "Pre-filter (title/age)" rather than naming a
  requirement.
  **The worker writes two `prefilter:` spellings and only one of them ever reaches this
  filter** — measured 2026-07-31: `"prefilter: title refused by the current filters"` is
  1,504 rows, all `discarded`; `"prefilter: refused by the current title/age filters"` is
  56 rows, all still `new`. `disqualifyCauseIds` scopes to `discarded`, so the second
  contributes nothing today; the pattern is left as a wildcard so it does once those rows
  discard.

- **A free seniority pre-ordering decides which rows deserve the paid fit call.** 96% of
  paid calls came back a "no" and 54% of those were `seniority=too_junior` — the budget
  was being spent proving that jobs that were never viable are not viable. That half is
  reachable for free: SCORING §4.2 measures seniority only against a bar the JD states
  explicitly, which is the closed-vocabulary bounded extraction §9.1 calls
  weak-model-capable. Same shape as the degree fix — the local model reports
  `stated_min_years` / `stated_rank` as literally stated, **code** compares them against
  the new `candidate.years_experience`, and the model never decides.
  **It re-orders and never filters.** A demoted row is stamped `deprioritized_at`, keeps
  `pipeline_status='new'` and its place among its peers, and sorts behind every undemoted
  row; `UPDATE job_postings SET deprioritized_at=NULL` reverses it row for row. That is
  not caution for its own sake: the layer was measured against the strong scorer's own
  verdicts rather than human labels, so it may decide which row gets the next paid call
  and may not delete a posting (SCORING §9.3).
  **Measured over 446 rows on `qwen3.5:4b` with zero quota** (`make eval-seniority`,
  new): precision **0.964**, recall 0.757, 44% demoted, 0 provider errors — and the
  number that actually decides it, **0 false demotions on rows the strong scorer called
  `domain=match` and 0 on rows that were notified**. The whole notify payoff set survives
  undemoted, so a false demotion costs a delay on a row the notify gate would have
  dropped anyway. A keep-direction veto clamps the model's number down to the smallest
  years-figure the JD literally states, which cut false demotions 20 -> 7 by catching the
  degree-conditional ladders the model mis-reads.
  Free only where it is local: wired on the `ollama` screen backend and nowhere else, and
  off entirely when no candidate is configured. Its prompt is its own file with its own
  eval gate, so the screen's degree/authorization/clearance extractions do not end up
  behind it. (SPEC §7.1/§9, SCORING §5.7, design record in
  `docs/superpowers/specs/2026-07-31-seniority-preordering-design.md`.)

### Changed

- **Amazon is fetched US-only, cutting 768 rows per pass with zero coverage loss.** The
  `custom/amazon` recipe URL gains `normalized_country_code[]=USA`, a board-side facet, so
  the non-US rows are never fetched, parsed or stored. A/B'd through the production
  `fetch_company` and the real gates: **unfiltered 2,035 fetched → 640 past title/age →
  411 past the free gate; filtered 1,267 → 411 → 411.** Identical survivor set, and 0 of
  the 768 removed rows would have survived — the filter removes exactly what the location
  gate was already discarding for free, just earlier. Every row on that board carries a
  country code (0 nulls), so this is a clean partition rather than a heuristic, and there
  is no unjudgeable bucket to drop silently.
  **The live change is a `watched_companies` row, not a file in this repo** (the watchlist
  is DB-owned), so it does not appear in the diff; `config.yaml.example` documents the
  filtered URL (its whole watchlist block is commented out, so it is a reference for a
  fresh install rather than something that ships), and the pre-change DB copy is at
  `db/applications.db.backup-20260801-1318-pre-amazon-country-filter`.
  **It does not generalise, and the negatives cost more to establish than the win.** TikTok
  and ByteDance accept city codes only (`CN_6` and `ST_*` both return 0); Workday silently
  *ignores* an unrecognised `locationCountry` facet (Micron 2,725 → 2,725, Cisco
  1,018 → 1,018, BlackRock 257 → 257, Japan and London rows intact); greenhouse ignores
  `?location`/`?country`/`?offices` alike. Amazon worked because `amazon.jobs` is a faceted
  *search* API; ATS board embeds serve the whole board by design. Full table in
  `BACKLOG.md`'s intake-cut entry.
  Pinned by `test_a_recipe_urls_own_query_string_survives_pagination`: pagination goes in
  `params` and is never spliced into the recipe URL, so a recipe carrying its own filter
  keeps it on every page.

### Fixed

- **`requirements.txt` certified an `anthropic` install that cannot run.** The floor was
  `>=0.40`, while `score/backends_claude.py:47/49` and `score/backends_screen.py:62` pass
  `thinking={"type": "adaptive"}` and `output_config={"format": ...}` — kwargs an 0.40
  client rejects with `TypeError`, so `--score-backend claude` would have died on its
  first call rather than on anything about the backend. Floored at **0.107.1**, the
  version in `apps/worker/.venv`, checked directly for both kwargs in `Messages.create`'s
  signature. The true minimum is probably lower; a verified floor beats a guessed one.
  Related: BACKLOG's "the claude scoring backend has never run in this deployment" already
  said to check the SDK floor before the first live run — this is that check.

- **Three code comments and seven doc lines asserted the codex quota is MESSAGE-bound. It
  is per-TOKEN credits, and the wrong claim was load-bearing.** `run.py:69`,
  `pipeline.py:811`, `backends_codex.py:49`, `SCORING.md` §4.5/§5.6/§8.5 and `SPEC.md`
  §7.1/§10 all justified the batching machinery as "the actual quota win" on the strength
  of it. Measured 2026-07-31 over 158 production calls from the codex rollout files'
  per-call token counts (the instrument `SCORING.md` §4.5 said did not exist): billing has
  been per-token since April 2026, so a batch saves the repeated ~5.5k-token
  rubric+profile+résumé prefix, not N-1 messages. Comments and docs only — no behavior
  changes, and batching stays parked at 1 on the correctness grounds that always held it
  there (cross-JD domain bleed), which never depended on the quota model.
  Two figures kept alongside the correction because they bound future arithmetic: our
  prompt is **~39%** of what a call bills (6,512 of 16,775 tok; the rest is codex CLI
  harness overhead), and `cached_input_tokens` reads **0** on codex-cli 0.146.0, so prefix
  caching is not a lever available today. `SCORING.md` §5.6's "concurrency is
  quota-neutral" survives the correction — each call bills its own tokens either way — and
  now names caching as the one mechanism that would break it.

- **The `capture_usage` failure has a NAME — HTTP 403 — and is now retried. What
  produces the 403 is still open.** #60's cause-naming earned its keep immediately: the
  first failing pass after it shipped (12:00 on 2026-07-31, 26 rows fit-scored) printed
  `returned HTTP 403 (Forbidden)`, ending a week of a bare `False`.
  **The interpretation is NOT established, and an earlier draft of this entry overclaimed
  it.** Hand-calling the endpoint afterwards gave 403 / 200 / 403 within forty seconds,
  which was read as "a blip, not a rate limit" — but Cloudflare rate-limiting rules
  commonly answer **403** rather than 429, and a limiter near its threshold produces
  exactly that alternation. The hand calls also came from a different client than the
  in-pass failure, so they may not sample the same phenomenon at all. Both hypotheses
  remain live.
  So the retry is deliberately agnostic rather than tuned to one of them: 4 attempts on a
  growing schedule (2s, 8s, 20s) that reaches past the only interval at which the endpoint
  was ever *observed* to change state. `_get_json` splits into a retrying wrapper and
  `_get_json_once` returning `(data, retryable)`; 401 and 404 are verdicts, not blips, and
  are not retried, so "not logged in" still answers immediately.
  **What this does not do is end the staleness.** At the roughly 2-in-3 per-call failure
  rate observed, four attempts still leave ~20% of passes without a snapshot, and "three
  hand calls in a row succeeded" cannot distinguish a 70% success rate from a 100% one.
  The measurement to take is the WARNING rate across passes, over days, not more hand
  calls. The remedy that would sidestep the question entirely — capturing usage at pass
  START, before the account is hot — is recorded in `docs/BACKLOG.md`.
- **The free seniority pre-ordering was throwing away evidence the model got right —
  70% of its misses were code's fault, not the 4B's.** Classifying the 61 misses by cause
  instead of counting them found three defects, all in `score/seniority.py`, and fixing
  them moved **every** gate axis at once: precision 0.964 -> **0.975**, recall 0.757 ->
  **0.793**, demote share 0.442 -> **0.457**, still **0** false demotions on a
  `domain=match` or notified row (`make eval-seniority`, 446 rows, zero quota).
  (1) *A cap is not a floor.* `stated_years` collected any number before a years token, so
  *"Less than 2 years Technical engineering experience"* read as a 2-year **minimum** and
  demoted a T-Mobile `Assoc Engineer` posting written for exactly this candidate — the
  rubric had said in prose since §4.2 that a cap is entry-level and NOT a bar. The same JD
  contributed *"At least 18 years of age"* as eighteen years of experience — which on its
  own changed nothing, since `clamp_years` minimises and `min(2, 18) = 2`; the age rule
  only becomes load-bearing once the cap rule removes the 2.
  **Two traps in this one, both handled:** a *negated* cap phrase is a minimum — "no less
  than 5 years" contains the word "less" and keeps its figure — and the rule is **not**
  purely keep-direction. `clamp_years` minimises over the stated set, so removing a low
  capped figure RAISES the clamped bar: *"internships up to 1 year considered ... 5 years
  required"* now clamps to 5 rather than 1 and demotes where it did not. That is the right
  reading of the JD and it is still a demotion the rule created, so it carries §9.3's
  demote-direction bar.
  (2) *An unevidenced years bar is dropped.* `clamp_years` passed the model's number
  through untouched when the JD stated no figure at all, so an invented bar survived —
  while the rank path had refused exactly that since the vetoes landed. This is the years
  path's missing half of `rank_stated_in`.
  (3) *The rank-cancelling veto now compares magnitude, not existence.* `clamp_years`
  returns `None` **iff** its input is `None`, so testing `years is not None` after the
  clamp was the same as testing before it: a clamped-down bar silently cancelled a rank
  the JD does state. A Microsoft *"Senior Fabric Design Verification Engineer"* stating
  5+ years was clamped to 1 by a stray *"1 year of experience with ..."* in the preferred
  qualifications and kept as if open to a new grad. **34 of the 61 misses share this
  mechanism; the shipped fix recovers the 9 of them where the model also reported a rank
  the JD states** — for the other 25 the model returned no rank, so the rank branch has
  nothing to fire on and the row is still kept.
  Behavior is SPEC §7.1, the contract and the full measurement SCORING §5.7. A 32-row
  held-out slice (every row scored since the golden corpus was frozen) behaves identically
  to the old code — 0 false demotions either way — which is a false-demotion check, not a
  confirmation of the recall gain: it carries only 3 positives.
  **A fourth candidate, a title-token rank floor, is measured and deliberately NOT
  shipped.** It is the largest in-sample win available (recall -> 0.900) and it owns the
  only held-out false demotion any candidate produced; SCORING §5.7 carries both numbers
  and the decision is the operator's. A fifth, widening `rank_stated_in`'s vocabulary, is
  rejected outright as provably redundant *and* a re-opening of the false-discard
  direction §9.3 warns about.

- **`capture_usage` failures now name their cause, and the "never broken" verdict is
  withdrawn.** The 2026-07-31 root cause — the passes had stopped fit-scoring, so the
  guarded call correctly never ran — was true of that window and not the whole story: the
  08:00 pass on 07-31 fit-scored **34** rows and still wrote no snapshot. The WARNING
  shipped 8h40m earlier (#53, 00:10 EDT the same day) is what caught it, the first time
  this failure has announced itself instead of being found by an `ls -la` days later.
  Called by hand 20 seconds later the same fetch returned 200 (35% stale on disk against
  37% live), and `~/.codex/auth.json` has not been rewritten since 07-26, so the
  concurrent-`codex exec` theory is dead a second time.
  It stayed undiagnosed because **every** route to a `False` return was a bare `None` or
  `False`, making a 403, an expired token, a DNS blip and a malformed body
  indistinguishable. All of them now say what happened: a non-200 with status and reason,
  an `HTTPError` (which `urlopen` **raises** rather than returns, so the status check
  never saw a 4xx at all), a connection or truncated-body failure with its exception
  type, "not logged in" with the resolved `CODEX_HOME`, a 200 whose body is not an
  object, a 200 with no `rate_limit`, a 200 whose window carries a null `used_percent`,
  an unknown backend, and the blanket catch that also covers the file write. That last
  one is what lets the fetch keep a NARROW catch: an unanticipated failure surfaces in
  the log rather than as silence. `http.client.HTTPException` is named in that tuple
  because `IncompleteRead` and `BadStatusLine` subclass neither `OSError` nor
  `ValueError` — a truncated body behind a CDN is textbook intermittent and previously
  escaped the fetch to die silently.
  **Three untested candidates**, in the order worth checking: a 429/403 right after a
  burst of paid calls (note the endpoint is called ONCE per pass, so the evidence is
  **n=1 against n=1** — one usage call failed after 34 fit calls where one succeeded
  after 7); a 200 with a null `used_percent` under the same load, which has no status
  code to show for it; or a truncated body. (SPEC §7.1/§9.)
- **Rows the operator's own TITLE filters would refuse were still buying paid fit
  calls.** `prefilter_postings` runs at INGEST only, and `screen_posting` re-checks
  location and intern but never title or age — so a row that entered before its filter
  existed kept its place and reached the paid scorer. `run_score`'s phase-0 sweep now
  re-applies the title filters (free, deterministic, outside `--score-limit`), merging a
  `prefilter: title refused` verdict into the gate's screen dict so the passing evidence
  a row already earned survives, and only after the location/intern gates so a row they
  killed keeps its own reason. **206 of the 5,941 rows** that survive the gates,
  measured 2026-07-31.
  **`max_age_days` is deliberately NOT re-applied, and the pre-merge review is why.** A
  title refusal is recoverable — widen the filter, `--rescreen-discarded`, the row comes
  back — while an age refusal is not, because the row only gets older. 474 of the 587
  age-refusals were *inside* the window when they were ingested; they aged out waiting in
  the queue, so discarding them is a queue-TTL policy that would terminally delete ~5,300
  rows over 30 days. That is an operator decision to take deliberately with a revert
  artifact, not something a pass does six times a day. Recorded in `docs/BACKLOG.md`
  along with a variant that WOULD be recoverable — judging age against the row's own
  `created_at` rather than `now` — queued there rather than declined; not shipped.
  Driven against a copy of the live DB: **`3646 free-gate discarded (unbudgeted)`**,
  where the same copy swept 3,440 before this change — the 3,440 deterministic kills
  plus the 206 title refusals.
  **The first measurement of this was wrong in a way worth recording:** it reported "438
  refused, only 3 on age". `_too_old` parses `now` and returns False on a ValueError
  ("unparseable -> keep"), so calling `prefilter_postings` without an explicit `now` —
  its own default — silently disables the age rule. Err-toward-keep is right in
  production and quietly wrong in a measurement. (SPEC §7.1/§9.)


- **`careers.qualcomm.com` is no longer lost on every pass.** It failed all six daily
  passes with `403 Client Error: Forbidden` deep in pagination, and the bounded-retry
  path only knew about 429 — so the search raised, the page loop unwound, and the
  salvage that exists for exactly this never ran. Probed cold on 2026-07-31, the failing
  offsets (`start=990`/`1060`/`1220`, which vary pass to pass) all return **200** from a
  fresh session, so it is not the offset and not a missing page: it is a WAF tripping on
  the pass's cumulative request volume — a throttle wearing a different status code. 403
  now takes the throttle path (bounded retry, then salvage the pages already walked). A
  403 on the FIRST page still raises: nothing to salvage, and a board that refuses from
  the start is a block, not a throttle. **The salvage now says so out loud** — it was
  silent, so a truncated board (990 of the 1,896 positions qualcomm reports) was
  indistinguishable from a complete one in the logs, which would have turned a loud
  failure every pass into a quiet one. (SPEC §7.1/§9.)
- **The scoring pass had stalled: free work was spending the paid budget.** The
  2026-07-30 recovery requeued 4,644 hydrated discards, `requeue_discarded` stamps
  `updated_at`, and the `new` queue orders on `COALESCE(updated_at,'') DESC` — so those
  rows sort ahead of fresh intake, whose `updated_at` is NULL. `--score-limit` bounded
  rows *touched*, not quota *spent*, so the daemon burned all 40 slots per pass
  re-killing location discards for free: **4 rows fit-scored at 16:00 EDT on 07-30, then
  0, then 0**, with ~16 days of that to go before it would have reached a posting
  discovered that day. Two changes, the first load-bearing: `run_score` opens with a
  **phase-0 sweep** (`_sweep_free_gates`) running `deterministic_screen` over the whole
  queue **outside `--score-limit`** — 0.26 ms/row to scan, ~0.5 ms/row including the
  committed write (~4.5s for 3,480 discards over 9,390 live rows), no model, no quota —
  and applies the budget only to what survives; and `screen_posting` runs the
  code-side gates **before** the model call, returning on a disqualification, so a doomed
  row no longer buys a ~1.5s GPU round trip (**37% of the live `new` queue dies on those
  gates**). Verdicts are unchanged — those gates were already terminal whatever the model
  said. What is given up is model detail on a row being discarded anyway, plus two
  consequences named in SPEC §7.1: a deterministically-killed row no longer carries
  `provider_error`, and a reason string no longer joins a model reason to a deterministic
  one. Driven end to end on a copy of the live DB: `3480 free-gate discarded
  (unbudgeted), then 2 row(s): ... 2 fit-scored`. `make eval-screen` reproduces its
  documented RED baseline exactly (ids 67/68/672/738, recall 31/37, 0 flips).
  `--score-limit` is **not** thereby a pure quota budget: an LLM screen-discard and a
  thin-JD row still consume a slot while spending nothing (~18% of screened rows over
  the 2026-07-29 live passes; 8.2% over the rows in DB history that would enter the
  screen phase — different denominators, both stated in SPEC §7.1).
  Closing that would make the per-pass model work unbounded, so it stands — on the live
  data the difference is ~1.3 days of catch-up rather than ~16. (SPEC §7.1/§9.)
- **`capture_usage` was never broken.** The 2026-07-30 defect — the quota snapshot
  silently not being written — root-caused on 07-31 to the documented `if _scorer_cell:`
  guard: the passes after 12:41 fit-scored nothing, so no scorer was built and the call
  correctly never ran. The fetch returns `True` from both an interactive shell and a
  replica of the daemon's environment, and `~/.codex/auth.json` has not been rewritten
  since 07-26, so the concurrent-`codex exec` suspicion is dead. No code change; the
  entry is closed in `docs/PROGRESS.md`.

### Added

- **The Telegram alert carries the fit summary.** The routing turns on the verdicts, so
  the scorecard's one-line `assessment.summary` is the part of the card with decision
  value — it now rides the message as a `Fit:` line, above the URL so Telegram still
  previews the link. It reads the **already-persisted, already-sanitised** summary out of
  `score_detail`; `notify.py` calls no model and gains no dependency. Whitespace is
  collapsed so a multi-line summary stays one line, and the text is truncated at 300
  chars: model prose is the one field in that message with no length contract, and
  `sendMessage` raises past 4096 — which would burn a notify retry on a real match.
  Absent, malformed or empty `score_detail` omits the line, same as the `Resume:` line
  it sits next to. (SPEC §7.1/§9.)

### Changed

- **`docs/PROGRESS.md` split into three files.** It had grown to ~28k tokens and every
  session reloads it, while most of it was reference material rather than state. What
  stays is the live delta a session needs now — in flight, the pick order, the quota gap,
  open defects. The catalogue moved to **`docs/BACKLOG.md`** (unverified/deferred +
  enhancements) and the evaluated-and-rejected records to **`docs/REJECTED.md`**, both
  loaded on demand. Text is moved verbatim; the conventions (block tag, effort, severity
  ordering) are unchanged and still stated once, in PROGRESS. `CLAUDE.md`, `AGENTS.md`,
  `README.md` and the `session-boot` skill point at the new files, and PROGRESS's "How to
  update" now routes a new gap: defects stay, everything else goes to BACKLOG.
- **Both eval harnesses now resolve their model the way production does.**
  `tools/score_eval.py` pinned `MODEL` to `run.DEFAULT_CODEX_SCORE_MODEL` and ignored
  `CODEX_SCORE_MODEL` / `ANTHROPIC_SCORE_MODEL` — the vars `run.py` itself reads — so a
  model A/B silently re-measured the production model under the challenger's name; it
  reads them now. `tools/screen_eval.py` ignored `OLLAMA_NUM_CTX`, which `run.main`
  threads into **both** the screener and `screen_posting` (whose JD truncation cap is
  `num_ctx*2`), so with that var set the eval ran a different context window than
  production; it now passes the same value to both. Latent, not active — the var is
  commented out in `apps/worker/.env`, so both sides ran 8192. Its report header also
  printed `"{backend} default"` instead of the model actually used, which is precisely
  what a reader diffs across A/B runs; it now names the real `DEFAULT_*_SCREEN_MODEL`.
  (SPEC §12.)
- **`docs/SCORING.md` records the `notified` status.** §2.4 listed `new` | `scored` |
  `discarded` | `failed`, omitting the status a *delivered* alert leaves behind — so a
  rebuild from that spec would write consumer queries that silently lose every row the
  system already alerted on. §6 now also states why the notify gate reads
  `pipeline_status = 'scored'` and not `IN ('scored','notified')`: that clause is the only
  thing that stops the gate re-alerting every match on every pass.

### Fixed

- **A failed quota capture said nothing, and the quota is the binding constraint.**
  `capture_usage` is best-effort by contract and swallows every exception, `run_once`
  ignored its return value, and the snapshot carried no timestamp — so a pass that failed
  to refresh `db/scorer_usage.json` was indistinguishable from one that refreshed it,
  short of checking the file's mtime. That is how a `--score-limit` decision came out ~17
  points optimistic against an 8-hour-stale reading. `run_once` now prints `[quota]
  WARNING: no <backend> usage snapshot written` on a `False` return, and the write stamps
  an offset-aware `as_of` into the snapshot itself, so a stale reading is legible to
  anything that opens the file. The web route keeps deriving `as_of` from the mtime (same
  instant, and pre-stamp snapshots must still render). **The root cause is still open** —
  the fetch fails inside a pass but succeeds standalone against the same path — but it now
  announces itself instead of waiting to be noticed. (SPEC §7.1/§9.)

- **The pass lock was keyed on the temp dir, so a daemon and a hand run could both score
  the same rows and pay twice.** `run.pass_lock` resolved `tempfile.gettempdir()`, which
  two processes on one host do not agree on: a systemd unit with `PrivateTmp=yes`, a cron
  job with a sanitized env, and an interactive shell that exports `TMPDIR` each get a
  different file, so each acquires its own lock and the paid fit scorer is charged twice
  for one set of postings — the exact failure the lock exists to prevent. It is now keyed
  on the `resolve()`d `--db` (`<db>.pass.lock`, beside the DB), which is the resource
  being protected: that database plus the one scorer account. `resolve()` is
  load-bearing — `apps/web/prisma/applications.db` is a symlink to `db/applications.db`,
  and a relative `--db`, an absolute one and the symlink must not be three locks. This
  also drops the false serialization in the other direction: two checkouts pointed at two
  DBs no longer block each other. `deploy/ats-worker.service.example` loses its
  `Environment=TMPDIR=/tmp` pin and its "do not set `PrivateTmp=yes`" warning, both of
  which only existed to work around the old keying. Found in passing and fixed with it:
  tests reaching `main()` without a `--db` resolved the operator's real database and left
  a lock file in the live `db/` directory, so the autouse fixture now redirects `DB_PATH`
  as well as the no-db fallback path.
- **The blind-response check from #44 discarded a good verdict, and broke
  `make eval-screen`.** The local qwen3.5:4b drops the `screen` wrapper on roughly **1 call
  in 100** and returns the requirement keys at the top level — a complete, correct verdict
  in a flat shape. `#44` read "no `screen` object" as no answer, so that response became a
  `provider_error`: in production the row was deferred a pass, and in the eval it aborted
  the whole run on the first occurrence (the gate stops on a provider error by design,
  since a run against a dead backend proves nothing). Caught by re-running the gate, which
  is the only thing that could have caught it — no unit test knew the shape existed.
  `verdict_block` now accepts both shapes and supplies **both** the blind check and
  `_screen_verdict`'s reader, so the two cannot drift apart about what "usable" means. A
  response is blind only when it is not a dict, or carries neither a `screen` object nor any
  requirement key; `{"nonsense": 1}`, `{"screen": "pass"}` and `{"screen": null}` all still
  are. The flat and nested shapes are pinned byte-identical.
- **`/api/health` reported healthy against a database SQLite had silently re-created
  empty.** PR #47 changed the probe from `SELECT 1` to a `sqlite_master` read on the
  reasoning that a constant expression is answered without a page read. **A drill measured
  that reasoning to be wrong** (2026-07-29, throwaway copy, four failure modes x three
  candidate probes — matrix in SPEC §6):

  | failure mode | `SELECT 1` | `sqlite_master` | `job_postings` |
  |---|---|---|---|
  | rename dir AFTER connect | 200 | 200 | 200 |
  | delete file AFTER connect | 200 | 200 | 200 |
  | rename dir BEFORE connect | 503 | 503 | 503 |
  | **delete file BEFORE connect** | **200** | **200** | **503** |

  `SELECT 1` and `sqlite_master` are behaviorally **identical** in every mode, so #47 was
  inert. The mode that discriminates is the last one: with the file absent SQLite silently
  **creates an empty database**, so both weaker probes report healthy forever against a
  tracker holding no data — precisely the silent failure the route exists to prevent.
  Naming a real application table yields `no such table: job_postings` → 503 → `autoheal`
  restarts the container. The probe is now `SELECT 1 FROM job_postings LIMIT 1`.
  **The AFTER-connect column is not fixable by a probe and is accepted:** once the
  connection is open, reads go through the existing fd, so nothing on the filesystem can
  invalidate them (the same reason the earlier `chmod 000` drill left the live probe at 200
  for five minutes). A restart re-opens.

- **A live screen backend that answered BLINDLY looked healthy and quietly discarded real
  jobs.** A backend returning valid JSON with no usable verdict — a non-dict, or a dict
  with no `screen` object — was not flagged `provider_error`. Degree and clearance both
  suppress themselves on absent data, so `NO_SPONSOR_PHRASES` became the **only** surviving
  check: a blunt substring scan of the whole description, disqualifying on a JD the model
  never condemned. Worse, `run_score` recorded a circuit-breaker **success** for each one,
  so the degraded mode could never trip the breaker and would walk the entire backlog.
  Realistic trigger is a wrong `--model` tag or a non-instruct model — `_post` only checks
  that a dict came back, and none of the hosted backends validate shape either.
  `screen_posting` now raises into the path that already handles a dead provider
  correctly, so the fix needed **no new policy and costs no quota**: the floor is already
  suppressed on `provider_error`, `run_score` already leaves such a row `new` instead of
  fit-scoring it, and the breaker already aborts the phase after 5 with zero successes.
  **Scoped narrowly on purpose.** `sponsorship_labels: null`, `[]`, a missing key and an
  empty `screen` dict are *answers* and still reach the floor, so a JD that says *"we do
  not sponsor work visas"* is still caught with no model data — the deliberate residual.
  All four tests pinning the floor hand back a well-formed `screen` dict, so a broader
  check would have contradicted them. SPEC §7.1 + §9 traceability.
- **`screen_eval --selftest` now catches a corpus row whose excerpt cannot support its own
  label.** The existing invariants checked that a label is *assertable*, never that the
  text handed to the model could support it. Four IMC rows (456/529/534/538) were golden
  `refuses` with excerpts cut at the 1600-char cap **before** the refusal sentence, so they
  carried no sponsorship vocabulary at all — guaranteed misses independent of any model or
  prompt, which means every recall figure `make eval-screen` printed was computed partly
  over rows whose stated premise was false. `unsupportable_bars` asserts that a row labeled
  as a **bar** carries that requirement's vocabulary in its excerpt+title; it found exactly
  those four and nothing else across the other 79 rows. Only the bar direction is asserted —
  for clearance and sponsorship, absence of the vocabulary *is* the evidence of no bar.
  The sponsorship set is deliberately wider than the production retrieval vocabulary
  (`sponsor` alone), because a bar phrased without that word is a pinned, accepted recall
  loss rather than a corpus defect. Clearance reuses `screen.CLEARANCE_TOKENS`, the regex
  that decides whether the production check may fire at all.

  The four excerpts were rebuilt locally around the refusal sentence, so the labels are now
  supportable. That repair is **data, not a commit** — `apps/worker/eval/` is gitignored.
  **The re-run confirms it paid off:** 3 of the 4 (456/534/538) now come back as hits on all
  3 draws, where before no model or prompt could reach them; 529 still misses. Recall
  **31/37 (84%)** against a comparable pre-repair 28/37 (76%). The false-disqualification
  gate was unaffected, as predicted — golden `refuses` rows are excluded from `false_disq`
  by construction.
- **The feed's detail-fetch failure reason now names WHICH failure it was.**
  `_detail_fetch` filed a raise/`None` and a posting that came back but failed
  `_valid_posting` under the same `detail_fetch_failed` string, so neither the
  `feed_unresolved` row nor the `[feed] <source>: detail-fetch collapse — 0/N resolved
  (scraper may be broken)` warning could say which had happened. The two diagnoses are
  opposite: a raise or `None` is usually a **dead req** (the feed surfaces an
  `externalPath` the board no longer serves — normal and harmless), while a body that came
  back and does not parse is a **broken scraper**. That matters because the warning is not
  incidental — workday's `existing_external_ids` prune never matches (the feed carries
  `externalPath`, the DB stores the GUID), so those ids are re-fetched and the line
  re-printed every pass, six times a day, which is exactly the signal that gets tuned out.
  `_detail_fetch` now returns `(external_id, reason)` pairs; an invalid posting is filed as
  `empty_description`, the **same** string the watchlist path already uses for the same
  condition, so one query over `feed_unresolved` covers both paths. The collapse warning
  names the split. Rows recorded before this carry the old conflated string.
- **`/api/health` could report 200 with the database file gone.** The probe ran
  `SELECT 1`, a constant expression SQLite answers from the query planner without touching
  a page — so it proved the Prisma client existed, not that the DB was reachable, which is
  the entire point of the route. It now reads `SELECT name FROM sqlite_master LIMIT 1`, forcing
  a real page read and, under WAL, the `-wal`/`-shm` sidecars. A row rather than a count
  because the SQLite connector returns counts as `BigInt`, which throws on
  `JSON.stringify` — nothing serializes this result today, and this way nothing can start
  to. Verified through Prisma against a throwaway copy of the live DB, not only against
  the mock. That is the failure the
  `autoheal` sidecar exists to repair: the recovery leg is proven (drill, 2026-07-22), and
  detection was the unproven half. The regression is invisible to the two existing tests,
  which mock `$queryRaw` and never inspect the SQL, so a third test pins that the probe
  reads a table rather than a constant. Detection against a real stale mount is still
  unobserved — the drill that would prove it (rename the directory holding a throwaway DB
  copy, so a fresh `open()` fails while the existing fd survives) is recorded in PROGRESS.

### Changed

- **The shipped `--score-limit` is `40`, down from `60`, because the weekly scorer quota
  cannot pay for `60`.** Measured over the window's first 7 live passes: **23% by 04:50 on
  2026-07-30** (~3.3%/pass), so `60` projected to **~138%/week** and the quota would have
  died around day 6 of 7. `40` projects to ~92% — under budget, but the remaining ~8% is
  about one hand run, not comfortable headroom. Intake over the same
  period was ~205 rows/pass (median ~85), so the cap binds and every pass saturates it:
  `40` parks ~20 more rows/pass than `60` did, and the backlog grows either way. The
  choice is *keeping up* with fresh intake rather than *catching up* on the backlog; the
  budget funds only one. Cadence is not a lever: fewer passes each ingest proportionally
  more, so paid calls per week do not move. **Quote `db/scorer_usage.json` only with its
  mtime** — it carries no `as_of` field, and a stale reading of it produced a first round
  of this arithmetic that was ~17 points optimistic.
- **A degree/clearance-only screen fail is now confirmed by the strong model instead of
  deleting the posting.** The selection rule is **measured false-disqualification rate**,
  not "a model produced the verdict" — `authorization` is also a 4B labelling retrieved
  prose. Degree measured **24%** (9 of 38 live discards) and clearance **83%** (20 of 24);
  authorization measured **0** false disqualifications on the gate and already carries the
  precision machinery the other two lack (retrieve-then-classify, the offers/preference
  vetoes, quote verification), so it is left alone — a second look is the wrong trade on
  the one check where a false positive is worst. Both rates are **pre-fix**: they are why
  the routing was decided, not a claim about what the shipped code does now. The clearance
  evidence floor (#24) already catches all 20 for free and the `degree_levels`/`min(rank)`
  rewrite cut degree's residual to 2-3 rows per eval run — a 4B ceiling four prompt
  attempts failed to close, which is what the routing insures against. Volume makes it
  cheap: degree/clearance-**only** discards were 30 of 3,262, so each buys one paid call.

  `score.demote_for_confirmation` **clears** the failing verdicts rather than flipping
  them to pass. That is what makes this a re-check and not an override:
  `merge_fallback_screen` fills only the checks the screen left absent, so clearing them
  is exactly how the fit scorer's own Stage 4 extraction gets to answer, with the same
  CODE applying the candidate's constraint. Flipping to `pass` would have materialized a
  verdict nothing produced — the 2026-07-23 blind-check-as-pass defect in a new place. The
  disqualification reason a confirmed bar lands with is therefore the strong model's, not
  the 4B string it replaced.

  Scoped deliberately narrow. A row failing **any** other check — `authorization`, the
  location gazetteer, the intern/co-op title regex — stays terminal and free. A
  disqualification carrying **no per-check entries**, or an entry that is not a
  well-formed verdict, is likewise not routed: an unreadable shape is not evidence the
  verdict is wrong, and routing it would mean paying for every discard whose shape cannot
  be classified.

  **This also fixed a latent defect in `merge_fallback_screen` that the routing newly
  exposed.** That function only runs when the screen left a GAP, and until now nothing
  ever cleared one — so nobody had noticed that `_screen_verdict` re-rules every check the
  *candidate* configured, not just the gap keys. With no entry and no snippets,
  `authorization` falls through to the blunt `NO_SPONSOR_PHRASES` substring floor — the
  exact path that produced both long-standing IMC false positives — and the resulting
  `disqualified`/reason were merged unfiltered. A demoted row could therefore be discarded
  on `authorization` while its own `score_detail` recorded `authorization: {"pass": true}`,
  throwing away the paid call that had just kept it. The verdict is now rebuilt from the
  filled gap checks only.

  Built as an **in-pass routing decision plus a `needs_confirmation` marker in
  `score_detail`**, not a new `pipeline_status`. PROGRESS proposed a state; screen and fit
  run in the same pass, so no row would ever be stored in it, and a real status would mean
  new `constants.ts` values and UI buckets for something never observed. The marker
  survives whichever way the confirmation goes, so the routed population stays selectable.
  The pass summary reports `… sent for confirmation`, which **overlaps** the other counts
  rather than adding to them (a demoted row lands in `fit-scored`, or in `failed`/
  `unreached` when the fit phase errors or breaks) and is excluded from the `done`
  arithmetic for that reason.

  Known residual: a degree/clearance-only fail on a JD below the low-context threshold is
  kept **without** confirmation, since the thin-JD path spends no fit call. That row is
  deliberately not counted as sent for confirmation, though it keeps the marker — which
  names a confirmation it still needs. A thin JD cannot support a degree-bar reading
  either way, and those rows are held back from notify and shown for human review.
  (SPEC §7.1, §9.)

### Added

- **`--score-max-id N` — the selector the discard recovery needed.** `--score-limit`
  bounds the *spend*; it cannot bound the *selection*. Since PR #29 the `new` queue is
  read `COALESCE(updated_at,'') DESC, id DESC`, so a cap can only ever name rows from the
  newest end — and a `--rescreen-discarded` recovery target sits at the oldest.
  `requeue_discarded` stamps one `updated_at` across all 3,232 discards at once, so they
  tie and break by `id DESC` while the ~46 wrongly-discarded rows are among the *lowest*
  ids in that tied set: `--score-limit 736` would have scored the 736 newest requeued
  discards and reached **zero** targets, and reaching the oldest needed the whole 3,232 —
  the cost the bound existed to avoid. `--score-max-id 1417` names them directly (the
  degree/clearance/authorization discards occupy ids 7-1417; the pre-existing paid backlog
  starts at 1419, so the bound structurally cannot reach it).

  Applied **before** `--score-limit`, so the two compose as "these rows, and at most this
  many of them"; the reverse order would hand the cap to the newest rows and then filter
  every one of them away. Like `--rescreen-discarded`, it **requires `--once`**: `once()`
  closes over the parsed args, so a bound left on the daemon would hold for every future
  firing — the first pass drains what is under it and every pass after screens nothing
  while higher-id intake piles up behind the bound, a daemon that logs healthy passes and
  scores nothing. A **negative** value is a parser error rather than "no bound": `run_score`
  tests `max_id > 0`, so a sign typo would otherwise clear the guard and then silently
  disable the filter on a pass that had just requeued 3,232 rows. Rejected alternative:
  inverting the queue for this one operator flag, which adds a second ordering to reason
  about for the same result. (SPEC §7.1, §9.)

### Fixed

- **Both privacy guards matched `.env` exactly, so every `.env.<suffix>` variant was
  unguarded.** `.gitignore` carried a literal `.env` and `tools/check_privacy.mjs` a
  `/(^|\/)\.env(\.local)?$/` rule, so a file like `.env.bak`, `.env.old` or
  `.env.production` was **both unignored and invisible to `make check-privacy`** — it
  showed as `??` in `git status` and one `git add -A` would have committed it to a public
  repo. Found via a real `.env.bak-tsserve` in the repo root (a pre-Tailscale-serve backup
  holding only `WEB_BIND`, so nothing leaked; the pattern was the defect, not that file).
  `.gitignore` now matches `.env*` with a `!.env.example` re-include — no leading slash,
  so it covers the root compose env and `apps/worker/.env` alike — and the RULES entry
  reads `/(^|\/)\.env($|\.)/`, which is "`.env` followed by end-or-a-dot" and so still
  passes `.environment`-style names and `setEnv.ts`. `--self-test` pins both directions
  (`.env.bak-tsserve` and `apps/worker/.env.production` denied,
  `apps/web/src/environment.ts` and `apps/worker/.env.example` allowed), so the boundary
  cannot silently widen back. (SPEC §11.)

- **The location gate leaked foreign on-site roles nine different ways; it is now
  evidence-tiered and gated in CI.** A survey of every distinct `location` string in the
  live DB (9,633 rows / 1,611 strings) found **317 rows kept that were clearly non-US** —
  3.3% of rows, 5.5% of everything the gate kept — against a **clean discard side (0 false
  discards)**. The failure was entirely one-directional over-keeping, in nine classes:
  informal country names pycountry cannot resolve (`UK`, `England`, `Scotland`, `LDN`,
  `UAE` — 116 rows; the alias table existed but was consulted only for the *allowed* list,
  never for a token, which also meant `locations: ["UK","USA"]` silently discarded every UK
  role); the remote hint firing **before** any country resolved, so `Remote - India` kept
  (85 rows); `Ontario` resolving to Ontario, **California**, which rescued
  `Toronto, Ontario, CAN` despite two of three tokens saying Canada (53 rows); vague region
  tokens (82 rows); nothing resolving at all (62 rows); ASCII-vs-diacritic city misses —
  the gazetteer stores `Montréal`/`São Paulo`/`Zürich` while boards write ASCII, and 6,449
  of its 30,699 city keys carry non-ASCII (32 rows); unknown foreign subdivisions
  (`Haryana`, `Telangana`, `NSW` — 25 rows); multi-country strings (13 rows); and strings
  with no separator at all (`Remote Canada`, `India-Pune`), which never tokenized.
  Plus a wrong-*reason* bug: `APAC` is a town in Uganda, so `APAC - India - Pune` discarded
  as "on-site in **Uganda**" — right verdict, wrong country in the audit trail.

  The gate now classifies every token into an evidence tier and reads the verdict off the
  strongest evidence present (SPEC §7.1). Three orderings are load-bearing: the remote hint
  runs **after** a named country decides; the literal `remote` allow-entry is excluded from
  the direct allowed-list match (it is a work arrangement, not a place — the other half of
  that bug); and **any** allowed evidence keeps, never `all`, which is what preserves the
  zero-false-discard invariant for `New York City, London, Singapore`. Region acronyms are
  a stoplist rather than a population floor, because none exists: `Apac` UG is 67,700
  against `Zug` CH at 30,542. Regions that *contain* the US (`Americas`, `AMER`) count as
  weak US evidence rather than noise.

  Three further passes run before a token is given up on, added once measurement showed
  that **197 of the 296 unresolved rows were gazetteer gaps rather than judgement** — a
  model tier would have been paying per posting for a lookup table. geonamescache's
  `alternatenames` (141k keys the primary index discarded) resolve `NYC`, `Bangalore`,
  `Gurgaon`, `Frankfurt`, with a million-person floor on 3-4 character aliases so facility
  codes don't collide (`MOD` had made an Indian row read as US-eligible). A token that
  resolved to nothing is retried split on `- . /`, catching the site-code formats
  (`FR-Paris`, `PL-Warsaw-Lixa C`); splitting on those up front would shred
  `Winston-Salem`, so it only runs on a failure, and a 2-letter prefix that is both a US
  state code and a country code reads as the country only when another part corroborates
  it (`DE-Germany` discards; `USA.VA.Reston` stays Virginia). Trailing facility nouns are
  stripped last (`San Francisco HQ`).

  **Measured, not asserted:** 416 rows moved keep -> discard, **0 moved the other way, and
  0 US-eligible strings were discarded.** The residual leak is pinned at 6 strings / 14
  rows rather than driven to zero — every one is a foreign country named alongside an
  ambiguous token that also reads as a US city, and tightening that is exactly what would
  start deleting real jobs. Unresolved rows are down to **1.0%**. Exempting *unambiguous*
  city names from the corroboration rule was measured (+26 rows) and **rejected**: it
  discarded a US university building as Tanzania (via "Coast") and an Israeli site as
  Italy.

  The invariant is gated **in CI** by `tests/fixtures/location_corpus.jsonl` — committed,
  unlike the two `eval/` golden sets, because a board location string is a place name
  rather than JD text, and because a gate only the operator can run is not a gate. Its
  labels come from an **independent oracle** (a deliberately dumb substring scan sharing no
  code with the resolver), since a corpus labeled by the code under test only proves the
  code agrees with itself. `pycountry` and `geonamescache` are pinned to `==` in the same
  commit: the corpus asserts exact counts, so the gazetteer data is part of the contract.

### Changed

- **Quota telemetry is a provider endpoint now, not a scraped session rollout — and the
  bar follows `SCORE_BACKEND`.** The codex figures used to live only in the session
  rollout (`codex exec --json` never carries `rate_limits`), so capturing them forced
  `--ephemeral` off on every scoring call, left the full résumé+profile+JD prompt on
  disk until a guarded reap, and identified "our" rollout by mtime.
  `GET https://chatgpt.com/backend-api/codex/usage` returns the same accounting
  directly, so scoring calls are unconditionally `--ephemeral` again and write nothing.
  Claude Code has an equivalent — `GET https://api.anthropic.com/api/oauth/usage` with
  `anthropic-beta: oauth-2025-04-20` — so `run_once` makes one free GET per pass against
  whichever backend actually scored, and the snapshot records which one. The bar
  (`CodexUsageBar` -> `ScorerUsageBar`, `/api/codex-usage` -> `/api/scorer-usage`,
  `codex_usage.json` -> `scorer_usage.json`, `CODEX_USAGE_FILE` -> `SCORER_USAGE_FILE`)
  relabels itself from that field instead of reading "No codex usage recorded yet"
  forever on `SCORE_BACKEND=claude`. This closes the "codex usage bar is backend-locked"
  gap. Two things worth knowing: chatgpt.com is behind Cloudflare, which 403s urllib's
  default `Python-urllib/3.x` (an honest client `User-Agent` is sent — a browser-looking
  one is also refused); and `/api/oauth/usage` reports the Claude Code **subscription**
  budget, which is NOT what `make_claude_scorer` bills (`ANTHROPIC_API_KEY`, metered, no
  percent-of-quota endpoint) — the bar states that outright rather than implying one
  number covers both.
- **The Discovered-Jobs keep half now requires `seniority=match`, and Below bar means
  near miss.** Below bar was the catch-all — every live row outside `matchedIds()`, so a
  `too_junior` posting the scorer had already judged unwinnable sat in the same tab as a
  genuine near miss (`prompts/score.txt` treats seniority as *disqualifying, not
  partial*, so those rows were never actionable). The split is now: `seniority=match AND
  domain=match` → **Matched**, `seniority=match AND domain=adjacent` → **Below bar**
  (`belowBarIds()`, the same raw-query shape as `matchedIds()`), and **everything else
  scored** → **Discarded**, which now holds two populations — hard-constraint screen
  failures *and* fit-verdict rejects. Only the first carries a keyed
  `disqualification_reason`, so the discarded why-cell falls back to the shared
  `VerdictShortfall` line (the pills Below bar already used) instead of printing the
  literal "disqualified" for a row that was never disqualified. The notify gate is
  untouched — it was already `match/match`.
  **Live-DB consequence, recorded here because it is not reproducible from the code:**
  the 509 `scored`/`notified` rows scored before 2026-07-29 were deleted when this
  landed — the scoring prompt had since been tuned, so those verdicts were not
  comparable to current output, and under the new rules most would have re-bucketed
  anyway. Backup at `db/applications.db.backup-20260729-pre-scorereset`. The 148 rows
  from that day's live passes were kept; the 3,857 `discarded` rows were not touched
  (screen output, not fit output). Rows still live on their boards re-enter as `new`.

### Fixed

- **`max_age_days` now also judges the date a feed row actually stores.** `run_feed`
  gated on Simplify's `date_posted` before the resolve and never re-checked the
  `posted_at` the board itself returned, so an evergreen requisition the feed re-lists as
  fresh was ingested and stored with its true first-published date — a `greenhouse` row
  dated 2025-06-16 landed on 2026-07-29 under `max_age_days: 30`, and 127 of that pass's
  2,568 rows were older than the window, all of them feed-path. `run_feed` re-runs
  `prefilter_postings` over the fetched postings before the upsert, which is what
  `run_fetch` has always done with its stub gate. Age only on the second pass: the title
  filters already passed on the feed's title, and the detail-fetch-collapse warning must
  keep reading the unfiltered result (an all-stale board is not a broken scraper). The
  pre-resolve gate is unchanged — it is where the fetch cost is saved. Closes half of the
  "feed's age gate judges a PROXY date" item in `PROGRESS.md`; the `date_updated` half
  stays open.
- **The location gate leaked foreign on-site roles whose city the gazetteer misses.**
  `resolve_location`'s corroboration rule (added so `London, ON` wouldn't be discarded as
  United Kingdom on its city token alone) demanded two agreeing tokens before any
  discard. But geonamescache indexes *Bengaluru*, not Bangalore, and carries no Penang at
  all — so `Bangalore, India` and `Penang, Malaysia - Grande` resolved on their **country**
  token alone, failed corroboration, and were kept as US-eligible. Eight such rows reached
  the live queue on 2026-07-29 (Cisco Bangalore, Micron Penang, Intel India/Malaysia,
  Target Bangalore), each costing a paid fit call for a job in a country the candidate
  cannot work in. A token that *names* a country is now self-corroborating; the city-only
  case is unchanged, so `London, ON` still keeps and `Hyderabad, TS` still costs one
  wasted fit call rather than a lost live match.

- **The Low-context why-cell reported a 4,560-char JD as "Thin JD".** The bucket has two
  entry rules (`lowContextIds`) — a body under `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`, or
  the fit scorer's own `insufficient_context` flag on a full-length but boilerplate JD —
  and the cell hardcoded the first. It now names which rule caught the row.

- **The Fit-assessment verdict rows didn't line up.** `JobDetailModal` laid Seniority and
  Domain out as independent flex rows, so a wide pill (`too_junior`) pushed its note out
  of line with the row below. A 3-column grid sizes the label and pill columns to the
  widest cell instead.

- **An unwritable pass lock wedged the daemon silently.** `pass_lock` opened the file
  `O_RDWR`, so one accidental `sudo python -m ats_worker.run` left a root-owned lock —
  never unlinked, by design — and every later pass got `EACCES`. That used to kill the
  daemon loudly at startup via the eager first pass; once that pass was dropped for
  wall-clock scheduling, the `RuntimeError` moved *inside* the APScheduler job, where the
  executor catches and logs it. The unit stayed `active (running)`, reported a healthy
  schedule, and never completed a pass — the worse failure, not the better one. It now
  falls back to `O_RDONLY`, since `flock` needs no write access: the guard stays
  exclusive and only the pid record is lost, which the holding pass says out loud rather
  than degrading quietly. A lock that cannot be opened in *either* mode — a 0600 file
  owned by someone else — still fails loud; so do the non-permission failures (missing
  TMPDIR, a symlink refused by `O_NOFOLLOW`, a read-only filesystem).
  **The pid a contender reports is now liveness-checked.** Since the file is never
  unlinked its pid outlives the process that wrote it, and a read-only holder cannot
  overwrite it at all — so the naive read named a *corpse* as the running pass and sent
  the operator hunting a process that does not exist. That is the same "is this recorded
  pid the same process" guessing game the flock exists to avoid. `_recorded_holder`
  reports the pid only when a process by that number is alive, and "unknown" otherwise.
- **`--score-limit` scored the oldest rows, so on a schedule it would never reach a job
  discovered today.** Every `new` row has `score` NULL — nothing has scored it yet, that
  being the point — so `get_by_status`'s `ORDER BY score DESC, id ASC` degenerated to
  plain oldest-id-first for that queue. A bounded pass therefore always worked the back
  of the backlog: against the 3,959 rows pending when the 4-hour cadence went in, a
  posting found today sat behind roughly two weeks of older ones, which defeats running
  on a schedule at all. `run_score` now reads the queue `newest_first=True` (the only
  caller that does; the `scored`/`discarded` queues keep the score-first ordering the UI
  and the operator expect). A backlog now drains from its tail only when a pass has
  headroom under the cap, which keeps clearing it an explicit operator action instead of
  something the schedule does silently and expensively. Two existing tests carried an
  implicit oldest-first assumption and now seed or select in the order they meant.
  (SPEC §7.1 scoring.)
  **It is `updated_at DESC, id DESC`, not plain `id DESC`, and the difference is a
  retry that would otherwise never run.** `run_retry` requeues a `failed` row to `new`
  keeping its ORIGINAL id, and both SPEC §7.1/§9 and its own contract promise the row is
  rescored *that same pass*; under newest-id-first an old failed row sorts behind the
  entire backlog and a capped pass never reaches it, so the retry budget would burn down
  without a single retry being attempted. Ordering by recency-of-touch satisfies both:
  `upsert_postings` leaves `updated_at` NULL, so fresh intake ties with the backlog and
  the id tiebreak orders it, while a requeued row carries a timestamp and sorts ahead.
  Caught by the §7 pre-merge review, not by the suite — the plain-`id DESC` version was
  fully green.
  **`--rescreen-discarded` does not compose with `--score-limit`**, which the flag's own
  comment previously claimed it did. Requeued discards do sort to the front, but
  `requeue_discarded` is unfiltered, so the cap lands on an arbitrary prefix of every
  requeued row and cannot be aimed at the ones a given rescreen was for. Documented in
  SPEC §9; PROGRESS queue item 2 carries the concrete case.
- **A capped scoring pass reported `0 left 'new'` while thousands of rows waited.** The
  count was `len(rows) - done` over the `--score-limit` *slice*, so it could only ever
  describe the slice. Harmless when every pass was uncapped and hand-run; on a daemon
  shipping `--score-limit` by default it prints six times a day, and a queue that is not
  draining is precisely what that line must not hide. The summary now separates
  `N unreached` (rows in this pass's slice a breaker or abort did not reach — the old
  meaning) from `N left 'new'` (the whole queue, counted from the DB).
- **The discovery feed ignored every one of the operator's coarse filters.** `run_fetch`
  has always applied `title_filter`, `title_exclude` and `max_age_days` via
  `fetch.prefilter_postings`; `run_feed` never called it, so none of the three touched a
  feed-discovered posting. Dormant while the feed was off, live the moment Simplify was
  enabled. Measured against the real feed the day before the fix: 17,659 listings ->
  2,013 past the feed's own `active`/category/sponsorship gate -> **1,193 of those (59%)
  refused by at least one operator filter** (1,049 stale, 302 title), leaving 820. Each
  refused listing was buying a URL resolve, a board detail fetch and a screen call.
  **Be exact about the recurrence:** for a listing that ingests those are *one-time*
  costs — `existing_external_ids` prunes it on the next pass and `run_score` only reads
  `new` — so the ~1,193-listing saving is large but paid once, and what recurs every
  pass is the resolve for whatever never lands.
  **The stale half is the surprise** — the feed marks listings `active: true`
  for months (sampled one posted 2025-12-01), so `max_age_days` does more work here than
  the title rules do. Anyone re-deriving these counts should re-measure: they are one
  snapshot of a feed that changes daily. The feed now runs the **same** `prefilter_postings` call, before the
  resolve — the only point that saves all three — as one shared ingest rule so the two
  paths cannot drift apart again. A listing the config refuses is dropped, not recorded
  in `feed_unresolved`: nothing about it is unresolved.
  **Two silent failure modes in the translation, which is why it is pinned by tests.**
  The feed publishes `title` where the filter reads `job_title`, and `date_posted` as a
  **Unix epoch int** (`1764549850`) where `_too_old` parses an ISO date. Wiring the raw
  listing straight through fails quietly in *both* directions and in opposite ways: an
  unmapped title matches no keep-list, so the feed would ingest **zero** rows; an
  unmapped epoch raises inside `date.fromisoformat` and falls through to
  "unparseable -> keep", so `max_age_days` would never fire — and stale listings are
  1,049 of the 1,193, the larger half of the win. `_feed_posting_view` does the mapping;
  an absent or unreadable date still keeps the listing, matching the board path.
  (SPEC §7.1 feed ingestion.)
- **`ats-autoheal`'s healthcheck could not fail, so it reported healthy unconditionally.**
  The image's check is `pgrep -f autoheal`, and `Cmd=["autoheal"]` puts that string in the
  process's own argv — the check matches itself, and therefore carries **zero** signal
  about whether the sidecar can do its job. It is now a socket **ping**
  (`curl -fsS --max-time 5 --unix-socket /var/run/docker.sock http://localhost/_ping`),
  which asks whether the Docker API is still reachable. Measured in a socket-less container
  held up artificially, with a faster interval than shipped: socket-ping reached
  `unhealthy` while `pgrep` reported healthy throughout. At the shipped 30s interval a real
  socket-less sidecar usually exits before three probes can fail, so `make health` sees
  `starting` — which it also fails on. The ping makes the signal real; it is not what makes
  the timing work.
  All four timing fields are set because Docker merges healthcheck fields **individually**
  with the image's — omitting `interval` would silently inherit this image's 5s. The
  socket path is hardcoded rather than `$$DOCKER_SOCK` so the check and the volume cannot
  disagree. Known false negative: `/_ping` is answered by dockerd's HTTP router before any
  containerd work, so a daemon wedged on container operations still pings OK.

- **`make health`** — a new target, invoked by `up`, polling both containers for `healthy`
  and treating a missing healthcheck as failure, waiting out web's 40s `start_period` and
  dumping `docker logs --tail 20` when it gives up. A fixed short sleep reads `starting`
  and calls it success — the same defect PR #19 shipped as `status=running` at t=0.
  It also compares a RestartCount delta, because a crash-looping container reads `healthy`
  with `.State.Status` == `running` for most of each cycle and health alone passes it.
  Residual, stated rather than papered over: that catches a container flapping before it
  first reads healthy, not one that comes up healthy and crash-loops afterwards.

- **An entrypoint watchdog was built for this and then REMOVED before merging**, because
  two measurements killed it. It would have exited when the Docker socket went away, so
  `restart: unless-stopped` could restart the sidecar. (1) That state does not occur: the
  image's `/docker-entrypoint` runs under `set -e -o pipefail`, so a failed API call exits
  the script — with a socket killed under a live **stock** sidecar it went `Exited (7)`
  and restarted itself 8 times unaided. (2) The wrapper introduced a worse failure than it
  removed: as PID 1 it survives its child, so killing the autoheal loop left the container
  `Up (healthy)` with `RestartCount 0` and no autoheal running, indefinitely — the exact
  deception this change exists to remove. It also swallowed SIGTERM. Its own drill passed;
  the drill was too narrow, because it only ever asked what happens when the *socket*
  dies. Reasoning in PROGRESS.

- **SPEC §6 documented a cure that does nothing, and a mechanism that does not hold on
  this platform.** It said "the cure is to recreate the container" without noting that
  `make up` will **not** recreate a running container whose config hash is unchanged — so
  the documented cure was a no-op. It also implied a restart re-resolves the bind mount;
  measured on Docker Desktop/WSL2, it does **not**: the source is pinned through a
  create-time hashed path, so swapping the host directory and restarting still shows the
  old contents while a freshly created container shows the new. `docker compose up -d
  --force-recreate web` is the cure that works in both cases. SPEC now separates a stale
  *view* of the same inode (plausibly cured by a restart, still unproven) from a
  *replaced* inode (measurably not).

### Added

- **The worker can be supervised — `deploy/ats-worker.service.example`, a systemd user
  unit.** The web stack has had `restart: unless-stopped` plus the autoheal sidecar since
  the beginning; the worker, being native (SPEC §6), had nothing, so a crash or an OOM
  kill just ended the job feed until a human noticed. `Restart=always` with `RestartSec=30s`
  and a `StartLimitBurst` that parks a genuine crash-loop in `failed` — visible to
  `systemctl --user status`, where an endlessly restarting unit is not.
  **Journald supplies retention and rotation, so no log-file code and no rotation code
  ships** — that is the entire reason for this shape rather than a log file the worker
  manages itself. `journalctl --user -u ats-worker -f` follows it, and the daemon's
  `basicConfig` is what makes the worker's own records timestamped beside APScheduler's.
  `PYTHONUNBUFFERED=1` is load-bearing rather than tidy: the pipeline's `print()` calls
  pass no `flush=`, and Python block-buffers stdout when it is not a tty, so under
  journald's pipe a hung pass and a quiet pass would look the same.
  Two traps are called out in the file because both fail silently: `StartLimitIntervalSec`
  belongs in `[Unit]` and is *ignored* in `[Service]` (`systemd-analyze verify` catches
  it), and `PrivateTmp=yes` must not be set, because `pass_lock` keys on
  `tempfile.gettempdir()` and a private `/tmp` would let the daemon and a hand run both
  acquire and both spend paid quota.
  `sudo loginctl enable-linger $USER` is documented as the one operator step: `Linger=no`
  is the default and tears the user manager down at logout.

- **`make doctor` reports whether the worker daemon is active** (`systemctl --user
  is-active ats-worker`). Informational like the other provider rows — hand-run `--once`
  is a supported workflow — but a stopped daemon and one merely waiting for its next
  wall-clock slot are otherwise indistinguishable, since both print nothing. A host with
  no systemd reports the row soft rather than crashing the preflight.

### Changed

- **The daemon fires on wall-clock slots, and no longer runs a pass at launch.**
  `run.main` did `add_job(once, "interval", hours=cfg.schedule_hours)` and called
  `once()` before `start()`, so passes landed at *launch time + N*: start the worker at
  09:47 and they ran at 09:47/13:47/17:47, never on the hour, and every restart re-phased
  the whole day *and* cost an immediate full pass — at 6 passes/day a daemon bounced
  three times ran nine. Slots are now absolute (`CronTrigger(hour=cron_hours(h),
  minute=0)`, where `cron_hours(4)` is `"0,4,8,12,16,20"`), so restarts cannot move them.
  **`--run-now` restores the eager pass on demand**; it is rejected alongside `--once`
  (two different programs) and does *not* unlock `--rescreen-discarded`, because `once()`
  closes over that flag and it would then fire on every later scheduled pass too.

  **No new config key** — the slots are derived from the existing `schedule_hours`, which
  keeps `_reject_unknown_keys` (it reads `dataclasses.fields(Config)`) untouched. What is
  new is a **bound**: `schedule_hours` must divide 24. A non-divisor leaves a `24 % h` gap
  across midnight that is always *tighter* than the configured cadence, and anything above
  24 collapses to a single `hour=0` — so `schedule_hours: 48` ("every other day", legal
  before this) would have silently become **daily**, a 2x change in paid fit-scorer spend
  from a file nobody edited. `config.py` rejects both at load, keeping a separate message
  for `0`/negative.

  **One scheduler setting is a non-default; the other two are restated defaults.**
  `misfire_grace_time=min(3600, schedule_hours*1800)` replaces APScheduler's default of
  **one second**, which silently drops any slot the host was busy through — the deleted
  eager `once()` had been masking that, since a restarted daemon always ran promptly
  whether or not it had missed anything. `max_instances=1` and `coalesce=True` are
  *already* the defaults (`BaseScheduler._configure`); they are written out because each
  would be expensive if it silently changed, not because they change anything here.
  **What the grace window does NOT buy, since it is easy to read the opposite:**
  coalescing keeps only the LAST missed run time, and the executor drops even that one if
  it is older than the window. A host resuming more than an hour past a slot therefore
  runs **zero** catch-up passes and simply waits for the next slot — a real behavior
  change from the old eager pass, which always ran on restart.

  **The daemon now installs a logging handler** (`basicConfig`, INFO, timestamped) — in
  the daemon branch only, so importing the module still configures nothing. Without it
  APScheduler's misfire warnings, max-instances skips and job tracebacks fell to
  `logging.lastResort`: message and level only, no timestamp and no logger name. This is
  the handler the pass-skip warning added with the lockfile was waiting for. It does
  **not** unify the streams — `lastResort` and a default `basicConfig` are both
  StreamHandlers on stderr, and the pipeline still `print()`s to stdout; what it buys is
  the timestamp and provenance journald needs to interleave them. Startup also prints the resolved slots and timezone, because with no eager pass a
  fresh daemon is otherwise indistinguishable from a hung one for up to `schedule_hours`:
  `[schedule] passes at 0,4,8,12,16,20:00 America/New_York (every 4h, wall-clock)`. The
  timezone comes from `tzlocal`, so a UTC host would defeat the whole change; `TZ=` is the
  no-code override.

  **One consequence, accepted rather than fixed:** wall-clock slots systematically
  synchronize an operator's habits with the daemon's. A routine 08:00 hand run now kills
  the 08:00 scheduled pass every day, because `pass_lock` skips rather than queues. Jitter
  would reintroduce the drift the change exists to remove, so the mitigation is visibility
  (the skip logs at `WARNING`) and SPEC §9 states the collision out loud.

- **Sponsorship screening inverted: CODE retrieves, the MODEL classifies, CODE decides.**
  The two halves were on the wrong sides. The model did RETRIEVAL — read 16K chars, find
  the sentence, copy it verbatim — and code did CLASSIFICATION, three regex vetoes
  deciding whether that sentence was a refusal. Retrieval on a keyword is trivially
  deterministic and regexes are bad at stance, which is what three rounds of
  whack-a-mole, PR #22's five false positives, and the screen eval's 8-of-16 recall (on
  rows whose refusal sentence was *inside the text handed to the model*) were all
  measuring.

  Now `sponsorship_snippets` pulls every sentence naming `sponsor` plus one neighbour
  each side, the prompt numbers them, the model returns one label per snippet
  (`refuses` / `offers` / `neither`), and code decides: any `offers` keeps, else any
  `refuses` discards, else keep. **Hallucination became structurally impossible rather
  than checked for** — the model labels text the code handed it and never supplies text
  — which retires `_quote_in` instead of strengthening it, and `_OFF_TOPIC_QUOTE` with
  it: an EEO line is simply `neither` to a classifier, so no pattern has to anticipate
  every innocent sentence in English.

  **Result on `make eval-screen`: sponsorship false disqualifications 2 → 0 across all
  21 corpus rows**, including the two IMC residuals (465/490) that had been open since
  2026-07-25. Whole-corpus false disqualifications are **11 → 2-3** counting the degree
  fix above; the stable pair is one JD shape (ids 67/68) and a third soft-degree-bar row
  joins it in some runs. The count is not reproducible run-to-run even at
  `temperature: 0, seed: 0` — two back-to-back runs gave 3 then 2 on identical code — so
  the number to hold this stack to is the part that *is* stable: **clearance 0 and
  sponsorship 0**, with every remaining failure inside the documented 4B degree ceiling
  (SPEC §7.1).

  **Two ways the floor was reached that should not have been — found by the pre-merge
  review and fixed before merge.** Not an exhaustive list: a live-but-BLIND backend still
  reaches it, which is an open fork recorded in PROGRESS rather than a defect, because
  four tests pin the floor as an independent deterministic signal on purpose. Both of
  these discarded a real job, the direction this design exists to close.
  (1) On a SCREEN **provider error** the "authorization always records a verdict"
  block ran the closed-list floor over the whole description, so an Ollama outage
  terminally discarded exactly the *"eligible to work without sponsorship, we encourage
  you to apply"* shape — a regression against `main`, which kept it. The block is now
  skipped on `provider_error`, leaving the key absent; `run_score` leaves such a row
  `new`, so no second model vote can occur and the next pass screens it properly.
  (2) `sponsorship_labels: []` is schema-legal (`["array", "null"]`) and a plausible 4B
  answer, but `[]` is falsy, so a **bad count expressed as an empty array** was read as
  silence and fell to the floor. "The model answered" is now `bool(labels) or
  isinstance(raw, list)`, with the floor still reached when nothing was retrieved.

  **Also fixed here:** `CLEARANCE_TOKENS` gained the `\b` in `\bts[.\s/-]?sci`. With the
  separator optional the pattern matched across a word gap — *"supports scientific"*,
  *"its scientific"*, *"products scientists"* all grounded a clearance claim, the exact
  `sci` trap the token list's own comment says it avoids. Narrowing only ever turns a
  discard into a keep. And `tools/screen_eval.py` now passes the resolved model to
  `make_screener` instead of only printing it: the model is a keyword argument there, not
  an `env` key, so every run used the built-in default while the report header claimed
  whatever `OLLAMA_MODEL`/`SCREEN_MODEL` said — which voids the tool's premise that
  eval-model equals production-model.

  **Three things the measurement corrected about the design as recorded.** (1) Adjacent
  snippets must NOT be merged — an early version merged them, and one IMC paragraph that
  refuses sponsorship for three named nationalities *and* offers it to Ukrainian
  applicants could then only come back `refuses`. One snippet per `sponsor` sentence,
  overlapping windows allowed to repeat a neighbour. (2) `_PREFERENCE_ONLY` had to be
  **restored** as a keep-direction veto: the design expected a classifier to make all
  three regex vetoes unnecessary, and the 4B labelled *"prioritizing applicants who …
  do not require sponsorship of a visa"* as `refuses` on 3 live TikTok rows, all three
  draws. (3) A **miscounted** answer must not fall through to the `NO_SPONSOR_PHRASES`
  floor — that path is exactly where both IMC false positives came from, the 4B returning
  one label for three snippets and the closed list then matching `without sponsorship`
  inside *"or are eligible to work without sponsorship, we encourage you to apply"*.
  Silence still reaches the floor; a bad count does not.

  The floor survives only for silence (`SCREEN_BACKEND=none`, provider error, the fit
  scorer's Stage 4 shape), and `authorization` still records a verdict even when nothing
  was retrieved and no clause was asked — `merge_fallback_screen` fills only absent keys,
  and a second model vote on a disqualification is what SPEC §7.1 forbids.

  **The retrieval vocabulary narrowed to `sponsor` alone**, and the cost is stated rather
  than hidden: 7 of the 13 corpus must-flag sentences (citizenship and work-authorization
  bars that never say "sponsor") are no longer retrieved and become misses — one paid fit
  call each, reaching the human. A test pins that count in both directions so the trade
  cannot drift silently. Every false positive ever recorded on this path came from a word
  that is *not* "sponsor".

### Added

- **`make eval-screen` — the accuracy gate `screen.txt` never had.** `score.txt` cannot
  change without two consecutive `tools/score_eval.py` PASS; the screen's degree,
  clearance and sponsorship clauses shipped on inspection alone, and on 2026-07-27 that
  cost four days of a clearance check running 83% wrong with nothing to surface it (no row
  is marked `failed`, so no failure ratio moves). `tools/screen_eval.py` reuses the
  production wiring (`run.make_screener` -> `score.screen_posting`), draws each corpus row
  K=3x on the free local Ollama backend, and judges the requirement that row was drawn for
  against a hand-labeled JD **fact** — "does this JD require a clearance?", never "is this
  posting disqualified?", because a verdict-labeled set rots the moment `config.yaml`
  changes and a fact-labeled one does not.

  **The gate is one-directional: zero false disqualification, judged on ANY of the three
  draws rather than the majority** — a check that discards a good posting one time in
  three is not a passing check. Recall and flip-rate are reported and never gated: a miss
  costs one paid fit call and reaches the human, while a false discard is reviewed by
  nobody. Rows whose label is genuinely ambiguous carry `gate: false` and are reported
  only — a gate is worthless if it can be argued with. `--selftest` is a free hermetic
  check of the gate logic *and* of the corpus's own invariants; it runs no model.

  The corpus (`apps/worker/eval/screen_golden.jsonl`, 83 rows) is built from **live fires
  rather than synthesized JDs** — the 24 clearance discards, the 38 degree discards, and
  the 21 operator-signed rows of the 2026-07-25 sponsorship worksheet — and stores
  excerpts, which is also the input shape the sponsorship rewrite will feed the model. It
  lives under the already-gitignored, privacy-guarded `apps/worker/eval/`, so like
  `eval/golden.jsonl` the gate is reproducible only with the operator's local files.

  **Its first run FAILED, 11 false disqualifications out of 81 gate-eligible rows** —
  clearance 0 (the evidence floor above, verified against live data), sponsorship 2 (the
  known `NO_SPONSOR_PHRASES` residual), **degree 9 — a previously unknown defect**: the 4B
  reads *"PhD, or Master's degree in…"*, *"PhD (or exceptional MSc)"* and *"PhD … strongly
  preferred"* as a hard PhD bar. All three draws agreed on all 9, so it is a stable
  misreading rather than noise. Microsoft's laddered *"Doctorate … OR Master's … OR
  Bachelor's"* form is read correctly 5 for 5, which places the fix in the prompt clause
  and not in code. Sponsorship recall is the other finding: **8 of 16 bars missed on rows
  whose refusal sentence is inside the excerpt the model was handed** — model-side
  retrieval failing at exactly the job the queued retrieve-then-classify rewrite takes
  away from it.

- **One pipeline pass at a time per host.** APScheduler's `max_instances=1` already stops
  the scheduler overlapping itself, but nothing stopped a hand-run pass landing inside a
  scheduled one — a race that gets likelier at the chosen cadence of 4 passes/day, and one
  whose costs are asymmetric: a duplicated notify is one extra Telegram message, a
  duplicated **score spends real paid quota**. Every pass now runs inside `run.pass_lock`,
  a non-blocking exclusive `fcntl.flock` on `$TMPDIR/ats-worker-pass.lock`. It is an
  `flock` rather than a PID file because that makes staleness self-solving — the kernel
  drops the lock when the holder dies, so a host killed mid-pass leaves a file the next
  pass takes immediately, with no operator deleting anything and no guessing whether a
  recorded pid was reused. The lock is held per *pass*, not for the process lifetime, so
  a running daemon does not lock the operator out of a hand run between firings; the file
  is never unlinked (unlinking races a waiter onto an inode no longer at that path). A
  refused pass is total and non-destructive — it neither queues nor partially runs:
  `--once` exits non-zero naming the holder's pid before any fetch or scorer call, while a
  scheduled firing logs one `logging.WARNING`, skips that slot and stays scheduled, so a daemon
  restarted during a hand run does not die on its eager startup pass. Drives of all three
  paths (clean pass, refusal, SIGKILLed holder) were run through the real CLI.
  The scheduled skip goes to `logging.WARNING` rather than `print`, because APScheduler
  emits its own misfire and max-instances warnings there and they are the same signal —
  "a pass did not run" — so one handler can carry both. The daemon installs that
  handler (see the wall-clock entry above); a bare import still installs none, and the
  `[pass] holding ...` line remains a `print` on stdout.

### Fixed

- **The degree check read "PhD **or** Master's" as a hard PhD bar: 9 of 38 live discards
  were wrong.** `screen.txt` asked the 4B for `required_degree`, "the MINIMUM degree the
  role requires" — a *judgment*, and the one thing this repo's design says not to ask a
  small local model for. It returned the highest level it saw. Found 2026-07-28 by the new
  `make eval-screen` gate on its first run, all three draws agreeing on all 9, so a stable
  misreading rather than noise: *"PhD, or Master's degree in Computer Science"*, *"Ms or
  PhD"*, *"PhD (or exceptional MSc)"*, *"advanced degree, preferably a Ph.D."*, *"PhD or
  equivalent industry experience"*, *"PhD or Master's … strongly preferred"*, *"DESIRABLE
  CANDIDATES: Ph.D. candidates"*.

  **The shape changed, not just the wording.** The model now returns `degree_levels` —
  every level the posting names as acceptable — plus `degree_required`, a bool separating
  a hard condition from a preference; CODE takes `min(rank)`. Listing what a posting says
  is extraction; picking the smallest number out of the list is arithmetic. **9 false
  disqualifications → 3, with recall 27/37 → 28/37** — the expensive direction improved
  without buying it from the cheap one. Two rounds of pure prompt rewording first reached
  4 and then 5 and stopped converging, which is what said the wording was not the problem.

  **Residual: 3 rows, and it is a 4B ceiling rather than a wording gap.** *"DESIRABLE
  CANDIDATES: Ph.D. candidates"* (ids 67/68 — one JD shape, twice) and *"PhD or equivalent
  industry experience"* (id 738) still come back `degree_required: true`. Probing the raw
  output showed the same model *inventing* a `master's` level on genuine sole-PhD roles, so
  it is unreliable in both directions and a fifth prompt rewrite is not the fix; routing a
  degree fail to the strong model is (tracked in PROGRESS).

  The fit scorer's Stage 4 block deliberately still emits the old single `required_degree`
  and `_check_degree` reads both shapes — that block runs on a strong model where the
  minimum is a judgment it can make, and editing `score.txt` would trigger its own gate of
  two quota-spending `score_eval` runs for no measured benefit.

- **The clearance check fired on the word "security": 20 of 24 live discards were
  wrong.** `_check_clearance` acted on a bare `requires_clearance: true` boolean from a
  4B model with no evidence floor at all — the failure class D1 exists to kill, closed
  for `authorization` by quote grounding and left standing here. Measured 2026-07-27
  against `db/applications.db`: of 24 clearance discards, **20 contained "security" (the
  engineering domain — "Senior Security Researcher", "Azure security") and not one
  clearance token**; the 4 true positives were all Microsoft `CTJ - Poly` roles carrying
  an explicit *"Other Requirements: Security Clearance Requirements:"* block. Every one
  of the 24 post-dates 2026-07-23, so this was live damage, not stale — the most recent
  pass was 3 for 3 wrong. CODE now requires a `CLEARANCE_TOKENS` match (`clearance` ·
  `top secret` · `secret` · `ts/sci` · `polygraph`) in the JD **description or the job
  title** before honouring the flag. On that data the two populations separate perfectly.
  The token list stays the measured one — bare `sci` (matches "science"/"scientist") and
  bare `poly` are deliberately absent, since on a disqualification path a collision costs
  a real job. The guard is **keep-direction only** (it can only turn a discard into a
  keep), so it needed no eval to ship, and `merge_fallback_screen`'s Stage 4 extraction
  obeys it too rather than becoming a back door. `degree` is left unguarded on purpose:
  38 of 38 live degree discards are grounded (36 in the description, 2 in the title), so
  the symmetric guard would close a hole with no observed instance.

  **Why it went unnoticed for four days:** clearance is 0.7% of discards, so it read as
  the least consequential check in the block; nothing marks such a row `failed`; and
  `screen.txt` has no eval gate. Volume ranked it last, error rate ranks it first — the
  gate is the next queue item.

- **A successful scoring pass printed nothing, so it was indistinguishable from a
  no-op.** `run_score` only ever spoke up on trouble — a fetch drop, a tripped breaker —
  so a pass that screened, scored and persisted rows exited silently with status 0. On
  2026-07-26 that cost real debugging time: a working `--score-only --score-limit 10`
  run against a 3,965-row backlog looked like a failure, and the DB row counts were the
  only way to tell it had worked. It now always ends with one line:
  `[score] 20 row(s): 12 screen-discarded, 0 thin-JD (no fit call), 8 fit-scored,
  0 failed, 0 left 'new'`. **`fit-scored` is the number that spent quota**, and
  **`left 'new'`** is what a tripped breaker or a `KeyboardInterrupt` never reached — so
  a partial pass reads as partial rather than as a smaller pass that went fine, which is
  the same silence the breakers themselves were added to end. Counters are a plain dict
  incremented at each terminal outcome; two tests cover the counts and the
  breaker-remainder arithmetic, both mutation-checked.

- **Every codex fit call was returning HTTP 400: the scoring backend was dead, not
  degraded.** OpenAI structured output requires every object to list every key of
  `properties` in `required`; the `screen` block added to `_score_schema` by `66dfb65`
  and the whole of `SCREEN_SCHEMA` had `properties` and no `required`, so the API
  rejected the request before the model ran (`invalid_json_schema ... Missing
  'required_degree'`). `score_eval` — the gate blocking a merge — could not execute a
  single row. Only ollama was unaffected, because `format="json"` constrains output to
  *some* object rather than to a schema, which is why nothing caught it. Both schemas are
  now strict-valid, with "omitted" spelled as an explicit null (`screen` is
  object-or-null, every leaf nullable) so a scorer with nothing to say still cannot fail
  the card.

  **The quieter half:** fixing the schema alone would have silently retired the Stage 4
  fallback. `_screen_verdict` gated the degree and clearance checks on the model
  returning a non-empty entry *dict*, and under a strict schema the model must emit every
  key — so a blind check arrives as `{"required_degree": null}`, a non-empty dict saying
  nothing, and would have been recorded as a genuine pass with `merge_fallback_screen`
  never seeing the gap. Both gates now test the **value** via `_said_something`, which
  mirrors the emptiness rule each checker already applies: `null`, `""` and the
  `"unknown"` family are all "no data", because `screen.txt` instructs the model to
  answer `"unknown"` for an unstated fact and `_degree_rank` already maps it to rank 0.
  A `False` boolean is a fact, not a gap.

  `test_schema_is_strict_mode_valid` walks `_batch_schema` (the payload codex actually
  receives — `_batch_schema` was hoisted to module level so the guard can reach it),
  `_score_schema` and `SCREEN_SCHEMA`, failing on any object whose properties are not all
  required.

- **`--rescreen-discarded` could destroy the rows it exists to rescue.** Stub-gate
  discards are stored deliberately un-hydrated (`description=''`) because they never
  reach the scorer — `run_fetch` exempts them from the bodyless drop for exactly that
  reason. `requeue_discarded` was unfiltered, so it flipped them to `new`; the thin-JD
  gate then parked them `scored` at score 0, and because `upsert_postings` is
  `ON CONFLICT DO NOTHING` no later pass could ever back-fill the JD. The row ended up
  neither scored nor recoverable, on a high-volume source (phenom). It now requeues only
  rows with a non-empty description; an un-hydrated stub stays `discarded`, where the
  stub gate can still revisit it.

- **The screen circuit breaker aborted silently and ignored raised failures.** Two gaps
  in the breaker shipped 2026-07-24. It printed nothing on trip, unlike its fit-phase
  twin — and since aborted rows keep `attempts=0` and never reach the Failed tab, a
  misconfigured provider produced a pass that did nothing and said nothing, the same
  silence the breaker was built to end. It also called `record_failure()` only on the
  `provider_error` verdict, not on the `except` path, so a screen failure that *raises*
  was invisible to the breaker while still marking rows `failed`. Scope that honestly:
  `screen_posting` wraps the backend call in its own `except`, so today's wiring cannot
  propagate a provider raise — this half is defensive symmetry with the fit phase (which
  pairs `record_failure()` with every `mark_failed`), not a live outage path. Both fixed,
  and both now covered by tests that fail when the breaker is stubbed
  out — the two pre-existing tests do not, since a `provider_error` row is skipped with or
  without a breaker.

- **`_scorer_meta` stamped the Anthropic model onto any unrecognized backend.**
  `make_scorer` raises on an unknown backend; its provenance twin fell through to
  `anthropic_score_model`, so a stray `SCORE_BACKEND=openai` in a `.env` (argparse does
  not validate an env-supplied `default` against `choices`) wrote a stamp naming a model
  that never ran. A silently wrong provenance field is worse than none. It now raises.

- **A real-but-irrelevant quote can no longer disqualify a posting for sponsorship.**
  `_check_authorization` verified that the model's `no_sponsorship_quote` actually
  appears in the JD, which makes hallucination unable to disqualify anything — but
  presence proves a sentence is *real*, not that it is *about* sponsorship. The
  2026-07-25 labeled-set run (3,553 already-scored rows, 21 disagreements hand-labeled)
  measured that residual: **8 of 28 fires were wrong**, and wrong in the expensive
  direction — a false positive here silently discards a good posting, the error "err
  toward keep" exists to prevent. Five of the eight were a single Optiver boilerplate
  line, *"We do not require any assistance from third-parties including agencies in the
  recruitment of this role"* — about recruiters, not visas.

  A verified quote must now also pass `_quote_on_topic`: three vetoes, then a vocabulary,
  every one resolving toward keeping the posting. The vetoes are an **off-topic** sentence
  that merely carries an authorization word — the recorded D1 pair, *"company-sponsored
  sports teams"* and *"we do not discriminate on citizenship"*, the latter sitting in
  essentially every US posting; the wrong **polarity**, since quote grounding fixes
  invented *text* but not inverted *meaning* and *"Visa sponsorship is available for this
  position."* is the most valuable line in a JD for a candidate who needs it; and a soft
  **preference** (*"prioritizing applicants who…"*), which is not a bar because the
  candidate can still apply.

  **The vocabulary stayed the measured one.** A round of speculative additions for misses
  nobody had observed — `opt `, `cpt `, `e-3`, `us person` — was reverted after review:
  each collided with text that appears in a large share of postings (*"We offer generous
  personal time off"*, *"we adopt a test-driven approach"*, *"you can opt out of on-call"*,
  *"CPT and ICD-10 coding"*), and on a disqualification path a collision costs a real job
  rather than an API call. Both directions are now pinned by a corpus,
  `tests/fixtures/sponsorship_quotes.json` — 32 must-keep and 13 must-flag sentences,
  every one from a real posting, a labeled row, or a review counter-example, none invented
  to fit the implementation. A new term needs a must-flag sentence that requires it and
  must-keep still passing.

  Measured on the labeled set, **for the whole function rather than one branch of it** —
  `_check_authorization` is `(grounded AND on topic) OR NO_SPONSOR_PHRASES`, and the
  ungated floor adds fires that a quote-branch-only number silently omits:
  the retired phrase gate alone was 81.8% precision / 45.0% recall; the shipped function
  is **90.9% / 100%**. The gate removes 8 false positives and **zero** true positives.
  The 2 residual false positives come from the floor, not the gate (IMC, where
  `without sponsorship` appears inside an *invitation* to people who don't need it) and
  are recorded as **open**. `tools/sponsor_diff.py` applies the same gate and now also
  writes a `-suppressed.json` of rows the gate rejected — without it the tool counts a
  suppressed row as agreement and goes blind to the one failure the gate introduces.

- **A dead screen provider no longer hands the whole backlog to the paid scorer.**
  `screen_posting` catches any provider exception and errs toward KEEP — correct for one
  flaky call, wrong for an outage. When Ollama was simply down (a WSL2 suspend does it)
  nothing raised and nothing was marked `failed`, so no failure count moved: every
  remaining row silently skipped screening and was fit-scored **blind on the paid
  backend**, turning the ~18% normally discarded for free into paid calls and switching
  the hard-requirement gate off entirely. This was the **fifth** instance of the policy
  error PRINCIPLES' four-way table names — a systemic condition handled as a per-item
  verdict — and the one pipeline block the 2026-07-23/24 sweep never reached. The verdict
  now carries `provider_error`, and `run_score` (a) leaves such a row **`new`** — no
  paid call, no `attempts` spent, screened properly next pass — unless a *deterministic*
  gate (location/intern, which cost nothing and ran fine) disqualified it, in which case
  that verdict stands; and (b) runs a second `_BackendBreaker` over the screen phase with
  the same signature as the fit one, aborting it and cancelling the queued remainder. One
  success disarms it, so a flaky-but-alive provider never trips. `SCREEN_BACKEND=none` is
  **not** a provider error — no provider, deterministic gates alone, scored as documented.
  Found while auditing the unattended long-run runbook, which had no signal that would
  have caught it.

- **`schedule_hours: 0` (or negative) is now a startup error instead of a hot loop.**
  `config.py` coerced `schedule_hours` with no lower bound and `run.main` fed it
  straight to APScheduler's `interval` trigger, whose `IntervalTrigger` falls back to a
  **1-second** period when every component is zero — so a `0`/negative typo silently
  meant a daemon hammering the whole watchlist once a second. `load_config` now raises
  `ConfigError` for anything `< 1`. (Config validation — fail loud.)
- **A wrong Telegram token no longer permanently destroys every matched posting.**
  `run_notify` treated a send failure as a per-posting fault, so a bad-token `401`
  drove all five matched rows to `attempts+1` each pass and parked them `failed` on
  the third — gone from both the alert channel and the web Matched tab, unrecoverable
  short of hand-editing the DB. A **systemic** send fault is now classified
  (`_systemic_send_error`: `401`/`403` or an invalid-token body) and **circuit-breaks
  the pass**: every matched row is left `scored`, **zero** notify budget spent, one
  operator line printed. A `_BackendBreaker` (5 consecutive failures, zero deliveries)
  backstops the unclassified-systemic case (e.g. the host unreachable). Only a
  genuinely per-posting fault still spends the retry budget. (PRINCIPLES "the four
  kinds of uncertainty" — circuit break.)
- **A dead fit backend no longer fails the entire score queue.** `run_score` isolated
  a bad *posting* but had no notion of a bad *backend*: one outage (e.g. `codex exec`
  not logged in) marked the whole `new` backlog `failed` at `attempts+1`, three passes
  from a terminally-dead queue. The same `_BackendBreaker` aborts scoring after 5
  failures with zero successes, leaving the untouched remainder `new` (recoverable),
  with one operator line; one success disarms it. The `batch_size==1` singles fallback
  is now guarded (`len(chunk) > 1`) so it no longer re-issues the byte-identical call
  that just failed, doubling the cost of every failure.
- **A score run is now interruptible and keeps finished work when killed.** The fit
  phase drained its whole queue on `ThreadPoolExecutor` exit (`shutdown(wait=True)`),
  so Ctrl-C waited out ~thousands of uninterruptible paid `codex exec` calls, and
  results finished-but-unwritten behind a straggler were discarded on abort. It now
  consumes via `as_completed` and persists each result on the calling thread as it
  completes (row-associated by a `future → chunk` map), and on `KeyboardInterrupt`
  tears the pool down with `cancel_futures=True` — queued calls are cancelled, not
  drained.
- **Score hiccups no longer silently eat the notify retry budget.** `attempts` was one
  counter shared across both stages, so a row that burned 2 transient score failures
  (already recovered) got only 1 of its 3 notify tries before parking `failed`. Notify
  failures now land on a separate `notify_attempts` column; `run_retry` guards both
  budgets (`attempts < 3 AND notify_attempts < 3`), keeping a notify-exhausted row
  terminal while giving delivery its own full budget. Additive schema column
  (`schema.prisma` + fixture); existing rows backfill to 0.

- **`resolve_location` no longer false-discards a city/region pair whose region
  abbreviation doesn't resolve.** With `locations: ["Canada", "USA", "remote"]`,
  `'London, ON'` returned `(False, 'on-site in United Kingdom')`: `_token_country`
  resolves each token independently, `'ON'` resolves to nothing (only **US**
  subdivisions are in the gazetteer — no other country's are), and `'London'` alone
  decided the country as GB by highest-population namesake. A genuinely Canadian
  posting was dropped *and* the recorded reason named the wrong country, so it could
  not even be spotted in the Discarded bucket. Discard now requires a **corroborated**
  foreign reading — every token resolved, or at least two did; a lone resolved token
  beside an unresolved one keeps. `'Tokyo, Japan'` and `'London, England, United
  Kingdom'` still discard. The cost is misses only (`'Hyderabad, TS'` now keeps = one
  wasted fit call), which is the trade SPEC already makes explicit for `run_expire`.
  Note the fix originally recorded for this defect — "require **all** tokens to
  resolve" — was implemented, measured, and **rejected**: it broke four shipped
  assertions, because `England`, `North Holland` and `Montréal` (accented in the
  gazetteer) don't resolve either, so it disabled the gate for `City, Region, Country`,
  the most common foreign board format.

- **A throttled board is no longer lost whole — bounded 429 retry in the phenom
  paginator.** The 2026-07-22 full pass lost exactly one board this way:
  `phenom/careers.qualcomm.com` rate-limited at deep pagination (`start=930`), and the
  exception unwound the page loop, discarding every posting already collected. A 429 on
  the search GET now retries the same offset up to 3 times (2s -> 4s -> 8s, honoring a
  delta-seconds `Retry-After` clamped to 30s). Still throttled at `start > 0` returns an
  empty page, which the paginator reads as the end of the board — **the pages already
  walked are kept**, no change to `_paged.py`. At `start == 0` it still raises, because
  a silent `[]` would report a throttled board as an empty one. A non-429 status never
  spends the retry budget. Detail calls are untouched (already isolated per posting).
  Deliberately not built: a per-source rate-limit policy across all 13 sources — 12 of
  them have never rate-limited.

- **An off-vocabulary `work_authorization` no longer silently disables the whole
  authorization screen check.** `_needs_sponsorship` substring-matches `"sponsor"` and
  reads its absence as "does not need sponsorship" — so `F-1 OPT`, `STEM OPT` and
  `H-1B`, the most natural things a user writes, each turned the check off with no
  error and no warning. `config.py` now validates the value against the four documented
  values (`citizen` | `permanent resident` | `authorized-no-sponsorship` | `needs visa
  sponsorship`, case-insensitive) and raises `ConfigError` otherwise, matching the
  module's existing fail-loud-at-startup contract (`VALID_SOURCES`, `VALID_FEEDS`).
  Blank stays legal — it means "don't screen on this". The guided `onboard-me` path was
  already safe; this covers hand-edited `config.yaml`, which is a documented path.
  Deliberately not built: the 6-field structured `authorization:` block proposed
  alongside it — the only distinction that changes an outcome is one boolean.

- **A screen check the model returned no data for is no longer recorded as a pass.**
  `_screen_verdict`'s `gate()` wrote `screen[key]` whenever the candidate had
  *configured* a check, and each `_check_*` errs toward pass on absent data — so a
  `degree`/`clearance` check that ran but got nothing back was byte-identical to one
  the model genuinely cleared. `degree` and `clearance` now materialize their key only
  when the extraction actually carried an entry; `authorization` still writes its key
  unconditionally, because `NO_SPONSOR_PHRASES` over the JD gives it a real verdict
  with no model data at all. Two effects: the persisted `screen` block (and the web
  detail modal's chips) stops claiming verdicts nothing produced, and the fit scorer's
  fallback extraction can now see a per-check gap instead of only a whole-backend
  absence. No schema change; sparse `screen` dicts were already the shape for
  unconfigured checks.

- **Telegram is now optional — a bot token is no longer required to run the worker.**
  `run_once` read `env["TELEGRAM_BOT_TOKEN"]` / `env["TELEGRAM_CHAT_ID"]` as bare dict
  access, so a user without a bot hit a hard `KeyError` at the notify stage after a full
  fetch/score — locking out anyone happy to review matches in the web **Discovered Jobs**
  tab (whose Matched bucket already surfaces `scored` rows, not just `notified`). When
  either credential is absent the worker now skips `run_notify` with a one-line notice and
  leaves matched rows `scored`; supply both to re-enable push alerts. (SETUP.md,
  SPEC §7.)
- **`make eval-score` could not run at all.** It was the one worker target that reached
  into `apps/worker/.venv/bin/python` instead of the host `$(PY)` every other worker
  target uses (`test-worker`, `test-integration`, `doctor`). That venv lacks `bs4`, so
  `score_eval.py`'s `from ats_worker import run` pulled in the fetch chain and died on
  `ModuleNotFoundError: No module named 'bs4'` before the eval began — meaning the
  documented command for the repo's only scorer-prompt gate, the gate currently blocking
  a merge, failed on the operator's own machine. Now `cd $(WORKER) && $(PY)
  tools/score_eval.py`, consistent with every sibling target; the script already inserts
  `apps/worker` on `sys.path` itself, so nothing else was needed. Verified with the free
  hermetic `--selftest`.

- **Bodyless postings no longer reach the paid fit scorer — or the DB.** `_valid_posting`
  (non-empty id + title + description) ran on the feed's detail path only; the watchlist
  board path upserted whatever an adapter returned, and `run_score` never checked the
  description. Because `upsert_postings` is `ON CONFLICT DO NOTHING`, a title-only row
  was **permanent**: a later cycle that *could* read the JD would not back-fill it, and
  the row was fit-scored blind on the paid backend meanwhile. `run_fetch` now applies the
  same guard, logging `dropped N posting(s) with no description` per board, so a board
  whose list endpoint carries no JD yields nothing that cycle instead of poisoning the
  DB. Stub-gated `discarded` rows are exempt — they are deliberately un-hydrated and
  never reach the scorer. This is the mechanism behind the two Citadel `browser` rows
  (0/10 descriptions) and behind the nine boards held off the watchlist for empty JDs;
  both are now non-destructive by construction. Each dropped row is recorded in
  `feed_unresolved` (`feed="watchlist"`, `reason="empty_description"`) so a
  silently-broken scraper surfaces on the Unresolved board instead of only in a log
  line — the same visibility the feed path already gives detail-fetch failures.

- **Thin JDs (< 200 chars) no longer spend a paid fit-score call.** The low-context
  hold-back (`LENGTH(TRIM(description)) < LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`) was applied
  only at *display/notify* time, so a short JD was still fit-scored on the paid Codex
  backend and *then* filtered into the Low-context bucket where its verdict is distrusted
  — paying to score something already pre-judged unscoreable. `run_score` now applies the
  threshold **before** the fit call: a screen survivor under the length bar is persisted
  `scored` + `insufficient_context` directly (score 0, screen verdicts kept), skipping the
  scorer. It lands in the same Low-context bucket a human can eyeball, minus the wasted
  message. The `200` threshold is now a single worker constant
  (`db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`, still hand-synced with web `constants.ts`)
  shared by the pre-fit gate and `get_notifiable`.

### Added

- **A root `AGENTS.md` — the convention agents other than Claude Code look for.** The
  repo had none, so every non-Claude agent arrived with no project instructions at all.
  It is a **real file**, not a symlink to `CLAUDE.md`: git stores a symlink as a blob
  containing the target path, so `raw.githubusercontent.com/.../AGENTS.md` would serve
  nine bytes reading `CLAUDE.md` to any agent fetching it over HTTP, and a Windows
  checkout without `core.symlinks=true` materializes it as a plain text file with the
  same nine bytes — an agent finds a file, reads it, and stops looking, which is worse
  than finding nothing. It carries the same guidance as `CLAUDE.md` minus the
  Claude-Code-specific conduct (effort levels, subagent policy) that would mislead a
  different agent. The two are hand-synced; there is little in either to drift.
  `.agents/skills` is a symlink to `.claude/skills` so agents that look there find the
  `SKILL.md` files — **but whether any of them follow a symlinked directory is untested**,
  and most directory walkers do not by default, so that half is recorded as unverified
  rather than shipped.

- **Two of SPEC's source-coverage matrix columns are now tested, not hand-kept.**
  `test_spec_matrix_matches_adapters` parses the matrix out of `SPEC.md` and asserts the
  **Platform** column's source names against `fetch.ADAPTERS` and the **Watchlist**
  column against `config.VALID_SOURCES`, so adding a 14th adapter — or promoting a
  feed-only source to the watchlist — reds the suite until the doc says so. Adapter,
  Host(s) and Feed router are deliberately **not** guarded and SPEC now says so:
  `resolve_url` is a URL-pattern parser rather than a registry (the same reason the
  `AdapterSpec` proposal was rejected), and the adapter cell's prose has nothing to
  compare against. The source name is the Platform column's first word
  (`Oracle Cloud HCM` -> `oracle`); a row whose Adapter cell begins `via ` is skipped as
  routed through another module. Cell text is normalized for `code`, **bold** and
  `[label](url)` first, and rows are split on unescaped pipes only — a guard that reds CI
  because someone bolded a word is worse than no guard, and a naive split would have read
  the Watchlist value out of the Feed router column, silently wrong rather than loud.
  Alongside it, `test_watchlist_sources_can_list` asserts every `VALID_SOURCES` member's
  adapter actually exposes `fetch` — the existing guard only checked the name was in
  `ADAPTERS`, which a feed-only `fetch_one`-only module would have passed.

- **`--no-notify`: score without alerting.** A bulk or unattended pass scores hundreds
  of rows and, until now, fired a Telegram alert per match — a burst nobody is there to
  read. The flag skips the notify stage and says so; nothing is consumed, because matched
  rows stay `scored` and a later pass without the flag alerts them normally (and they are
  in the web Discovered tab the whole time).

- **Every fit-scored row now records which scorer produced it.** `score_detail`
  persisted the verdict but nothing about its author, so a row scored on
  `codex`/`gpt-5.6-sol` was indistinguishable from one scored on
  `claude`/`claude-sonnet-5`, or from one scored before a `score.txt` edit — a
  `--score-backend` A/B could not be read back off the data, and any rubric change made
  re-scoring all-or-nothing over the whole table. `run.py` (the only layer that knows
  the scorer's identity) now hands `run_score` a three-field `scorer_meta` —
  `backend`, `model`, `scorer_version` — which `_score_detail` merges into the existing
  JSON, so **no schema migration**. Stamped only where a fit call actually ran (both
  `_persist_scored` outcomes, including the fallback-disqualified `discarded` that
  already paid for its call), never on a screen-discarded or low-context row that would
  otherwise claim a backend it never reached. `model` branches on `backend` beside
  `make_scorer` so the stamp can't name a model the scorer wasn't built with, and
  `scorer_version` is a hand-bumped date string in `prompts.py`. The eight-field hash
  provenance with automatic re-score triggering stays rejected — a cache-invalidation
  system for inputs that change a handful of times a year.

- **`--rescreen-discarded`: the one way back from a terminal discard.** `run_retry`
  requeues only `failed`, so `discarded` was permanent — editing a candidate hard
  requirement (`locations`, `highest_degree`, `work_authorization`,
  `exclude_internships`), or fixing the screen itself, left every prior discard frozen
  under the old rule and made a **false** discard unrecoverable. The flag runs one bulk
  `db.requeue_discarded` UPDATE immediately before `run_retry`, returning every discard
  to `new` so the same pass re-screens it. Unbudgeted and unfiltered by design (a
  discard spends no `attempts`, so there is no counter to guard). It is **one-shot** —
  `main` rejects it without `--once`, because on the interval schedule it would
  resurrect the same discards every pass and re-charge the paid fit scorer for each
  survivor indefinitely. Screening is free on the default ollama backend; pair with
  `--score-limit` to bound the fit calls that follow.

- **`browser` recipes can build `job_url` from a `{field}` template.** `custom` recipes
  already interpolate `{dotted.field}` into their `url`; `browser` recipes could not, so
  a board whose cards carry no `href` — the id sits in a `data-*` attribute and routing
  is JS-side — could only produce a broken or empty `job_url`. A `url` spec containing
  `{` is now interpolated over the recipe's *own* other `fields`, reusing the existing
  `interpolate`/`_PLACEHOLDER` machinery rather than a second interpolator. Detection
  matches the `custom` path's rule, and CSS selectors never contain braces, so no
  shipped recipe changes meaning. Fields the canonical posting dict ignores are
  extracted too, so a recipe can carry a url-only helper field — e.g.
  `external_id: {attr: "data-id"}` + `url: "/s/details?jobReq={external_id}"`, resolved
  against the listing `base_url`. The interpolated URL
  enters the pipeline at the same point as a scraped `href` and passes the same
  `is_safe_public_url` guard in `browser.fetch` — no new fetch path (regression-tested
  with a template resolving to a link-local address). Unblocks the Balyasny / Jacobs
  Levy-shape boards that were blocked on this primitive alone; no adapter changed.

- **`test_no_source_specific_logic` — an architecture guard welding the fetch layer's
  main invariant in place.** Which adapter runs is decided by data (the watchlist row's
  `source`, looked up in `fetch.ADAPTERS`), never by the orchestration layer naming a
  board — so `pipeline.py` and `db.py` carry no board names, and adding a 12th adapter
  must not require editing either. The test derives its source list from `ADAPTERS`
  itself (so a new adapter is covered with no edit here), strips comments and docstrings
  before scanning (prose naming a board while explaining why the generic path exists is
  not coupling), and fails on any board name appearing in executable code. `db.py` is
  entirely clean; `pipeline.py`'s one occurrence — `"embedded_greenhouse"`, a
  `classify_reason` fail-bucket label, not adapter dispatch — is an explicit allowlist
  entry with its reasoning inline, plus a note to rename rather than allowlist a second
  one. A stale-allowlist assertion keeps the exceptions honest.

- **`SCREEN_BACKEND` — five more ways to run the hard-requirements screen, so a user
  with no local GPU (or no Ollama at all) can still run the pipeline.** The screen was
  hard-wired to one Ollama HTTP call; it is now injected as a single seam,
  `extract(prompt, schema) -> dict`, and `run.make_screener(backend, ...)` builds that
  callable from `SCREEN_BACKEND`/`--screen-backend` across **six** values in **three**
  adapter shapes: HTTP + JSON schema (`ollama` — **default**, free, local; `claude-api`
  — metered, Anthropic SDK structured outputs, default `claude-haiku-4-5`; `openai-api`
  — metered, plain `requests` against `chat/completions`, default `gpt-5.6-luna`), CLI
  subprocess + schema (`codex` — the operator's ChatGPT-subscription CLI, default
  `gpt-5.6-sol`, runs tool-less as a security boundary, passes the schema as a **file**
  via `--output-schema`; `claude-code` — the operator's Claude Code CLI subscription,
  passes the schema **inline** via `--json-schema <json>`, **not** a file path despite
  the flag name — verified behaviorally against the CLI, so the two subprocess backends
  are **not** symmetric), and deterministic-only (`none` — no LLM call at all, runs only
  the location + intern gates, and is **low recall on sponsorship**: the
  work-authorization check falls back to the closed ~2/11-recall `NO_SPONSOR_PHRASES`
  list). **Auto-detection never selects a paid backend** — the default stays `ollama`
  and `make_screener` never guesses from what's installed; spending money is explicit
  opt-in via `SCREEN_BACKEND`. New `--screen-model`/`SCREEN_MODEL` overrides whichever
  backend's default model. `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` are read from the
  in-process `env` dict only — never promoted to an argparse default, never leaked to a
  subprocess's inherited environment — the same secret-scoping discipline the fit
  scorer already follows. Screen batching is **not** part of this change; concurrent
  execution shipped separately later in this branch (see Changed, below).
  (SPEC §7.1.)

- **`onboard-me` skill gained a Step 0 and stopped carrying its own prereq prose.** The
  skill began at "write the profile", assuming a checkout that already worked, and
  hand-asserted prerequisites that had since gone stale (Telegram "required for the
  pipeline"; the screen running on a "host GPU … no cloud fallback"; ad-hoc `curl` /
  `codex doctor` probes). It now opens with **Step 0 — `make setup` then `make doctor`**,
  and reads doctor's status lines to pick the user's provider path instead of describing
  prerequisites from memory, with a row-by-row table of what a `[no]` means for each
  check. Step 7 shrank to just the values only a user can supply. Because doctor's
  provider rows are informational, the skill is explicitly told they are "a status line,
  not a verdict" — Telegram absent is a fine outcome, and a remote `OLLAMA_HOST` replaces
  the local-GPU requirement. Also makes the skill agent-agnostic: it reads a command's
  output rather than embedding harness-specific prereq prose. New eval scenario
  (`fresh-checkout-no-telegram-remote-ollama`) covers the behavior.

- **`make setup` and `make doctor` — one-command bootstrap and a preflight.** A fresh
  checkout had no path to a runnable worker: nothing installed deps, created the DB, or
  reported what was missing. `make setup` now installs web + worker deps, runs `db-push`,
  and copies the two **config** templates (`config.yaml`, `.env`) to their targets **only
  when the target is absent** (never clobbering a filled-in file). It deliberately does
  *not* create `resume.txt`/`personal_profile.txt`: every `resume/*.txt` is loaded as a
  résumé version, so a forgotten placeholder would silently be scored as the user's real
  résumé, whereas an absent file fails loudly and points at `resume/README.md`.
  `make doctor`
  (`python -m ats_worker.doctor`) prints one ASCII status line per prerequisite
  (worker deps · database · ollama · codex · claude · anthropic key · node · docker ·
  telegram) and exits non-zero **only** when a *universal* prerequisite is missing
  (worker deps + a set-up DB); provider rows report `ok`/`no` but never fail the exit
  code, since which provider is required depends on the path the user picks — the data
  `onboard-me` Step 0 will read to pick it. Doctor imports only the standard library, so
  it runs even on a checkout whose deps are missing — the state it exists to diagnose.

- **`--fetch-only`, `--score-only`, and `--score-limit` operator flags
  (`ats_worker.run`).** `--fetch-only` runs fetch/feed/expire/retry then stops before any
  screen or scorer call — a quota-free board refresh (and a real log). `--score-only` is
  the inverse: it skips the network ingest and scores the existing `new` backlog without
  a full re-fetch. `--score-limit N` caps how many `new` rows `run_score` touches in one
  pass (0 = no cap), bounding the paid fit scorer over a large fresh intake; the
  remainder stays `new` for the next pass.

### Changed

- **`run_score` now screens and fit-scores concurrently, instead of one posting at a
  time.** Both loops were serial; they now use the same read-serial /
  network-parallel / write-serial shape `run_feed` already proved (§7.1): every
  `db.*` call stays on the calling thread (SQLite connections aren't safe across
  threads), only the screen (`screen_fn`) and fit (`fit_fn`) I/O calls run in a
  `ThreadPoolExecutor`, and futures are consumed in **submission order** so writes
  stay deterministic and correctly row-associated. A failing screen or fit call
  still fails only its own row — the singles-fallback in the fit loop is unchanged.
  New `--screen-workers`/`--score-workers` (`SCREEN_WORKERS`/`SCORE_WORKERS`) knobs
  bound each pool; screen defaults to a **per-backend** value
  (`DEFAULT_SCREEN_WORKERS`) — **1** for `ollama`/`none` (a single GPU serializes
  the compute, so parallel requests interleave rather than speed up), **4** for the
  subprocess/hosted backends. Fit concurrency is **quota-neutral**: N parallel
  `codex exec` calls spend exactly the same number of messages as N serial ones —
  only wall-clock changes (§11).

- **The sponsorship screen is now a quote-grounded LLM check, not a closed phrase
  list.** The prior gate (`NO_SPONSOR_PHRASES`, a 12-phrase substring list) missed
  ~9 of 11 realistic no-sponsorship phrasings because it only matched wording
  literally on the list. `_check_authorization` (`score/screen.py`) now asks the
  model for `no_sponsorship_quote` — the exact JD sentence it claims states
  sponsorship is unavailable — and CODE (`_quote_in`) verifies that sentence is
  actually present in the description (whitespace-collapsed, case-insensitive)
  before disqualifying: a hallucinated quote fails verification and the posting is
  *kept*, so hallucination cannot disqualify anything by construction. This holds
  on the free `qwen3.5:4b` default too. `NO_SPONSOR_PHRASES` is demoted to a floor
  underneath the quote check: it still runs and can only *add* a disqualification,
  never veto a model pass, so `SCREEN_BACKEND=none` (no LLM at all) still gets the
  closed-list's blunt catch. New `tools/sponsor_diff.py` diffs the quote-grounded
  screen against the old phrase list over already-scored rows, so only the
  disagreements need hand-labeling. **Precision/recall on the new check is pending
  measurement against a hand-labeled set — not yet run** (PROGRESS.md, SPEC §7.1).

- **`workday` boards are now stub-gated (drop-only), cutting detail calls 55%.**
  `workday` shares `phenom`'s N+1 shape — a cheap paged list, then one detail GET per
  posting for the description — but was deliberately left ungated by the 2026-07-21
  stub-gate design, whose §Scope reasoned that its three boards held five postings
  total and so the id-reconciliation work wasn't worth it. A profile-driven watchlist
  expansion invalidated that premise: 28 workday boards, 14,902 postings, every one
  paying a detail GET *before* `title_filter` ever ran.

  The exclusion's underlying risk is narrower than the exclusion was. A workday list
  stub carries no GUID (`parse_job` reads `external_id` from the **detail** payload),
  so a *stored* stub keys on `jobReqId` and a later hydration inserts a second row
  under the GUID. That risk belongs entirely to the `discard` verdict, which stores an
  un-hydrated row. `drop` stores nothing at all, so it has no id to reconcile. The
  gate therefore honours **only** `drop`; `discard` and every unrecognised verdict
  fall through and hydrate exactly as before (also the fail-open path — a broken
  predicate can cost requests, never postings).

  New `workday.parse_stub` builds the title/location shape the gate reads and
  deliberately omits `external_id`, so it is unstorable by construction. Measured
  across the live 28-board watchlist: **14,902 → 6,703 detail calls per run (-55%)**
  from `title_filter`/`title_exclude` alone.

- **`workday` age-gating: the stub's relative prose date now feeds `max_age_days`.**
  A workday list stub's only date is prose (`"Posted 30+ Days Ago"`), so the gate
  above could not drop by age. `parse_stub` now dates that prose against the injected
  `now` — `posted_at = now - age` — so a stale stub is dropped before its detail GET
  too. Only the confident English `"N[+] Days Ago"` form is parsed, and the number is
  treated as a **lower bound** on age (`"30+"` → at least 30); `"Today"`/`"Yesterday"`
  and any other locale or wording leave `posted_at` None, which the age filter keeps —
  so a mis-parse can never silently drop a good posting. `now` reaches the adapter
  through the same `keep`-gate call path (`run_fetch` → `fetch` → `parse_stub`); which
  sources take it is declared by the fetch layer (`STUB_GATE_NOW_SOURCES`), so the
  orchestration layer selects by membership rather than naming a board. The reduction
  beyond the -55% is unmeasured and depends on `max_age_days` config (PROGRESS).

### Documentation

- **The `.agents/skills` symlink is verified, and it turns out to be load-bearing.** It
  shipped 2026-07-25 marked unverified, with the recorded guess that Codex would *not*
  follow a symlinked skills directory — most directory walkers don't (Rust
  `walkdir`/`ignore`, Python `glob('**')`, Node `readdir({recursive:true})`). Three
  `git archive HEAD` checkouts, `codex exec --sandbox read-only` in each, differing only
  in which directory exists: with the symlink all three repo skills load (resolved to
  their real `.claude/skills/...` paths); with `.agents/` removed and `.claude/skills/`
  intact **none** load; with neither, none. So Codex follows the link *and* never reads
  `.claude/skills` on its own — deleting the link silently costs a Codex session every
  repo skill. `codex-cli 0.144.5`; other agents remain untested and `AGENTS.md` says so.
  **Asking the agent is not the test:** Codex gave three inconsistent answers across
  runs and, in the checkout with no skills at all, confidently named all three — it was
  reciting `AGENTS.md`'s own "Current skills:" line out of its context. The evidence is
  the session rollout's skills-registry block under `~/.codex/sessions/`. Closes track 4
  of provider-choice-and-onboarding, the last of its five.

- **Agent context slimmed, and the self-merge review contradiction resolved.** An audit
  against Anthropic's 2026-07-24 context-engineering guidance found `CLAUDE.md` paying
  for content a session can derive itself and, worse, carrying a rule that contradicted
  the one `c641849` had just added. `CLAUDE.md` §Agent conduct said subagents were
  "never to verify or re-read your own work" and that the verify gate takes "no
  self-review pass on top", while §Sessions and `DEVELOPMENT.md` §7 required a **fresh
  subagent review** before a session may merge its own PR; `DEVELOPMENT.md` §5 carried
  the same contradiction against §7 *within one file*. Both now scope the older rule
  rather than drop it: the §7 pre-merge review is a gate on **merging**, explicitly not
  a second verification of the change, and a skill invoking another skill is not
  delegation (which is what had forbidden `onboard-me` from handing each company to
  `onboard-board`). Cut alongside it: the repo map and `make` target list (derivable
  from `ls` and `make help`), indent rules (`.editorconfig` owns them), commit and
  branch conventions (`CONTRIBUTING.md` and branch protection own them), the git
  identity (`git config` owns it), a scope rule duplicating the harness system prompt,
  and an unpaired code fence that had been in the file since it was written.
  `CLAUDE.md` drops from 7,064 to 4,587 chars.

- **Doc reading is now progressive instead of mandatory.** `CLAUDE.md` opened by
  requiring every session to read `SPEC.md`, `PROGRESS.md`, `PRINCIPLES.md`, and
  `DEVELOPMENT.md` "before any substantive work" — about 57k tokens, charged equally to
  a typo fix and a scorer rewrite, while the same file elsewhere warned that those docs
  are "already large and every session reloads them". The only genuinely unconditional
  read is `PROGRESS.md`'s **"In flight"** section (~2.4k tokens), because skipping it is
  how two sessions collide on one branch; that stays a hard rule in `CLAUDE.md`. The
  rest became a `session-boot` skill holding the read order — claim, classify, then only
  the `SPEC` sections the change touches, `PRINCIPLES` on a fork, §5/§6 at the end.
  `onboard-me`'s SKILL.md split the same way: the profile-authoring rules, the
  `candidate:` field reference, and the résumé fallbacks moved to `references/`, leaving
  the structural contract (the six profile section headers, the `<w:t>` extraction rule)
  in the body where the evals depend on it.

- **Unattended long-run day captured as a committed runbook.** The next operational
  step — one unattended day that clears both of PR #7's merge blockers and puts a
  bounded, provenance-stamped slice of the ~3,985 unscored postings through the
  pipeline — lived only in a conversation, which is exactly the decision shape the
  cross-session handoff rule exists to prevent. Now
  `docs/superpowers/plans/2026-07-24-long-run-day-runbook.md`, with the five phases and
  their concrete commands, the message-bound quota math (including the ~150-message
  reserve that keeps a good scoring run from eating the gate budget), the branch it
  must run from (`feat/score-provenance-and-rescreen` — score anywhere else and ~1,500
  rows persist unstamped, permanently), the monitoring cadence, and an explicit
  **authority boundary** splitting what an agent may decide alone from what waits for
  the operator (the Stage 4 revert, any merge, editing the golden set, any code
  change). PROGRESS's "Do next" now points at it as the queue head, and its phase
  checkboxes are the run's live state for a session that picks it up mid-flight.

- **The strong-model-overturn decision resolved by measurement, not design.** That
  entry had said one free read-only query would unblock it; the query ran 2026-07-24.
  Of 3,262 discarded rows, `location` accounts for 94.0% and degree/clearance-*only*
  discards for 30 rows (0.9%) — under the entry's own "a couple of percent → just route
  them" threshold, so it drops from `M` (build a screen eval first) to `S` (route ~30
  rows to the paid scorer). The same number deflates the `screen.txt` eval-gate entry,
  whose clauses turn out to decide ~1.2% of discards. PROGRESS records both, plus the
  caveat that most of those 3,262 are fetch-time location kills, so degree/clearance is
  a larger share of *screen-stage* discards than 0.9%.

- **PROGRESS "In flight" reconciled with what actually merged.** PRs #4 and #5 are on
  `main` (#5 needed a CHANGELOG conflict resolution — `main`'s squash of #4 diverged
  from #5's copy of those commits). **PR #6 was based on `feat/workday-stub-gate`, not
  `main`**, so merging it landed there; that branch now sits 8 commits ahead of `main`
  with no PR of its own, and one PR closes the gap. The new
  `feat/score-provenance-and-rescreen` branch is recorded as queuing behind #7.

- **A branch/PR/merge protocol for sessions working as a team.** Sessions are the
  workers on this repo and share no memory — only the repo — but nothing wrote down how
  they should hand work between each other, and 2026-07-24 spent four merges paying for
  that. `DEVELOPMENT.md` gained **§7**: work is *claimed* by its `PROGRESS.md` In-flight
  entry rather than by the branch existing; each branch rule cites the incident that
  bought it (a PR that silently targeted another feature branch instead of `main`; a
  merge onto a local branch that was stale because `git fetch` updates remote-tracking
  refs, not local ones; the squash-divergence conflict every stacked PR hit, whose
  mechanical resolution would have re-opened an item that same branch shipped); and an
  **authority table** splits what a session decides alone (branch, commit, push, open a
  PR, record a defect) from what needs the operator (**merging to `main`**, force-pushes,
  releases, reverting another session's work, anything spending money or quota) — with
  the note that "just merge" authorizes *that* merge, not a standing one. A session may
  merge **its own** green PR, but only behind a **fresh-subagent review**: an author
  cannot review its own diff (it re-reads its intent and checks the code against the
  plan, rather than checking the plan), so the reviewer gets the diff and the spec and
  explicitly *not* the working session's reasoning, and any finding that survives
  verification blocks the merge. CI green is not a review. `CLAUDE.md`
  carries the short form. **Deliberately rejected: GitHub issues as the queue** —
  `PROGRESS.md` already is one, in-repo and greppable, and a second list would drift.

- **Agent protocol retuned for Claude Opus 5, now the repo's dev model.** The rail was
  written against older models and carried two assumptions that no longer hold. First,
  DEVELOPMENT.md's closing hint routed design work to "the strongest model available"
  and maintenance to "smaller ones" — on Opus 5 the dial is **effort**, not model size
  (`xhigh` for design and multi-file work, `low`/`medium` for maintenance, docs, and
  review). Second, nothing capped the behaviors this model does on its own: it
  self-verifies, delegates, and writes long. So §5 now states that the evidence table
  *is* the verification step (no self-review pass, no subagent to double-check own
  work), §6 and a new `CLAUDE.md` "Agent conduct" block calibrate doc length against
  the three files every session reloads, and the same block caps delegation and pins
  scope to the ask. The kickoff template gained the matching scope line.

- **PRINCIPLES gained "the four kinds of uncertainty" — "err toward keep" is one row,
  not the whole rule.** The bias was stated everywhere as a single rule, but the code
  deliberately does not apply it uniformly: `_normalize_score` raises on a missing score
  (buried as 0 it would silently drop the posting out of notification),
  `_normalize_assessment` raises on an out-of-enum verdict (they drive the seniority
  floor and the ranking), and the codex fit backend raises the **whole batch** on a
  missing, duplicate or unknown `job_ref`. Each carried a local comment; nothing stated
  the general rule behind them, so an agent reading only "err toward keep" had a live
  licence to soften them into defaults. Now a table — candidate opportunity **KEEP** ·
  data integrity **FAIL LOUD** · systemic configuration **CIRCUIT BREAK** · delivery
  **RETRY** — with principle 3 itself scoped to opportunity uncertainty, and a pointer
  from `CLAUDE.md`. It earns its place because **every one of the seven defects found
  probing this pipeline on 2026-07-23 is one cell treated as another.**

- **README reordered for a first-time reader instead of a reviewer.** The landing
  page led with the tech stack and a 14-line bullet that carried the entire pipeline,
  Codex-vs-Claude billing, Telegram, and the no-auto-apply promise in one breath, then
  pointed at the authoritative spec above the fold. It now opens with the five-step
  flow, states who it's for and what it deliberately doesn't do (no auto-apply, no
  employer-side ATS, no login/CAPTCHA circumvention), splits Features into
  Discover/Screen/Score/Track, and offers the tracker-only and full-pipeline paths
  separately with their prerequisites named — deferring to `SETUP.md` rather than
  dropping the reader into SPEC §12. Adapter counts are now an explicit source list
  instead of "and 6 more", so the 11/13/watchlist-capable split reads without
  arithmetic. No behavior change.

- **Docs audit — drift corrected and duplication collapsed.** Fixed every claim that
  had fallen out of step with the code: the adapter count (11 platform adapters +
  custom/browser recipe executors, of which 11 are watchlist-capable — the old "9 / 11
  total" silently dropped the feed-only oracle/jobvite), `SECURITY.md`'s supported
  branch (`main`, not the deleted `master`/`dev`) and spec pointer (§6/§11, not §3/§4),
  `CONTRIBUTING.md`'s CI trigger (PRs + pushes to `main` + nightly — *not* every push)
  and the tracked-resume-template list, `CLAUDE.md`'s repo map (`feed/`,
  `check_privacy.mjs`, `SETUP.md` is no longer a stub) and command list (adds
  `test-integration` / `check-privacy`; `make up` is the web stack, not the worker),
  and the `docker compose up` goal in SPEC §4, which claimed a one-command stack the
  native worker never belonged to. Renamed the leftover "ATS" titles in SPEC, PROGRESS,
  and the Makefile to Job Matchbook. `PRINCIPLES.md` #4 now names the hosted scorer
  generically (Codex is the default, not Claude) and #7 records Playwright as shipped
  rather than planned.
- **One home per fact.** `SECURITY.md`'s accepted-risk list and `README.md`'s 25-row
  feature-status table were second copies of `SPEC.md` §11 and §9; both now point at
  the spec, and the `next@14` advisory writeup moved into §11 so nothing was lost.
  Deleted `docs/pipeline-design.md` (a pointer stub — the original is in git history)
  and trimmed `docs/SETUP.md`'s Path B, which restated SPEC §12's numbered steps.
- **`apps/worker/quant_job_boards.txt` untracked.** The file's own legend defines
  `[x]` as "added to `apps/worker/config.yaml` AND verified live", and 43 lines carry
  it — so the tracked copy disclosed which companies the operator is personally
  tracking (65 of the 73 names/slugs in the gitignored `config.yaml`). Now gitignored,
  with a matching deny rule + self-test case in `tools/check_privacy.mjs` so it cannot
  return via `git add -f`. Also deleted `docs/images/status-funnel.png`, orphaned when
  `charts-row.png` replaced it. A credential sweep (Telegram/Anthropic/OpenAI/GitHub/AWS
  /private-key patterns) and an 8-word-shingle comparison of the real résumé and
  `personal_profile.txt` against every tracked file both came back clean.
- **Project-level Claude Code config.** `.claude/settings.json` (read-only permission
  allowlist) plus `.claude/hooks/guard-privacy.mjs`, a `PreToolUse` hook that blocks
  `git commit` whenever `tools/check_privacy.mjs` reports a tracked private file —
  CI only catches such a leak after it is already pushed.
- **Design-spec statuses are current again.** Twelve specs under
  `docs/superpowers/specs/` still read "ready to implement" / "not yet built" for work
  that shipped; each now carries its ship date. `DEVELOPMENT.md` §6 adds closing the
  spec to the same-commit doc rule, since §2 treats that header as the license to build.

## [1.0.0] — 2026-07-22

*Milestone:* on **2026-07-13** the full `fetch → screen → score → notify` pipeline ran
against live services for the first time — one cold pass over 39 boards → **1169**
postings fetched, **~45%** screened out (internship/location/visa), **642** fit-scored
with zero failures, matches delivered to Telegram.

### Repository

- **Renamed to Job Matchbook (`job-matchbook`) and published.** The repo went public
  under a product name instead of `personal-ats`, with the About description and topics
  filled in. *match* = the worker (screen + fit score), *book* = the tracker (the kept
  record). Code identifiers (`ats_worker`, `ats-web`, `apps/`) are deliberately unchanged.
- **`dev` + `master` collapsed into a single `main`.** `master` was a strict ancestor of
  `dev`, so the 274-commit lag closed as a fast-forward with no merge commit and no
  history rewritten. `main` is now the only long-lived branch: substantive work lands as
  a squash-merged PR with CI green, small doc fixes go direct, and the branch is
  protected (required `Web` + `Worker` checks, linear history, no force-push or
  deletion). `CONTRIBUTING.md` and `DEVELOPMENT.md` §6 document the flow; design and
  rationale in `docs/superpowers/specs/2026-07-21-repo-workflow-design.md`.

### Security

- **Watchlist slug host-safety check (closes a SPEC §11 residual).** `phenom` and
  `workday` pack a hostname into the slug, and the slug charset check
  (`[A-Za-z0-9._/-]`) can't distinguish a careers hostname from an internal IP
  literal — so `phenom` slugs like `127.0.0.1/x` or `169.254.169.254/x` reached the
  fetch. Both adapters now run the built host through `util.is_safe_public_url` in
  `_parts` and raise `ValueError` instead. `workday`'s check is belt-and-braces (its
  `.myworkdayjobs.com` suffix is hardcoded today) and guards the built URL so it
  holds if the slug charset ever loosens.
- **`npm audit fix` (no `--force`) clears the `defu`/`effect` Prisma-toolchain
  advisories.** `defu` <=6.1.4 (prototype pollution via `__proto__` in a defaults
  argument) and `effect` <3.20.0 (`AsyncLocalStorage` context loss/contamination
  under concurrent RPC load — pulled in transitively via `@prisma/config` →
  `prisma`) both had non-breaking fixes: defu 6.1.4→6.1.7, effect 3.18.4→3.21.0,
  and `prisma`/`@prisma/config` took a same-major patch bump (6.19.2→6.19.3) to
  pick up the new `effect`. `package.json` is unchanged; only the lockfile moved.
  `npm audit --omit=dev` went from 6 advisories (1 moderate, 5 high) to 2 (1
  moderate, 1 high). The remaining two — `next@14.2.35`'s high advisories and
  the `postcss` moderate bundled with it — require the `next@16` major and are
  an accepted risk for this release (kept off `--force`; documented in the
  shipped `SECURITY.md`'s accepted-risk list — see "Community health files"
  below).
- **`add_watched.py` (onboard-board) now validates the slug charset before writing the
  watchlist.** The script derives slugs from scraped, untrusted careers pages and wrote
  `args.slug` straight to `db.import_watchlist` with no check — a third watchlist write
  boundary the earlier slug guard missed (the web `actions.ts` and worker `config.py`
  boundaries both validate). Now calls `config._valid_slug` right after the source check,
  before the recipe load / DB-exists check / DB write, closing the host-injection SSRF gap
  at all three boundaries.
- **Redirect-following SSRF closed on the feed/custom paths; browser path's data-return
  harm closed, one residual GET remains.** `requests` (default `allow_redirects=True`)
  and Playwright's `page.goto` both follow 30x redirects, so a public URL that passed
  `is_safe_public_url`'s initial check could still 302 into an internal target (e.g.
  `169.254.169.254`, `localhost:11434`) — the first-hop-only guard missed it. A new
  `util.get_redirect_safe` follows redirects manually, re-validating **every hop** with
  `is_safe_public_url` before it is requested (so an internal host is never contacted),
  and is now used by `feed/embedded_gh.resolve_embedded` (attacker-controllable:
  Simplify feed data) and `fetch/custom._request` (operator-authored recipe URLs) — for
  these two paths the internal host is never contacted, full stop. `fetch/browser.py`
  adds a Playwright route interceptor (`_block_unsafe_navigation`, registered via
  `page.route("**/*", ...)` right after page creation) that blocks internal
  *subresources* (img/css/xhr) the rendered page issues, plus a post-`page.goto`
  check in `render()` on the *landed* `page.url` that discards the response when it's
  non-public. That combination closes the *data-return* harm (an internal target's
  body never reaches a posting's description) but **not** the request itself: per
  Playwright's docs the route handler fires only for a navigation's initial URL, so a
  3xx redirect is followed by Chromium without re-invoking the interceptor — a single
  read-only GET to the internal target still fires before `render()` discards the
  response. Browser sources are gated off the default cycle, which bounds this residual.

- **Validate watchlist slug structure at the web + config write boundaries.** Both
  `addWatchedCompany` (web) and `_parse_companies` (worker `config.py`) now reject a
  `slug` outside `[A-Za-z0-9._/-]` or containing `..`/leading-trailing-doubled `/` — the
  slug is interpolated straight into a fetch URL host/path by the board adapters, so this
  blocks host-injection metacharacters (`@ : ? # % \` and whitespace) while still allowing
  legitimate multi-part slugs (workday `tenant/dc/site`, phenom `host/domain`).
- **CSV export prefixes formula-lead cells (= + - @) with `'` to block spreadsheet formula injection.** Cells whose first character is a character a spreadsheet may treat as a formula lead are now prefixed with a single quote before quote-wrapping, so Excel and Sheets render them as literal text instead of executing formulas.
- **Web UI is published on loopback only (`127.0.0.1:3000`).** The Compose port bind
  was `0.0.0.0:3000`, exposing the unauthenticated server actions to any LAN peer;
  it now binds `127.0.0.1` (single-user localhost, no-auth is a non-goal). (SPEC §6/§11.)
- **Removed real résumé + `config.yaml` from git history.** `apps/worker/resume/resume.txt`
  and the real `config.yaml` (committed 2026-06-05, untracked 2026-06-08) were purged from
  all history with `git filter-repo` and force-pushed; the repo was also made private as
  immediate containment. (SPEC §3/§11, Privacy-first.)
- **Telegram bot token is scrubbed from recorded/printed notify errors.** A `requests`
  failure embeds the full Telegram URL (with the token) in its exception text; `run_notify`
  now redacts the token to `***` before writing `job_postings.pipeline_error` (shown in the
  web Failed bucket) or printing it.
- **Bump Next.js 14.2.0 → 14.2.35 (CVE-2024-56332 server-actions DoS).**
- **Health probe 503 returns a generic message; error detail logged server-side only.**
  The `/api/health` endpoint was leaking the raw error message (e.g. `SQLITE_CANTOPEN`) in
  the 503 response body; this could reveal internal paths and driver strings to clients.
  The response now returns a generic `{ status: 'error', error: 'database unreachable' }`,
  while the full error is logged server-side only via `console.error()`. The autoheal
  sidecar keys on the status code, not the body, so the change is transparent to monitoring.
- **Job-posting links pass through safeHref (http/https only) to block javascript:/data: URLs in scraped job_url.**
  Untrusted scraper output (job_url) is rendered in `<a href>` tags; malicious javascript: and
  data: schemes execute on click. The new `safeHref` utility allows only http(s) schemes, blocking
  XSS via scraped URLs. Applied to `DiscoveredJobsTable` and `JobDetailModal` link hrefs.
- **`db._update` validates SET columns against an allowlist.** Defense-in-depth: the worker's
  shared `_update` helper builds its SQL `SET` clause from dict keys; a new `_UPDATABLE_COLUMNS`
  frozenset (`score`, `score_detail`, `pipeline_status`, `pipeline_error`, `updated_at` — the exact
  union of what `save_score`/`mark_notified` pass today) now rejects any other key with an explicit
  `ValueError` before it can reach the SQL string, guarding against a future caller passing an
  attacker-influenced key.
- **promotion-suggestions query binds source list as params instead of string interpolation.**
  `promotion-actions.ts`'s `SUGGESTIONS_SQL` interpolated `VALID_SOURCES` directly into the
  `IN (...)` clause (safe only while the list stays a compile-time constant); it now binds a
  `?` placeholder per source and passes `VALID_SOURCES` as positional `$queryRawUnsafe` args,
  removing the interpolation seam entirely.
- Add X-Frame-Options/X-Content-Type-Options/Referrer-Policy/CSP response headers.
- Server actions gate status/category to the constants sets and clamp page/size.
- **Embedded-greenhouse resolver refuses non-public/non-http(s) fetch targets.** New
  `util.is_safe_public_url` (pure, no DNS) rejects `localhost` and private/loopback/
  link-local/reserved IP literals (incl. the `169.254.169.254` metadata endpoint) and
  non-http(s) schemes; `feed/embedded_gh.py`'s `resolve_embedded` checks it before any
  HTTP GET, so a malicious Simplify-feed listing can no longer make the worker fetch an
  internal target.
- **`custom` and `browser` recipe executors validate `recipe.url` against the SSRF guard before fetching.** Both `fetch()` functions now call `is_safe_public_url()` as their first statement (before the lazy Playwright import in `browser`), blocking non-http(s) schemes and private/loopback/link-local/reserved IP literals including legacy IPv4 notations.
- **`browser` executor also guards the per-posting detail URL and the pagination URL, not just `recipe.url`.** The detail href (`p.get(url_field)`) is scraped from third-party board listing HTML, not operator-authored — a malicious/compromised board could otherwise embed an internal target (e.g. the cloud metadata IP) as a job's href and have headless Chromium fetch it, scraping the response into `description` (a data-return SSRF). `fetch()` now runs `is_safe_public_url()` on that URL before rendering and skips it (posting kept, description-less) when unsafe; the operator-authored pagination URL (`page.template.format(n=n)`) gets the same check and **raises** on an unsafe value (symmetric with `recipe.url` — the board is logged + skipped, not silently truncated to page 1). This blocks the internal-IP-*literal* payload; bare internal hostnames (`metadata.google.internal`) and redirect-to-internal remain the documented accepted-residual of the pure, no-DNS guard (PROGRESS). Both guard paths are now exercised by a fake `sync_playwright` (no Chromium, runs in CI).
- **Codex usage capture only deletes an unambiguous rollout and cleans up on failure.**
  `_capture_usage` now gathers every session rollout newer than the pre-call mtime mark
  and deletes the newest one only when it's the *sole* newer rollout — zero or several
  means a concurrent codex session shares the window, so deletion is skipped and nothing
  is removed, closing the risk of nuking another session's history. `make_codex_scorer`'s
  `fit()` also moves the capture call into a `finally` around the `codex exec` subprocess
  call + exit-code check + result read, so the résumé-bearing rollout (written because
  capturing drops `--ephemeral`) is reaped even when the exec fails, instead of leaking
  the full résumé+profile+JD prompt onto disk.
- **Pin CI actions and the web Docker base image by SHA digest.** All 10 `uses:` steps
  in `.github/workflows/ci.yml` (`checkout`, `setup-node`, `setup-python`, `cache`,
  `upload-artifact`) and `apps/web/Dockerfile`'s `FROM node:20-alpine` now resolve to an
  immutable commit/image digest (with a `# vN` / image-tag comment so renovate/dependabot
  can still bump them), closing the floating-tag supply-chain gap tracked in PROGRESS.
- **Worker `main()` only merges the six argparse-read config keys from `.env` into
  `os.environ`, no longer every key.** The previous unconditional merge promoted secrets
  (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`) into `os.environ`, which
  are then inherited by any subprocess spawned without an explicit `env=` — the default
  codex fit-score backend's `subprocess.run` call (`score/backends_codex.py`), handing the
  Telegram bot token and Anthropic API key to the third-party `codex` CLI (and anything
  reading `/proc/<pid>/environ`). Every secret consumer already reads the in-process `env`
  dict (`run_once(..., env=env)` / `make_scorer`), never `os.environ`, so the secrets remain
  fully plumbed without being promoted.


### Added

- **Dead-link sweep (`pipeline.run_expire`).** Each pass re-fetches up to 50 live
  (`scored`/`notified`) postings from **detail sources** — the ones with a real per-job
  endpoint — least-recently-updated first, and marks the ones the board answers 404/410
  for as `pipeline_status='expired'` (new terminal status; drops out of the live
  Discovered buckets like `removed`). Every other outcome — timeout, 403 bot wall, 5xx,
  a `None` from the adapter — leaves the row live, because wrongly expiring a match costs
  a job while a missed dead link costs one stale row. A successful check rewrites
  `updated_at`, which is the entire queue-rotation mechanism (no new column). Runs after
  fetch/feed, before retry.
- **Privacy guard (`tools/check_privacy.mjs`, `make check-privacy`, CI).** Fails if git
  *tracks* any private file — `.env`, `config.yaml`, `db/` or any `*.db`,
  `apps/worker/resume/` (bar `README.md` / `*.example`), `apps/worker/eval/`, `resumes/`.
  `.gitignore` only guards the default path; this catches `git add -f`, a loosened ignore
  rule, or a file committed before its rule existed. Path deny-list, no content scan;
  `--self-test` pins the allow/deny regexes and CI runs it alongside the schema-drift guard.

- **User-configurable job categories (general-purpose pivot).** The application-category
  vocabulary is no longer a fixed quant/SWE enum — it's chosen per user and stored in a new
  `app_settings` table (key `categories`, JSON value). A first-run modal prompts new users to
  pick their own categories; a header **Categories** button edits them anytime; the Add form,
  Mark-Applied dialog, table filter, and donut all read the chosen list. `getCategories` /
  `setCategories` server actions back it. Categories are now **free-form labels** (the dropdown
  supplies the vocabulary), so the old "coerce an unknown category to Others" behavior is gone —
  only a blank value falls back to `Others`.
- **`personal_profile.txt.example` + docs.** A persona-neutral profile template, plus
  documentation in `apps/worker/resume/README.md` of the TARGET / ANTI-TARGET / STAGE structure
  the scorer's domain verdict reads (previously only in `SPEC.md`).
- **`onboard-me` skill — full guided setup.** A conversational, adaptive first-time
  onboarding: one interview (step-by-step for a bare "onboard me", or straight to writing when
  the user front-loads details) that builds `personal_profile.txt` (STAGE / TARGET tiers /
  ANTI-TARGETS / POSITIONING / INTERESTS / CAVEATS, with explicit rules keeping it
  résumé-backed — interests never inflate a top target, anti-targets scoped so they don't sink
  wanted roles), ingests the résumé into `resume/resume.txt` (`.txt`/PDF/`.docx`, no new
  dependency), sets the DB categories (bundled `set_categories.py`), fills the `config.yaml`
  `candidate` block, seeds a starter watchlist (delegated to the `onboard-board` skill), guides
  `.env`/prereqs (verify, never fabricate secrets), and ends on `python -m ats_worker.run
  --once`. Steps are ordered-but-independent — a narrow ask ("just set my categories") does one
  step and stops. `score.txt` is never touched — generality lives in the profile. Validated with
  a skill-creator eval suite (`.claude/skills/onboard-me/evals/`).
- **Fetch-time filtering (watchlist path).** Two global `config.yaml` knobs cut
  local-LLM volume before any model runs: `max_age_days` drops postings whose
  `posted_at` is older than N days (dateless boards kept; `0` = off), and
  `title_exclude` drops titles containing any listed keyword (the negative
  complement of `title_filter`). The deterministic intern/location screen gates now
  also run **at fetch** (`deterministic_screen`), so a location/intern miss is
  recorded `discarded` — visible in the Discovered "Discarded" bucket with its reason —
  **without** an Ollama call, instead of after it. No schema change. (Phase 1 of
  `docs/superpowers/specs/2026-07-20-fetch-time-filtering-design.md`; per-board rules
  remain future work in PROGRESS.)

- Index on `status_history.application_id`.
- Schema-drift guard now also checks column nullability (pytest guard).
- **Cross-service drift guard for board-source allowlists + low-context threshold.**
- **`browser` recipe executor (headless Chromium, isolated + opt-in).** The universal
  last-resort fetcher (`fetch/browser.py`) for boards plain HTTP can't reach — a Playwright
  Chromium renders the page and CSS selectors extract from the rendered DOM: `item` + `fields`
  (selector or `{selector, attr, extract}`), `url`-template pagination, and an optional per-role
  `detail` enrich. Same recipe idea as `custom`, so a board stays a data row. **Cloudflare
  handling:** a realistic UA + viewport + `--disable-blink-features=AutomationControlled` and
  *waiting for the `item` selector* (not a fixed sleep) lets the "Just a moment" JS interstitial
  auto-clear for the listing — the default headless-shell fingerprint otherwise gets stuck (0
  cards). Cloudflare still re-challenges rapid deep-link navigations, so per-role `detail` pages on
  a walled board come back description-less; a **circuit-breaker bails detail enrichment after 3
  straight empties** (postings still ship with title/location/url; self-heals if the wall relaxes).
  **Kept off the pure-`requests` core**: Playwright is lazy-imported inside `fetch()` and lives in a
  new `requirements-browser.txt` (the repo has no pyproject extras); a missing extra raises a clear
  install hint; and `browser` rows are gated off the default cycle by `enable_browser_sources`
  (default off, filtered with a log in `run_once`) — a normal run never imports Chromium. First
  members: Citadel Securities + Citadel (Cloudflare) and Renaissance (Struts, JS-rendered). Pure
  `parse_jobs`/`apply_detail` fixture-tested against live-captured Citadel/Renaissance HTML; the
  browser-driving `fetch` is `# pragma: no cover` glue. (Board-scraper expansion, phase 4.)
- **`custom` recipe executor (declarative, plain-HTTP fetch).** A generic executor
  (`fetch/custom.py` + shared `fetch/_recipe.py`) driven by a JSON **recipe** stored on the
  watchlist row — no per-site code, so adding a board stays a data row. Modes: `json` (GET/POST)
  and `next-data` (extract the `__NEXT_DATA__` blob, then treat as JSON); pagination
  `offset`/`page`/`none`; an optional `item_path` (omit for a bare root-level JSON array, e.g. Jane
  Street); a `fields` map with dotted paths (list-indexing, e.g. `office.0.name`),
  `url` templates, list-concat descriptions, and a tolerant date normalizer (ISO / "Month D,
  YYYY" / epoch s|ms). Schema: a nullable `recipe` column on `watched_companies` (Prisma-owned,
  mirrored in the drift fixture); `config` requires a recipe for `RECIPE_SOURCES` (`custom`,
  `browser`); the dispatcher routes `recipe` only to those executors; the web add-company form
  gains a recipe JSON field (parsed + required for recipe sources). Verified against live-captured
  Amazon / TikTok / DE&nbsp;Shaw fixtures. (Board-scraper expansion, phase 2.)
- **iCIMS + Phenom board adapters (plain HTTP, watchlist-capable).** Two new per-board
  sources, no browser. **iCIMS** (`slug` = careers subdomain, e.g. `careers-sig`) GETs
  `{slug}.icims.com/jobs/search?in_iframe=1&pr={n}` and parses the server-rendered job cards
  with BeautifulSoup, paginating `pr` until a page yields no new ids. **Phenom** (`slug` packs
  `{host}/{domain}`, e.g. `apply.careers.microsoft.com/microsoft.com`) pages
  `/api/pcsx/search` by `start` against `data.count`, then hydrates each posting's description
  via one `/api/pcsx/position_details?…&position_id={id}` call (a failed detail keeps the
  posting, description-less). Both emit the canonical 8-field posting dict, registered in
  `fetch.ADAPTERS` + `config.VALID_SOURCES` (and web `constants.ts`); fixtures captured live.
  Adds `beautifulsoup4` to the worker deps. (Board-scraper expansion, phase 1.)
- **Codex quota usage bar (web + worker).** The `codex` fit-score backend now captures
  its own quota usage off each scoring call: it reads codex's `/status` accounting
  (`used_percent`, `resets_at`, `window_minutes`, `plan_type`) from the **session rollout**
  the scoring call writes — for **free** (rides the scoring message, no probe; best-effort,
  never breaks a score) — and writes a latest-wins `codex_usage.json` snapshot in the
  shared db dir. (`codex exec --json` stdout carries only thread/turn/item events, **not**
  `rate_limits` — verified on 0.144.5 — and `--ephemeral` suppresses the rollout, so when
  capturing the scorer drops `--ephemeral`, reads the rollout it just wrote, then deletes
  it; assumes sequential scoring.) A new `app/api/codex-usage/route.ts` serves it (adds
  `as_of` from the file mtime; empty state, not an error, before the first pass) and a
  `CodexUsageBar` renders one bar per limit — `used_percent`, "resets in Nd Hh", "as of" —
  on the Discovered Jobs view. It reflects the **last scoring call**, not a live reading:
  a fresh "now" reading would cost a quota message, the exact resource being tracked.
  Capture runs only on the production `run_once` path (a `usage_path` is set), so the
  eval/test path keeps its byte-identical `--ephemeral` gated call. Replaces the parked
  "message-quota usage tracker" plan: the
  observed binding limit is **weekly** (`window_minutes=10080`), not the assumed rolling
  5-hour window, and codex reports usage itself (via `rate_limits`; the bar also renders a
  `secondary` limit if one appears), so no homegrown call-counter or exit-1 stderr
  fingerprinting is needed. Storage is a single shared-mount file (no Prisma schema
  change). (SPEC §7.1, §7.2; design `docs/superpowers/specs/2026-07-17-codex-quota-bar-design.md`.)

- **Drift probe (`tools/score_eval.py --drift-probe`) — answers whether the batched
  verdict drift is context bleed or draw noise. It's bleed, and it scales with batch
  size.** The `--batched` guard draws each row once per pass, so it structurally cannot
  tell "batch-mates corrupted this verdict" from "this JD is a coin-flip on any re-draw"
  — every drift row was `adjacent`-domain borderline, consistent with either. The probe
  re-draws the 4 drift rows **K=3×** at one batch size per run (`CODEX_BATCH_SIZE`; `1` =
  single/probe-rows-only, `>1` = batched over the **whole** golden set so probe rows keep
  their real batch-mates — scoring the 4 alone would replace the very context under test).
  **Run 2026-07-17 (`gpt-5.6-sol`, b=1/5/10, 36 calls, one window):** rows holding one
  verdict went **3/4 → 2/4 → 1/4**. **`batch_size=5` is not a safe middle ground** — it
  turns id 111 from stably *correct* (`match/adjacent` ×3 single) into stably **wrong**
  (`match/match` ×3), crossing the notify predicate; a confident wrong answer is worse
  than a flip. id 184 is stable in *both* modes at *different* values (noise can't do
  that), and id 132's **seniority** bleeds at b≥5 — so the corruption is **not** confined
  to `domain`. Batching stays parked at `batch_size=1` for good; the quota win is off the
  table via batching (SPEC §11, §13).

- **Low-context tab in Discovered Jobs.** Postings whose JD is too thin to screen/score
  with confidence now get their own bucket instead of being silently scored alongside
  confidently-parsed rows. Detection is *derived at query time* — no schema change, no
  worker change: a single raw `LENGTH(TRIM(description)) < LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`
  query (new constant, default 200) yields the low-context id set, layered as `id IN` on
  the new `lowcontext` bucket and `id NOT IN` on Matched/Discarded/Failed so the buckets
  stay **mutually exclusive**. Scope is the scored/notified rows that actually received a
  fit score; disqualified/failed/applied/removed rows keep their own buckets. New tab in
  `DiscoveredJobsTable`, `JobBucket` gains `'lowcontext'`; tune via the one constant in
  `lib/constants.ts`. Covered by unit (`actions.test.ts`), integration
  (`actions.int.test.ts`, mutual-exclusivity assertion) and component
  (`DiscoveredJobsTable.test.tsx`) tests.
- **Tests for two untested CI blind spots.** (1) The chart-data aggregations
  `getStatusFlow` / `getTimelineData` / `getCategoryData` (`lib/actions.ts`, feeding the
  Sankey / heatmap / donut) now have integration coverage against the throwaway SQLite
  (`charts.int.test.ts`) — status-chain dedup + collapse, per-day `T`-split counts,
  `null`→`Others` bucketing. (2) The `/api/health` liveness probe now has a unit test
  (`health.test.ts`, `@jest-environment node`) asserting 200 on a reachable DB and 503
  when Prisma throws. `jest.setup.ts` is guarded (`typeof window !== 'undefined'`) so the
  shared jsdom setup is a no-op under node-env files.
- **Fit-score band-regression eval harness** (`apps/worker/tools/score_eval.py` +
  `make eval-score`). Read-only (opens the shared DB `mode=ro`, never writes DDL/DML),
  reuses the exact production scorer wiring (`load_resumes` →
  `make_claude_scorer("claude-sonnet-5")` → `score_fit` → `_normalize_score`), scores
  each row of a frozen hand-labeled golden set K=3× and judges the **majority
  keep/near/skip band** — not the noisy exact score — against the label in code. PASS =
  0 hard-invariant violations + ≥85% band agreement + <20% flip-rate over the gate rows;
  `marked` rows route to a flagged watch list, excluded from the gate. Uses `max_tokens=8192` +
  a per-draw retry so a truncated response (adaptive thinking overruns the prod 4096 cap
  and is *not* an SDK-retried transient) can't abort a paid run. Replaces the retired
  ad-hoc "edit prompt → paid re-score → eyeball 20 rows" loop; the golden labels
  (`apps/worker/eval/`) stay gitignored (real postings). Design:
  `docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md`.

- **Multi-resume fit scoring.** The worker loads every `resume/*.txt` as a labeled
  resume version (plus optional `personal_profile.txt` context); one Claude call
  scores the best-fitting version and names it (`recommended_resume`, enum-constrained),
  surfaced in the Telegram alert and the job detail modal. Single-resume setups are
  unchanged. (`--resume` → `--resume-dir`.) **Validated live 2026-07-13:** first
  full production pass — two resume versions (`swe`, `quant_dev`) over a 642-posting
  cold run, zero scorer failures; `recommended_resume` confirmed in `score_detail`
  and the Telegram `Resume:` line. (Closes the last "unexercised live" gap in
  `docs/PROGRESS.md`.)
- **Development mechanism for AI sessions: `docs/PRINCIPLES.md` + `docs/DEVELOPMENT.md`.**
  PRINCIPLES captures the project's fourteen design principles (each with rationale,
  repo exemplar, and violation smell) plus the decision procedure (forks go to the
  user; rejected alternatives get recorded). DEVELOPMENT pins the six-step session
  rail — boot, task classification, design gate, implement, evidence-based verify
  gate, same-commit docs — with a session-kickoff prompt template. `CLAUDE.md` and
  SPEC §14 now point at both. Design spec:
  `docs/superpowers/specs/2026-07-09-dev-mechanism-design.md`.

- **Discovered Jobs: sort by Best match or Newest posted (new `posted_at`, captured
  from greenhouse/lever/ashby/workday); bulk Remove (terminal, hidden + worker-inert)
  on Matched & Discarded, bulk Reopen + "Remove all in view" on Discarded; Discarded
  reframed as a near-miss audit view (default 60–74); job titles link to the posting.**
- **Embedded-greenhouse feed resolution.** Companies that host greenhouse jobs on their
  own domain with `?gh_jid=` apply URLs now resolve: a new *enriching resolver*
  (`feed/embedded_gh.py`) fetches the company page, scrapes the greenhouse board token
  (`…/embed/job_board?for=<token>`), and yields `("greenhouse", token, gh_jid)` so the
  existing greenhouse adapter ingests it (dedups with direct greenhouse). It stays out
  of the pure `resolve_url`; `run_feed` calls it as an injected I/O fallback (wired only
  in `run.py`). Recovers the server-side-embed subset; JS-injected embeds return None and
  stay recorded on the unresolved board. Recon deferred the other two Tier-2 sources:
  iCIMS is bot-walled ("Human Verification") and ByteDance/TikTok exposes no clean API
  (JD only in fragile Next.js flight data) — both need a headless browser, so they're
  left recorded, not built.
- **Detail-fetch robustness (prep for Tier-2 scrapers).** Silently-broken scrapers are
  now made visible: a fetched detail posting is validated (non-empty
  `external_id`/`job_title`/`description`) before it counts, and any failed surfaced id
  (a raise, a `None`, or an invalid posting) is recorded in `feed_unresolved` as
  `detail_fetch_failed` — appearing on the existing unresolved board, grouped by host —
  instead of vanishing into `run_feed`'s swallowed per-listing exception. A detail source
  that resolves ids but keeps none also prints a one-line collapse warning. Source-agnostic
  (lives in `pipeline.run_feed`/`_detail_fetch`); no adapter changes, no schema change.
  Canary self-tests and proactive Telegram/banner alerting are deferred.
- **Feed coverage Tier 1 — Oracle / Workable / Jobvite + Greenhouse-EU host.** Lifts feed
  resolution from ~⅔ to ~78% of the filtered-active feed (measured against the live
  `listings.json`: 460 → ~300 unresolved). New: a **per-listing detail-fetch path** in
  `run_feed` (a source exposes `fetch_one` and is listed in `fetch.DETAIL_SOURCES`) for
  boards with no public list endpoint, alongside the existing per-board list adapters.
  Adapters: **Oracle Cloud HCM** (`recruitingCEJobRequisitionDetails`, +116, feed-only),
  **Jobvite** (schema.org JSON-LD, +14, feed-only), and **Workable** (widget list API,
  +7, watchlist-capable → added to `VALID_SOURCES`). One-line **Greenhouse EU host**
  (`job-boards.eu.greenhouse.io`) fix (+23). Feed-only sources can't be enumerated as a
  watchlist company, so they stay out of `VALID_SOURCES` and are excluded from promotion
  suggestions. Deferred (fragile scraping): iCIMS, embedded greenhouse, ByteDance/TikTok.
  Added a source coverage matrix to SPEC §7.1.
- **Feed coverage expansion + promotion suggestions + unresolved viewer.** Building on
  the discovery feed: (1) **Workday** feed resolution (the feed exposes the per-tenant
  `jobReqId`, matched as a substring of the board's `externalUrl` since the adapter keys
  on the GUID) and a new **SmartRecruiters** board adapter (two-step list+detail), lifting
  feed coverage from ~⅓ to ~⅔ of the filtered-active feed; (2) **promotion suggestions** —
  non-watchlisted companies whose feed-discovered postings repeatedly pass threshold
  (`tailored`/`notified`/`applied`) or get applied to are surfaced in the Watchlist tab
  with **Approve** (→ add to watchlist) / **Dismiss** (→ `promotion_dismissed`); (3) a
  read-only **Unresolved** tab grouping the `feed_unresolved` backlog by host + reason.
  Postings now carry a `company_slug` (set at ingest) so promotion grouping needs no URL
  re-parsing. Sources supported: six (added `smartrecruiters`).
- **Discovery feed (SimplifyJobs) + DB-backed watchlist.** A new opt-in feed path
  ingests the SimplifyJobs `New-Grad-Positions/listings.json` (a public GitHub data
  file, *not* a scraped board): it pre-filters cheaply on the feed's own metadata
  (`active`, `category` keep-list, explicit-no-`sponsorship`), resolves each apply
  URL back to its board `(source, slug, external_id)`, and **reuses the existing
  board adapters** to fetch the JD — keeping only the feed-surfaced postings so the
  score/tailor/notify pipeline runs unchanged. v1 resolves
  `lever`/`ashby`/`greenhouse`-direct (~⅓ of the filtered-active feed); the rest
  (Workday, SmartRecruiters, embedded-greenhouse, other ATSes) is recorded in a new
  `feed_unresolved` table as a prioritised backlog, never silently dropped. New
  worker package `ats_worker/feed/` (`simplify`/`prefilter`/`resolve`), pipeline
  stage `run_feed`, and an optional `feeds:` config block. (SPEC §5–§9.)
- **Watchlist moved into the database** (`watched_companies`) and is now managed in
  a new **Watchlist** tab in the web app (list / add / remove). The worker reads its
  watchlist from the DB and **auto-seeds it once** from `config.yaml`'s `companies:`
  when the table is empty (`--import-companies` forces a re-seed); `companies:` is
  now a one-time seed rather than the live source.
- Two more board adapters — **Workday** (CXS list + per-job detail; the `slug`
  packs `tenant/datacenter/site`) and **Pinpoint** — bringing supported sources
  to five.
- **Hard-constraint candidate screening**: an optional `candidate` block in
  `config.yaml` (years of experience, degree, work authorization, security
  clearance, locations, plus freeform dealbreakers). The local scorer screens each
  posting *semantically* and auto-discards conflicting roles, keeping the reason and
  per-requirement verdicts for the UI; a **Reopen** action reverses a discard.
- Integration test tiers (worker `run_once` over a temp SQLite; web Server Actions
  over a real throwaway Prisma DB) and a **Playwright** end-to-end suite.
- **Container self-healing for the WSL2 stale-bind-mount failure.** A new `GET
  /api/health` route opens the DB (`SELECT 1`) behind a Docker `healthcheck`, and an
  **`autoheal`** sidecar restarts `ats-web` whenever Docker marks it unhealthy —
  recovering from the `SQLITE_CANTOPEN` (Error code 14) a stale bind mount causes
  after the WSL2 VM suspends/resumes. (SPEC §6.)
- **`make seed-dev`** (`apps/web/prisma/seed-dev.mjs`) — appends a realistic spread
  of sample applications (varied statuses, categories, dates, and `status_history`
  trails) to the local DB for populating the dashboard. Unlike the e2e fixture it
  **never clears** existing rows, so it is safe to run against a DB holding real
  worker `job_postings`.
- **Auto-retry of `failed` postings, attempts-capped.** A new pipeline stage
  `run_retry` (`ats_worker/pipeline.py`, run before `run_score`) requeues every
  `failed` row back to `new` while its cumulative `attempts` — a single counter
  shared across score **and** notify failures — stays under `RETRY_MAX_ATTEMPTS`
  (3, mirroring `NOTIFY_MAX_ATTEMPTS`): one bulk `db.requeue_failed` UPDATE, no
  per-item loop needed. A requeued row re-runs the full screen+fit this same pass;
  a row already parked by `run_notify`'s exhausted retries reads `attempts >= 3`
  and never requeues, so `failed` stays terminal for that path. Persistent
  failures requeue-fail-repark each pass until the 3rd cumulative failure parks
  the row for good — a hard ceiling of 3 total failures per row. `db.save_score`
  now also clears `pipeline_error` on a successful (re-)score, so a recovering
  row doesn't carry a stale error string (mirrors `mark_notified`'s existing
  clear on the notify side).
- **Community health files.** `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1,
  reports via this repo's issue tracker — no personal contact info), `SECURITY.md`
  (single-user/loopback threat model, GitHub Security Advisories reporting flow,
  and the accepted-risk list: `next`/bundled `postcss` advisories pending the
  `next@16` major, plus pointers to the `autoheal` Docker-socket and SSRF-guard
  items already tracked in `PROGRESS.md`), and `.github/ISSUE_TEMPLATE/`
  (`bug_report.md`, `feature_request.md`).


### Changed

- **Worker config rejects unknown keys instead of silently ignoring them.**
  `load_config` now fails loud on any unrecognised top-level or `candidate` key
  (allowed keys are derived from the dataclass fields, so the guard can't drift from
  the schema). Previously a stale or mistyped field — notably the retired `threshold`
  and the never-read `candidate.years_experience` — was accepted and quietly did
  nothing, so tuning it changed no behaviour. The shipped `config.yaml` dropped both
  dead keys. Mirrors the existing `filters` migration guard.
- **Phenom boards skip the detail fetch for postings the deterministic gates already
  reject.** `phenom` is a two-step adapter — a paged search, then ONE detail GET per
  position for the description — and every filter used to run *after* the whole board
  was hydrated. The search stub already carries the title and location, which is
  everything `title_filter` / `title_exclude` / `max_age_days` and the intern/location
  gates read, so `run_fetch` now hands `phenom.fetch` a `keep` predicate that decides
  from the stub: a title/age miss is dropped, an intern/location miss is recorded
  un-hydrated, and only survivors cost a detail GET. Measured on the live Microsoft
  board (1,580 postings): **1,580 → ~458 detail GETs, −71%**. Statuses and
  `score_detail` are unchanged; a stub-gated discard simply has an empty
  `description` (and `ON CONFLICT DO NOTHING` means it is never back-filled). The
  predicate fails open — any unrecognised verdict hydrates. Other adapters are
  untouched; `workday` is deliberately not gated (its list stub carries no GUID).

  **Decided against, in the same pass** (recorded here so neither is re-proposed;
  full numbers and rejected alternatives in
  `docs/superpowers/specs/2026-07-21-stub-gate-design.md`):
  - **Per-board fetch settings.** Phase 2 was originally specced as per-board
    keep-rules — a `filters` JSON column on `watched_companies` plus a Watchlist
    editor. Measurement killed it: the only board large enough to matter is
    Microsoft/`phenom` (1,580 postings), its cost is the per-position detail GET,
    and stub-gating cuts that to ~458 using the *existing* global filters. The
    source-side params the column would have carried reach only 369 — for a schema
    column, a UI editor and `onboard-board` capture. Reopen only if a board appears
    that stub-gating can't tame.
  - **`max_age_days` stays `0`.** 13 of the 39 postings ever notified are >365 days
    old, including the four highest scorers (93 @ 416d, 91 @ 448d, 85 @ 545d, 85 @
    400d): these boards run evergreen requisitions and `posted_at` is
    first-published, not freshness. `max_age_days: 30` would have kept 7 of 39
    matches. Genuinely dead postings are a liveness problem, not an age one — see
    the Dead-link sweep item in [`docs/PROGRESS.md`](./docs/PROGRESS.md). (The one
    true zombie found, an Ansatz row dated 2016-05-25 that still scored 80, is a
    `lever` posting — a board source, precisely the case `run_expire` does not yet
    cover.)

- **`Dashboard.tsx`'s refresh after a mutation now has two tiers instead of one.**
  `refreshData()` fired 5 server actions on every mutation — `getApplications` +
  `getKPIs` + `getStatusFlow` + `getTimelineData` + `getCategoryData` (4 of them
  full-table `findMany` + in-JS aggregation) — even for a plain status change, which
  can't move `date_applied` or `category` and so can't affect the timeline/category
  charts. A new light tier, `refreshStatusData()` (apps + KPIs + status flow), is
  composed as the shared core; `refreshData()` is now that core plus the
  timeline/category fetch. `handleStatusChange`/`handleAddStatus`/`handleDeleteHistory`
  (status/history-only mutations) call the light tier; `handleAddApplication`/
  `handleDeleteApplication`/`handleEditApplication`/`handleImportCSV`/
  `handleConfirmApply` (which can change dates/categories/row count) keep the full tier.
- Worker pure modules no longer bind real network callables as defaults (wired only in run.py).
- **Domain verdict redesigned from "background" to "target-fit" (`prompts/score.txt`).**
  The old one-line domain prompt ("is their background in this role's domain?") had no
  criteria for `adjacent`, so the verdict was a vibe that drifted (a coin-flip on the
  golden set's borderline rows and the dimension that bled under batching). It is now a
  deterministic collapse of **three checks** recorded in the note — (1) ANTI-TARGETS,
  (2) which TARGET priority (from the role's day-to-day work, not its title), (3) whether
  the RÉSUMÉ evidences the field — against the operator's `personal_profile.txt`. This
  keeps the single `domain` enum (no schema change) but makes the match/adjacent line —
  which the notify predicate turns on — a checkable rule instead of a judgment call.
  **The fit-score verdict-accuracy gate (`make eval-score`, K=3 × 21 rows) PASSES at
  100% agreement / hard 10/10 / 5% flip** under the redesigned rubric (2026-07-17,
  `gpt-5.6-sol`). Flip-rate collapsed from 24–38% (pre-redesign) to 5%. The golden set
  and profile that validate it are operator-local (gitignored), so the committed artifact
  is the rubric; the eval's validity is tied to the local profile + golden labels.
  - **The "analyst penalty" was a profile tension, not a rubric bug.** Build-heavy
    "Analyst"/"Researcher" seats (e.g. a prop-desk Trading Analyst) scored `adjacent`
    because the model applied the profile's POSITIONING ("mostly engineering fits, mostly
    research doesn't") and read them as analysis-central — demoting them below the
    engineering-facing-analyst tier. The fix was in the **profile** (loosen the tier-3
    analyst qualifier to include seats with substantial tooling/pipeline building even if
    analysis-central), not the prompt: a prompt tweak that tried to force it (deliverable-
    based check) backfired — it destabilized an ambiguous row into a false-notify and
    over-corrected another. Same defect, opposite outcomes: fixing the profile *stabilized*
    the ambiguous row (100% agreement), fixing the rubric destabilized it.
- **Docs corrected for the native worker** (OLLAMA_HOST default → localhost:11434; dropped
  stale host.docker.internal/extra_hosts notes; refreshed CI requirements-dev comment).
  The worker is native (not containerized), so all references to `host.docker.internal`
  have been updated to `localhost:11434` in `.env.example`, `CLAUDE.md` (Gotchas),
  `docs/SPEC.md` (§6 + setup steps), and the CI comment now accurately lists the actual
  requirements-dev dependencies (beautifulsoup4, pycountry, pytest, pytest-cov, requests, PyYAML).
- Misc low-arch cleanups: align web Dockerfile UID/GID to the compose default, point add_watched
  DEFAULT_DB at db/applications.db, scope the CI cron, align removeAllInView's where with the
  visible bucket.
- **Worker `ats_worker/score.py` (1089 ln god-module) split into an `ats_worker/score/` package**
  — behavior-preserving, no signature changes. Concerns separated into `usage.py` (codex quota
  telemetry), `location.py` (deterministic location gazetteer/gate), `errors.py` (`ScoreError`),
  `prompts.py` (prompt + schema assembly), `backends_claude.py` / `backends_codex.py` (the two
  fit-scoring backends), and `screen.py` (screen rules, normalization, and the `screen_posting`
  composition). `score/__init__.py` is now a ~40-line pure re-export shim (plus `import subprocess`,
  kept as the tests' monkeypatch lifeline) so every existing `score.<name>` caller (tests,
  `pipeline.py`, `run.py`, `tools/score_eval.py`) is unaffected.
- **`Dashboard.tsx` (720-line god client component) split into per-tab components** —
  behavior-preserving, render tree unchanged. The four tab bodies now live in
  `ApplicationsTab.tsx`, `DiscoveredJobsTab.tsx`, `WatchlistTab.tsx`, and
  `UnresolvedTab.tsx`, each taking the tab's slice of state as props; `Dashboard.tsx`
  is now a thin shell holding the header/KPI grid, the tab-toggle bar, all state +
  handlers, and the `StatusHistoryModal`/`JobDetailModal`/`ApplyCategoryDialog` that
  span tabs.
- **`verdictClass` / `verdictLabel` / score_detail JSON parsing shared via
  `lib/score-detail.ts`** — behavior-preserving. `JobDetailModal.tsx` and
  `DiscoveredJobsTable.tsx` each hand-duplicated the verdict-chip color helper (and the
  table also had `verdictLabel`) plus an inline `try/JSON.parse/catch` guard; both now
  import the shared helpers and route their own `parseScoreDetail`/`parseDetail`
  view-model shaping through `safeParseDetail`. The two components' distinct view-models
  are unchanged — only the genuinely-duplicated leaf helpers moved.
- **Three near-identical list→detail adapter loops (`workday`, `smartrecruiters`,
  `phenom`) now share `fetch/_paged.paged_details`** — behavior-preserving. The
  shared helper owns `http = session or requests`, the page loop, the len-based
  offset advance, and termination on an empty page or a reached honest total; each
  adapter supplies only its list-page call (+ total key — `total` / `totalFound` /
  `count`) and its per-row detail-fetch + failure policy via `fetch_page`/`build_row`.
  `workday` and `smartrecruiters` still skip a posting outright on a failed detail
  call; `phenom` still uniquely **keeps** it with an empty description (its `_row`
  catches the detail-fetch exception and falls through to `parse_position(...)`
  rather than returning `None`) — the adapters' distinct failure policies are
  unchanged, only the duplicated loop scaffolding moved. **`smartrecruiters`' page-offset
  advance changed from a fixed page-stride (`offset += PAGE`) to rows-returned
  (`+= len(items)`)**, matching `workday` and `phenom` (which already advanced by
  rows-returned before this refactor) — so a short non-final SmartRecruiters page no
  longer silently skips postings. This is the one real behavior delta in the migration
  set: a latent correctness gain, and behavior-identical on all current fixtures (no
  fixture exercises a short non-final page).

- **Notify and the web matched/belowbar buckets now route on the fit verdicts, not
  the score.** The `>=75` notify threshold sat exactly on the rubric's band-edge
  quantization point — score flip-rate 29–38% across two codex configs (see
  `PROGRESS.md`) — while the `seniority`/`domain` enum verdicts held 100% stable
  across every re-draw. Both sides now gate on one predicate: `seniority.verdict ==
  "match" AND domain.verdict == "match" AND NOT insufficient_context`. **Worker:**
  `db.get_notifiable(conn)` selects `pipeline_status='scored'` rows matching the
  predicate via `json_extract`; `run_notify` drops its `threshold` parameter and no
  longer calls `db.get_by_status(..., min_score=)` for gating. **Web:** a new
  `matchedIds()` raw-query helper (mirrors `lowContextIds()`) returns the matching
  ids; `matched` = active (`scored`|`notified`) ∩ `matchedIds()`, `belowbar` = active
  ∖ `matchedIds()` — the same predicate the worker uses, so the UI and the Telegram
  alert can never disagree. `MATCH_SCORE_THRESHOLD` is **removed** from
  `apps/web/src/lib/constants.ts` (zero remaining references). The fit **score is now
  display/ranking only** — it gates nothing. `config.yaml`'s `threshold:` key and the
  worker's `cfg.threshold` are now **inert** (parsed but unread; left in place for a
  later cleanup). Design:
  `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`
  (Part A; the eval-harness verdict-accuracy reframe is Part C, below — Part B
  batched fit scoring shipped separately, see below).
- **`make eval-score` gates on verdict accuracy, not score-band regression.** Follows
  the routing cutover above: since notify/matched no longer read the score, the harness
  stops judging whether the score reproduces a keep/near/skip band and instead judges
  the thing routing now depends on — the per-dimension `seniority`/`domain` verdicts.
  The golden set (`apps/worker/eval/golden.jsonl`, gitignored) is relabeled with
  ground-truth `seniority` (match/too_junior/too_senior) and `domain`
  (match/adjacent/mismatch) verdicts on every row. `tools/score_eval.py` scores each row
  K=3×, takes the majority verdict per dimension, and PASSes iff: 0 hard-invariant
  violations (a `hard`+`skip` golden row must never come back `seniority==match AND
  domain==match`) **AND** ≥85% per-dimension verdict agreement **AND** <20% verdict
  flip-rate across the K draws — all over the gate-eligible (non-`marked`) rows. The
  derived `match`/`match` notify decision is still reported per row for visibility but
  is **not** the gate, so the accepted recall loss (adjacent-domain keeps) can't fail
  it. Design: `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`
  (Part C), superseding the score→band design in
  `docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md`.
- **Discovered-Jobs bucket taxonomy split + table redesign.** The old `discarded`
  bucket conflated two very different things — hard disqualifications *and*
  below-threshold scored rows — behind a `discardType` (nearmiss/disqualified/all)
  sub-filter. Split into clean, mutually-exclusive buckets: `JobBucket` is now
  **matched · belowbar · discarded · failed · lowcontext**. **belowbar** = live
  (`scored`|`notified`) rows with `score < MATCH_SCORE_THRESHOLD` — *all* of them,
  including deep misses far below the bar, so nothing scored is orphaned;
  **discarded** = disqualified **only** (`pipeline_status='discarded'` with the screen's
  `disqualified:true`) — a below-bar scored row no longer lands here. The old
  `DiscardType` sub-filter is replaced by a disqualification-**cause** filter
  (`DisqualifyCause` ∈ authorization/location/degree/clearance/internship), implemented —
  like `lowContextIds` — as a raw-query id set matching the worker's keyed
  `disqualification_reason` via `json_extract(...) LIKE` the cause pattern, layered as
  `id IN` on the discarded query (and `removeAllInView`). `getJobPostings` /
  `removeAllInView` take `cause?` instead of `discardType?`, and `getJobPostings` now
  returns each row's `created_at` + `posted_at`. `NEAR_MISS_FLOOR` is kept only as a
  documented score-band marker (no longer a query boundary). **Table redesign**
  (`DiscoveredJobsTable`): the bucket tabs (Matched · Below bar · Discarded · Failed ·
  Low-context) moved to their **own row** above the filters; columns folded to Company
  (name + location + source chip) · Role (title + a bucket-aware "why" subline — below-bar
  seniority/domain **verdict pills** (too_junior / adjacent / mismatch, color-coded) + the
  top missing must-have, falling back to the legacy one-line `reasoning` for pre-S2.1 rows;
  the disqualification reason; thin-JD char count; or the pipeline error) · Score (with the
  `recommended_resume` label — SWE / Quant Dev — beneath it) · Dates (Posted / Fetched) ·
  Actions; the cause dropdown replaces the discard-type Select. The per-row dismiss now
  writes `removed` (hidden, like bulk Remove) instead of `discarded`, so the
  disqualified-only Discarded bucket can't be polluted by a hand-dismissed row. Reuses
  existing shadcn/ui tokens and the modal's verdict-pill palette (no new colors).
  Covered by updated unit (`actions.test.ts`), integration (`actions.int.test.ts` —
  belowbar bucket, discarded = disqualified-only, cause filter, created_at/posted_at) and
  component (`DiscoveredJobsTable.test.tsx` — Below-bar tab, cause dropdown, why-cell,
  dates) tests.
- **Round-2 fit-score prompt** (`score.txt`, `0de0068`). Four refinements to how the score
  is reasoned: crisp / de-duplicated `missing` must-haves; `seniority` keyed to an *explicit
  stated level* only (a range starting at 0–1 or a cap is not a bar); credit a capability the
  résumé demonstrates under a different name; never list a requirement structurally impossible
  for the role's own target candidate. Shipped on judgment — the band-regression harness read a
  24% flip-rate that analysis traced to score *noise* (all majority keep/near/skip bands were
  correct), not a prompt fault; the harness stays as the standing regression gate for future
  prompt edits.

- **Fit score reasoning redesigned into a structured `assessment` scorecard (S2.1;
  closes D3 + D4).** The Claude fit call now emits an `assessment` object — enum-
  constrained `seniority`/`domain` verdicts + notes, split `must_haves` {met, missing} /
  `nice_to_haves` {missing}, and a one-line `summary` — replacing the flat
  `matched_keywords`/`missing_keywords` lists and the prose `reasoning` blob in
  `score_detail`. The prompt scores from those verdicts: a material seniority gap floors
  the score at 0–30 (**D3** — a new grad no longer earns a mid score on a 3+-year role,
  e.g. id=904/177), and missing `nice_to_haves` barely move it (**D4** — a missing "plus"
  like C++ no longer tanks a strong core fit, e.g. id=427). `JobDetailModal` renders the
  scorecard (verdict chips, must/nice-have chips, summary) with the legacy
  matched/missing/reasoning path kept as a fallback for old rows; discarded rows carry no
  assessment. No DB migration (old rows keep their shape). Design:
  `docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md` §S2.1.

- **Location screen is now a deterministic code gate off the board field, not the 4B
  model.** The screen asked qwen3.5:4b to extract `{city,region,country}` from the JD
  and matched that; the 4B intermittently missed obvious foreign locations (a live run
  kept an on-site `Shanghai, China` role) and err-toward-keep leaked them to the paid
  Claude score. Location now resolves in code (`resolve_location`, `pycountry`) against
  `posting["location"]`: foreign roles that carry a country token are discarded before
  scoring; US-state-only and remote strings keep; ambiguous/missing keeps. Location left
  the LLM screen entirely (a `locations`-only candidate makes no Ollama call), and the
  scoring prompt split into `prompts/score.txt` + `prompts/screen.txt`. New dep:
  `pycountry`. (SPEC §5, §7.)
- **Scoring: the hard-requirements SCREEN now runs first and gates the Claude fit
  score.** `score_posting` previously called Claude on every posting and only *then*
  ran the local screen, so a posting bound for `discarded` (foreign on-site role,
  internship, missing-clearance, …) still paid for a Sonnet fit call. The order is now
  screen → gate → score: a disqualified posting records `score` 0 and **skips the paid
  Claude call entirely**; only postings that pass the screen are fit-scored. No change
  to screen logic or the score for surviving postings; disqualified rows still carry
  the per-requirement screen verdict + reason. Worker suite green (315). (SPEC §5, §7.)
- **Scoring: fit assessed by Claude Sonnet 5 (reason-first) instead of the local
  4B model; removed the fragile local years/seniority screen gate.** The
  hard-requirements screen (degree, work authorization, clearance, locations,
  dealbreakers, internships) stays on local Ollama, with code applying the
  candidate's configured constraints; only the fit SCORE moved to Claude, via a
  cached résumé+rubric system prefix, adaptive thinking, and schema-constrained
  JSON output (`reasoning` before `score`). New `ANTHROPIC_SCORE_MODEL` /
  `--anthropic-score-model` (default `claude-sonnet-5` — structured outputs
  require it; `claude-sonnet-4-6` doesn't support `output_config.format`),
  reusing `ANTHROPIC_API_KEY`. The now-inert `candidate.years_experience` config
  field was dropped (nothing screens on it anymore). (SPEC §3, §7.1, §10.)
- **Repo-wide over-engineering cleanup (behavior-preserving).** Removed dead code
  (worker `db.discard`/`db.mark_applied` + their tests, the `_row_to_dict` helper —
  `dict(row)` covers it, an unreachable `load_config` bytes branch, and the never-read
  `run_score`/`run_tailor` params) and unused web exports (`TERMINAL_STATUSES`, the
  `Status`/`Category`/`Source` type aliases). Dropped four web dependencies:
  `date-fns` + `date-fns-tz` (zero imports) and the redundant *direct* declarations of
  `playwright` + `@testing-library/dom` (kept transitively via `@playwright/test` and
  `@testing-library/react`). Deduped three duplicated types (components now `import type`
  them from their server-action modules), shared one `StageRow` renderer across
  `StatusFunnel`'s two groups, reused `<Pagination>` in `ApplicationTable`, and tidied a
  few test helpers. No capability change; worker + web suites and the coverage gate stay
  green. (Several audit findings were deliberately *not* applied — see commit history.)
- **Discovered Jobs UX: full pagination, debug filters, per-row reason, apply-time
  category.** (1) A proper paginator (first/last, numbered pages with ellipsis,
  go-to-page) replaces the bare Prev/Next (`components/Pagination.tsx`, reused by the
  Discovered table). (2) New filters for review/debug: a **Min score** input (all
  buckets) and, in the Discarded bucket, a **type** filter (All / Disqualified /
  Low score) — `getJobPostings` gains `minScore` + `discardType`. (3) Each discarded
  row shows its reason inline (red `✕ <disqualification reason>`, amber `low score`,
  or `discarded manually`) so you don't open each one. (4) **Mark Applied** now opens
  a category picker (`ApplyCategoryDialog`); `markJobApplied(id, category)` records the
  chosen category instead of always `Others`. (SPEC §7.2, §9.)
- **Discovered Jobs collapsed to three score-aware buckets + pagination.** While
  scoring is the focus, the per-status (`queue/all/scored/tailored/…`) and min-score
  dropdowns were too granular. The table now has three buckets: **Matched** (live +
  score ≥ `MATCH_SCORE_THRESHOLD`, default 75 — mirrors the worker's tailoring
  threshold), **Discarded** (explicitly discarded *or* live-but-below-threshold), and
  **Failed** (pipeline failures, for monitoring). `getJobPostings` now takes a
  `bucket` instead of `status`/`minScore` and is **paginated** (`page`/`size`, default
  25) — previously it loaded every row into one page, which could exhaust browser
  memory. (SPEC §7.2, §9.)
- **Experience screen is now strict — but only on a *hard-required* minimum.** A role
  whose hard-required minimum exceeds the candidate's years is screened out (was: only
  when ≥4 years beyond). With 1 YoE, "2-3"/"2-5 years" *required* roles (lower-bound 2)
  are now disqualified; "0-2"/"1-3" still pass. To avoid false-discards on early-career
  roles, the extraction prompt now reports `null` when the years are merely *preferred*
  / "a plus" / "or equivalent", or are a **cap** ("no more than 3 years", early-career)
  rather than a floor; and a deterministic keep-guard never discards on years when the
  JD welcomes early-career candidates (new grads / entry-level / "graduates will be
  considered"). The senior-title check is not relaxed by the guard.
  (`score._check_experience` + `_EARLY_CAREER_HINTS`, `prompts/score.txt`; SPEC §7.1.)
- **Feed performance: a full pass dropped from ~tens of minutes to ~1 minute.** Profiling
  showed the feed was network-bound and dominated by N+1 boards. Two fixes: (1) the feed
  now fetches **SmartRecruiters and Workday per surfaced job** (their new `fetch_one`)
  instead of listing the whole board — a 1500-posting SmartRecruiters board cost ~11 min
  of per-job detail calls just to keep the 1–2 jobs the feed wanted. Workday's per-job id
  is the job's `externalPath` (the CXS per-job endpoint), which also resolves Workday URLs
  the old `jobReqId`-suffix parsing rejected (a small coverage gain; the watchlist still
  lists the whole board). (2) `run_feed` now fetches **concurrently** — a `ThreadPoolExecutor`
  fans out the embedded-greenhouse I/O resolves and the per-group fetches, with all SQLite
  reads/writes kept on the main thread; `run.py` gives each worker thread its own
  `requests.Session` (keep-alive) and a shorter timeout. Measured: a fresh full feed pass
  went from ~47 min to ~47 s.

- Default scoring model is now **`qwen3.5:4b`** (local Ollama) and default
  resume-tailoring model is **Claude `claude-sonnet-4-6`** — both overridable via
  CLI flag or env var.
- The repo ships only `*.example` templates; the real resume, `config.yaml`, and
  secrets stay gitignored.
- CI now gates coverage on both suites, runs a schema-drift guard (worker SQL
  fixture vs. `prisma/schema.prisma`), and runs a gated Playwright e2e job.


### Removed

- **Mobile/responsive layout — the tracker UI is now desktop-only.** Collapsed the
  `sm:`/`lg:`/`md:` breakpoint pairs to their desktop value across the app
  (`ApplicationsTab`'s form/table + charts grids, the `ApplicationTable` /
  `DiscoveredJobsTable` / `Pagination` / `WatchlistTable` toolbars, and the vendored
  `ui/` dialog/input/textarea primitives), so nothing stacks or reflows below
  ~640/1024px anymore. This is a self-hosted, single-operator tool; the mobile layout
  wasn't earning its upkeep. Also drops the README feature-status row, the SPEC §11
  "Responsive UI" bullet, and the orphaned `docs/images/mobile.png`.

- **`tools/seed_db.mjs` deleted (superseded by `prisma/seed-dev.mjs` + `e2e/helpers/seed.mjs`).**
  Never invoked; both seeders satisfy all paths (Make, e2e, CI).
- **`SankeyChart.getNodeColumn` unused `allNodes` param dropped.** The parameter was passed
  at the call site but never read in the function body.
- Debris swept: unused `simplify.SOURCE`, dead `"remote"` token in `_flag`, orphaned
  `test:all` npm script, and 4 stale `.gitignore` entries.

- **`threshold` config key removed.** Parsed, validated, and documented in `config.py` + `config.yaml.example`, but never read in production — the notify predicate gates on verdict fields instead. Removed from the Config dataclass, YAML loader, and all tests.
- **`db.get_by_status` `min_score`/`limit` kwargs removed.** Test-only; sole prod caller passes neither.

- **`dealbreakers` from the candidate screen config.** It was the *only* screen
  requirement the local 4B model actually **adjudicated** (a free-text `{pass, note}`
  judgment); every other screen gate — degree, work authorization, clearance, location,
  internships — is decided by **deterministic code**, with the model only *extracting* a
  JOB fact for degree/clearance. Dropping it makes every screen *decision* deterministic.
  Removed the `Candidate.dealbreakers` field + parsing, the `_candidate_block` clause, the
  `_screen_verdict` gate + `_passed` helper, the `SCORE_C_DEALBREAKERS` prompt fragment,
  `screen.txt`'s `c_dealbreakers` section, and the `config.yaml` key. The misleading
  `Candidate` docstring (which claimed the model gives each field a pass/fail verdict) is
  corrected to match the code: `config.Candidate` serves the **screen only** — the Claude
  fit score reads the résumé + profile, never the config.
- **Worker `Dockerfile` + `.dockerignore` deleted.** De-containerized 2026-07-16;
  nothing built them.

- **Résumé tailoring removed — the pipeline now ends at score → notify.** Dropped the
  Claude+tectonic per-posting tailoring stage entirely: the state machine collapses
  `new → scored → tailored → notified` to `new → scored → notified`, and the score
  threshold (75) that used to gate tailoring now gates the Telegram alert. Telegram
  sends a message-only alert (company / role / score / link); the user applies by hand.
  - **Worker:** deleted `tailor.py` + `prompts/tailor.txt`; removed `run_tailor`,
    `db.save_resume`, the tailor wiring/flags (`--anthropic-model`, `--master-tex`,
    `--resume-dir`) and `max_single_page_rounds`. `run_notify` now processes
    `scored ≥ threshold` and `notify_posting` is a single atomic `sendMessage`. Dropped
    the `pypdf` dependency and the `tectonic` install (+ bundle prewarm) from the worker
    image. Fit-score `matched_keywords`/`missing_keywords` are **kept** — they still feed
    the Discovered-Jobs match analysis.
  - **Web + shared schema:** dropped `resume_tex`/`resume_path`/`resume_pages` and the
    `tailored` pipeline status from `schema.prisma` (apply with `make db-push` —
    destructive, back up `db/applications.db` first); deleted the `/api/resume/[id]` PDF
    route and the "Download Resume" UI in `DiscoveredJobsTable` / `JobDetailModal`;
    retargeted `ACTIVE_PIPELINE_STATUSES` → `{scored, notified}` and the
    promotion-traction SQL → `{notified, applied}`.
  - Worker (314) + web (137) + Playwright (4/4) suites and the coverage / schema-drift
    gates stay green. Design spec:
    `docs/superpowers/specs/2026-07-06-tailoring-removal-design.md`. (SPEC §1, §5–§13.)

- **Status-change notes field (was silently dropped).** The Update-Status form collected
  `notes` and threaded them through `updateApplicationStatus(id,status,date,notes)`, but the
  action never persisted them and `status_history` has no notes column, so users' notes
  vanished. Removed the textarea, the dead `notes` param, the history-row render branch, the
  `notes?` history type field, and the `Dashboard` call-site arg. (Application-level notes,
  edited via `updateApplicationDetails`, are unaffected.)
- **Worker `score_posting()` removed** (production-dead composer; screen/normalize unit
  assertions migrated to direct tests, coverage floor held).


### Fixed

- **Playwright e2e was red on every spec (CI-only, since the categories feature).**
  The e2e seed never wrote an `app_settings` row, so the dashboard read the throwaway
  DB as a **first run** and auto-opened the category picker; its overlay swallowed the
  first `Discovered Jobs` tab click and all 4 specs timed out (`element was detached
  from the DOM, retrying`). `e2e/helpers/seed.mjs` now seeds a stored `categories`
  row in `clear()`, so both `seed()` and `seedEmpty()` produce an already-configured
  install — which is what every spec is actually exercising.
- **Phenom `job_url` is now absolute.** `parse_position` absolutizes a relative
  `positionUrl` against the board's host (`urljoin`, a no-op on an already-absolute
  `publicUrl`) instead of storing it bare. The real captured board never sends
  `publicUrl` — every position carries only a relative `positionUrl` — so a
  stub-gated `"discard"` row (empty `description`, per the fetch-time filtering
  above) was landing with a link neither the web UI (`safeHref`'s bare `new
  URL(url)` throws on a relative path and falls back to `'#'`) nor the Telegram
  alert (`notify.py` interpolates `job_url` bare) could open — defeating the
  stub-gate's compensating control that a discarded row still has a clickable
  link. `upsert_postings`'s `ON CONFLICT DO NOTHING` meant it would never be
  back-filled either.

- **Filter-change callbacks are memoized at the source instead of frozen on the child.**
  `Dashboard.tsx`'s `handleFilterChange`/`handleJobFilterChange` got a new identity every
  render; `ApplicationTable`/`DiscoveredJobsTable` worked around it with
  `useCallback(onFilterChange, [])`, a stale-closure hack that froze the render-0 prop and
  was the repo's only 2 lint warnings (`react-hooks/exhaustive-deps`). Both Dashboard
  handlers are now `useCallback`-wrapped with honest (empty) dep arrays — they only call
  stable setters and a server action with explicit args — and the tables' debounce effects
  depend on `onFilterChange` directly. Lint is clean (0 warnings).
- **Playwright e2e harness now boots: the schema push moved into the `webServer`
  command, ahead of the server, instead of `globalSetup`.** `make test-e2e` failed
  locally before any test ran (180s webServer timeout), and CI's `e2e` job failed the
  same way (webServer spamming `PrismaClientKnownRequestError`). Root cause: Playwright
  starts `webServer` — a plugin "setup" task — *before* `globalSetup` runs, so the
  `next start` server was booting against the throwaway SQLite before
  `e2e/global-setup.ts`'s `prisma db push` ever ran; every request 500'd with
  `P2021: table does not exist` and the url-poll never saw success. The prior diagnosis
  (`docs/PROGRESS.md`) blamed an unmigrated DB and a `next start`/`output: standalone`
  incompatibility — the DB-not-migrated part was right for the wrong reason (ordering,
  not a missing call), and `next start` in fact serves fine on standalone builds
  (prints a compatibility warning, live-tested 200 on `/api/health`) so the server was
  left as-is. `playwright.config.ts`'s `webServer.command` now chains
  `npm run build && npx prisma db push --skip-generate --accept-data-loss && npm run
  start -- -p 3100`, and the now-redundant `e2e/global-setup.ts` is deleted (per-spec
  seeding via `e2e/helpers/seed.mjs` was already independent of it). Fixing the boot
  order surfaced a second, independently pre-existing defect: `e2e/helpers/seed.mjs`'s
  `POSTINGS` fixtures predated the 2026-07-16 verdict-routing change
  (`matchedIds()`/`get_notifiable` now key the Matched bucket and notify gate on
  `score_detail.assessment.{seniority,domain}.verdict === 'match'`, not score) and the
  2026-07-14 S2.1 assessment scorecard, so Acme/Globex never landed in Matched (empty
  bucket) regardless of the harness fix, and their JD-modal descriptions were under the
  200-char low-context floor. Seeded a real `assessment` scorecard shape (mirroring the
  worker's `_score_detail`/`_assessment`) with match/match verdicts and >=200-char
  descriptions for Acme/Globex, moved Initech to `pipeline_status: 'discarded'` with a
  `disqualified` reason so it lands in the literal Discarded bucket (a below-bar scored
  row lands in Below bar instead), and updated `discovered.spec.ts`'s JD-modal toggle
  assertion ("Match details" → "Fit assessment", the scorecard-era label) and
  `discard.spec.ts`'s stale `getByTitle('Discard')` (the row action is titled "Remove").
- **CI's worker job was red on a missing `geonamescache`, hidden by a local-green/CI-red
  asymmetry.** `requirements.txt` pinned `geonamescache>=3.0.1` for the location gate
  (`score/location.py`'s lazy city→country index), but `requirements-dev.txt` — the only
  file CI's worker job installs — was never updated to match, so
  `test_foreign_location_disqualifies_from_board_string` and friends failed with
  `ModuleNotFoundError` on every push for a week (2026-07-13..19). Local runs stayed green
  throughout because the host python had the full `requirements.txt` installed, masking the
  gap. `requirements-dev.txt` now mirrors the `geonamescache` pin.
- **The nightly CI cron now runs the web (Jest) and worker (pytest) unit suites again, not
  just e2e** — restoring early warning on the worker's unpinned dev-dependency drift. Both
  jobs' `if: github.event_name != 'schedule'` guard is removed from `ci.yml`.
- **`feed_unresolved` rows are now cleared when the posting they reference is
  successfully (re-)ingested**, so a transient board failure no longer leaves
  permanent stale entries in the Unresolved backlog. (New `db.delete_unresolved`,
  called from `run_feed`'s write loop.)
- **`.env` now feeds the argparse defaults.** `SCORE_BACKEND` / `OLLAMA_MODEL` / `DB_PATH`
  / `CODEX_*` set in `.env` were silently ignored — `load_env()` ran after `parse_args`
  and its dict was never merged into `os.environ`. `main()` now loads `.env` and
  `setdefault`-merges it before the parser is built, so a real env var still wins and an
  explicit CLI flag still overrides.
- **`run_fetch` now logs a skipped company.** A failing board was swallowed by a bare
  `except: continue` despite the "logged-and-skipped" docstring; it now prints
  `[fetch] <source>/<slug>: skipped after error: <exc>`, matching `run_notify`.
- **Toasts now follow the system theme.** `<Toaster>` was hardcoded `theme="dark"` while
  `ThemeProvider` is `enableSystem`; it is now `theme="system"`, so toasts track
  `prefers-color-scheme` like the rest of the UI. (No manual theme toggle exists.)
- **CI now runs on `dev` pushes, not just `master`.** All development lands on the
  long-lived `dev` branch (master stays far behind by design), so routine commits were
  getting zero CI and the gated e2e job never fired. `ci.yml` push trigger is now
  `[master, dev]`.
- **`run_score` batch persist no longer trusts `len(cards) == len(chunk)`.** A fit
  backend returning fewer/more cards than postings without raising would have
  zip-misaligned in `pipeline.run_score` and silently orphaned the tail rows (stuck
  `new`, re-scored every pass). A `len(cards) != len(postings)` check now routes the
  chunk into the existing singles fallback, so every posting is scored 1:1. Latent
  today (codex raises on a missing `job_ref`; claude loops one-per-posting), hardened
  from the 2026-07-17 scoring-system audit.
- **Notify gate now mirrors the web "Matched" tab on thin JDs.** `db.get_notifiable`
  gained `AND LENGTH(TRIM(description)) >= 200`, so a short (<200-char) `match/match` JD the
  model did not flag `insufficient_context` no longer fires a Telegram alert while the web
  hides it under Low-context — the two now agree. Surfaced by the 2026-07-17 scoring-system
  audit (SPEC §9 corrected). The `200` is hand-synced with the web
  `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH` (a cross-service constant, flagged in both).
- **A malformed `recipe` in one watchlist row no longer aborts the whole pass.**
  `db.get_watchlist` decoded every row's `recipe` JSON in a comprehension before any
  per-company isolation, so one corrupt row raised through the entire read (fetching
  nothing). It now guards each row, skipping + logging the bad one (SPEC §9 invariant).
- **Feed board-source fetch failures are recorded (`feed_unresolved`) instead of silently
  dropping surfaced ids.**
- **Web Prisma client's SQLite `busy_timeout` verified already sufficient — no code
  change needed.** Suspected the web client (plain `new PrismaClient()`, no explicit
  pragma) could throw `SQLITE_BUSY` on a colliding worker write-lock, unlike the
  worker's explicit `busy_timeout=5000` (`db.py:26`). A new integration test
  (`db-pragma.int.test.ts`) measured the real default and found Prisma 6's SQLite
  connector already sets `busy_timeout=5000` ms with zero configuration — the planned
  `connection_limit=1` + explicit `PRAGMA` fix was de-scoped (Ponytail) since the
  behavior it would have added already exists; the test stays as a regression lock.
- **`deleteHistoryItem` and CSV import run in transactions.**
- **`addApplication` runs in a transaction (closes create-dedupe TOCTOU).**
- **CSV import now strips the formula-injection guard apostrophe that export adds, so an
  export→import round-trip no longer corrupts fields or creates duplicates.** `csvEscape`
  prefixes a `'` to any cell whose first char is a formula lead (`= + - @`, tab, CR) so
  spreadsheets render it as text; the import's field reader never reversed that, so
  re-importing an export (the supported restore flow) stored the guard apostrophe verbatim
  and the `(company_name, job_title)` dedupe no longer matched the original row, producing a
  duplicate. `get()` now strips a single leading `'` only when followed by a formula-lead
  char OR another `'` — the exact inverse of `csvEscape`, which now also guards a cell whose
  first char is already `'` (not just the formula-lead set). Without that, a raw value like
  `"+1 Talent"` and a raw value like `"'+1 Talent"` both escaped to the same `"'+1 Talent"`,
  so the strip couldn't tell them apart and silently dropped a real leading apostrophe on
  import; the pair is now a proper bijection, so the round-trip is lossless for every value,
  including ones that already start with an apostrophe.
- **CSV import runs in 100-row transaction batches instead of one 60s transaction, so a
  large import no longer holds SQLite's write lock long enough to make a concurrent worker
  pass fail with "database is locked".** The whole import previously ran as a single
  `prisma.$transaction` with a 60s timeout, holding SQLite's WAL write lock for up to that
  long; the worker connects with a 5s `busy_timeout`, so a large import mid-pass could abort
  a scoring pass. Import is idempotent per-row (dedupe), so a chunked, interrupted import
  still leaves a consistent prefix that a re-import completes.
- **The edit-form category is now a dropdown constrained to `CATEGORIES`.** It was a
  free-text `<Input>` whose out-of-set values were silently coerced to `'Others'` by the
  server on save, losing the typed category. `StatusHistoryModal`'s edit form now uses a
  `<select>` over `CATEGORIES` (mirroring `AddApplicationForm`), so application edits no
  longer silently drop a category.
- **`run_fetch` now raises immediately when no `fetch_fn` is injected**, instead of
  swallowing the resulting `TypeError` per company and silently fetching nothing.
- **`get_watchlist` no longer drops a platform-source watchlist row (greenhouse/workday/…)
  when its `recipe` column is malformed JSON** — only recipe sources (`custom`/`browser`)
  are skipped; a platform row is kept with `recipe=None` (it fetches without one).

- **`--batched` guard counted `marked` rows, holding them to a stricter standard than
  the gate they're excluded from.** Two of its four "drift rows" (132, 184) are
  watch-list rows the K=3 accuracy gate deliberately drops — 132's own golden note reads
  *"model splits 50/50 (34 vs 70, a full band)"* — so its headline `19/23` blamed
  batching for known label noise. `marked` rows now still ride in their real batches
  (their bleed can corrupt a gate-eligible batch-mate, so removing them would weaken the
  test) but no longer decide PASS; they're reported under a separate watch-list heading.
  Gate-eligible drift is **19/21**. The guard's verdict (batching does not ship) is
  unchanged and now better-founded. Also corrected in the docs: **id 125 was never a
  batching victim** — it reads `match/match` on 3/3 *single* draws, so unbatched scoring
  notifies it too; it's a stable calibration disagreement with its `adjacent` label, not
  a batching regression.
- **Codex fit-score backend — the ChatGPT-subscription twin (`make_codex_scorer`),
  now the default.** Fit scoring moves off metered Claude onto the Codex CLI running
  on the operator's ChatGPT subscription: a full ~640-row re-score becomes a
  flat-rate pass instead of a paid one, which is what the cost of re-scoring the
  queue actually turns on. `run.make_scorer` picks the backend
  (`--score-backend`/`SCORE_BACKEND`, `codex` default | `claude`); both twins expose
  the same `score_fit(posting, resumes) -> dict` contract, send the same prompt
  sections (`_scorer_system_sections`, extracted so a prompt edit lands on both) and
  the same JSON schema (`_score_schema` → codex's `--output-schema`), so scores stay
  comparable and the band-regression harness can judge one against the other.
  Each call is one ephemeral, read-only, repo-less `codex exec` turn (`--ephemeral`
  so a 640-row pass leaves no session files; `-C <tmpdir>` + `--skip-git-repo-check`
  so the JD is the only input), with the JSON read back from `--output-last-message`.
  Auth is the operator's `codex login` state, not an env key — `ANTHROPIC_API_KEY` is
  needed only for `--score-backend claude`. A non-zero exit **always** raises
  `ScoreError` and never yields a `0`: codex purges `~/.codex/auth.json` after
  repeated auth failures, so a logged-out cron must fail loudly rather than silently
  score the whole queue 0. `make eval-score` follows the production backend
  (`SCORE_BACKEND=claude` A/Bs the old path), keeping the gate's
  `eval-model == production-model` rule true.
  Runs **tool-less** — `--disable shell_tool` + `web_search="disabled"` — a security
  boundary rather than a tuning choice: a JD is untrusted scraped text and `codex exec`
  is natively an agent whose shell `--sandbox read-only` still lets read *any* file, so
  a posting could otherwise ask it to read `~/.codex/auth.json`/`.env` and echo a secret
  into `summary` (which we persist and push to Telegram). Verified behaviorally with a
  canary JD; also worth **~3.1 k fewer input tokens/call** (12,755 → 9,659). The official
  docs claim exec can't be disabled — wrong as of 0.144.4. Model `gpt-5.6-sol` (the CLI
  default) with `model_reasoning_effort=low`/`model_verbosity=low`. A synthetic probe
  favored `gpt-5.6-terra` (tighter spread, half the credits), but on the golden set terra
  scored **worse** (gate 76%/38% flip vs sol's 86%/29%), so sol stands; `luna` was rejected
  (~3x looser) despite the docs recommending it for classification. Effort buys nothing on
  this task shape but is pinned anyway because the default is server-controlled and was seen
  flipping `low`→`medium`→`low` mid-session; verbosity is a no-op under `--output-schema`.
  **Revises the 2026-07-15 direction on two points, from evidence:** (1) it uses the
  **subscription CLI, not the OpenAI API** — the API was chosen for `seed` +
  `temperature=0`, but `codex exec` exposes neither, so the score noise is **not** fixed
  and the harness, not a seed, is what says whether it moves a band; (2) the "fragile at
  strict JSON" objection is **withdrawn** — `--output-schema` enforces the nested,
  enum-constrained production schema exactly as Claude's structured outputs do (verified
  end-to-end). The "heavy" objection stands, and the real bound turned out to be **quota,
  not latency**: Plus meters a rolling 5-hour message window (~20–110 on terra), so a
  ~640-row re-score spans several windows and parallelism can't help. Each call also pays
  a fixed ~9.7 k input tokens of Codex scaffolding for ~80 tokens of JSON with **zero**
  prompt-cache credit — the opposite of Claude's cached prefix.
- **Fit scorer `insufficient_context` signal (case #2).** The Claude fit scorer now
  returns a top-level `insufficient_context` boolean (schema-required, normalized to
  `False` when absent, persisted in `score_detail`): true when the JD is too thin,
  boilerplate, or truncated to assess with confidence. It routes the posting to the
  **Low-context** bucket independently of the 0–100 score, so a full-length-but-empty JD
  the LLM couldn't judge gets human review rather than a trusted number — complementing
  case #1 (a short JD body). `lowContextIds` unions the two signals
  (`LENGTH(TRIM(description)) < N OR json_extract(score_detail,'$.insufficient_context') = 1`).
- **Batched codex fit scoring — the fit call is now list-in/list-out, and `run_score`
  batches the survivors instead of scoring one posting per call.** `fit(postings,
  resumes) -> list[dict]` (both backends) now takes a **list** of postings and returns
  one scorecard per input, in the same order; a single score is
  `fit([posting], resumes)[0]` — `score_posting`'s own call site, unchanged from the
  caller's perspective. `run_score` (`pipeline.py`) is restructured into three phases:
  (1) SCREEN every `new` posting (Ollama, per-item, unchanged) and persist a
  disqualified one `discarded` immediately — it never reaches the fit call; (2) chunk
  the survivors into batches of `batch_size` (default 10) and make **one** `fit_fn`
  call per chunk — on `codex` this is one `codex exec` scoring up to 10 JDs at once,
  each tagged `=== JOB job_ref=<posting id> ===`, with the schema wrapping results as
  `{"results":[{job_ref,...}]}`; results are realigned to the input postings **by
  `job_ref`, not list position** (an LLM isn't guaranteed to preserve order across N
  items), and a missing/duplicate/unknown `job_ref` raises `ScoreError` for the
  **whole batch**; (3) **safety net** — a batch call that raises `ScoreError` *or any
  other exception* (e.g. a transient `claude`-backend API error surfacing through the
  same call site) falls back to scoring that batch's postings **singly**, so one
  malformed batch costs latency, not correctness, and a single that still fails marks
  only that one row `failed`. `batch_size` is configurable via
  `--batch-size`/`CODEX_BATCH_SIZE` (shipped default was 10, since parked to 1 — see
  below); `batch_size=1` degrades to exactly the pre-batching one-call-per-posting
  path (no special-casing). Batching is **codex-only** — the intended quota win,
  since the ChatGPT-subscription cap is message-bound, not token-bound, and at
  `batch_size=10` a ~640-row re-score would drop from 640 messages to ~64 (10/batch),
  cutting total input tokens ~6× (the fixed scaffolding prefix amortizing over 10 JDs
  per call instead of 1) — **see the outcome below: this win is not realized at the
  parked default.** The `claude` backend still loops one
  call per posting regardless of `batch_size`: its cached system prefix already makes
  the marginal posting cheap, so batching would only save request count, which
  doesn't matter on metered billing. `tools/score_eval.py` gains a `--batched` mode —
  a separate, **live**, quota-spending guard, never run from CI/selftest — that scores
  the golden set once single and once batched and asserts the per-row `(seniority,
  domain)` verdicts are identical (PASS = 0 drift), which is what proves a batch's
  JDs don't corrupt each other's score via context bleed from their batch-mates.
  **This guard ran live 2026-07-16** (gpt-5.6-sol, `batch_size=10`, 23 golden rows)
  **and FAILED — 19/23 agree.** All 4 drift rows are on the **domain** verdict —
  concatenating JDs into one codex call bleeds domain judgment across batch-mates: id
  111 and 125 `match/adjacent`→`match/match`, id 132
  `too_junior/adjacent`→`too_junior/match`, id 184 `match/match`→`match/adjacent`.
  111/125 are gate-eligible and their `adjacent→match` drift crosses the notify
  predicate — batching would have **wrongly notified** them (132 stays not-notified,
  floored by `too_junior`; 184 is a `marked` row). Per the design's rollout rule,
  **batching does not ship by default**: `run.py`'s `DEFAULT_BATCH_SIZE` is **1** (was
  10) — default-off, degrading to the pre-batching one-call-per-posting path — with
  the batching machinery and this guard left in place for a future fix (smaller
  `batch_size` / stronger per-JD prompt isolation). Opt back in via
  `--batch-size`/`CODEX_BATCH_SIZE` once the domain-verdict drift is resolved. Unit-
  tested: `job_ref` alignment, the fallback path, `batch_size=1` equivalence. Design:
  `docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md`
  (Part B; the batched==single validation is part of Part C).

- **Fit-scale calibration validated — no change needed (D6).** Re-scoring a 20-row sample
  (flagged rows + a stratified sample) with the post-D3/D4/D5 prompt showed the score
  scale de-compressed on its own: the 60–74 near-miss pile-up collapsed (9→1 in the
  sample) and genuine good-fits reached ≥75 (0→6), while weak/too-junior roles sank. The
  deferred fork (loosen rubric vs lower the notify threshold) resolves to neither — the
  threshold stays **75**. Spot-checks confirmed D3 (id=904 62→25, id=177 63→28, id=322
  72→25, all `too_junior`) and D4 (id=427 66→81, C++/UNIX demoted to nice-to-haves).
- **Location no longer leaks into the fit score (D5).** The JOB section sent to the
  Claude fit call omits the `Location:` line (`_job_block(..., include_location=False)`),
  and the prompt tells the model to ignore geography. The same role posted per city now
  scores identically — geography is the screen gate's job, not the fit number's (it had
  ranked Cumberland London above Chicago, id=324 vs 323). The SCREEN call still receives
  location. Design: `…/2026-07-13-screen-score-quality-fixes-design.md` §D5.
- **Location gate resolves every token via geonamescache (D2).** `resolve_location` no
  longer inspects only the last token through `pycountry` (countries only) — it resolves
  **every** token to a country (US state / country name via pycountry, else a city via
  **geonamescache**, highest-population match), keeps if any is US or an allowed country,
  and discards only when ≥1 token resolves and none are allowed. Fixes both directions of
  the audit: a multi-city US role is kept (Tudor "NYC, London, Singapore", id=1009, was
  discarded) and a bare foreign city is dropped (DRW "London", id=324; WorldQuant "Hanoi
  OR Ho Chi Minh City", id=1071 — the ` OR ` split is now case-insensitive). Adds
  `geonamescache>=3.0.1`; supersedes the last-token/pycountry approach in
  `docs/superpowers/specs/2026-07-07-location-gate-design.md`. Design: `…/2026-07-13-screen-score-quality-fixes-design.md` §D2.
- **Authorization screen no longer disqualifies on boilerplate (D1).**
  `_check_authorization` replaced its loose `_SPONSOR_HINTS` substring guard — which
  fired on "company-sponsored sports teams" (Tower, id=986) and an EEO "citizenship"
  line (WorldQuant, id=1071), killing reachable US roles — with an explicit
  no-sponsorship **phrase** gate (`NO_SPONSOR_PHRASES`) over the JD text. The 4B model's
  invented `offers_sponsorship: "no"` is no longer consulted; a role is disqualified only
  when the candidate needs sponsorship *and* the description literally states no
  sponsorship. Design:
  `docs/superpowers/specs/2026-07-13-screen-score-quality-fixes-design.md` §D1.

- **A transient Telegram send error no longer buries a high-scoring match.** A notify
  failure used to park the row in terminal `failed` — gone from the default
  Discovered-Jobs view, never re-notified. `run_notify` now treats a send error as
  transient: the row stays `scored` (`attempts+1`, `pipeline_error` recorded) and the
  next scheduled pass retries the send; the 3rd cumulative failure parks it `failed`
  (the Failed tab), so a persistently-broken channel (revoked token, wrong chat id)
  still surfaces instead of retrying silently forever. A successful send clears
  `pipeline_error`; delivery is at-least-once (a duplicate ping beats a lost match).
  Design spec: `docs/superpowers/specs/2026-07-09-notify-retry-design.md`.
- **`apply-loop` e2e now confirms the Mark-Applied dialog.** The spec clicked the
  row's Mark-Applied icon but never confirmed the `ApplyCategoryDialog` the
  discovered-jobs overhaul (`d4b46ea`) added, so it timed out with the dialog open. It
  now clicks the dialog's confirm button; the Playwright suite is back to **4/4**.

- **Internship/co-op roles now reliably screened out, via an explicit config flag.**
  The "no internships/co-op" case was a free-text LLM dealbreaker the 4B model often
  missed, leaking internships into the queue. It is now a first-class structured
  constraint — `candidate.exclude_internships: true` — decided deterministically from
  the job title (whole-word `intern`/`internship`/`co-op`, so "internal"/
  "international" don't match), independent of the LLM and of free-text dealbreakers.
  Same philosophy as the other hard-constraint gates (the 4B model is unreliable, so
  decide in code). (`score._is_internship`, `config.Candidate.exclude_internships`;
  SPEC §7.1.)

- Workday pagination and adapter robustness; hardened hard-constraint screening;
  HTML-to-text now collapses non-breaking spaces; config errors surface clearly.


### Documentation

- **SPEC audit — synced with code and deduplicated.** A five-way code audit surfaced
  stale claims, now fixed: the workday feed path is per-job `fetch_one`, not a
  board-list keep-filter substring (§9); `discardJobPosting` → `removed` in the
  traceability table; bulk Remove is offered in every bucket; the §6 stack table and
  §12 `DB_PATH` still described the removed worker container; `score.py` is now the
  `score/` package; the iCIMS feed-backlog note predated the shipped list adapter;
  §7.1's notify-gate summary was missing the thin-JD hold-back; §4/§10 now name the
  iCIMS-HTML + custom/browser recipe surface instead of "official APIs only". The
  traceability table gains the ~20 test files it omitted (recipe executors, SSRF
  guard, sync guard, web routes/components) and its component-test paths. The
  batching/retry/quota stories are deduplicated — one authoritative telling each
  (§13 / §9 / §11), pointers elsewhere. Code side: refreshed stale `schema.prisma`
  source/score/posted_at comments, `run.py`'s docker-era `DB_PATH` comments, and
  documented the optional env overrides in `.env.example`.

- **`PROGRESS.md` slimmed back to a pure live delta.** Shipped-work narratives it had
  accumulated (the remediated-defect recaps, the onboard-board / headless-browser
  "SHIPPED" write-ups, the batching post-mortem, resolved-item strikethroughs, the
  external-reference mining notes' historical validation) moved out: capabilities and
  accepted limitations now live in `SPEC.md` (new §11 "Accepted security residuals"
  block; §7.1 score-stability escape hatch), history stays here. PROGRESS retains only
  genuinely open items — pending publish steps, unverified properties, deferred
  decisions, and unbuilt enhancements.

- Added an authoritative system spec ([`docs/SPEC.md`](./docs/SPEC.md)), a progress
  tracker ([`docs/PROGRESS.md`](./docs/PROGRESS.md)), and an auto-loaded `CLAUDE.md`;
  slimmed the README and reduced `docs/SETUP.md` / `docs/pipeline-design.md` to
  pointers.
- Separated the three docs by role: **SPEC** = the current capability map ·
  **PROGRESS** = live delta only (in-flight + open work, graded by severity) ·
  **CHANGELOG** = chronological history. PROGRESS dropped its completed-feature
  tables (the capability inventory now lives solely in SPEC), recalibrated its
  summary (no "feature-complete and stable"), and surfaces the shipped notify
  data-loss defect as a graded defect rather than one bullet among nice-to-haves.
- Added a user-facing **Feature status** matrix to the README with an honest
  *Tested* axis (yes / partial / —) that distinguishes shipped from verified — fixing the
  old all-`yes` over-claim. Building it surfaced an untested gap: the chart-data
  actions (`getStatusFlow`/`getTimelineData`/`getCategoryData`) have no test
  coverage (now tracked in SPEC §9 and PROGRESS).
- **README/CLAUDE.md/SPEC.md realigned with the shipped adapter set and
  codex-default scorer.** The front-door docs still described a 5-board-API worker
  scoring exclusively with Claude; the worker has shipped 13 adapters (11
  watchlist-capable + 2 feed-resolution-only) and switched its default fit-score
  backend to the Codex CLI (Claude demoted to a metered alternate,
  `SCORE_BACKEND=claude`) since. Fixed the service description, pipeline line,
  Stack line, and Feature-status table in README; the worker one-liner and default-
  models gotcha in CLAUDE.md; and stale product-context mentions in SPEC.md §1/§3/
  §4/§7. Also corrected two stale README notes (Dashboards' "no test" claim —
  `charts.int.test.ts` covers it; Notify's transient-failure warning — a send
  error auto-retries for up to 3 attempts and parks `failed` for a manual
  reopen, never silently buried) and the Notify row's
  superseded "score ≥ threshold" gate (replaced by the seniority/domain verdict
  gate); added missing rows for the Watchlist tab, Unresolved-feeds tab +
  promotion suggestions, and the Codex usage bar. SPEC §12's "Full pipeline" setup
  steps and README's Quick Start still described `docker compose up` starting the
  worker — stale since the worker was decontainerized 2026-07-16 (SPEC §6); both
  now show the native `python -m ats_worker.run` invocation. Also closed two
  SPEC §11 "Open defect (PROGRESS)" callouts (git-history purge, Telegram-token
  scrub) that CHANGELOG already shows shipped. The same two staleness patterns
  (Claude-only scorer claims, 5-board mentions) were also present in
  `apps/worker/README.md` and `CONTRIBUTING.md` — fixed there too: the worker
  README's service description, ASCII pipeline diagram, board table, `.env`
  setup step, and test-suite note; CONTRIBUTING's prerequisites and
  dependency-injection note. Missed by that pass: the worker README's own **Run**
  section still led with "Docker (recommended)" and `docker compose up` — also
  stale since the 2026-07-16 decontainerization. Rewritten so the native
  `python -m ats_worker.run` path (host-Ollama prerequisite folded in) is the
  only run path, with a short note that `docker compose up` starts the web
  stack alone and a pointer to SPEC §6.
- **The 6 README/`docs/images/*.png` screenshots now come from seeded sample
  data, not the operator's real job search.** Regenerated all of them
  (`kpi-and-table`, `charts-row`, `status-funnel`, `sankey`, `dashboard`,
  `mobile`) against a throwaway DB seeded via `apps/web/prisma/seed-dev.mjs`
  (400 rows of fictional companies — Hooli, Stark Industries, Wayne
  Enterprises, etc.) — closing a privacy blocker for going public. Image
  paths and filenames are unchanged.

## [0.2.0] — 2026-06-08

### Added
- **Semi-automated job-hunt pipeline** (`apps/worker/`): a Python worker that
  scans Greenhouse / Lever / Ashby boards, scores each posting against your
  resume with a local Ollama model, auto-tailors a one-page resume for high
  scorers (Claude + `tectonic`), and notifies you on Telegram.
- **Discovered Jobs** tab in the web app: a scored, filterable queue with a
  job-description + match-analysis dialog, per-job tailored-resume download
  (`GET /api/resume/[id]`), and one-click "Mark Applied" that promotes a posting
  into a tracked application.
- `job_postings` model in the Prisma schema (deduped on `(source, external_id)`,
  advancing through a `pipeline_status` state machine).
- Repository scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`, this changelog,
  `.editorconfig`, a root `Makefile`, GitHub Actions CI, and a PR template.

### Changed
- Promoted `docker-compose.yml` to the repository root; it now orchestrates both
  the web app and the worker from one place (`docker compose up` from root).
- Moved `SETUP.md` and the pipeline design doc under `docs/`.
- Prisma datasource is now driven by `DATABASE_URL` so the same schema serves
  local dev and the directory-mounted Docker volume shared with the worker.

### Fixed
- Web `lint` step (and therefore CI) failed before running: the flat
  `eslint.config.mjs` used Next 15 / ESLint 9 imports (`eslint/config`,
  `eslint-config-next/typescript`) incompatible with the pinned Next 14 /
  ESLint 8 toolchain. Replaced with a standard `.eslintrc.json`
  (`next/core-web-vitals`) run via `next lint`.

## [0.1.0] — initial tracker

### Added
- Next.js + Prisma + SQLite application tracker: status KPIs, searchable and
  paginated table with inline status editing and history, CSV import/export,
  and dashboards (activity heatmap, category donut, status funnel, Sankey).
- Dockerized web app with a bind-mounted database.
