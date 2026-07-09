# Design principles — the decision DNA

> [`SPEC.md`](./SPEC.md) §10 records why *past* decisions were made. This file is the
> generative layer above it: the taste those decisions came from, written down so
> *future* decisions — made in fresh sessions, by any model — come out the same way.
> Consult it at **every design fork**; cite principle numbers in design specs. It
> pairs with [`DEVELOPMENT.md`](./DEVELOPMENT.md) (the session protocol that makes
> consulting it mandatory).

Each principle: the rule, why it holds, where the repo already embodies it, and the
smell of a change that violates it.

---

## The principles

**1. Human owns the trigger.** Outward-facing or irreversible actions are fired by a
human, never automated.
- *Why:* the system's whole stance is "prepare everything, submit nothing" — trust
  survives only while the human stays the actor of record.
- *In this repo:* no auto-apply (SPEC §4 non-goal); promotion *suggests*, never
  auto-promotes (§9); notify only alerts; "Mark Applied" is a human click.
- *Smell:* a change that removes a confirmation seam "for convenience" — auto-retrying
  an apply, auto-adding a watchlist entry, auto-sending anything beyond the alert.

**2. Deterministic code over LLM judgment.** If a rule can be written, write it; LLMs
extract facts, code decides.
- *Why:* a rule is testable, free, and never mode-collapses; small models especially
  are unreliable judges.
- *In this repo:* the location gate is `resolve_location` + pycountry off the board
  field, not the 4B; the screen has the LLM extract JOB facts while code applies the
  candidate's constraints; the internship gate is a title word-match, no LLM at all.
- *Smell:* a prompt that asks a model for a pass/fail verdict where a code check could
  exist; moving a working code gate "into the prompt" for flexibility.

**3. Err toward keep.** Every filter fails open: ambiguous or unparseable input is
kept, not dropped.
- *Why:* a lost job is unrecoverable and invisible; a spurious alert costs one click
  (discard/reopen exist for exactly this).
