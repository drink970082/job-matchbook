"""Gate the FREE seniority pre-ordering layer (ats_worker/score/seniority.py).

FREE: local Ollama only, zero paid calls, and READ-ONLY on the database.

What it measures, and the framing matters more than the numbers: the labels are the
strong scorer's own `seniority` verdicts on rows it has already scored — **Sol's
verdicts, not human labels**. The corpus therefore inherits Sol's errors (two known
ones are recorded in docs/PROGRESS.md), which is why this gate is allowed to authorize
a RE-ORDERING and never a discard.

**THREE LIMITS ON WHAT A GREEN RUN PROVES. Read them before quoting a number.**

1. **It is IN-SAMPLE.** `YEARS_MARGIN`, `SENIOR_YEARS`, the keep-direction veto and the
   thresholds below were all fitted on this same corpus. There is no held-out split and
   no second corpus, so the precision and the zero-false-demotion result are training-set
   numbers, not estimates of future performance.
2. **The decisive gate has little statistical power.** Only ~34 of 446 rows are
   `domain=match` and ~18 were notified. With the 7 false demotions the shipped run
   produces placed at random, the chance of hitting neither set is roughly 0.57 and
   0.75 — so the gate can go green for a layer whose demotions are indifferent to
   whether a row was a payoff row. Treat a pass as "no evidence of harm", never as
   "evidence of no harm".
3. **The corpus is not the production population.** `build_corpus` selects rows that
   already SURVIVED the screen and bought a paid fit call, so every row has a real
   description (minimum 200 chars). Production runs this layer on every `new` row,
   before the screen and before the thin-JD gate — including short postings where a bare
   "Senior ..." title is nearly all the model sees. That population is 0% of this eval.

Positive class = `too_junior` = "send this row to the back of the score queue".
A false positive is a real job delayed; a false negative is one paid call spent.

    PYTHONPATH=. python3 tools/seniority_eval.py --build-corpus  # read-only DB -> jsonl
    PYTHONPATH=. python3 tools/seniority_eval.py --selftest      # hermetic, no model
    make eval-seniority
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "worker"))
from ats_worker import run  # noqa: E402  (needs apps/worker on the path)
from ats_worker.score import seniority  # noqa: E402
from ats_worker.score.screen import make_ollama_extract  # noqa: E402

GOLDEN = ROOT / "apps/worker/eval/seniority_golden.jsonl"
OUT = ROOT / "apps/worker/eval/last_seniority_run.md"

# The eval candidate. FIXED here, not read from config.yaml, for the same reason
# screen_eval fixes its own: the labels are JD facts and the gate's meaning must not
# drift with the operator's config. 0 = the stage the 2026-07-30 run measured.
YEARS_EXPERIENCE = 0

# K=1 draw, deliberately. At production settings (temperature=0, seed=0) the extraction
# is bit-reproducible — 0 flips in 79 re-draws on 2026-07-30 — so a second draw measures
# nothing. Determinism is NOT confidence: the errors are systematic and will never
# average out. Do not read a single clean run as robustness.
K = 1

# --- the gate ---------------------------------------------------------------
# The number that decides this layer is not the P/R, it is WHICH rows the false
# demotions are. Every row the strong scorer called `domain=match` is the notify payoff
# set; demoting one of those delays a job the human would have seen. Measured 0.
MAX_FALSE_DEMOTES_ON_MATCH_DOMAIN = 0
MIN_PRECISION = 0.95            # measured 0.964 with both keep-direction vetoes
# Measured 0.442 — a THIN margin over this gate, not a comfortable one, and it moved
# 0.484 -> 0.442 when the rank veto landed. Any further keep-direction change should
# expect to trip this, which is the point: below it the layer stops buying enough to
# justify the GPU time.
MIN_DEMOTE_SHARE = 0.40


def build_corpus(db_path: Path) -> int:
    """Freeze every already-scored row that carries a seniority verdict. Read-only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, job_title, company_name, location, description, score_detail,
               pipeline_status
          FROM job_postings
         WHERE json_extract(score_detail,'$.assessment.seniority.verdict') IS NOT NULL
           AND pipeline_status IN ('scored','notified')
         ORDER BY id
    """).fetchall()
    with GOLDEN.open("w", encoding="utf-8") as fh:
        for row in rows:
            detail = json.loads(row["score_detail"])
            assessment = detail.get("assessment", {})
            fh.write(json.dumps({
                "id": row["id"],
                "job_title": row["job_title"],
                "company_name": row["company_name"],
                "location": row["location"],
                "description": row["description"],
                "sol_seniority": assessment.get("seniority", {}).get("verdict"),
                "sol_domain": (assessment.get("domain") or {}).get("verdict"),
                "notified": row["pipeline_status"] == "notified",
            }) + "\n")
    conn.close()
    return len(rows)


def load_corpus() -> list[dict]:
    if not GOLDEN.exists():
        print(f"no corpus at {GOLDEN.relative_to(ROOT)} — run --build-corpus first",
              file=sys.stderr)
        raise SystemExit(2)
    return [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def selftest(rows: list[dict]) -> int:
    """Hermetic: the code-side rule and the veto, with no model and no database."""
    text = "We want 5+ years of experience."
    assert seniority.stated_years(text) == {5}, seniority.stated_years(text)
    ladder = "Master's and no experience; or Bachelor's and 3 years of experience."
    assert seniority.stated_years(ladder) == {3}, seniority.stated_years(ladder)
    # the veto can only ever LOWER a bar
    assert seniority.clamp_years(5, "at least 2 years") == 2
    assert seniority.clamp_years(1, "at least 4 years") == 1
    assert seniority.clamp_years(None, "3 years") is None
    # word forms and parentheticals the model quotes back as digits
    assert seniority.stated_years("three (3) years") == {3}
    assert 1 in seniority.stated_years("1-3 years")
    # the code-side rule
    assert seniority.verdict({"stated_min_years": 5}, job_text="5 years") == "too_junior"
    assert seniority.verdict({"stated_min_years": 1}, job_text="1 year") == "match"
    assert seniority.verdict({"stated_rank": "staff"},
                             job_text="Staff Engineer") == "too_junior"
    assert seniority.verdict({"stated_rank": "manager"}, job_text="Manager") == "match"
    # the rank path's keep-direction veto: a rank the posting never names is not a bar
    assert seniority.verdict({"stated_rank": "staff"}, job_text="Junior role") == "match"
    # a blind or empty response is a KEEP
    assert seniority.verdict(None, job_text="") == "match"
    assert seniority.verdict({}, job_text="") == "match"
    # the flat shape counts, same as the wrapped one (#48)
    assert seniority.read_entry({"seniority": {"stated_rank": "lead"}}) is not None
    assert seniority.read_entry({"screen": {"seniority": {"stated_rank": "lead"}}}) is not None
    # a senior candidate is not demoted by a rank the JD names
    assert seniority.verdict({"stated_rank": "staff"}, job_text="Staff Engineer",
                             years_experience=8) == "match"
    if rows:
        missing = [r["id"] for r in rows if not (r.get("description") or "").strip()]
        assert not missing, f"corpus rows with no description: {missing[:5]}"
        labels = {r["sol_seniority"] for r in rows}
        assert labels <= {"too_junior", "match", "insufficient_context"}, labels
    print(f"selftest ok — rule, veto and shape checks pass; corpus rows: {len(rows)}")
    return 0


def evaluate(rows: list[dict], extract, num_ctx: int) -> dict:
    cells = {"tp": [], "fp": [], "fn": [], "tn": []}
    blind, errors, details = [], [], {}
    started = time.time()
    for n, row in enumerate(rows, 1):
        got, detail = seniority.assess(row, extract, years_experience=YEARS_EXPERIENCE,
                                       max_desc_chars=num_ctx * 2)
        details[row["id"]] = detail
        if detail.get("error"):
            errors.append(row["id"])
        elif detail.get("blind"):
            blind.append(row["id"])
        sol_junior = row["sol_seniority"] == "too_junior"
        free_junior = got == "too_junior"
        cell = ("tp" if sol_junior else "fp") if free_junior else ("fn" if sol_junior else "tn")
        cells[cell].append(row["id"])
        if n % 25 == 0:
            print(f"\r{n}/{len(rows)} rows  {time.time()-started:.0f}s",
                  end="", file=sys.stderr)
    print(file=sys.stderr)
    return {"cells": cells, "blind": blind, "errors": errors, "details": details,
            "secs": round(time.time() - started, 1)}


def report(rows: list[dict], result: dict, model: str, num_ctx: int) -> tuple[str, bool]:
    cells = result["cells"]
    tp, fp, fn, tn = (len(cells[k]) for k in ("tp", "fp", "fn", "tn"))
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    demote_share = (tp + fp) / total if total else 0.0

    by_id = {r["id"]: r for r in rows}
    on_match_domain = [i for i in cells["fp"] if by_id[i]["sol_domain"] == "match"]
    on_notified = [i for i in cells["fp"] if by_id[i]["notified"]]

    passed = (len(on_match_domain) <= MAX_FALSE_DEMOTES_ON_MATCH_DOMAIN
              and not on_notified
              and precision >= MIN_PRECISION
              and demote_share >= MIN_DEMOTE_SHARE)

    lines = [
        f"# Seniority pre-ordering eval — {'PASS' if passed else 'FAIL'}",
        "",
        f"- model `{model}`, num_ctx {num_ctx}, K={K} draw (deterministic at "
        f"temperature=0 / seed=0), {result['secs']}s for {total} rows",
        f"- corpus `{GOLDEN.name}` — labels are the strong scorer's own verdicts, "
        "NOT human labels",
        "",
        "## Confusion (positive class = too_junior = send to the back of the queue)",
        "",
        f"| | Sol too_junior | Sol not |",
        f"|---|---|---|",
        f"| **free too_junior** | TP {tp} | FP {fp} |",
        f"| **free match** | FN {fn} | TN {tn} |",
        "",
        f"- precision **{precision:.3f}** (gate: >= {MIN_PRECISION})",
        f"- recall **{recall:.3f}** (reported, not gated — a miss costs one paid call)",
        f"- demote share **{demote_share:.3f}** of {total} rows "
        f"(gate: >= {MIN_DEMOTE_SHARE})",
        f"- provider errors {len(result['errors'])}, blind responses "
        f"{len(result['blind'])} (all kept)",
        "",
        "## The gate that actually decides this layer",
        "",
        f"- false demotions on rows the strong scorer called `domain=match`: "
        f"**{len(on_match_domain)}** (gate: <= {MAX_FALSE_DEMOTES_ON_MATCH_DOMAIN})"
        + (f" -> {on_match_domain}" if on_match_domain else ""),
        f"- false demotions on rows that were NOTIFIED: **{len(on_notified)}** "
        f"(gate: 0)" + (f" -> {on_notified}" if on_notified else ""),
        "",
        "A demotion is reversible and observable: the row stays `new` and searchable, "
        "and a deliberate operator pass still reaches it.",
        "",
        f"## False demotions ({fp})",
        "",
    ]
    for i in cells["fp"][:40]:
        row, detail = by_id[i], result["details"][i]
        lines.append(f"- {i} `{row['job_title']}` @ {row['company_name']} — "
                     f"domain={row['sol_domain']}, model said "
                     f"years={detail.get('stated_min_years')} "
                     f"rank={detail.get('stated_rank')}, "
                     f"clamped={detail.get('clamped_min_years')}")
    if len(cells["fp"]) > 40:
        lines.append(f"- ... and {len(cells['fp']) - 40} more")
    return "\n".join(lines) + "\n", passed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-corpus", action="store_true",
                    help="freeze the labeled rows out of the live DB (read-only)")
    ap.add_argument("--selftest", action="store_true",
                    help="hermetic gate-logic check, no model and no DB")
    ap.add_argument("--limit", type=int, default=0, help="evaluate the first N rows only")
    ap.add_argument("--db", default=str(ROOT / "db" / "applications.db"))
    args = ap.parse_args()

    if args.build_corpus:
        n = build_corpus(Path(args.db))
        print(f"wrote {n} rows to {GOLDEN.relative_to(ROOT)}")
        return 0
    if args.selftest:
        rows = load_corpus() if GOLDEN.exists() else []
        return selftest(rows)

    rows = load_corpus()
    if args.limit:
        rows = rows[:args.limit]
    # Same env vars run.main threads into the production screener, so the eval and the
    # pipeline cannot silently run different models or context windows.
    model = os.environ.get("OLLAMA_MODEL") or run.DEFAULT_OLLAMA_MODEL
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX") or 8192)
    host = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    import requests
    extract = make_ollama_extract(http=requests, ollama_host=host, model=model,
                                  num_ctx=num_ctx)
    result = evaluate(rows, extract, num_ctx)
    text, passed = report(rows, result, model, num_ctx)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"(report written to {OUT.relative_to(ROOT)})")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
