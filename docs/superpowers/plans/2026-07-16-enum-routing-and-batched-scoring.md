# Enum-Verdict Routing + Batched Fit Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route Telegram notify + the web "matched" bucket on the stable
`seniority==match AND domain==match` verdicts instead of the flip-prone score
threshold, and batch codex fit calls (~10 JDs/call) to fit the message-bound 5-hour
quota — both validated by a repurposed verdict-accuracy eval harness.

**Architecture:** Three phases matching the spec's rollout. **Phase A** swaps the
score-threshold gate for a verdict predicate in the worker (`db.get_notifiable`) and
the web UI (`matchedIds` raw query), retiring `MATCH_SCORE_THRESHOLD` from gating.
**Phase C** reframes `score_eval.py` from score-bands to verdict accuracy and relabels
the golden set with ground-truth verdicts. **Phase B** splits the per-posting screen
from the fit call and restructures `run_score` to screen-all-then-batch-fit-survivors,
with a fall-back-to-single safety net. Phases are ordered A → C → B (C gates B).

**Tech Stack:** Python 3.11 (worker, pytest), Next.js 14 + Prisma/SQLite (web, Jest),
the Codex CLI (`codex exec`, subprocess), Ollama (local screen).

## Global Constraints

- **Notify/matched predicate (verbatim):** `seniority.verdict == "match" AND domain.verdict == "match" AND NOT insufficient_context`.
- **Scorer default (unchanged this plan):** codex backend, model `gpt-5.6-sol`, `model_reasoning_effort=low`, `model_verbosity=low`, tool-less (`--disable shell_tool`, `web_search="disabled"`).
- **Fit-scorer contract becomes batch-first:** `fit(postings: list[dict], resumes: dict) -> list[dict]` (one scorecard per input, same order). Single scoring is `fit([posting], resumes)[0]`. The `claude` backend implements this by looping single calls; only `codex` sends a true batch.
- **Batching is codex-only.** `claude` stays effectively single. Default `batch_size=10`, overridable via `--batch-size` / `CODEX_BATCH_SIZE`.
- **A batch failure never fails N postings:** on `ScoreError` for a batch, fall back to scoring that batch's postings singly.
- **Prisma's typed `where` cannot read `score_detail` JSON** — use a raw `$queryRaw` json_extract helper and layer ids (`in`/`notIn`), mirroring the existing `lowContextIds`.
- **Worker tests are hermetic:** no network, subprocess/Ollama mocked. Run worker tests from `apps/worker/` with `python3 -m pytest` (system python3, per the Makefile). Web tests: `cd apps/web && npm test`.
- **Every behavior change updates SPEC.md + PROGRESS.md + CHANGELOG.md in the same commit.**
- **Commit identity:** `drink970082 <howdywu@gmail.com>`.

---

## Phase A — `match/match` routing

### Task A1: `db.get_notifiable` — select scored rows whose verdicts are match/match

**Files:**
- Modify: `apps/worker/ats_worker/db.py` (add function after `get_by_status`, ~line 151)
- Test: `apps/worker/tests/test_db.py`

**Interfaces:**
- Produces: `get_notifiable(conn) -> list[sqlite3.Row]` — `pipeline_status='scored'` rows where `json_extract(score_detail,'$.assessment.seniority.verdict')='match'` AND the domain extract `='match'` AND `COALESCE(json_extract(score_detail,'$.insufficient_context'),0)` is not 1, ordered `score DESC, id ASC`.

- [ ] **Step 1: Write the failing test**

