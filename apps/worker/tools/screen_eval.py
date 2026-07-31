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
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "worker"))
from ats_worker import run, score  # noqa: E402  (needs apps/worker on the path)

K = 3
GOLDEN = ROOT / "apps/worker/eval/screen_golden.jsonl"
# Overridable so two backends can be A/B'd CONCURRENTLY. They otherwise race on one file:
# on 2026-07-31 two runs of this tool overwrote each other's report, and a third process
# read the survivor as its own result. A backend comparison is the normal use of this
# tool, so the shared default path is a footgun rather than a convenience.
OUT = Path(os.environ.get("SCREEN_EVAL_OUT") or ROOT / "apps/worker/eval/last_screen_run.md")

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

# The vocabulary a row labeled as a BAR must contain for that label to be supportable by
# the text handed to the model. Checked in `--selftest`, and it is a check on the CORPUS,
# not on the model: a row whose excerpt cannot support its own label is a guaranteed miss
# for any model or prompt, so every recall figure computed over it is meaningless. Four
# IMC rows were exactly that — golden `refuses`, excerpts truncated at the `_readme` cap
# before the refusal sentence, no sponsorship word anywhere in them.
#
# Only the BAR direction is asserted. A `no bar` row legitimately contains nothing: for
# clearance and sponsorship, absence of the vocabulary IS the evidence of no bar.
#
# `clearance` reuses the production floor's own tokens (`screen.CLEARANCE_TOKENS`) because
# that regex is what decides whether the check may fire at all. The other two are stated
# here rather than borrowed: the sponsorship set is deliberately WIDER than the production
# retrieval vocabulary (`sponsor` alone), since a bar phrased without that word is a
# pinned, accepted recall loss — a corpus premise the eval measures, not a corpus defect.
BAR_VOCAB = {
    "clearance": score.screen.CLEARANCE_TOKENS,
    "sponsorship": re.compile(
        r"sponsor|visa|citizen|authoriz|right to work|immigration|work permit|"
        r"green card|permanent resident|\bh-?1b\b|\bead\b|opt\b", re.IGNORECASE),
    # A bar for CANDIDATE (Master's) means a doctorate is required, so "degree" or
    # "bachelor's" alone cannot support the label — it has to name the doctorate.
    "degree": re.compile(r"ph\.?\s?d|doctora|d\.?phil", re.IGNORECASE),
}


def unsupportable_bars(rows: list[dict]) -> list[tuple]:
    """Corpus rows labeled as a bar whose own text carries none of that requirement's
    vocabulary. Returns `(id, drawn_for, excerpt_len)` for each — a corpus defect."""
    bad = []
    for r in rows:
        if fact_is_a_bar(r["drawn_for"], r["facts"]) is not True:
            continue
        if not r.get("gate", True):
            continue
        evidence = f"{r.get('title') or ''} {r.get('excerpt') or ''}"
        if not BAR_VOCAB[r["drawn_for"]].search(evidence):
            bad.append((r["id"], r["drawn_for"], len(r.get("excerpt") or "")))
    return bad


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


# `claude-code` is absent on purpose: make_claude_code_extract(None) lets the CLI pick,
# so there is no constant here to name.
_BACKEND_DEFAULT_MODEL = {
    "codex": run.DEFAULT_CODEX_SCREEN_MODEL,
    "claude-api": run.DEFAULT_CLAUDE_SCREEN_MODEL,
    "openai-api": run.DEFAULT_OPENAI_SCREEN_MODEL,
}


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
    # Same reason, same premise: run.main threads OLLAMA_NUM_CTX into BOTH the screener
    # and screen_posting (the JD truncation cap is num_ctx*2), so an eval that ignored it
    # would run a different context window than production wherever it is set.
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
    extract = run.make_screener(backend, env=dict(os.environ), http=requests,
                                model=ollama_model, screen_model=screen_model,
                                num_ctx=num_ctx)
    # Name the model the run will ACTUALLY use. "{backend} default" is what a reader
    # diffs across A/B runs, and it names nothing.
    model = ollama_model if backend == "ollama" else (
        screen_model or _BACKEND_DEFAULT_MODEL.get(backend) or f"{backend} default")

    rows = load_golden()
    results = []
    for n, row in enumerate(rows, 1):
        posting = posting_of(row)
        draws = []
        for _ in range(K):
            out = score.screen_posting(posting, extract=extract, candidate=CANDIDATE,
                                       num_ctx=num_ctx)
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

    # The invariants above check that a label is ASSERTABLE; this one checks the excerpt
    # could actually support it. They are different failures, and only the second one
    # catches a truncated excerpt — a guaranteed miss that silently deflates recall.
    assert unsupportable_bars([{"id": 1, "drawn_for": "sponsorship", "gate": True,
                                "title": "t", "excerpt": "no vocabulary here",
                                "facts": {"sponsorship": "refuses"}}])
    assert not unsupportable_bars([{"id": 1, "drawn_for": "sponsorship", "gate": True,
                                    "title": "t", "excerpt": "we do not sponsor visas",
                                    "facts": {"sponsorship": "refuses"}}])
    # A `no bar` row needs no vocabulary — its absence is the evidence.
    assert not unsupportable_bars([{"id": 1, "drawn_for": "clearance", "gate": True,
                                    "title": "t", "excerpt": "nothing relevant",
                                    "facts": {"requires_clearance": False}}])
    bad = unsupportable_bars(rows)
    assert not bad, (
        "corpus rows labeled as a bar whose excerpt carries none of that requirement's "
        f"vocabulary — guaranteed misses, so any recall figure over them is meaningless: {bad}")

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
