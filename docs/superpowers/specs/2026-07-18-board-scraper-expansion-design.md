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
**three buckets — and by design there is no code-per-site tier**: a board is a known
platform, a plain-HTTP recipe, or a browser recipe. Adding one is always a data row.

| Bucket | Meaning | Members (verified) |
|---|---|---|
| **Platform** | one adapter, ∞ companies via slug | iCIMS (SIG, General Dynamics, Fujifilm…), **Phenom** (Microsoft, Kraft Heinz, Mastercard, CVS…) |
| **Plain-HTTP recipe** | one row against the `custom` executor, fetched by `requests` | Amazon, ByteDance/TikTok, Jane Street, DE Shaw, G-Research, Renaissance, AQR |
| **Browser recipe** | one row against the `browser` executor — for boards plain HTTP can't fetch (*blocked*) or can't cleanly parse (*fragile shape*) | Citadel (Cloudflare-blocked), Google (WIZ positional arrays — read the rendered DOM instead) |

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
- **Google**: curl-reachable, but the jobs are WIZ `AF_initDataCallback` **positional arrays**
  (`ds:1`) — parseable yet index-fragile, and no dotted-path or CSS recipe addresses positional
  data. So Google is a **browser recipe**: render the page, read the job cards from the DOM via
  CSS selectors (steadier than array indices), `&page=N`, total 1711. (Deferred: 1711 roles ≈
  ~170 rendered pages/run — a real runtime cost; build only if Google becomes must-have, on a
  slow cadence.)
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

**How we fetch — two executors, both recipe-driven, zero code-per-site.** Adding any board is
a **data row**, never a new file (the core goal, §1). A row resolves to one of:

- a **known platform adapter** (greenhouse, icims, phenom, … — slug only), or
- a **plain-HTTP recipe** run by the `custom` executor (`requests` → JSON / `__NEXT_DATA__` /
  json-ld / CSS), or
- a **browser recipe** run by the `browser` executor (Playwright renders the page; the same
  recipe fields extract from the rendered DOM) — the universal last resort.

