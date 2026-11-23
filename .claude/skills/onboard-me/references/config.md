# The `candidate:` block in `config.yaml`

Hard constraints are the ONLY things that **discard** a posting; a missing *skill* is
not one (fit is the AI client's judgment — skills live in the résumé).

**This block is a one-time seed.** The first worker pass copies it into the DB
candidate profile (`candidate_profile`; `highest_degree` becomes one education row);
after that the DB wins and edits here are ignored (the pass logs that they differ). If a
pass has already run, change requirements in the web Settings page or through the MCP
`set_candidate_profile` tool instead (`get_candidate_profile` shows the stored values).

Edit these under `candidate:` (leave any one **blank** to *not* screen on it; blank
everything to disable disqualification):

- `highest_degree` — none | High School | Associate | Bachelor's | Master's | PhD
- `work_authorization` — citizen | permanent resident | authorized-no-sponsorship | needs visa sponsorship
- `security_clearance` — none | confidential | secret | top secret
- `locations` — EVERY country or state they will work in, plus `remote` if remote roles
  count (e.g. `["USA", "remote"]`). No country is assumed: `["remote"]` alone discards
  on-site US postings. Matching is deterministic; a country covers its cities and states
  ("USA" covers "New York"). Blank = open to anywhere (no location screening).
- `exclude_internships` — `true`/`false` (deterministic, by title).
- `exclude_contract` — `true`/`false`: skip contract / part-time / temporary roles
  (deterministic, by title).

Optionally set `title_filter` — a coarse, **title-only** substring keep-list applied
at fetch time, before any model call. Leave it empty unless a high-volume company
floods them with off-target titles; relevance is judged downstream.

## Two rules that bite

- **`title_filter` is a top-level key** (a sibling of `candidate:`, at column 0), NOT
  a `candidate:` subkey — nesting it under `candidate:` fails loud at startup.
- **Unknown / mistyped keys fail loud at startup**, both at the top level and inside
  `candidate:`. Use only the documented keys, keep each at its right level, and set
  values rather than adding sections.

**Edit the file directly — don't script it.** A YAML writer would strip the template's
comments.
