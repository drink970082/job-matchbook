"""The one-time operator migration (#224) on scratch DBs built from the fixture schema."""
from __future__ import annotations

import json
import sqlite3

import pytest

from ats_worker import config as cfgmod
from ats_worker import db, jev, migrate_profile, profile
from tests._helpers import NOW, bootstrap_db, make_posting

# The two legacy tables exactly as the pre-#224 Prisma schema created them.
LEGACY_DDL = """
CREATE TABLE "candidate_preferences" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "highest_degree" TEXT NOT NULL DEFAULT '', "work_authorization" TEXT NOT NULL DEFAULT '',
    "security_clearance" TEXT NOT NULL DEFAULT '', "locations" TEXT NOT NULL DEFAULT '[]',
    "exclude_internships" BOOLEAN NOT NULL DEFAULT false,
    "exclude_contract" BOOLEAN NOT NULL DEFAULT false, "version" INTEGER NOT NULL DEFAULT 1,
    "actor" TEXT NOT NULL, "changed_at" TEXT, "updated_at" TEXT NOT NULL);
CREATE TABLE "jev_profile" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "profile_text" TEXT NOT NULL,
    "c_pack" TEXT NOT NULL, "yoe_pack" TEXT NOT NULL, "yoe_context" TEXT NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1, "actor" TEXT NOT NULL, "changed_at" TEXT,
    "updated_at" TEXT NOT NULL);
"""
# Synthetic stand-ins for an operator's private free-text profile and measured packs.
PROFILE_TEXT = '{"domains": ["backend"], "profile": "Synthetic: backend engineer, café."}  '
C_PACK = {"version": "synthetic-c", "questions": [
    {"id": "preference", "type": "choice", "instructions": "p",
     "criteria": {"strong": "s", "plausible": "p", "weak": "w", "unknown": "u"}}]}
YOE_PACK = {"version": "synthetic-yoe", "questions": [
    {"id": "required_yoe_for_candidate", "type": "choice", "instructions": "y",
     "criteria": {"under_3": "a", "three_plus": "b", "not_stated": "c", "unclear": "d"}}]}


def _legacy(tmp_path, *, prefs=True, jev_row=True):
    path = tmp_path / "backup.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_DDL)
    if prefs:
        conn.execute("INSERT INTO candidate_preferences VALUES (1, 'BS in CS', 'needs visa sponsorship', "
                     "'', '[\"USA\",\"remote\"]', 1, 0, 2, 'web', '2026-11-19T00:00:00.000Z', "
                     "'2026-11-19T00:00:00.000Z')")
    if jev_row:
        conn.execute("INSERT INTO jev_profile VALUES (1, ?, ?, ?, 'Synthetic MS; no full-time years.', "
                     "1, 'config', NULL, '2026-11-18T00:00:00Z')",
                     (PROFILE_TEXT, json.dumps(C_PACK, indent=2), json.dumps(YOE_PACK)))
    conn.commit()
    conn.close()
    return str(path)


def _live(tmp_path):
    path = bootstrap_db(tmp_path / "applications.db")
    conn = db.connect(path)
    db.upsert_postings(conn, [make_posting("a")], now=NOW)
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    conn.execute("INSERT INTO job_screenings (job_posting_id, state, result_json, backend, "
                 "evaluator_version, last_attempted_at, completed_at, created_at) VALUES "
                 "(?, 'complete', '{\"disqualified\":false}', 'ollama', 'v', ?, ?, ?)", (pid, NOW, NOW, NOW))
    conn.execute("INSERT INTO job_jev_assessments (job_posting_id, state, verdict, model, "
                 "last_attempted_at, created_at, updated_at) VALUES "
                 "(?, 'complete', 'keep', 'm', ?, ?, ?)", (pid, NOW, NOW, NOW))
    conn.commit()
    conn.close()
    return path


def _verdicts(path):
    with sqlite3.connect(path) as conn:
        return [conn.execute(f"SELECT * FROM {t}").fetchall()
                for t in ("job_postings", "job_screenings", "job_jev_assessments")]


def _row(path):
    conn = db.connect(path)
    try:
        return db.get_candidate_profile(conn)
    finally:
        conn.close()


