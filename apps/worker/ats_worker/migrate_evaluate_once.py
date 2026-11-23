"""One-time operator migration to evaluate-once (#225).

Run it once, with the worker stopped, after the schema push that adds
`job_postings.verdict`:

    (cd ../web && npx prisma db push)
    python3 -m ats_worker.migrate_evaluate_once migrate --db ../../db/applications.db

`migrate` first writes a backup beside the DB (SQLite backup API, PRINCIPLES 9), then:

1. Moves every legacy fetch-time discard (`pipeline_status='discarded'` with the screen
   verdict embedded in `score_detail`) into the shape the worker writes now: a completed
   requirements result in `job_screenings` (backend `deterministic`), `pipeline_status`
   back to `new`, `score_detail` cleared, verdict `discarded`.
2. Backfills `job_postings.verdict` once from today's status rules: a disqualifying
   screen is `discarded`; a completed triage keep/skip stands; a passing screen is `keep`
   when triage is not in use (the readers' "for you" rule: a target role or custom
   context, and at least one triage verdict); anything unfinished stays `pending` inside
   the window and becomes `not_evaluated` outside it.
3. Deletes the retired `jev_current_policy_sha256` setting.

It refuses, writing nothing, before the schema push, when triage rows exist but no
`candidate_profile` row does (run `ats_worker.migrate_profile` first), or when a
`discarded` row is not exactly the legacy shape (or already has a screen row): those
need a look by hand. All of it is one transaction, committed with the
`evaluate_once_migrated_at` setting; a rerun with that marker set and nothing left for
db.needs_evaluate_once_migration (the worker's refusal test) reports "already
migrated" and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import db, pipeline

_LEGACY_KEYS = {"screen", "disqualified", "disqualification_reason", "source_content_revision"}
_RESULT_KEYS = ("screen", "disqualified", "disqualification_reason")
ALREADY = "already migrated: no legacy discard and no unsettled screen or triage verdict"
MARKER = "evaluate_once_migrated_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MigrationError(Exception):
    """A state the migration does not know how to move; nothing was written."""


def backup(db_path: str, *, stamp: str | None = None) -> Path:
    """A consistent single-file copy beside the DB (the backup API also captures the WAL)."""
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = Path(f"{db_path}.backup-{stamp}-pre-evaluate-once")
    if target.exists():
        raise MigrationError(f"{target} already exists")
    with closing(sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)) as src, \
            closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target


def _legacy_discards(conn) -> list[tuple[int, str, dict]]:
    """(id, created_at, the requirements result) per legacy discard; raises on any row
    that is not exactly the legacy fetch-time shape."""
    out = []
    for row in conn.execute(
            "SELECT p.id, p.created_at, p.score_detail, s.id AS screening FROM job_postings p "
            "LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
            "WHERE p.pipeline_status='discarded' ORDER BY p.id"):
        if row["screening"] is not None:
            raise MigrationError(f"discarded posting {row['id']} already has a job_screenings row")
        try:
            detail = json.loads(row["score_detail"]) if row["score_detail"] else None
        except json.JSONDecodeError:
            detail = None
        if (not isinstance(detail, dict) or set(detail) - _LEGACY_KEYS
                or detail.get("disqualified") is not True
                or not isinstance(detail.get("screen"), dict)):
            raise MigrationError(f"discarded posting {row['id']} has an unexpected score_detail "
                                 "(not a legacy fetch-time discard)")
        out.append((row["id"], row["created_at"],
                    {k: detail[k] for k in _RESULT_KEYS if k in detail}))
    return out


def _triage_in_use(conn) -> bool:
    """The readers' "for you" mode rule (web JEV_MODE_SQL): triage is configured in the
    profile and has produced at least one verdict."""
    return bool(conn.execute(
        "SELECT EXISTS (SELECT 1 FROM candidate_profile WHERE id=1 "
        "AND (json_array_length(target_roles) > 0 OR custom_triage_context IS NOT NULL)) "
        "AND EXISTS (SELECT 1 FROM job_jev_assessments)").fetchone()[0])


def _backfill(conn, *, now: str) -> dict:
    screen = ("SELECT 1 FROM job_screenings s WHERE s.job_posting_id=job_postings.id "
              "AND s.state='complete' AND json_valid(s.result_json) "
              "AND COALESCE(json_extract(s.result_json,'$.disqualified'),0)")
    done = {}
    done["discarded"] = conn.execute(
        "UPDATE job_postings SET verdict='discarded', verdict_at=? "
        f"WHERE verdict='pending' AND EXISTS ({screen}=1)", (now,)).rowcount
    # Any finished triage verdict stands (a disqualifying screen settled above first), so
    # no pending row with a complete triage row survives: see needs_evaluate_once_migration.
    triaged = conn.execute(
        "UPDATE job_postings SET verdict=(SELECT j.verdict FROM job_jev_assessments j "
        "WHERE j.job_posting_id=job_postings.id), verdict_at=? "
        "WHERE verdict='pending' AND EXISTS (SELECT 1 FROM "
        "job_jev_assessments j WHERE j.job_posting_id=job_postings.id AND j.state='complete' "
        "AND j.verdict IN ('keep','skip'))", (now,)).rowcount
    done["triaged"] = triaged
    # not_evaluated too: a no-triage pass run before the migration aged these out.
    done["kept_untriaged"] = 0 if _triage_in_use(conn) else conn.execute(
        "UPDATE job_postings SET verdict='keep', verdict_at=? "
        "WHERE verdict IN ('pending','not_evaluated') "
        f"AND EXISTS ({screen}=0) AND NOT EXISTS ({screen}=1)", (now,)).rowcount
    done["not_evaluated"] = db.age_out(conn, since=pipeline.window_start(now), now=now,
                                       commit=False)
    return done


def migrate(db_path: str, *, now: str, out=print) -> int:
    """0 = migrated or already migrated, 2 = refused (nothing written)."""
    if not Path(db_path).is_file():
        out(f"refused: {db_path} does not exist")
        return 2
    with closing(db.connect(db_path)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(job_postings)")}
        if "verdict" not in cols:
            out("refused: job_postings has no verdict column; run `npx prisma db push` in "
                "apps/web first")
            return 2
        try:
            legacy = _legacy_discards(conn)
        except MigrationError as exc:
            out(f"refused: {exc}; nothing written")
            return 2
        marked = conn.execute("SELECT 1 FROM app_settings WHERE key=?", (MARKER,)).fetchone()
        if marked and not db.needs_evaluate_once_migration(conn):
            out(ALREADY)
            return 0
        if conn.execute("SELECT EXISTS (SELECT 1 FROM job_jev_assessments) AND NOT EXISTS "
                        "(SELECT 1 FROM candidate_profile)").fetchone()[0]:
            out("refused: triage rows exist but no candidate_profile row; run "
                "`python3 -m ats_worker.migrate_profile migrate` first; nothing written")
            return 2
    target = backup(db_path)
    out(f"backed up to {target}")
    with closing(db.connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for posting_id, created_at, result in legacy:
            db._insert_requirements(conn, posting_id, result, now=created_at,
                                    evaluator_version=pipeline.SCREEN_EVALUATOR_VERSION,
                                    profile_version=None)
            conn.execute("UPDATE job_postings SET pipeline_status='new', score_detail=NULL, "
                         "verdict='discarded', verdict_at=? WHERE id=?", (created_at, posting_id))
        conn.execute("DELETE FROM app_settings WHERE key='jev_current_policy_sha256'")
        done = _backfill(conn, now=now)
        conn.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                     "updated_at=excluded.updated_at", (MARKER, now, now))
        # One commit for move + backfill + setting + age-out: a kill before it leaves the
        # DB as it was, so the rerun still sees it unmigrated.
        conn.commit()
    out(f"moved {len(legacy)} legacy discard(s) into the requirements shape")
    out(f"backfilled verdicts: {done['discarded']} discarded, {done['triaged']} from triage, "
        f"{done['kept_untriaged']} keep without triage, {done['not_evaluated']} not_evaluated "
        "(outside the window); the rest stay pending for the next pass")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m ats_worker.migrate_evaluate_once",
                                     description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help="back up, move legacy discards, backfill verdicts")
    m.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    try:
        return migrate(args.db, now=_now())
    except (MigrationError, sqlite3.Error) as exc:
        print(f"refused: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
