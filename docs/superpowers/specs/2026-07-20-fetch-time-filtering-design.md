# Design: Fetch-time filtering (Phase 1) — global age + title-exclude drops, hoisted deterministic gates

**Status:** designed, approved (Phase 1 scope + Option B), not yet built.
**Date:** 2026-07-20.

## Problem / motivation

High-volume watchlist boards (Amazon, Microsoft, …) return hundreds–thousands of
postings per pass. Two kinds of waste follow:

1. **Stale / off-title noise reaches the models.** The *only* fetch-time filter today
   is the global positive `title_filter` (keep-if-title-matches). Everything that
   passes is upserted, and every upserted `new` row buys one local Ollama **screen**
   call — and `screen_posting` fires that LLM call **first** (`score/screen.py:118`),
   *before* its own deterministic internship/location gates (`:129`, `:143`). So a
   posting that would be trivially disqualified on location still costs a screen call.
2. **Outdated postings clutter the queue.** Postings already carry `posted_at`, but
   nothing filters on it — a role posted months ago is scored and surfaced like a
   fresh one.

The result: the local LLM is prompted far more often than necessary, and the
Discovered queue fills with stale/irrelevant rows.

## Goal

Add cheap, **deterministic, pre-scorer** fetch-time filters (no LLM at fetch) on the
**watchlist path** that:

- **Drop confident noise before upsert** — postings older than a max age, or whose
  title matches an exclude keyword.
- **Hoist the two already-deterministic screen gates** (internship title, location
  string) *ahead of* the Ollama call, so a location/intern miss never triggers a
  screen — while staying **visible** in the Discarded bucket (Option B).

Global `config.yaml` only. No schema change. The scorer still does all real relevance
judgment.

## Non-goals (Phase 1 — deferred to Phase 2, tracked in PROGRESS)

- **No per-board filters.** No `filters` column on `watched_companies`, no
  Watchlist-tab editing, no `onboard-board` capture. Phase 2.
- **No source-side query narrowing** (recipe `base_query`, which is the only lever
  that cuts the *scrape* itself). Phase 2.
- **No change to the feed path** (`run_feed`). Feed postings keep screen-time gating —
  which is why the hoisted gates are **reused, not removed** from `screen_posting`.
- **No new LLM at fetch.** No change to the other screen gates (degree / work-auth /
  clearance) — they stay LLM-extract + code-apply, post-fetch.

## Decisions (resolved with the user)

