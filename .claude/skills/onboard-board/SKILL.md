---
name: onboard-board
description: >-
  Onboard a new job board / company into the ATS worker's watchlist. Use this
  whenever the user wants to add a company or careers page to the worker's fetch
  list, scrape a new job board, work out how to fetch jobs from a careers URL, or
  asks "how do I add <company> to the watchlist" / "can we track <company>'s jobs".
  Walks the platform → plain-HTTP recipe → browser recipe cascade and emits a
  reviewed watchlist data row (+ a test fixture) — never a new adapter file.
---

# Onboard a board

The worker (`apps/worker`) fetches jobs from a **watchlist** of boards. The whole
point of its design is that **adding a board is a data row, never a new file**. Your job
is to take a careers URL, walk a fixed cascade to work out how its jobs are fetched,
validate it, and **add it to the watchlist so it shows up in the web UI** — or, if nothing
fits, explain why. If you find yourself about to write a new `fetch/<company>.py` adapter,
stop: that's the one thing this system is built to avoid.

The deliverable is deliberately lopsided: **on success, a one-line "added" is the whole
story** — the user doesn't want a write-up of a routine add. A full explanation is only worth
writing **when the cascade fails** and a human has to make a call. Keep that asymmetry.

## The cascade (always in this order — take the first rung that fits)

The rungs are ordered by runtime cost: a platform row costs nothing, a plain-HTTP
recipe is one `requests` call, and a browser recipe drags in headless Chromium. So you
always prefer the earliest rung that actually works.

1. **Platform** — the board runs on a known ATS. Onboarding is just `{source, slug}`,
   no recipe. Supported: `greenhouse, lever, ashby, workday, pinpoint, smartrecruiters,
   workable, icims, phenom` — authoritative list is `ADAPTERS` in
   `apps/worker/ats_worker/fetch/__init__.py` (minus the recipe and feed-only sources).
2. **Plain-HTTP `custom` recipe** — plain `requests` can reach a JSON endpoint, a
   `__NEXT_DATA__` blob, or server-rendered job cards in the returned HTML. Write a
   `custom` recipe (`mode: json` / `next-data` / `html`).
3. **Browser `browser` recipe** — plain HTTP is blocked (Cloudflare/bot wall) or the
   jobs render only client-side with no findable JSON. Render in a real browser and
   extract from the DOM with CSS. Last resort.

## Step 1 — probe

Run the bundled scout, which tries the known ATS endpoints and reads the page for
plain-HTTP signals and bot walls:

```
python .claude/skills/onboard-board/scripts/probe.py <careers-url>
```

Read its `VERDICT:` line. It is a **scout, not a verdict you must obey** — it narrows
the search. In particular, a `plain-http?` result (page fetched, but jobs not in the
static HTML) means *the jobs load via an XHR you still have to find* — that's normal
for a JSON board; go find the endpoint (browser DevTools → Network → filter Fetch/XHR,
or guess a `search.json` / `/api/…` sibling). Don't stop at the probe.

## Step 2 — build the row for the rung the probe pointed you at

The authoritative recipe shapes live in the code and examples — skim these before
writing a recipe: `apps/worker/config.yaml.example` (worked examples of every source),
`apps/worker/ats_worker/fetch/custom.py` + `browser.py` (the executors), and
`fetch/_recipe.py` (the field extractor: dotted paths, `url` templates, the tolerant
date normalizer). Every posting the executors emit has exactly these 8 keys:
`source, external_id, company_name, job_title, location, job_url, description, posted_at`.

### 2a. Platform → a data row

```yaml
- { source: greenhouse, slug: figma, name: "Figma" }
```

`slug` comes from the ATS URL/API the probe verified — never invented. Two packed slugs:
- **workday**: `"tenant/datacenter/site"` (from `{tenant}.{dc}.myworkdayjobs.com/{site}`).
- **phenom**: `"{host}/{domain}"` (e.g. `apply.careers.microsoft.com/microsoft.com`).

