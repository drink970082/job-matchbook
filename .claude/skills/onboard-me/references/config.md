# The `candidate:` block in `config.yaml`

Hard constraints are the ONLY things that **discard** a posting; a missing *skill* is
not one (that just lowers the fit score — skills live in the résumé).

Edit these under `candidate:` (leave any one **blank** to *not* screen on it; blank
everything to disable disqualification):

- `highest_degree` — none | High School | Associate | Bachelor's | Master's | PhD
- `work_authorization` — citizen | permanent resident | authorized-no-sponsorship | needs visa sponsorship
- `security_clearance` — none | confidential | secret | top secret
- `locations` — where they can actually work (e.g. `["remote"]`, `["USA"]`); on-site
  roles elsewhere are discarded. The LLM judges by meaning ("USA" covers "New York").
- `exclude_internships` — `true`/`false` (deterministic, by title).

Optionally set `title_filter` — a coarse, **title-only** substring keep-list applied
before the scorer. Leave it empty unless a high-volume company floods them with
off-target titles; the scorer does the real relevance work.

## Two rules that bite

- **`title_filter` is a top-level key** (a sibling of `candidate:`, at column 0), NOT
  a `candidate:` subkey — nesting it under `candidate:` fails loud at startup.
- **Unknown / mistyped keys fail loud at startup**, both at the top level and inside
  `candidate:`. Use only the documented keys, keep each at its right level, and set
  values rather than adding sections.

**Edit the file directly — don't script it.** A YAML writer would strip the template's
comments.
