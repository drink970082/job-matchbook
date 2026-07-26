#!/usr/bin/env python3
"""Sponsorship gate: diff the quote-grounded screen against the old phrase list over
already-scored rows, so only the DISAGREEMENTS need hand-labeling.

Agreements are free labels; disagreements are the candidates for a three-class
hand-label (no-sponsorship / offers / silent). Reports recall and the precision risk
that quote-grounding does NOT close: misclassification, where the model quotes
real-but-irrelevant text.

Usage:
    PYTHONPATH=apps/worker python3 tools/sponsor_diff.py --db path/to.db [--limit N]

Read-only against the DB. Spends screen calls on whatever SCREEN_BACKEND is set
(free on the default ollama).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "worker"))

import requests  # noqa: E402

from ats_worker import db, run  # noqa: E402
from ats_worker.score.screen import (NO_SPONSOR_PHRASES, _quote_in,  # noqa: E402
                                     _quote_on_topic)


def _phrase_hit(description: str) -> bool:
    text = " ".join((description or "").lower().split())
    return any(p in text for p in NO_SPONSOR_PHRASES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="apps/web/prisma/applications.db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--backend", default=os.environ.get("SCREEN_BACKEND", "ollama"))
    ap.add_argument("--out", default="sponsor_diff.json")
    args = ap.parse_args()

    conn = db.connect(args.db)
    rows = [dict(r) for r in conn.execute(
        "SELECT id, job_title, company_name, description FROM job_postings "
        "WHERE pipeline_status IN ('scored','notified','discarded') "
        "AND LENGTH(TRIM(description)) > 200 ORDER BY id").fetchall()]
    if args.limit:
        rows = rows[:args.limit]

    extract = run.make_screener(args.backend, env=os.environ, http=requests)
    if extract is None:
        print("backend 'none' has no LLM check to diff", file=sys.stderr)
        return 2

    agree = disagree = 0
    out = []
    suppressed = []
    from ats_worker.score.prompts import SCREEN_SCHEMA, _candidate_block, _job_block
    from ats_worker.prompts import SCREEN_HEADER
    checklist = _candidate_block({"work_authorization": "needs visa sponsorship"})

    for row in rows:
        desc = row["description"] or ""
        try:
            data = extract(SCREEN_HEADER + checklist + "\n" + _job_block(row, 16384),
                           SCREEN_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            print(f"id={row['id']} screen failed: {exc}", file=sys.stderr)
            continue
        quote = ((data.get("screen") or {}).get("authorization") or {}).get(
            "no_sponsorship_quote")
        grounded = _quote_in(quote, desc)
        llm = grounded and _quote_on_topic(quote)
        phrase = _phrase_hit(desc)
        # A row the RELEVANCE gate suppressed is the new residual, and it agrees with the
        # phrase list (both False) — so without this it would be counted as a free label
        # and never written down, leaving the tool blind to the very failure the gate
        # introduces. Emit it explicitly instead.
        if grounded and not llm:
            suppressed.append({"id": row["id"], "company": row["company_name"],
                               "title": row["job_title"], "quote": quote,
                               "verdict": "gate_suppressed", "label": None})
        if llm == phrase:
            agree += 1
            continue
        disagree += 1
        out.append({"id": row["id"], "company": row["company_name"],
                    "title": row["job_title"], "llm_says_no_sponsorship": llm,
                    "phrase_list_says_no_sponsorship": phrase, "quote": quote,
                    "label": None})  # hand-fill: no-sponsorship | offers | silent

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    if suppressed:
        with open(args.out.replace(".json", "-suppressed.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(suppressed, fh, indent=2)
    print(f"{len(rows)} rows: {agree} agree (free labels), {disagree} disagree")
    if suppressed:
        print(f"{len(suppressed)} row(s) grounded but suppressed by the relevance gate "
              f"-> {args.out.replace('.json', '-suppressed.json')} (the gate's own "
              f"residual: a wrong suppression here is a MISSED disqualification)")
    print(f"hand-label the {disagree} rows in {args.out} (label: "
          f"no-sponsorship | offers | silent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
