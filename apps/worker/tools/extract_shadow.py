"""Run the bounded fit EXTRACTION over a set of postings and write the records to disk.

SHADOW, AND THAT IS STRUCTURAL. This is a standalone tool. It reads the DB read-only,
writes nothing back to it, and touches no `score_detail`, no `pipeline_status` and no
notification gate — the live scorer keeps deciding everything until the rebuild's single
cutover. Its only output is a jsonl artifact.

WHAT AN ARTIFACT HAS TO CARRY, and why each field is not optional:

- the four provenance hashes, because a label is only meaningful against the inputs it
  was made under, and those inputs move — `personal_profile.txt` changed 2026-08-02 and
  `config.yaml` 2026-08-03, which is why all 501 stored production scores are stale;
- the ref -> concept-id mapping AND the descriptions the model was shown, because a
  stored record naming `ml_platform` is uncheckable without the text that produced it;
- the run token, so the whole run replays byte-identically;
- the backend and model, because the point of a shadow run is comparing two model
  families over the same postings.

USAGE
    PYTHONPATH=. python3 tools/extract_shadow.py --frame eval/frame_extraction.jsonl \\
        --backend codex --model gpt-5.6-sol --out eval/extract_codex.jsonl
    PYTHONPATH=. python3 tools/extract_shadow.py --ids 723,738 --backend claude \\
        --model claude-sonnet-5 --out /tmp/probe.jsonl

Resumable: an existing --out is read first and its ids are skipped, so a paid run splits
across sittings. Cost is real — read `docs/PROGRESS.md`'s quota section before a large
one, and note that batching is pinned at ONE posting per call because batching was
measured to bleed verdicts between postings at every size above 1.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ats_worker.config import load_config  # noqa: E402
from ats_worker.prompts import EXTRACTOR_VERSION  # noqa: E402
from ats_worker.run import load_resumes  # noqa: E402
from ats_worker.score.errors import ScoreError  # noqa: E402
from ats_worker.score.extract import make_extractor  # noqa: E402
from ats_worker.fit_profile import provenance  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DB = f"file:{ROOT}/db/applications.db?mode=ro"
WORKER = Path(__file__).resolve().parents[1]

_COLUMNS = "id, job_title, company_name, source, description"


def _rows_from_db(ids: list[int]) -> list[dict]:
    """Read postings by id, read-only. Ids not in the DB are reported, never skipped
    silently — a shrinking corpus that nobody notices is the exact failure that left the
    fit gate running 71 of 93 rows and reporting PASS."""
    with sqlite3.connect(DB, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(ids))
        found = {r["id"]: dict(r) for r in
                 conn.execute(f"SELECT {_COLUMNS} FROM job_postings WHERE id IN ({marks})", ids)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise SystemExit(f"{len(missing)} id(s) are not in the DB: {missing[:10]}")
    return [found[i] for i in ids]


def _rows_from_frame(path: Path) -> list[dict]:
    """Read a frame file. A row's INLINE posting text wins over the DB copy — that
    self-containment is why `screen_golden.jsonl` survived the DB churn that killed 22
    rows of `golden.jsonl`."""
    inline, needed = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "id" not in row:
            continue  # the frame's `kind: frame_header` line, and any future metadata
        posting = row.get("posting")
        if isinstance(posting, dict) and posting.get("description"):
            inline.append({"id": row["id"], **posting})
        else:
            needed.append(int(row["id"]))
    return inline + (_rows_from_db(needed) if needed else [])


# The meter is read before EVERY call, and `/api/oauth/usage` is rate-limited. At opus's
# ~25s/posting an uncached read is ~144 requests/hour; it answers 429, three in a row trip
# the blind-row stop, and the sitting ends at 31 rows (measured 2026-08-04). Sonnet at
# 136s/posting never hit it — the faster the arm, the harder it polls, so the speed win is
# what created this. ccstatusline caches the same endpoint for 180s for the same reason.
#
# A cached reading can only ever be stale-LOW, so the guard must sit far enough below 100
# to absorb one TTL of burn: at ~0.6 points/row and ~25s/row that is ~7 rows, ~4 points.
# Hence `--stop-at-percent 88` rather than 95 on this arm.
# Caching the HEALTHY path is not enough, and the second 429-stall proved it: `_get_json`
# retries a 429 four times with backoff, and the next row 35s later does it again, so a
# failing meter generates ~4 requests per row in a tight loop and holds the endpoint in
# its penalty box indefinitely. The failure path needs the backoff, not just the hot path.
#
# So a failed read opens a penalty box: no request AT ALL for 300s (the backoff
# ccstatusline observes after a 429), during which the last good reading is served if it
# is still worth trusting. Only when there is no reading that fresh does the run go blind
# and the 3-strike stop apply.
_METER_TTL_S = 180.0
_METER_PENALTY_S = 300.0
# The oldest reading still worth acting on. Bounds the stale-LOW error: ~600s at this
# arm's ~35s/row and ~0.6 points/row is ~10 points, which is why the guard sits at 85.
_METER_STALE_MAX_S = 600.0

_meter_cache: dict[str, tuple[float, tuple[int, str]]] = {}
_meter_penalty: dict[str, float] = {}


def _tightest_window(backend: str, ttl: float = _METER_TTL_S):
    """Read the backend's usage and return (used_percent, key) for the window that binds
    SOONEST, or None if no reading worth acting on is available. Cached for `ttl` seconds,
    with a 300s no-request penalty box after any failure.

    The tightest window is the right one to guard, not the biggest: Claude Code meters a
    rolling 5-hour SESSION window alongside a weekly one, and a 250-call batch exhausts
    the 5-hour one long before the weekly. Codex exposes only a weekly window, so the
    rule degenerates correctly there.
    """
    now = time.monotonic()
    cached = _meter_cache.get(backend)
    if cached is not None and (now - cached[0]) < ttl:
        return cached[1]

    def _stale_or_blind():
        if cached is not None and (now - cached[0]) < _METER_STALE_MAX_S:
            return cached[1]
        return None

    if now < _meter_penalty.get(backend, 0.0):
        return _stale_or_blind()  # in the penalty box: make no request

    from ats_worker.score.usage import fetch_claude_usage, fetch_codex_usage
    snapshot = (fetch_claude_usage if backend == "claude" else fetch_codex_usage)()
    limits = (snapshot or {}).get("limits") or []
    if not limits:
        _meter_penalty[backend] = now + _METER_PENALTY_S
        return _stale_or_blind()
    tight = min(limits, key=lambda x: x.get("window_minutes") or 10 ** 9)
    result = (int(tight.get("used_percent") or 0), tight.get("key"))
    _meter_cache[backend] = (now, result)
    _meter_penalty.pop(backend, None)
    return result


# Consecutive unreadable meters before the run stops. The quota endpoint is known to
# answer 403 intermittently (PROGRESS: `capture_usage`), so one miss must not end a paid
# run — but flying blind INTO a hard limit is worse than stopping early, so it is bounded.
_MAX_BLIND_ROWS = 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--frame", help="jsonl frame file ({id, posting?} per line)")
    src.add_argument("--ids", help="comma-separated posting ids")
    ap.add_argument("--backend", required=True, choices=("codex", "claude"))
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True, help="jsonl artifact (appended, resumable)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N new postings")
    ap.add_argument("--stop-at-percent", type=int, default=0,
                    help="stop cleanly once the backend's TIGHTEST quota window reaches "
                         "this percent (0 = no guard). Checked before every call, so the "
                         "run stops below the line rather than crossing it.")
    ap.add_argument("--effort", default="",
                    help="reasoning effort for the claude backend (`--effort`). Codex is "
                         "pinned to `low`; pass `low` here to configure the two "
                         "comparably, or an A/B measures the flags, not the models.")
    ap.add_argument("--run-token", default="",
                    help="seeds the ephemeral concept refs; defaults to the concept "
                         "vocabulary hash, so every run of one vocabulary — including "
                         "the K draws of a self-consistency measurement — shares a "
                         "mapping and a cached prefix")
    ap.add_argument("--config", default=str(WORKER / "config.yaml"))
    ap.add_argument("--resume-dir", default=str(WORKER / "resume"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    profile = cfg.fit_profile
    if profile is None or profile.is_empty():
        raise SystemExit(f"{args.config} has no `fit_profile` block — see "
                         "config.yaml.example for the shape.")
    for warning in profile.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    resumes, profile_text = load_resumes(args.resume_dir)
    stamp = provenance(profile, profile_text=profile_text, resumes=resumes)
    out_path = Path(args.out)
    # Seeded off the VOCABULARY, not the clock and not the filename. A resumed run must
    # mint the mapping of the sitting it continues, or half the artifact refers to a list
    # the other half never saw — and, less obviously, a K=3 self-consistency run writes
    # to three different `--out` files, so a filename seed would shuffle the concept list
    # differently in each draw and confound model flip with list order. That flip rate is
    # the measurement `SCORING 8.7` calls the deciding one, so it must not be confounded.
    run_token = args.run_token or stamp["concept_vocab_hash"]

    rows = (_rows_from_frame(Path(args.frame)) if args.frame
            else _rows_from_db([int(x) for x in args.ids.split(",") if x.strip()]))

    done: set[int] = set()
    have_header = False
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "run_header":
                have_header = True
                # Appending a second backend's rows under the first's header would make
                # the artifact describe a run that never happened. The per-row stamps
                # would still be right, but nobody reads 250 rows to discover that.
                if (row.get("backend"), row.get("model")) != (args.backend, args.model):
                    raise SystemExit(
                        f"{out_path} was started on {row.get('backend')}/{row.get('model')}"
                        f" and you asked for {args.backend}/{args.model}. Use a separate "
                        "--out per arm; comparing arms is the point of running two.")
            elif "id" in row:
                done.add(int(row["id"]))
    pending = [r for r in rows if r["id"] not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f"{len(rows)} posting(s), {len(done)} already in {out_path.name}, "
          f"{len(pending)} to run on {args.backend}/{args.model}", file=sys.stderr)
    if not pending:
        return 0

    backend_kwargs = {"effort": args.effort} if args.effort and args.backend == "claude" else {}
    extract = make_extractor(profile, run_token, backend=args.backend, model=args.model,
                             **backend_kwargs)
    header = {
        "kind": "run_header", "extractor_version": EXTRACTOR_VERSION,
        "backend": args.backend, "model": args.model, "run_token": run_token,
        "resume_labels": sorted(resumes), "provenance": stamp,
        # Both halves: the mapping to read an answer, and the text that produced it.
        "concepts": [{"ref": e["ref"], "concept_id": extract.ref_to_id[e["ref"]],
                      "description": e["description"]} for e in extract.concept_entries],
    }
    failures = 0
    with out_path.open("a", encoding="utf-8") as fh:
        # Keyed on the header itself, not on `done`: a sitting that wrote the header and
        # then died before its first record would otherwise write a second one.
        if not have_header:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            fh.flush()
        blind = 0
        for n, posting in enumerate(pending, 1):
            if args.stop_at_percent:
                reading = _tightest_window(args.backend)
                if reading is None:
                    blind += 1
                    print(f"  [{n}/{len(pending)}] quota meter unreadable "
                          f"({blind}/{_MAX_BLIND_ROWS})", file=sys.stderr)
                    if blind >= _MAX_BLIND_ROWS:
                        print(f"STOPPING: could not read the quota meter {blind} times "
                              "in a row. Resume with the same --out once it answers.",
                              file=sys.stderr)
                        break
                else:
                    blind = 0
                    used, key = reading
                    if used >= args.stop_at_percent:
                        print(f"STOPPING at {used}% of the `{key}` window "
                              f"(guard {args.stop_at_percent}%), {n - 1} row(s) written "
                              f"this sitting. Resume with the same --out after it resets.",
                              file=sys.stderr)
                        break
            started = time.monotonic()
            try:
                # ONE posting per call. Batching was measured to bleed duty and verdict
                # content between postings at every size above 1 (2026-07-17), and the
                # quota is per-token anyway, so a batch saves only the shared prefix.
                record = extract([posting], resumes)[0]
            except ScoreError as exc:
                failures += 1
                print(f"  [{n}/{len(pending)}] id={posting['id']} FAILED: {exc}",
                      file=sys.stderr)
                # Recorded, not swallowed: a schema/enum failure rate IS one of the
                # measurements a shadow run exists to produce.
                record = {"error": str(exc)}
            row = {"id": posting["id"], "job_title": posting.get("job_title", ""),
                   "company_name": posting.get("company_name", ""),
                   "source": posting.get("source", ""),
                   "backend": args.backend, "model": args.model,
                   "extractor_version": EXTRACTOR_VERSION, "provenance": stamp,
                   "elapsed_s": round(time.monotonic() - started, 1),
                   "extraction": record}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()  # a paid run must survive a Ctrl-C with everything bought so far
            if "error" not in record:
                ev = record.get("evidence", {})
                print(f"  [{n}/{len(pending)}] id={posting['id']} "
                      f"{len(record['duties'])}d/{len(record['required_qualifications'])}q "
                      f"quote-fail={ev.get('job_quote_failures', 0)} "
                      f"{row['elapsed_s']}s", file=sys.stderr)
    print(f"wrote {len(pending)} row(s) to {out_path} ({failures} failed)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