No recipe, no fixture needed beyond confirming the board returns jobs (the probe's count).

### 2b. Plain-HTTP → a `custom` recipe

Find the JSON source, then map its fields. A recipe is data:

```yaml
- source: custom
  slug: amazon
  name: "Amazon"
  recipe:
    method: GET                      # or POST (with `body:` / `headers:`)
    url: "https://www.amazon.jobs/en/search.json?base_query=engineer"
    mode: json                       # or next-data (extract __NEXT_DATA__ then treat as json)
    item_path: jobs                  # dotted path to the job array
    total_path: hits                 # optional dotted path to the total (drives pagination stop)
    page: { type: offset, param: offset, size_param: result_limit, size: 100 }  # or {type: none}
    fields:                          # dotted paths; url may be a "{template}"; description may be [a, b]
      title: title
      location: normalized_location
      url: "https://www.amazon.jobs{job_path}"
      description: description
      posted_at: posted_date         # ISO / "Month D, YYYY" / epoch — normalized for you
      external_id: id_icims
```

Field rules that save you time (all handled by `_recipe.py`, so lean on them rather than
pre-processing): `description` accepts a list of paths (concatenated); `url` interpolates
`{dotted.field}` placeholders; dotted paths index lists too (`office.0.name`); a missing
`location`/`posted_at` becomes `null`. `page.type` is `offset` (advance by rows), `page`
(page number), or `none` (single request). POST bodies pass the page value via
`body_param` instead of `param`.

**No JSON, but the cards are in the served HTML?** Use `mode: html` — the response IS the
listing page, and extraction is the *same CSS model as a browser recipe* (2c): an `item`
selector for the cards, then CSS `fields` (string selector, or `{selector, attr, extract}`),
`{field}` url templates included. Only the transport differs, so read 2c's field block for
the syntax. This is the rung that keeps a plain-HTML board off headless Chromium.

```yaml
  recipe:
    url: "https://careers.acme.com/jobs"
    mode: html
    item: "li.job-card"
    page: { type: page, param: page }      # query-param paging; or {type: none}
    fields: { title: ".job-card__title", external_id: { attr: data-req },
              url: "/jobs/{external_id}" }
```

### 2c. Browser → a `browser` recipe

Only when 2a/2b can't reach the jobs. Render the listing in a real browser (Playwright),
read the card structure, and write CSS selectors:

```yaml
- source: browser
  slug: citadelsecurities.com
  name: "Citadel Securities"
  recipe:
    url: "https://www.citadelsecurities.com/careers/open-opportunities/"
    item: "a.careers-listing-card"   # CSS selector for each job card
    page: { type: url, template: ".../page/{n}/", start: 2 }  # or {type: none}
    fields:                          # a selector string (text) OR {selector, attr, extract}
      title: "h2"
      location: ".careers-listing-card__location"
      url: { attr: href }            # no selector = the item node itself
      external_id: { attr: href, extract: "details/([^/]+)/" }  # regex group 1
      # url may INSTEAD be a "{field}" template over this recipe's own other fields —
      # for cards with no href (id in a data-* attr, routing JS-side). Any string
      # containing { is treated as a template, e.g.
      #   external_id: { attr: data-id, extract: "_(REQ\\d+)$" }
      #   url: "/s/details?jobReq={external_id}"
      # A name the recipe doesn't define substitutes empty. Relative results are
      # resolved against the recipe url, and the SSRF guard applies as normal.
    detail: { url_field: job_url, fields: { description: ".single-job-post-description" } }
```

`browser` rows also need `enable_browser_sources: true` in config and the Playwright extra
(`requirements-browser.txt`) — call this out to the user, since it's off by default.

## Step 3 — validate before you touch the live watchlist

A row that isn't verified is a guess, and Step 4 adds it to the **live** board list — so
prove it first. Confirm the recipe yields **≥1 well-formed posting** (a real title, a
`job_url`, a non-empty `external_id`); a platform row just needs the probe's non-zero count.
For a recipe, run its `parse_jobs` against a captured response:

```bash
cd apps/worker && python -c "
import json; from ats_worker.fetch import custom    # or: browser
recipe = {...}
jobs = custom.parse_jobs(json.load(open('/tmp/capture.json')), recipe, '<Name>')
print(len(jobs), jobs[0])"
```

If it validates, add it (Step 4). If it yields 0 postings — or no rung fit at all — do NOT
add a broken row; write the failure report instead (see below).

## Step 4 — add it (the watchlist is a DB, not a file)

The watchlist lives in the DB table `watched_companies`, which the web **Watchlist tab**
reads and writes. `config.yaml` `companies:` is ONLY a one-time seed — editing it after the
first run does nothing and never reaches the UI. So add the board straight to the DB with the
bundled helper (deduped on `(source, slug)`):

```bash
python .claude/skills/onboard-board/scripts/add_watched.py \
  --source <source> --slug <slug> --name "<name>" [--recipe /tmp/recipe.json]
```

It prints `added` or `already on the watchlist`. Then **tell the user the outcome in one
line** — added / already there — and, for a `browser` row, that it needs
`enable_browser_sources: true` + the Playwright extra to actually run. **No success report.**
The board now shows in the Watchlist tab; the worker fetches it next cycle. (The user can also
add/remove boards by hand in that same tab — this skill is just the automated path.)

Optional repo hygiene (only if the user wants a committed regression test): save the trimmed
response to `apps/worker/tests/fixtures/<slug>.<ext>` and add a `parse_jobs` case mirroring an
existing `tests/test_<source>.py`. Separate from adding the board.

## When the cascade fails — the one time a report earns its place

If no rung fits — not a known platform, plain HTTP reaches no parseable jobs, and even a
browser render finds no job list — **don't force a bad recipe onto the live watchlist.**
Instead, report: what you tried at each rung, what you actually saw (status codes, a missing
selector, an auth-walled XHR), and your best guess at why. *That* is when the human needs the
detail — to decide whether the board is worth a bespoke effort or should be skipped. On a
routine success they don't; "added" is the whole story.

## Guardrails (why this stays cheap to maintain)

- **Never write a new adapter file.** The value here is that boards are data. A weird board
  becomes a `browser` recipe (you can read almost any rendered DOM with CSS), not code.
- **Prefer the earliest rung.** Platform > plain-HTTP > browser, by runtime cost. Don't reach
  for a browser recipe when a `search.json` exists.
- **Verify slugs, don't guess them.** Shared ATS APIs host squatted accounts for common words
  ("careers", "search") — the probe already guards this by requiring a non-empty board; hold
  the same bar when a human hands you a slug.
- **A board that fits nothing is unsupported.** Say so plainly rather than inventing a bespoke
  scraper — that's a real, useful answer.
