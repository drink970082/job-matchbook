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
import re
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


# Control keys must not collide with any verdict key, or the prompt teaches the labeller
# to write a wrong label. They did: the skip key was `s`, which is also SENIORITY's
# `too_senior`, so following the prompt silently appended `too_senior` — flushed at once,
# never re-offered (labelled ids are skipped on the next run), and a wrong human label is
# worse than no label at all. Non-alphabetic by construction so no future verdict can
# reach them; the assert makes a collision a startup error rather than bad data.
SKIP_KEY, QUIT_KEY = "-", "/"
assert not (set(SENIORITY) | set(DOMAIN)) & {SKIP_KEY, QUIT_KEY}, "control key collides"


def ask(prompt: str, options: dict) -> str | None:
    menu = "  ".join(f"[{k}] {v}" for k, v in options.items())
    while True:
        raw = input(f"{prompt}\n  {menu}\n"
                    f"  [{SKIP_KEY}] skip this row   [{QUIT_KEY}] save & quit > ").strip().lower()
        if raw == QUIT_KEY:
            return None
        if raw == SKIP_KEY:
            return "SKIP"
        if raw in options:
            return options[raw]
        print(f"  ? pick one of: {' '.join(list(options) + [SKIP_KEY, QUIT_KEY])}")


SHEET = EVAL / "golden_to_label.md"
# Enough JD to judge seniority and domain without turning the sheet into a novel. The
# fit scorer still sees the FULL description at eval time — this cap is for the human.
SHEET_JD_CHARS = 2200


def emit_sheet(conn, todo) -> int:
    """Write a fill-in sheet: one block per posting, blind, with blank label lines.

    Same corpus and same blindness as the interactive path — the frame is read for ids
    and bands only, and every displayed field comes from the DB — but it can be filled
    offline, in any editor, in any order, over several sittings.
    """
    out = [
        "# Score golden set — fill in the labels\n",
        f"\n{len(todo)} postings, ordered `near` first (the band that actually separates ",
        "models, so a partial fill is still useful). Fill `seniority:` and `domain:` on ",
        "each block; leave a block blank to skip it. `note:` is optional.\n",
        "\nWhen done (or part-done): `PYTHONPATH=. python3 tools/label_golden.py --ingest`\n",
        f"\n- seniority: {' | '.join(SENIORITY.values())}",
        f"\n- domain: {' | '.join(DOMAIN.values())}\n",
        "\n**The Sol verdicts are deliberately absent.** Seeing them would make these ",
        "labels agree with Sol by construction, which is the circularity the human set ",
        "exists to escape.\n",
    ]
    for n, (pid, band) in enumerate(todo, 1):
        row = conn.execute(
            "SELECT job_title, company_name, location, description "
            "FROM job_postings WHERE id=?", (pid,)).fetchone()
        if row is None:
            continue
        jd = (row["description"] or "").strip()
        out.append(f"\n\n---\n\n## [{n}/{len(todo)}] id {pid}  ·  band {band}\n")
        out.append(f"\n**{row['company_name']} — {row['job_title']}**  \n")
        out.append(f"location: {row['location'] or '—'}\n")
        out.append(f"\n```\n{jd[:SHEET_JD_CHARS]}")
        out.append("\n[... truncated for the sheet; the scorer sees the whole JD ...]"
                   if len(jd) > SHEET_JD_CHARS else "")
        out.append("\n```\n")
        out.append(f"\nseniority: \ndomain: \nnote: \n")
    SHEET.write_text("".join(out))
    print(f"wrote {len(todo)} blocks -> {SHEET}")
    return 0


def ingest_sheet(conn) -> int:
    """Read the filled sheet back into golden.jsonl. Blocks left blank are skipped."""
    if not SHEET.exists():
        print(f"missing {SHEET} — run --emit first", file=sys.stderr)
        return 1
    done = _labelled_ids()
    text = SHEET.read_text()
    blocks = re.split(r"^## \[\d+/\d+\] id (\d+)\s+·\s+band (\w+)\s*$", text, flags=re.M)
    written = bad = 0
    with GOLDEN.open("a") as fh:
        for i in range(1, len(blocks) - 2, 3):
            pid, band, body = int(blocks[i]), blocks[i + 1], blocks[i + 2]
            sen = (re.search(r"^seniority:[^\S\n]*(\S*)[^\S\n]*$", body, re.M) or [None, ""])[1].strip()
            dom = (re.search(r"^domain:[^\S\n]*(\S*)[^\S\n]*$", body, re.M) or [None, ""])[1].strip()
            note = (re.search(r"^note:[^\S\n]*(.*)$", body, re.M) or [None, ""])[1].strip()
            if not sen and not dom:
                continue                     # untouched block = skip, not an error
            if sen not in SENIORITY.values() or dom not in DOMAIN.values():
                print(f"! id={pid}: bad label {sen!r}/{dom!r} — skipped", file=sys.stderr)
                bad += 1
                continue
            if pid in done:
                continue                     # already labelled; never double-write
            row = conn.execute(
                "SELECT job_title, company_name, location, description "
                "FROM job_postings WHERE id=?", (pid,)).fetchone()
            if row is None:
                print(f"! id={pid}: gone from the DB — skipped", file=sys.stderr)
                continue
            fh.write(json.dumps({
                "id": pid,
                "band": "keep" if (sen == "match" and dom == "match")
                        else ("near" if dom == "adjacent" else "skip"),
                "hard": False,
                "note": note or f"{row['company_name']} {(row['job_title'] or '')[:60]}",
                "seniority": sen, "domain": dom,
                "posting": {"job_title": row["job_title"],
                            "company_name": row["company_name"],
                            "description": row["description"],
                            "location": row["location"]},
            }) + "\n")
            written += 1
    print(f"ingested {written} labelled rows"
          + (f" ({bad} rejected for a bad label value)" if bad else ""))
    print(f"golden.jsonl now has {len(_labelled_ids())} rows")
    return 0


def _labelled_ids() -> set:
    if not GOLDEN.exists():
        return set()
    return {json.loads(l)["id"] for l in GOLDEN.read_text().splitlines()
            if l.strip() and "id" in json.loads(l)}


def main() -> int:
    if not FRAME.exists():
        print(f"missing {FRAME} — run tools/expand_golden.py first", file=sys.stderr)
        return 1
    conn = sqlite3.connect(DB, uri=True)
    conn.row_factory = sqlite3.Row
    if "--ingest" in sys.argv:
        return ingest_sheet(conn)
    done = _labelled_ids()
    frame = [json.loads(l) for l in FRAME.read_text().splitlines() if l.strip()]
    # Take ids and bands ONLY. Every other field in the frame is a Sol verdict.
    todo = [(r["id"], r["band"]) for r in frame if r["id"] not in done]
    todo.sort(key=lambda t: (BAND_ORDER.index(t[1]) if t[1] in BAND_ORDER else 9, t[0]))

    if "--emit" in sys.argv:
        # Default to the DISCRIMINATING bands only. `skip` is 74% of the frame and every
        # model gets those right, so labelling them costs hours and buys no separating
        # power; `--emit-all` is there if a negative-class check is ever wanted.
        rows = todo if "--emit-all" in sys.argv else [t for t in todo if t[1] != "skip"]
        return emit_sheet(conn, rows)

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
