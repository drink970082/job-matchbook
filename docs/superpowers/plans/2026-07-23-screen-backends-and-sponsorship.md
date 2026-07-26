# Screen Backends, Sponsorship Rework, and Concurrency — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user without a local GPU run the pipeline, by making the hard-requirements screen provider-agnostic; replace the ~2/11-recall sponsorship phrase list with a quote-grounded LLM check; and make both scoring loops concurrent.

**Architecture:** `screen_posting` gains one injected callable — `extract(prompt, schema) -> dict` — exactly mirroring how `fit_fn` is already injected. Six `SCREEN_BACKEND` values reduce to three adapter shapes (HTTP+schema, CLI subprocess, deterministic-only). All real service wiring stays in `run.py`; every other module stays pure and dependency-injected. Concurrency copies `run_feed`'s proven read-serial / network-parallel / write-serial shape.

**Tech Stack:** Python 3.11, pytest, `requests`, `anthropic` SDK, `codex` CLI, `claude` CLI, SQLite.

**Spec:** [`../specs/2026-07-23-screen-backends-and-sponsorship-design.md`](../specs/2026-07-23-screen-backends-and-sponsorship-design.md)

## Global Constraints

- **Worker modules are pure + dependency-injected.** Real services are wired ONLY in `ats_worker/run.py`. Tests mock everything — no network, no API keys, no GPU. Keep it that way.
- **Err toward keep, never toward discard.** An `extract` that raises must leave the posting NOT disqualified. A broken provider must never silently discard the queue. This invariant predates this work and must not regress.
- **Auto-detection must never select a paid backend.** Default stays `ollama`. Spending money is explicit opt-in.
- **Secrets are never promoted to argparse defaults.** `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` are read from the in-process `env` dict only — promoting them leaks them to subprocesses that inherit the environment (the codex CLI). See `run.py:66-75`.
- **SQLite connections are not thread-safe.** Every DB call stays on the calling thread. Network work parallelises; reads and writes do not.
- **Coverage floor `fail_under = 85`** (`apps/worker/pyproject.toml`). Run from `apps/worker` with `PYTHONPATH=. python3 -m pytest`.
- **Python: 4-space indent.** Commits: short imperative subject, optional `type(scope):` prefix. Each commit green.
- **Never edit `ats_worker/prompts/score.txt` outside Task 9**, and never without the gate in Task 10.

---

## File Structure

| File | Responsibility |
|---|---|
| `ats_worker/score/screen.py` (modify) | Screen composition; gains `extract` param, loses Ollama kwargs |
| `ats_worker/score/backends_screen.py` (create) | All six screen adapters. One file: they share the schema and are each ~20 lines |
| `ats_worker/score/prompts.py` (modify) | Gains `SCREEN_SCHEMA` |
| `ats_worker/prompts/screen.txt` (modify) | Sponsorship clause becomes quote-grounded |
| `ats_worker/prompts/score.txt` (modify, Task 9 ONLY) | Additive extraction block |
| `ats_worker/pipeline.py` (modify) | `run_score` concurrency |
| `ats_worker/run.py` (modify) | `make_screener`, CLI flags, wiring |
| `tools/sponsor_diff.py` (create) | Labeled-set gate for the sponsorship rework |
| `apps/worker/tests/test_score.py` (modify) | Existing screen tests migrate to `extract` |
| `apps/worker/tests/test_backends_screen.py` (create) | Per-adapter tests |
| `apps/worker/tests/test_pipeline.py` (modify) | Concurrency tests |

---

# STAGE 1 — The seam, `ollama`, and `none`

Ships the P1 premise on its own: a GPU-less user can run a pass with `SCREEN_BACKEND=none`.

## Task 1: Extract the Ollama transport behind an injected `extract`

**Files:**
- Modify: `apps/worker/ats_worker/score/screen.py:96-157` (`screen_posting`), `:160-189` (`_post`)
- Modify: `apps/worker/ats_worker/score/__init__.py` (re-export)
- Modify: `apps/worker/tests/test_score.py` (existing screen tests)

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `make_ollama_extract(*, http, ollama_host, model=None, temperature=0.0, seed=0, num_ctx=8192, timeout=180) -> Callable[[str, dict], dict]`
  - `screen_posting(posting, *, extract=None, candidate=None, num_ctx=8192) -> dict`

- [ ] **Step 1: Write the failing test**

Add to `apps/worker/tests/test_score.py`:

```python
def test_screen_posting_uses_injected_extract():
    # The screen's only backend-specific step is "give me JSON from this prompt".
    seen = {}

    def extract(prompt, schema):
        seen["prompt"] = prompt
        return {"screen": {"clearance": {"requires_clearance": True}}}

    out = score.screen_posting(POSTING, extract=extract,
                               candidate={"security_clearance": "none"})
    assert out["disqualified"] is True
    assert out["disqualification_reason"] == "clearance: requires security clearance"
    assert "=== JOB:" in seen["prompt"]


def test_screen_posting_without_extract_runs_deterministic_gates_only():
    # SCREEN_BACKEND=none: no LLM call, but the intern/location gates still fire.
    posting = dict(POSTING, job_title="Software Engineering Intern")
    out = score.screen_posting(posting, extract=None,
                               candidate={"exclude_internships": True,
                                          "security_clearance": "none"})
    assert out["disqualified"] is True
    assert "internship" in out["disqualification_reason"]


def test_extract_failure_errs_toward_keep():
    # A broken provider must NEVER discard the queue.
    def extract(prompt, schema):
        raise score.ScoreError("provider down")

    out = score.screen_posting(POSTING, extract=extract,
                               candidate={"highest_degree": "Master's"})
    assert out["disqualified"] is False
    assert out["screen"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_score.py::test_screen_posting_uses_injected_extract -v`
Expected: FAIL — `TypeError: screen_posting() got an unexpected keyword argument 'extract'`

- [ ] **Step 3: Add `make_ollama_extract` to `screen.py`**

Insert after `_post` (which stays exactly as it is — do not modify its body):

```python
def make_ollama_extract(*, http, ollama_host: str, model: str | None = None,
                        temperature: float = 0.0, seed: int = 0,
                        num_ctx: int = 8192, timeout: int = 180):
    """Build the `extract(prompt, schema) -> dict` callable for the local Ollama
    screen — the default backend, and the only free one.

    `schema` is accepted and ignored: this call uses Ollama's `format="json"` mode,
    which constrains output to *some* JSON object rather than to a schema. Keeping
    the parameter means every backend has one signature; the schema-enforcing
    backends use it. Behavior is byte-identical to the pre-seam call.
    """
    options = {
        "temperature": temperature,
        "seed": seed,
        "num_ctx": num_ctx,
        # Cap generation: the JSON answers are small, so this only bounds a
        # runaway (which otherwise stalls a call past the read timeout).
        "num_predict": 512,
    }

    def extract(prompt: str, schema: dict) -> dict:
        return _post(http, ollama_host, model, prompt, options=options, timeout=timeout)

    return extract
```

- [ ] **Step 4: Rewrite `screen_posting` to take `extract`**

Replace `screen_posting` (`screen.py:96-157`) entirely with:

```python
def screen_posting(posting: dict, *, extract=None, candidate: dict | None = None,
                   num_ctx: int = 8192) -> dict:
    """Screen `posting` against the candidate's hard requirements — the CHEAP half of
    scoring (no résumé, no paid fit call). Combines three signals into one verdict:

      1. The LLM extraction call (`extract`) reports structured JOB facts (required
         degree, sponsorship, clearance) for whatever the candidate configured; CODE
         (`_screen_verdict`) applies the candidate's constraint. Skipped entirely when
         no candidate constraints are configured OR when `extract` is None
         (SCREEN_BACKEND=none). A failure errs toward KEEP, never toward discard.
      2. A deterministic intern/co-op title check, gated by `exclude_internships`.
      3. A deterministic pycountry LOCATION gate (`resolve_location`), gated by
         `candidate["locations"]`, matched against the board's location string.

    `extract(prompt, schema) -> dict` is the ENTIRE backend contract — the one step
    that differs between ollama / codex / claude / openai / none. Build it with
    `make_ollama_extract` or `score.backends_screen.make_extract`; run.py wires it.

    Returns `{"screen": {...}, "disqualified": bool, "disqualification_reason": str}`.
    Takes no fit-scorer callable — it structurally cannot pay for the fit call.
    """
    job = _job_block(posting, num_ctx * 2)
    description = str(posting.get("description") or "")
    checklist = _candidate_block(candidate)
    screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    if checklist and extract is not None:
        try:
            data = extract(SCREEN_HEADER + checklist + "\n" + job, SCREEN_SCHEMA)
            screen = _screen_verdict(data, candidate or {}, description)
        except Exception:  # noqa: BLE001 — err toward KEEP on any provider failure
            screen = {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    # Deterministic CODE gates (intern title + location string), hoisted into a
    # shared helper so the fetch-time pre-filter applies the SAME verdict. No LLM.
    return deterministic_screen(screen, posting, candidate)
```

