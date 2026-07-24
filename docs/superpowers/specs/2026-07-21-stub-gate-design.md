# Design: Stub-gating the phenom N+1 fetch (fetch-time filtering, Phase 2)

**Status:** shipped 2026-07-21 (v1.0.0).
**Date:** 2026-07-21.
**Supersedes:** the Phase 2 sketched in
[`2026-07-20-fetch-time-filtering-design.md`](./2026-07-20-fetch-time-filtering-design.md)
§"Non-goals" (per-board `filters` column + source-side query narrowing). That shape was
measured and rejected — see §Measurements and §Rejected alternatives.

## Problem / motivation

`phenom` is a two-step adapter: a paged search that carries **no description**, then ONE
detail GET per position to fetch it (`fetch/phenom.py`, via `fetch/_paged.py`). Every
filter the pipeline owns runs *after* `fetch_company` returns — so a board is fully
hydrated before a single posting is dropped.

Measured against the live Microsoft board (`apply.careers.microsoft.com/microsoft.com`,
the only `phenom` watchlist row) on 2026-07-21:

| Stage | Postings | Detail GETs it costs |
|---|---|---|
| Raw board | 1,580 | 1,580 |
| After the existing `title_filter` | 782 | 782 |
| After the existing location gate (`candidate.locations = [remote, USA]`) | ~458 | 458 |

One pass over one company therefore issues **158 search requests + 1,580 detail GETs ≈
1,738 HTTP requests**, and bins roughly 1,100 of the descriptions it just paid for. A
full fetch did not finish within a 20-minute observation window.

The search stub already carries **`name` (title)** and **`locations`** — exactly and
only the two fields the deterministic gates read. The information needed to say "no" is
present before the expensive call.

## Goal

Skip the per-position detail GET for postings the **already-existing** deterministic
gates would reject anyway. Same postings in the queue, same `pipeline_status` values,
same `score_detail` shapes — fewer HTTP requests.

Target: **1,580 → ~458 detail GETs (−71%)** on the Microsoft board.

## Non-goals

- **No new filter semantics.** `title_filter`, `title_exclude`, `max_age_days`,
  `deterministic_screen` are reused verbatim. This change moves *when* they run, not
  *what* they decide.
- **No per-board configuration.** No `filters` column, no Watchlist-tab editor, no
  `onboard-board` capture. Measured and rejected (§Rejected alternatives).
- **No source-side query narrowing.** Rejected for the same reason.
- **No new LLM anywhere.** The gates involved are pure code.
- **Watchlist path only.** The feed path (`run_feed`) is untouched.
- **`workday` is not wired**, though it shares the same N+1 shape (§Scope).

## Decisions (resolved with the user)

1. **A stub-rejected posting is not hydrated at all** — including one that will be
   *stored* as `discarded`. Such a row keeps `job_title`, `company_name`, `location`
   and `job_url`; its `description` is empty. Reopening it from the Discarded bucket
   means clicking through to `job_url`. Chosen over "hydrate on reopen" (which would
   need a web→worker fetch path that does not exist) and over "only silent drops skip
   the fetch" (which reaches 782, not 458).
2. **The gate lives in the adapter, not in `_paged.py`.** `paged_details` stays
   untouched; only `phenom.fetch` grows an optional parameter.
3. **`keep` is an optimization, never a decision.** `run_fetch`'s existing post-fetch
   loop re-runs `prefilter_postings` + `deterministic_screen` over whatever the adapter
   returns and does all status tagging. The adapter's verdict changes which HTTP calls
   happen, never which status a row gets.
4. **Scope to `phenom`.** `workday` is deliberately excluded (§Scope).
5. **`max_age_days` stays `0`** — measured, not built (§Measurements).

## Change list

### Worker — `ats_worker/fetch/phenom.py`

`fetch(slug, company_name, session=None, timeout=20, keep=None)`.

`keep` is `Callable[[dict], str]` returning one of `"drop"`, `"discard"`, `"hydrate"`.
`None` (the default) means today's behavior exactly.

Inside the existing `_row(http, pos)` closure, before the detail GET:

```python
stub = parse_position(pos, company_name)   # description="" — the existing mapper
if keep is not None:
    verdict = keep(stub)
    if verdict == "drop":
        return None        # never stored, no detail call
    if verdict == "discard":
        return stub        # stored with an empty JD, no detail call
# "hydrate" (or keep is None) falls through to today's detail GET
```

An unrecognised return value is treated as `"hydrate"` (fail-open: a bad predicate
costs requests, never postings).

**Why the ids stay correct:** `parse_position` reads `external_id` from `pos["id"]` —
the same field the hydrated row uses — so a stub row and a hydrated row carry an
identical `(source, external_id)` dedup key.

### Worker — `ats_worker/fetch/__init__.py`

- Add `STUB_GATE_SOURCES = {"phenom"}` next to the existing `RECIPE_SOURCES`.
- `fetch_company(source, slug, company_name, *, recipe=None, keep=None, **kwargs)`
  forwards `keep` **only** when `source in STUB_GATE_SOURCES`, mirroring exactly how
  `recipe` is forwarded today. Every other adapter — and every injected test double —
  is called with an unchanged signature.

### Worker — `ats_worker/pipeline.py` `run_fetch`

Build the predicate once, from parameters `run_fetch` already receives
(`title_filter`, `title_exclude`, `max_age_days`, `candidate`, `now`). Add it to the
per-company `kw` dict **only when `c["source"] in fetch.STUB_GATE_SOURCES`** — the same
guard style as `recipe`, and the reason an injected 3-arg `fetch_fn` double in the
existing tests keeps working untouched. (`fetch_company`'s own forwarding guard is then
belt-and-braces for any other caller.)

```python
def _keep(stub):
    if not prefilter_postings([stub], title_filter=title_filter,
                              title_exclude=title_exclude,
                              max_age_days=max_age_days, now=now):
        return "drop"
    if candidate:
        verdict = score.deterministic_screen(
            {"screen": {}, "disqualified": False, "disqualification_reason": ""},
            stub, candidate)
        if verdict.get("disqualified"):
            return "discard"
    return "hydrate"
```

The existing per-company loop is otherwise unchanged: it still calls
`prefilter_postings` on the returned list and still tags disqualified rows
`pipeline_status='discarded'` with `_score_detail(verdict, disqualified=True)`. The
double evaluation is deliberate and cheap — both functions are pure and deterministic,
so the second pass reaches the same verdict on the same stub.

### Docs (same commit)

- **SPEC §7** (fetch/adapters): note that `phenom` gates the search stub before
  hydrating, and that a stub-gated discard carries no description.
- **SPEC §9** invariant→test map: add the new rows.
- **PROGRESS:** close "Fetch-time filtering — Phase 2 (per-board settings)"; record the
  `max_age_days` finding under the entry that replaces it.
- **CHANGELOG:** entry under Changed.

## Measurements (2026-07-21, live boards + the real `db/applications.db`)

These drove the design; they are recorded so the rejected options are not re-proposed.

**Board volume.** The `phenom` watchlist row (Microsoft) is the only board large enough
to matter: 1,580 postings. `greenhouse` (31 rows, 1,137 postings ever) is a single list
call per board with descriptions included — no N+1, nothing to gate. `workday` boards
here hold 5 postings total. `custom`/`browser` rows (Amazon, TikTok, ByteDance, Jane
Street, Citadel…) are single-list recipes; Amazon's already narrows at source via
`base_query=software+engineer` in its recipe URL.

**`max_age_days` is wrong for this domain — leave it at `0`.** Of the 39 postings ever
notified, **13 are more than 365 days old**, including the four highest scorers: 93 @
416d, 91 @ 448d, 85 @ 545d, 85 @ 400d. `max_age_days: 30` would have kept 7 of 39
matches; `180` would have kept 24. These boards run evergreen requisitions and
`posted_at` is first-published, not freshness. The one genuinely stale row found (an
Ansatz posting dated 2016-05-25, scored 80) is a *dead* posting, not an old one — that
is the separate "mark dead postings `expired`" PROGRESS item, which checks liveness
rather than age.