```python
# apps/worker/tests/test_db.py  (add; import db, use the existing conn/bootstrap fixtures)
def test_get_notifiable_selects_only_match_match_non_thin(tmp_path):
    conn = _bootstrap(tmp_path)  # existing helper that creates an empty schema'd db
    def add(pid, sen, dom, thin=False, status="scored", score=50):
        detail = {"assessment": {"seniority": {"verdict": sen},
                                 "domain": {"verdict": dom}}}
        if thin:
            detail["insufficient_context"] = True
        db.upsert_postings(conn, [_posting(pid)], now=NOW)
        db.save_score(conn, pid, score=score, score_detail=detail, now=NOW, status=status)
    add(1, "match", "match")                       # notifiable
    add(2, "match", "adjacent")                    # domain not match -> no
    add(3, "too_junior", "match")                  # seniority not match -> no
    add(4, "match", "match", thin=True)            # thin JD -> no
    add(5, "match", "match", status="notified")    # already notified -> no (only 'scored')
    got = [r["id"] for r in db.get_notifiable(conn)]
    assert got == [1]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `apps/worker/`): `python3 -m pytest tests/test_db.py::test_get_notifiable_selects_only_match_match_non_thin -v`
Expected: FAIL — `AttributeError: module 'ats_worker.db' has no attribute 'get_notifiable'`

- [ ] **Step 3: Write minimal implementation**

```python
# apps/worker/ats_worker/db.py  (after get_by_status)
def get_notifiable(conn: sqlite3.Connection):
    """Scored rows the fit verdicts mark a strong match — the notify gate.
    Replaces the old score>=threshold gate: seniority AND domain must both be
    `match`, and a thin-JD (insufficient_context) row is held back for human
    review. json_extract reads the verdicts out of the score_detail JSON."""
    return conn.execute(
        "SELECT * FROM job_postings WHERE pipeline_status='scored' "
        "AND json_extract(score_detail,'$.assessment.seniority.verdict')='match' "
        "AND json_extract(score_detail,'$.assessment.domain.verdict')='match' "
        "AND COALESCE(json_extract(score_detail,'$.insufficient_context'),0)<>1 "
        "ORDER BY score DESC, id ASC"
    ).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_db.py::test_get_notifiable_selects_only_match_match_non_thin -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/db.py apps/worker/tests/test_db.py
git commit -m "feat(worker): db.get_notifiable — verdict-based notify selection"
```

### Task A2: `run_notify` gates on `get_notifiable` (drop the threshold param)

**Files:**
- Modify: `apps/worker/ats_worker/pipeline.py:271` (`run_notify`)
- Modify: `apps/worker/ats_worker/run.py:185-192` (call site — drop `cfg.threshold` arg)
- Test: `apps/worker/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `db.get_notifiable(conn)` (A1).
- Produces: `run_notify(conn, *, now, notify_fn, token, chat_id)` — no `threshold` param.

- [ ] **Step 1: Write the failing test** (adapt the existing run_notify test to the new signature + selection)

```python
# apps/worker/tests/test_pipeline.py
def test_run_notify_pings_only_verdict_matches(tmp_path):
    conn = _bootstrap(tmp_path)
    def add(pid, sen, dom):
        db.upsert_postings(conn, [_posting(pid)], now=NOW)
        db.save_score(conn, pid, score=50, now=NOW, status="scored",
                      score_detail={"assessment": {"seniority": {"verdict": sen},
                                                    "domain": {"verdict": dom}}})
    add(1, "match", "match")       # ping
    add(2, "match", "adjacent")    # no ping (below the verdict bar)
    sent = []
    pipeline.run_notify(conn, now=NOW, notify_fn=lambda p, **k: sent.append(p["id"]),
                        token="t", chat_id="c")
    assert sent == [1]
    assert db.get_by_status(conn, "notified")[0]["id"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pipeline.py::test_run_notify_pings_only_verdict_matches -v`
Expected: FAIL — `TypeError: run_notify() got an unexpected keyword argument` / positional `threshold` mismatch.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/worker/ats_worker/pipeline.py  — change signature + selection line
def run_notify(conn, *, now, notify_fn, token, chat_id) -> None:
    """Notify every scored posting whose fit verdicts mark it a strong match
    (db.get_notifiable) and advance it to 'notified'. The verdict predicate is
    the gate now — the old score>=threshold gate is gone (the score quantized to
    the rubric band edge and flipped run-to-run; the verdicts are stable)."""
    for row in db.get_notifiable(conn):
        # ... body unchanged (notify_fn -> mark_notified / record_notify_failure) ...
