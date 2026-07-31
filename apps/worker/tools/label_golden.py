"""BLIND, resumable labelling of `eval/golden.jsonl` — the human fit-verdict golden set.

WHY this exists: the set is 23 rows, and the standing `gpt-5.6-terra` rejection rests on it
(terra 76% gate agreement vs sol's 86%). On 23 rows that gap is about TWO rows — inside the
noise the set itself carries — so the comparison cannot separate the models. ~120 rows is
where it starts to: with paired verdicts you are really counting the rows where two models
DISAGREE, and at ~15% discordance 120 rows yields ~18 of them. 23 yields ~3.

Candidates come from `eval/golden_expanded.jsonl` (built by `expand_golden.py`), drawn from
the bands where models actually diverge. 367 of those 499 rows are `domain=mismatch` and
every model gets them right, so labelling them buys nothing.

**BLIND BY CONSTRUCTION, and that is the whole point.** The candidate rows carry Sol's own
verdicts and a `note` built from them. If those are on screen while you label, the new
labels inherit Sol's bias and the expanded set measures agreement-with-Sol wearing a human
costume — which is the exact circularity the human set exists to escape. This tool reads
the candidate file ONLY for ids and re-reads every displayed field from the DB.

Read-only on the DB. Appends to `golden.jsonl`, never rewrites it, and skips ids already
present — so a 2-3 hour sitting splits across as many sessions as you like.
"""
import json
import sqlite3
import sys
import textwrap
from pathlib import Path

DB = "file:/home/halcyon/root/ats/db/applications.db?mode=ro"
EVAL = Path(__file__).resolve().parents[1] / "eval"
GOLDEN = EVAL / "golden.jsonl"
FRAME = EVAL / "golden_expanded.jsonl"

# The production enums (ats_worker/score/prompts.py:33,42). `too_senior` never appears in
# the current corpus but is a legal verdict, so it stays offerable — a golden set that
# cannot express a verdict the model can return would score that answer wrong by omission.
SENIORITY = {"m": "match", "j": "too_junior", "s": "too_senior"}
DOMAIN = {"m": "match", "a": "adjacent", "x": "mismatch"}
# Order matters: `near` is the band the notify gate turns on, so it is labelled first and a
# short sitting still yields the rows that decide the comparison.
BAND_ORDER = ["near", "keep", "skip"]


def ask(prompt: str, options: dict) -> str | None:
    menu = "  ".join(f"[{k}] {v}" for k, v in options.items())
    while True:
        raw = input(f"{prompt}\n  {menu}\n  (s=skip row, q=save & quit) > ").strip().lower()
        if raw in ("q", "quit"):
            return None
        if raw == "skip":
            return "SKIP"
        if raw in options:
            return options[raw]
        print("  ? pick one of the letters above.")


def main() -> int:
    if not FRAME.exists():
        print(f"missing {FRAME} — run tools/expand_golden.py first", file=sys.stderr)
        return 1
    done = {json.loads(l)["id"] for l in GOLDEN.read_text().splitlines()
            if l.strip() and "id" in json.loads(l)} if GOLDEN.exists() else set()
    frame = [json.loads(l) for l in FRAME.read_text().splitlines() if l.strip()]
    # Take ids and bands ONLY. Every other field in the frame is a Sol verdict.
    todo = [(r["id"], r["band"]) for r in frame if r["id"] not in done]
    todo.sort(key=lambda t: (BAND_ORDER.index(t[1]) if t[1] in BAND_ORDER else 9, t[0]))

    conn = sqlite3.connect(DB, uri=True)
    conn.row_factory = sqlite3.Row
    print(f"{len(done)} already labelled · {len(todo)} to go "
          f"(order: {' -> '.join(BAND_ORDER)})\n")

    written = 0
    with GOLDEN.open("a") as fh:
        for n, (pid, band) in enumerate(todo, 1):
            row = conn.execute(
                "SELECT job_title, company_name, location, description "
                "FROM job_postings WHERE id=?", (pid,)).fetchone()
            if row is None:
                continue
            print("=" * 78)
            print(f"[{n}/{len(todo)}]  id {pid}")
            print(f"{row['company_name']} — {row['job_title']}")
            print(f"location: {row['location'] or '—'}")
            print("-" * 78)
            print(textwrap.fill((row["description"] or "").strip()[:2600], 78))
            print("-" * 78)

            sen = ask("SENIORITY — does this posting's bar fit the candidate?", SENIORITY)
            if sen is None:
                break
            if sen == "SKIP":
                continue
            dom = ask("DOMAIN — is this posting's field a target for this candidate?", DOMAIN)
            if dom is None:
                break
            if dom == "SKIP":
                continue
            note = input("  one-line note (why) > ").strip()

            fh.write(json.dumps({
                "id": pid,
                # Recomputed from the HUMAN verdicts just given, not carried from the frame.
                "band": "keep" if (sen == "match" and dom == "match")
                        else ("near" if dom == "adjacent" else "skip"),
                # `hard` makes a wrong notify decision a gate VIOLATION (score_eval's
                # hard_violation). Default false and promote by hand afterward, so a
                # bulk sitting cannot quietly inflate what the gate is allowed to fail on.
                "hard": False,
                "note": note or f"{row['company_name']} {(row['job_title'] or '')[:60]}",
                "seniority": sen,
                "domain": dom,
                # SELF-CONTAINED by construction. Storing only the id is what killed the
                # previous corpus: on 2026-07-31, 22 of its 23 rows named postings no
                # longer in the DB, the gate fell to ONE row, and it kept reporting PASS.
                # A hand-written label cannot be re-derived, so the posting has to travel
                # with it. `eval/` is gitignored, which is what makes this safe to store.
                "posting": {
                    "job_title": row["job_title"], "company_name": row["company_name"],
                    "description": row["description"], "location": row["location"],
                },
            }) + "\n")
            fh.flush()   # crash-safe: every answer is on disk before the next row renders
            written += 1

    print(f"\nwrote {written} new rows -> {GOLDEN}  (total {len(done) + written})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
