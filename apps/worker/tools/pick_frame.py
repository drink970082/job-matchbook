"""Pick the stratified sampling frame the rebuilt fit corpus is labelled from.

WHY A FRESH PICK RATHER THAN A RE-LABEL. `golden.jsonl` is 15 keep / 54 near / 2 skip
after the dead rows — a gate whose job is to stop false keeps holding almost no false-keep
evidence, which is the same shape as both recorded "gate that cannot fail" incidents.
Composition is not a labelling problem, so re-labelling cannot fix it. Four things this
gets that a re-label structurally cannot:

1. **Deliberate stratification.** Balanced allocation across the six live
   domain x seniority cells, so the thin classes are over-weighted relative to their
   population share and the fat `mismatch` cells still appear — a corpus without rows
   today's system gets RIGHT can detect improvements but not regressions.
2. **Inline posting text from row one.** The absence of it is exactly why 22 rows of
   `golden.jsonl` died when their DB rows went away; `screen_golden.jsonl` carried its
   text and survived the same churn.
3. **A frozen, hashed profile.** Every row records the four provenance hashes it was
   picked under, so an edit to the vocabulary or the résumés says which labels expired
   instead of silently serving stale ones.
4. **Room for graded relevance.** The label file NDCG@K needs is written against this
   frame; binary keep/skip cannot support it.

A DELIBERATE THIN-JD STRATUM. `insufficient_context` is a field the extractor must set,
and a frame with no thin postings could never test it — a metric that cannot fail is the
failure mode this repo has now hit twice. So a small `thin_jd` cell is picked on purpose.

The 64 answers in `eval/golden_review_answers.json` are attached as `review_note` where
the id is drawn. Their value is the NOTE, not the enum — row 662 reads "pure quant
research and not engineering oriented sits anti-target", i.e. a human judgment the
three-way enum flattened. They are context for the labeller, never truth.

Read-only on the DB, deterministic given `--seed`, and it overwrites nothing: an existing
--out is an error, because silently replacing the frame a corpus was labelled against
would orphan every label.

USAGE
    PYTHONPATH=. python3 tools/pick_frame.py --out eval/frame_extraction.jsonl
    PYTHONPATH=. python3 tools/pick_frame.py --size 300 --per-company 2 --dry-run
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ats_worker.config import load_config  # noqa: E402
from ats_worker.run import load_resumes  # noqa: E402
from ats_worker.score.fit_profile import provenance  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DB = f"file:{ROOT}/db/applications.db?mode=ro"
WORKER = Path(__file__).resolve().parents[1]
REVIEW_ANSWERS = WORKER / "eval" / "golden_review_answers.json"

# Below this the JD is a stub and the extractor is expected to say so. It matches
# `db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH` in intent; it is repeated rather than imported
# because this is a corpus-shape choice, not the production gate.
THIN_JD_MAX = 200
# One deliberate thin cell, small: enough to make `insufficient_context` measurable,
# not enough to spend the labelling budget on stubs.
THIN_JD_QUOTA = 10
LENGTH_BUCKETS = ((1000, "short"), (3000, "medium"), (6000, "long"), (10**9, "very_long"))


def _bucket(length: int) -> str:
    return next(name for edge, name in LENGTH_BUCKETS if length < edge)


def _load_rows() -> list[dict]:
    """Every posting that carries a description, with today's verdicts where it has them.

    Screen-discarded rows are included: the new extractor sits at the same pipeline
    position as the fit call, and a corpus made only of rows the fit call already saw
    inherits the screen's blind spots along with its judgments.
    """
    with sqlite3.connect(DB, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        raw = conn.execute(
            "SELECT id, source, company_name, job_title, location, description, score, "
            "       score_detail, pipeline_status "
            "FROM job_postings WHERE TRIM(COALESCE(description,'')) <> ''").fetchall()
    rows = []
    for record in raw:
        row = dict(record)
        detail = {}
        if row["score_detail"]:
            try:
                detail = json.loads(row["score_detail"])
            except json.JSONDecodeError:
                detail = {}
        assessment = detail.get("assessment") or {}
        row["domain"] = (assessment.get("domain") or {}).get("verdict")
        row["seniority"] = (assessment.get("seniority") or {}).get("verdict")
        row["length"] = len(row["description"].strip())
        rows.append(row)
    return rows


def _stratum(row: dict) -> str:
    """The cell a row belongs to. `unscored` is one cell, not a hole: those rows are the
    intake the paid scorer has never reached, and they are the majority of the backlog."""
    if row["length"] < THIN_JD_MAX:
        return "thin_jd"
    if not row["domain"] or not row["seniority"]:
        return "unscored"
    return f"{row['domain']}/{row['seniority']}"


def _allocate(counts: dict, target: int) -> dict:
    """Balanced allocation: an equal share per stratum, with whatever a small stratum
    cannot fill redistributed to the ones that can.

    Balanced rather than proportional ON PURPOSE. Proportional sampling reproduces the
    population — 42% `mismatch/too_junior`, 6% `match/match` — and a corpus that mirrors
    the backlog spends its human budget on the easy majority while leaving single digits
    of evidence in the cells where the decisions are actually made.
    """
    quota = {name: 0 for name in counts}
    remaining, open_strata = target, [name for name, n in counts.items() if n]
    while remaining > 0 and open_strata:
        share = max(1, remaining // len(open_strata))
        progressed = False
        for name in list(open_strata):
            take = min(share, counts[name] - quota[name], remaining)
            if take <= 0:
                open_strata.remove(name)
                continue
            quota[name] += take
            remaining -= take
            progressed = True
            if quota[name] >= counts[name]:
                open_strata.remove(name)
            if remaining <= 0:
                break
        if not progressed:
            break
    return quota


def _draw(rows: list[dict], quota: int, per_company: int, rng: random.Random) -> list[dict]:
    """Draw `quota` rows spread across JD-length buckets and companies.

    Both spreads matter and for different reasons: length correlates with how much there
    is to extract (a 600-char stub and a 9k JD are different tasks), and one company's
    postings share a template, so an unspread draw can measure one employer's house style
    and call it a model comparison.
    """
    by_bucket: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_bucket[_bucket(row["length"])].append(row)
    for bucket in by_bucket.values():
        rng.shuffle(bucket)

    picked: list[dict] = []
    seen_company: collections.Counter = collections.Counter()
    order = sorted(by_bucket)
    deferred: list[dict] = []
    while len(picked) < quota and any(by_bucket[b] for b in order):
        for bucket in order:
            if len(picked) >= quota:
                break
            while by_bucket[bucket]:
                row = by_bucket[bucket].pop()
                company = (row["company_name"] or "").strip().lower()
                if per_company and seen_company[company] >= per_company:
                    deferred.append(row)  # only if the cap starves the cell
                    continue
                seen_company[company] += 1
                picked.append(row)
                break
    # A cap that cannot be met must not silently shrink the stratum — better a
    # concentrated cell, named in the report, than a quota quietly missed.
    while len(picked) < quota and deferred:
        picked.append(deferred.pop())
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(WORKER / "eval" / "frame_extraction.jsonl"))
    ap.add_argument("--size", type=int, default=250, help="target frame size (plan: 200-300)")
    ap.add_argument("--per-company", type=int, default=3,
                    help="soft cap per company inside a stratum (0 = off)")
    ap.add_argument("--seed", default="2026-08-03", help="makes the draw reproducible")
    ap.add_argument("--dry-run", action="store_true", help="print the composition, write nothing")
    ap.add_argument("--config", default=str(WORKER / "config.yaml"))
    ap.add_argument("--resume-dir", default=str(WORKER / "resume"))
    args = ap.parse_args()

    out_path = Path(args.out)
    if out_path.exists() and not args.dry_run:
        raise SystemExit(f"{out_path} exists. Replacing a frame orphans every label made "
                         "against it — move it aside deliberately if that is the intent.")

    cfg = load_config(args.config)
    if cfg.fit_profile is None or cfg.fit_profile.is_empty():
        raise SystemExit(f"{args.config} has no `fit_profile` block; the frame stamps the "
                         "vocabulary hash it was picked under.")
    resumes, profile_text = load_resumes(args.resume_dir)
    stamp = provenance(cfg.fit_profile, profile_text=profile_text, resumes=resumes)

    rows = _load_rows()
    by_stratum: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_stratum[_stratum(row)].append(row)

    # The thin cell is fixed and small; the rest of the budget is balanced across the
    # cells that carry real JDs.
    thin = by_stratum.pop("thin_jd", [])
    counts = {name: len(items) for name, items in by_stratum.items()}
    thin_quota = min(THIN_JD_QUOTA, len(thin))
    quotas = _allocate(counts, max(0, args.size - thin_quota))
    quotas["thin_jd"] = thin_quota
    by_stratum["thin_jd"] = thin

    rng = random.Random(args.seed)
    picked: list[dict] = []
    for name in sorted(quotas):
        if quotas[name]:
            for row in _draw(by_stratum[name], quotas[name], args.per_company, rng):
                picked.append({**row, "stratum": name})

    notes = {}
    if REVIEW_ANSWERS.exists():
        notes = json.loads(REVIEW_ANSWERS.read_text(encoding="utf-8"))

    print(f"population {len(rows)} postings -> frame {len(picked)}", file=sys.stderr)
    for name in sorted(quotas):
        print(f"  {name:26s} {quotas[name]:4d} of {len(by_stratum[name]):5d} available",
              file=sys.stderr)
    companies = collections.Counter((r["company_name"] or "").lower() for r in picked)
    seeded = sum(1 for r in picked if str(r["id"]) in notes)
    print(f"  {len(companies)} companies, top {companies.most_common(1)[0][1]} rows; "
          f"{seeded} row(s) carry an operator review note", file=sys.stderr)
    if args.dry_run:
        return 0

    header = {"kind": "frame_header", "seed": args.seed, "size": len(picked),
              "per_company_cap": args.per_company, "provenance": stamp,
              "strata": {name: quotas[name] for name in sorted(quotas) if quotas[name]},
              "population": len(rows)}
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for row in picked:
            note = notes.get(str(row["id"]))
            entry = {
                "id": row["id"], "stratum": row["stratum"], "provenance": stamp,
                # INLINE, always. The corpus must not depend on mutable DB state.
                "posting": {"job_title": row["job_title"], "company_name": row["company_name"],
                            "source": row["source"], "location": row["location"],
                            "description": row["description"]},
                # Today's verdicts, so a regression against the current system is
                # visible. Context for the labeller, never the label.
                "current": {"score": row["score"], "domain": row["domain"],
                            "seniority": row["seniority"], "status": row["pipeline_status"]},
            }
            if note:
                entry["review_note"] = note
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"wrote {len(picked)} row(s) to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