Add the import for `SCREEN_SCHEMA` at the top of `screen.py`, alongside the existing
`from .prompts import _candidate_block, _job_block`:

```python
from .prompts import SCREEN_SCHEMA, _candidate_block, _job_block
```

- [ ] **Step 5: Add `SCREEN_SCHEMA` to `prompts.py`**

Append to `apps/worker/ats_worker/score/prompts.py`:

```python
# Structured-output schema for the SCREEN extraction. Every field is OPTIONAL at the
# JSON-Schema level: the candidate configures which checks run, so a config with only
# `highest_degree` set legitimately returns just `degree`. Code (`_screen_verdict`)
# ignores keys the candidate didn't configure and errs toward PASS on absent data, so
# a permissive schema cannot cause a wrong disqualification.
SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "screen": {
            "type": "object",
            "properties": {
                "degree": {
                    "type": "object",
                    "properties": {"required_degree": {"type": ["string", "null"]}},
                    "additionalProperties": False,
                },
                "authorization": {
                    "type": "object",
                    "properties": {"no_sponsorship_quote": {"type": ["string", "null"]}},
                    "additionalProperties": False,
                },
                "clearance": {
                    "type": "object",
                    "properties": {"requires_clearance": {"type": "boolean"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    },
    "required": ["screen"],
    "additionalProperties": False,
}
```

Note: `no_sponsorship_quote` is added here in Task 1 so the schema is stable from the
start, but nothing reads it until Task 7. The current `screen.txt` still asks for
`offers_sponsorship`, which `_check_authorization` already ignores — so this is inert.

- [ ] **Step 6: Re-export the new symbols**

In `apps/worker/ats_worker/score/__init__.py`, add `SCREEN_SCHEMA` to the `.prompts`
import block and `make_ollama_extract` to the `.screen` import block:

```python
from .prompts import (  # noqa: F401  (re-export)
    _SCORE_SCHEMA,
    SCREEN_SCHEMA,
    _job_block,
    _score_schema,
    _scorer_system_blocks,
    _scorer_system_sections,
    _truncate,
)
from .screen import (  # noqa: F401  (re-export)
    _degree_rank,
    _flag,
    _is_internship,
    _needs_sponsorship,
    _normalize_score,
    deterministic_screen,
    make_ollama_extract,
    screen_posting,
)
```

- [ ] **Step 7: Migrate the existing screen tests**

Every existing `score.screen_posting(POSTING, http=http, ollama_host="h", model="m", ...)`
call must become an `extract=` call. Add this helper near the top of
`apps/worker/tests/test_score.py`, below the existing `FakeHttp` class:

```python
def _ollama(http, **kw):
    """Build the Ollama extract for tests that assert on the HTTP request shape."""
    kw.setdefault("ollama_host", "h")
    kw.setdefault("model", "m")
    return score.make_ollama_extract(http=http, **kw)
```

Then mechanically rewrite each call site. Two worked examples:

```python
# Before
out = score.screen_posting(POSTING, http=http, ollama_host="h", model="m",
                           candidate={"security_clearance": "none"}, num_ctx=8192)
# After
out = score.screen_posting(POSTING, extract=_ollama(http),
                           candidate={"security_clearance": "none"}, num_ctx=8192)

# Before (asserts on transport options)
score.screen_posting(POSTING, http=http, ollama_host="h", model="m",
                     seed=7, num_ctx=4096, candidate={"highest_degree": "Master's"})
# After — seed/num_ctx are transport options, so they move to the extract.
# num_ctx is ALSO passed to screen_posting, which uses it for JD truncation.
score.screen_posting(POSTING, extract=_ollama(http, seed=7, num_ctx=4096),
                     num_ctx=4096, candidate={"highest_degree": "Master's"})
```

Find every call site with:

```bash
cd apps/worker && grep -n "screen_posting(" tests/test_score.py
```

- [ ] **Step 8: Run the full worker suite**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest -q`
Expected: all tests pass (543 + 3 new = 546), zero failures.

- [ ] **Step 9: Commit**

```bash
git add apps/worker/ats_worker/score/screen.py apps/worker/ats_worker/score/prompts.py \
        apps/worker/ats_worker/score/__init__.py apps/worker/tests/test_score.py
git commit -m "refactor(worker): inject the screen's extraction call behind one seam

screen_posting's only backend-specific step was 'give me JSON from this prompt'
(the Ollama _post). It now takes an injected extract(prompt, schema) -> dict,
mirroring how fit_fn is already injected, so a non-Ollama screen backend is a new
callable rather than a new branch. make_ollama_extract preserves the existing call
byte-for-byte. extract=None runs the deterministic gates only, which is both the
existing no-candidate path and the future SCREEN_BACKEND=none."
```

---

## Task 2: `make_screener` with `ollama` and `none`, wired through the CLI

**Files:**
- Modify: `apps/worker/ats_worker/run.py:78-93` (next to `make_scorer`), `:134-141` (`run_once` signature), `:230-242` (`screen_fn`), `:355-390` (argparse)
- Modify: `apps/worker/tests/test_run.py`
- Modify: `apps/worker/.env.example`

**Interfaces:**
- Consumes: `make_ollama_extract` from Task 1
- Produces: `make_screener(backend, *, env, http, model=None, num_ctx=8192) -> Callable | None`; `run_once(..., screen_backend="ollama")`

- [ ] **Step 1: Write the failing test**

Add to `apps/worker/tests/test_run.py`:

```python
def test_make_screener_none_returns_no_extract():
    # SCREEN_BACKEND=none must produce NO callable at all — screen_posting then runs
    # the deterministic gates only and never attempts a provider call.
    assert run.make_screener("none", env={}, http=None) is None


def test_make_screener_ollama_builds_a_working_extract(monkeypatch):
    calls = []

    class FakeHttp:
        def post(self, url, json=None, timeout=None):
            calls.append(url)

            class R:
                status_code = 200

                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    return {"response": '{"screen": {}}'}
            return R()

    extract = run.make_screener("ollama", env={"OLLAMA_HOST": "http://x:11434"},
                                http=FakeHttp(), model="m")
    assert extract("prompt", {}) == {"screen": {}}
    assert calls == ["http://x:11434/api/generate"]


def test_make_screener_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown screen backend"):
        run.make_screener("gpt9", env={}, http=None)


def test_default_screen_backend_is_free():
    # "Auto-detection must never select a paid backend" is satisfied BY CONSTRUCTION:
    # there is no auto-detection. The backend is always explicit and defaults to the
    # free local one, so no code path can reach a metered provider without the operator
    # naming it. This test pins that property against a future "helpfully" added probe.
    assert run.DEFAULT_SCREEN_BACKEND == "ollama"
    assert run.make_screener(run.DEFAULT_SCREEN_BACKEND, env={}, http=None,
                             model="m") is not None
```

Add `import pytest` at the top of `test_run.py` if it is not already imported.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_run.py::test_make_screener_none_returns_no_extract -v`
Expected: FAIL — `AttributeError: module 'ats_worker.run' has no attribute 'make_screener'`

- [ ] **Step 3: Add `make_screener` to `run.py`**

Insert immediately after `make_scorer` (`run.py:93`):

```python
# The screen's default stays the free local backend. AUTO-DETECTION MUST NEVER SELECT
# A PAID BACKEND — spending money is explicit opt-in via SCREEN_BACKEND. `make doctor`
# reports which providers are actually installed; the operator (or onboard-me Step 0)
# chooses from that, and this function never guesses.
DEFAULT_SCREEN_BACKEND = "ollama"
SCREEN_BACKENDS = ("ollama", "codex", "claude-code", "claude-api", "openai-api", "none")


def make_screener(backend: str, *, env, http=None, model=None, num_ctx: int = 8192):
    """Pick the screen backend, returning the `extract(prompt, schema) -> dict`
    callable `screen_posting` consumes — or None for `none`, which runs the
    deterministic gates only (documented as LOW RECALL on sponsorship: it falls back
    to the closed NO_SPONSOR_PHRASES list, ~2/11 recall).
    """
    if backend == "none":
        return None
    if backend == "ollama":
        return make_ollama_extract(
            http=http, model=model or DEFAULT_OLLAMA_MODEL,
            ollama_host=env.get("OLLAMA_HOST", "http://localhost:11434"),
            num_ctx=num_ctx,
        )
    raise ValueError(
        f"unknown screen backend: {backend!r} (want one of {', '.join(SCREEN_BACKENDS)})")
```

Add `make_ollama_extract` to the existing `from .score import ...` line at `run.py:27`:

```python
from .score import (make_claude_scorer, make_codex_scorer, make_ollama_extract,
                    screen_posting)
```

- [ ] **Step 4: Run the test to verify `none` and `ollama` pass**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_run.py -k make_screener -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire it into `run_once`**

