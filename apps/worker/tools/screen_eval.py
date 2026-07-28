#!/usr/bin/env python
"""Hard-requirement accuracy eval for the SCREEN prompt — READ-ONLY, never writes the DB.

The gate `screen.txt` never had. `score.txt` cannot change without two consecutive
`tools/score_eval.py` PASS; the screen clauses shipped on inspection alone, and on
2026-07-27 that cost four days of a clearance check running 83% wrong with nothing to
surface it (no row is marked `failed`, and no eval existed).

Reuses the production wiring (`run.make_screener` -> `score.screen_posting` ->
`_screen_verdict`), draws each golden row K=3x, and judges the MAJORITY verdict for the
requirement that row was drawn for against a hand-labeled JD FACT.

WHAT IT GATES, and only this: **zero false disqualification.** A row whose golden fact
carries no bar for the eval candidate must never come back disqualified — in any draw,
not just the majority. That direction is the expensive one: a discarded posting is
reviewed by nobody, while a MISS costs one paid fit call and reaches the human. So
**recall is reported, never gated**, and so is flip rate.

Rows with `gate: false` are drawn and reported but excluded from the gate — their label
is genuinely ambiguous (see the corpus `_readme`), and a gate is worthless if it is
argued with.

The gate is meaningful only when eval-model == production-model, so the backend follows
`run.DEFAULT_SCREEN_BACKEND` (ollama / qwen3.5:4b — free). `SCREEN_BACKEND` A/Bs it.

Corpus: apps/worker/eval/screen_golden.jsonl — real postings, EXCERPTS only (the repo is
public). Its `_readme` carries the rebuild query and the labeling rules.

Run:  PYTHONPATH=. python3 tools/screen_eval.py            # LIVE (free: local Ollama)
      PYTHONPATH=. python3 tools/screen_eval.py --selftest # free, hermetic gate-logic check
      make eval-screen
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "worker"))
from ats_worker import run, score  # noqa: E402  (needs apps/worker on the path)

K = 3
GOLDEN = ROOT / "apps/worker/eval/screen_golden.jsonl"
OUT = ROOT / "apps/worker/eval/last_screen_run.md"

# The eval candidate. FIXED here rather than read from config.yaml: the golden labels are
# JD facts, and turning a fact into a verdict needs a stable constraint to compare against
# — reading the operator's live config would make the gate's meaning drift with it.
# `exclude_internships` is deliberately OFF: several corpus rows are intern postings, and
# the deterministic title gate would disqualify them before the requirement under test
# ever ran. `location` is likewise neutralized by the synthetic posting below.
CANDIDATE = {
    "highest_degree": "Master's",
    "work_authorization": "needs visa sponsorship",
    "security_clearance": "none",
}
# Every synthetic posting is Remote so the deterministic location gate always passes.
# Without this the gate would measure `resolve_location`, which has its own tests.
LOCATION = "Remote"


# --- turning a labeled JD FACT into "is this a bar for CANDIDATE?" ---------

def fact_is_a_bar(drawn_for: str, facts: dict) -> bool | None:
    """Does the labeled fact disqualify CANDIDATE? None = not assertable."""
    if drawn_for == "clearance":
        return bool(facts.get("requires_clearance"))
    if drawn_for == "degree":
        required = facts.get("required_degree")
        if required in (None, "unclear"):
            return None
        return score.screen._degree_rank(required) > score.screen._degree_rank(
            CANDIDATE["highest_degree"])
    if drawn_for == "sponsorship":
        label = facts.get("sponsorship")
        if label is None:
            return None
        return label == "refuses"
    return None


# The screen verdict key each requirement lands under in `out["screen"]`.
VERDICT_KEY = {"clearance": "clearance", "degree": "degree",
               "sponsorship": "authorization"}


def measured_bar(out: dict, drawn_for: str) -> bool:
    """Did the screen disqualify on THIS requirement? A requirement that recorded no
    verdict at all (a blind extraction) is not a disqualification — it is a miss."""
    entry = (out.get("screen") or {}).get(VERDICT_KEY[drawn_for])
    if not isinstance(entry, dict) or "pass" not in entry:
        return False
    return not entry["pass"]


def posting_of(row: dict) -> dict:
    return {"job_title": row["title"], "company_name": row["company"],
            "description": row["excerpt"], "location": LOCATION}


# --- judging ---------------------------------------------------------------

def judge(row: dict, draws: list[bool]) -> dict:
    """One row's result. `false_disq` is the gate: golden says no bar, and AT LEAST ONE
    draw disqualified. Any-draw, not majority — a check that discards a good posting one
    time in three is not a passing check."""
    golden = fact_is_a_bar(row["drawn_for"], row["facts"])
    majority = sum(draws) > len(draws) / 2
    return {
        "id": row["id"], "drawn_for": row["drawn_for"], "company": row["company"],
        "title": row["title"], "gate": bool(row.get("gate", True)),
        "golden": golden, "draws": draws, "majority": majority,
        "flipped": len(set(draws)) > 1,
        "false_disq": golden is False and any(draws),
        "miss": golden is True and not majority,
        "note": row.get("note", ""),
    }


def summarize(results: list[dict]) -> dict:
    gated = [r for r in results if r["gate"] and r["golden"] is not None]
    false_disq = [r for r in gated if r["false_disq"]]
    bars = [r for r in gated if r["golden"] is True]
    hit = [r for r in bars if r["majority"]]
    return {
        "rows": len(results), "gated": len(gated),
        "false_disq": false_disq,
        "recall_n": len(hit), "recall_d": len(bars),
        "flips": [r for r in results if r["flipped"]],
        "passed": not false_disq,
    }


# --- report ----------------------------------------------------------------

def render(results: list[dict], summary: dict, meta: dict) -> str:
    verdict = "PASS" if summary["passed"] else "FAIL"
    recall = (f"{summary['recall_n']}/{summary['recall_d']} "
              f"({100 * summary['recall_n'] / summary['recall_d']:.0f}%)"
              if summary["recall_d"] else "n/a")
    lines = [
        f"# screen eval — {verdict}",
        "",
        f"- backend `{meta['backend']}` model `{meta['model']}`, K={K}",
        f"- {summary['rows']} corpus rows, {summary['gated']} gate-eligible",
        f"- **false disqualification: {len(summary['false_disq'])} — this is the gate**",
        f"- recall (reported, NOT gated): {recall}",
        f"- flip (any draw disagreed): {len(summary['flips'])}",
        "",
    ]
    if summary["false_disq"]:
        lines += ["## False disqualifications — every one of these deletes a real job", ""]
        lines += ["| id | req | company | title | draws | golden fact | note |",
                  "|---|---|---|---|---|---|---|"]
        for r in summary["false_disq"]:
            lines.append(f"| {r['id']} | {r['drawn_for']} | {r['company']} | "
                         f"{r['title'][:44]} | {''.join('X' if d else '.' for d in r['draws'])} "
                         f"| no bar | {r['note'][:60]} |")
        lines.append("")
    misses = [r for r in results if r["miss"] and r["gate"]]
    if misses:
        lines += ["## Misses — reported, not gated (each costs one paid fit call)", ""]
        lines += ["| id | req | company | title | note |", "|---|---|---|---|---|"]
        for r in misses:
            lines.append(f"| {r['id']} | {r['drawn_for']} | {r['company']} | "
                         f"{r['title'][:44]} | {r['note'][:60]} |")
        lines.append("")
    lines += ["## Every row", "",
              "| id | req | gate | golden | draws | maj | company | title |",
              "|---|---|---|---|---|---|---|---|"]
    for r in results:
        golden = {True: "bar", False: "no bar", None: "—"}[r["golden"]]
        lines.append(
            f"| {r['id']} | {r['drawn_for']} | {'y' if r['gate'] else 'n'} | {golden} "
            f"| {''.join('X' if d else '.' for d in r['draws'])} "
            f"| {'X' if r['majority'] else '.'} | {r['company']} | {r['title'][:44]} |")
    return "\n".join(lines) + "\n"


# --- live run --------------------------------------------------------------

def load_golden() -> list[dict]:
    rows = []
    for line in GOLDEN.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if "_readme" in d:
            continue
        rows.append(d)
    return rows


def run_live() -> int:
    backend = os.environ.get("SCREEN_BACKEND", run.DEFAULT_SCREEN_BACKEND)
    if backend == "none":
        print("SCREEN_BACKEND=none makes no LLM call — there is nothing to gate.",
              file=sys.stderr)
        return 2
    import requests
    # Mirror run.main's model resolution EXACTLY. `make_screener` takes the model as a
    # KEYWORD, never from `env` (which it reads only for OLLAMA_HOST and the API keys):
    # --model / OLLAMA_MODEL drives ollama, --screen-model / SCREEN_MODEL drives the
    # hosted backends, and for ollama `screen_model` is ignored outright. Passing neither
    # ran every eval on the built-in defaults while the report header printed whatever
    # the env said — which silently voids this tool's one premise, that eval-model ==
    # production-model, and mislabels any A/B.
    ollama_model = os.environ.get("OLLAMA_MODEL") or run.DEFAULT_OLLAMA_MODEL
    screen_model = os.environ.get("SCREEN_MODEL") or None
    extract = run.make_screener(backend, env=dict(os.environ), http=requests,
                                model=ollama_model, screen_model=screen_model)
    model = ollama_model if backend == "ollama" else (screen_model
                                                      or f"{backend} default")

    rows = load_golden()
    results = []
    for n, row in enumerate(rows, 1):
        posting = posting_of(row)
        draws = []
        for _ in range(K):
            out = score.screen_posting(posting, extract=extract, candidate=CANDIDATE)
            if out.get("provider_error"):
                print(f"\nprovider error on row {row['id']} — the backend is down; "
                      f"a run against a dead provider proves nothing.", file=sys.stderr)
                return 2
            draws.append(measured_bar(out, row["drawn_for"]))
        results.append(judge(row, draws))
        print(f"\r{n}/{len(rows)} rows", end="", file=sys.stderr)
    print(file=sys.stderr)

    summary = summarize(results)
    report = render(results, summary, {"backend": backend, "model": model})
    OUT.write_text(report)
    print(report)
    print(f"(report written to {OUT.relative_to(ROOT)})")
    return 0 if summary["passed"] else 1


# --- selftest: free, hermetic, no Ollama and no network --------------------

def selftest() -> int:
    assert fact_is_a_bar("clearance", {"requires_clearance": True}) is True
    assert fact_is_a_bar("clearance", {"requires_clearance": False}) is False
    # CANDIDATE holds a Master's: phd bars, master's/bachelor's/none do not.
    assert fact_is_a_bar("degree", {"required_degree": "phd"}) is True
    assert fact_is_a_bar("degree", {"required_degree": "master's"}) is False
    assert fact_is_a_bar("degree", {"required_degree": "bachelor's"}) is False
    assert fact_is_a_bar("degree", {"required_degree": "none"}) is False
    assert fact_is_a_bar("degree", {"required_degree": "unclear"}) is None
    assert fact_is_a_bar("sponsorship", {"sponsorship": "refuses"}) is True
    assert fact_is_a_bar("sponsorship", {"sponsorship": "offers"}) is False
    assert fact_is_a_bar("sponsorship", {"sponsorship": "neither"}) is False

    # A requirement with no recorded verdict is a MISS, never a disqualification —
    # the distinction the 2026-07-23 pass/unknown fix exists to preserve.
    assert measured_bar({"screen": {}}, "degree") is False
    assert measured_bar({"screen": {"degree": {"pass": True}}}, "degree") is False
    assert measured_bar({"screen": {"degree": {"pass": False}}}, "degree") is True
    assert measured_bar({"screen": {"clearance": {"pass": False}}}, "sponsorship") is False

    row = {"id": 1, "drawn_for": "clearance", "company": "c", "title": "t",
           "facts": {"requires_clearance": False}, "gate": True, "note": ""}
    # ONE bad draw out of three is a false disqualification. Majority would hide it.
    assert judge(row, [False, True, False])["false_disq"] is True
    assert judge(row, [False, False, False])["false_disq"] is False
    bar = {**row, "facts": {"requires_clearance": True}}
    assert judge(bar, [True, False, False])["miss"] is True
    assert judge(bar, [True, True, False])["miss"] is False
    assert judge(bar, [True, True, False])["flipped"] is True

    # The gate is one-directional: misses never fail it, false disqualifications always do.
    only_misses = [judge(bar, [False, False, False])]
    assert summarize(only_misses)["passed"] is True
    assert summarize([judge(row, [True, True, True])])["passed"] is False
    # An ungated row cannot fail the gate however wrong it is.
    ungated = {**row, "gate": False}
    assert summarize([judge(ungated, [True, True, True])])["passed"] is True
    # Nor can a row whose label is not assertable.
    unclear = {**row, "drawn_for": "degree", "facts": {"required_degree": "unclear"}}
    assert summarize([judge(unclear, [True, True, True])])["passed"] is True

    # The corpus itself must be loadable and labeled the way the gate assumes.
    rows = load_golden()
    assert rows, "golden set is empty"
    kinds = Counter(r["drawn_for"] for r in rows)
    assert set(kinds) == {"clearance", "degree", "sponsorship"}, kinds
    for r in rows:
        assert r["excerpt"].strip(), f"row {r['id']} has an empty excerpt"
        assert fact_is_a_bar(r["drawn_for"], r["facts"]) is not None or not r.get("gate", True), \
            f"row {r['id']} is gated but its label is not assertable"

    print(f"selftest ok — {len(rows)} corpus rows "
          + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Hard-requirement accuracy eval for the SCREEN prompt.")
    ap.add_argument("--selftest", action="store_true",
                    help="free, hermetic gate-logic check — no Ollama, no network")
    args = ap.parse_args()
    return selftest() if args.selftest else run_live()


if __name__ == "__main__":
    raise SystemExit(main())
