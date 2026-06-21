# Discovered Jobs — posting-date sort, bulk actions, audit reframe

Date: 2026-06-21
Status: design approved, ready for implementation plan

## Problem

The Discovered Jobs view has three rough edges:

1. **Sort is opaque.** Rows are ordered `score desc, id asc`. There's no way to
   see what's *freshest on the market* — and `created_at` (scrape time) is a
   biased proxy: adding a watchlist company dumps its whole backlog on one day,
   so everything looks "new."
2. **No bulk actions.** Clearing noise or rescuing several rows is one-by-one.
3. **The Discard tab is a firehose treated like a work queue.** It presents as a
   peer of Matched ("process this too"), but it's really an *audit log*: you're
   not meant to action every row, only catch scorer mistakes and occasionally
   rescue one. Most of it is confirmed junk that wastes attention.

## Decisions (all confirmed with the user)

- **Sort:** capture the real posting date and add a sort toggle. `Best match`
  (default, current order) + `Newest posted`.
- **Matched bulk action:** **Remove** (terminal hide), not Discard — bulk-rejected
  noise should disappear everywhere, not pile up on a second page.
- **Remove semantics:** a terminal `removed` pipeline status that hides the row
  from every tab AND is inert to the worker (no re-score / re-tailor / re-notify).
  Chosen over hard-delete, which would boomerang: dedup is `(source, external_id)`,
  so a deleted-but-still-open posting gets re-inserted and reprocessed next fetch.
- **Discard tab:** reframe as an audit view, not a queue.
  - Default to the **near-miss band** (score 60–74) — the only slice where a real
    false-negative hides. Sub-filters: `Near-miss` (default), `Disqualified`,
    `All` (the full firehose, on demand).
  - Add **Remove all in this view** to clear the pile in one click.
  - Bulk **Reopen** and bulk **Remove** on selected rows.

## Out of scope (YAGNI — say if wanted)

- A "Removed" tab / browse-removed UI. Remove is reversible at the DB level only;
  the bulk-remove confirm dialog is the safety net.
- Bulk actions on the Failed tab.
- Bulk Apply (apply stays one-by-one by design).
- Changing existing per-row actions (View JD / Download / Mark Applied / per-row
  Discard-X on active / Reopen on discarded) — left untouched.

---

## 1. Posting date (`posted_at`)

### Schema
Add to `job_postings` (Prisma owns the schema; then `make db-push`):

```prisma
posted_at  String?  // board-provided posting date, normalized to YYYY-MM-DD; null only on legacy rows pre-backfill
```

### Worker — capture
Verified live (2026-06-10/06-21) which of the 5 active boards expose a date:

| Board | Field | Format | Notes |
|---|---|---|---|
| greenhouse | `first_published` | ISO 8601 | also has `updated_at`, `application_deadline` |
| lever | `createdAt` | epoch ms | convert |
| ashby | `publishedAt` | ISO 8601 | |
| workday | `startDate` | `YYYY-MM-DD` | in the per-job **detail** payload we already fetch |
| pinpoint | — | — | no posting date; only `deadline_at` (usually null) |

Each parser emits `posted_at` **normalized to date-only `YYYY-MM-DD`** (truncate
datetimes; lever epoch→date). Pinpoint omits it.

Invariant — **`posted_at` is never null for new rows.** In `db.upsert_postings`:

```python
posted_at = (p.get("posted_at") or now)[:10]   # board date, else scrape date (truncated to day)
```

This keeps the sort a plain `posted_at desc` with no NULL/coalesce handling.
Date-only across all rows → one comparable format (created_at, the fallback
source, stays a full ISO datetime and is untouched).

One-time backfill for rows already in the DB:

```sql
UPDATE job_postings SET posted_at = substr(created_at, 1, 10) WHERE posted_at IS NULL;
```

### Schema-drift guard
Add `posted_at` to the worker's SQL fixture so `make check-schema` stays green.

---

## 2. Sort toggle (web)

`getJobPostings` gains a `sort` param: `'score' | 'posted'` (default `'score'`).

- `score`  → `orderBy: [{ score: 'desc' }, { id: 'asc' }]` (current behavior)
- `posted` → `orderBy: [{ posted_at: 'desc' }, { id: 'desc' }]`

