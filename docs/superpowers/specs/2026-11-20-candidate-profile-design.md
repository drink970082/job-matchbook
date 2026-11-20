# One candidate profile; evaluate each posting once

**Status:** draft - awaiting operator approval. Epic #223; slices #224-#227.

## Problem

A user configures the screen and the keep/skip filter (JEV) in five places:
`config.yaml` title filters, `candidate_preferences`, `jev_profile`, the `jev_dir`
pack files, and env/flags. Facts are entered twice (degree in both rows). The two
stages also follow opposite rerun rules, and that causes five user-visible
inconsistencies:

1. A watchlist posting discarded at fetch (`pipeline_status='discarded'`) can never be
   re-evaluated, but the same miss arriving through the feed is a `job_screenings`
   row that `--rescreen-screened` can redo.
2. Editing the screen preferences re-runs nothing and marks nothing stale.
3. A JD content change re-queues JEV but not the screen. Only SmartRecruiters ever
   refreshes content.
4. The screen covers every `new` posting, JEV only the last 7 days, so a posting can
   sit at "screened, unassessed" with no visible reason.
5. JEV's policy hash ignores the screen preferences. A degree edit in one row re-runs
   one stage, and an edit in the other row re-runs nothing.

Readers add a sixth problem. The web (`lib/job-actions.ts`) and MCP
(`mcp/read_repository.py`) each carry a hand-kept port of about 100 lines of status SQL
(triage status, JEV model status, stale rules, legacy discard shape).

## Decisions (operator, 2026-11-20)

- **One `candidate_profile`** covers everything. The keep/skip stage is not named after
  a model: user-facing it is **triage**, and JEV is one triage provider.
- Background facts (education, experience) are entered once; both stages read them.
- **Look forward only.** A profile edit applies to postings evaluated afterward and
  never re-runs an old verdict. No policy hash.
- A JD content change does not re-evaluate. Each posting is evaluated once.
- There is no manual re-evaluate escape hatch.
- Each result records the profile `version` it ran under (display only, never a
  trigger).
- Title filters move into the profile. This answers #203 question 4: they are
  DB-owned now.
- Packs become system-owned defaults.
- Also in scope: an override that rescues a requirements discard, a confirmation gate
  before paid stages, and one stored verdict for all readers.

## Design

### Profile (`candidate_profile`, one row, id=1)

| Section | Fields | Read by |
|---|---|---|
| Search scope | title include, title exclude, max age days | fetch |
| Hard requirements | locations, work authorization (closed vocabulary), clearance, exclude internships, exclude contract | requirements |
| Background | education rows (degree, field), experience rows (title, company, years) | requirements, triage |
| Preferences | target roles, open to, not interested | triage |
| Packs | optional custom question packs; empty = committed defaults | triage |

Columns beyond the sections: `version` (+1 per actual change), `actor`, `changed_at`,
`confirmed_at`, `updated_at`.

- **Derived fields.** Highest degree is the maximum over the education rows. Total
  years is the sum of the experience rows. Both are computed in one worker function
  and one web function, and both are tested against the same fixture.
- **Packs.** The defaults are today's `apps/worker/jev.example/` packs (YOE uses
  `above_candidate`, so they fit any experience level). Custom packs keep the
  operator's private, measured packs (`three_plus`). The defaults stay labelled
  unvalidated until #182 measures them.
- **Seeding.** The migration reads, once, `candidate_preferences` + `jev_profile` +
  config `title_filter`/`title_exclude`/`max_age_days` + `jev_dir`. The DB is backed up
  first. After that the row wins and differing config is logged (the watchlist
  precedent). Both old tables are dropped.
- **Surfaces.** One Settings form. MCP `get_candidate_profile` / `set_candidate_profile`
  replace `get/set_preferences` and `get/set_jev_profile`. One
  `/api/v1/candidate-profile` route replaces `/preferences` and `/jev-profile`.
  Validation is shared with the form.

### Evaluation lifecycle

A `new` posting moves through: fetch -> requirements -> triage (if configured) -> a
stored verdict. Each stage runs at most once per posting.