```

```python
# apps/worker/ats_worker/run.py  — drop cfg.threshold
        pipeline.run_notify(
            conn,
            now=now,
            notify_fn=notify_posting,
            token=env["TELEGRAM_BOT_TOKEN"],
            chat_id=env["TELEGRAM_CHAT_ID"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pipeline.py -v` (whole file — the old threshold-based notify tests must be updated/removed here too)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/pipeline.py apps/worker/ats_worker/run.py apps/worker/tests/test_pipeline.py
git commit -m "feat(worker): notify gates on match/match verdicts, not score threshold"
```

### Task A3: web `matchedIds` + matched/belowbar buckets on verdicts

**Files:**
- Modify: `apps/web/src/lib/actions.ts` (add `matchedIds()`; change `matched`/`belowbar` bucket filters; layer `matchedIds` in the async `where` builder alongside `lowIds`)
- Modify: `apps/web/src/lib/constants.ts:51` (remove `MATCH_SCORE_THRESHOLD` or demote to a display-only comment if a chart still references it — grep first)
- Test: `apps/web/src/lib/__tests__/actions.test.ts` (or the existing actions test file)

**Interfaces:**
- Produces: `matchedIds(): Promise<number[]>` — ids of `scored|notified` rows whose `score_detail` verdicts are match/match AND not thin. `matched` bucket = `id IN matchedIds`; `belowbar` = active scored `id NOT IN matchedIds` (and existing `notIn lowIds`).

- [ ] **Step 1: Write the failing test** (seed a throwaway SQLite db; mirror existing actions tests)

```typescript
// a match/adjacent row scoring 90 is NOT matched; a match/match row scoring 60 IS.
it('matched bucket keys on verdicts, not score', async () => {
  await seedScored({ id: 1, score: 90, seniority: 'match', domain: 'adjacent' })
  await seedScored({ id: 2, score: 60, seniority: 'match', domain: 'match' })
  const matched = await getDiscoveredJobs({ bucket: 'matched' })
  expect(matched.rows.map(r => r.id)).toEqual([2])
  const below = await getDiscoveredJobs({ bucket: 'belowbar' })
  expect(below.rows.map(r => r.id)).toContain(1)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npm test -- actions`
Expected: FAIL — matched returns id 1 (score 90 ≥ 75) under the old threshold logic.

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/lib/actions.ts — new helper (mirror lowContextIds)
async function matchedIds(): Promise<number[]> {
    const rows = await prisma.$queryRaw<Array<{ id: number | bigint }>>`
        SELECT id FROM job_postings
        WHERE pipeline_status IN ('scored', 'notified')
          AND json_extract(score_detail, '$.assessment.seniority.verdict') = 'match'
          AND json_extract(score_detail, '$.assessment.domain.verdict') = 'match'
          AND COALESCE(json_extract(score_detail, '$.insufficient_context'), 0) <> 1
    `
    return rows.map((r) => Number(r.id))
}
```

Then in the async `where` builder (where `lowIds` is fetched, ~line 190): fetch
`const matchIds = await matchedIds()` and change the `matched`/`belowbar` branches of
`buildJobWhere` to consume passed-in ids — matched → `{ id: { in: matchIds } }`,
belowbar → active-scored + `{ id: { notIn: matchIds } }`. Remove the
`score: { gte/lt: MATCH_SCORE_THRESHOLD }` clauses. (Guard empty sets like the lowIds
`notIn` guard.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npm test -- actions`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/actions.ts apps/web/src/lib/constants.ts apps/web/src/lib/__tests__/actions.test.ts
git commit -m "feat(web): matched/belowbar buckets key on match/match verdicts"
```

### Task A4: Phase-A docs

**Files:** Modify `docs/SPEC.md` (the fit-score / routing sections + defaults line), `docs/PROGRESS.md` (close the flip-rate item's routing half), `CHANGELOG.md`.

- [ ] **Step 1:** SPEC — state the notify + matched-bucket gate is the match/match verdict predicate; note score is display/ranking only and `threshold`/`MATCH_SCORE_THRESHOLD` no longer gate.
- [ ] **Step 2:** PROGRESS — update the in-flight codex item: routing landed; flip-rate is moot for gating (verdicts are stable); batching + harness still open.
- [ ] **Step 3:** CHANGELOG — Added/Changed entry for verdict routing.
- [ ] **Step 4: Commit**

```bash
git add docs/SPEC.md docs/PROGRESS.md CHANGELOG.md
git commit -m "docs: verdict-based notify/matched routing"
```

---

## Phase C — verdict-accuracy eval harness

### Task C1: relabel the golden set with ground-truth verdicts

**Files:** Modify `apps/worker/eval/golden.jsonl` (add `seniority` + `domain` to each row).

**Interfaces:** Produces golden rows carrying `seniority` ∈ {match,too_junior,too_senior} and `domain` ∈ {match,adjacent,mismatch}, plus a derived comment. `band` stays for reference.

- [ ] **Step 1: Capture current verdicts** — run the scorer over the 23 golden ids once, printing each row's `assessment.seniority.verdict` / `domain.verdict`:

```bash
cd /home/halcyon/root/ats && apps/worker/.venv/bin/python - <<'PY'
import json, sqlite3, sys; from pathlib import Path
R=Path("/home/halcyon/root/ats"); sys.path.insert(0,str(R/"apps/worker"))
from ats_worker import run, score
res,prof=run.load_resumes(str(R/"apps/worker/resume"))
fit=score.make_codex_scorer(run.DEFAULT_CODEX_SCORE_MODEL,profile=prof)
C=("job_title","company_name","description","location")
c=sqlite3.connect(f"file:{R}/db/applications.db?mode=ro",uri=True)
for l in open(R/"apps/worker/eval/golden.jsonl"):
    row=json.loads(l); g=c.execute(f"SELECT {','.join(C)} FROM job_postings WHERE id=?",(row["id"],)).fetchone()
    a=fit([dict(zip(C,g))],res)[0]["assessment"]
    print(row["id"], a["seniority"]["verdict"], a["domain"]["verdict"], "| band:",row["band"])
PY
```

- [ ] **Step 2: Human-confirm each verdict** against the existing `note` (target-domain keeps → `domain: match`; the min-2 skips → `seniority: too_junior`; adjacent-domain rows → `domain: adjacent`). Where the model's verdict disagrees with the note's intent, the **note wins** — this is ground truth, not a model echo.
- [ ] **Step 3: Write the labels** into `golden.jsonl` (`"seniority": "...", "domain": "..."` per row).
- [ ] **Step 4: Commit**

```bash
git add apps/worker/eval/golden.jsonl
git commit -m "test(worker): golden set carries ground-truth seniority/domain verdicts"
```

### Task C2: `score_eval.py` gates on verdict accuracy

**Files:** Modify `apps/worker/tools/score_eval.py`; add a selftest assertion.

**Interfaces:** Produces a report whose PASS gate is: **0 hard-invariant violations** (no hard row comes back `match/match` when ground truth isn't) AND **verdict agreement ≥ 85%** (majority verdict == ground truth, per dimension, over gate rows) AND **verdict flip-rate < 20%** (K draws disagree). The derived match/match notify decision is reported per row but is not itself the gate.

- [ ] **Step 1: Write the failing selftest** (band boundaries → verdict logic)

```python
# tools/score_eval.py --selftest additions
assert notify_decision({"seniority":{"verdict":"match"},"domain":{"verdict":"match"}}) is True
assert notify_decision({"seniority":{"verdict":"match"},"domain":{"verdict":"adjacent"}}) is False
assert notify_decision({"seniority":{"verdict":"too_junior"},"domain":{"verdict":"match"}}) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `apps/worker/.venv/bin/python apps/worker/tools/score_eval.py --selftest`
Expected: FAIL — `notify_decision` undefined.

- [ ] **Step 3: Implement** — replace the score→`band()` bucketing with verdict capture:
  - `notify_decision(assessment) -> bool` = `assessment["seniority"]["verdict"]=="match" and assessment["domain"]["verdict"]=="match"`.
  - `score_row` draws K×, capturing `(seniority, domain)` per draw; majority per dimension; `agree` = majority matches the golden `seniority`/`domain`; `flip` = draws disagree on either dimension; `hard_viol` = a `hard` row whose majority is match/match but golden isn't (or vice-versa).
  - `render`/verdict line reports agreement %, verdict flip-rate, and the derived notify decision per row. PASS per the Interfaces gate above.

- [ ] **Step 4: Run selftest + a live gate**

Run: `apps/worker/.venv/bin/python apps/worker/tools/score_eval.py --selftest` → PASS
Then `make eval-score` → inspect: flip-rate should be ≈ 0 (stable verdicts), agreement ≥ 85%.

- [ ] **Step 5: Commit**

```bash
git add apps/worker/tools/score_eval.py Makefile
git commit -m "test(worker): eval-score gates on verdict accuracy, not score bands"
```

### Task C3: Phase-C docs

- [ ] SPEC (eval-harness section: verdict-accuracy gate), PROGRESS (harness reframed), CHANGELOG. Commit `docs: verdict-accuracy eval harness`.

---

## Phase B — batched codex fit scoring

### Task B1: fit scorer becomes batch-first (`fit(postings, resumes) -> list`)

**Files:**
- Modify: `apps/worker/ats_worker/score.py` (`make_codex_scorer`, `make_claude_scorer`)
- Test: `apps/worker/tests/test_score.py`

**Interfaces:**
- Produces: both factories return `fit(postings: list[dict], resumes) -> list[dict]`, one scorecard per posting in order. `codex` builds ONE `codex exec` with N `job_ref`-tagged JD blocks and a `{"results":[{job_ref,...}]}` schema; missing/extra `job_ref` → `ScoreError`. `claude` loops single calls.
- Consumes: `_scorer_system_sections`, `_score_schema`, `_job_block` (unchanged).

- [ ] **Step 1: Write the failing tests**

```python
def test_codex_batch_returns_one_scorecard_per_posting_in_order(monkeypatch):
    def run(cmd, **kw):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w") as fh:
            json.dump({"results": [
                {"job_ref": 2, "score": 40, "assessment": {}, "insufficient_context": False},
                {"job_ref": 1, "score": 80, "assessment": {}, "insufficient_context": False}]}, fh)
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    fit = score.make_codex_scorer("gpt-5.6-sol")
    got = fit([{**POSTING, "id": 1}, {**POSTING, "id": 2}], {"swe": "r"})
    assert [g["score"] for g in got] == [80, 40]          # realigned by job_ref, input order

def test_codex_batch_missing_job_ref_raises(monkeypatch):
    def run(cmd, **kw):
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w") as fh:
            json.dump({"results": [{"job_ref": 1, "score": 80, "assessment": {}, "insufficient_context": False}]}, fh)
        return Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(score.subprocess, "run", run)
    with pytest.raises(score.ScoreError, match="job_ref"):
        score.make_codex_scorer("gpt-5.6-sol")([{**POSTING, "id": 1}, {**POSTING, "id": 2}], {"swe": "r"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_score.py -k codex_batch -v`
Expected: FAIL — current `fit` takes a single posting.

- [ ] **Step 3: Implement** — `make_codex_scorer.fit(postings, resumes)`:
  - Prompt = system sections once + one `=== JOB job_ref=<id> ===` block per posting (reuse `_job_block`, `include_location=False`).
  - Schema = `{"type":"object","properties":{"results":{"type":"array","items":<_score_schema + required job_ref:int>}},"required":["results"],"additionalProperties":False}`.
  - After parse: index results by `job_ref`; for every input id, pull its result or raise `ScoreError(f"codex omitted job_ref {id}")`; return in input order.
  - `make_claude_scorer.fit(postings, resumes)` = `[<existing single call>(p) for p in postings]`.

- [ ] **Step 4: Update the existing single-call tests** to the list contract (`fit([p], r)[0]`), run `python3 -m pytest tests/test_score.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/score.py apps/worker/tests/test_score.py
git commit -m "feat(worker): fit scorer is batch-first (list in, list out); codex batches by job_ref"
```

### Task B2: split screen from fit — `screen_posting`

**Files:**
- Modify: `apps/worker/ats_worker/score.py` (extract `screen_posting`; `score_posting` composes it + a 1-batch fit)
- Test: `apps/worker/tests/test_score.py`

**Interfaces:**
- Produces: `screen_posting(posting, *, http, ollama_host, model, candidate, num_ctx, timeout) -> dict` returning `{"disqualified": bool, "disqualification_reason": str, "screen": {...}}` (the screen half of today's `score_posting`). `score_posting` keeps its signature and behavior by calling `screen_posting` then, if not disqualified, `score_fit([posting], resumes)[0]` and merging — so all existing `score_posting` tests stay green.

- [ ] **Step 1: Write the failing test**

```python
def test_screen_posting_disqualifies_without_calling_fit():
    http = FakeHttp(json.dumps({"screen": {"clearance": {"requires_clearance": True}}}))
    out = score.screen_posting(POSTING, http=http, ollama_host="h", model="m",
                               candidate={"security_clearance": "none"}, num_ctx=8192)
    assert out["disqualified"] is True
    assert "screen" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_score.py::test_screen_posting_disqualifies_without_calling_fit -v`
Expected: FAIL — `screen_posting` undefined.

- [ ] **Step 3: Implement** — move the SCREEN block (steps 1–2 of current `score_posting`, ~lines 294–...) into `screen_posting`; rewrite `score_posting` to `s = screen_posting(...); if s["disqualified"]: return {score:0, **s}; fit = score_fit([posting], resumes)[0]; return {**normalize(fit), **s}`.

- [ ] **Step 4:** `python3 -m pytest tests/test_score.py -v` → PASS (existing score_posting tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/score.py apps/worker/tests/test_score.py
git commit -m "refactor(worker): extract screen_posting from score_posting (enables batch fit)"
```

### Task B3: `run_score` screens-all then batch-fits survivors (single-fallback)

**Files:**
- Modify: `apps/worker/ats_worker/pipeline.py` (`run_score`)
- Modify: `apps/worker/ats_worker/run.py` (build a `screen_fn` + a batched `fit_fn`; thread `batch_size`)
- Test: `apps/worker/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `screen_posting` (B2), the batch-first `fit` (B1).
- Produces: `run_score(conn, *, now, screen_fn, fit_fn, batch_size=10)` — screens each `new` row (persisting disqualifications), chunks survivors, calls `fit_fn(chunk_postings)`; on `ScoreError` for a chunk, retries that chunk's postings one-per-`fit_fn` call; persists each merged result. `run.py` wires `screen_fn`/`fit_fn` from the selected backend and passes `batch_size` from `--batch-size`/`CODEX_BATCH_SIZE`.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_score_batches_survivors_and_falls_back_on_batch_error(tmp_path):
    conn = _bootstrap(tmp_path)
    for pid in (1, 2, 3):
        db.upsert_postings(conn, [_posting(pid)], now=NOW)  # all 'new'
    calls = {"batch": [], "single": 0}
    def fit_fn(postings):
        ids = [p["id"] for p in postings]
        calls["batch"].append(ids)
        if len(ids) > 1:
            raise score.ScoreError("batch parse failed")      # force fallback
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()} for _ in postings]
    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=fit_fn)
    assert calls["batch"][0] == [1, 2, 3]     # tried as one batch
    assert calls["single"] == 3               # fell back to singles
    assert len(db.get_by_status(conn, "scored")) == 3

def test_run_score_persists_disqualified_without_fit(tmp_path):
    conn = _bootstrap(tmp_path)
    db.upsert_postings(conn, [_posting(1)], now=NOW)
    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": True, "disqualification_reason": "x"},
                       fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("fit must not run")))
    assert db.get_by_status(conn, "discarded")[0]["id"] == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py -k run_score -v`
Expected: FAIL — `run_score` has the old `score_fn` signature.

- [ ] **Step 3: Implement** `run_score` per the Interfaces block: screen loop → persist disqualified (`db.save_score(status="discarded")`) → collect survivors → `for chunk in _chunks(survivors, batch_size): try: results = fit_fn([p for _,p in chunk]) except ScoreError: results = [fit_fn([p])[0] for _,p in chunk]` (a single that still fails → `db.mark_failed` for just that row) → merge screen+fit detail and `save_score(status="scored")`. Add `_chunks(seq, n)` helper. Update `run.py` to build `screen_fn`/`fit_fn` and read `--batch-size`.

- [ ] **Step 4:** `python3 -m pytest tests/test_pipeline.py tests/test_run.py -v` → PASS (update the old `run_score`/`score_fn` tests to the new wiring).

- [ ] **Step 5: Commit**

```bash
git add apps/worker/ats_worker/pipeline.py apps/worker/ats_worker/run.py apps/worker/tests/test_pipeline.py apps/worker/tests/test_run.py
git commit -m "feat(worker): run_score screens-all then batch-fits survivors, single-fallback"
```

### Task B4: harness batched==single guard + acceptance run

**Files:** Modify `apps/worker/tools/score_eval.py` (add a `--batched` mode / assertion that batched verdicts equal single verdicts per golden row).

- [ ] **Step 1:** Add a harness path that scores the golden set once single and once at `batch_size=10` and asserts per-row `(seniority, domain)` are identical; report any drift.
- [ ] **Step 2: Run the acceptance gate:**

```bash
make eval-score            # verdict-accuracy gate: hard 0 viol, agreement >=85%, flip <20%
# plus the batched==single assertion — must show 0 drift
```
Expected: PASS twice consecutively before batching is trusted for the queue (per the shipping rule). If batched verdicts drift, **do not ship batching** — Phase A routing still stands.

- [ ] **Step 3: Commit**

```bash
git add apps/worker/tools/score_eval.py
git commit -m "test(worker): harness asserts batched verdicts == single verdicts"
```

### Task B5: Phase-B docs

- [ ] SPEC (batched scoring: interface, job_ref, fallback, batch_size; the quota math updated — 640 rows → ~64 messages), PROGRESS (batching landed / or parked if drift), CHANGELOG. Commit `docs: batched codex fit scoring`.

---

## Self-Review

**Spec coverage:** Part A (match/match routing) → A1–A4 ✓. Part B (batched scorer) →
B1–B5 ✓. Part C (verdict-accuracy harness + golden relabel) → C1–C3 ✓. `insufficient_context`
excluded from notify → A1/A3 predicate ✓. Threshold retirement → A3 (web) + A2 (worker call
site drops `cfg.threshold`); `config.yaml threshold:` left inert per spec non-goal ✓. Accepted
recall loss not penalized → C2 gates on verdict accuracy, not notify intent ✓. Batching
codex-only, claude loops → Global Constraints + B1 ✓. Batch-failure single-fallback → B3 ✓.
Batched==single validation → B4 ✓.

**Placeholder scan:** No TBD/TODO; each code step carries real code. The two web steps
that describe an edit in prose (A3 Step 3 tail, the `where`-builder layering) reference the
exact existing `lowIds`/`notIn` pattern in `actions.ts` rather than inventing an interface.

**Type consistency:** `get_notifiable(conn)->rows` (A1) consumed by `run_notify` (A2).
`matchedIds():Promise<number[]>` (A3) mirrors `lowContextIds`. `fit(postings,resumes)->list`
(B1) consumed by `screen_posting`-composed `score_posting` (B2) and `run_score`'s `fit_fn`
(B3). `notify_decision(assessment)->bool` (C2) matches the A1/A3 predicate. `screen_fn`/`fit_fn`
names consistent across B2/B3/run.py.
