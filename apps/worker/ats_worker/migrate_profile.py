"""One-time operator migration to the candidate profile (#224).

The legacy `candidate_preferences` and `jev_profile` tables are dropped by the schema
push, so the migration reads them from the backup taken first (PRINCIPLES 9):

    python3 -m ats_worker.migrate_profile backup  --db ../../db/applications.db
    (cd ../web && npx prisma db push --accept-data-loss)   # creates candidate_profile
    python3 -m ats_worker.migrate_profile migrate --db ../../db/applications.db \\
        --legacy-db <the backup path printed above> --config config.yaml

`migrate` writes one `candidate_profile` row from the legacy rows plus config.yaml
`title_filter` / `title_exclude` / `max_age_days` (and `jev_dir` when no `jev_profile`
row exists). It refuses unless the new row screens and triages exactly as the legacy
inputs did: the same requirements at the same degree rank, and the same JEV policy hash.
No stored verdict is touched. Idempotent: a second run reports "already migrated". An
untouched config seed (the worker ran before the migration) is replaced; a row edited
since is never overwritten. Keep the worker stopped from the backup until `migrate` is done.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import config as config_mod
from . import db, jev, profile
from .screening.engine import _degree_rank

_POLICY_PROBE_MODEL = "policy-probe"  # any fixed model: both hashes take the same one


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MigrationError(Exception):
    """A step that must stop the operator before the destructive schema push."""


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def backup(db_path: str, *, stamp: str | None = None) -> Path:
    """A consistent single-file copy (the SQLite backup API also captures the WAL).

    The source is opened read-only, so a mistyped path fails instead of creating an
    empty DB, and the copy must hold the legacy rows the migration will need."""
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(f"{db_path}.backup-{stamp}-pre-candidate-profile")
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            tables = _tables(dst)
    except sqlite3.OperationalError as exc:
        target.unlink(missing_ok=True)
        raise MigrationError(f"cannot read {db_path}: {exc}") from exc
    if "job_postings" not in tables or not tables & {"candidate_preferences", "jev_profile"}:
        target.unlink(missing_ok=True)
        raise MigrationError(f"{db_path} has no job_postings or no candidate_preferences / "
                             "jev_profile table: wrong path, or the schema push already ran; "
                             "no backup written")
    return target


def _legacy_rows(legacy_db: str) -> tuple[dict | None, dict | None]:
    uri = f"file:{Path(legacy_db).resolve()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        tables = _tables(conn)
        if not tables & {"candidate_preferences", "jev_profile"}:
            raise MigrationError(f"{legacy_db} has no candidate_preferences or jev_profile "
                                 "table: pass the backup taken before the schema push")

        def one(table):
            if table not in tables:
                return None
            row = conn.execute(f"SELECT * FROM {table} WHERE id=1").fetchone()
            return dict(row) if row else None
        return one("candidate_preferences"), one("jev_profile")


def _legacy_screen(preferences: dict | None) -> dict | None:
    """The legacy checklist as the old worker built it, degree as its rank."""
    if preferences is None:
        return None
    cand = config_mod._parse_candidate({k: preferences[k] for k in (
        "highest_degree", "work_authorization", "security_clearance", "exclude_internships",
        "exclude_contract")} | {"locations": json.loads(preferences["locations"] or "[]")})
    return None if cand.is_empty() else _comparable(cand.__dict__)


def _comparable(candidate: dict | None) -> dict | None:
    if candidate is None:
        return None
    out = dict(candidate, locations=list(candidate["locations"]))
    degree = str(out.pop("highest_degree") or "").strip()
    out["degree_rank"] = _degree_rank(degree) if degree else None
    return out


def _policy(texts: dict | None) -> str | None:
    return None if texts is None else jev.inputs_from_texts(texts).policy_sha(_POLICY_PROBE_MODEL)


def migrate(db_path: str, legacy_db: str, cfg, *, now: str, out=print) -> int:
    """0 = migrated or already migrated, 2 = refused (nothing written)."""
    try:
        preferences, jev_row = _legacy_rows(legacy_db)
    except (MigrationError, sqlite3.OperationalError) as exc:
        out(f"refused: {exc}")
        return 2
    jev_texts = ({k: jev_row[k] for k in jev.INPUT_TEXTS} if jev_row is not None
                 else jev.read_files(cfg.jev_dir) if cfg.jev_dir else None)
    values = profile.seed_values(cfg, preferences=preferences, jev_texts=jev_texts)
    if values is None:
        out("nothing to migrate: no legacy rows and no config.yaml candidate settings")
        return 0
    new = profile.from_row(values)

    # The verdict-stability checks: refuse rather than change what the stages decide.
    if _comparable(new.screen_candidate()) != _legacy_screen(preferences) and preferences is not None:
        out("refused: the migrated hard requirements would screen differently")
        return 2
    if jev_texts is not None and _policy(new.triage_texts()) != _policy(jev_texts):
        out("refused: the migrated triage inputs would change the JEV policy hash")
        return 2

    with closing(db.connect(db_path)) as conn:
        try:
            existing = db.get_candidate_profile(conn)
        except sqlite3.OperationalError:
            out("refused: no candidate_profile table; run `npx prisma db push` in apps/web first")
            return 2
        if existing is not None:
            if profile.from_row(existing) == profile.from_row({**values, "version": existing["version"]}):
                out("already migrated: the stored candidate profile matches the legacy inputs")
                return 0
            untouched = (existing["actor"] == "config" and existing["version"] == 1
                         and existing["changed_at"] is None)
            if not untouched:
                out("refused: a candidate profile was already edited (actor "
                    f"{existing['actor']}, version {existing['version']}); nothing written")
                return 2
        changed_at = preferences.get("changed_at") if preferences else None
        db.write_candidate_profile(conn, values, actor="migration", now=now, confirmed_at=now,
                                   changed_at=changed_at, replace=existing is not None)
    p = new
    out("migrated the candidate profile"
        + (" (replaced an untouched config seed)" if existing is not None else ""))
    out(f"  search scope: {len(p.title_include)} include, {len(p.title_exclude)} exclude, "
        f"max_age_days {p.max_age_days}")
    out("  requirements: " + ("screen unchanged; " if preferences is not None else
                              "no legacy requirements, seeded from config.yaml; ")
        + f"highest degree {p.highest_degree or '(not screened)'}")
    out("  triage: " + ("not configured" if p.triage_context() is None else
                        ("policy hash unchanged; " if jev_texts is not None else "")
                        + ("custom context (verbatim)" if p.custom_triage_context else "rendered context")
                        + ", " + ("custom packs" if p.custom_packs else "default packs")))
    out("The legacy tables are gone from the live DB; the backup keeps them.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m ats_worker.migrate_profile",
                                     description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="copy the DB before the schema push")
    b.add_argument("--db", required=True)
    m = sub.add_parser("migrate", help="write the candidate profile from the backup")
    m.add_argument("--db", required=True)
    m.add_argument("--legacy-db", required=True,
                   help="the backup holding candidate_preferences / jev_profile")
    m.add_argument("--config", required=True,
                   help="config.yaml (title filters, max_age_days, jev_dir)")
    args = parser.parse_args(argv)
    if args.cmd == "backup":
        try:
            print(f"backed up to {backup(args.db)}")
        except MigrationError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        return 0
    return migrate(args.db, args.legacy_db, config_mod.load_config(args.config), now=_now())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