**The default pipeline is plain HTTP.** The browser executor is isolated, opt-in, and off the
default path (§4.5); an LLM appears only at *onboarding* (§4.6) to draft a row, never in the
fetch/score loop. So "HTML-scrape or headless browser?" — **prefer plain HTTP; drop to the
browser executor only when plain HTTP is *blocked* (Citadel) or the shape *won't parse cleanly*
(Google's positional arrays).** Both paths are recipes — the difference is just the transport.

**Phase 1 — platform adapters (build now).** `icims` + `phenom` modules, added to
`VALID_SOURCES`. Plain HTTP — iCIMS returns server-rendered HTML rows; Phenom is a JSON API.

**Phase 2 — custom recipe executor (build now).** `custom.py` runs a declarative recipe
(`json` GET/POST + `next-data` modes; `offset`/`page`/`none` pagination), the recipe
stored as a row on the watchlist. Plain HTTP — the recipe hits a JSON endpoint or extracts
`__NEXT_DATA__` JSON embedded in the served HTML. **No browser, no CSS-selector scraping.**

**Phase 3 — extended plain-HTTP recipe modes (deferred).** `custom` `json-ld` + `html-css`
modes + the optional detail-enrich phase (G-Research 51, Renaissance 12 — low volume / higher
fragility). Still plain HTTP; deferred on volume + fragility, not on mechanism.

**Phase 4 — browser recipe executor (approved 2026-07-18).** The `browser` executor: an
isolated, opt-in, recipe-driven module that renders a board in headless Playwright Chromium and
extracts fields from the rendered DOM via the same recipe schema. It is the **catch-all last
resort** for the two things plain HTTP can't handle — *blocked* boards (Citadel: Cloudflare
clears only in a real browser, and the `cf_clearance` cookie isn't portable to `requests`, §2)
and *fragile-shape* boards (Google's positional arrays — read the rendered cards, don't
index-parse JSON). First recipe: Citadel (Securities 81 + fund 49). Design in §4.5. Chromium
ships as an **extra** that never touches core install, CI, or the no-network test gate, and the
executor stays off the default plain-HTTP cycle.

**The cascade — how a new board is classified (as a skill, §4.6):**

1. Known platform/ATS? → **data row** (`source` + `slug`).
2. Plain HTTP reaches a parseable endpoint (JSON / `__NEXT_DATA__` / json-ld / CSS)? →
   **plain-HTTP recipe row** (`source: custom`).
3. Neither — blocked, or plain HTTP won't parse it cleanly? → **browser recipe row**
   (`source: browser`). **No bespoke per-site code, ever.**

Always take the earliest rung that works — it keeps runtime cheapest.

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

**Escape hatch = the browser executor, not code.** Anything the plain-HTTP recipe can't
express (Google's positional arrays, cursor pagination, signed requests, a bot wall) becomes a
**browser recipe** (§4.5), never a hand-written per-site adapter: in a rendered browser you read
the visible DOM, click "next"/scroll to paginate, and the page signs its own requests, so a
CSS-selector recipe covers it. Two guardrails at once — the plain-HTTP recipe DSL never balloons
with exotic knobs, **and** the file count never grows per site (a board stays a data row). The
one thing the browser executor can't do cheaply is *scale*: large boards (Google's 1711) mean
many rendered pages/run — so prefer plain HTTP whenever it parses, and put big browser-only
boards on a slow cadence.

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
- **`VALID_SOURCES`** gains `icims`, `phenom`, `custom` (phase 1–2) and `browser` (phase 4).
- **`config.Company`** gains an optional `recipe: dict | None`; `config.yaml`
  `companies:` entries for `source: custom` **or** `source: browser` carry an inline `recipe:`
  (seeded like everything else).
- **`db.get_watchlist` / `import_watchlist`** select/insert the `recipe` column
  (parse/serialize JSON string ↔ dict at the boundary).
- **Dispatch:** `pipeline.run_fetch` passes `recipe=company.get("recipe")` to `fetch_company`;
  `fetch_company` routes `source == "custom"` → `custom.fetch(...)` and `source == "browser"` →
  `browser.fetch(...)`. Existing sources ignore the kwarg. **`browser` rows are gated**: skipped
  with a warning unless the `browser` extra is installed (or `enable_browser_sources` is set), so
  the default run never imports Playwright.

One watchlist, one seed path, one fetch loop — `custom` and `browser` are just other `source`s,
differing only in transport (plain `requests` vs headless Chromium).

### 4.4 Onboarding workflow (where the browser/LLM live)

Adding a new board is a **build-time** activity, never runtime — codified as the
`onboard-board` skill (§4.6). In short:

1. Drive the board once in a headless browser; capture the XHR / page payload that
   holds the jobs (both Google's and Microsoft's *documented* URLs were dead — you
   must discover the live one).
2. Walk the cascade (§3) and draft the row: "it's platform X, slug = …", a `custom`
   recipe (plain HTTP), or — only if blocked/unparseable — a `browser` recipe.
3. Human reviews the row and commits it. Runtime then uses **plain `requests`** for
   `custom`/platform rows, and the isolated browser executor only for `browser` rows.

### 4.5 Browser recipe executor (`browser.py`) — the isolated phase-4 fallback

The catch-all for boards plain HTTP can't fetch or can't cleanly parse. Recipe-driven like
`custom` (no per-site code), but the transport is a headless browser and extraction reads the
**rendered DOM**. Walled off so the plain-`requests` core never imports Chromium.

- **Contract, unchanged.** `SOURCE = "browser"`, a pure `parse_jobs(pages, recipe) ->
  list[dict]`, and `fetch(slug, company_name, recipe, session=None, timeout=30) -> list[dict]`.
  Registered in `fetch.ADAPTERS` + `config.VALID_SOURCES`. A board is a **data row**
  (`source: browser`, slug = host, inline `recipe`); a second firm on the same site is zero code
  (Citadel's two domains = two rows).
- **Recipe = the `custom` schema + CSS extraction + interaction pagination.** Reuses the shared
  field-mapping / date-normalization helpers (§4.2). Extraction is `html-css`: an `item` selector
  for the job cards, then per-`field` CSS selectors (text or attr). Pagination gains browser-native
  knobs — `page: {type: url, template: ".../page/{n}/", until: empty}` for URL paging, or
  `{type: click, selector: "…Next"}` / `{type: scroll}` for interaction paging. An optional
  `detail: {url_field, fields}` block enriches each role from its detail page. **Keep this DSL
  lean** — the same ponytail guardrail as the plain-HTTP recipe.
- **The parse is pure and browser-free.** `parse_jobs(pages, recipe)` takes the already-rendered
  HTML strings + the recipe and returns standard posting dicts. Unit-tested against a saved fixture
  (`tests/fixtures/citadel.html`): **no browser in tests, no-network invariant preserved.** All the
  extraction logic lives here; `fetch` is thin glue that only produces the HTML strings.
- **Playwright is lazy + optional.** `from playwright.sync_api import sync_playwright` lives
  *inside* `fetch`, never at module top — importing the module (and running the whole rest of the
  suite) needs no Chromium. Missing extra → `fetch` raises a clear `RuntimeError` pointing to
  `pip install -e '.[browser]' && playwright install chromium`. Playwright + Chromium are a
  packaging **extra**, so core install, CI, and the coverage/schema gates stay browser-free.
- **Fetch flow (thin glue over the pure parse):** launch headless Chromium → navigate the listing
  (any Cloudflare challenge clears unaided, ~2–8 s) → paginate per the recipe **in the same browser
  context** (a cleared cookie isn't portable, so all loads stay in-session) → optionally open each
  role's detail page → collect the rendered HTML → close → `parse_jobs(pages, recipe)`.
  - `# ponytail: detail-enrich loads one page per role (Citadel first run ≈130 loads, ~minutes).
    Upgrade path if it bites: enrich only unseen external_ids (the pipeline already diffs new by
    id), so steady-state is a handful/run.` Big browser-only boards get a slow cadence.
- **Off the default path.** Because it drives a browser, `browser`-source rows run only when the
  `browser` extra is present (or an `enable_browser_sources` flag is set); a normal `run.py` without
  the extra **skips them with a warning**, never crashes. The default every-cycle pipeline stays
  100% plain `requests`.

**Citadel recipe (illustrative; selectors finalized from the saved fixture at build):**

```yaml
source: browser
slug: citadelsecurities.com
name: Citadel Securities
recipe:
  url: "https://www.citadelsecurities.com/careers/open-opportunities/"
  mode: html-css
  item: "article.job-card"
  page: {type: url, template: "https://www.citadelsecurities.com/careers/open-opportunities/page/{n}/", until: empty}
  fields:
    title: "h3"
    location: ".job-location"
    url: {selector: "a", attr: href}
    external_id: {selector: "a", attr: href, extract: "details/([^/]+)/"}
  detail: {url_field: url, fields: {description: ".job-description"}}
```

`citadel.com` is the same recipe with the other host — a second data row, zero new code.

### 4.6 Onboarding skill (`onboard-board`)

The cascade (§3) as a repeatable Claude Code **skill**, so adding a board is a guided procedure,
not tribal knowledge. Build-time only; it emits a reviewed data row, never code.

**Input:** a careers URL (+ optional company name).

1. **Platform check.** Probe known-ATS/platform signatures (greenhouse/lever/…/icims/phenom URL
   shapes). Hit → propose `{source, slug}`, done.
2. **Plain-HTTP probe.** `requests` the page; look for a JSON/XHR endpoint, `__NEXT_DATA__`, or
   json-ld `JobPosting`. Parseable → draft a `source: custom` recipe and validate it against the
   live response (must return ≥1 well-formed posting).
3. **Browser fallback.** If blocked (403/challenge) or the shape won't parse cleanly, render in
   Playwright, capture the rendered DOM, and draft a `source: browser` html-css recipe (item +
   field selectors, pagination, optional detail). Validate against the render.
4. **Emit + verify.** Output the watchlist row (source/slug/name/recipe) **and** a captured fixture
   for the parse test. Human reviews, commits the row + fixture. Runtime never re-runs the skill.

**Guardrails:** the skill *only ever produces a data row* (+ a test fixture) — it never writes a
new adapter file. If no recipe fits, it says the board is genuinely unsupported rather than
inventing bespoke code. Always prefer the earliest cascade rung that works.

Deliverable: `skills/onboard-board/` (SKILL.md + probe helpers) — specced here, built as its own
task.

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
- `browser`: fixture (`tests/fixtures/citadel.html`) + `parse_jobs(pages, recipe)` test —
  item/field CSS extraction, detail-URL/`external_id`, url-template pagination stop, and a
  recipe-with-no-matches shape guard (fails loud on selector drift). The browser-driving `fetch`
  glue isn't unit-tested against the live site (same as other adapters' network I/O). These tests
  import no Playwright — the lazy import keeps the suite browser-free.
- Keep worker coverage ≥ 85 (`pyproject.toml`).

## 6. Risks & mitigations

- **Recipe DSL creep** → hard rule: the plain-HTTP recipe covers common shapes; anything it
  can't express becomes a **browser recipe** (§4.2 escape hatch), never bespoke code.
  `json-ld`/`html`/detail-enrich stay deferred until a wanted board needs them.
- **HTML/positional fragility** (iCIMS rows, browser-recipe selectors) → each such parser fails
  loud (guard on shape) and has a fixture test so a site redesign is caught, not
  silently zeroed.
- **Missing `posted_at`** (Jane Street, ByteDance, Renaissance) → treated as `null`;
  freshness for those boards derives from first-seen `external_id` diffing (already
  how the pipeline detects "new").
- **Phenom N+1 description calls** → one extra request per posting; bounded by the
  page-of-10 loop and the existing per-thread session/timeout.
- **Browser executor fragility / cost** → the Playwright path is isolated behind the `browser`
  extra and off the default cycle, so a site hardening against headless Chromium (or a selector
  drift) breaks only that one browser board — the plain-HTTP core is unaffected. `parse_jobs`
  fails loud on a selector miss (fixture test); per-role detail loads are the bounded cost in §4.5
  (new-only enrich is the upgrade path), and large browser-only boards run on a slow cadence.
  Never runs in CI/tests (lazy import + extra).
- **Code-per-site growth** → eliminated by design: no code-adapter tier exists. Fragile boards
  become browser recipes, so the file count grows per *executor mode*, never per site (§4.2).
- **Browser-recipe DSL creep** → the browser recipe adds only a few knobs (CSS `item`/`fields`,
  url/click/scroll pagination, optional `detail`). Hold the line there; if a board needs more, it's
  a signal to reconsider whether it's worth scraping, not to grow the DSL.

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
- **Google (browser recipe, deferred):** `results/?page=N` renders WIZ job cards; a
  `source: browser` html-css recipe reads the rendered cards (sitemap's 3585 URLs as a dedup
  anchor). Deferred on scale — 1711 roles ≈ ~170 rendered pages/run; build only if Google is
  must-have, on a slow cadence.
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
