"""Build an EXPANDED score corpus from rows Sol has already scored.

Deliberately a SEPARATE file from `eval/golden.jsonl`. The 23 rows there carry
HUMAN-curated labels with hand-written notes; these carry Sol's own verdicts as labels.
Mixing them would silently downgrade the authoritative gate to machine labels, which is
the same trap `seniority_eval.py` documents ("labels are the strong scorer's own
verdicts, NOT human labels").

Sampling is deliberately NOT uniform. A cheaper fit model fails where the decision is
close, so the rows that matter are the notify payoff set and the borderline band:
  - every NOTIFIED row (the ground truth that a human acted on)
  - every domain=match row (the notify gate's positive class)
  - every domain=adjacent row (the borderline the gate turns on)
  - a capped sample of the clear negatives, so the corpus is not all edge cases

Read-only on the DB. Writes to the scratchpad for review before anything is installed.
"""
import json
import sqlite3
from collections import Counter
from pathlib import Path

DB = "file:/home/halcyon/root/ats/db/applications.db?mode=ro"
HUMAN = Path("/home/halcyon/root/ats/apps/worker/eval/golden.jsonl")
# Writes into eval/, which is gitignored wholesale — these rows carry real company names
# and job titles from live postings, the same class of data that decision already covers.
# tools/ is tracked, so writing here instead would publish them.
OUT = HUMAN.with_name("golden_expanded.jsonl")
# The negative class is the one failure this corpus exists to catch: a cheaper model that
# inflates FALSE POSITIVES costs the operator junk notifications directly. 30 negatives
# cannot resolve a few percentage points of over-generation across 367 real ones, so the
# cap is high enough to keep the whole population. Kept as a knob rather than deleted:
# the stride sample is what makes a smaller corpus reviewable by hand.
MAX_CLEAR_NEGATIVES = 400

human_ids = {json.loads(l)["id"] for l in HUMAN.read_text().splitlines() if l.strip()}

conn = sqlite3.connect(DB, uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT id, job_title, company_name, pipeline_status, score, score_detail,
           LENGTH(TRIM(description)) AS dlen
      FROM job_postings
     WHERE json_extract(score_detail,'$.assessment.seniority.verdict') IS NOT NULL
       AND pipeline_status IN ('scored','notified')
       AND LENGTH(TRIM(description)) >= 200
     ORDER BY id
""").fetchall()

cand = []
for r in rows:
    a = json.loads(r["score_detail"]).get("assessment", {})
    sen = (a.get("seniority") or {}).get("verdict")
    dom = (a.get("domain") or {}).get("verdict")
    if not sen or not dom:
        continue
    cand.append({
        "id": r["id"], "title": r["job_title"], "company": r["company_name"],
        "seniority": sen, "domain": dom,
        "notified": r["pipeline_status"] == "notified",
        "score": r["score"],
        # The notify gate is a VERDICT predicate, so band follows the verdicts rather
        # than the number (score_eval.py:8 -- verdict agreement is the gate).
        "band": "keep" if (sen == "match" and dom == "match")
                else ("near" if dom == "adjacent" else "skip"),
        "in_human_set": r["id"] in human_ids,
    })

notified = [c for c in cand if c["notified"]]
match_dom = [c for c in cand if c["domain"] == "match" and not c["notified"]]
adjacent = [c for c in cand if c["domain"] == "adjacent"]
clear_neg = [c for c in cand if c["domain"] == "mismatch"]
# spread the negatives across the id range rather than taking the oldest N
step = max(1, len(clear_neg) // MAX_CLEAR_NEGATIVES)
sampled_neg = clear_neg[::step][:MAX_CLEAR_NEGATIVES]

picked, seen = [], set()
for group, why in ((notified, "notified — a human acted on this row"),
                   (match_dom, "domain=match — the notify gate's positive class"),
                   (adjacent, "domain=adjacent — the borderline the gate turns on"),
                   (sampled_neg, "domain=mismatch — clear negative, sampled across the id range")):
    for c in group:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        picked.append({
            "id": c["id"],
            "band": c["band"],
            "seniority": c["seniority"],
            "domain": c["domain"],
            "label_source": "sol",          # NOT a human label -- see module docstring
            "notified": c["notified"],
            "note": f"{c['company']} {c['title'][:60]} — {why}",
        })

OUT.write_text("\n".join(json.dumps(p) for p in picked) + "\n")

print(f"candidates with a Sol verdict: {len(cand)}")
print(f"  notified              {len(notified)}")
print(f"  domain=match (unnotified) {len(match_dom)}")
print(f"  domain=adjacent       {len(adjacent)}")
print(f"  domain=mismatch       {len(clear_neg)}  -> sampled {len(sampled_neg)}")
print(f"\nwrote {len(picked)} rows to {OUT.name}")
print("bands:", dict(Counter(p['band'] for p in picked)))
print("seniority:", dict(Counter(p['seniority'] for p in picked)))
print("domain:", dict(Counter(p['domain'] for p in picked)))
overlap = sum(1 for p in picked if p["id"] in human_ids)
print(f"overlap with the 23 human-labelled rows: {overlap}")
