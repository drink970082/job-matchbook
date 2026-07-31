"""Find corpus candidates that break the CLEARANCE TAUTOLOGY in screen_golden.jsonl.

The problem, measured 2026-07-31: of the 24 clearance rows, 4 are golden
`requires_clearance: true` and 20 are golden `false` — and **none of the 20 carries a
clearance token**. So `_check_clearance` short-circuits on its evidence floor for every
one of them, and `judge` excludes the 4 `true` rows from `false_disq` by construction.
No row can produce a clearance false disqualification, for any model. The half of the
eval that exists because the clearance check once ran 83% wrong is the half it cannot see.

What fixes it is the row this tool looks for: a JD that **names a clearance it does not
require**. "Ability to obtain a clearance is a plus", "no clearance required", "clearance
preferred but not required", or a title/body where "security" is the engineering domain.
Those reach the model with real evidence, so a model that over-reads them produces a false
disqualification the gate can finally catch.

Read-only on the DB. Emits candidates + the evidence window for human confirmation — it
labels NOTHING. The corpus is human-labelled by design (`_readme`: "LABELS ARE
PER-REQUIREMENT JD FACTS"), and a tool-labelled row would reintroduce the exact circularity
the human set exists to avoid.

Excerpt window is +/-780 characters centred on the match, NOT the `_readme`'s "+/-1
sentence" recipe. That is deliberate: the 2026-07-29 repair found `sponsorship_snippets`
could not rebuild these, because a period-free bullet block is ONE sentence, so the window
returns the whole JD and the 1600-cap then cuts the evidence back off. The character window
is what actually worked.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

DB = "file:/home/halcyon/root/ats/db/applications.db?mode=ro"
CORPUS = Path(__file__).resolve().parents[1] / "eval" / "screen_golden.jsonl"
OUT = CORPUS.with_name("clearance_candidates.md")
HALF_WINDOW = 780
CAP = 1600

# The floor's own vocabulary — a candidate is only useful if it TRIPS this, otherwise the
# short-circuit swallows it exactly like the 20 rows already in the corpus.
TOKENS = re.compile(r"clearance|ts/sci|top secret|\bsecret\b|polygraph|\bdod\b|security\+",
                    re.I)
# Phrases that suggest the bar is soft or absent — i.e. a likely golden `false`, which is
# the class the corpus has none of. Ranked first; the human still decides.
SOFT = re.compile(r"not required|no clearance|preferred|is a plus|nice to have|"
                  r"ability to obtain|able to obtain|eligible to obtain|willing to obtain|"
                  r"or ability to|not necessary", re.I)


def window(text: str, m: re.Match) -> str:
    lo = max(0, m.start() - HALF_WINDOW)
    excerpt = text[lo:m.end() + HALF_WINDOW].strip()
    return excerpt[:CAP] + (" [...]" if len(excerpt) > CAP else "")


def main() -> int:
    # 84 lines = 1 `_readme` + 83 rows, but only 78 distinct ids: a posting may appear
    # twice, drawn once per requirement (the `_readme` allows it — "each row asserts only
    # the requirement it was drawn for"). Excluding by POSTING id is therefore slightly
    # conservative — a row already in for `degree` could legitimately also serve as a
    # `clearance` row — but it keeps one posting from carrying two excerpts of itself.
    parsed = [json.loads(l) for l in CORPUS.read_text().splitlines() if l.strip()]
    seen = {r["id"] for r in parsed if "id" in r}
    conn = sqlite3.connect(DB, uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, job_title, company_name, description,
               json_extract(score_detail,'$.disqualification_reason') AS reason
          FROM job_postings
         WHERE description IS NOT NULL AND LENGTH(TRIM(description)) >= 400
    """).fetchall()

    soft, hard = [], []
    for r in rows:
        if r["id"] in seen:
            continue
        m = TOKENS.search(r["description"] or "")
        if not m:
            continue
        ex = window(r["description"], m)
        # A row the screen already discarded FOR clearance is a golden `true` candidate;
        # the corpus has 4 of those and needs `false` ones, so they sort last.
        already = "clearance" in (r["reason"] or "").lower()
        (hard if already else soft if SOFT.search(ex) else hard).append((r, ex, already))

    lines = [f"# Clearance corpus candidates — {len(soft)} likely `false`, "
             f"{len(hard)} other\n",
             "The corpus has **zero** golden-`false` rows carrying a clearance token, which "
             "is why that half of `make eval-screen` cannot fail. Confirm each row below by "
             "reading the excerpt, then add it to `eval/screen_golden.jsonl` as\n",
             '`{"id": N, "drawn_for": "clearance", "gate": true, "title": "...", '
             '"company": "...", "excerpt": "...", "facts": {"requires_clearance": false}, '
             '"note": "why"}`\n',
             "**Label the JD fact, not the verdict** — 'does this JD require a clearance?', "
             "never 'is this posting disqualified?'. Set `gate: false` if genuinely "
             "ambiguous; those are reported but cannot fail the gate.\n"]
    for label, group in (("Likely golden `false` — review these first", soft),
                         ("Other clearance-token rows", hard)):
        lines.append(f"\n## {label}\n")
        for r, ex, already in group[:60]:
            flag = "  *(already clearance-discarded — golden `true` candidate)*" if already else ""
            lines.append(f"\n### id {r['id']} — {r['company_name']} — {r['job_title']}{flag}\n")
            lines.append(f"```\n{ex}\n```\n")
    OUT.write_text("".join(lines))

    print(f"corpus rows already present: {len(seen)}")
    print(f"likely golden `false` (soft/absent bar): {len(soft)}")
    print(f"other clearance-token rows:              {len(hard)}")
    print(f"\nwrote {OUT}")
    print("Nothing was labelled — confirm each row by hand before it enters the corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