- **Window.** Both stages share one window: `posted_at`, else `created_at`, within N
  days (default 7, today's `JEV_MAX_AGE_DAYS`).
  - Inside the window, unfinished work keeps its place in the queue: deferred by a cap
    or a breaker, or a retryable provider error.
  - Outside it, the posting's verdict is final `not_evaluated`, and Activity counts it
    (PRINCIPLES 5).
- **No re-queue.** Delete `--rescreen-screened`, the JEV policy hash with its
  `jev_current_policy_sha256` setting, and the source-revision re-queue in both stages.
  `evaluator_version` and backend/model stay recorded and are never compared.
- **Profile version.** `job_screenings.profile_version` and
  `job_jev_assessments.profile_version` record the version each stage ran under.
- **One discard shape.** The fetch-time deterministic gate writes a requirements result
  (the same `screen` shape as a screen-time rule discard) and leaves
  `pipeline_status='new'`. Legacy `discarded` rows with an embedded screen verdict are
  migrated once into that shape, so neither reader keeps the legacy branch.
- **Stored verdict.** `job_postings.verdict` is one of `pending | keep | skip |
  discarded | not_evaluated`, plus `verdict_at`.
  - The worker writes it when a posting's last configured stage finishes, or when the
    posting leaves the window.
  - With no triage backend configured, passing requirements yields `keep`.
  - Rows evaluated before the cutover get a backfilled verdict computed from today's
    status rules once, during the migration, and keep it.
- **Title filter** still drops postings before storage. Loosening it lets still-listed
  postings arrive as new postings, evaluated under the current profile. Rule: the title
  filter decides what the system looks at; the profile decides, once, what it thinks
  of it.

### Readers

The effective status is `override.decision` if an override exists, else
`job_postings.verdict`. Web and MCP each read that with one `CASE`. All of the
following are deleted: the ported status SQL, `stale`, `JEV_MODE_SQL` (the "for you"
mode switch becomes `verdict='keep'`), and the legacy discard branch. One shared
fixture test runs on each side.

The override (`override_triage`, web "Not interested") also accepts a `discarded`
posting, and `keep` rescues it. It is no longer bound to `source_content_revision`,
because nothing else re-evaluates on content change either.

### Confirmation gate

`candidate_profile.confirmed_at` is null on a fresh install.

- Until it is set, the worker runs fetch plus the free deterministic gates only. Model
  stages leave postings `pending`.
- Settings and MCP `get_setup_status` show an intake summary: fetched, dropped by title
  filter, discarded by requirement (by reason).
- The operator fixes the profile or overrides wrong discards, then confirms. Pending
  in-window postings then get the model stages.
- Deterministic discards made before confirmation stay; the override is the rescue.

## Principles

- **2 (deterministic for facts):** unchanged. Requirements still extract facts, and
  code decides.
- **3 (err toward keep) - conflict, surfaced.** Look-forward makes a wrong discard
  permanent unless a human acts, and P3's premise is that a lost job is unrecoverable
  and invisible. Mitigations: discards stay visible in the Discarded bucket, the
  override rescues any of them (#226), and nothing paid runs until the operator has
  seen the intake summary (#227). Accepted by the operator as the price of a
  predictable rule.
- **4 (cheap assistance):** the confirmation gate means a fresh install buys no
  judgment before review.
- **5 (fail loud):** aged-out postings are counted, not silently dropped.
- **9 (Prisma owns schema; backup before destructive change):** the profile migration,
  the discard migration, and dropping the two old tables all take a DB backup first.
- **14 (defer with reason):** the extension point is deferred to #222; stage merging
  and backend measurement to #180/#182.

## Slices

| Issue | Slice | Size |
|---|---|---|
| #224 | A: profile row, migration, one form, one MCP pair, one route, triage naming | 2-3 d |
| #225 | B: shared window, no re-queue, profile version, one discard shape, stored verdict, aged-out count | 1.5-2 d |
| #226 | C: readers on the stored verdict; override rescues discards; delete ported SQL | 1 d |
| #227 | D: confirmation gate and intake summary | 1 d |

Order: A -> B -> C; D after A, and its counts need B. Blocked on #157 being accepted and
closed.

## Rejected alternatives

- **Keep two profile tables behind one form.** Fewer migrations, but the duplicated
  degree survives in storage, and the operator wants one profile.
- **Re-run on profile change (hash or version compare).** Rejected by the look-forward
  decision. It spends quota on old postings, and it makes verdicts move under the
  user.
- **Flag results stale on profile change.** Moot once nothing re-runs; the recorded
  version is enough to show what judged a row.
- **Re-evaluate on JD change.** Rare (SmartRecruiters only), and it is the one rule
  exception that would keep revision logic alive in both stages and both readers.
- **Manual re-evaluate tool.** An exception to look-forward; the override covers the
  real need, which is rescuing a wrong discard.
- **Share the status SQL through #209 (MCP reads via `/api/v1`).** That fixes the
  duplication but leaves a 100-line derivation in place. A stored verdict is possible
  because look-forward makes the verdict immutable, and it deletes the derivation.
- **Drop fetch-time discards before storage (like the title filter).** That would make
  loosening a location recover postings, but it loses the Discarded bucket's
  visibility (PRINCIPLES 5).
- **One results table / criteria registry:** #222. **One LLM call for both stages:**
  #180; it varies rubric and model together and voids both measured bases.

## Open questions for approval

1. Stored `job_postings.verdict` (recommended) vs. a shared derivation function. The
   stored column is the larger schema change but deletes the most code.
2. Confirmation-gate semantics: model stages wait until confirmation (recommended) vs.
   only a small capped calibration pass.
