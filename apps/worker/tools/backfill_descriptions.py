"""Re-hydrate stored postings whose description is a teaser.

`db.upsert_postings` is ON CONFLICT DO NOTHING, so every fetch-layer improvement helps
only postings fetched AFTER it. The rows already in the table keep the teaser they were
stored with — 1,615 of them, 14% of the corpus, at 250-850 chars against the 1,900-2,200
that a healthy board produces.

This re-runs the now-capable fetch for a board and UPDATEs `description` where the fresh
one is materially longer. Dry-run by default.

**It never re-scores, and never touches `score`, `score_detail` or `pipeline_status`.**
665 of these rows already hold a paid fit verdict computed from a teaser. Re-scoring them
is a quota decision, and quota is the standing priority — so this reports what changed and
stops. Deciding what to do about the stale verdicts is the operator's.

    python3 tools/backfill_descriptions.py --slug ibm
    python3 tools/backfill_descriptions.py --slug ibm --apply
    python3 tools/backfill_descriptions.py --all --apply
"""
import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ats_worker.fetch import fetch_company  # noqa: E402

DEFAULT_DB = str(Path(__file__).resolve().parents[2] / "web" / "prisma" / "applications.db")
# Below this, a stored description is a teaser rather than a JD — the same threshold
# `pipeline._log_board_health` marks boards with. Healthy boards sit at 1,900-2,200.
TEASER_MEDIAN_CHARS = 1500


def _boards(conn, slug):
    q = "SELECT source, slug, name, recipe FROM watched_companies"
    rows = conn.execute(q + (" WHERE slug = ?" if slug else ""),
                        (slug,) if slug else ()).fetchall()
    return [dict(r) for r in rows]


def _teaser_boards(conn):
    """Boards whose STORED rows read as teasers — the ones worth re-fetching."""
    out = []
    for r in conn.execute(
            "SELECT company_slug, COUNT(*) n, AVG(LENGTH(COALESCE(description,''))) a "
            "FROM job_postings GROUP BY 1 HAVING n > 0"):
        if r["a"] < TEASER_MEDIAN_CHARS:
            out.append(r["company_slug"])
    return out


def backfill(conn, board, *, apply_changes, min_gain):
    """Returns (examined, improved, chars_before, chars_after)."""
    recipe = json.loads(board["recipe"]) if board["recipe"] else None
    fresh = fetch_company(board["source"], board["slug"], board["name"], recipe=recipe)
    # Same key `upsert_postings` dedups on, so a match here is the row that would have
    # been written had the board been capable at the time.
    by_id = {(p["source"], p["external_id"]): p for p in fresh}

    stored = conn.execute(
        "SELECT id, source, external_id, LENGTH(COALESCE(description,'')) n "
        "FROM job_postings WHERE company_slug = ?", (board["slug"],)).fetchall()

    examined = improved = 0
    before, after = [], []
    for row in stored:
        p = by_id.get((row["source"], row["external_id"]))
        if p is None:
            continue          # posting is gone from the board; leave the row alone
        examined += 1
        new = p.get("description") or ""
        # `min_gain` guards against churning a row for a few characters of whitespace
        # difference, and against a board that transiently serves a SHORTER body.
        if not new or len(new) < max(row["n"] * min_gain, row["n"] + 1):
            continue
        improved += 1
        before.append(row["n"])
        after.append(len(new))
        if apply_changes:
            # description ONLY. score/score_detail/pipeline_status are deliberately
            # untouched: a stale verdict is a quota decision, not this tool's call.
            conn.execute("UPDATE job_postings SET description = ? WHERE id = ?",
                         (new, row["id"]))
    if apply_changes:
        conn.commit()
    return examined, improved, before, after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slug", help="one watchlist slug")
    g.add_argument("--all", action="store_true",
                   help="every board whose stored rows read as teasers")
    ap.add_argument("--apply", action="store_true",
                    help="write the UPDATEs (default is a dry run)")
    ap.add_argument("--min-gain", type=float, default=1.2,
                    help="only replace when the fresh body is this many times longer")
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    slugs = _teaser_boards(conn) if args.all else [args.slug]
    boards = [b for b in _boards(conn, None) if b["slug"] in slugs]
    if not boards:
        print(f"no watchlist board matched {slugs}")
        return 1

    print(f"{'DRY RUN — nothing written' if not args.apply else 'APPLYING'}"
          f"   min-gain={args.min_gain}x   db={args.db}\n")
    print(f"{'board':<24} {'examined':>8} {'improved':>8} {'median before':>14} {'after':>8}")
    total = 0
    for b in boards:
        try:
            examined, improved, before, after = backfill(
                conn, b, apply_changes=args.apply, min_gain=args.min_gain)
        except Exception as exc:  # noqa: BLE001 — one bad board must not stop the rest
            print(f"{b['slug']:<24} SKIPPED: {type(exc).__name__}: {str(exc)[:60]}")
            continue
        total += improved
        mb = f"{statistics.median(before):.0f}" if before else "-"
        ma = f"{statistics.median(after):.0f}" if after else "-"
        print(f"{b['slug']:<24} {examined:>8} {improved:>8} {mb:>14} {ma:>8}")

    print(f"\n{total} row(s) {'updated' if args.apply else 'would be updated'}.")
    if total and not args.apply:
        print("Re-run with --apply to write.")
    if total and args.apply:
        print("\nNOTE: `score`, `score_detail` and `pipeline_status` were NOT touched.\n"
              "Rows already scored still hold the verdict computed from the teaser.\n"
              "Re-scoring them costs quota and is your call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