UI: a `Select` next to the existing filters — `Best match` / `Newest posted`.
Applies across all buckets (harmless; primarily useful on Matched).

---

## 3. Bulk actions + selection (web)

### Selection UI (shared)
- Checkbox column + header "select all on page" (page-scoped, since paginated).
- Selection state clears on page change, bucket change, and filter change.
- A bulk action bar renders when ≥1 row is selected; its buttons depend on the
  active bucket:
  - **Matched:** `Remove selected`
  - **Discarded:** `Reopen selected`, `Remove selected`
  - **Failed:** none

### `Remove all in this view` (Discarded only)
A button (separate from selection) that removes **every row matching the current
filter** — not just the current page. Guarded by a confirm dialog showing the
count: *"Remove N jobs? They'll be hidden from all tabs."*

### Server actions (`lib/actions.ts`)
Thin wrappers over the existing single-row update logic:

```ts
bulkRemove(ids: number[])   // UPDATE ... SET pipeline_status='removed' WHERE id IN (...)
bulkReopen(ids: number[])   // → 'scored'  (mirror of reopenJobPosting)
removeAllInView(filter)     // UPDATE ... SET pipeline_status='removed' WHERE <same where as getJobPostings>
```

`bulkRemove`/`removeAllInView` set `updated_at` like the single-row paths do.

### The `removed` status is self-hiding
`removed` is automatically invisible everywhere with **no extra filter code**:

- **Matched** requires `pipeline_status ∈ ACTIVE_PIPELINE_STATUSES`
  (`scored|tailored|notified`) — `removed` not included.
- **Discarded** requires `pipeline_status='discarded'` OR below-threshold-active —
  `removed` matches neither.
- **Failed** requires `pipeline_status='failed'`.
- **Worker** ingest is `INSERT ... ON CONFLICT(source,external_id) DO NOTHING`
  and the pipeline only ever selects rows by explicit status (`new`/`scored`/…),
  so a `removed` row is never re-inserted and never reprocessed. **No worker
  change needed for remove.**

---

## 4. Near-miss reframe (web)

Replace the Discarded sub-filter values `all | disqualified | lowscore` with
`nearmiss | disqualified | all`, default `nearmiss`:

- **nearmiss** → active rows with `NEAR_MISS_FLOOR ≤ score < MATCH_SCORE_THRESHOLD`
  (i.e. `60 ≤ score < 75`). The rescue band.
- **disqualified** → unchanged (hard-DQ rows).
- **all** → unchanged (the full firehose: discarded-status OR below-threshold).

Add `NEAR_MISS_FLOOR = 60` to `lib/constants.ts` (tunable; `MATCH_SCORE_THRESHOLD`
is already there = 75).

Optional polish (low priority): relabel the tab "Discarded" → "Discarded (audit)"
or visually demote it so it doesn't read as a second work queue. Not required for
correctness.

---

## 5. Job-title hyperlink (web)

Wrap the title cell in `DiscoveredJobsTable` with
`<a href={job.job_url} target="_blank" rel="noopener noreferrer">` so the title
opens the live application/posting page. Keep the existing `View JD` button (that
opens the parsed-JD modal — different thing). Applies in all buckets; `job_url` is
always populated.

---

## Testing notes

- **Worker:** unit-test each parser emits the expected `posted_at` (date-only) for
  a fixture with the date field, and `None` for pinpoint / a missing field. Test
  `upsert_postings` fallback-to-`now[:10]` when `posted_at` absent.
- **Web (Jest):** `getJobPostings` ordering for both `sort` values; near-miss
  filter bounds (64/74 in, 59/75 out); `removed` rows absent from all three
  buckets; `bulkRemove`/`bulkReopen`/`removeAllInView` flip the right rows.
- **Component:** selection clears on bucket/filter/page change; bulk bar shows the
  right buttons per bucket; Remove confirm dialog fires; title renders as a link
  to `job_url`.
- **Schema drift:** `make check-schema` passes with `posted_at` in the fixture.
- Keep all three docs in sync in the implementing commit(s): `SPEC.md`
  (capabilities/data model), `PROGRESS.md` (close/added entries), `CHANGELOG.md`.