Change the `run_once` signature (`run.py:134-141`) to add `screen_backend`:

```python
def run_once(cfg, *, db_path, resumes, profile="", env,
             ollama_model=DEFAULT_OLLAMA_MODEL,
             screen_backend=DEFAULT_SCREEN_BACKEND,
             score_backend=DEFAULT_SCORE_BACKEND,
             codex_score_model=DEFAULT_CODEX_SCORE_MODEL,
             anthropic_score_model=DEFAULT_ANTHROPIC_SCORE_MODEL,
             batch_size: int = DEFAULT_BATCH_SIZE,
             fetch_only: bool = False, score_only: bool = False,
             score_limit: int = 0) -> None:
```

Replace the `screen_fn` closure (`run.py:234-242`) with:

```python
        screen_extract = make_screener(screen_backend, env=env, http=requests,
                                       model=ollama_model, num_ctx=num_ctx)

        def screen_fn(posting):
            return screen_posting(posting, extract=screen_extract,
                                  candidate=candidate, num_ctx=num_ctx)
```

- [ ] **Step 6: Add the CLI flag and env key**

In `run.py`'s argparse block (after `--score-backend`, `run.py:369`):

```python
    parser.add_argument("--screen-backend", choices=SCREEN_BACKENDS,
                        default=os.environ.get("SCREEN_BACKEND",
                                               DEFAULT_SCREEN_BACKEND),
                        help="hard-requirements screen backend. Default 'ollama' "
                             "(free, local). 'none' runs the deterministic gates "
                             "only and is LOW RECALL on sponsorship")
```

Add `"SCREEN_BACKEND"` to `_ENV_ARGPARSE_KEYS` (`run.py:72-75`) — it is non-secret,
so it follows the existing pattern:

```python
_ENV_ARGPARSE_KEYS = frozenset({
    "DB_PATH", "OLLAMA_MODEL", "SCREEN_BACKEND", "SCORE_BACKEND",
    "CODEX_SCORE_MODEL", "ANTHROPIC_SCORE_MODEL", "CODEX_BATCH_SIZE",
})
```

Pass it through at the `run_once(...)` call site in `main` (find it with
`grep -n "run_once(" apps/worker/ats_worker/run.py`):

```python
        screen_backend=args.screen_backend,
```

Append to `apps/worker/.env.example`:

```
# Hard-requirements screen backend: ollama (default, free, local) | codex |
# claude-code | claude-api | openai-api | none.
# 'none' runs only the deterministic gates (location, internships) and is LOW RECALL
# on sponsorship — it falls back to a 12-phrase substring list (~2/11 recall).
# SCREEN_BACKEND=ollama
```

- [ ] **Step 7: Test the wiring end-to-end**

Add to `apps/worker/tests/test_run.py`:

```python
def test_run_once_screen_backend_none_makes_no_provider_call(monkeypatch, tmp_path):
    # A GPU-less user: the pass must complete with zero screen calls.
    _stub_stages(monkeypatch)
    seen = {}
    monkeypatch.setattr(run, "make_screener",
                        lambda backend, **kw: seen.setdefault("backend", backend))
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile),
                 resumes={"resume": "r"}, env=_ENV, screen_backend="none")
    assert seen["backend"] == "none"
```

- [ ] **Step 8: Run the full suite**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add apps/worker/ats_worker/run.py apps/worker/tests/test_run.py apps/worker/.env.example
git commit -m "feat(worker): add SCREEN_BACKEND with ollama and none

make_screener mirrors make_scorer: it returns the extract callable screen_posting
consumes, or None for 'none' (deterministic gates only). Default stays ollama and
auto-detection never selects a paid backend. SCREEN_BACKEND is non-secret so it
follows the existing argparse-default pattern; API keys deliberately do not.

'none' unblocks a GPU-less user today, at the cost of low sponsorship recall until
the quote-grounded check lands."
```

---

# STAGE 2 — The hosted backends

## Task 3: `claude-api` screen adapter

**Files:**
- Create: `apps/worker/ats_worker/score/backends_screen.py`
- Create: `apps/worker/tests/test_backends_screen.py`
- Modify: `apps/worker/ats_worker/run.py` (`make_screener`)

**Interfaces:**
- Consumes: `SCREEN_SCHEMA` (Task 1), `make_screener` (Task 2)
- Produces: `make_claude_api_extract(api_key, model="claude-haiku-4-5", *, max_tokens=1024) -> Callable[[str, dict], dict]`

- [ ] **Step 1: Write the failing test**

Create `apps/worker/tests/test_backends_screen.py`:

```python
"""Screen backends: the six `extract(prompt, schema) -> dict` adapters."""
import json
import sys
import types

import pytest

from ats_worker.score import backends_screen
from ats_worker.score.errors import ScoreError


def _fake_anthropic(captured, text='{"screen": {}}'):
    """A stand-in `anthropic` module. The real SDK is never imported in tests."""
    mod = types.ModuleType("anthropic")

    class _Messages:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            block = types.SimpleNamespace(type="text", text=text)
            return types.SimpleNamespace(content=[block])

    class Anthropic:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _Messages()

    mod.Anthropic = Anthropic
    return mod


def test_claude_api_extract_returns_parsed_json(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(captured))
    extract = backends_screen.make_claude_api_extract("sk-test")
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    assert captured["model"] == "claude-haiku-4-5"
    assert captured["api_key"] == "sk-test"
    # The schema must actually constrain the response, not just ride along.
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["output_config"]["format"]["schema"] == {"type": "object"}