CFG = cfgmod.load_config("title_filter: [engineer]\ntitle_exclude: [sales]\nmax_age_days: 30\n")


def test_migrates_a_free_text_install_without_moving_any_verdict_input(tmp_path):
    live, legacy = _live(tmp_path), _legacy(tmp_path)
    before = _verdicts(live)
    lines = []
    assert migrate_profile.migrate(live, legacy, CFG, now=NOW, out=lines.append) == 0
    assert _verdicts(live) == before                        # no stored verdict touched
    row = _row(live)
    assert (row["actor"], row["version"], row["confirmed_at"], row["changed_at"]) == (
        "migration", 1, NOW, "2026-11-19T00:00:00.000Z")
    p = profile.from_row(row)
    assert (p.title_include, p.title_exclude, p.max_age_days) == (("engineer",), ("sales",), 30)
    # The screen: same requirements, degree at the legacy rank ('BS in CS' ranks 0).
    assert p.screen_candidate() == {
        "highest_degree": "none", "work_authorization": "needs visa sponsorship",
        "security_clearance": "", "locations": ["USA", "remote"], "exclude_internships": True,
        "exclude_contract": False}
    # Triage: the free text and the measured packs ride along verbatim, same policy hash.
    assert p.custom_triage_context["profile_text"] == PROFILE_TEXT
    legacy_texts = {"profile_text": PROFILE_TEXT, "c_pack": json.dumps(C_PACK, indent=2),
                    "yoe_pack": json.dumps(YOE_PACK), "yoe_context": "Synthetic MS; no full-time years."}
    assert (jev.inputs_from_texts(p.triage_texts()).policy_sha("m")
            == jev.inputs_from_texts(legacy_texts).policy_sha("m"))
    assert any("policy hash unchanged" in line for line in lines)

    # Idempotent: a second run writes nothing.
    again = []
    assert migrate_profile.migrate(live, legacy, CFG, now="2026-12-01T00:00:00Z", out=again.append) == 0
    assert again == ["already migrated: the stored candidate profile matches the legacy inputs"]
    assert _row(live)["updated_at"] == row["updated_at"]


def test_replaces_an_untouched_config_seed_but_never_an_edited_row(tmp_path):
    live, legacy = _live(tmp_path), _legacy(tmp_path)
    conn = db.connect(live)
    db.write_candidate_profile(conn, profile.seed_values(CFG), actor="config", now=NOW)
    conn.close()
    lines = []
    assert migrate_profile.migrate(live, legacy, CFG, now=NOW, out=lines.append) == 0
    assert "replaced an untouched config seed" in lines[0] and _row(live)["actor"] == "migration"

    with sqlite3.connect(live) as conn:
        conn.execute("UPDATE candidate_profile SET locations='[\"Boston\"]', version=2, actor='web', "
                     "changed_at='2026-11-21T00:00:00Z'")
    lines = []
    assert migrate_profile.migrate(live, legacy, CFG, now=NOW, out=lines.append) == 2
    assert "already edited" in lines[0] and _row(live)["locations"] == '["Boston"]'


def test_refuses_before_the_schema_push(tmp_path):
    live = tmp_path / "old.db"
    sqlite3.connect(live).executescript(LEGACY_DDL)
    lines = []
    assert migrate_profile.migrate(str(live), _legacy(tmp_path), CFG, now=NOW, out=lines.append) == 2
    assert "prisma db push" in lines[0]


def test_nothing_to_migrate_on_an_empty_install(tmp_path):
    lines = []
    legacy = _legacy(tmp_path, prefs=False, jev_row=False)
    assert migrate_profile.migrate(_live(tmp_path), legacy, cfgmod.Config(), now=NOW,
                                   out=lines.append) == 0
    assert lines == ["nothing to migrate: no legacy rows and no config.yaml candidate settings"]


