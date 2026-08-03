#!/usr/bin/env python
"""Verdict-accuracy eval for the fit-score prompt — READ-ONLY, never writes the DB.

Reuses the exact production wiring (load_resumes -> the run.py default score backend ->
score_fit -> _normalize_score), scores each labeled golden-set row K=3x, and judges the
MAJORITY per-dimension verdict (seniority: match/too_junior/too_senior; domain:
match/adjacent/mismatch) against the frozen human labels. Production now routes notify
on these verdicts (match/match), not the score band, so the gate follows: verdict
agreement, not score->band agreement. The gate only means something when eval-model ==
production-model, so the backend follows run.DEFAULT_SCORE_BACKEND; SCORE_BACKEND=claude
A/Bs the old metered path. PASS over the gate-eligible (non-`marked`) rows: 0 hard-
invariant violations AND >=85% verdict agreement AND <20% verdict flip-rate; shipping
needs two consecutive PASS runs. `marked` rows are scored but routed to a watch list,
excluded from the gate.

The derived notify decision (seniority==match AND domain==match, the same predicate
db.get_notifiable routes on) is reported per row for visibility, but is NOT itself the
gate — that's what lets the accepted recall loss (e.g. adjacent-domain keeps) pass
without failing the prompt.

`--batched` is a SEPARATE guard (B4, not the K=3 gate above): scores the whole golden
set once SINGLE (`fit([posting], resumes)`) and once BATCHED (`fit(chunk, resumes)` at
BATCH_SIZE), one draw per row per pass, and asserts the per-row (seniority, domain)
verdicts are IDENTICAL. This is what proves the codex batching win (N JDs sharing one
call) doesn't corrupt a JD's score via context bleed from its batch-mates; PASS = 0
drift. It is a LIVE, quota-spending run — call it deliberately, never from CI/selftest.
If verdicts drift, batching must not be trusted for the queue; Phase A routing stands
regardless (see the design doc). It FAILED 2026-07-16 (19/23, all 4 on `domain`), which
parked batching at batch_size=1 and raised the question `--drift-probe` answers.

`--drift-probe` is a one-shot EXPERIMENT (not a gate — it has no pass/fail): the
--batched guard draws each row once single + once batched, so it cannot tell context
BLEED from a JD whose verdict is a coin-flip on any re-draw. The probe re-draws the 4
drift rows K=3x at ONE setting per run, chosen by CODEX_BATCH_SIZE (1 / 5 / 10); compare
the reports to attribute the drift. LIVE and quota-spending — see run_drift_probe.

Design: docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md
        (Part C / B4), superseding the score->band design in
        docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md
Run:    apps/worker/.venv/bin/python apps/worker/tools/score_eval.py   (or `make eval-score`)
        …/python apps/worker/tools/score_eval.py --selftest   # free, hermetic gate-logic check
        …/python apps/worker/tools/score_eval.py --batched    # LIVE: batched==single guard (B4)
        CODEX_BATCH_SIZE=1 …/python …/score_eval.py --drift-probe   # LIVE: bleed-vs-noise
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "worker"))
from ats_worker import run, score  # noqa: E402  (needs apps/worker on the path)

K = 3
# --batched / --drift-probe chunk size. Defaults to 10 — the batch shape the B4 guard
# FAILED at on 2026-07-16 — not run.py's parked DEFAULT_BATCH_SIZE=1, because these are
# the guards that must re-measure the drift, not inherit the workaround. Env-settable so
# --drift-probe can sweep b1/b5/b10 without an edit (see run_drift_probe).
BATCH_SIZE = int(os.environ.get("CODEX_BATCH_SIZE", "10"))
# The 4 domain-verdict drift rows from the 2026-07-16 --batched guard (19/23 agree):
# 111 match/adjacent->match/match · 125 match/adjacent->match/match ·
# 132 too_junior/adjacent->too_junior/match · 184 match/match->match/adjacent.
PROBE_IDS = (111, 125, 132, 184)
# The gate is only meaningful when eval-model == production-model, so the backend
# tracks run.py's default (codex / ChatGPT subscription). Override to A/B a backend:
#   SCORE_BACKEND=claude-code apps/worker/.venv/bin/python apps/worker/tools/score_eval.py
# Values: codex | claude-code (both subscription) | claude-api (METERED — real dollars
# per call, so it is never reached by accident; see the explicit branch below).
BACKEND = os.environ.get("SCORE_BACKEND", run.DEFAULT_SCORE_BACKEND)
# ...and the MODEL follows the same env vars run.main reads (run.py's --codex-score-model
# / --anthropic-score-model default out of them), so a model A/B is runnable:
#   CODEX_SCORE_MODEL=... apps/worker/.venv/bin/python apps/worker/tools/score_eval.py
# Pinning the defaults here made the tool silently ignore the override and re-measure
# the production model under an A/B's name.
_MODELS = {
    "codex": lambda: (os.environ.get("CODEX_SCORE_MODEL")
                      or run.DEFAULT_CODEX_SCORE_MODEL),
    "claude-code": lambda: (os.environ.get("CLAUDE_CODE_SCORE_MODEL")
                            or run.DEFAULT_CLAUDE_CODE_SCORE_MODEL),
    "claude-api": lambda: (os.environ.get("ANTHROPIC_SCORE_MODEL")
                           or run.DEFAULT_ANTHROPIC_SCORE_MODEL),
}
if BACKEND not in _MODELS:
    raise SystemExit(f"unknown SCORE_BACKEND {BACKEND!r} (want one of "
                     f"{tuple(_MODELS)}) — `claude` was split into 'claude-code' and "
                     "'claude-api' on 2026-08-02")
MODEL = _MODELS[BACKEND]()
# The corpus, overridable the same way BACKEND/MODEL are. An A/B needs a swappable
# corpus: on 2026-07-31 **22 of the 23 rows then in golden.jsonl named postings no longer
# in the DB**, so the default corpus scored 1 row and reported PASS at 100% — a gate that
# cannot fail. Point GOLDEN_SET at another file to measure something real meanwhile.
# The 22 orphans are still there (golden.jsonl is 93 rows as of 2026-08-02, 70 of them
# carrying the inline payload the consensus relabel wrote), but they no longer hide: a
# corpus row the harness cannot reach now FAILS the gate instead of shrinking it. See
# the reachability check in main().
# A substituted corpus is NOT the authoritative gate: golden.jsonl carries HUMAN labels,
# and anything built from the strong scorer's own verdicts measures AGREEMENT, not
# correctness (a challenger that is genuinely better scores as a regression).
GOLDEN = Path(os.environ.get("GOLDEN_SET") or ROOT / "apps/worker/eval/golden.jsonl")
OUT = Path(os.environ.get("SCORE_EVAL_OUT") or ROOT / "apps/worker/eval/last_run.md")
OUT_BATCHED = ROOT / "apps/worker/eval/last_batched_run.md"
# One report per --drift-probe setting ({b} = batch size) — the settings are compared
# against each other, so a shared path would clobber the very baseline being compared to.
OUT_PROBE_FMT = ROOT / "apps/worker/eval/last_drift_probe_b{b}.md"
DB = ROOT / "db/applications.db"
COLS = ("job_title", "company_name", "description", "location")


def notify_decision(assessment: dict) -> bool:
    """The SAME predicate db.get_notifiable routes production notify on (minus
    insufficient_context, which the golden set doesn't carry — matching per-dimension
    verdict accuracy is the gate, not this derived decision)."""
    return (assessment["seniority"]["verdict"] == "match"
            and assessment["domain"]["verdict"] == "match")


def hard_violation(row: dict, notify: bool) -> bool:
    """A `hard` row's derived notify decision must match its golden match/match status:
    a hard+keep row (golden match/match) that fails to notify, or a hard+skip row
    (golden anything-but-match/match) that DOES notify, is a safety-floor violation.
    Non-`hard` rows can never violate — soft disagreements are tolerated as noise."""
    if not row.get("hard"):
        return False
    golden_notify = row["seniority"] == "match" and row["domain"] == "match"
    return notify != golden_notify


def _chunks(seq: list, n: int):
    """Yield `seq` sliced into consecutive chunks of at most `n` items (mirrors
    ats_worker.pipeline._chunks — the batched pass chunks the same way production
    does, so the guard measures the real batching shape)."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def draw_verdicts(score_fit, posting, resumes):
    """One SINGLE-posting fit draw -> (seniority_verdict, domain_verdict), retrying a
    rare parse/truncation blip up to 3x. Adaptive thinking is non-deterministic (and
    the SDK does NOT retry a truncated 200), so a re-draw usually fits; returns None if
    all 3 attempts fail so one bad draw can't throw away the whole paid run.

    `score_fit` is the batch-first `fit(postings, resumes) -> list[dict]` (B1); a
    single draw is `score_fit([posting], resumes)[0]`.
    """
    for _ in range(3):
        try:
            assessment = score._normalize_score(score_fit([posting], resumes)[0])["assessment"]
            return assessment["seniority"]["verdict"], assessment["domain"]["verdict"]
        except score.ScoreError as exc:
            print(f"  · draw retry ({exc.__class__.__name__})", file=sys.stderr)
    return None