**`title_exclude` is small.** Title words appearing ≥6× in never-matched titles and
never in a matched one: `senior` (60), `systems` (24), `c++` (19), `operations` (19),
plus `support`, `network`, `fpga`, `hardware`, `floor`, `experienced`, `lead`. ≈100 of
1,573 postings (~6%), and it is a *silent* drop. Left off; the operator may set it.

## Rejected alternatives

- **Per-board `filters` column on `watched_companies`** (the originally-specced Phase
  2). The phenom search API does accept narrowing — `query=software engineer` → 556 of
  1,580; `location=United States` → 838; both together → 369. But that is *worse* than
  the ~458 this design reaches for free, once the search-page cost (158 → ~37 requests)
  is set against a Prisma column, a drift-fixture update, a Watchlist UI editor and
  `onboard-board` capture. Revisit only if a board appears that stub-gating cannot tame.
- **Re-express Microsoft as a `custom` recipe** (zero code — put the query in the URL,
  like Amazon). Impossible: `custom` has no per-item detail step, and the phenom search
  payload carries no description, so every posting would arrive with an empty JD and
  nothing to score.
- **Packing the query into the slug** (`host/domain/query`). The slug charset forbids
  spaces, and the slug is half the `(source, slug)` dedup key — changing it re-keys the
  watchlist row.
- **Gating inside `paged_details`.** Would need a source-agnostic stub→canonical mapper
  passed in by every adapter. `phenom.parse_position` already *is* that mapper for the
  one adapter that needs it; putting the gate in the closure costs nothing and touches
  no shared code.

## Scope: why `workday` is excluded

`workday` has the same N+1 shape, but its list stub carries no GUID — `parse_job` takes
`external_id` from the **detail** payload (`jobPostingInfo.id`, falling back to
`jobReqId`). A stub row would therefore key on `jobReqId`, and if the same posting were
later hydrated it would insert a **second** row under its GUID. Its three boards hold 5
postings total, so the fix is not worth the id-reconciliation work. Documented here so
the next large workday board starts from a known problem, not a surprise.

## Impact & operational risks

- **Behavior change:** a posting rejected by title (`drop`) or by location/internship
  (`discard`) on a `phenom` board is no longer hydrated. Statuses and `score_detail` are
  unchanged; only `description` differs (empty).
- **Permanence.** `upsert_postings` is `ON CONFLICT(source, external_id) DO NOTHING`, so
  an empty-JD discarded row is **never** back-filled — widening `candidate.locations`
  later will not re-hydrate it. To re-evaluate such rows, delete them and re-fetch.
- **Fail-open predicate.** Any unrecognised `keep` verdict hydrates. A broken predicate
  degrades to today's cost; it cannot silently lose postings.
- **No schema change** → the schema-drift guard is unaffected.
- **Other adapters unaffected**; `keep` is never passed to them.

## Testing / verification

- **`phenom.fetch` with `keep=None`** — regression: identical postings and identical
  detail-GET count to today (the existing phenom tests must stay green untouched).
- **`phenom.fetch` with a `keep` stub-gate** — a fake session over three positions (one
  title miss → `drop`, one foreign on-site → `discard`, one match → `hydrate`) issues
  **exactly one** detail GET; the dropped position is absent, the discarded one is
  present with `description == ""`, the hydrated one carries its JD.
- **Id stability** — the stub row and the hydrated row for the same position produce the
  same `external_id`.
- **Fail-open** — a predicate returning `"nonsense"` hydrates and returns every posting.
- **`fetch_company`** — `keep` reaches `phenom` and is *not* passed to a non-gated
  adapter (a strict 3-arg double must not raise).
- **`run_fetch` integration** — a mixed phenom batch yields the same statuses and
  `score_detail` as the same batch fetched without the gate; a non-phenom company in the
  same pass is unaffected.
- Full worker suite green; coverage gate (`fail_under = 85`) holds.

## Sequencing (suggested)

1. `phenom.fetch(..., keep=None)` + the `_row` gate; unit tests (regression first, then
   the three-verdict test).
2. `STUB_GATE_SOURCES` + `fetch_company` forwarding; its tests.
3. `run_fetch` builds and passes `_keep`; integration test.
4. Full suite + coverage.
5. Docs (SPEC / PROGRESS / CHANGELOG).
