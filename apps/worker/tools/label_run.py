#!/usr/bin/env python3
"""Blind K=1 labeler: score a corpus on one backend and write one label per row.

DELIBERATELY NOT `score_eval.py`. That tool is a GATE — K=3 draws, agreement and
flip-rate against hand-written labels, PASS/FAIL. This one is a LABELER: one draw per
row, no reference labels read, no verdict rendered. Conflating the two is how the
corpora rotted the first time (a machine-labelled corpus was measured against the same
machine that wrote it — see `expand_golden.py`'s docstring and BACKLOG).

BLIND BY CONSTRUCTION: the corpus file's own `seniority`/`domain`/`note` fields are
never read, so a prior label — the operator's included — cannot leak into the prompt or
bias the run. Only `id` is taken from the corpus.

Usage:
    SCORE_BACKEND=claude-code PYTHONPATH=. python3 tools/label_run.py \\
        --corpus eval/golden_expanded.jsonl --out eval/claude_code_labels.jsonl \\
        [--reachable-only] [--limit N] [--workers 4]

Resumable: rows already present in --out are skipped, so a 287-row run that dies at 200
resumes at 200 rather than re-spending the first 200 calls.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/worker"))

from ats_worker import run  # noqa: E402
from ats_worker import score  # noqa: E402
from ats_worker.fetch import prefilter_postings  # noqa: E402

DB = ROOT / "db/applications.db"
COLS = ("job_title", "company_name", "description", "location")


def build_scorer(backend: str, model: str, profile: str, env: dict):
    """Same three-way split as `run.make_scorer`, kept explicit here so a labeling run
    can never fall through to the METERED backend by accident."""
    if backend == "codex":
        return score.make_codex_scorer(model, profile=profile)
    if backend == "claude-code":
        return score.make_claude_cli_scorer(model, profile=profile)
    if backend == "claude-api":
        return score.make_claude_scorer(env["ANTHROPIC_API_KEY"], model,
                                        profile=profile, max_tokens=8192)
    raise SystemExit(f"unknown SCORE_BACKEND {backend!r} (want one of {run.SCORE_BACKENDS})")


def load_ids(corpus: Path) -> list[int]:
    """Ids only — see the module docstring on blindness."""
    return [int(json.loads(l)["id"])
            for l in corpus.read_text().splitlines() if l.strip()]


def reachable(conn, ids: list[int], cfg_path: Path) -> list[int]:
    """Drop ids the shipped title filters would refuse at fetch time.

    A row the pipeline can no longer produce is not worth a paid call: labeling it buys
    a verdict on traffic that will never arrive. Driven through the real
    `prefilter_postings` rather than a reimplementation of its rule.
    """
    cfg = run.config_mod.load_config(cfg_path.read_text())
    rows = conn.execute(
        f"SELECT id, job_title FROM job_postings WHERE id IN ({','.join('?' * len(ids))})",
        ids).fetchall()
    titles = {r[0]: r[1] for r in rows}
    kept = prefilter_postings(
        [{"job_title": titles.get(i) or "", "posted_at": None, "id": i} for i in ids],
        title_filter=cfg.title_filter, title_exclude=cfg.title_exclude)
    return [p["id"] for p in kept]


def resume_done(out: Path) -> tuple[set, int]:
    """`(ids to skip, count of errored rows that will be retried)`.

    SUCCESSES only count as done. An `error` row must not: the failure that produces
    most of them is a quota window closing mid-run, and treating those ids as finished
    would permanently skip exactly the rows the resume path exists to pick up.
    Re-labeling appends a second row for the id; readers key by id and take the last,
    so the good row wins.
    """
    if not out.exists():
        return set(), 0
    rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    done = {r["id"] for r in rows if not r.get("error")}
    return done, len(rows) - len(done)


def label_one(score_fit, resumes, posting) -> dict:
    """One draw. Returns the flattened label row, or an `error` row — a backend failure
    must be visible in the output, not a silently missing id."""
    try:
        card = score._normalize_score(score_fit([posting], resumes)[0])
    except Exception as exc:  # noqa: BLE001 - any backend failure is data, not a crash
        return {"id": posting["id"], "error": f"{type(exc).__name__}: {exc}"}
    a = card.get("assessment") or {}
    return {
        "id": posting["id"],
        "seniority": (a.get("seniority") or {}).get("verdict"),
        "domain": (a.get("domain") or {}).get("verdict"),
        "score": card.get("score"),
        "insufficient_context": card.get("insufficient_context"),
        "seniority_note": (a.get("seniority") or {}).get("note"),
        "domain_note": (a.get("domain") or {}).get("note"),
        "summary": a.get("summary"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--reachable-only", action="store_true",
                    help="drop ids the shipped title_filter/title_exclude would refuse")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4,
                    help="concurrent calls. Quota-neutral: same spend, less wall-clock")
    ap.add_argument("--config", type=Path, default=ROOT / "apps/worker/config.yaml")
    args = ap.parse_args()

    backend = os.environ.get("SCORE_BACKEND", run.DEFAULT_SCORE_BACKEND)
    model = {"codex": run.DEFAULT_CODEX_SCORE_MODEL,
             "claude-code": run.DEFAULT_CLAUDE_CODE_SCORE_MODEL,
             "claude-api": run.DEFAULT_ANTHROPIC_SCORE_MODEL}.get(backend)
    env = run.load_env(str(ROOT / "apps/worker/.env"))
    resumes, profile = run.load_resumes(str(ROOT / "apps/worker/resume"))
    score_fit = build_scorer(backend, model, profile, env)

    ids = load_ids(args.corpus)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    if args.reachable_only:
        before = len(ids)
        ids = reachable(conn, ids, args.config)
        print(f"reachable: {len(ids)} of {before} "
              f"({before - len(ids)} refused by the shipped title filters)",
              file=sys.stderr)

    done, failed = resume_done(args.out)
    if done or failed:
        print(f"resuming: {len(done)} labeled"
              + (f", {failed} errored rows will be retried" if failed else ""),
              file=sys.stderr)
    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[:args.limit]

    rows = conn.execute(
        f"SELECT id, {', '.join(COLS)} FROM job_postings "
        f"WHERE id IN ({','.join('?' * len(todo))})", todo).fetchall() if todo else []
    postings = {r[0]: {"id": r[0], **dict(zip(COLS, r[1:]))} for r in rows}
    missing = [i for i in todo if i not in postings]
    if missing:
        print(f"! {len(missing)} ids not in the DB, skipped: {missing[:5]}", file=sys.stderr)
    todo = [i for i in todo if i in postings]

    print(f"labeling {len(todo)} rows on {backend} ({model}), {args.workers} workers",
          file=sys.stderr)
    started = time.time()
    written = errors = 0
    with args.out.open("a") as fh, ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(lambda i: label_one(score_fit, resumes, postings[i]), todo):
            fh.write(json.dumps(row) + "\n")
            fh.flush()  # a killed run keeps everything it paid for
            written += 1
            errors += 1 if row.get("error") else 0
            if written % 10 == 0 or written == len(todo):
                rate = written / max(time.time() - started, 1) * 60
                print(f"  {written}/{len(todo)}  {errors} errors  {rate:.1f}/min",
                      file=sys.stderr, flush=True)
    conn.close()
    print(f"wrote {written} rows ({errors} errors) -> {args.out}", file=sys.stderr)
    return 1 if errors and errors == written else 0


if __name__ == "__main__":
    raise SystemExit(main())
