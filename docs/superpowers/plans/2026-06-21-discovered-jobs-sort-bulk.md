# Discovered Jobs — sort, bulk actions, audit reframe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a posting-date sort toggle, bulk Remove/Reopen actions, a self-hiding `removed` status, and a near-miss audit reframe to the Discovered Jobs view; make the job title a link to the live posting.

**Architecture:** The worker captures each board's posting date into a new nullable `posted_at` column (never null for new rows — falls back to scrape date). The web layer adds a sort param and a `nearmiss` discard sub-filter to `getJobPostings`, three bulk server actions backed by `updateMany`, and selection + a bulk bar in the table component. `removed` is a new terminal `pipeline_status` that is invisible to every bucket query and inert to the worker (no schema/worker change needed for it).

**Tech Stack:** Next.js 14 server actions + Prisma (SQLite), React client component (Jest + Testing Library), Python 3.11 worker (pytest). Spec: `docs/superpowers/specs/2026-06-21-discovered-jobs-sort-bulk-design.md`.

## Global Constraints

- **Prisma owns the schema.** Change `apps/web/prisma/schema.prisma`, then `make db-push`. The worker issues no DDL. Mirror every column change into `apps/worker/tests/fixtures/schema.sql` or `make check-schema` fails.
- **Git identity:** commit as `drink970082 <howdywu@gmail.com>` (use `git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit ...`). Branch: `dev`. Keep every commit green.
- **Worker modules stay pure + DI.** No new network in adapters; tests use inline payloads / fixtures.
- **Date format:** `posted_at` is always date-only `YYYY-MM-DD` (or null on legacy rows pre-backfill).
- **Constants:** `MATCH_SCORE_THRESHOLD = 75` and the new `NEAR_MISS_FLOOR = 60` live in `apps/web/src/lib/constants.ts`. Near-miss band is `60 ≤ score < 75`.
- **Test runner caveat (this environment):** RTK mis-summarizes raw `pytest`/`jest`/`node`. For targeted runs prefix with `rtk proxy` (e.g. `rtk proxy python3 -m pytest ...`). `make test-worker` / `make test-web` are fine as-is.
- **No new dependencies:** selection uses native `<input type="checkbox">`; the destructive confirm uses `window.confirm` (already the pattern — see `Dashboard.tsx` `handleDeleteApplication`).

---

### Task 1: Add `posted_at` column to the schema

**Files:**
- Modify: `apps/web/prisma/schema.prisma` (the `job_postings` model, ~line 52)
- Modify: `apps/worker/tests/fixtures/schema.sql` (the `job_postings` table, ~line 38)

**Interfaces:**
- Produces: a nullable `posted_at String?` / `"posted_at" TEXT` column on `job_postings`, consumed by Tasks 2–5.

- [ ] **Step 1: Add the column to Prisma, then run the drift guard to see it fail (red)**

In `apps/web/prisma/schema.prisma`, in `model job_postings`, add after the `updated_at` line:

```prisma
  posted_at       String? // board-provided posting date, normalized to YYYY-MM-DD; null only on legacy rows pre-backfill
```

- [ ] **Step 2: Run the schema-drift guard — expect FAIL**

Run: `make check-schema`
Expected: FAIL — `DRIFT: "job_postings" is missing column "posted_at"`

- [ ] **Step 3: Mirror the column into the worker fixture (green)**

In `apps/worker/tests/fixtures/schema.sql`, in `CREATE TABLE "job_postings"`, add after the `"updated_at" TEXT,` line (keep it before the `CONSTRAINT` line):

```sql
    "posted_at" TEXT,
```

- [ ] **Step 4: Run the drift guard again — expect PASS**

Run: `make check-schema`
Expected: PASS — `schema.sql is in sync with apps/web/prisma/schema.prisma`

- [ ] **Step 5: Push the schema into SQLite and backfill existing rows**

Run: `make db-push`
Then backfill legacy rows so `posted_at` is never null going forward (run once; harmless if the DB is empty or absent):

Run: `sqlite3 db/dev.db "UPDATE job_postings SET posted_at = substr(created_at, 1, 10) WHERE posted_at IS NULL;"`

(`db/` is a gitignored directory mount; adjust the filename if your local DB differs. If `sqlite3` isn't installed or there's no DB yet, skip — new rows get `posted_at` from Task 3.)

- [ ] **Step 6: Confirm the worker schema-sync pytest still passes**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_schema_sync.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/web/prisma/schema.prisma apps/worker/tests/fixtures/schema.sql
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(schema): add job_postings.posted_at"
```

---

### Task 2: Worker captures `posted_at` in every adapter

**Files:**
- Modify: `apps/worker/ats_worker/util.py` (add `to_iso_date`; add `posted_at` to `POSTING_FIELDS`)
- Modify: `apps/worker/ats_worker/fetch/greenhouse.py`, `lever.py`, `ashby.py`, `workday.py` (real dates)
- Modify: `apps/worker/ats_worker/fetch/pinpoint.py`, `smartrecruiters.py`, `oracle.py`, `workable.py`, `jobvite.py` (None / schema.org)
- Test: `apps/worker/tests/test_util.py`, `apps/worker/tests/test_fetch.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `to_iso_date(value) -> str | None` in `util.py`; every adapter dict now contains a `posted_at` key (str `YYYY-MM-DD` or `None`). `POSTING_FIELDS` includes `"posted_at"`. Consumed by Task 3.