def test_claude_api_extract_raises_score_error_on_non_json(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic",
                        _fake_anthropic({}, text="not json {{{"))
    extract = backends_screen.make_claude_api_extract("sk-test")
    with pytest.raises(ScoreError):
        extract("p", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_backends_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ats_worker.score.backends_screen'`

- [ ] **Step 3: Create `backends_screen.py`**

```python
"""Screen backends — the `extract(prompt, schema) -> dict` adapters that
`score.screen.screen_posting` consumes.

Six SCREEN_BACKEND values, three shapes:
  · HTTP + JSON schema — ollama (see score.screen.make_ollama_extract), claude-api,
    openai-api
  · CLI subprocess + a schema file — codex, claude-code
  · none — no adapter at all; run.make_screener returns None

Every adapter returns the PARSED dict or raises ScoreError. Nothing here decides
whether a posting is disqualified: the model only extracts JOB facts, and
`score.screen._screen_verdict` applies the candidate's constraint in code. A raised
ScoreError is caught by screen_posting and errs toward KEEP.

Imports of provider SDKs are deferred to the first call so importing this module —
and building an adapter in tests — never needs the SDK or a key.
"""
from __future__ import annotations

import json

from .errors import ScoreError

# Two-to-three fields of fact extraction. Haiku is the right tier — Sonnet is wasted
# money on this shape. Override per-deploy with SCREEN_MODEL.
DEFAULT_CLAUDE_SCREEN_MODEL = "claude-haiku-4-5"


def _parse(raw: str, provider: str) -> dict:
    """Parse a provider's text response into the extraction dict, or raise."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScoreError(f"{provider} returned non-JSON screen: {raw!r}") from exc
    if not isinstance(data, dict):
        raise ScoreError(f"{provider} screen was not a JSON object: {data!r}")
    return data


def make_claude_api_extract(api_key: str, model: str = DEFAULT_CLAUDE_SCREEN_MODEL, *,
                            max_tokens: int = 1024):
    """Screen via the metered Anthropic API, schema-constrained by structured outputs
    (the same mechanism backends_claude.py already uses for the fit call).

    No prompt caching: unlike the fit call there is no large shared prefix — the
    checklist is a few hundred tokens and the JD is fresh every call.
    """
    cell: list = []

    def extract(prompt: str, schema: dict) -> dict:
        if not cell:
            import anthropic  # lazy: only at runtime
            cell.append(anthropic.Anthropic(api_key=api_key))
        msg = cell[0].messages.create(
            model=model,
            max_tokens=max_tokens,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
        return _parse(text, "claude-api")

    return extract
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_backends_screen.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire it into `make_screener`**

In `run.py`'s `make_screener`, before the final `raise ValueError`:

```python
    if backend == "claude-api":
        return make_claude_api_extract(env["ANTHROPIC_API_KEY"],
                                       model or DEFAULT_CLAUDE_SCREEN_MODEL)
```

Add the import to `run.py`:

```python
from .score.backends_screen import (DEFAULT_CLAUDE_SCREEN_MODEL,
                                    make_claude_api_extract)
```

Note `model` here is the `--screen-model` override added in Task 6; until then callers
pass `model=None` and the default applies. To avoid a forward dependency, change
`make_screener`'s signature now to take `screen_model=None` separately from the Ollama
`model`:

```python
def make_screener(backend: str, *, env, http=None, model=None, screen_model=None,
                  num_ctx: int = 8192):
```

and use `screen_model or DEFAULT_CLAUDE_SCREEN_MODEL` in the claude-api branch, leaving
the ollama branch on `model`.

- [ ] **Step 6: Run the full suite and commit**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest -q`
Expected: all pass.

```bash
git add apps/worker/ats_worker/score/backends_screen.py \
        apps/worker/tests/test_backends_screen.py apps/worker/ats_worker/run.py
git commit -m "feat(worker): add the claude-api screen backend

Schema-constrained via structured outputs, the same mechanism the Claude fit
backend already uses. claude-haiku-4-5 by default: three-field fact extraction is
exactly the tier's job and Sonnet would be wasted money. The SDK import is deferred
to the first call so tests and module load never need it."
```

---

## Task 4: `openai-api` screen adapter

**Files:**
- Modify: `apps/worker/ats_worker/score/backends_screen.py`
- Modify: `apps/worker/tests/test_backends_screen.py`
- Modify: `apps/worker/ats_worker/run.py`, `apps/worker/.env.example`

**Interfaces:**
- Consumes: `_parse` (Task 3)
- Produces: `make_openai_api_extract(api_key, model="gpt-5.6-luna", *, http=None, base_url="https://api.openai.com/v1", timeout=60) -> Callable[[str, dict], dict]`

- [ ] **Step 1: Verify the current OpenAI structured-outputs request shape**

Before writing code, confirm the request shape against current docs — the endpoint and
the structured-output field have both moved in the past.

Run: WebFetch `https://developers.openai.com/api/docs/` with the prompt
*"What is the current request shape for structured outputs with a JSON schema — which
endpoint, and which request field carries the schema? Show a minimal example."*

If the shape differs from Step 3's code, adjust Step 3 and note the deviation in the
commit message. Do not guess — this is the one adapter whose wire format is unverified.

- [ ] **Step 2: Write the failing test**

Add to `apps/worker/tests/test_backends_screen.py`:

```python
class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResp(self._payload, self._status)


def test_openai_api_extract_returns_parsed_json():
    http = _FakeHttp({"choices": [{"message": {"content": '{"screen": {}}'}}]})
    extract = backends_screen.make_openai_api_extract("sk-oa", http=http)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    body = http.calls[0]["json"]
    assert body["model"] == "gpt-5.6-luna"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer sk-oa"
    assert body["response_format"]["type"] == "json_schema"


def test_openai_api_extract_raises_score_error_on_empty_choices():
    http = _FakeHttp({"choices": []})
    extract = backends_screen.make_openai_api_extract("sk-oa", http=http)
    with pytest.raises(ScoreError):
        extract("p", {})
```

- [ ] **Step 3: Implement the adapter**

Append to `backends_screen.py`:

```python
# Cheapest of the three frontier models ($1/$6 per MTok, 1.05M ctx) and it supports
# structured outputs. Aggregator sites claim a cheaper "nano" tier; OpenAI's own models
# page does not list one, so it is deliberately not hard-coded here.
DEFAULT_OPENAI_SCREEN_MODEL = "gpt-5.6-luna"


def make_openai_api_extract(api_key: str, model: str = DEFAULT_OPENAI_SCREEN_MODEL, *,
                            http=None, base_url: str = "https://api.openai.com/v1",
                            timeout: int = 60):
    """Screen via the metered OpenAI API over plain `requests` — no new dependency.
    `http` is injected (the real `requests` module is bound only in run.py) so tests
    exercise the parsing with a fake transport and zero network.
    """
    def extract(prompt: str, schema: dict) -> dict:
        resp = http.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "screen", "strict": True,
                                    "schema": schema},
                },
            },
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not choices:
            raise ScoreError(f"openai-api returned no choices: {payload!r}")
        return _parse(choices[0].get("message", {}).get("content", ""), "openai-api")

    return extract
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_backends_screen.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire it in**

In `run.py`'s `make_screener`:

```python
    if backend == "openai-api":
        return make_openai_api_extract(env["OPENAI_API_KEY"],
                                       screen_model or DEFAULT_OPENAI_SCREEN_MODEL,
                                       http=http)
```

Append to `apps/worker/.env.example`:

```
# OpenAI API key — used ONLY when SCREEN_BACKEND=openai-api (metered).
# OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
```

Add an `openai api key` row to `ats_worker/doctor.py`'s `run_checks` (soft, like the
anthropic one), immediately after the existing `anthropic api key` Check:

```python
        Check("openai api key", bool(env.get("OPENAI_API_KEY")),
              "set" if env.get("OPENAI_API_KEY")
              else "unset (needed only for SCREEN_BACKEND=openai-api)", core=False),
```

- [ ] **Step 6: Run the full suite and commit**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest -q`

```bash
git add apps/worker/ats_worker/score/backends_screen.py apps/worker/tests/test_backends_screen.py \
        apps/worker/ats_worker/run.py apps/worker/ats_worker/doctor.py apps/worker/.env.example
git commit -m "feat(worker): add the openai-api screen backend

Plain requests against chat/completions with a json_schema response_format — no new
dependency, and http is injected so tests need no network. gpt-5.6-luna is the
cheapest frontier model that supports structured outputs. doctor gains an openai
api key row (soft, like the anthropic one)."
```

---

## Task 5: `codex` and `claude-code` subprocess screen adapters

**Files:**
- Modify: `apps/worker/ats_worker/score/backends_screen.py`
- Modify: `apps/worker/tests/test_backends_screen.py`
- Modify: `apps/worker/ats_worker/run.py`

**Interfaces:**
- Consumes: `_parse` (Task 3)
- Produces:
  - `make_codex_extract(model="gpt-5.6-sol", *, codex_bin="codex", timeout=180, runner=None) -> Callable`
  - `make_claude_code_extract(model=None, *, claude_bin="claude", timeout=180, runner=None) -> Callable`

- [ ] **Step 1: Write the failing test**

Add to `apps/worker/tests/test_backends_screen.py`:

```python
def _fake_runner(stdout="", returncode=0, writes=None):
    """Stand in for subprocess.run. `writes` maps a flag to the JSON written to the
    path that follows it, emulating a CLI that writes its result to a file."""
    calls = []

    def run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        for flag, payload in (writes or {}).items():
            path = cmd[cmd.index(flag) + 1]
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(payload)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    run.calls = calls
    return run


def test_codex_extract_reads_the_output_file():
    runner = _fake_runner(writes={"--output-last-message": '{"screen": {}}'})
    extract = backends_screen.make_codex_extract(runner=runner)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    cmd = runner.calls[0]["cmd"]
    # Tool-less is a SECURITY boundary, not a tuning choice: a JD is untrusted text
    # and codex exec is natively an agent holding a shell.
    assert "--disable" in cmd and "shell_tool" in cmd
    assert 'web_search="disabled"' in cmd
    assert "--output-schema" in cmd


def test_codex_extract_raises_on_nonzero_exit():
    extract = backends_screen.make_codex_extract(runner=_fake_runner(returncode=1))
    with pytest.raises(ScoreError, match="codex"):
        extract("p", {})


def test_claude_code_extract_parses_stdout_json():
    runner = _fake_runner(stdout=json.dumps({"result": '{"screen": {}}'}))
    extract = backends_screen.make_claude_code_extract(runner=runner)
    assert extract("the prompt", {"type": "object"}) == {"screen": {}}
    cmd = runner.calls[0]["cmd"]
    assert "--print" in cmd
    assert "--json-schema" in cmd
    assert "--output-format" in cmd and "json" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_backends_screen.py -k codex -v`
Expected: FAIL — `AttributeError: module has no attribute 'make_codex_extract'`

- [ ] **Step 3: Implement both subprocess adapters**

Append to `backends_screen.py` (add `import os`, `import subprocess`, `import tempfile`
to the imports at the top):

```python
# The codex screen ships on the model already trusted for fit scoring. gpt-5.6-luna is
# the cheaper candidate, but run.py rejects luna on MEASURED golden-set grounds (~3x
# looser spread) — a verdict measured on calibration-sensitive JUDGMENT, which does not
# obviously transfer to extraction. Re-measure before switching; do not assume.
DEFAULT_CODEX_SCREEN_MODEL = "gpt-5.6-sol"


def _run_cli(runner, cmd, prompt, timeout, provider):
    """Shared subprocess call for the CLI-shaped backends."""
    try:
        proc = runner(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ScoreError(f"{provider} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise ScoreError(f"{provider} binary not found: {cmd[0]!r}") from exc
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip()[-400:]
        raise ScoreError(f"{provider} failed (exit {proc.returncode}): {tail}")
    return proc


def make_codex_extract(model: str = DEFAULT_CODEX_SCREEN_MODEL, *,
                       codex_bin: str = "codex", timeout: int = 180, runner=None):
    """Screen via the Codex CLI on the operator's ChatGPT subscription.

    Runs TOOL-LESS (`--disable shell_tool`, `web_search="disabled"`) — a security
    boundary, not a tuning choice: a JD is untrusted scraped text and `codex exec` is
    natively an agent holding a shell, so a posting could otherwise ask it to read
    ~/.codex/auth.json and echo a secret into the output. Same posture as the fit
    backend. `--ephemeral` suppresses the session rollout so a JD never lands on disk;
    the screen does not capture quota usage (that rides the fit call).
    """
    runner = runner or subprocess.run

    def extract(prompt: str, schema: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = os.path.join(tmp, "schema.json")
            out_path = os.path.join(tmp, "out.json")
            with open(schema_path, "w", encoding="utf-8") as fh:
                json.dump(schema, fh)
            cmd = [codex_bin, "exec", "--model", model,
                   "--disable", "shell_tool",
                   "-c", 'web_search="disabled"',
                   "--output-schema", schema_path,
                   "--output-last-message", out_path,
                   "--sandbox", "read-only", "--skip-git-repo-check",
                   "--ephemeral", "--color", "never", "-C", tmp, "-"]
            _run_cli(runner, cmd, prompt, timeout, "codex screen")
            try:
                with open(out_path, encoding="utf-8") as fh:
                    return _parse(fh.read(), "codex screen")
            except OSError as exc:
                raise ScoreError(f"codex screen wrote no output: {exc}") from exc

    return extract


def make_claude_code_extract(model: str | None = None, *, claude_bin: str = "claude",
                             timeout: int = 180, runner=None):
    """Screen via the Claude Code CLI on the operator's subscription.

    `--json-schema` constrains the structured output and `--output-format json` wraps
    the result; both require `--print`. The wrapper's `result` field carries the model's
    text, which is the schema-constrained JSON we want.
    """
    runner = runner or subprocess.run

    def extract(prompt: str, schema: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = os.path.join(tmp, "schema.json")
            with open(schema_path, "w", encoding="utf-8") as fh:
                json.dump(schema, fh)
            cmd = [claude_bin, "--print",
                   "--json-schema", schema_path,
                   "--output-format", "json"]
            if model:
                cmd += ["--model", model]
            proc = _run_cli(runner, cmd, prompt, timeout, "claude-code screen")
            envelope = _parse(proc.stdout, "claude-code screen")
            return _parse(str(envelope.get("result", "")), "claude-code screen")

    return extract
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_backends_screen.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Wire both into `make_screener`**

```python
    if backend == "codex":
        return make_codex_extract(screen_model or DEFAULT_CODEX_SCREEN_MODEL)
    if backend == "claude-code":
        return make_claude_code_extract(screen_model)
```

- [ ] **Step 6: Verify `--json-schema` accepts a file path, not inline JSON**

The CLI help says `--json-schema <schema>` without specifying. Confirm before shipping:

Run: `claude --print --json-schema /tmp/nonexistent.json --output-format json <<< "hi"`
Expected: an error naming the missing FILE (confirming a path is expected). If instead
it complains about invalid JSON, the flag takes inline JSON — change Step 3 to pass
`json.dumps(schema)` directly instead of writing a temp file, and drop the
`TemporaryDirectory` from that adapter.

- [ ] **Step 7: Run the full suite and commit**

```bash
git add apps/worker/ats_worker/score/backends_screen.py \
        apps/worker/tests/test_backends_screen.py apps/worker/ats_worker/run.py
git commit -m "feat(worker): add the codex and claude-code screen backends

Both are CLI subprocess shapes with a schema file. codex runs tool-less
(--disable shell_tool, web_search=disabled, --ephemeral) — the same security
boundary the fit backend documents, since a JD is untrusted scraped text and codex
exec is natively an agent holding a shell. The screen ships on gpt-5.6-sol: luna is
cheaper but was rejected on measured grounds for fit scoring, and that verdict must
be re-measured on extraction rather than assumed to transfer."
```

---

## Task 6: `--screen-model` override and backend documentation

**Files:**
- Modify: `apps/worker/ats_worker/run.py`, `apps/worker/.env.example`
- Modify: `docs/SPEC.md` (§7.1), `docs/SETUP.md`, `CHANGELOG.md`, `docs/PROGRESS.md`

**Interfaces:**
- Consumes: all adapters from Tasks 3-5
- Produces: `--screen-model` / `SCREEN_MODEL`

- [ ] **Step 1: Add the flag**

```python
    parser.add_argument("--screen-model",
                        default=os.environ.get("SCREEN_MODEL"),
                        help="model for the screen backend (default: per-backend — "
                             "qwen3.5:4b / claude-haiku-4-5 / gpt-5.6-luna / "
                             "gpt-5.6-sol)")
```

Add `"SCREEN_MODEL"` to `_ENV_ARGPARSE_KEYS`, pass `screen_model=args.screen_model`
through `run_once` to `make_screener`.

- [ ] **Step 2: Test the override reaches the adapter**

```python
def test_screen_model_override_reaches_the_backend(monkeypatch):
    captured = {}
    monkeypatch.setattr(run, "make_claude_api_extract",
                        lambda key, model, **kw: captured.update(model=model))
    run.make_screener("claude-api", env={"ANTHROPIC_API_KEY": "k"},
                      screen_model="claude-sonnet-5")
    assert captured["model"] == "claude-sonnet-5"
```

- [ ] **Step 3: Update the docs**

`docs/SPEC.md` §7.1 — document `SCREEN_BACKEND`, the six values, the three adapter
shapes, the per-backend default models, and that auto-detection never selects a paid
backend. State plainly that `none` is low-recall on sponsorship.

`docs/SETUP.md` — the prerequisites table's Ollama row becomes "or any of five other
screen backends"; add `SCREEN_BACKEND` to the settings section.

`CHANGELOG.md` under `### Added`, and close the Track 1 entry in `docs/PROGRESS.md`.

- [ ] **Step 4: Run the full suite and commit**

```bash
git add -A && git commit -m "feat(worker): add --screen-model and document the screen backends"
```

---

# STAGE 3 — Quote-grounded sponsorship

## Task 7: Replace the sponsorship phrase list with a quote-grounded check

**Files:**
- Modify: `apps/worker/ats_worker/prompts/screen.txt:13-14` (`c_authorization`)
- Modify: `apps/worker/ats_worker/score/screen.py:51-62` (`NO_SPONSOR_PHRASES` comment), `:307-318` (`_check_authorization`), `:282-287` (`_screen_verdict` gate call)
- Modify: `apps/worker/tests/test_score.py`

**Interfaces:**
- Consumes: `SCREEN_SCHEMA.screen.authorization.no_sponsorship_quote` (Task 1)
- Produces: `_check_authorization(cand_auth, description, entry=None) -> tuple[bool, str]`; `_quote_in(quote, description) -> bool`

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_score.py`:

```python
# --- quote-grounded sponsorship ------------------------------------------

_NEEDS_VISA = {"work_authorization": "needs visa sponsorship"}


def _screen_with(quote, description):
    http = FakeHttp(json.dumps(
        {"screen": {"authorization": {"no_sponsorship_quote": quote}}}))
    posting = dict(POSTING, description=description)
    return score.screen_posting(posting, extract=_ollama(http), candidate=_NEEDS_VISA)


def test_verified_quote_disqualifies():
    jd = "Great role. US Citizenship is required for this position. Apply now."
    out = _screen_with("US Citizenship is required for this position.", jd)
    assert out["disqualified"] is True
    assert "sponsorship" in out["disqualification_reason"]


def test_hallucinated_quote_keeps_the_posting():
    # THE security property of this design: a quote that is not in the JD fails
    # verification, so hallucination cannot disqualify anything BY CONSTRUCTION.
    jd = "Great role. We welcome applicants from all backgrounds."
    out = _screen_with("We do not sponsor visas.", jd)
    assert out["disqualified"] is False


def test_quote_match_tolerates_line_wraps_and_casing():
    # A faithful quote legitimately differs in whitespace and case; invented text does not.
    jd = "We will NOT sponsor\n   employment visas for this role."
    out = _screen_with("we will not sponsor employment visas for this role.", jd)
    assert out["disqualified"] is True


def test_null_quote_falls_through_to_the_phrase_floor():
    # The list is demoted to a floor that can only ADD a disqualification.
    jd = "This employer does not sponsor applicants for work visas."
    out = _screen_with(None, jd)
    assert out["disqualified"] is True


def test_silent_jd_with_null_quote_is_kept():
    out = _screen_with(None, "A normal job description with no sponsorship language.")
    assert out["disqualified"] is False


def test_candidate_not_needing_sponsorship_is_never_gated():
    http = FakeHttp(json.dumps(
        {"screen": {"authorization": {"no_sponsorship_quote": "We will not sponsor."}}}))
    posting = dict(POSTING, description="We will not sponsor.")
    out = score.screen_posting(posting, extract=_ollama(http),
                               candidate={"work_authorization": "citizen"})
    assert out["disqualified"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_score.py -k quote -v`
Expected: FAIL — the quote is ignored today, so `test_verified_quote_disqualifies` fails.

- [ ] **Step 3: Update the prompt**

Replace the `@@ c_authorization` section of `apps/worker/ats_worker/prompts/screen.txt`:

```
@@ c_authorization
- authorization: report {"no_sponsorship_quote": "<the EXACT sentence, copied verbatim from the JOB text, stating that visa sponsorship is NOT available (e.g. 'We will not sponsor visas for this role.', 'US Citizenship is required.', 'Must be authorized to work without sponsorship.'). Copy it word for word — it is verified against the posting and a sentence that does not appear there is discarded. Use null if the posting does not say this. MOST postings never mention sponsorship — those are null>"}.
```

- [ ] **Step 4: Implement the quote check**

Replace `_check_authorization` (`screen.py:307-318`) with:

```python
def _quote_in(quote, description: str) -> bool:
    """Is `quote` actually present in the JD? Whitespace-collapsed and case-insensitive,
    matching the normalization the phrase floor already uses — that tolerates the ways a
    FAITHFUL quote legitimately differs (line wraps, casing) without tolerating invented
    text. This is what makes hallucination unable to disqualify."""
    needle = " ".join(str(quote or "").lower().split())
    if not needle:
        return False
    return needle in " ".join((description or "").lower().split())


def _check_authorization(cand_auth, description: str = "",
                         entry: dict | None = None) -> tuple[bool, str]:
    """Fail only when the candidate needs sponsorship AND the JD says it isn't offered.

    Primary check: the model returns `no_sponsorship_quote`, the verbatim JD sentence
    saying so, and CODE verifies that sentence actually appears in the description
    before acting on it. A hallucinated quote fails verification and the posting is
    KEPT — hallucination cannot disqualify anything by construction, not by trust.
    This holds on qwen3.5:4b too, so D1 needs no re-litigating.

    Floor: NO_SPONSOR_PHRASES still runs and can only ADD a disqualification. It never
    vetoes a model pass, so the closed list's ~2/11 recall is a floor, not a ceiling.
    """
    if not _needs_sponsorship(cand_auth):
        return True, ""
    quote = (entry or {}).get("no_sponsorship_quote")
    if _quote_in(quote, description):
        return False, "no visa sponsorship offered"
    text = " ".join((description or "").lower().split())
    if any(phrase in text for phrase in NO_SPONSOR_PHRASES):
        return False, "no visa sponsorship offered"
    return True, ""
```

Update the call in `_screen_verdict` (`screen.py:284-285`) to pass the entry:

```python
    gate("authorization", bool(str(candidate.get("work_authorization") or "").strip()),
         *_check_authorization(candidate.get("work_authorization"), description,
                               entry("authorization")))
```

Update the `NO_SPONSOR_PHRASES` comment (`screen.py:51-56`) to say it is now a floor:

```python
# The FLOOR for the sponsorship gate, not the gate itself. The primary check is the
# quote-grounded LLM extraction in _check_authorization; this closed list runs after it
# and can only ADD a disqualification, never veto a model pass. Measured recall on its
# own is ~2/11 realistic phrasings, which is why it was demoted. Kept because it costs
# nothing and catches the blunt wordings even on SCREEN_BACKEND=none.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_score.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/worker/ats_worker/prompts/screen.txt apps/worker/ats_worker/score/screen.py \
        apps/worker/tests/test_score.py
git commit -m "feat(worker): ground the sponsorship screen in a verbatim JD quote

The model now returns the exact JD sentence stating sponsorship is unavailable, and
code verifies that sentence appears in the description before disqualifying. A
hallucinated quote fails verification and the posting is KEPT, so hallucination
cannot disqualify anything by construction rather than by trust — which is why this
works on qwen3.5:4b and D1 needs no re-litigating.

NO_SPONSOR_PHRASES is demoted to a floor that can only add disqualifications; its
measured ~2/11 recall is now a floor, not the ceiling."
```

---

## Task 8: The sponsorship labeled-set gate

**Files:**
- Create: `tools/sponsor_diff.py`

**Interfaces:**
- Consumes: `screen_posting`, `make_screener` (Tasks 1-5), `_check_authorization` (Task 7)
- Produces: a hand-labelable disagreement report

- [ ] **Step 1: Write the tool**

Create `tools/sponsor_diff.py`:

```python
#!/usr/bin/env python3
"""Sponsorship gate: diff the quote-grounded screen against the old phrase list over
already-scored rows, so only the DISAGREEMENTS need hand-labeling.

Agreements are free labels; disagreements are the candidates for a three-class
hand-label (no-sponsorship / offers / silent). Reports recall and the precision risk
that quote-grounding does NOT close: misclassification, where the model quotes
real-but-irrelevant text.

Usage:
    PYTHONPATH=apps/worker python3 tools/sponsor_diff.py --db path/to.db [--limit N]

Read-only against the DB. Spends screen calls on whatever SCREEN_BACKEND is set
(free on the default ollama).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "worker"))

import requests  # noqa: E402

from ats_worker import db, run  # noqa: E402
from ats_worker.score.screen import NO_SPONSOR_PHRASES, _quote_in  # noqa: E402


def _phrase_hit(description: str) -> bool:
    text = " ".join((description or "").lower().split())
    return any(p in text for p in NO_SPONSOR_PHRASES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="apps/web/prisma/applications.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--backend", default=os.environ.get("SCREEN_BACKEND", "ollama"))
    ap.add_argument("--out", default="sponsor_diff.json")
    args = ap.parse_args()

    conn = db.connect(args.db)
    rows = [dict(r) for r in conn.execute(
        "SELECT id, job_title, company_name, description FROM job_postings "
        "WHERE pipeline_status IN ('scored','notified','discarded') "
        "AND LENGTH(TRIM(description)) > 200 ORDER BY id").fetchall()]
    if args.limit:
        rows = rows[:args.limit]

    extract = run.make_screener(args.backend, env=os.environ, http=requests)
    if extract is None:
        print("backend 'none' has no LLM check to diff", file=sys.stderr)
        return 2

    agree = disagree = 0
    out = []
    from ats_worker.score.prompts import SCREEN_SCHEMA, _candidate_block, _job_block
    from ats_worker.prompts import SCREEN_HEADER
    checklist = _candidate_block({"work_authorization": "needs visa sponsorship"})

    for row in rows:
        desc = row["description"] or ""
        try:
            data = extract(SCREEN_HEADER + checklist + "\n" + _job_block(row, 16384),
                           SCREEN_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            print(f"id={row['id']} screen failed: {exc}", file=sys.stderr)
            continue
        quote = ((data.get("screen") or {}).get("authorization") or {}).get(
            "no_sponsorship_quote")
        llm = _quote_in(quote, desc)
        phrase = _phrase_hit(desc)
        if llm == phrase:
            agree += 1
            continue
        disagree += 1
        out.append({"id": row["id"], "company": row["company_name"],
                    "title": row["job_title"], "llm_says_no_sponsorship": llm,
                    "phrase_list_says_no_sponsorship": phrase, "quote": quote,
                    "label": None})  # hand-fill: no-sponsorship | offers | silent

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"{len(rows)} rows: {agree} agree (free labels), {disagree} disagree")
    print(f"hand-label the {disagree} rows in {args.out} (label: "
          f"no-sponsorship | offers | silent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify it runs hermetically against a temp DB**

```bash
cd /home/halcyon/root/ats
PYTHONPATH=apps/worker python3 tools/sponsor_diff.py --db /tmp/nope.db --limit 1 ; echo "exit=$?"
```
Expected: a clean sqlite error or `0 rows` — NOT a traceback from the tool's own logic.

- [ ] **Step 3: Commit**

```bash
git add tools/sponsor_diff.py
git commit -m "tools: diff the quote-grounded sponsorship screen against the phrase list

Agreements over already-scored rows are free labels; only disagreements need a
hand-label into no-sponsorship / offers / silent. This is the cheap route to the
labeled set that gates the sponsorship rework, and it measures the one risk
quote-grounding does not close: misclassification."
```

- [ ] **Step 4: OPERATOR GATE — run it and report**

This is a human step, not a code step. Run the tool over the existing scored rows,
hand-label the disagreements, and record in `docs/PROGRESS.md`:
recall against the 11 realistic phrasings, and precision on the `silent` class.
**Do not proceed to Stage 4 claiming the sponsorship rework is validated until this
number exists.**

---

# STAGE 4 — Scorer fallback check

> **This is the risky stage.** It touches `score.txt`, which has destabilized verdicts
> before (SPEC §7.1). Task 10's gate is mandatory. If the gate fails, revert Task 9 —
> do not ship it anyway.

## Task 9: Add the fallback extraction to the fit scorer

**Files:**
- Modify: `apps/worker/ats_worker/prompts/score.txt`
- Modify: `apps/worker/ats_worker/score/prompts.py` (`_SCORE_SCHEMA`)
- Modify: `apps/worker/ats_worker/score/screen.py` (`_normalize_score`)
- Modify: `apps/worker/ats_worker/pipeline.py` (`_persist_scored`)
- Modify: `apps/worker/tests/test_score.py`, `apps/worker/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `_screen_verdict`, `_quote_in` (Task 7)
- Produces: `merge_fallback_screen(screen: dict, card: dict, posting: dict, candidate: dict | None) -> dict`

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_score.py`:

```python
# --- scorer fallback screen check ----------------------------------------

def test_fallback_screen_used_when_screen_produced_nothing():
    # SCREEN_BACKEND=none: the screen has no verdict, so the scorer's extraction is
    # the ONLY check. It must be consumed.
    empty = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"clearance": {"requires_clearance": True}}}
    out = score.merge_fallback_screen(empty, card, POSTING,
                                      {"security_clearance": "none"})
    assert out["disqualified"] is True


def test_fallback_screen_ignored_when_screen_already_ruled():
    # On a working backend the screen wins. A second independent checker would double
    # the false-positive surface, and a spurious "requires PhD" silently discards a
    # good posting — the exact failure err-toward-keep exists to avoid.
    ruled = {"screen": {"clearance": {"pass": True, "note": ""}},
             "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"clearance": {"requires_clearance": True}}}
    out = score.merge_fallback_screen(ruled, card, POSTING,
                                      {"security_clearance": "none"})
    assert out["disqualified"] is False


def test_fallback_sponsorship_quote_is_verified_too():
    empty = {"screen": {}, "disqualified": False, "disqualification_reason": ""}
    card = {"screen": {"authorization": {"no_sponsorship_quote": "We never sponsor."}}}
    posting = dict(POSTING, description="A perfectly normal JD.")
    out = score.merge_fallback_screen(empty, card, posting,
                                      {"work_authorization": "needs visa sponsorship"})
    assert out["disqualified"] is False   # hallucinated quote -> keep, same as the screen
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_score.py -k fallback -v`
Expected: FAIL — `AttributeError: module has no attribute 'merge_fallback_screen'`

- [ ] **Step 3: Add the schema fields and prompt block**

In `score/prompts.py`, add to `_SCORE_SCHEMA["properties"]` (and NOT to `required` —
the field is advisory, and requiring it would make every malformed response raise):

```python
        # Fallback hard-requirement extraction, consumed ONLY where the screen produced
        # nothing (SCREEN_BACKEND=none, or a swallowed screen failure). Not required:
        # a scorer that omits it must not fail the whole card.
        "screen": {
            "type": "object",
            "properties": {
                "degree": {
                    "type": "object",
                    "properties": {"required_degree": {"type": ["string", "null"]}},
                    "additionalProperties": False,
                },
                "authorization": {
                    "type": "object",
                    "properties": {"no_sponsorship_quote": {"type": ["string", "null"]}},
                    "additionalProperties": False,
                },
                "clearance": {
                    "type": "object",
                    "properties": {"requires_clearance": {"type": "boolean"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
```

Append to `apps/worker/ats_worker/prompts/score.txt` — an ADDITIVE block at the end.
**Do not touch the rubric or the seniority/domain verdict definitions:**

```
=== HARD REQUIREMENTS (secondary extraction) ===
Separately from the fit assessment above, and WITHOUT letting any of it change the score or the verdicts, report these facts about the JOB under "screen":
- degree: {"required_degree": "<the MINIMUM degree the role requires — one of: none, high school, associate, bachelor's, master's, phd — or null if unstated>"}
- authorization: {"no_sponsorship_quote": "<the EXACT sentence, copied verbatim from the JOB text, stating visa sponsorship is NOT available, or null if the posting does not say this. Copy it word for word — it is verified against the posting and a sentence that does not appear there is discarded. MOST postings never mention sponsorship — those are null>"}
- clearance: {"requires_clearance": <true if the role requires an active government security clearance, else false>}
These are extraction, not judgment: report what the posting says and let code decide.
```

- [ ] **Step 4: Implement `merge_fallback_screen`**

Append to `score/screen.py`:

```python
def merge_fallback_screen(screen: dict, card: dict, posting: dict,
                          candidate: dict | None) -> dict:
    """Consume the fit scorer's secondary hard-requirement extraction — but ONLY for
    checks the screen produced no verdict for.

    Why fallback and not a second vote: on a working screen backend a second independent
    checker doubles the false-positive surface, and a spurious "requires PhD" would
    SILENTLY DISCARD a good posting — the exact failure the err-toward-keep design
    exists to avoid. This is insurance for the gap (SCREEN_BACKEND=none, or a screen
    failure that err-toward-keep already swallowed), not redundancy.

    Sponsorship keeps the same quote verification as the screen, so a hallucinated
    quote cannot disqualify here either.
    """
    if not candidate or not isinstance(card, dict):
        return screen
    extracted = card.get("screen")
    if not isinstance(extracted, dict):
        return screen
    already = screen.get("screen") or {}
    gaps = {k: v for k, v in extracted.items() if k not in already}
    if not gaps:
        return screen
    verdict = _screen_verdict({"screen": gaps}, candidate,
                              str(posting.get("description") or ""))
    merged = dict(already)
    merged.update(verdict.get("screen") or {})
    prior = screen.get("disqualification_reason") or ""
    extra = verdict.get("disqualification_reason") or ""
    reason = "; ".join(r for r in (prior, extra) if r)
    return {
        "screen": merged,
        "disqualified": bool(screen.get("disqualified")) or bool(verdict.get("disqualified")),
        "disqualification_reason": reason,
    }
```

Re-export it from `score/__init__.py` (add `merge_fallback_screen` to the `.screen`
import block).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_score.py -k fallback -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Wire it into `_persist_scored`**

Find the call site: `grep -n "_persist_scored" apps/worker/ats_worker/pipeline.py`.
Inside it, before the screen verdict is merged onto the card, apply the fallback and
re-route a newly-disqualified row to `discarded`:

```python
    screen = score_mod.merge_fallback_screen(screen, card, posting, candidate)
```

`_persist_scored` needs `candidate` threaded through from `run_score`; add it as a
keyword argument on both, defaulting to `None`, and pass it from `run.py`'s
`pipeline.run_score(...)` call. Add a test in `test_pipeline.py` asserting a row the
scorer disqualifies lands `discarded` rather than `scored`.

- [ ] **Step 7: Run the full suite**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit (but DO NOT merge until Task 10 passes)**

```bash
git add -A && git commit -m "feat(worker): let the fit scorer double-check the screen where the screen was blind

The fit call already happens, so three extra extraction fields cost a handful of
output tokens and zero extra calls. Consumed ONLY where the screen produced no
verdict — SCREEN_BACKEND=none, or a screen failure err-toward-keep swallowed — so a
working backend's verdict still wins and the false-positive surface does not double.
Sponsorship keeps the same quote verification, so hallucination cannot disqualify
here either.

The prompt block is additive and the rubric is untouched, but this still edits
score.txt: NOT SHIPPABLE until two consecutive score_eval PASS."
```

---

## Task 10: OPERATOR GATE — `score_eval`, two consecutive PASS

**Files:** none (a measurement, not a change)

- [ ] **Step 1: Run the free hermetic self-test first**

Run: `cd apps/worker && PYTHONPATH=. python3 tools/score_eval.py --selftest`
Expected: PASS. **Note `tools/score_eval.py` has no argparse — any unrecognized flag
(including `--help`) starts a LIVE, quota-spending run.**

- [ ] **Step 2: Run the live gate twice**

Run: `make eval-score` (twice, consecutively).
Expected: two consecutive PASS — 0 hard-invariant violations, >=85% per-dimension
verdict agreement, <20% flip rate. ~69 Codex messages per run.

This run also discharges the gate owed for the 2026-07-22 `personal_profile.txt` edit
(PROGRESS P2 item 5) — record both results.

- [ ] **Step 3: Decide**

- **Two PASS** → record the numbers in `docs/PROGRESS.md` and `CHANGELOG.md`; Stage 4 ships.
- **Any FAIL** → `git revert` Task 9's commit. The scorer fallback is dropped, not
  shipped anyway. Stages 1-3 and 5 are unaffected and still ship.

---

# STAGE 5 — Concurrency

> Independent of Stages 1-4. Could land first if a quick win is wanted.

## Task 11: Concurrent screen and fit loops

**Files:**
- Modify: `apps/worker/ats_worker/pipeline.py:427-500` (`run_score`)
- Modify: `apps/worker/ats_worker/run.py` (flags + pass-through)
- Modify: `apps/worker/tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing from Stages 1-4
- Produces: `run_score(conn, *, now, screen_fn, fit_fn, batch_size=10, limit=0, screen_workers=1, score_workers=4, candidate=None)`

- [ ] **Step 1: Write the failing tests**

Add to `apps/worker/tests/test_pipeline.py`:

```python
def test_run_score_screens_concurrently(tmp_path):
    # The screen calls must overlap; the DB writes must not.
    import threading
    conn = _seeded_conn(tmp_path, rows=6)
    inflight, peak, lock = 0, [0], threading.Lock()

    def screen_fn(posting):
        nonlocal inflight
        with lock:
            inflight += 1
            peak[0] = max(peak[0], inflight)
        time.sleep(0.05)
        with lock:
            inflight -= 1
        return {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=4)
    assert peak[0] > 1, "screen calls did not overlap"


def test_run_score_preserves_write_order_and_row_association(tmp_path):
    # A pool must not mis-associate a screen verdict with the wrong posting.
    conn = _seeded_conn(tmp_path, rows=5)

    def screen_fn(posting):
        # Disqualify exactly one known row.
        dq = posting["job_title"] == "row-3"
        return {"screen": {}, "disqualified": dq,
                "disqualification_reason": "test" if dq else ""}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=4)
    discarded = [dict(r)["job_title"] for r in db.get_by_status(conn, "discarded")]
    assert discarded == ["row-3"]


def test_run_score_screen_failure_fails_only_its_own_row(tmp_path):
    conn = _seeded_conn(tmp_path, rows=3)

    def screen_fn(posting):
        if posting["job_title"] == "row-1":
            raise RuntimeError("provider blew up")
        return {"screen": {}, "disqualified": False, "disqualification_reason": ""}

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn,
                       fit_fn=lambda ps: [_card() for _ in ps], screen_workers=4)
    assert [dict(r)["job_title"] for r in db.get_by_status(conn, "failed")] == ["row-1"]
```

`_seeded_conn(tmp_path, rows=N)` and `_card()` are helpers to add near the top of
`test_pipeline.py` if equivalents don't already exist — check first with
`grep -n "def _seeded_conn\|def _card" apps/worker/tests/test_pipeline.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_pipeline.py -k concurrent -v`
Expected: FAIL — `TypeError: run_score() got an unexpected keyword argument 'screen_workers'`

- [ ] **Step 3: Make the screen loop concurrent**

In `pipeline.py`, replace the screen loop (`pipeline.py:455-479`). The pattern mirrors
`run_feed`: submit everything, then consume results **in the original order** so DB
writes stay serial, deterministic, and on this thread.

```python
    survivors: list[tuple] = []  # (row, posting, screen)
    rows = db.get_by_status(conn, "new")
    if limit > 0:
        rows = rows[:limit]
    postings = [dict(row) for row in rows]

    # Screen calls are I/O-bound (an HTTP round trip, or a subprocess spawn on the CLI
    # backends), so they run CONCURRENTLY while every DB call stays on this thread —
    # the same read-serial / network-parallel / write-serial shape run_feed uses,
    # because SQLite connections are not safe across threads. Consuming futures in
    # submission order keeps writes deterministic and correctly row-associated.
    with ThreadPoolExecutor(max_workers=max(1, screen_workers)) as ex:
        futures = [ex.submit(screen_fn, posting) for posting in postings]
        for row, posting, future in zip(rows, postings, futures):
            try:
                screen = future.result()
            except Exception as exc:  # noqa: BLE001 — one bad screen never aborts the pass
                db.mark_failed(conn, row["id"], error=str(exc), now=now)
                continue
            if screen.get("disqualified"):
                db.save_score(
                    conn, row["id"], score=0,
                    score_detail=_score_detail(screen, disqualified=True),
                    now=now, status="discarded",
                )
            elif len((posting.get("description") or "").strip()) < \
                    db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH:
                _persist_low_context(conn, row, screen, now=now)
            else:
                survivors.append((row, posting, screen))
```

Note the screen loop does **not** call `merge_fallback_screen` — that consumes the fit
scorer's card, which does not exist until after the fit call, so it lives in
`_persist_scored` (Task 9) and nowhere else. Stage 5 touches neither.

- [ ] **Step 4: Make the fit loop concurrent**

Replace the chunk loop (`pipeline.py:481-484`):

```python
    # Fit calls are also I/O-bound. Concurrency is QUOTA-NEUTRAL: N parallel codex
    # execs spend exactly the same number of messages as N serial ones — it only
    # changes wall-clock. (The 2026-07-15 "parallelism can't help" note assumed a
    # rolling 5-hour message window; that was corrected to WEEKLY two days later, and
    # pacing is served by --score-limit. See CHANGELOG 412-414 and SPEC §11.)
    chunks = list(_chunks(survivors, batch_size))
    with ThreadPoolExecutor(max_workers=max(1, score_workers)) as ex:
        futures = [ex.submit(fit_fn, [p for (_row, p, _screen) in chunk])
                   for chunk in chunks]
        for chunk, future in zip(chunks, futures):
            postings_in_chunk = [p for (_row, p, _screen) in chunk]
            try:
                cards = future.result()
            except Exception:  # noqa: BLE001 — see the singles-fallback rationale below
                cards = None
            # ... existing length-mismatch check and singles fallback, unchanged ...
```

The existing singles-fallback logic (`pipeline.py:485-500`) is preserved verbatim — one
bad posting must never abort the batch.

Add the import at the top of `pipeline.py` (it already imports `ThreadPoolExecutor` at
line 34 for `run_feed` — verify, don't duplicate).

Update the `run_score` signature:

```python
def run_score(conn, *, now, screen_fn, fit_fn, batch_size: int = 10,
              limit: int = 0, screen_workers: int = 1, score_workers: int = 4,
              candidate=None) -> None:
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest tests/test_pipeline.py -q`
Expected: all pass.

- [ ] **Step 6: Add the CLI flags with per-backend screen defaults**

In `run.py`:

```python
# Per-backend screen concurrency. Ollama defaults to 1: a single GPU SERIALIZES the
# compute, so parallel requests interleave rather than speed up (weights load once and
# are not duplicated per slot — only KV cache is, so RAM is the secondary constraint,
# not the binding one). The subprocess and HTTP backends are latency-bound and benefit.
# Configurable so a multi-GPU or remote-Ollama user can raise it.
DEFAULT_SCREEN_WORKERS = {"ollama": 1, "none": 1, "codex": 4, "claude-code": 4,
                          "claude-api": 4, "openai-api": 4}
```

```python
    parser.add_argument("--screen-workers", type=int,
                        default=int(os.environ.get("SCREEN_WORKERS", "0")),
                        help="concurrent screen calls (0 = per-backend default: 1 for "
                             "ollama, 4 for the hosted backends)")
    parser.add_argument("--score-workers", type=int,
                        default=int(os.environ.get("SCORE_WORKERS", "4")),
                        help="concurrent fit-scorer calls. Quota-neutral: parallel "
                             "calls spend the same messages, only less wall-clock")
```

Resolve the screen default in `run_once`:

```python
        workers = screen_workers or DEFAULT_SCREEN_WORKERS.get(screen_backend, 1)
```

and pass `screen_workers=workers, score_workers=score_workers` to `pipeline.run_score`.

- [ ] **Step 7: Run the full suite, then update the docs**

Run: `cd apps/worker && PYTHONPATH=. python3 -m pytest -q`

Update `docs/SPEC.md` §9 (the pipeline stage description) to say `run_score` screens and
fit-scores concurrently with the read-serial / network-parallel / write-serial pattern,
and `docs/SPEC.md` §11 to record that concurrency is quota-neutral so the weekly-window
bound argues for pacing (`--score-limit`), not against threads. Add a `CHANGELOG.md`
entry under `### Changed`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "perf(worker): run the screen and fit loops concurrently

Both loops in run_score were serial. They now use the same read-serial /
network-parallel / write-serial shape run_feed already proves, with every DB call on
the calling thread because SQLite connections are not thread-safe. Futures are
consumed in submission order, so writes stay deterministic and correctly
row-associated, and a failing call still fails only its own row.

Ollama defaults to 1 worker: a single GPU serializes the compute, so parallel
requests interleave rather than speed up. The hosted and subprocess backends default
to 4.

Fit concurrency is quota-neutral — N parallel codex execs spend the same messages as
N serial ones. The 2026-07-15 'parallelism can't help' objection assumed a rolling
5-hour window, corrected to weekly two days later."
```

---

## Final verification

- [ ] `cd apps/worker && PYTHONPATH=. python3 -m pytest -q` — all pass
- [ ] `PYTHONPATH=. python3 -m pytest --cov=ats_worker --cov-report=term-missing` — `fail_under=85` met
- [ ] `make doctor` — exit 0, `openai api key` row present
- [ ] `make check-privacy` — no private files tracked
- [ ] `make test-web` — unaffected, still green
- [ ] `docs/SPEC.md`, `docs/PROGRESS.md`, `CHANGELOG.md`, `docs/SETUP.md`, `.env.example` all updated
- [ ] Sponsorship recall reported from Task 8's labeled set
- [ ] Two consecutive `score_eval` PASS recorded (or Task 9 reverted)