def test_reads_jev_dir_when_no_jev_profile_row_exists(tmp_path):
    d = tmp_path / "jev"
    d.mkdir()
    (d / "profile-binding.json").write_text(PROFILE_TEXT, encoding="utf-8")
    (d / "question-pack.json").write_text(profile.default_packs()["preference_pack"], encoding="utf-8")
    (d / "yoe-pack.json").write_text(profile.default_packs()["yoe_pack"], encoding="utf-8")
    (d / "yoe-context.txt").write_text("Synthetic.\n", encoding="utf-8")
    live = _live(tmp_path)
    cfg = cfgmod.load_config(f"jev_dir: {d}\n")
    assert migrate_profile.migrate(live, _legacy(tmp_path, jev_row=False), cfg, now=NOW,
                                   out=lambda _: None) == 0
    p = profile.from_row(_row(live))
    assert p.custom_packs is None                           # the defaults: nothing to carry
    assert p.custom_triage_context == {"profile_text": PROFILE_TEXT, "yoe_context": "Synthetic."}


def test_refuses_a_seed_that_would_change_the_policy_hash(tmp_path, monkeypatch):
    live, legacy = _live(tmp_path), _legacy(tmp_path)
    real = profile.CandidateProfile.triage_texts
    monkeypatch.setattr(profile.CandidateProfile, "triage_texts",
                        lambda self: {**real(self), "yoe_context": "moved"})
    lines = []
    assert migrate_profile.migrate(live, legacy, CFG, now=NOW, out=lines.append) == 2
    assert "policy hash" in lines[0] and _row(live) is None


def test_refuses_a_seed_that_would_screen_differently(tmp_path, monkeypatch):
    live, legacy = _live(tmp_path), _legacy(tmp_path)
    monkeypatch.setattr(profile, "canonical_degree", lambda value: "phd")
    lines = []
    assert migrate_profile.migrate(live, legacy, CFG, now=NOW, out=lines.append) == 2
    assert "screen differently" in lines[0] and _row(live) is None


def test_cli_backs_up_then_migrates(tmp_path, capsys):
    live, legacy = _live(tmp_path), _legacy(tmp_path)
    with sqlite3.connect(live) as conn:                     # the pre-push live DB
        conn.executescript(LEGACY_DDL)
    assert migrate_profile.main(["backup", "--db", live]) == 0
    backup = capsys.readouterr().out.split("backed up to ")[1].strip()
    assert _verdicts(backup) == _verdicts(live)
    with pytest.raises(FileExistsError):
        migrate_profile.backup(live, stamp=backup.split(".backup-")[1].split("-pre-")[0])
    cfg = tmp_path / "config.yaml"
    cfg.write_text("title_filter: [engineer]\n")
    assert migrate_profile.main(["migrate", "--db", live, "--legacy-db", legacy,
                                 "--config", str(cfg)]) == 0
    assert "migrated the candidate profile" in capsys.readouterr().out
    with pytest.raises(SystemExit):                         # --config is required
        migrate_profile.main(["migrate", "--db", live, "--legacy-db", legacy])


def test_backup_of_a_mistyped_path_fails_and_creates_nothing(tmp_path, capsys):
    missing = tmp_path / "typo.db"
    assert migrate_profile.main(["backup", "--db", str(missing)]) == 2
    assert "refused" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []                   # neither the source nor a backup


def test_backup_without_the_legacy_tables_is_refused_and_deleted(tmp_path):
    live = _live(tmp_path)                                   # post-push: no legacy tables
    with pytest.raises(migrate_profile.MigrationError, match="no backup written"):
        migrate_profile.backup(live, stamp="x")
    assert not (tmp_path / "applications.db.backup-x-pre-candidate-profile").exists()


def test_migrate_refuses_a_legacy_db_without_the_legacy_tables(tmp_path):
    live = _live(tmp_path)
    lines = []
    assert migrate_profile.migrate(live, live, CFG, now=NOW, out=lines.append) == 2
    assert "no candidate_preferences or jev_profile" in lines[0] and _row(live) is None


def test_no_legacy_requirements_does_not_claim_an_unchanged_screen(tmp_path):
    live = _live(tmp_path)
    lines = []
    assert migrate_profile.migrate(live, _legacy(tmp_path, prefs=False), CFG, now=NOW,
                                   out=lines.append) == 0
    assert not any("screen unchanged" in line for line in lines)
    assert any("no legacy requirements" in line for line in lines)