> **Why all 9 adapters at once:** `test_adapter_emits_canonical_fields` asserts `set(p.keys()) == set(POSTING_FIELDS)`. Adding `posted_at` to `POSTING_FIELDS` without every adapter emitting it (or vice-versa) fails that test — so the helper, the contract, and all adapters must land in one commit to stay green.

- [ ] **Step 1: Write failing tests for `to_iso_date`**

Add to `apps/worker/tests/test_util.py`:

```python
from ats_worker.util import to_iso_date


def test_to_iso_date_keeps_iso_date_prefix():
    assert to_iso_date("2026-04-17T05:58:03-04:00") == "2026-04-17"
    assert to_iso_date("2026-04-17") == "2026-04-17"


def test_to_iso_date_converts_epoch_millis():
    assert to_iso_date(1553186035299) == "2019-03-21"   # lever createdAt (ms, UTC)


def test_to_iso_date_none_or_garbage_is_none():
    assert to_iso_date(None) is None
    assert to_iso_date("") is None
    assert to_iso_date("bad") is None
```

- [ ] **Step 2: Run them — expect FAIL**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_util.py -k to_iso_date -v`
Expected: FAIL — `ImportError: cannot import name 'to_iso_date'`

- [ ] **Step 3: Implement `to_iso_date` and extend `POSTING_FIELDS`**

In `apps/worker/ats_worker/util.py`, add the import near the top (below `import re`):

```python
from datetime import datetime, timezone
```

Add `"posted_at",` as the last entry of `POSTING_FIELDS`:

```python
POSTING_FIELDS = (
    "source",
    "external_id",
    "company_name",
    "job_title",
    "location",
    "job_url",
    "description",
    "posted_at",
)
```

Add the helper (below `POSTING_FIELDS`):

```python
def to_iso_date(value) -> str | None:
    """Normalize a board posting date to 'YYYY-MM-DD', or None.

    Accepts ISO-8601 strings (greenhouse first_published, ashby publishedAt,
    workday startDate — we keep the date prefix) and epoch-millisecond ints
    (lever createdAt). Anything unparseable returns None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # ponytail: epoch-ms is the only numeric date any board sends (lever)
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    s = str(value)
    return s[:10] if len(s) >= 10 else None
```

- [ ] **Step 4: Run the helper tests — expect PASS**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_util.py -k to_iso_date -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write failing tests for per-adapter `posted_at`**

Add to `apps/worker/tests/test_fetch.py`:

```python
def test_greenhouse_captures_posted_at():
    payload = {"jobs": [{"id": 1, "title": "X", "absolute_url": "http://x",
                         "content": "y", "first_published": "2026-04-17T05:58:03-04:00"}]}
    assert greenhouse.parse_jobs(payload, company_name="Acme")[0]["posted_at"] == "2026-04-17"


def test_lever_captures_posted_at():
    payload = [{"id": "1", "text": "X", "hostedUrl": "http://x",
                "descriptionPlain": "y", "createdAt": 1553186035299}]
    assert lever.parse_jobs(payload, company_name="Acme")[0]["posted_at"] == "2019-03-21"


def test_ashby_captures_posted_at():
    payload = {"jobs": [{"id": "1", "title": "X", "jobUrl": "http://x",
                         "descriptionPlain": "y", "publishedAt": "2024-03-04T14:29:08.532+00:00"}]}
    assert ashby.parse_jobs(payload, company_name="Acme")[0]["posted_at"] == "2024-03-04"


def test_pinpoint_has_no_posted_at():
    posting = pinpoint.parse_jobs(load("pinpoint.json"), company_name="Acme")[0]
    assert posting["posted_at"] is None
```

And for workday (it builds from a detail payload via `parse_job`). Add to `apps/worker/tests/test_fetch_new.py` (or wherever workday is tested — search `parse_job`); if unsure, add to `test_fetch.py` with an import:

```python
def test_workday_captures_posted_at():
    from ats_worker.fetch import workday
    info = {"jobPostingInfo": {"id": "g1", "title": "X", "externalUrl": "http://x",
                               "jobDescription": "y", "startDate": "2026-04-17"}}
    assert workday.parse_job(info, "Acme")["posted_at"] == "2026-04-17"
```

- [ ] **Step 6: Run them — expect FAIL**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_fetch.py -k posted_at -v`
Expected: FAIL — `KeyError: 'posted_at'`

- [ ] **Step 7: Emit `posted_at` from every adapter**

In each adapter's canonical dict, add a `posted_at` entry:

- `greenhouse.py` (in `parse_jobs`, after `"description": ...`): `"posted_at": to_iso_date(j.get("first_published")),`
- `lever.py`: `"posted_at": to_iso_date(j.get("createdAt")),`
- `ashby.py`: `"posted_at": to_iso_date(j.get("publishedAt")),`
- `workday.py` (in `parse_job`): `"posted_at": to_iso_date(info.get("startDate")),`
- `jobvite.py` (in `parse_page`): `"posted_at": to_iso_date(ld.get("datePosted")),` (schema.org field; safe — `None` if absent)
- `pinpoint.py`, `smartrecruiters.py` (`parse_job`), `oracle.py` (`parse_job`), `workable.py` (`parse_jobs`): `"posted_at": None,`

Each of greenhouse/lever/ashby/jobvite needs `to_iso_date` imported — they already do `from ats_worker.util import html_to_text`; change to:

```python
from ats_worker.util import html_to_text, to_iso_date
```

(workday too.) pinpoint/smartrecruiters/oracle/workable use the literal `None`, no import change.

- [ ] **Step 8: Run the full fetch + util suites — expect PASS**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_fetch.py tests/test_fetch_new.py tests/test_util.py -v`
Expected: PASS — including the pre-existing `test_adapter_emits_canonical_fields` (key sets now match with `posted_at`).

- [ ] **Step 9: Commit**

```bash
git add apps/worker/ats_worker/util.py apps/worker/ats_worker/fetch/ apps/worker/tests/test_util.py apps/worker/tests/test_fetch.py apps/worker/tests/test_fetch_new.py
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(worker): capture posted_at from board adapters"
```

---

### Task 3: Worker writes `posted_at` on ingest (with scrape-date fallback)

**Files:**
- Modify: `apps/worker/ats_worker/db.py` (`_INSERT` and `upsert_postings`, lines 33–67)
- Test: `apps/worker/tests/test_db.py`

**Interfaces:**
- Consumes: adapter dicts carrying `posted_at` (Task 2).
- Produces: every inserted `job_postings` row has a non-null `posted_at` (board date, else `now[:10]`).

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_db.py`:

```python
def test_upsert_stores_board_posted_at(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("1", posted_at="2026-04-17")], now=NOW)
    row = db.get_by_status(conn, "new")[0]
    assert row["posted_at"] == "2026-04-17"


def test_upsert_falls_back_to_scrape_date_when_no_posted_at(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [posting("2")], now=NOW)   # make_posting has no posted_at
    row = db.get_by_status(conn, "new")[0]
    assert row["posted_at"] == NOW[:10]                 # "2026-06-04"
```

- [ ] **Step 2: Run them — expect FAIL**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_db.py -k posted_at -v`
Expected: FAIL — `sqlite3.OperationalError` (column not in INSERT) or `KeyError`/`None`.

- [ ] **Step 3: Add `posted_at` to the insert**

In `apps/worker/ats_worker/db.py`, update `_INSERT` columns and values:

```python
_INSERT = """
INSERT INTO job_postings
    (source, external_id, company_slug, company_name, job_title, location, job_url,
     description, posted_at, pipeline_status, attempts, created_at)
