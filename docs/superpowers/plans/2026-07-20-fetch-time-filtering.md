# Fetch-Time Filtering (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut local-LLM volume on the watchlist fetch path by dropping stale/off-title postings before upsert and by moving the two deterministic screen gates (internship title, location string) ahead of the Ollama call — while keeping disqualified rows visible in the Discovered "Discarded" bucket.

**Architecture:** All changes are in `apps/worker` and touch no schema. A new pure `prefilter_postings` extends today's title keep-list with a negative title list and a `posted_at` max-age drop. The existing deterministic gate logic is extracted into a shared `deterministic_screen(screen, posting, candidate)` reused by both `screen_posting` (post-LLM, unchanged behavior — protects the feed path) and a new fetch-time tagging step in `run_fetch` that marks misses `discarded` (skipping Ollama). `upsert_postings` gains optional per-row `pipeline_status`/`score_detail`.

**Tech Stack:** Python 3.11, pytest, SQLite (via `ats_worker.db`), stdlib `datetime`/`json`.

**Design spec:** `docs/superpowers/specs/2026-07-20-fetch-time-filtering-design.md`.

## Global Constraints

- **Worker style:** Python, 4-space indent. Modules stay pure + dependency-injected; real services wired only in `run.py`. Tests are hermetic (no network, no keys).
- **No schema DDL.** Prisma owns `schema.prisma`; this change writes only existing columns (`pipeline_status`, `score_detail`). No `make db-push`, no drift-fixture change.
- **Coverage gate:** worker `fail_under = 85` (`apps/worker/pyproject.toml`) must hold.
- **Run worker tests** from repo root: `make test-worker`, or a single test with
  `cd apps/worker && python -m pytest tests/test_x.py::name -v`. (If RTK mis-summarizes runner output, bypass with `rtk proxy python -m pytest ...`.)
- **Keep each commit green.** Commit as `drink970082 <howdywu@gmail.com>`.
- **Age semantics:** `posted_at` null/empty/unparseable → **keep**; `max_age_days == 0` → filter off. Compare date-only (`YYYY-MM-DD`).
- **Matching:** title-only, case-insensitive (both keep and exclude). Never match the description.

---

### Task 1: Config — `max_age_days` + `title_exclude`

**Files:**
- Modify: `apps/worker/ats_worker/config.py` (`Config` dataclass ~105-116; `load_config` ~157-164)
- Test: `apps/worker/tests/test_config.py`

**Interfaces:**
- Produces: `Config.max_age_days: int` (default `0`), `Config.title_exclude: list[str]` (default `[]`), parsed by `load_config`.

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_config.py` (it already imports `load_config` and `ConfigError`):

```python
def test_config_defaults_new_filters_off():
    cfg = load_config("companies: []\n")
    assert cfg.max_age_days == 0
    assert cfg.title_exclude == []


def test_config_parses_new_filters():
    cfg = load_config("companies: []\nmax_age_days: 30\ntitle_exclude: [intern, sales]\n")
    assert cfg.max_age_days == 30
    assert cfg.title_exclude == ["intern", "sales"]


