# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The current
system is described in [`docs/SPEC.md`](./docs/SPEC.md).

## [Unreleased]

### Fixed

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
  extracted too, so a recipe can carry a url-only helper field. The interpolated URL
  enters the pipeline at the same point as a scraped `href` and passes the same
  `is_safe_public_url` guard in `browser.fetch` — no new fetch path (regression-tested
  with a template resolving to a link-local address). Unblocks two watchlist candidates
  that were blocked on this primitive alone; no adapter changed.

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

- **`browser` recipes can build `job_url` from a `{field}` template.** `custom` (JSON)
  recipes already interpolate `{dotted.field}` into `url`; `browser` (rendered-DOM)
  recipes could only read a `url` off the card via a CSS selector, so a board whose
  cards carry no `href` (id in a `data-*` attribute, routing JS-side) produced an empty
  `job_url`. A `url` spec that is a string containing `{` is now interpolated in
  `_recipe.apply_css_fields` from the fields already extracted for that posting — e.g.
  `external_id: {attr: "data-id"}` + `url: "/s/details?jobReq={external_id}"`, then
  resolved against the listing `base_url`. The interpolation namespace is the recipe's
  **own `fields` map**, so a helper field the canonical posting ignores (`req`, say) can
  still feed the template. Any other `url` spec stays a CSS selector as before. Unblocks
  Balyasny / Jacobs Levy-shape boards without touching an adapter.

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