def _index_batch(postings: list[dict], cards: list[dict]) -> dict:
    """Map a batched fit's returned cards back to their golden-row id.

    Codex cards carry `job_ref` (== posting["id"]) verbatim (make_codex_scorer tags
    every element and the runtime already realigned by it) — keyed on that when EVERY
    card has one, since it's the model's own tag, not a trusted position. The claude
    backend's fit doesn't batch/tag, so its cards carry no job_ref; fall back to
    zipping against input order, which `fit()` guarantees for both backends anyway.
    """
    if cards and all(isinstance(c, dict) and "job_ref" in c for c in cards):
        return {c["job_ref"]: c for c in cards}
    return {p["id"]: c for p, c in zip(postings, cards)}


def draw_batch_verdicts(score_fit, postings, resumes):
    """One BATCHED fit draw over `postings` -> {id: (seniority, domain) | None}.

    Retries the WHOLE batch call up to 3x on a parse/alignment blip (mirrors
    draw_verdicts' single-draw retry — codex raises ScoreError for the entire batch on
    a bad draw, never per-element). If every attempt fails, every id in the batch maps
    to None (drift against a real single verdict, not silently dropped). A card that
    fails to normalize AFTER a successful batch call maps only THAT id to None.
    """
    cards = None
    for _ in range(3):
        try:
            cards = score_fit(postings, resumes)
            break
        except score.ScoreError as exc:
            print(f"  · batch retry ({exc.__class__.__name__})", file=sys.stderr)
    if cards is None:
        return {p["id"]: None for p in postings}
    by_id = _index_batch(postings, cards)
    out = {}
    for p in postings:
        card = by_id.get(p["id"])
        if card is None:
            out[p["id"]] = None
            continue
        try:
            assessment = score._normalize_score(card)["assessment"]
            out[p["id"]] = (assessment["seniority"]["verdict"], assessment["domain"]["verdict"])
        except score.ScoreError as exc:
            print(f"  ! id={p['id']} card failed to normalize ({exc.__class__.__name__})",
                  file=sys.stderr)
            out[p["id"]] = None
    return out


