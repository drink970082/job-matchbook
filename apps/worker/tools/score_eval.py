#!/usr/bin/env python
"""Band-regression eval for the fit-score prompt — READ-ONLY, never writes the DB.

Reuses the exact production wiring (load_resumes -> the run.py default score backend ->
score_fit -> _normalize_score), scores each labeled golden-set row K=3x, buckets each
score to a keep/near/skip band, and judges the MAJORITY band against the frozen human
label. The gate only means something when eval-model == production-model, so the backend
follows run.DEFAULT_SCORE_BACKEND; SCORE_BACKEND=claude A/Bs the old metered path. PASS over the gate-eligible (non-`marked`) rows: 0 hard-invariant violations AND
>=85% band-agreement AND <20% flip-rate; shipping needs two consecutive PASS runs.
`marked` rows are scored but routed to a ⚑ watch list, excluded from the gate.

Design: docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md
Run:    apps/worker/.venv/bin/python apps/worker/tools/score_eval.py   (or `make eval-score`)
        …/python apps/worker/tools/score_eval.py --selftest   # free band-boundary check
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
# The gate is only meaningful when eval-model == production-model, so the backend
# tracks run.py's default (codex / ChatGPT subscription). Override to A/B a backend:
#   SCORE_BACKEND=claude apps/worker/.venv/bin/python apps/worker/tools/score_eval.py
BACKEND = os.environ.get("SCORE_BACKEND", run.DEFAULT_SCORE_BACKEND)
MODEL = (run.DEFAULT_CODEX_SCORE_MODEL if BACKEND == "codex"
         else run.DEFAULT_ANTHROPIC_SCORE_MODEL)
GOLDEN = ROOT / "apps/worker/eval/golden.jsonl"
OUT = ROOT / "apps/worker/eval/last_run.md"
DB = ROOT / "db/applications.db"
COLS = ("job_title", "company_name", "description", "location")


def band(s: int) -> str:
    """Bucket a fit score to the operator's decision band — the rubric's own
    boundaries (>=75 = notify threshold, 60-74 = partial fit), no new thresholds."""
    return "keep" if s >= 75 else "near" if s >= 60 else "skip"


def draw_score(score_fit, posting, resumes):
    """One fit draw -> int score, retrying a rare parse/truncation blip up to 3x.
    Adaptive thinking is non-deterministic (and the SDK does NOT retry a truncated
    200), so a re-draw usually fits; returns None if all 3 attempts fail so one bad
    draw can't throw away the whole paid run."""
    for _ in range(3):
        try:
            return score._normalize_score(score_fit(posting, resumes))["score"]
        except score.ScoreError as exc:
            print(f"  · draw retry ({exc.__class__.__name__})", file=sys.stderr)
    return None


def score_row(conn, score_fit, resumes, row) -> dict | None:
    got = conn.execute(
        f"SELECT {', '.join(COLS)} FROM job_postings WHERE id=?", (row["id"],)
    ).fetchone()
    if got is None:
        print(f"! id={row['id']} not in DB — skipped", file=sys.stderr)
        return None
    posting = dict(zip(COLS, got))
    print(f"scoring id={row['id']} ({row['band']}) …", file=sys.stderr, flush=True)
    scores = [s for s in (draw_score(score_fit, posting, resumes) for _ in range(K))
              if s is not None]
    if not scores:  # every draw failed even after retries — flag, don't abort/silently pass
        print(f"! id={row['id']} — all {K} draws failed; row ERRORED", file=sys.stderr)
        return {**row, "title": posting["job_title"], "scores": [], "bands": [],
                "maj": "ERR", "flip": False, "ok": False, "errored": True}
    bands = [band(s) for s in scores]
    maj = Counter(bands).most_common(1)[0][0]
    return {**row, "title": posting["job_title"], "scores": scores, "bands": bands,
            "maj": maj, "flip": len(set(bands)) > 1, "ok": maj == row["band"]}


def _rowline(r) -> str:
    runs = " ".join(f"{b}({s})" for b, s in zip(r["bands"], r["scores"])) or "ERRORED"
    tag = " (hard)" if r.get("hard") else ""
    return (f"{r['id']:>5}  {r['band']:<5}  {runs:<26}  {r['maj']:<5}  "
            f"{'⚠' if r['flip'] else '-'}  {'✓' if r['ok'] else '✗'}{tag}  {r['title'][:44]}")


def render(gate, watch, meta) -> str:
    hard = [r for r in gate if r.get("hard")]
    errored = [r for r in gate if r.get("errored")]
    hard_viol = [r for r in hard if not r["ok"] and not r.get("errored")]
    agree, flips, n = sum(r["ok"] for r in gate), sum(r["flip"] for r in gate), len(gate)
    apct, fpct = (100 * agree / n, 100 * flips / n) if n else (0.0, 0.0)
    passed = not hard_viol and not errored and apct >= 85 and fpct < 20
    verdict = (f"agreement {agree}/{n} ({apct:.0f}%) · hard {len(hard) - len(hard_viol)}/"
               f"{len(hard)} · flip-rate {fpct:.0f}% → {'PASS' if passed else 'FAIL'}"
               + (f"  ⚠ {len(errored)} ERRORED — re-run" if errored else ""))
    head = f"{'id':>5}  {'human':<5}  {'runs':<26}  {'maj':<5}  fl ok"
    lines = [
        f"# Fit-score band-regression eval — {meta['ts']}", "",
        f"Model: `{meta['model']}` · resumes: {meta['labels']} · "
        f"profile: {meta['profile']} chars · K={K} · gate rows: {n}",
        "READ-ONLY — scores measured, never written to the DB. "
        "Shipping needs two consecutive PASS runs.", "",
        f"**{verdict}**", "", "## Per-row (gate)", "```", head, "-" * 78,
        *[_rowline(r) for r in gate], "```", "",
        "## ⚑ Watch list (marked — scored, excluded from gate)", "```",
        *([_rowline(r) for r in watch] or ["(none)"]), "```", "",
    ]
    return "\n".join(lines)


def main() -> int:
    if "--selftest" in sys.argv:  # free: guards the score->band boundaries (the gate's core)
        assert [band(s) for s in (100, 75, 74, 60, 59, 0)] == \
            ["keep", "keep", "near", "near", "skip", "skip"], "band boundaries drifted"
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
