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
regardless (see the design doc).

Design: docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md
        (Part C / B4), superseding the score->band design in
        docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md
Run:    apps/worker/.venv/bin/python apps/worker/tools/score_eval.py   (or `make eval-score`)
        …/python apps/worker/tools/score_eval.py --selftest   # free, hermetic gate-logic check
        …/python apps/worker/tools/score_eval.py --batched    # LIVE: batched==single guard (B4)
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
# --batched mode's chunk size — mirrors ats_worker.pipeline.run_score's default
# (and CODEX_BATCH_SIZE), so the guard measures the same batching production uses.
BATCH_SIZE = 10
# The gate is only meaningful when eval-model == production-model, so the backend
# tracks run.py's default (codex / ChatGPT subscription). Override to A/B a backend:
#   SCORE_BACKEND=claude apps/worker/.venv/bin/python apps/worker/tools/score_eval.py
BACKEND = os.environ.get("SCORE_BACKEND", run.DEFAULT_SCORE_BACKEND)
MODEL = (run.DEFAULT_CODEX_SCORE_MODEL if BACKEND == "codex"
         else run.DEFAULT_ANTHROPIC_SCORE_MODEL)
GOLDEN = ROOT / "apps/worker/eval/golden.jsonl"
OUT = ROOT / "apps/worker/eval/last_run.md"
OUT_BATCHED = ROOT / "apps/worker/eval/last_batched_run.md"
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


def verdicts_match(single_map: dict, batched_map: dict) -> tuple[bool, list[dict]]:
    """Pure comparator (no I/O, no model calls): per-id (seniority, domain) tuples from
    a SINGLE-pass run vs a BATCHED-pass run. A row present in `single_map` but missing
    or None (a failed draw) in `batched_map` counts as drift too — "we don't know" is
    not "they match". Returns (ok, drift_rows); drift_rows is empty iff ok is True.
    """
    drift = []
    for rid in sorted(single_map):
        single = single_map[rid]
        batched = batched_map.get(rid)
        if single != batched:
            drift.append({"id": rid, "single": single, "batched": batched})
    return not drift, drift


def _build_postings(rows, conn) -> list[dict]:
    """Golden rows -> posting dicts carrying `id` (required: the codex fit batches by
    `posting["id"]` as `job_ref`, so every posting handed to it MUST carry one; COLS
    has no id column, so it's added explicitly)."""
    postings = []
    for row in rows:
        got = conn.execute(
            f"SELECT {', '.join(COLS)} FROM job_postings WHERE id=?", (row["id"],)
        ).fetchone()
        if got is None:
            print(f"! id={row['id']} not in DB — skipped", file=sys.stderr)
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

    ok, drift = verdicts_match(single_map, batched_map)
    doc = render_batched(single_map, batched_map, ok, drift, meta)
    OUT_BATCHED.write_text(doc)
    print(doc)
    print(f"→ {OUT_BATCHED.relative_to(ROOT)}")
    return ok


def render_batched(single_map, batched_map, ok, drift, meta) -> str:
    n = len(single_map)
    lines = [
        f"# Batched == single verdict guard (B4) — {meta['ts']}", "",
        f"Model: `{meta['model']}` · batch_size={meta['batch_size']} · rows={n}",
        "LIVE run — spends quota. READ-ONLY on the DB. Each row scored ONCE per pass "
        "(not K×): isolates context bleed, not draw-to-draw noise.", "",
        f"**batched==single: {n - len(drift)}/{n} agree → {'PASS' if ok else 'FAIL'}**",
        "",
    ]
    if drift:
        lines += ["## Drift", "```", f"{'id':>5}  {'single':<18}  {'batched':<18}", "-" * 45]
        for d in drift:
            s = _pair(*d["single"]) if d["single"] else "ERR/None"
            b = _pair(*d["batched"]) if d["batched"] else "ERR/None"
            lines.append(f"{d['id']:>5}  {s:<18}  {b:<18}")
        lines += ["```", "", "If verdicts drift, batching must NOT be trusted for the "
                  "queue — Phase A routing still stands regardless."]
    else:
        lines.append("0 drift — batching is safe to trust for the queue.")
    return "\n".join(lines)


def score_row(conn, score_fit, resumes, row) -> dict | None:
    got = conn.execute(
        f"SELECT {', '.join(COLS)} FROM job_postings WHERE id=?", (row["id"],)
    ).fetchone()
    if got is None:
        print(f"! id={row['id']} not in DB — skipped", file=sys.stderr)
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
    passed = not hard_viol and not errored and apct >= 85 and fpct < 20
    verdict = (f"agreement {agree}/{n} ({apct:.0f}%) · hard {len(hard) - len(hard_viol)}/"
               f"{len(hard)} · flip-rate {fpct:.0f}% → {'PASS' if passed else 'FAIL'}"
               + (f"  ⚠ {len(errored)} ERRORED — re-run" if errored else ""))
    head = (f"{'id':>5}  {'golden':<18}  {'draws (seniority/domain × K)':<58}  "
            f"{'maj':<18}  fl ag        notify  title")
    lines = [
        f"# Fit-score verdict-accuracy eval — {meta['ts']}", "",
        f"Model: `{meta['model']}` · resumes: {meta['labels']} · "
        f"profile: {meta['profile']} chars · K={K} · gate rows: {n}",
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
                           "batched": ("match", "match")}]
        # A missing/failed batched draw (None) is drift too, not a silent pass.
        ok, drift = verdicts_match(base, {**base, 3: None})
        assert ok is False
        assert drift == [{"id": 3, "single": ("match", "adjacent"), "batched": None}]

        print("selftest ok")
        return 0

    rows = [json.loads(l) for l in GOLDEN.read_text().splitlines() if l.strip()]
    env = run.load_env(str(ROOT / "apps/worker/.env"))
    resumes, profile = run.load_resumes(str(ROOT / "apps/worker/resume"))
    if BACKEND == "codex":
        score_fit = score.make_codex_scorer(MODEL, profile=profile)
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
        if "--batched" in sys.argv:  # B4: LIVE, quota-spending batched==single guard
            meta = {"ts": time.strftime("%Y-%m-%d %H:%M"), "model": MODEL,
                    "batch_size": BATCH_SIZE}
            ok = run_batched(rows, conn, score_fit, resumes, meta, batch_size=BATCH_SIZE)
            return 0 if ok else 1
        scored = [r for r in (score_row(conn, score_fit, resumes, x) for x in rows) if r]
    finally:
        conn.close()

    meta = {"ts": time.strftime("%Y-%m-%d %H:%M"), "model": MODEL,
            "labels": list(resumes), "profile": len(profile)}
    doc = render([r for r in scored if not r.get("marked")],
                 [r for r in scored if r.get("marked")], meta)
    OUT.write_text(doc)
    print(doc)
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
