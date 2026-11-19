# Rejected and evaluated-out — do not re-derive

> Proposals that were **evaluated and turned down**, each with the measurement or the
> reason that killed it. This is reference material consulted at one moment — when you
> are about to propose a redesign — not state that changes, so it is not loaded with the
> live delta in [`PROGRESS.md`](./PROGRESS.md).
>
> **Read the entry for your block before proposing a redesign of it.** Entries are named
> by block rather than tagged (`Fetch capability registry…`, `Screen shape changes…`,
> `Orchestration-layer shapes…`). Negative results about LLM judgment over postings
> (batching, numeric-score noise, model selection) are in
> [SCORING §6.4](./SCORING.md#64-constraints-carried-over-from-the-retired-fit-scorer).
> A rejection here is not permanent — several name the trigger that would reopen them
> (usually a counted instance).
> What it forecloses is re-deriving the same argument from scratch.
>
> Open work lives in [`BACKLOG.md`](./BACKLOG.md); the live delta and open defects in
> [`PROGRESS.md`](./PROGRESS.md).

- **An autoheal entrypoint watchdog — built, drilled, and rejected · do not re-derive.** The idea (a `sh -c` wrapper that pings the socket in a loop and exits when it
  dies, so `restart:` fires) was in the approved plan and its own drill **passed**: bogus
  socket path -> exit 1, restarted 7x in 8s; real socket -> healthy, `RestartCount 0`.
  Two further measurements killed it anyway.
  1. **The state it fixes does not occur.** The stock image's `/docker-entrypoint` runs
     under `set -e -o pipefail`, so a failed Docker API call exits the script. Measured
     against a relay socket killed under a live **stock** sidecar: `Exited (7)`, and
     `restart: unless-stopped` climbed to 8 restarts unaided.
  2. **It reintroduces the deception it was meant to remove.** As PID 1 the wrapper
     survives its child, so killing the autoheal loop inside a wrapped container left it
     `Up (healthy)`, `RestartCount 0`, no autoheal running — indefinitely. It also
     swallowed SIGTERM (a trapless `sh -c` as PID 1 gets no default disposition), turning
     every `docker stop` into a SIGKILL after the full timeout.
  **The lesson, and it is the same one the screen stack taught:** a drill that only
  exercises the failure you designed for is not evidence the design is safe. Ask what the
  change makes newly possible, not just whether it does what you meant.
  **What exists instead** (SPEC §6): the socket-ping healthcheck and `make health`. Its known limits are recorded in SPEC §6 — `/_ping` is answered before any
  containerd work so a daemon wedged on container *operations* still reads healthy; nothing
  detects a sidecar whose loop died without exiting; and `make health`'s RestartCount delta
  catches a container flapping *before* first-healthy but not one that crash-loops after.
  **Recorded, unverified, not in scope:** long-syntax `create_host_path: false` on the
  socket bind — the only compose knob touching bind resolution; it would make a poisoned
  host path fail the start instead of being mkdir'd. Untested here (legacy `Binds` path).

- **Fetch capability registry (`AdapterSpec`) — rejected · do not re-derive.** The proposal was to replace the four collections in
  `fetch/__init__.py` (`ADAPTERS` · `RECIPE_SOURCES` · `STUB_GATE_SOURCES` ·
  `DETAIL_SOURCES`) with one frozen dataclass of explicit capability booleans, so an
  agent adding a source can't forget a `frozenset`. **Rejected on two counts.**
  (1) *The failure it prevents is already loud or already harmless*: forgetting
  `VALID_SOURCES` raises `ConfigError` at startup; forgetting `RECIPE_SOURCES` reds
  `test_recipe_sources_match_web_and_fetch`; `DETAIL_SOURCES` is **derived**
  (`hasattr(m, "fetch_one")`) and cannot be forgotten; forgetting `STUB_GATE_SOURCES`
  only costs an optimization and fails open. Five of the seven proposed booleans are
  likewise derivable from what the module already exposes. (2) *One field would be an
  outright second source of truth*: feed routability lives in
  `feed/resolve.py:resolve_url`, a URL-pattern parser, not a registry — Pinpoint has
  an adapter and a watchlist row but no host route — so a `feed_enabled: bool` would
  eventually disagree with the parser silently. The real gap the proposal was
  reaching for is narrower and is the SPEC source-matrix test (`test_spec_matrix_matches_adapters`). A narrower
  variant (#175: a dependency-free `sources.py` flag table, no feed field, deriving
  `config.VALID_SOURCES`) was also turned down on count (1): it saves one duplicated
  tuple in `config.py` for a new file and test; the README checklist covers the gap.
  **Rejected alongside it:** a retry/classification queue on `feed_unresolved`
  (`attempts`, `next_retry_at`, retryable-vs-terminal). The feed re-reads
  `listings.json` in full every pass and `record_unresolved` upserts on `url`, so
  every transient reason *already* retries on pass cadence; the table is a human
  backlog the UI does not yet surface, and giving it a scheduler is building a job
  queue for a page that doesn't exist. **Deferred, not rejected:** `content_hash` +
  `first_seen_at`/`last_seen_at` to re-assess a posting whose JD changed under
  `ON CONFLICT DO NOTHING` — a real hole, but no observed instance of it costing
  anything; wants one concrete case before it earns four columns and a re-assessment
  trigger.
- **Orchestration-layer shapes — one already correct, four rejected · do not
  re-derive.** A review proposed nine cross-cutting reworks; the err-toward-keep policy
  table it produced is in PRINCIPLES. These are not:
  **Already correct, verified by execution:** *never hold a SQLite transaction across a
  network call.* `conn.in_transaction` is `False` after connect, after a SELECT, and
  after every mutator — each one `execute`s then `commit`s immediately, and sqlite3's
  default `isolation_level=""` opens nothing on a read. There is no long transaction to
  eliminate.
  **Rejected:**
  (a) *A formal `transition_posting(job_id, expected, new, reason_code)` API replacing
  every direct status UPDATE.* The **table** of legal transitions is worth having — as
  documentation plus one test — but rewriting every mutator call site to funnel through
  a transition function is a large diff against a problem with no observed instance (no
  illegal transition has occurred). `db._update`'s `_UPDATABLE_COLUMNS` allowlist
  already demonstrates the taste at a tenth the cost.
  (b) *Per-row `claimed_by` / `claim_expires_at` lease columns.* APScheduler cannot
  overlap itself (`max_instances=1`), so the only real race is a hand-run pass inside a
  scheduled one on a single host — and `run.pass_lock` (a non-blocking, stale-safe
  `flock`, SPEC §7.1) is ~15 lines against a per-row lease protocol. The lockfile is
  worth it because a duplicated provider call costs real quota or money.
  (c) *`pipeline_runs` + `stage_runs` observability tables.* Every question offered as
  motivation — why only 40 postings today, which adapter went empty, when a provider started
  failing, whether the location gate suddenly widened — is **already printed** by the
  per-stage log lines. What is missing is that the output is not kept. Redirect it to a
  dated file first; build tables when a real question survives having the logs. Same
  ordering applies to the proposed per-gate metrics: the **sampling audit** half (spot
  check ~20 title-filter drops, ~20 location discards, ~20 screen discards per week for
  false negatives) costs no code and is the half with the value, since the earliest
  gates are the ones no later model can correct.
  (d) *End-to-end version hashes plus a re-run planner* deciding what to re-assess from
  input deltas. Inputs change a handful of times a year; a stored version/hash plus an
  explicit one-shot re-run (`--rescreen-screened`, JEV's `policy_sha`) covers it.
- **Screen shape changes — rejected · do not re-derive.**
  A review proposed four reshapes of the screen's output. These particular *shapes* are
  not the fix for the problems they named.
  (1) *Four-state `verdict: pass|fail|unknown|not_applicable` + `reason_code` on every
  check.* `not_applicable` already exists — `gate()` returns before writing the key
  when a check isn't configured, so an absent key **is** that state. The only genuine
  conflation is `pass` vs `unknown`, which is fixed by not writing the key on an empty
  extraction; a four-verdict enum plus stable codes would additionally break every
  reader of the stored `screen` block — the web modal, the MCP read path, and every
  existing row.
  (2) *`confidence` on the location resolver.* Every ambiguous string the review
  offered as motivation already keeps, verified by execution: `Paris, TX`,
  `New York / London`, `United States or Canada`, `Remote - US excluding Colorado`,
  `Remote within EST hours`, `San Francisco preferred, remote considered`. Clauses
  (C) direct-match, (D) US-state precedence and (E) any-token-allowed already do the
  work a confidence tier would. The one string that *is* wrong (`London, ON`) needs
  the resolver to be **more conservative**, not more granular.
  (3) *`disqualification_codes` array + `primary_disqualification_code`.*
  `disqualification_reason` is already `"; ".join(failures)` — it carries every
  reason, not one — and `screen{}` already stores each check's verdict and note. The
  only thing missing is machine-readable codes, and nothing consumes them today.
  (4) *A six-field structured `authorization:` config* (country / authorization_type /
  requires_future_sponsorship / citizen / permanent_resident / currently_authorized).
  One bit changes an outcome — *currently authorized but needs future sponsorship* —
  and the actual bug is the silent off-vocabulary fallthrough, a validation fix.
- **Cross-service drift — guarding the rest was declined (orchestration)**. `test_source_enums_sync.py`
  guards the cheaply-comparable duplicated items (source enums + the low-context
  length literal). **Still unguarded (deliberate scope call — fragile, low value):**
  the `pipeline_status` string literals (scattered across worker + web) — documented,
  not guarded, hand-duplicated with "must match" comments only.
- **`requirements-dev.txt` duplicates base pins** — accepted (no include mechanism
  exists without adding tooling), but the duplication bit once — see the
  [CHANGELOG](../CHANGELOG.md) geonamescache CI fix. The standing rule it produced is
  a *convention*, so it lives in [`CONTRIBUTING.md`](../CONTRIBUTING.md) where it is
  read at the moment it applies — adding a dependency — not here.

- **Fetch levers measured dead — do not re-open.**
  (1) *Workday prose-date age gating.* Workday's ladder tops out at `"Posted 30+ Days
  Ago"`, which parses to exactly 30 days, and `_too_old` tests `> max_age_days`, so at
  `max_age_days: 30` the gate cannot fire; dropping the global threshold to 29 would
  tighten every board for a handful of Workday postings. Parse coverage is 100%; the
  threshold, not the parser, neutralises it.
  (2) *A per-position detail-leg retry for `empty_description` re-fetches* (built and
  reverted). It rescued nothing — every sampled row was already stored with a full JD,
  and `ON CONFLICT DO NOTHING` means a bodyless re-fetch cannot overwrite it — and it
  is a per-position budget for a board-wide failure: a throttling board would cost hours
  per pass under a `pass_lock` that refuses rather than queues. Any future retry needs a
  board-level breaker first, and 404 stays terminal.
  (3) *A recipe date for `tiktok`, `janestreet`, `bytedance`, `ibm`.* Their list payloads
  carry no date-like field at all, so `posted_at` is the scrape day and `max_age_days`
  cannot fire for them; only a per-posting detail call could supply a date, which is not
  worth it. Check the payload before filing this as a bug on another board.
  (4) *Per-page stealth for bot-walled boards.* `Stealth().apply_stealth_sync(page)`
  under-patches (six arms failed); the context-level `use_sync` form in SPEC §7.1 is the
  working rung, and a wall is per host, not per company. If a board resists it,
  Patchright is the drop-in next rung; Camoufox (200MB+ per instance, ~42s per
  challenge) is the wrong shape for a several-times-daily pipeline.
- **Boards held off the watchlist — decision recorded.** Validated but not added because
  of the board, not a bug. *Empty list JD:* Uber, Netflix, Morgan Stanley, Brevan
  Howard, Campbell — they insert nothing until `custom` gains a chained detail call.
  *Render cost:* Citi (~3.5k postings), Barclays (~1k), Bloomberg, Moody's — a `browser`
  `detail:` block costs one Chromium render per posting with no stub gate. Reopen when
  `custom` gains a chained detail call (or an HTML mode, for Citi/Barclays).
- **Feed-resolution targets not worth a resolver.** Greenhouse embed-token links carry a
  job id but no board slug, so they cannot resolve to a watchlist row; SuccessFactors
  does not appear in the feed at all.