1. **Two mechanisms, split by intent:**
   - **Noise → silent drop** (never upserted, exactly like today's `title_filter`):
     `max_age_days`, `title_exclude`.
   - **Disqualification → keep visible (Option B):** a hoisted internship/location miss
     is still upserted, pre-marked `discarded` with the same `score_detail` screen
     shape, just **skipping Ollama**. Preserves the Discarded bucket + reopen. Chosen
     over silent-drop (Option A) for least surprise — the LLM saving is identical
     either way; A only additionally spares a cheap DB write.
2. **Global config only** in Phase 1.
3. **Age is keep-leaning:** `null`/absent/unparseable `posted_at` → **keep** (dateless
   boards fall through; note `db.py:65` applies a scrape-date fallback at *upsert*, so
   the null only exists pre-upsert where the filter runs). Compare date-only
   (`YYYY-MM-DD`). `max_age_days == 0` → filter off.
4. **Reuse the existing pure gate functions** (`resolve_location`, `_is_internship`) so
   a fetch-time verdict is byte-identical to the screen-time verdict — hoisting changes
   *timing*, not *outcome*.
5. **Scope to the watchlist fetch path** (`run_fetch`). Feeds unaffected.

## Change list

### Worker — `ats_worker/config.py`

- Add two fields to `Config`: `max_age_days: int = 0` and
  `title_exclude: list[str] = field(default_factory=list)`. `0` = age filter off;
  empty list = no exclude. Parse `max_age_days` via the existing `_int_field`,
  `title_exclude` via a `_parse_title_filter`-shaped list parse. The unknown-key guard
  (`_reject_unknown_keys`) picks them up automatically — they are dataclass fields.

### Worker — fetch gate (`ats_worker/fetch/__init__.py`)

- Keep `filter_postings` semantics but broaden the chokepoint to a single **pure**
  function (no I/O, table-testable):
  `prefilter_postings(postings, *, title_filter, title_exclude, max_age_days, now)`.
  A posting is **kept** ⟺
  `(title_filter empty OR title matches one) AND (title_exclude empty OR title matches none) AND (max_age_days == 0 OR posted_at is null/unparseable OR age(posted_at, now) <= max_age_days)`.
  `age()` slices `posted_at`/`now` to `YYYY-MM-DD` and diffs days. Matching stays
  title-only and case-insensitive (same rationale as `filter_postings`: description
  matching makes "engineer" hit everything).

### Worker — hoist the deterministic gates (`ats_worker/score/screen.py`)

- Extract the internship + location verdict-merge (`screen.py:129-150`) into one pure
  helper `deterministic_screen(posting, candidate) -> dict` returning
  `{"screen": {...}, "disqualified": bool, "disqualification_reason": str}` (empty /
  not-disqualified when nothing is configured).
- `screen_posting` calls it after its LLM merge — **behavior-identical to today**, so
  the feed path (which never sees the fetch gate) is unchanged.
- The new fetch gate (below) calls the *same* helper — one implementation, two call
  sites, guaranteed-identical verdicts.

### Worker — `ats_worker/pipeline.py` `run_fetch`

- Grow the signature to receive the `candidate` dict and the new filter params (a small
  `FetchFilter` bundle, or pass them explicitly). Per company: `prefilter_postings` →
  for each survivor run `deterministic_screen`; if `disqualified`, tag the posting
  `pipeline_status = 'discarded'` and
  `score_detail = _score_detail(result, disqualified=True)` (reuse the existing
  assembler at `pipeline.py:247` so the shape is byte-identical to the screen-discard
  path and `JobDetailModal` renders it unchanged). Otherwise the row stays `new`.
  Then upsert.

### Worker — `ats_worker/db.py` `upsert_postings`

- The INSERT hardcodes `'new'` (`db.py:38-41`). Make it honor an optional per-posting
  `pipeline_status` (default `'new'`) and `score_detail` (default `null`); the dedup
  `ON CONFLICT(source, external_id)` behavior is unchanged. Only these two columns gain
  a per-row source.

### Worker — `ats_worker/run.py`

- Build the `candidate` dict once (it exists at `:197`, currently only for
  `run_score`) and pass it plus `cfg.max_age_days` / `cfg.title_exclude` into
  `run_fetch` (`:165`).

### Config template

- `config.yaml.example`: document both keys with worked examples, e.g.
  `max_age_days: 30` and `title_exclude: [intern, "co-op", sales, principal, staff, director]`.

### Docs (same commit)

- **SPEC §5 (flow) / §7:** fetch-time filtering now covers age + `title_exclude` +
  hoisted deterministic gates on the watchlist path; note internship/location are
  decided at fetch (skipping Ollama) while the shared helper still lives in `screen`
  for the feed path. **§9 invariant→test map:** add the new rows. Config section: the
  two new keys.
- **PROGRESS:** narrow the "Fetch-time filtering" entry — Phase 1 shipped; keep Phase 2
  (per-board `filters` column + source-side query + `onboard-board` capture) as the
  remaining open item.
- **CHANGELOG:** entry under Added / Changed.

## Impact & operational risks

- **Behavior change (watchlist path):** location/intern-disqualified postings are now
  decided at fetch — no Ollama call — but stay visible in the Discarded bucket
  (Option B). UX-identical, fewer LLM calls. Feed postings unchanged.
- **False-drop risk** (age + `title_exclude` are silent drops): mitigated by age
  defaulting **off** (`0`), null→keep, a generous recommended default (30d), and
  `title_exclude` being an explicit user-authored list. Both opt-in.
- **Dedup interaction:** `ON CONFLICT` keeps an already-inserted row on re-fetch, so the
  new drops only affect rows not yet inserted. A posting that goes stale *after*
  insertion is not retroactively removed — that's the separate "mark dead postings
  `expired`" PROGRESS item.
- **No schema change** → schema-drift guard unaffected.

## Testing / verification

- **config:** new keys parse + defaults; the unknown-key guard still fires on typos.
- **`prefilter_postings`** (pure, table-driven): `title_filter` keep; `title_exclude`
  drop; compose (keep-and-not-excluded); age boundary (older → drop, equal/newer →
  keep, null → keep, unparseable → keep); `max_age_days == 0` → keep all.
- **`deterministic_screen` extraction:** verdict identical to the pre-refactor screen
  for the internship + location cases (reuse the existing `test_score` location/intern
  cases; the refactor must be green before wiring the fetch gate).
- **Fetch hoist:** a location/intern miss is upserted with `pipeline_status='discarded'`
  + matching `score_detail`, and makes **no** Ollama call; a survivor is `new`.
- **`run_fetch` integration:** a mixed batch yields the right counts + statuses; the
  feed path (`run_feed`) is unchanged.
- Full worker suite green; coverage gate (`fail_under = 85`) holds; schema-drift guard
  unaffected.

## Sequencing (suggested)

1. `config.py`: add the two fields + parsing; update `config.yaml.example`.
2. Extract `deterministic_screen`; keep `screen_posting` behavior-identical
   (regression-test first).
3. Add `prefilter_postings` (age + `title_exclude`) with unit tests.
4. `db.upsert_postings`: optional per-row `pipeline_status` / `score_detail`.
5. Wire `run_fetch` (signature + candidate) + `run.py`; add the fetch-time discard
   tagging.
6. Tests (unit + integration); full suite green.
7. Docs (SPEC / PROGRESS / CHANGELOG).