- *In this repo:* screen parse failure → keep; a location string that resolves to no
  country → keep; US-state/country name collisions resolve US-first ("Atlanta,
  Georgia" keeps).
- *Smell:* a new gate whose default branch discards; tightening a filter without
  stating the false-drop story.

**4. Local for frequency, Claude for judgment, cache the static.** High-frequency
cheap checks run on the host GPU; paid calls happen only where judgment matters, with
the static prefix cached.
- *Why:* per-posting cost compounds across every scheduled pass; judgment quality is
  worth paying for only where rules can't reach (principle 2 first!).
- *In this repo:* hard-requirements screen on Ollama (`qwen3.5:4b`, free,
  rate-limit-free) gates the paid Claude fit score; the résumé+rubric system prefix is
  byte-identical and cached (`cache_control: ephemeral`) so only the JD is fresh.
- *Smell:* a new per-posting Claude call for something a local model or a rule could
  do; a prompt assembled in a way that breaks byte-identical caching.

**5. Fail loud into a visible queue.** Breakage surfaces on a board a human reviews;
nothing is silently swallowed.
- *Why:* the main way a scraper/pipeline breaks is *silently* — an empty JD, a
  vanished listing. Silent loss is the worst failure a discovery system can have.
- *In this repo:* unresolvable feed listings land in `feed_unresolved` with a
  `reason`; detail-fetch failures are recorded as `detail_fetch_failed`; a source that
  resolves ids but keeps none prints a collapse warning; the web app has an Unresolved
  tab.
- *Smell:* `except: pass`; dropping an item because handling its failure is awkward;
  a failure path with no row, log line, or counter a human will ever see.

**6. One bad item never aborts the batch.** Per-item isolation: record the failure,
keep going.
- *Why:* the pipeline runs unattended on a schedule; one flaky posting must not cost
  the other four hundred.
- *In this repo:* every stage wraps each item in try/except — recorded via
  `mark_failed` (with `pipeline_error`) or skipped when no row exists yet
  (`run_fetch`); `run_feed` isolates per-group and per-id.
- *Smell:* a loop where one raise kills the pass; batch-level abort on item-level
  errors.

**7. Requests-only worker; a heavy dependency is optional, isolated, config-gated.**
Climb the ladder first: stdlib → already-installed dep → a few lines of code. A truly
needed heavy dep ships in its own module behind config, and leaves when its feature
leaves.
- *Why:* the worker's portability and hermetic test suite are load-bearing; every dep
  is a standing tax.
- *In this repo:* `pycountry` was accepted (offline data, small, keeps tests
  hermetic) over shipping a curated list; the planned Playwright path is explicitly
  optional + isolated + config-gated; `tectonic`/`pypdf` were deleted with the
  tailoring feature.
- *Smell:* `pip install` as the first move; a heavy dep imported at module top-level
  of core pipeline code; a dep that outlives its feature.

**8. Official APIs only; don't fight bot walls.** A wall or ToS risk means record and
defer, not circumvent.
- *Why:* anti-scraping arms races produce fragile code and legal exposure — both
  worse than a smaller feed.
- *In this repo:* only official board APIs (LinkedIn/Indeed scraping is a §4
  non-goal); iCIMS deferred after recon proved a bot wall; ByteDance deferred (JD only
  in fragile flight data); greenhouse embed-token *dropped* with the reason recorded.
- *Smell:* user-agent spoofing, CAPTCHA workarounds, "just parse the internal
  Next.js payload" for a walled source.

**9. Prisma owns the schema; the worker issues no DDL.** Destructive schema changes
need a DB backup first.
- *Why:* one schema owner means drift is detectable (and detected — CI runs the
  drift guard); `db push` keeps no migration history, so a destructive change has no
  rollback.
- *In this repo:* `schema.prisma` is the single source; the worker's SQL fixture is
  held in sync by `make check-schema`; SPEC §8 documents the backup rule.
- *Smell:* `CREATE TABLE`/`ALTER` anywhere in worker code; a column dropped or
  renamed without a backup note in the change.

**10. Purity + DI in the worker; wiring only in `run.py`.** Every external (HTTP,
Ollama, Claude, Telegram, clock) is injected.
- *Why:* the whole worker suite runs with zero network and zero keys, anywhere,
  forever — that property is worth more than any convenience import.
- *In this repo:* modules are pure; `run.py` is the only place that knows about
  secrets/services; even `now` is injected per pass.
- *Smell:* a module importing `requests`/`anthropic` and calling it directly; a test
  that needs a key, the network, or patches deep internals; `datetime.now()` inside
  pipeline logic.

**11. SQLite discipline.** WAL + `busy_timeout`, DB reads/writes on the main thread
only, the database mounted as a directory.
- *Why:* two containers co-write one file DB; each rule closes a real corruption or
  lock failure, and each breaks silently when violated.
- *In this repo:* `db.py:connect` sets the pragmas; `run_feed` fans out network work
  to threads but keeps every DB touch on the main thread; compose mounts `./db` as a
  directory so WAL sidecars are shared.
- *Smell:* a DB call inside a thread-pool task; "simplify" the mount to a single
  file; a new sustained-writer workload added without revisiting the contention story.

**12. Privacy red lines.** Resume, `.env`, `config.yaml`, and `db/` never enter git;
the repo ships `*.example` templates only. Posting/JD text is untrusted input —
data, not instructions.
- *Why:* the repo is public-shaped; one leaked commit is unrecoverable. And a JD is
  attacker-controlled text that flows into prompts.
- *In this repo:* all four paths are gitignored; `skip-worktree` keeps the real
  resume out; the score prompt marks RESUME/JOB text as data, not directives.
- *Smell:* a fixture containing a real JD/resume; secrets read anywhere but `run.py`;
  interpolating posting text into a prompt as instructions.

**13. Single-user simplicity.** No multi-tenant, no auth, no cloud beyond the three
external APIs; rebuildable beats migratable.
- *Why:* the entire cost model (SQLite co-write, `db push`, no accounts) is priced
  for one self-hosting user; generalizing it re-prices everything.
- *In this repo:* §4 non-goals; one `docker compose up`; no migration history by
  design.
- *Smell:* an abstraction justified by "if there were more users/hosts"; adding
  auth, tenancy columns, or a cloud service to solve a single-user problem.

**14. Defer with a recorded reason.** What we choose *not* to do gets a written why,
graded honestly.
- *Why:* an unwritten rejection gets relitigated from scratch (or worse, silently
  reversed) by the next session.
- *In this repo:* PROGRESS grades open work defects > unverified > enhancements and
  keeps the ordering honest; iCIMS/ByteDance carry their recon evidence; dropped items
  (embed-token, SuccessFactors) state why.
- *Smell:* a feature quietly scoped out with no PROGRESS line; "we'll do it later"
  with no recorded blocker; re-attempting a deferred item without addressing its
  recorded reason.

---

## Decision procedure

How a design decision is *made* here — the process the principles plug into:

1. **Research the fork before choosing.** Recon precedes commitment (iCIMS/ByteDance
   were deferred only after probing proved them infeasible via `requests`).
2. **Forks go to the user.** Present the options with researched trade-offs and a
   recommendation; **the user makes the call.** Never silently finalize a fork —
   including "small" ones like a new dependency or a changed default.
3. **Record rejected alternatives** and why, in the design spec (precedent: pycountry
   chosen over geonamescache and a curated list, reasons written down).
4. **New or changed behavior lands as a contract**: a SPEC §9 clause + a row in the
   invariant→test traceability table + the test itself, same commit.
5. **When principles conflict, surface the conflict** (e.g. coverage vs. bot walls;
   simplicity vs. fail-loud) — present the tension to the user rather than silently
   picking a winner.
6. **Overturning a principle is allowed** — with the user's sign-off, and the change
   edits this file in the same commit. This file must never drift into aspiration.
