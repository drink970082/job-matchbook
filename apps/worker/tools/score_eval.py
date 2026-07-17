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

Design: docs/superpowers/specs/2026-07-16-enum-routing-and-batched-scoring-design.md
        (Part C), superseding the score->band design in
        docs/superpowers/specs/2026-07-15-fit-score-eval-harness-design.md
Run:    apps/worker/.venv/bin/python apps/worker/tools/score_eval.py   (or `make eval-score`)
        …/python apps/worker/tools/score_eval.py --selftest   # free, hermetic gate-logic check
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


def draw_verdicts(score_fit, posting, resumes):
    """One fit draw -> (seniority_verdict, domain_verdict), retrying a rare parse/
    truncation blip up to 3x. Adaptive thinking is non-deterministic (and the SDK does
    NOT retry a truncated 200), so a re-draw usually fits; returns None if all 3
    attempts fail so one bad draw can't throw away the whole paid run."""
    for _ in range(3):
        try:
            assessment = score._normalize_score(score_fit(posting, resumes))["assessment"]
            return assessment["seniority"]["verdict"], assessment["domain"]["verdict"]
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