def verdicts_match(single_map: dict, batched_map: dict,
                   marked_ids: frozenset = frozenset()) -> tuple[bool, list[dict]]:
    """Pure comparator (no I/O, no model calls): per-id (seniority, domain) tuples from
    a SINGLE-pass run vs a BATCHED-pass run. A row present in `single_map` but missing
    or None (a failed draw) in `batched_map` counts as drift too — "we don't know" is
    not "they match". Returns (ok, drift_rows); drift_rows is empty iff ok is True.

    `marked_ids` are watch-list rows the K=3 accuracy gate excludes (main() splits them
    out of `render`'s gate set) because their labels are provisional or the model is
    known to split on them — e.g. golden id=132's own note reads "model splits 50/50
    (34 vs 70, a full band)". They are still SCORED and still ride in their real batches
    (dropping them would change the batch-mates whose bleed is under test), but they
    cannot decide PASS: a row documented as a coin-flip will drift on any re-draw, so
    counting it as a batching failure blames batching for known label noise. They are
    reported with `marked=True` so a reader sees them; `ok` ignores them.
    """
    drift = []
    for rid in sorted(single_map):
        single = single_map[rid]
        batched = batched_map.get(rid)
        if single != batched:
            drift.append({"id": rid, "single": single, "batched": batched,
                          "marked": rid in marked_ids})
    return not [d for d in drift if not d["marked"]], drift


def _cols_for(conn, row) -> tuple | None:
    """The COLS tuple for a golden row: the DB first, then the row's own inline
    `posting` payload. ONE helper because both callers need identical behavior — the
    first version fixed only `score_row` and left `_build_postings` skipping the same
    rows, so `--batched`/`--drift-probe` would still have reported PASS over zero rows.

    DB wins over inline when both exist: `job_postings.id` is AUTOINCREMENT so an id is
    never recycled, and the live row is the fresher copy of the same posting.
    """
    got = conn.execute(
        f"SELECT {', '.join(COLS)} FROM job_postings WHERE id=?", (row["id"],)
    ).fetchone()
    if got is not None:
        return tuple(got)
    inline = row.get("posting")
    # PRESENCE, not truthiness: `location` is NULL/empty on 174 of 11,675 live rows and
    # the DB path tolerates that, so requiring truthiness would reject a good row.
    if isinstance(inline, dict) and all(c in inline for c in COLS):
        return tuple(inline[c] for c in COLS)
    return None


def _build_postings(rows, conn) -> list[dict]:
    """Golden rows -> posting dicts carrying `id` (required: the codex fit batches by
    `posting["id"]` as `job_ref`, so every posting handed to it MUST carry one; COLS
    has no id column, so it's added explicitly)."""
    postings = []
    for row in rows:
        got = _cols_for(conn, row)
        if got is None:
            print(f"! id={row['id']} not in DB and no inline posting — skipped",
                  file=sys.stderr)
            continue
        postings.append({**dict(zip(COLS, got)), "id": row["id"]})
    return postings


