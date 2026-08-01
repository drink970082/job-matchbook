"""Merge two independent labellers into a golden set, and emit ONLY what needs a human.

Inputs: `eval/claude_labels.jsonl` and `eval/codex_labels.jsonl`, each
`{id, seniority, domain, confidence, why}`.

Routing:
  AGREE + both confident   -> accepted straight into `golden.jsonl`
  DIVERGE, or either `low`  -> written to `golden_review.md` for the operator

The split is the whole point. Two labellers agreeing on an obvious row adds nothing a
human would have added; two labellers disagreeing is precisely where a human judgement is
worth the minutes. And because the `near` band is where models diverge, this routes
attention at the rows that decide a model comparison rather than at the easy negatives.

**What this cannot do:** catch rows where both labellers are confidently wrong the same
way. Agreement is not correctness — it is only evidence that the row was not hard. Rows
accepted here are model-shaped labels in a set whose whole purpose is to be human-shaped,
which is a deliberate, bounded trade and is recorded on every row as `label_source`.
"""
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL = Path(__file__).resolve().parents[1] / "eval"
CLAUDE, CODEX = EVAL / "claude_labels.jsonl", EVAL / "codex_labels.jsonl"
GOLDEN, REVIEW = EVAL / "golden.jsonl", EVAL / "golden_review.md"
DB = f"file:{ROOT}/db/applications.db?mode=ro"
RANK = {"low": 0, "medium": 1, "high": 2}


def load(p: Path) -> dict:
    if not p.exists():
        return {}
    return {d["id"]: d for d in (json.loads(l) for l in p.read_text().splitlines() if l.strip())}


def main() -> int:
    a, b = load(CLAUDE), load(CODEX)
    both = sorted(set(a) & set(b))
    if not both:
        print("no overlapping ids yet", file=sys.stderr)
        return 1
    done = {json.loads(l)["id"] for l in GOLDEN.read_text().splitlines()
            if l.strip() and "id" in json.loads(l)} if GOLDEN.exists() else set()
    conn = sqlite3.connect(DB, uri=True)
    conn.row_factory = sqlite3.Row

    accepted, review = [], []
    for pid in both:
        ca, cb = a[pid], b[pid]
        agree = ca["seniority"] == cb["seniority"] and ca["domain"] == cb["domain"]
        # `low` from EITHER labeller sends the row to a human even on agreement: a
        # confident-looking consensus built on two shrugs is the failure this guards.
        unsure = min(RANK[ca["confidence"]], RANK[cb["confidence"]]) == 0
        (accepted if (agree and not unsure) else review).append((pid, ca, cb, agree, unsure))

    with GOLDEN.open("a") as fh:
        n = 0
        for pid, ca, cb, _, _ in accepted:
            if pid in done:
                continue
            row = conn.execute("SELECT job_title, company_name, location, description "
                               "FROM job_postings WHERE id=?", (pid,)).fetchone()
            if row is None:
                continue
            sen, dom = ca["seniority"], ca["domain"]
            fh.write(json.dumps({
                "id": pid,
                "band": "keep" if (sen == "match" and dom == "match")
                        else ("near" if dom == "adjacent" else "skip"),
                "hard": False,
                # Recorded on the row, not just in a doc: a future reader must be able to
                # tell a consensus label from a human one without archaeology.
                "label_source": "claude+codex consensus",
                "note": f"{row['company_name']} {(row['job_title'] or '')[:55]} — "
                        f"both labellers agreed ({ca['confidence']}/{cb['confidence']})",
                "seniority": sen, "domain": dom,
                "posting": {"job_title": row["job_title"],
                            "company_name": row["company_name"],
                            "description": row["description"],
                            "location": row["location"]},
            }) + "\n")
            n += 1

    out = [f"# Review queue — {len(review)} of {len(both)} rows need you\n",
           f"\nAccepted without review: **{len(accepted)}** (both labellers agreed and "
           "neither was unsure).\n",
           "\nEach block below is either a DISAGREEMENT or carries a `low` confidence. "
           "Fill the `seniority:` / `domain:` lines to decide it; leave blank to drop the "
           "row from the corpus entirely.\n",
           "\n- seniority: match | too_junior | too_senior\n- domain: match | adjacent | mismatch\n"]
    for pid, ca, cb, agree, unsure in review:
        row = conn.execute("SELECT job_title, company_name, location, description "
                           "FROM job_postings WHERE id=?", (pid,)).fetchone()
        if row is None:
            continue
        why = "DISAGREE" if not agree else f"low confidence ({ca['confidence']}/{cb['confidence']})"
        out.append(f"\n\n---\n\n## id {pid} — {why}\n")
        out.append(f"\n**{row['company_name']} — {row['job_title']}**  \nlocation: "
                   f"{row['location'] or '—'}\n")
        out.append(f"\n| labeller | seniority | domain | conf |\n|---|---|---|---|\n")
        out.append(f"| claude | {ca['seniority']} | {ca['domain']} | {ca['confidence']} |\n")
        out.append(f"| codex  | {cb['seniority']} | {cb['domain']} | {cb['confidence']} |\n")
        out.append(f"\n- claude: {ca['why']}\n- codex: {cb['why']}\n")
        out.append(f"\n<details><summary>JD</summary>\n\n```\n"
                   f"{(row['description'] or '')[:1800]}\n```\n</details>\n")
        out.append("\nseniority: \ndomain: \n")
    REVIEW.write_text("".join(out))

    print(f"compared {len(both)} rows")
    print(f"  accepted (agree + confident): {len(accepted)}  -> appended {n} to golden.jsonl")
    print(f"  NEEDS REVIEW:                 {len(review)}  -> {REVIEW}")
    print(f"    disagreements: {sum(1 for r in review if not r[3])}")
    print(f"    low confidence: {sum(1 for r in review if r[3] and r[4])}")
    print("\nagreement by axis:")
    print(f"  seniority: {sum(1 for p in both if a[p]['seniority']==b[p]['seniority'])}/{len(both)}")
    print(f"  domain:    {sum(1 for p in both if a[p]['domain']==b[p]['domain'])}/{len(both)}")
    print("  claude conf:", dict(Counter(a[p]['confidence'] for p in both)))
    print("  codex conf: ", dict(Counter(b[p]['confidence'] for p in both)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
