# Board-Scraper Expansion — Design

**Date:** 2026-07-18
**Status:** approved for build (phases 1–2, and phase 4 via an opt-in browser module —
decided 2026-07-18); phase 3 deferred — see §3
**Author:** design session (Claude + drink970082)

## 1. Problem & goal

The worker fetches jobs from **9 known-ATS adapters** (`ats_worker/fetch/`:
greenhouse, lever, ashby, workday, pinpoint, smartrecruiters, workable, oracle,
jobvite). Each is a per-**platform** adapter: give it a company `slug`, get clean
JSON. A tracked company is a **data row** in `watched_companies` (`source, slug,
name`) — adding one is zero code.

The gap is every board that is **not** on a supported platform: big-tech and
quant firms that either run a different ATS or self-host. The wishlist
(`scrape_board.txt`, `apps/worker/quant_job_boards.txt`) is dominated by these.

**Goal (the user's words):** *easy to expand, easy to maintain.* Concretely:

- Adding a company must stay a **data row**, never a new file.
- The file count grows **per platform**, not per company — and only when a genuinely
  new *shape* appears.
- No browser or LLM in the runtime/scoring loop (keeps the worker pure + DI, no
  network in tests, and off the fit-scorer's codex quota).

## 2. Findings (live recon, 2026-07-17/18)

Every board on the wishlist was probed against its live endpoint. They fall into
four buckets:

| Bucket | Meaning | Members (verified) |
|---|---|---|
| **Platform** | one adapter, ∞ companies via slug | iCIMS (SIG, General Dynamics, Fujifilm…), **Phenom** (Microsoft, Kraft Heinz, Mastercard, CVS…) |
| **Custom-recipe** | one row against one generic executor | Amazon, ByteDance/TikTok, Jane Street, DE Shaw, G-Research, Renaissance, AQR |
| **Code-adapter** | too weird for a recipe; ~30 lines of code | Google (WIZ `AF_initDataCallback` positional arrays) |
| **Browser-required** | plain HTTP blocked, but a real browser clears it | Citadel (Cloudflare invisible JS challenge; server-rendered once past — see §2 evidence) |

Key evidence:

- **iCIMS**: jobs render in an iframe; `GET {sub}.icims.com/jobs/search?in_iframe=1&pr=N`
  returns server HTML rows via plain curl. Paginate `pr`.
- **Phenom**: `GET {host}/api/pcsx/search?domain={domain}&start=N` → `data.positions[]`,
  total at `data.count`. Description needs a second `…/api/pcsx/position_details` call.
  Confirmed reusable across Microsoft (553) + Kraft Heinz (764) with the same recipe.
- **Amazon**: `GET amazon.jobs/en/search.json`, `.jobs[]`, offset≤100, full descriptions inline.
- **ByteDance/TikTok**: `POST jobs.bytedance.com/api/v1/public/supplier/search/job/posts`,
  `website-path` header selects brand (`en`=1188, `tiktok`=3703), `data.job_post_list[]`,
  offset+limit. No posted date.
- **Jane Street**: `GET janestreet.com/jobs/main.json` — single file, top-level array, 214 roles, descriptions inline, no pagination.
- **DE Shaw**: parse `__NEXT_DATA__` from `/careers`, `props.pageProps.regularJobs` (78 roles). (A `/_next/data/{buildId}/…` JSON API also exists but `buildId` rots — the HTML blob is more robust.)
- **Google**: curl-reachable; `AF_initDataCallback` `ds:1` parses as strict JSON, `&page=N`, total 1711. ~30 lines of positional parsing.
- **Citadel** (corrected 2026-07-18, verified first-hand, then re-audited by three independent
  agents same day — supersedes the earlier "skip, headless won't help"): plain HTTP is blocked —
  `curl`, the worker's `requests`, and Claude Code's WebFetch all get a **403 Cloudflare** challenge
  every time (20/20 probes across UAs — default/Chrome/Googlebot — and paths, incl. `/wp-json/`,
  `/feed/`, and job-detail pages). The mechanism is Cloudflare's **invisible managed JS challenge**
  (`cdn-cgi/challenge-platform/.../jsd/oneshot`), not a clickable Turnstile widget. A **real browser
  (Playwright Chromium) clears it unaided** (2/2 attempts, no interaction, `cf_clearance` minted), and
  the listing is then plain **server-rendered HTML** paginated at `/careers/open-opportunities/page/N/`
  with **no XHR/JSON API and no ATS** behind it — roles are in the initial document. **Two separate
  boards, two separate entities** (from each site's own "Viewing N of M" counter, 2026-07-18):
  **citadelsecurities.com** (the market maker) = **81 roles / 9 pages**; **citadel.com** (the hedge
  fund) = **49 roles / 5 pages**. Both are on the wishlist. (The original "81 / 9 pages" was correct
  for Citadel Securities; a mid-audit run mistakenly measured only citadel.com and read 49 — corrected
  here.) There is **no** portable plain-HTTP path: the `cf_clearance`
  cookie is bound to the browser's TLS/JA3 fingerprint + IP, so replaying cookie+UA over `curl` still
  403s (verified) — you must keep driving the browser end-to-end, not lift the cookie. So Citadel needs
  a browser **at fetch time**. Accurate verdict: **browser-required**, not impossible.
  - **New (audit finding):** the Yoast **`career-sitemap.xml`** *is* reachable plain-HTTP (200, no
    challenge) on both domains — 53 URLs (citadel.com) + 86 (citadelsecurities.com), each with live
    `<lastmod>` and a title-bearing slug (`…/careers/details/quantitative-research-analyst-asia/`).
    Enough to build a **fresh URL/slug inventory with change-detection** without a browser, but it
    carries **no titles/descriptions/locations** as fields and every detail page is challenged, so it
    cannot deliver job *content*. Useful as a cheap "what changed" signal, not a scraper source.
  - A web *search* is not a fetch: it returns aggregators, not the origin. Coverage is **incomplete but
    not stale** (audit corrected the earlier "stale" framing): Built In carried 46 Citadel jobs with
    "Yesterday"/"2 Days Ago" postings; LinkedIn's unauthenticated `jobs-guest` API serves live postings
    to plain `curl`; Simplify 37; Glassdoor 26. Fresh-but-partial (~57% at best) — fine for a rough
    count, useless as the complete source.

Cross-cutting reality that shapes the recipe format: **`posted_at` is inconsistent** —
ISO (DE Shaw), a human string "July 17, 2026" (Amazon), epoch seconds (Phenom),
epoch ms (ByteDance has none at all), or absent (Jane Street, Renaissance). The
executor must normalize tolerantly and treat `posted_at` as optional.

## 3. Scope & phases

**The one invariant — how we fetch: the runtime pipeline is plain HTTP (`requests`) only.
No headless browser and no LLM in the fetch/score loop.** A browser and an LLM appear
*once per board, at onboarding* (§4.4) — to discover the live endpoint and draft the
recipe — then a human commits the row and runtime replays it with plain `requests`. Every
phase below obeys this, *except* phase 4 (Citadel), which is walled off in its own opt-in browser module (§4.5) because it can't.

So "are we HTML-scraping or driving a headless browser?" — **at runtime, neither is a
browser: it's plain HTTP.** Two flavors of plain HTTP: hit a JSON endpoint, or pull
server-rendered HTML / embedded `__NEXT_DATA__` JSON out of a `requests` response. The
headless browser is an onboarding tool, never a pipeline step.

**Phase 1 — platform adapters (build now).** `icims` + `phenom` modules, added to
`VALID_SOURCES`. Plain HTTP — iCIMS returns server-rendered HTML rows; Phenom is a JSON API.

**Phase 2 — custom recipe executor (build now).** `custom.py` runs a declarative recipe
(`json` GET/POST + `next-data` modes; `offset`/`page`/`none` pagination), the recipe
stored as a row on the watchlist. Plain HTTP — the recipe hits a JSON endpoint or extracts
`__NEXT_DATA__` JSON embedded in the served HTML. **No browser, no CSS-selector scraping.**

**Phase 3 — extended reach (deferred).** `custom` `json-ld` + `html-css` modes + the
optional detail-enrich phase (G-Research 51, Renaissance 12 — low volume / higher
fragility), and the `google` code-adapter (WIZ positional arrays). Still plain HTTP;
deferred on volume + fragility, not on mechanism.

**Phase 4 — browser-required (approved 2026-07-18: opt-in browser module).** Citadel
Securities (81) + Citadel (49). The **only** class that can't be done with plain HTTP at
fetch time — a real browser must clear Cloudflare *per session*, and the cleared
`cf_clearance` cookie is not portable to `requests` (§2). Built as an **isolated, opt-in
`citadel` adapter** driven by headless Playwright Chromium, kept off the default plain-HTTP
path so the core stays pure. Design in §4.5. It carries a Chromium **extra** dependency
that never touches core install, CI, or the no-network test gate.

## 4. Architecture

### 4.1 Platform adapters (`icims.py`, `phenom.py`)

Same contract as the existing 9: a module with `SOURCE`, a pure `parse_jobs(...)`,
and `fetch(slug, company_name, session=None, timeout=20) -> list[dict]`. Registered
in `fetch.ADAPTERS` and listed in `config.VALID_SOURCES`.

- **iCIMS** — `slug` = the careers subdomain (e.g. `careers-sig`). `fetch` GETs
  `https://{slug}.icims.com/jobs/search?in_iframe=1&pr={page}` and parses the HTML
  job rows (`/jobs/{id}/{slug}/job` links), paginating `pr` until a page returns no rows.
- **Phenom** — `slug` packs `"{host}/{domain}"` (e.g. `apply.careers.microsoft.com/microsoft.com`),
  mirroring Workday's multi-part `"tenant/dc/site"` convention, so **no schema change**.
  `fetch` pages `start` by the fixed size (10) against `data.count`, maps `data.positions[]`,
  then hydrates each posting's description via one `position_details` call. Treats an
  HTTP-200 body with `status != 200` / `data == null` ("Tenant not identified") as an error.

Multi-part slugs continue to pack into the single `slug` string — **platform adapters
require no schema change.**

### 4.2 Generic `custom` executor (`custom.py`)

`fetch(slug, company_name, recipe, session=None, timeout=20)` runs a declarative
**recipe** and returns the standard posting dicts. The recipe is data (JSON),
authored once per board.

**Recipe schema** (only the knobs the evidence requires):

```
method        GET | POST                       (default GET)
url           string (may embed the slug/params)
headers       optional map                     (e.g. {website-path: tiktok})
body          optional map (POST body template)
mode          json | next-data                 (json-ld/html deferred — §3)
item_path     dotted path to the job array     (e.g. data.job_post_list)
total_path    optional dotted path to total    (drives pagination stop)
page:
  type        offset | page | none
  param       query-param name (GET) …
  body_param  … or body key (POST)
  size        page size
  size_param  optional query-param for size
fields:
  title         path
  location      path
  url           path OR "template with {field}" placeholders
  description   path OR [path, path]  (list = concatenate)
  posted_at     path (optional; missing → null)
  external_id   path
```

**Fixed behavior (not knobs), applied by the executor to every recipe:**

- `description` → `util.html_to_text` (no-op on clean text).
- `posted_at` → one tolerant normalizer: ISO, `"Month D, YYYY"`, epoch s/ms, or
  `null`. A missing/garbage date yields `null` (the pipeline tolerates it).
- `url` template interpolation with any field from the raw job object (e.g. `{id}`).
- `next-data` mode = extract the `__NEXT_DATA__` `<script>` JSON, then behave as `json`.

**Escape hatch:** anything a recipe can't express (Google's positional arrays,
cursor pagination, signed headers) gets a tiny hand-written code adapter — it does
**not** grow a knob on the recipe DSL. This boundary is the ponytail guardrail
against the recipe format ballooning into a brittle mini-language.

**Example recipes** (illustrative; exact paths finalized during build from the
saved fixtures):

```yaml
# Amazon — GET JSON, paginate offset up to hits
source: custom
slug: amazon
recipe:
  method: GET
  url: "https://www.amazon.jobs/en/search.json?base_query=software+engineer&sort=recent"
  mode: json
  item_path: jobs
  total_path: hits
  page: {type: offset, param: offset, size_param: result_limit, size: 100}
  fields:
    title: title
    location: normalized_location
    url: "https://www.amazon.jobs{job_path}"
    description: description
    posted_at: posted_date
    external_id: id_icims
```

```yaml
# TikTok — POST JSON, header-selected brand, no posted date
source: custom
slug: tiktok
recipe:
  method: POST
  url: "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts"
  headers: {website-path: tiktok}
  body: {recruitment_id_list: [], keyword: "", limit: 100, offset: 0}
  mode: json
  item_path: data.job_post_list
  total_path: data.count
  page: {type: offset, body_param: offset, size: 100}
  fields:
    title: title
    location: city_info.en_name
    url: "https://lifeattiktok.com/search/{id}"
    description: [description, requirement]
    external_id: id
```

### 4.3 Storage & dispatch

- **Schema (Prisma-owned):** add a nullable `recipe String?` column to
  `watched_companies` (SQLite has no JSON type; store a JSON string). Platform/known-ATS
  rows leave it `NULL`; `custom` rows carry the recipe JSON. Then `make db-push` and
  update the schema-drift fixture (`make check-schema`).
- **`VALID_SOURCES`** gains `icims`, `phenom`, `custom`.
- **`config.Company`** gains an optional `recipe: dict | None`; `config.yaml`
  `companies:` entries for `source: custom` carry an inline `recipe:` (seeded like
  everything else).
- **`db.get_watchlist` / `import_watchlist`** select/insert the `recipe` column
  (parse/serialize JSON string ↔ dict at the boundary).
- **Dispatch:** `pipeline.run_fetch` passes `recipe=company.get("recipe")` to
  `fetch_company`; `fetch_company` routes `source == "custom"` to
  `custom.fetch(slug, name, recipe=...)`. Existing sources ignore the kwarg.

One watchlist, one seed path, one fetch loop — `custom` is just another `source`.

### 4.4 Onboarding workflow (where the browser/LLM live)

Adding a new board is a **build-time** activity, never runtime:

1. Drive the board once in a headless browser; capture the XHR / page payload that
   holds the jobs (both Google's and Microsoft's *documented* URLs were dead — you
   must discover the live one).
2. An LLM drafts either "it's platform X, slug = …" or a `custom` recipe row from the
   captured response.
3. Human reviews the row and commits it. Runtime then uses **plain `requests`** only.

### 4.5 Browser adapter (`citadel.py`) — the isolated phase-4 path

The one board class that needs a browser *at fetch time*, walled off so the plain-`requests`
core stays untouched. Same adapter contract as the other 11; the browser is confined to a
lazy-imported optional dependency.

- **Contract, unchanged.** `SOURCE = "citadel"`, a pure `parse_jobs(pages: list[str]) ->
  list[dict]`, and `fetch(slug, company_name, session=None, timeout=30) -> list[dict]`.
  Registered in `fetch.ADAPTERS` + `config.VALID_SOURCES`. Two watchlist rows, one adapter:
  `slug` = the host (`citadelsecurities.com` | `citadel.com`) — the second firm is **zero
  code**, just a data row.
- **The parse is pure and browser-free.** `parse_jobs` takes the already-fetched
  `/page/N/` HTML strings and returns standard posting dicts — `title`, `location`, `url`
  (the detail link), `external_id` (the detail slug, stable + unique → drives new-role
  diffing), `description` (filled by the enrich step). Unit-tested against
  `tests/fixtures/citadel.html`: **no browser in tests, no-network invariant preserved.**
  All the real logic lives here.
- **Playwright is lazy + optional.** `from playwright.sync_api import sync_playwright` lives
  *inside* `fetch`, never at module top — importing the module (and running the whole rest
  of the suite) needs no Chromium. If the extra is absent, `fetch` raises a clear
  `RuntimeError` pointing to `pip install -e '.[browser]' && playwright install chromium`.
  Playwright + Chromium ship as a packaging **extra**, so core install, CI, and the
  coverage/schema gates stay browser-free.
- **Fetch flow (thin glue over the pure parse):** launch headless Chromium → navigate the
  listing (Cloudflare clears unaided, ~2–8 s) → read "Viewing N of M" for the page count →
  walk `/careers/open-opportunities/page/1..K/` **in the same browser context** (the cookie
  can't be lifted out, so every load stays in-session) → for each role, navigate its
  `/careers/details/{slug}/` for the description → close browser → `parse_jobs(pages)`.
  - `# ponytail: full-description mode loads one detail page per role — first run ≈130 loads
    (~minutes). Upgrade path if it bites: enrich only unseen external_ids (the pipeline
    already diffs new by id), so steady-state is a handful/run.` Until then, schedule Citadel
    on a slower cadence than the plain-HTTP boards.
- **Off the default path.** Because it drives a browser, `citadel` runs only when the
  `browser` extra is present (or an `enable_browser_sources` flag is set); a normal `run.py`
  without the extra **skips it with a warning**, never crashes. The default every-cycle
  pipeline stays 100% plain `requests`.

## 5. Testing

Follow the existing adapter convention: save a captured response as
`tests/fixtures/{name}.json` (or `.html`) and unit-test the pure parse against it.

- `icims`, `phenom`: fixture + `parse_jobs` test each (Phenom also a `position_details`
  description-hydrate test).
- `custom`: fixtures for the `json` (GET), `json` (POST + headers), and `next-data`
  cases; tests for pagination stop (`total_path`), the tolerant date normalizer
  (ISO / human / epoch / missing), `url` template interpolation, and multi-path
  (concatenated) description.
- `config`: a `source: custom` entry parses its `recipe`; a `custom` row missing a
  `recipe` is a startup `ConfigError`.
- `citadel`: fixture (`tests/fixtures/citadel.html`) + `parse_jobs` test — role rows,
  location, detail-URL/`external_id` extraction, and a "Viewing N of M" count guard. The
  browser-driving `fetch` glue is not unit-tested against the live site (same as other
  adapters' network I/O); its shape-guard makes it fail loud if the card markup changes.
  These tests import no Playwright (the lazy import keeps the suite browser-free).
- Keep worker coverage ≥ 85 (`pyproject.toml`).

## 6. Risks & mitigations

- **Recipe DSL creep** → hard rule: recipe covers common shapes; weird boards get a
  code adapter (§4.2 escape hatch). `json-ld`/`html`/detail-enrich stay deferred until a
  wanted board needs them.
- **HTML/positional fragility** (iCIMS rows, future Google) → each such parser fails
  loud (guard on shape) and has a fixture test so a site redesign is caught, not
  silently zeroed.
- **Missing `posted_at`** (Jane Street, ByteDance, Renaissance) → treated as `null`;
  freshness for those boards derives from first-seen `external_id` diffing (already
  how the pipeline detects "new").
- **Phenom N+1 description calls** → one extra request per posting; bounded by the
  page-of-10 loop and the existing per-thread session/timeout.
- **Browser fragility / cost (Citadel)** → the Playwright path is isolated behind the
  `browser` extra and off the default cycle, so if Cloudflare hardens against headless
  Chromium only Citadel breaks — the plain-HTTP core is unaffected. `parse_jobs` fails loud
  on a markup change (fixture test); the per-role detail loads are the bounded cost in §4.5
  (new-only enrich is the upgrade path). Never runs in CI/tests (lazy import + extra).

## 7. Docs to update on build

Per CLAUDE.md, in the same commit(s): `SPEC.md` (new adapters + custom executor in the
capability map), `PROGRESS.md` (close/open the relevant items), `CHANGELOG.md`
(history), and reconcile `apps/worker/quant_job_boards.txt` (its support
classifications and 2026-06-10 counts are stale — separate verification in flight).

## 8. Out-of-scope, for later reference

- **`custom` `json-ld` mode**: extract schema.org `JobPosting` objects — one extractor
  reused across G-Research (detail), Renaissance (detail), and many WordPress boards.
- **`custom` `html-css` mode + detail-enrich phase**: list via CSS selectors, then fetch
  each detail URL to fill description/date. Needed by G-Research (51) and Renaissance (12).
- **`google` code-adapter**: `results/?page=N` → parse `AF_initDataCallback` `ds:1` with
  index guards; sitemap (3585 URLs) as a dedup anchor.
- **Citadel (browser-required):** no longer out-of-scope — promoted to **phase 4**, built as
  the opt-in `citadel` browser adapter (§3, §4.5). Two alternatives were rejected: the
  `cf_clearance` cookie hybrid **doesn't work** (clearance is TLS/JA3+IP-bound, so replaying
  cookie+UA over `requests` still 403s — audit-tested 2026-07-18), and sitemap-only change
  detection was passed over because we want full descriptions for fit-scoring (the
  plain-HTTP `career-sitemap.xml` in §2 remains a free fallback if the browser path ever
  becomes too costly to run).
- **A web search is not a fetch:** search tools (and assistants that "search the web") return a search
  engine's already-crawled copy or third-party aggregators — not the live origin. Aggregator coverage
  is **fresh but incomplete** (audit 2026-07-18: Built In 46 w/ postings from yesterday, LinkedIn
  jobs-guest live to `curl`, Simplify 37, Glassdoor 26 — vs 81 live on the Citadel Securities origin).
  Usable as a rough
  count or fallback signal; useless as the complete source (no full list / descriptions / guaranteed
  freshness across all roles).