VALUES
    (:source, :external_id, :company_slug, :company_name, :job_title, :location, :job_url,
     :description, :posted_at, 'new', 0, :created_at)
ON CONFLICT(source, external_id) DO NOTHING
"""
```

In `upsert_postings`, add to the params dict (after `"description": p["description"],`):

```python
                # posted_at is date-only; fall back to the scrape day so it's never null.
                "posted_at": (p.get("posted_at") or now)[:10],
```

- [ ] **Step 4: Run the db suite — expect PASS**

Run (from `apps/worker/`): `rtk proxy python3 -m pytest tests/test_db.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/db.py apps/worker/tests/test_db.py
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(worker): persist posted_at on ingest with scrape-date fallback"
```

---

### Task 4: `getJobPostings` — sort param + near-miss sub-filter

**Files:**
- Modify: `apps/web/src/lib/constants.ts` (add `NEAR_MISS_FLOOR`)
- Modify: `apps/web/src/lib/actions.ts` (extract `buildJobWhere`; add `JobSort`; change `DiscardType`; add `sort` + `nearmiss` handling)
- Test: `apps/web/src/__tests__/actions.int.test.ts`

**Interfaces:**
- Consumes: `posted_at` column (Task 1).
- Produces: `buildJobWhere(params)` (used by Task 5's `removeAllInView`); `export type JobSort = 'score' | 'posted'`; `export type DiscardType = 'disqualified' | 'nearmiss'`; `getJobPostings` accepts `sort?: JobSort`.

- [ ] **Step 1: Add the constant**

In `apps/web/src/lib/constants.ts`, after the `MATCH_SCORE_THRESHOLD` line:

```ts
// Floor of the "near-miss" band shown by default in the Discarded audit view:
// NEAR_MISS_FLOOR ≤ score < MATCH_SCORE_THRESHOLD. The only slice where a real
// false-negative hides; deeper-junk rows are reachable via the "All" sub-filter.
export const NEAR_MISS_FLOOR = 60
```

- [ ] **Step 2: Write/adjust failing integration tests**

In `apps/web/src/__tests__/actions.int.test.ts`, **replace** the existing `getJobPostings discardType narrows the discarded bucket` test with:

```ts
test('getJobPostings discardType narrows the discarded bucket', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'dq', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'on-site' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'near', score: 70, pipeline_status: 'scored' }) })  // 60..74 -> near-miss
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'deep', score: 40, pipeline_status: 'scored' }) })  // below the floor
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'man', score: 88, pipeline_status: 'discarded', score_detail: null }) })  // manual discard

    const dq = await getJobPostings({ bucket: 'discarded', discardType: 'disqualified' })
    expect(dq.data.map((d) => d.external_id)).toEqual(['dq'])

    const near = await getJobPostings({ bucket: 'discarded', discardType: 'nearmiss' })
    expect(near.data.map((d) => d.external_id)).toEqual(['near'])   // excludes deep(40) and man(88)

    const all = await getJobPostings({ bucket: 'discarded' })
    expect(all.data.map((d) => d.external_id).sort()).toEqual(['deep', 'dq', 'man', 'near'])
})
```

Add a new sort test below it:

```ts
test('getJobPostings sort=posted orders by posted_at desc', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'old', score: 80, pipeline_status: 'scored', posted_at: '2026-01-01' }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'new', score: 80, pipeline_status: 'scored', posted_at: '2026-06-01' }) })

    const byScore = await getJobPostings({ bucket: 'matched' })                  // default: score desc, id asc
    expect(byScore.data.map((d) => d.external_id)).toEqual(['old', 'new'])       // tie score -> id asc

    const byPosted = await getJobPostings({ bucket: 'matched', sort: 'posted' })
    expect(byPosted.data.map((d) => d.external_id)).toEqual(['new', 'old'])      // newest posted first
})
```

- [ ] **Step 3: Run them — expect FAIL**

Run (from `apps/web/`): `rtk proxy npx jest --config jest.integration.config.ts -t "getJobPostings"`
Expected: FAIL — `nearmiss` not handled (returns firehose) and `sort` ignored.

- [ ] **Step 4: Refactor `getJobPostings` and add the behavior**

In `apps/web/src/lib/actions.ts`:

Change the `DiscardType` type and add `JobSort` (replace the existing `DiscardType` line ~64):

```ts
// Within the Discarded audit view you narrow to one slice (default near-miss):
//   nearmiss     — live, NEAR_MISS_FLOOR ≤ score < threshold (where false-negatives hide)
//   disqualified — LLM hard-constraint failures
export type DiscardType = 'disqualified' | 'nearmiss'

// Sort for the discovered queue: best match (score) or freshest posting.
export type JobSort = 'score' | 'posted'
```

Add `NEAR_MISS_FLOOR` to the constants import at the top of the file:

```ts
import { STATUSES, CATEGORIES, VALID_SOURCES, MATCH_SCORE_THRESHOLD, NEAR_MISS_FLOOR } from '@/lib/constants'
```

Extract the where-building (lines ~80–126) into a module-level helper and add a `nearMiss` branch:

```ts
function buildJobWhere(params: {
    bucket?: JobBucket
    search?: string
    minScore?: number
    discardType?: DiscardType
}): Prisma.job_postingsWhereInput {
    const bucket = params.bucket ?? 'matched'
    const search = params.search || ''
    const minScore = params.minScore

    const belowThreshold: Prisma.job_postingsWhereInput = {
        pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
        score: { lt: MATCH_SCORE_THRESHOLD },
    }
    const nearMiss: Prisma.job_postingsWhereInput = {
        pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
        score: { gte: NEAR_MISS_FLOOR, lt: MATCH_SCORE_THRESHOLD },
    }
    const disqualified: Prisma.job_postingsWhereInput = {
        pipeline_status: 'discarded',
        OR: [
            { score_detail: { contains: '"disqualified": true' } },
            { score_detail: { contains: '"disqualified":true' } },
        ],
    }

    let bucketFilter: Prisma.job_postingsWhereInput
    if (bucket === 'failed') {
        bucketFilter = { pipeline_status: 'failed' }
    } else if (bucket === 'discarded') {
        if (params.discardType === 'disqualified') {
            bucketFilter = disqualified
        } else if (params.discardType === 'nearmiss') {
            bucketFilter = nearMiss
        } else {
            bucketFilter = { OR: [{ pipeline_status: 'discarded' }, belowThreshold] }
        }
    } else {
        bucketFilter = {
            pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
            score: { gte: MATCH_SCORE_THRESHOLD },
        }
    }

    return {
        AND: [
            bucketFilter,
            minScore != null ? { score: { gte: minScore } } : {},
            search
                ? { OR: [{ company_name: { contains: search } }, { job_title: { contains: search } }] }
                : {},
        ],
    }
}
```

Rewrite `getJobPostings` to use it and apply the sort:

```ts
export async function getJobPostings(params: {
    bucket?: JobBucket
    search?: string
    page?: number
    size?: number
    minScore?: number
    discardType?: DiscardType
    sort?: JobSort
}) {
    const page = params.page ?? 0
    const size = params.size ?? 25
    const where = buildJobWhere(params)
    const orderBy: Prisma.job_postingsOrderByWithRelationInput[] =
        params.sort === 'posted'
            ? [{ posted_at: 'desc' }, { id: 'desc' }]
            : [{ score: 'desc' }, { id: 'asc' }]

    const [data, total] = await Promise.all([
        prisma.job_postings.findMany({ where, orderBy, skip: page * size, take: size }),
        prisma.job_postings.count({ where }),
    ])

    return { data, total }
}
```

- [ ] **Step 5: Run the integration suite — expect PASS**

Run (from `apps/web/`): `rtk proxy npx jest --config jest.integration.config.ts -t "getJobPostings"`
Expected: PASS (buckets, pagination, discardType/near-miss, sort).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/lib/constants.ts apps/web/src/lib/actions.ts apps/web/src/__tests__/actions.int.test.ts
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(web): posting-date sort + near-miss sub-filter in getJobPostings"
```

---

### Task 5: Bulk server actions (`bulkRemove`, `bulkReopen`, `removeAllInView`)

**Files:**
- Modify: `apps/web/src/lib/actions.ts` (add three actions, after `reopenJobPosting`)
- Test: `apps/web/src/__tests__/actions.int.test.ts`

**Interfaces:**
- Consumes: `buildJobWhere` (Task 4).
- Produces: `bulkRemove(ids: number[])`, `bulkReopen(ids: number[])`, `removeAllInView(filter)` — each returns `{ success: true, count } | { success: false, error }`. `removeAllInView`'s `filter` is `{ bucket?, search?, minScore?, discardType? }`. Consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

Add to `apps/web/src/__tests__/actions.int.test.ts` (import the three actions in the top `import { ... } from '@/lib/actions'` block):

```ts
test('bulkRemove hides rows from every bucket', async () => {
    const a = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'b1', score: 90, pipeline_status: 'scored' }) })
    const b = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'b2', score: 85, pipeline_status: 'notified' }) })
    const res = await bulkRemove([a.id, b.id])
    expect(res).toEqual({ success: true, count: 2 })
    expect((await getJobPostings({ bucket: 'matched' })).data).toHaveLength(0)
    expect((await prisma.job_postings.findUnique({ where: { id: a.id } }))!.pipeline_status).toBe('removed')
})

test('bulkReopen sends discarded rows back to scored', async () => {
    const a = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'r1', score: 90, pipeline_status: 'discarded' }) })
    const res = await bulkReopen([a.id])
    expect(res).toEqual({ success: true, count: 1 })
    expect((await prisma.job_postings.findUnique({ where: { id: a.id } }))!.pipeline_status).toBe('scored')
})

test('removeAllInView removes only rows matching the filter', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'keep', score: 90, pipeline_status: 'scored' }) })   // matched
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'gone', score: 65, pipeline_status: 'scored' }) })   // near-miss
    const res = await removeAllInView({ bucket: 'discarded', discardType: 'nearmiss' })
    expect(res).toEqual({ success: true, count: 1 })
    expect((await getJobPostings({ bucket: 'matched' })).data.map((d) => d.external_id)).toEqual(['keep'])
    expect((await getJobPostings({ bucket: 'discarded', discardType: 'nearmiss' })).data).toHaveLength(0)
})
```

- [ ] **Step 2: Run them — expect FAIL**

Run (from `apps/web/`): `rtk proxy npx jest --config jest.integration.config.ts -t "bulk|removeAllInView"`
Expected: FAIL — actions not exported.

- [ ] **Step 3: Implement the three actions**

In `apps/web/src/lib/actions.ts`, after `reopenJobPosting`:

```ts
// Terminal hide: a 'removed' posting is invisible to every bucket query and inert
// to the worker (ingest is ON CONFLICT DO NOTHING; the pipeline only selects by
// explicit status), so it never re-scores/re-notifies. See the design spec.
export async function bulkRemove(ids: number[]) {
    try {
        const res = await prisma.job_postings.updateMany({
            where: { id: { in: ids } },
            data: { pipeline_status: 'removed', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function bulkReopen(ids: number[]) {
    try {
        const res = await prisma.job_postings.updateMany({
            where: { id: { in: ids } },
            data: { pipeline_status: 'scored', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// Clear the whole current Discarded view in one click (respects bucket + sub-filter
// + search + minScore via the same where-builder getJobPostings uses).
export async function removeAllInView(filter: {
    bucket?: JobBucket
    search?: string
    minScore?: number
    discardType?: DiscardType
}) {
    try {
        const res = await prisma.job_postings.updateMany({
            where: buildJobWhere(filter),
            data: { pipeline_status: 'removed', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
```

- [ ] **Step 4: Run them — expect PASS**

Run (from `apps/web/`): `rtk proxy npx jest --config jest.integration.config.ts -t "bulk|removeAllInView"`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/actions.ts apps/web/src/__tests__/actions.int.test.ts
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(web): bulkRemove / bulkReopen / removeAllInView server actions"
```

---

### Task 6: Table — sort dropdown, near-miss filter labels, title hyperlink

**Files:**
- Modify: `apps/web/src/components/DiscoveredJobsTable.tsx`
- Test: `apps/web/src/components/__tests__/DiscoveredJobsTable.test.tsx`

**Interfaces:**
- Consumes: `JobSort`, `DiscardType` from `@/lib/actions`.
- Produces: `onFilterChange` payload now always includes `sort: JobSort`; in the Discarded bucket it includes `discardType` unless `'all'`. (Selection/bulk props come in Task 7.)

- [ ] **Step 1: Update the existing payload-shape tests (they will break) + add new tests**

In `apps/web/src/components/__tests__/DiscoveredJobsTable.test.tsx`:

Update the **debounce** test expectation:

```ts
      expect(onFilterChange).toHaveBeenCalledWith({ search: 'Acme', bucket: 'matched', sort: 'score' })
```

Update the **switching to Discarded** test expectation (default sub-filter is now `nearmiss`):

```ts
      expect(onFilterChange).toHaveBeenCalledWith({ search: '', bucket: 'discarded', discardType: 'nearmiss', sort: 'score' })
```

Add new tests:

```ts
  it('renders the job title as a link to the live posting', () => {
    renderTable()
    const link = screen.getByRole('link', { name: 'Backend Engineer' })
    expect(link).toHaveAttribute('href', 'https://acme.example/jobs/1')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('sends the chosen sort in the filter payload', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      renderTable({ onFilterChange })
      fireEvent.click(screen.getByLabelText(/sort by/i))
      fireEvent.click(screen.getByText('Newest posted'))
      onFilterChange.mockClear()
      act(() => { jest.advanceTimersByTime(300) })
      expect(onFilterChange).toHaveBeenCalledWith(expect.objectContaining({ sort: 'posted' }))
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })
```

- [ ] **Step 2: Run — expect FAIL**

Run (from `apps/web/`): `rtk proxy npx jest DiscoveredJobsTable`
Expected: FAIL — no link role / no sort control / old payload shape.

- [ ] **Step 3: Implement sort state, near-miss labels, and the title link**

In `apps/web/src/components/DiscoveredJobsTable.tsx`:

Update the type import:

```ts
import type { JobBucket, DiscardType, JobSort } from '@/lib/actions'
```

Add `posted_at` to the `JobPosting` interface (after `pipeline_status?`):

```ts
    posted_at?: string | null
```

Extend the `onFilterChange` prop type to include `sort`:

```ts
    onFilterChange: (filters: {
        bucket: JobBucket
        search: string
        minScore?: number
        discardType?: DiscardType
        sort: JobSort
    }) => void
```

Add sort state and change the discard sub-filter default to `nearmiss` (replace the two `useState` lines for `discardType`):

```ts
    const [sort, setSort] = useState<JobSort>('score')
    // Discarded-only sub-filter — default to the near-miss band (the audit reframe).
    const [discardType, setDiscardType] = useState<'all' | DiscardType>('nearmiss')
```

Add `sort` to the debounced payload and to the effect deps:

```ts
            stableFilterChange({
                search,
                bucket,
                minScore: minScore === '' ? undefined : Number(minScore),
                discardType: bucket === 'discarded' && discardType !== 'all' ? discardType : undefined,
                sort,
            })
```
```ts
    }, [search, bucket, minScore, discardType, sort, stableFilterChange])
```

Add the sort `Select` in the filter row (after the `Min score` input, before the discarded sub-filter):

```tsx
                <Select value={sort} onValueChange={(v) => setSort(v as JobSort)}>
                    <SelectTrigger className="w-[150px]" aria-label="Sort by">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="score">Best match</SelectItem>
                        <SelectItem value="posted">Newest posted</SelectItem>
                    </SelectContent>
                </Select>
```

Replace the discarded sub-filter `SelectItem`s with the near-miss set:

```tsx
                        <SelectContent>
                            <SelectItem value="nearmiss">Near-miss</SelectItem>
                            <SelectItem value="disqualified">Disqualified</SelectItem>
                            <SelectItem value="all">All discarded</SelectItem>
                        </SelectContent>
```

Wrap the job title in a link (replace the `{job.job_title}` text node inside the title `TableCell`, keeping the `reason` block below it):

```tsx
                                            <a
                                                href={job.job_url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="hover:underline text-foreground"
                                            >
                                                {job.job_title}
                                            </a>
```

- [ ] **Step 4: Run — expect PASS**

Run (from `apps/web/`): `rtk proxy npx jest DiscoveredJobsTable`
Expected: PASS (updated + new).

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/DiscoveredJobsTable.tsx apps/web/src/components/__tests__/DiscoveredJobsTable.test.tsx
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(web): sort toggle, near-miss filter, title link in Discovered Jobs"
```

---

### Task 7: Table — row selection + bulk action bar

**Files:**
- Modify: `apps/web/src/components/DiscoveredJobsTable.tsx`
- Test: `apps/web/src/components/__tests__/DiscoveredJobsTable.test.tsx`

**Interfaces:**
- Produces three new required props consumed by Task 8: `onBulkRemove(ids: number[])`, `onBulkReopen(ids: number[])`, `onRemoveAllInView()`.

- [ ] **Step 1: Add jest.fn() defaults for the new props, then write failing tests**

In `DiscoveredJobsTable.test.tsx`, add to the `renderTable` `props` object (so all existing tests keep working):

```ts
    onBulkRemove: jest.fn(),
    onBulkReopen: jest.fn(),
    onRemoveAllInView: jest.fn(),
```

Add tests:

```ts
  it('selecting a matched row reveals Remove selected and calls onBulkRemove with ids', () => {
    const onBulkRemove = jest.fn()
    renderTable({ onBulkRemove })
    fireEvent.click(screen.getByLabelText('Select Backend Engineer'))
    fireEvent.click(screen.getByRole('button', { name: /remove selected/i }))
    expect(onBulkRemove).toHaveBeenCalledWith([1])
  })

  it('on the Discarded bucket, selected rows offer Reopen selected', () => {
    const onBulkReopen = jest.fn()
    renderTable({
      data: [{ ...mockJobs[0], pipeline_status: 'discarded' }],
      total: 1,
      onBulkReopen,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
    fireEvent.click(screen.getByLabelText('Select Backend Engineer'))
    fireEvent.click(screen.getByRole('button', { name: /reopen selected/i }))
    expect(onBulkReopen).toHaveBeenCalledWith([1])
  })

  it('select-all toggles every row on the page', () => {
    renderTable()
    fireEvent.click(screen.getByLabelText(/select all/i))
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument()
  })

  it('clears selection when the data set changes', () => {
    const { rerender } = renderWithRerender()
    fireEvent.click(screen.getByLabelText('Select Backend Engineer'))
    expect(screen.getByText(/1 selected/i)).toBeInTheDocument()
    rerender([{ ...mockJobs[0], id: 99 }])
    expect(screen.queryByText(/selected/i)).not.toBeInTheDocument()
  })
```

Add this helper near `renderTable` (clearing-selection test needs a rerender with new data):

```ts
function renderWithRerender() {
  const props = {
    data: mockJobs, total: 2, page: 0, size: 25,
    onPageChange: jest.fn(), onFilterChange: jest.fn(), onMarkApplied: jest.fn(),
    onDiscard: jest.fn(), onReopen: jest.fn(), onViewJD: jest.fn(),
    onBulkRemove: jest.fn(), onBulkReopen: jest.fn(), onRemoveAllInView: jest.fn(),
  }
  const utils = render(<DiscoveredJobsTable {...props} />)
  return { rerender: (data: any[]) => utils.rerender(<DiscoveredJobsTable {...props} data={data} />) }
}
```

- [ ] **Step 2: Run — expect FAIL**

Run (from `apps/web/`): `rtk proxy npx jest DiscoveredJobsTable`
Expected: FAIL — no checkboxes / no bulk bar.

- [ ] **Step 3: Implement selection state + bulk bar + checkbox column**

In `DiscoveredJobsTable.tsx`:

Add the three props to `DiscoveredJobsTableProps`:

```ts
    onBulkRemove: (ids: number[]) => void
    onBulkReopen: (ids: number[]) => void
    onRemoveAllInView: () => void
```

Destructure them in the component signature alongside the others.

Add selection state + helpers (after the existing `useState` hooks):

```ts
    const [selected, setSelected] = useState<Set<number>>(new Set())
    // Whenever the visible row set changes (page / filter / post-action refresh),
    // drop the selection — stale ids must never carry across views.
    useEffect(() => { setSelected(new Set()) }, [data])

    const allSelected = data.length > 0 && data.every((j) => selected.has(j.id))
    const toggleAll = () => setSelected(allSelected ? new Set() : new Set(data.map((j) => j.id)))
    const toggleOne = (id: number) =>
        setSelected((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id); else next.add(id)
            return next
        })
    const ids = () => [...selected]
```

Add the bulk bar just inside the outer `<div className="space-y-4">`, above the filter row:

```tsx
            {selected.size > 0 && (
                <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                    <span className="font-medium">{selected.size} selected</span>
                    {bucket === 'discarded' && (
                        <Button variant="outline" size="sm" onClick={() => onBulkReopen(ids())}>
                            Reopen selected
                        </Button>
                    )}
                    <Button variant="destructive" size="sm" onClick={() => onBulkRemove(ids())}>
                        Remove selected
                    </Button>
                </div>
            )}
```

Add a "Remove all in view" button in the filter row, inside the existing `{bucket === 'discarded' && ( ... )}` region (next to the sub-filter Select — wrap both in a fragment if needed):

```tsx
                {bucket === 'discarded' && (
                    <Button variant="outline" size="sm" onClick={onRemoveAllInView}>
                        Remove all in view
                    </Button>
                )}
```

Add the checkbox header cell as the first `TableHead`:

```tsx
                            <TableHead className="w-[4%]">
                                <input
                                    type="checkbox"
                                    aria-label="Select all"
                                    checked={allSelected}
                                    onChange={toggleAll}
                                    className="h-4 w-4 align-middle"
                                />
                            </TableHead>
```

Add the per-row checkbox cell as the first `TableCell` in the row map:

```tsx
                                        <TableCell>
                                            <input
                                                type="checkbox"
                                                aria-label={`Select ${job.job_title}`}
                                                checked={selected.has(job.id)}
                                                onChange={() => toggleOne(job.id)}
                                                className="h-4 w-4 align-middle"
                                            />
                                        </TableCell>
```

Bump the empty-state `colSpan` from `6` to `7`.

- [ ] **Step 4: Run — expect PASS**

Run (from `apps/web/`): `rtk proxy npx jest DiscoveredJobsTable`
Expected: PASS (all, including the Task 6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/DiscoveredJobsTable.tsx apps/web/src/components/__tests__/DiscoveredJobsTable.test.tsx
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(web): row selection + bulk action bar in Discovered Jobs"
```

---

### Task 8: Dashboard wiring

**Files:**
- Modify: `apps/web/src/components/Dashboard.tsx`
- Test: `apps/web/src/components/__tests__/Dashboard.test.tsx` (verify still green)

**Interfaces:**
- Consumes: `bulkRemove`, `bulkReopen`, `removeAllInView` (Task 5); the three new table props (Task 7).

- [ ] **Step 1: Import the new actions**

In the `from '@/lib/actions'` import block in `Dashboard.tsx`, add:

```ts
    bulkRemove,
    bulkReopen,
    removeAllInView,
```

- [ ] **Step 2: Add the handlers**

After `handleReopenJob` in `Dashboard.tsx`:

```ts
    const handleBulkRemove = async (jobIds: number[]) => {
        // ponytail: native confirm — same pattern as handleDeleteApplication.
        if (!confirm(`Remove ${jobIds.length} job${jobIds.length === 1 ? '' : 's'}? They'll be hidden from all tabs.`)) return
        const result = await bulkRemove(jobIds)
        if (result.success) {
            toast.success(`Removed ${result.count} job${result.count === 1 ? '' : 's'}`)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    const handleBulkReopen = async (jobIds: number[]) => {
        const result = await bulkReopen(jobIds)
        if (result.success) {
            toast.success(`Reopened ${result.count} job${result.count === 1 ? '' : 's'}`)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    const handleRemoveAllInView = async () => {
        if (!confirm("Remove every job in this view? They'll be hidden from all tabs.")) return
        const result = await removeAllInView(jobFilters)
        if (result.success) {
            toast.success(`Removed ${result.count} job${result.count === 1 ? '' : 's'}`)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }
```

- [ ] **Step 3: Pass the props to `DiscoveredJobsTable`**

In the `<DiscoveredJobsTable ... />` block (~line 500), add:

```tsx
                            onBulkRemove={handleBulkRemove}
                            onBulkReopen={handleBulkReopen}
                            onRemoveAllInView={handleRemoveAllInView}
```

- [ ] **Step 4: Verify the Dashboard test still passes**

The new actions are auto-mocked by `jest.mock('@/lib/actions')` and only fire on user interaction (not on mount), so no mock setup is needed.

Run (from `apps/web/`): `rtk proxy npx jest Dashboard`
Expected: PASS.

- [ ] **Step 5: Full web + worker suites green**

Run: `make test-web` then `make test-worker`
Expected: both PASS. (If `make` wrapping is noisy, the equivalents are `rtk proxy npx jest` in `apps/web/` and `rtk proxy python3 -m pytest` in `apps/worker/`.)

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/Dashboard.tsx
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "feat(web): wire bulk remove/reopen + remove-all into the dashboard"
```

---

### Task 9: Docs — SPEC, PROGRESS, CHANGELOG

**Files:**
- Modify: `docs/SPEC.md`, `docs/PROGRESS.md`, `CHANGELOG.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: SPEC.md — data model + behaviors**

In the data-model section for `job_postings`, add the `posted_at` column (date-only `YYYY-MM-DD`; board date with scrape-date fallback). In the pipeline-status list, add `removed` as a terminal, UI-only hide (set by bulk Remove; invisible to all buckets; inert to the worker). In the Discovered Jobs capability description, record: sort toggle (Best match / Newest posted), bulk Remove (Matched + Discarded) and bulk Reopen (Discarded), "Remove all in view", the Discarded view reframed as a near-miss audit (`NEAR_MISS_FLOOR ≤ score < MATCH_SCORE_THRESHOLD` default), and the job-title link to the live posting.

- [ ] **Step 2: PROGRESS.md — close/add entries**

Remove any now-done in-flight item this covers; if tracking remaining ideas, add a one-line note that `posted_at` is captured for greenhouse/lever/ashby/workday only (Pinpoint has no board date → scrape-date fallback). No fabricated open defects.

- [ ] **Step 3: CHANGELOG.md — one entry**

Add under the current unreleased/dated section:

```markdown
- Discovered Jobs: sort by Best match or Newest posted (new `posted_at`, captured
  from greenhouse/lever/ashby/workday); bulk Remove (terminal, hidden + worker-inert)
  on Matched & Discarded, bulk Reopen + "Remove all in view" on Discarded; Discarded
  reframed as a near-miss audit view (default 60–74); job titles link to the posting.
```

- [ ] **Step 4: Sanity-check docs render and nothing else broke**

Run: `make check-schema`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/SPEC.md docs/PROGRESS.md CHANGELOG.md
git -c user.name=drink970082 -c user.email=howdywu@gmail.com commit -m "docs: record discovered-jobs sort + bulk actions"
```

---

## Self-Review

**Spec coverage:**
- Posting-date sort (Best match default / Newest posted) → Tasks 1–4, 6, 8. ✓
- `posted_at` capture across 4 boards + fallback → Tasks 2, 3. ✓
- Matched bulk Remove → Tasks 5, 7, 8. ✓
- `removed` terminal status, self-hiding + worker-inert → Task 5 (no worker change, by design — verified: `ON CONFLICT DO NOTHING` + status-only pipeline selects). ✓
- Discarded bulk Reopen + Remove + "Remove all in view" → Tasks 5, 7, 8. ✓
- Near-miss reframe (default `nearmiss`, `NEAR_MISS_FLOOR`) → Tasks 4, 6. ✓
- Job-title hyperlink → Task 6. ✓
- Out-of-scope (no removed tab, no Failed bulk, no bulk Apply, no visible date column) → not built. ✓
- Tests: worker parser/upsert, web action sort/near-miss/bulk, component selection/link, schema drift → covered. ✓

**Placeholder scan:** no TBD/TODO/"handle edge cases"; every code step shows real code. ✓

**Type consistency:** `DiscardType = 'disqualified' | 'nearmiss'`, `JobSort = 'score' | 'posted'`, `NEAR_MISS_FLOOR`, `buildJobWhere`, `bulkRemove/bulkReopen/removeAllInView`, table props `onBulkRemove/onBulkReopen/onRemoveAllInView` — names match across actions, component, and dashboard. ✓