def test_config_rejects_non_int_max_age():
    with pytest.raises(ConfigError):
        load_config("companies: []\nmax_age_days: soon\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && python -m pytest tests/test_config.py -k "new_filters or max_age" -v`
Expected: FAIL — `Config` has no attribute `max_age_days` / `title_exclude`.

- [ ] **Step 3: Add the fields + parsing**

In `config.py`, add two fields to the `Config` dataclass (after `title_filter`):

```python
    # Optional negative title pre-filter: DROP a posting whose title contains one of
    # these (case-insensitive) — the complement of title_filter. Empty = drop none.
    title_exclude: list[str] = field(default_factory=list)
    # Optional fetch-time freshness gate: drop a posting whose posted_at is older than
    # this many days. 0 = off. Dateless/unparseable posted_at is always kept.
    max_age_days: int = 0
```

In `load_config`, extend the `Config(...)` return (reusing the existing helpers):

```python
        title_filter=title_filter,
        title_exclude=_parse_title_filter(data.get("title_exclude") or []),
        max_age_days=_int_field(data, "max_age_days", 0),
        candidate=candidate,
```

(`_reject_unknown_keys` derives allowed keys from the dataclass fields, so both new keys are accepted automatically.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/worker && python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the existing unknown-key guard).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/config.py apps/worker/tests/test_config.py
git commit -m "feat(worker): add max_age_days + title_exclude config fields"
```

---

### Task 2: `prefilter_postings` — negative title + max-age drop

**Files:**
- Modify: `apps/worker/ats_worker/fetch/__init__.py` (add function + `__all__`)
- Test: `apps/worker/tests/test_fetch.py`

**Interfaces:**
- Consumes: existing `filter_postings(postings, title_filter)`.
- Produces: `prefilter_postings(postings, *, title_filter=None, title_exclude=None, max_age_days=0, now=None) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_fetch.py`. Extend the existing import line
`from ats_worker.fetch import fetch_company, filter_postings` to also import
`prefilter_postings`:

```python
def test_prefilter_drops_title_exclude():
    posts = [{"job_title": "Software Engineer", "posted_at": None},
             {"job_title": "Sales Engineer", "posted_at": None}]
    kept = prefilter_postings(posts, title_exclude=["sales"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["Software Engineer"]


def test_prefilter_drops_stale_keeps_fresh_and_dateless():
    posts = [{"job_title": "A", "posted_at": "2026-01-01"},   # ~5 months old
             {"job_title": "B", "posted_at": "2026-06-01"},   # 3 days old
             {"job_title": "C", "posted_at": None}]           # dateless -> keep
    kept = prefilter_postings(posts, max_age_days=30, now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["B", "C"]


def test_prefilter_zero_max_age_keeps_old_dates():
    posts = [{"job_title": "A", "posted_at": "2020-01-01"}]
    assert prefilter_postings(posts, max_age_days=0, now="2026-06-04") == posts


def test_prefilter_unparseable_date_is_kept():
    posts = [{"job_title": "A", "posted_at": "not-a-date"}]
    assert prefilter_postings(posts, max_age_days=30, now="2026-06-04") == posts


def test_prefilter_composes_keep_then_exclude():
    posts = [{"job_title": "Senior Engineer", "posted_at": None},
             {"job_title": "Sales Engineer", "posted_at": None},
             {"job_title": "Designer", "posted_at": None}]
    kept = prefilter_postings(posts, title_filter=["engineer"],
                              title_exclude=["sales"], now="2026-06-04")
    assert [p["job_title"] for p in kept] == ["Senior Engineer"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && python -m pytest tests/test_fetch.py -k prefilter -v`
Expected: FAIL — `cannot import name 'prefilter_postings'`.

- [ ] **Step 3: Implement `prefilter_postings`**

In `fetch/__init__.py`, add `from datetime import date` at the top (below `from __future__ import annotations`), then add after `filter_postings`:

```python
def _too_old(posted_at, now, max_age_days: int) -> bool:
    """True only when posted_at is a parseable date strictly older than max_age_days.
    A null/empty/unparseable date or max_age_days<=0 is never 'too old' (err toward keep)."""
    if not max_age_days or not posted_at:
        return False
    try:
        posted = date.fromisoformat(str(posted_at)[:10])
        today = date.fromisoformat(str(now)[:10])
    except ValueError:
        return False  # unparseable -> keep
    return (today - posted).days > max_age_days


def prefilter_postings(postings, *, title_filter=None, title_exclude=None,
                       max_age_days=0, now=None):
    """Fetch-time coarse pre-filter (deterministic, no LLM). Drops a posting when it
    fails the positive title keep-list, its title contains a title_exclude keyword,
    or its posted_at is older than max_age_days (null/unparseable posted_at kept).
    Title matching is case-insensitive and title-only, like filter_postings."""
    kept = filter_postings(postings, title_filter)
    excl = [k.lower() for k in (title_exclude or []) if k]
    out = []
    for p in kept:
        title = (p.get("job_title") or "").lower()
        if any(k in title for k in excl):
            continue
        if _too_old(p.get("posted_at"), now, max_age_days):
            continue
        out.append(p)
    return out
```

Add `"prefilter_postings"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/worker && python -m pytest tests/test_fetch.py -v`
Expected: PASS (new prefilter tests + all existing filter tests).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/fetch/__init__.py apps/worker/tests/test_fetch.py
git commit -m "feat(worker): add prefilter_postings (title_exclude + max-age drop)"
```

---

### Task 3: Extract `deterministic_screen` (behavior-preserving)

**Files:**
- Modify: `apps/worker/ats_worker/score/screen.py` (`screen_posting` body ~126-152; add helper)
- Modify: `apps/worker/ats_worker/score/__init__.py` (re-export)
- Test: `apps/worker/tests/test_score.py`

**Interfaces:**
- Consumes: `_is_internship(title)`, `resolve_location(location_str, allowed_locations) -> (bool, str)` (both already in `screen.py`/`location.py`).
- Produces: `deterministic_screen(screen: dict, posting: dict, candidate: dict | None) -> dict` — mutates and returns `screen`; re-exported as `score.deterministic_screen`.

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_score.py` (it already imports `score`):

```python
def test_deterministic_screen_flags_intern_and_location():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    posting = {"job_title": "Data Science Intern", "location": "Shanghai, China"}
    out = score.deterministic_screen(
        base, posting, {"exclude_internships": True, "locations": ["remote", "USA"]})
    assert out["disqualified"] is True
    assert out["screen"]["internships"]["pass"] is False
    assert out["screen"]["location"]["pass"] is False
    assert "internship/co-op role" in out["disqualification_reason"]
    assert "location: on-site in China" in out["disqualification_reason"]


def test_deterministic_screen_passes_clean_row():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    posting = {"job_title": "Software Engineer", "location": "New York, New York"}
    out = score.deterministic_screen(base, posting, {"locations": ["remote", "USA"]})
    assert out["disqualified"] is False


def test_deterministic_screen_noop_without_candidate():
    base = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    out = score.deterministic_screen(base, {"job_title": "Intern"}, None)
    assert out == {"screen": {}, "disqualified": False, "disqualification_reason": ""}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && python -m pytest tests/test_score.py -k deterministic_screen -v`
Expected: FAIL — `AttributeError: module 'ats_worker.score' has no attribute 'deterministic_screen'`.

- [ ] **Step 3: Extract the helper and call it from `screen_posting`**

In `score/screen.py`, add this function (above `screen_posting`), copying the exact merge logic currently inline at lines 126-150:

```python
def deterministic_screen(screen: dict, posting: dict, candidate: dict | None) -> dict:
    """Apply the two CODE-only screen gates — intern/co-op title, and location string
    (resolve_location off posting['location']) — merging their verdicts into `screen`
    in place. Shared by screen_posting (after the LLM screen, preserving prior
    degree/auth/clearance reasons) and the fetch-time gate (fresh empty screen). No
    LLM. Returns `screen`."""
    if candidate and candidate.get("exclude_internships") and _is_internship(
        str(posting.get("job_title") or "")
    ):
        screen.setdefault("screen", {})["internships"] = {"pass": False, "note": "internship/co-op role"}
        prior = screen.get("disqualification_reason") or ""
        screen["disqualified"] = True
        screen["disqualification_reason"] = (
            f"{prior}; internship/co-op role" if prior else "internship/co-op role"
        )
    if candidate and candidate.get("locations"):
        passed, note = resolve_location(posting.get("location"), candidate["locations"])
        screen.setdefault("screen", {})["location"] = {"pass": passed, "note": note}
        if not passed:
            prior = screen.get("disqualification_reason") or ""
            reason = f"location: {note}" if note else "location"
            screen["disqualified"] = True
            screen["disqualification_reason"] = f"{prior}; {reason}" if prior else reason
    return screen
```

Then in `screen_posting`, **replace** the two inline gate blocks (the `if candidate and ... exclude_internships` block and the `if candidate and ... locations` block, currently lines ~126-150) with a single call, keeping the trailing `return screen`:

```python
    # Deterministic CODE gates (intern title + location string), hoisted into a
    # shared helper so the fetch-time pre-filter can apply the SAME verdict before
    # the Ollama call. No LLM. Merged on top of the LLM screen verdict above.
    screen = deterministic_screen(screen, posting, candidate)

    return screen
```

In `score/__init__.py`, add `deterministic_screen` to the `from .screen import (...)` re-export list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/worker && python -m pytest tests/test_score.py -v`
Expected: PASS — the new `deterministic_screen` tests **and** every existing screen test (foreign-location, intern, degree/auth/clearance, no-Ollama-call) stay green, proving the refactor is behavior-preserving.

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/score/screen.py apps/worker/ats_worker/score/__init__.py apps/worker/tests/test_score.py
git commit -m "refactor(worker): extract deterministic_screen (shared intern/location gate)"
```

---

### Task 4: `upsert_postings` — optional per-row status + score_detail

**Files:**
- Modify: `apps/worker/ats_worker/db.py` (`_INSERT` ~35-43; `upsert_postings` ~46-71)
- Test: `apps/worker/tests/test_db.py`

**Interfaces:**
- Produces: `upsert_postings` now reads optional `p["pipeline_status"]` (default `"new"`) and `p["score_detail"]` (a dict, `json.dumps`-ed; default `NULL`). All other behavior (dedup, rowcount) unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_db.py` (it imports `db` and `_helpers.make_posting`/`NOW`; use the same imports the file already has, plus `import json`):

```python
def test_upsert_honors_pipeline_status_and_score_detail(db_path):
    conn = db.connect(db_path)
    p = make_posting("1", pipeline_status="discarded",
                     score_detail={"disqualified": True,
                                   "disqualification_reason": "location: on-site in China"})
    db.upsert_postings(conn, [p], now=NOW)
    rows = db.get_by_status(conn, "discarded")
    assert [r["external_id"] for r in rows] == ["1"]
    detail = json.loads(rows[0]["score_detail"])
    assert detail["disqualified"] is True


def test_upsert_defaults_status_new_and_null_detail(db_path):
    conn = db.connect(db_path)
    db.upsert_postings(conn, [make_posting("2")], now=NOW)
    row = db.get_by_status(conn, "new")[0]
    assert row["external_id"] == "2"
    assert row["score_detail"] is None
```

(If `make_posting`/`NOW`/`json` aren't already imported in `test_db.py`, add
`import json` and extend the `from tests._helpers import ...` line.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && python -m pytest tests/test_db.py -k "pipeline_status or null_detail" -v`
Expected: FAIL — the `discarded` row is inserted as `new` (hardcoded), so `get_by_status(conn, "discarded")` is empty.

- [ ] **Step 3: Parametrize the INSERT**

In `db.py`, change `_INSERT` to bind the two columns instead of literals:

```python
_INSERT = """
INSERT INTO job_postings
    (source, external_id, company_slug, company_name, job_title, location, job_url,
     description, posted_at, score_detail, pipeline_status, attempts, created_at)
VALUES
    (:source, :external_id, :company_slug, :company_name, :job_title, :location, :job_url,
     :description, :posted_at, :score_detail, :pipeline_status, 0, :created_at)
ON CONFLICT(source, external_id) DO NOTHING
"""
```

In `upsert_postings`, add the two params to the dict (after `posted_at`/`created_at`):

```python
                "posted_at": (p.get("posted_at") or now)[:10],
                "created_at": now,
                # Optional per-row overrides: the fetch-time deterministic gate marks
                # a location/intern miss 'discarded' with a screen verdict, skipping
                # the Ollama call. Everything else inserts as a fresh 'new' row.
                "pipeline_status": p.get("pipeline_status") or "new",
                "score_detail": (
                    json.dumps(p["score_detail"]) if p.get("score_detail") is not None else None
                ),
```

(`json` is already imported in `db.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/worker && python -m pytest tests/test_db.py -v`
Expected: PASS (new tests + all existing upsert/db tests — the default-`new` path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/db.py apps/worker/tests/test_db.py
git commit -m "feat(worker): upsert_postings honors per-row pipeline_status + score_detail"
```

---

### Task 5: `run_fetch` — apply prefilter + tag deterministic discards

**Files:**
- Modify: `apps/worker/ats_worker/pipeline.py` (import ~35; `run_fetch` ~42-64)
- Test: `apps/worker/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `prefilter_postings` (Task 2), `score.deterministic_screen` (Task 3), `_score_detail` (existing, `pipeline.py:247`), `db.upsert_postings` (Task 4).
- Produces: `run_fetch(conn, companies, title_filter, *, now, fetch_fn=None, title_exclude=None, max_age_days=0, candidate=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_pipeline.py` (it imports `db, pipeline, score`, `_helpers.NOW`, `make_posting as _posting`, and `json as _json`):

```python
def test_run_fetch_marks_location_miss_discarded(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("1", location="Shanghai, China"),
                _posting("2", location="Remote")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn,
                                  candidate={"locations": ["remote", "USA"]})
    assert inserted == 2  # both rows recorded; the miss is discarded, not dropped
    assert [r["external_id"] for r in db.get_by_status(conn, "discarded")] == ["1"]
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["2"]
    detail = _json.loads(db.get_by_status(conn, "discarded")[0]["score_detail"])
    assert detail["disqualified"] is True
    assert detail["screen"]["location"]["pass"] is False


def test_run_fetch_drops_stale_by_max_age(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("fresh", posted_at="2026-06-01"),
                _posting("stale", posted_at="2026-01-01")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn,
                                  max_age_days=30)
    assert inserted == 1
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["fresh"]


def test_run_fetch_no_candidate_leaves_all_new(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [_posting("1", location="Shanghai, China")]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    assert [r["external_id"] for r in db.get_by_status(conn, "new")] == ["1"]
    assert db.get_by_status(conn, "discarded") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && python -m pytest tests/test_pipeline.py -k run_fetch -v`
Expected: FAIL — `run_fetch` has no `candidate`/`max_age_days` kwargs (TypeError), and no discard tagging.

- [ ] **Step 3: Wire the prefilter + tagging into `run_fetch`**

In `pipeline.py`, change the import at line 35:

```python
from .fetch import DETAIL_SOURCES, prefilter_postings
```

Replace the `run_fetch` signature and body (lines 42-64) with:

```python
def run_fetch(conn, companies, title_filter, *, now, fetch_fn=None,
              title_exclude=None, max_age_days=0, candidate=None) -> int:
    """Fetch every company, pre-filter (title keep/exclude + max-age), tag any
    deterministic disqualification (intern/location) so it lands 'discarded' WITHOUT
    an Ollama call, then upsert. Returns rows inserted.

    A failing company is logged-and-skipped (no posting to mark failed yet —
    nothing is in the db), so the remaining companies still ingest.
    """
    if fetch_fn is None:
        raise ValueError("run_fetch requires an injected fetch_fn (wired in run.py)")
    inserted = 0
    for c in companies:
        try:
            kw = {"recipe": c["recipe"]} if c.get("recipe") is not None else {}
            postings = fetch_fn(c["source"], c["slug"], c["name"], **kw)
            kept = prefilter_postings(
                postings, title_filter=title_filter, title_exclude=title_exclude,
                max_age_days=max_age_days, now=now)
            for p in kept:
                p["company_slug"] = c["slug"]
                if candidate:
                    verdict = score.deterministic_screen(
                        {"screen": {}, "disqualified": False, "disqualification_reason": ""},
                        p, candidate)
                    if verdict.get("disqualified"):
                        p["pipeline_status"] = "discarded"
                        p["score_detail"] = _score_detail(verdict, disqualified=True)
            inserted += db.upsert_postings(conn, kept, now=now)
        except Exception as exc:  # noqa: BLE001 — one bad board must not abort the rest
            print(f"[fetch] {c.get('source')}/{c.get('slug')}: skipped after error: {exc}")
            continue
    return inserted
```

(`score` and `db` are already imported at `pipeline.py:34`; `_score_detail` is defined at `pipeline.py:247`. Passing the `_score_detail` dict as `p["score_detail"]` is correct — `upsert_postings` `json.dumps`-es it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/worker && python -m pytest tests/test_pipeline.py -k run_fetch -v`
Expected: PASS (new tests + the four existing `run_fetch` tests — they pass `candidate=None`, so tagging is skipped and rows stay `new`).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/pipeline.py apps/worker/tests/test_pipeline.py
git commit -m "feat(worker): run_fetch pre-filters + tags deterministic discards pre-screen"
```

---

### Task 6: Wire config into `run.py` + document the keys

**Files:**
- Modify: `apps/worker/ats_worker/run.py` (candidate block ~194-203 → moved before the `run_fetch` call ~165)
- Modify: `apps/worker/config.yaml.example`
- Test: `apps/worker/tests/test_run.py`

**Interfaces:**
- Consumes: `Config.title_exclude`, `Config.max_age_days`, `Config.candidate` (Task 1); `run_fetch`'s new kwargs (Task 5).

- [ ] **Step 1: Write the failing test**

Add to `apps/worker/tests/test_run.py` (it imports `run`, `config as cfgmod`, and defines `_ENV`):

```python
def test_run_once_threads_fetch_filters(monkeypatch):
    captured = {}
    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda *a, **k: captured.update(k) or 0)
    for stage in ("run_retry", "run_score", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "max_age_days: 30\n"
        "title_exclude: [intern]\n"
        "candidate: { locations: [USA] }\n"
    )
    run.run_once(cfg, db_path=":memory:", resumes={"resume": "resume"}, env=_ENV)
    assert captured["max_age_days"] == 30
    assert captured["title_exclude"] == ["intern"]
    assert captured["candidate"]["locations"] == ["USA"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/worker && python -m pytest tests/test_run.py -k threads_fetch_filters -v`
Expected: FAIL — `run_fetch` is called without `max_age_days`/`title_exclude`/`candidate`, so `captured` lacks those keys (KeyError).

- [ ] **Step 3: Build `candidate` before `run_fetch` and pass the new kwargs**

In `run.py`, **move** the candidate-building block (currently ~194-203) to just above the `run_fetch` call (~165), so it reads:

```python
        # Build the screening checklist (candidate hard-requirements) once, up front:
        # run_fetch uses it for the deterministic pre-screen gate, and screen_fn below
        # reuses it. Empty candidate => None => no gate, no SCREEN call.
        if cfg.candidate.is_empty():
            candidate = None
        else:
            candidate = {
                "highest_degree": cfg.candidate.highest_degree,
                "work_authorization": cfg.candidate.work_authorization,
                "security_clearance": cfg.candidate.security_clearance,
                "locations": list(cfg.candidate.locations),
                "exclude_internships": cfg.candidate.exclude_internships,
            }

        pipeline.run_fetch(conn, companies, cfg.title_filter, now=now,
                           fetch_fn=fetch_company, title_exclude=cfg.title_exclude,
                           max_age_days=cfg.max_age_days, candidate=candidate)
```

Delete the now-duplicated candidate block from its old location (~194-203); leave the `num_ctx = ...` line and `screen_fn`/scorer wiring in place (they still reference `candidate`, now in scope from earlier).

- [ ] **Step 4: Document the keys in `config.yaml.example`**

Near the existing `title_filter:` entry, add:

```yaml
# Optional negative title pre-filter: DROP a posting whose title contains any of
# these (case-insensitive), the complement of title_filter. Empty/omitted = drop none.
title_exclude: [intern, "co-op", sales, principal, staff, director]

# Optional fetch-time freshness gate: drop a posting whose posted_at is older than
# this many days before it is ever screened/scored. 0 or omitted = off. Boards that
# don't publish a date (posted_at null) are always kept.
max_age_days: 30
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/worker && python -m pytest tests/test_run.py -v`
Expected: PASS (new wiring test + all existing run tests, including the stage-order test — its config sets no candidate, so `candidate=None` flows through).

- [ ] **Step 6: Commit**

```bash
git add apps/worker/ats_worker/run.py apps/worker/config.yaml.example apps/worker/tests/test_run.py
git commit -m "feat(worker): wire max_age_days/title_exclude/candidate into run_fetch"
```

---

### Task 7: Docs — SPEC, PROGRESS, CHANGELOG

**Files:**
- Modify: `docs/SPEC.md`
- Modify: `docs/PROGRESS.md`
- Modify: `CHANGELOG.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Run the full worker suite + coverage (evidence for the doc claims)**

Run: `make test-worker` then `cd apps/worker && python -m pytest --cov=ats_worker --cov-report=term-missing`
Expected: all green; coverage ≥ 85. Record the pass for the "Tested ✅" claims below.

- [ ] **Step 2: Update `docs/SPEC.md`**

- In the fetch section (§5 flow / §7, where `filter_postings` / `title_filter` are described, around the lines found via `grep -n "title_filter\|filter_postings" docs/SPEC.md`): note that the watchlist fetch path now applies `prefilter_postings` (positive `title_filter` keep + negative `title_exclude` drop + `max_age_days` freshness drop) and that the deterministic intern/location gates run **at fetch** via `deterministic_screen`, tagging a miss `discarded` (skipping the Ollama call) while the same helper still runs post-LLM inside `screen_posting` for the feed path.
- In the config-keys list: add `title_exclude` (negative title list) and `max_age_days` (freshness gate, 0 = off, null posted_at kept).
- In the §9 invariant→test map, add rows:
  - `Fetch-time max-age + title_exclude drop | test_fetch.py::test_prefilter_*`
  - `Deterministic gate hoisted to fetch (discarded, no Ollama) | test_pipeline.py::test_run_fetch_marks_location_miss_discarded`

- [ ] **Step 3: Update `docs/PROGRESS.md`**

Replace the "Fetch-time filtering — by date + per-board settings" entry (lines ~92-108) so **Phase 1 is shipped** and only **Phase 2** remains open:

```markdown
- **Fetch-time filtering — Phase 2 (per-board settings)** — `[M · design call]`.
  Phase 1 shipped (global `max_age_days` + `title_exclude` drops, and the deterministic
  intern/location gates hoisted ahead of the Ollama call on the watchlist path — see
  `docs/superpowers/specs/2026-07-20-fetch-time-filtering-design.md`). Still open: move
  keep-rules onto the watchlist row so each board carries its own query / keywords /
  locations / max-age (Amazon/Microsoft flood the scorer). **Design forks:** a nullable
  `filters` JSON column on `watched_companies` (Prisma-owned + drift fixture) vs. staying
  global-only; source-side query narrowing (recipe `base_query` — the only lever that
  cuts the scrape itself); and whether the `onboard-board` skill / Watchlist UI generates
  the per-board filter or the operator hand-sets it. Ties into [[design-work-preference]].
```

- [ ] **Step 4: Update `CHANGELOG.md`**

Under `## [Unreleased]` → `### Added` (create the subsection if absent, above `### Changed`):

```markdown
### Added

- **Fetch-time filtering (watchlist path).** Two global `config.yaml` knobs cut
  local-LLM volume before any model runs: `max_age_days` drops postings whose
  `posted_at` is older than N days (dateless boards kept; `0` = off), and
  `title_exclude` drops titles containing any listed keyword (the negative
  complement of `title_filter`). The deterministic intern/location screen gates now
  also run **at fetch** (`deterministic_screen`), so a location/intern miss is
  recorded `discarded` — visible in the Discovered "Discarded" bucket with its reason —
  **without** an Ollama call, instead of after it. No schema change. (Phase 1 of
  `docs/superpowers/specs/2026-07-20-fetch-time-filtering-design.md`; per-board rules
  remain future work in PROGRESS.)
```

- [ ] **Step 5: Commit**

```bash
git add docs/SPEC.md docs/PROGRESS.md CHANGELOG.md
git commit -m "docs: record fetch-time filtering Phase 1 (SPEC/PROGRESS/CHANGELOG)"
```

---

## Self-Review

**Spec coverage:**
- Two "noise" drop-filters (`max_age_days`, `title_exclude`) → Tasks 1, 2, 6. ✅
- Hoist deterministic gates via shared helper, feed path preserved → Task 3 (extraction, existing screen tests stay green) + Task 5 (fetch tagging). ✅
- Option B (keep discarded rows visible, skip Ollama) → Task 4 (upsert per-row status/detail) + Task 5 (tag `discarded` + `_score_detail`). ✅
- Config surface + example + wiring → Tasks 1, 6. ✅
- Invariant "fetch verdict == screen verdict" → guaranteed by reusing `deterministic_screen`; Task 3's existing-tests-green step is the check. ✅
- Docs (SPEC §5/§7/§9, PROGRESS narrow to Phase 2, CHANGELOG) → Task 7. ✅
- Non-goals honored: no schema change (only existing columns), feeds untouched (`run_feed` not modified), no LLM at fetch, no per-board column. ✅

**Placeholder scan:** none — every code and test step carries complete code and exact `pytest` commands.

**Type consistency:** `prefilter_postings(postings, *, title_filter, title_exclude, max_age_days, now)`, `deterministic_screen(screen, posting, candidate) -> dict`, `run_fetch(..., title_exclude=None, max_age_days=0, candidate=None)`, and `upsert_postings` reading `p["pipeline_status"]`/`p["score_detail"]` are used identically across Tasks 2–6. `_score_detail(result, *, disqualified=True)` returns a dict; `upsert_postings` `json.dumps`-es it — consistent, no double-encode (only the fetch tag sets `score_detail`, always a dict).