def run_batched(rows, conn, score_fit, resumes, meta, batch_size: int = BATCH_SIZE) -> bool:
    """The batched==single guard (B4). Scores the golden set ONCE single and ONCE
    batched (chunks of `batch_size`, one draw per row per pass — the design's premise
    is verdicts are run-to-run stable, so single(1 draw) vs batched(1 draw) directly
    isolates context bleed rather than re-testing draw stability) and asserts the
    per-row (seniority, domain) verdicts agree. Prints + writes a drift table; PASS =
    0 drift. LIVE, quota-spending — never call this from --selftest.
    """
    postings = _build_postings(rows, conn)
    n_batches = -(-len(postings) // batch_size)  # ceil div
    print(f"--batched: LIVE run, spends quota. {len(postings)} rows, "
          f"batch_size={batch_size} ({n_batches} batch calls) …", file=sys.stderr)

    single_map: dict = {}
    for posting in postings:
        print(f"single id={posting['id']} …", file=sys.stderr, flush=True)
        single_map[posting["id"]] = draw_verdicts(score_fit, posting, resumes)

    batched_map: dict = {}
    for chunk in _chunks(postings, batch_size):
        print(f"batched ids={[p['id'] for p in chunk]} …", file=sys.stderr, flush=True)
        batched_map.update(draw_batch_verdicts(score_fit, chunk, resumes))

    # Marked rows stay in the batches above (real batch-mates) but cannot decide PASS.
    marked_ids = frozenset(r["id"] for r in rows if r.get("marked"))
    ok, drift = verdicts_match(single_map, batched_map, marked_ids)
    # Same corpus-reachability rule as the K=3 gate: `_build_postings` drops an
    # unreachable row silently, so a shrunken corpus would otherwise report PASS. Applied
    # HERE, not in render_batched, because this `ok` is what becomes the exit code.
    ok = ok and not meta.get("missing")
    doc = render_batched(single_map, batched_map, ok, drift, meta, marked_ids)
    OUT_BATCHED.write_text(doc)
    print(doc)
    print(f"→ {OUT_BATCHED.relative_to(ROOT)}")
    return ok


def render_batched(single_map, batched_map, ok, drift, meta, marked_ids=frozenset()) -> str:
    n = len(single_map)
    n_gate = n - len(marked_ids)
    gate_drift = [d for d in drift if not d["marked"]]
    watch_drift = [d for d in drift if d["marked"]]
    # Same corpus-reachability rule as the K=3 gate: `_build_postings` drops an
    # unreachable row silently, so a shrunken corpus would otherwise report PASS.
    missing = meta.get("missing") or []
    lines = [
        f"# Batched == single verdict guard (B4) — {meta['ts']}", "",
        f"Model: `{meta['model']}` · batch_size={meta['batch_size']} · rows={n} "
        f"({n_gate} gate-eligible + {len(marked_ids)} marked)"
        + (f" · **{len(missing)} of {meta.get('corpus', '?')} corpus rows unreachable: "
           f"{missing}**" if missing else ""),
        "LIVE run — spends quota. READ-ONLY on the DB. Each row scored ONCE per pass "
        "(not K×): isolates context bleed, not draw-to-draw noise.", "",
        f"**batched==single (gate-eligible): {n_gate - len(gate_drift)}/{n_gate} agree "
        f"→ {'PASS' if ok else 'FAIL'}**",
        "",
    ]
    if gate_drift:
        lines += ["## Drift (gate-eligible — decides PASS)", "```",
                  f"{'id':>5}  {'single':<18}  {'batched':<18}", "-" * 45]
        for d in gate_drift:
            s = _pair(*d["single"]) if d["single"] else "ERR/None"
            b = _pair(*d["batched"]) if d["batched"] else "ERR/None"
            lines.append(f"{d['id']:>5}  {s:<18}  {b:<18}")
        lines += ["```", "", "If verdicts drift, batching must NOT be trusted for the "
                  "queue — Phase A routing still stands regardless.", ""]
    if watch_drift:
        lines += ["## ⚑ Drift (marked — watch-list, does NOT decide PASS)", "```",
                  f"{'id':>5}  {'single':<18}  {'batched':<18}", "-" * 45]
        for d in watch_drift:
            s = _pair(*d["single"]) if d["single"] else "ERR/None"
            b = _pair(*d["batched"]) if d["batched"] else "ERR/None"
            lines.append(f"{d['id']:>5}  {s:<18}  {b:<18}")
        lines += ["```", "", "These rows are scored and ride in their real batches (their "
                  "bleed can still corrupt a gate-eligible batch-mate), but their labels "
                  "are provisional / the model is known to split on them, so a drift here "
                  "is not evidence against batching. `--drift-probe` re-draws them K×.", ""]
    if not drift:
        lines.append("0 drift — batching is safe to trust for the queue.")
    return "\n".join(lines)


def run_drift_probe(rows, conn, score_fit, resumes, meta, batch_size: int) -> bool:
    """Is the batched domain drift context BLEED, or just JD/draw NOISE? (The open
    question PROGRESS raised 2026-07-16.)

    The --batched guard draws each row ONCE single + ONCE batched, so a diff cannot
    separate "batch-mates corrupted this verdict" from "this JD's domain verdict is a
    coin-flip on any re-draw" — every drift row is adjacent-domain borderline, which is
    consistent with either. This re-draws the PROBE_IDS K× at ONE setting, selected by
    `batch_size`, and reports per-row verdict stability:

      batch_size=1  -> K × SINGLE draws of the probe rows only (4×K calls). A batch of
                       one IS the single path, so this setting needs no separate mode.
      batch_size>1  -> K × BATCHED passes over the WHOLE golden set (b10 = 3 batches ×
                       K, b5 = 5 × K). The full set is deliberate: the golden rows are
                       ordered by verdict class, so a probe row's batch-mates are what
                       bleed would come FROM — scoring the 4 rows alone would replace
                       the very context under test with each other.

    Reading the reports (run one setting per 5h quota window, then compare):
      flips at b1                  -> JD/draw noise; batching may be innocent and those
                                      golden labels are just genuinely borderline.
      stable b1 + drift at b10     -> real context bleed.
      b5 drifts less than b10      -> bleed scales with batch size. This used to read
                                      "a middle-ground batch_size keeps most of the
                                      quota win"; there is no such win. The quota is
                                      per-TOKEN credits (SCORING §4.5), so a batch
                                      saves the repeated prefix, not N-1 messages —
                                      and SCORING §8.5 measured batching dead at every
                                      size above 1 regardless.
    LIVE, quota-spending — never call from --selftest. READ-ONLY on the DB.
    """
    postings = _build_postings(rows, conn)
    probe = [p for p in postings if p["id"] in PROBE_IDS]
    missing = set(PROBE_IDS) - {p["id"] for p in probe}
    if missing:  # a probe row absent from the DB makes its column unreadable, not empty
        print(f"! probe ids missing from DB: {sorted(missing)}", file=sys.stderr)
    draws: dict = {p["id"]: [] for p in probe}

    if batch_size == 1:
        print(f"--drift-probe: SINGLE setting (b=1), {len(probe)} probe rows × K={K} "
              f"= {len(probe) * K} calls. LIVE, spends quota …", file=sys.stderr)
        for k in range(K):
            for posting in probe:
                print(f"single draw {k + 1}/{K} id={posting['id']} …",
                      file=sys.stderr, flush=True)
                draws[posting["id"]].append(draw_verdicts(score_fit, posting, resumes))
    else:
        n_batches = -(-len(postings) // batch_size)  # ceil div
        print(f"--drift-probe: BATCHED setting (b={batch_size}) over all "
              f"{len(postings)} golden rows — {n_batches} batches × K={K} = "
              f"{n_batches * K} calls. LIVE, spends quota …", file=sys.stderr)
        for k in range(K):
            for chunk in _chunks(postings, batch_size):
                print(f"batched draw {k + 1}/{K} ids={[p['id'] for p in chunk]} …",
                      file=sys.stderr, flush=True)
                for rid, verdict in draw_batch_verdicts(score_fit, chunk, resumes).items():
                    if rid in draws:  # non-probe rows ride along free; only probe reported
                        draws[rid].append(verdict)

    doc = render_drift_probe(draws, rows, meta, batch_size)
    out = OUT_PROBE_FMT.with_name(OUT_PROBE_FMT.name.format(b=batch_size))
    out.write_text(doc)
    print(doc)
    print(f"→ {out.relative_to(ROOT)}")
    return True  # a probe MEASURES; it has no pass/fail — the comparison is the answer


def render_drift_probe(draws, rows, meta, batch_size: int) -> str:
    """Probe report: per probe row, the K draws and whether the verdict held. A row
    whose draws all failed is ERR — never silently counted 'stable'."""
    golden = {r["id"]: r for r in rows}
    setting = "SINGLE (b=1)" if batch_size == 1 else f"BATCHED (b={batch_size})"
    lines = [
        f"# Drift probe — context bleed vs JD/draw noise — {meta['ts']}", "",
        f"Model: `{meta['model']}` · setting: **{setting}** · K={K}",
        "LIVE run — spends quota. READ-ONLY on the DB.", "",
        "Question: are the 4 batched-drift rows unstable because their BATCH-MATES bleed "
        "into the domain verdict, or because the verdict is a coin-flip on ANY re-draw?",
        "", "```",
        f"{'id':>5}  {'golden':<22}  {'draws (seniority/domain × K)':<62}  {'maj':<22}  held",
        "-" * 124,
    ]
    n_stable = 0
    for rid in PROBE_IDS:
        got = [d for d in draws.get(rid, []) if d is not None]
        row = golden.get(rid, {})
        gpair = _pair(row.get("seniority", "?"), row.get("domain", "?"))
        tag = " (marked)" if row.get("marked") else ""
        if not got:
            lines.append(f"{rid:>5}  {gpair + tag:<22}  {'ALL DRAWS FAILED':<62}  "
                         f"{'ERR':<22}  ?")
            continue
        maj = _pair(Counter(d[0] for d in got).most_common(1)[0][0],
                    Counter(d[1] for d in got).most_common(1)[0][0])
        held = len(set(got)) == 1
        n_stable += held
        lines.append(f"{rid:>5}  {gpair + tag:<22}  "
                     f"{' '.join(_pair(*d) for d in got):<62}  {maj:<22}  "
                     f"{'yes' if held else 'FLIPS'}")
    lines += [
        "```", "",
        f"**{n_stable}/{len(PROBE_IDS)} probe rows held one verdict across K={K} draws "
        f"at {setting}.**", "",
        "Compare settings to answer it: flips at b=1 ⇒ JD/draw noise (batching may be "
        "innocent); stable at b=1 but drifting at b=10 ⇒ real context bleed; less drift "
        "at b=5 than b=10 ⇒ bleed scales with batch size. A smaller batch is NOT a "
        "partial fix worth taking: the quota is per-token credits, so a batch saves the "
        "repeated prefix rather than N-1 messages, and batching measured dead at every "
        "size above 1 (SCORING §4.5, §8.5).",
    ]
    return "\n".join(lines)


def _write_report(path, doc: str) -> None:
    """Write a report to `path`, tolerating an out-of-repo or not-yet-existing directory.

    Both matter because the OUT path is now operator-supplied: `relative_to(ROOT)` raises
    ValueError for anything outside the repo (`/tmp/luna.md` is the natural choice when
    A/B-ing two backends concurrently), and `write_text` raises FileNotFoundError for a
    missing parent. Either would abort AFTER a quota-spending run had already finished.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc)
    try:
        shown = path.relative_to(ROOT)
    except ValueError:
        shown = path
    print(f"→ {shown}")


def score_row(conn, score_fit, resumes, row) -> dict | None:
    # A row may carry its own posting payload, which makes the corpus SELF-CONTAINED the
    # way screen_golden.jsonl already is. That asymmetry is why this corpus decayed and
    # that one did not: on 2026-07-31, 22 of 23 golden rows named postings no longer in
    # the DB, so the gate silently fell to ONE row and kept reporting PASS. Labels here
    # are hand-written and cannot be re-derived, so losing the posting loses the label.
    # Remapping by title was tried and rejected — two different golden rows fuzzy-matched
    # the same candidates.
    got = _cols_for(conn, row)
    if got is None:
        print(f"! id={row['id']} not in DB and no inline posting — skipped",
              file=sys.stderr)
        return None
    # `id` is required: the codex fit batches by posting["id"] (job_ref); COLS has no
    # id column, so add it explicitly (B1/B4 batch-first migration).
    posting = {**dict(zip(COLS, got)), "id": row["id"]}
    print(f"scoring id={row['id']} ({row['seniority']}/{row['domain']}) …",
          file=sys.stderr, flush=True)
    draws = [d for d in (draw_verdicts(score_fit, posting, resumes) for _ in range(K))
             if d is not None]
    if not draws:  # every draw failed even after retries — flag, don't abort/silently pass
        print(f"! id={row['id']} — all {K} draws failed; row ERRORED", file=sys.stderr)
        return {**row, "title": posting["job_title"], "draws": [],
                "maj_seniority": "ERR", "maj_domain": "ERR", "flip": False,
                "agree": False, "notify": False, "hard_viol": False, "errored": True}
    seniorities, domains = [d[0] for d in draws], [d[1] for d in draws]
    maj_seniority = Counter(seniorities).most_common(1)[0][0]
    maj_domain = Counter(domains).most_common(1)[0][0]
    notify = notify_decision({"seniority": {"verdict": maj_seniority},
                               "domain": {"verdict": maj_domain}})
    return {**row, "title": posting["job_title"], "draws": draws,
            "maj_seniority": maj_seniority, "maj_domain": maj_domain,
            "flip": len(set(seniorities)) > 1 or len(set(domains)) > 1,
            "agree": maj_seniority == row["seniority"] and maj_domain == row["domain"],
            "notify": notify, "hard_viol": hard_violation(row, notify), "errored": False}


def _pair(seniority, domain) -> str:
    return f"{seniority}/{domain}"


def _rowline(r) -> str:
    draws = " ".join(_pair(s, d) for s, d in r["draws"]) or "ERRORED"
    golden = _pair(r["seniority"], r["domain"])
    maj = "ERR" if r.get("errored") else _pair(r["maj_seniority"], r["maj_domain"])
    tag = " (hard)" if r.get("hard") else ""
    return (f"{r['id']:>5}  {golden:<18}  {draws:<58}  {maj:<18}  "
            f"{'⚠' if r['flip'] else '-'}  {'✓' if r['agree'] else '✗'}{tag}  "
            f"{'notify' if r['notify'] else '—':<6}  {r['title'][:40]}")


def render(gate, watch, meta) -> str:
    hard = [r for r in gate if r.get("hard")]
    errored = [r for r in gate if r.get("errored")]
    hard_viol = [r for r in hard if r.get("hard_viol")]
    agree, flips, n = sum(r["agree"] for r in gate), sum(r["flip"] for r in gate), len(gate)
    apct, fpct = (100 * agree / n, 100 * flips / n) if n else (0.0, 0.0)
    # An unreachable row is a corpus defect, not a scoring result, and it must not be
    # survivable: the rows that vanish are whichever ones the DB happened to lose, so
    # the surviving sample is not the gate anyone approved. FAIL is the only honest
    # verdict — see the corpus-reachability check in main().
    missing = meta.get("missing") or []
    passed = (not hard_viol and not errored and not missing
              and apct >= 85 and fpct < 20)
    verdict = (f"agreement {agree}/{n} ({apct:.0f}%) · hard {len(hard) - len(hard_viol)}/"
               f"{len(hard)} · flip-rate {fpct:.0f}% → {'PASS' if passed else 'FAIL'}"
               + (f"  ⚠ {len(errored)} ERRORED — re-run" if errored else "")
               + (f"  ⚠ {len(missing)} of {meta.get('corpus', '?')} CORPUS ROWS "
                  f"UNREACHABLE — the gate did not see them" if missing else ""))
    head = (f"{'id':>5}  {'golden':<18}  {'draws (seniority/domain × K)':<58}  "
            f"{'maj':<18}  fl ag        notify  title")
    lines = [
        f"# Fit-score verdict-accuracy eval — {meta['ts']}", "",
        f"Model: `{meta['model']}` · resumes: {meta['labels']} · "
        f"profile: {meta['profile']} chars · K={K} · gate rows: {n}"
        + (f" · **{len(missing)} of {meta.get('corpus', '?')} corpus rows unreachable "
           f"(no DB row, no inline payload): {missing}**" if missing else ""),
        "READ-ONLY — scores measured, never written to the DB. "
        "Shipping needs two consecutive PASS runs.", "",
        f"**{verdict}**", "", "## Per-row (gate)", "```", head, "-" * 130,
        *[_rowline(r) for r in gate], "```", "",
        "## ⚑ Watch list (marked — scored, excluded from gate)", "```",
        *([_rowline(r) for r in watch] or ["(none)"]), "```", "",
    ]
    return "\n".join(lines)


def main() -> int:
    if "--selftest" in sys.argv:  # free, hermetic: guards the gate's core logic
        assert notify_decision(
            {"seniority": {"verdict": "match"}, "domain": {"verdict": "match"}}) is True
        assert notify_decision(
            {"seniority": {"verdict": "match"}, "domain": {"verdict": "adjacent"}}) is False
        assert notify_decision(
            {"seniority": {"verdict": "too_junior"}, "domain": {"verdict": "match"}}) is False

        hard_keep = {"hard": True, "seniority": "match", "domain": "match"}
        hard_skip = {"hard": True, "seniority": "too_junior", "domain": "match"}
        soft_skip = {"hard": False, "seniority": "too_junior", "domain": "match"}
        assert hard_violation(hard_keep, notify=True) is False   # hard+keep, matched -> ok
        assert hard_violation(hard_keep, notify=False) is True   # hard+keep, missed -> VIOLATION
        assert hard_violation(hard_skip, notify=True) is True    # hard+skip, wrongly notified -> VIOLATION
        assert hard_violation(hard_skip, notify=False) is False  # hard+skip, correctly held -> ok
        assert hard_violation(soft_skip, notify=True) is False   # not hard -> never a violation

        # B4: verdicts_match — the batched==single drift comparator, hermetic (no
        # model calls). Identical maps -> no drift; a differing entry -> that row
        # (and only that row) reported as drift.
        base = {1: ("match", "match"), 2: ("too_junior", "match"), 3: ("match", "adjacent")}
        ok, drift = verdicts_match(base, dict(base))
        assert ok is True and drift == []
        flipped = {**base, 2: ("match", "match")}  # row 2's seniority verdict drifted
        ok, drift = verdicts_match(base, flipped)
        assert ok is False
        assert drift == [{"id": 2, "single": ("too_junior", "match"),
                           "batched": ("match", "match"), "marked": False}]
        # A missing/failed batched draw (None) is drift too, not a silent pass.
        ok, drift = verdicts_match(base, {**base, 3: None})
        assert ok is False
        assert drift == [{"id": 3, "single": ("match", "adjacent"), "batched": None,
                          "marked": False}]
        # A `marked` (watch-list) row is REPORTED as drift but cannot fail the guard —
        # the K=3 accuracy gate excludes those rows, so counting them here blames
        # batching for known label noise (golden 132: "model splits 50/50").
        ok, drift = verdicts_match(base, flipped, marked_ids=frozenset({2}))
        assert ok is True, "a marked row must not decide PASS"
        assert drift == [{"id": 2, "single": ("too_junior", "match"),
                           "batched": ("match", "match"), "marked": True}]
        # …but a gate-eligible row drifting alongside a marked one still FAILS.
        ok, drift = verdicts_match(base, {**flipped, 3: None}, marked_ids=frozenset({2}))
        assert ok is False
        assert [d["id"] for d in drift] == [2, 3]

        # --drift-probe: the whole probe REPORTS a stability call, so a bug there answers
        # bleed-vs-noise wrong while looking fine. Hermetic (fake draws, no model calls).
        probe_meta = {"ts": "-", "model": "-", "batch_size": 1}
        probe_rows = [{"id": rid, "seniority": "match", "domain": "adjacent"}
                      for rid in PROBE_IDS]
        held = render_drift_probe({rid: [("match", "adjacent")] * K for rid in PROBE_IDS},
                                  probe_rows, probe_meta, 1)
        assert f"{len(PROBE_IDS)}/{len(PROBE_IDS)} probe rows held" in held
        assert "FLIPS" not in held
        # One row's domain flips across draws -> that row FLIPS, the count drops.
        flips = render_drift_probe(
            {**{rid: [("match", "adjacent")] * K for rid in PROBE_IDS},
             PROBE_IDS[0]: [("match", "adjacent"), ("match", "match"), ("match", "adjacent")]},
            probe_rows, probe_meta, 10)
        assert "FLIPS" in flips
        assert f"{len(PROBE_IDS) - 1}/{len(PROBE_IDS)} probe rows held" in flips
        # A row whose every draw failed is ERR — never silently counted stable.
        errored = render_drift_probe({**{rid: [("match", "adjacent")] * K for rid in PROBE_IDS},
                                      PROBE_IDS[0]: [None, None, None]},
                                     probe_rows, probe_meta, 1)
        assert "ALL DRAWS FAILED" in errored
        assert f"{len(PROBE_IDS) - 1}/{len(PROBE_IDS)} probe rows held" in errored

        # Corpus reachability. A row the corpus names but the harness cannot reach is a
        # gate that did not RUN, and it used to just shrink `n` behind one stderr line —
        # which is how the authoritative fit gate reported PASS over 71 of its 93 rows.
        clean = {"id": 1, "seniority": "match", "domain": "match", "hard": False,
                 "draws": [("match", "match")] * K, "maj_seniority": "match",
                 "maj_domain": "match", "flip": 0, "agree": 1, "notify": True,
                 "title": "t"}
        gate_meta = {"ts": "-", "model": "-", "labels": [], "profile": 0}
        assert "→ PASS" in render([clean], [], gate_meta)
        holed = render([clean], [], {**gate_meta, "missing": [7, 9], "corpus": 3})
        assert "→ FAIL" in holed, "unreachable corpus rows must not survive as a PASS"
        assert "2 of 3 corpus rows unreachable" in holed
        # The batched guard reports the same hole (its PASS is flipped in run_batched,
        # where the value becomes the exit code).
        assert "1 of 2 corpus rows unreachable" in render_batched(
            {1: ("match", "match")}, {1: ("match", "match")}, True, [],
            {"ts": "-", "model": "-", "batch_size": 1, "missing": [7], "corpus": 2})

        print("selftest ok")
        return 0

    rows = [json.loads(l) for l in GOLDEN.read_text().splitlines() if l.strip()]
    env = run.load_env(str(ROOT / "apps/worker/.env"))
    resumes, profile = run.load_resumes(str(ROOT / "apps/worker/resume"))
    if BACKEND == "codex":
        score_fit = score.make_codex_scorer(MODEL, profile=profile)
    elif BACKEND == "claude-code":
        score_fit = score.make_claude_cli_scorer(MODEL, profile=profile)
    else:
        # max_tokens 8192 (prod is 4096): adaptive thinking + the verbose assessment
        # notes truncate the JSON at 4096 on some rows -> ScoreError. The cap doesn't
        # change the model's *score* (only whether the JSON completes), so this is
        # measurement-neutral.
        score_fit = score.make_claude_scorer(
            env["ANTHROPIC_API_KEY"], MODEL, profile=profile, max_tokens=8192)
    # mode=ro: a bug can never write the shared DB (probed: reads the live WAL fine).
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        # Corpus reachability, measured ONCE and up front. Every scoring path below
        # drops an unreachable row with a stderr line and carries on, so `n` in the
        # report is the rows that survived — and a report saying "gate rows: 71" over a
        # 93-row corpus reads exactly like a healthy 71-row gate. That is the same
        # green-gate-that-cannot-fail shape as the clearance tautology in eval-screen.
        # Counted here rather than in the scoring loops because `--batched` and
        # `--drift-probe` share the hole and would each need their own tally.
        missing = [r["id"] for r in rows if _cols_for(conn, r) is None]
        if missing:
            print(f"! {len(missing)} of {len(rows)} corpus rows are unreachable — no DB "
                  f"row and no inline `posting` payload: {missing}", file=sys.stderr)
        if "--batched" in sys.argv:  # B4: LIVE, quota-spending batched==single guard
            meta = {"ts": time.strftime("%Y-%m-%d %H:%M"), "model": MODEL,
                    "batch_size": BATCH_SIZE, "missing": missing, "corpus": len(rows)}
            ok = run_batched(rows, conn, score_fit, resumes, meta, batch_size=BATCH_SIZE)
            return 0 if ok else 1
        if "--drift-probe" in sys.argv:  # LIVE: bleed-vs-noise probe (one setting/run)
            meta = {"ts": time.strftime("%Y-%m-%d %H:%M"), "model": MODEL,
                    "batch_size": BATCH_SIZE}
            run_drift_probe(rows, conn, score_fit, resumes, meta, batch_size=BATCH_SIZE)
            return 0
        scored = [r for r in (score_row(conn, score_fit, resumes, x) for x in rows) if r]
    finally:
        conn.close()

    meta = {"ts": time.strftime("%Y-%m-%d %H:%M"), "model": MODEL,
            "labels": list(resumes), "profile": len(profile),
            # Which corpus produced this. Without it, a shell that still exports
            # GOLDEN_SET emits a report indistinguishable from the authoritative gate's
            # while measuring a substitute (machine-labelled) corpus.
            "golden": GOLDEN, "missing": missing, "corpus": len(rows)}
    doc = render([r for r in scored if not r.get("marked")],
                 [r for r in scored if r.get("marked")], meta)
    # print BEFORE writing: the write can fail (missing parent dir) and this run cost
    # real quota, so the report must reach the terminal either way.
    print(doc)
    _write_report(OUT, doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
