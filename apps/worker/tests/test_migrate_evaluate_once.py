"""The one-time operator migration (#225) on scratch DBs built from the fixture schema."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from ats_worker import db, migrate_evaluate_once as mig
from tests._helpers import bootstrap_db, make_posting

NOW = "2026-11-22T12:00:00.000Z"
OLD = "2026-07-01T00:00:00.000Z"      # outside the 7-day window at NOW
RECENT = "2026-11-21T00:00:00.000Z"   # inside it
LEGACY = {"screen": {"location": {"pass": False, "note": "on-site in China"}},
          "disqualified": True, "disqualification_reason": "location: on-site in China"}


def _db(tmp_path, *, triage_roles='["Backend engineer"]', profile=True):
    path = bootstrap_db(tmp_path / "applications.db")
    conn = db.connect(path)
    if profile:
        conn.execute("INSERT INTO candidate_profile (id, target_roles, actor, updated_at) "
                     "VALUES (1, ?, 'migration', ?)", (triage_roles, NOW))
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('jev_current_policy_sha256', 'sha')")
    conn.commit()
    return path, conn


def _add(conn, ext, *, at=OLD, status="new", detail=None, screen=None, jev=None):
    """One posting as the pre-#225 worker left it; verdict is the db-push default."""
    db.upsert_postings(conn, [make_posting(ext, posted_at=at[:10])], now=at)
    pid = conn.execute("SELECT id FROM job_postings WHERE external_id=?", (ext,)).fetchone()[0]
    conn.execute("UPDATE job_postings SET pipeline_status=?, score_detail=? WHERE id=?",
                 (status, json.dumps(detail) if detail is not None else None, pid))
    if screen is not None:
        state, disq = screen
        conn.execute("INSERT INTO job_screenings (job_posting_id, state, result_json, backend, "
                     "evaluator_version, last_attempted_at, completed_at, created_at) "
                     "VALUES (?, ?, ?, 'ollama', 'screen-v1', ?, ?, ?)",
                     (pid, state, json.dumps({"screen": {}, "disqualified": disq})
                      if state == "complete" else None, at, at, at))
    if jev is not None:
        state, verdict = jev
        conn.execute("INSERT INTO job_jev_assessments (job_posting_id, state, verdict, model, "
                     "last_attempted_at, created_at) VALUES (?, ?, ?, 'm', ?, ?)",
                     (pid, state, verdict, at, at))
    conn.commit()
    return pid


def _verdicts(path):
    with sqlite3.connect(path) as conn:
        return dict(conn.execute("SELECT external_id, verdict FROM job_postings"))


def test_moves_legacy_discards_into_the_requirements_shape_and_backfills_verdicts(tmp_path):
    path, conn = _db(tmp_path)
    legacy = _add(conn, "legacy", status="discarded", detail=LEGACY)
    _add(conn, "rejected", screen=("complete", True))
    _add(conn, "kept", screen=("complete", False), jev=("complete", "keep"))
    _add(conn, "skipped", screen=("complete", False), jev=("complete", "skip"))
    _add(conn, "untriaged-old", screen=("complete", False))
    _add(conn, "untriaged-recent", at=RECENT, screen=("complete", False))
    _add(conn, "failed-recent", at=RECENT, screen=("provider_error", None))
    _add(conn, "unscreened-old")
    conn.close()
    lines = []
    assert mig.migrate(path, now=NOW, out=lines.append) == 0

    assert _verdicts(path) == {
        "legacy": "discarded", "rejected": "discarded", "kept": "keep", "skipped": "skip",
        # Triage is configured and has run: an untriaged pass waits inside the window.
        "untriaged-old": "not_evaluated", "untriaged-recent": "pending",
        "failed-recent": "pending", "unscreened-old": "not_evaluated"}
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        p = c.execute("SELECT * FROM job_postings WHERE id=?", (legacy,)).fetchone()
        s = c.execute("SELECT * FROM job_screenings WHERE job_posting_id=?", (legacy,)).fetchone()
        assert c.execute("SELECT COUNT(*) FROM app_settings "
                         "WHERE key='jev_current_policy_sha256'").fetchone()[0] == 0
    # The same shape a fetch-time discard has now (db.upsert_postings).
    assert (p["pipeline_status"], p["score_detail"], p["verdict_at"]) == ("new", None, OLD)
    assert json.loads(s["result_json"]) == LEGACY
    assert (s["state"], s["backend"], s["model"], s["evaluator_version"], s["completed_at"],
            s["profile_version"]) == ("complete", "deterministic", None, "screen-v1", OLD, None)
    assert any("1 legacy discard" in line for line in lines)
    backups = list(Path(path).parent.glob("applications.db.backup-*-pre-evaluate-once"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as b:
        assert b.execute("SELECT pipeline_status FROM job_postings WHERE id=?",
                         (legacy,)).fetchone()[0] == "discarded"

    # Idempotent: a second run reports and writes nothing.
    again = []
    assert mig.migrate(path, now="2026-11-23T00:00:00.000Z", out=again.append) == 0
    assert again == [mig.ALREADY]
    assert _verdicts(path)["untriaged-recent"] == "pending"


def test_a_migration_killed_mid_way_writes_nothing_and_a_rerun_completes(tmp_path, monkeypatch):
    """Move + backfill + setting delete + age-out are one transaction: a kill at the last
    phase leaves the legacy shape intact, so the rerun is not mistaken for 'migrated'."""
    path, conn = _db(tmp_path)
    _add(conn, "legacy", status="discarded", detail=LEGACY)
    _add(conn, "kept", screen=("complete", False), jev=("complete", "keep"))
    conn.close()

    def killed(*_a, **_k):
        raise KeyboardInterrupt
    monkeypatch.setattr(mig.db, "age_out", killed)
    with pytest.raises(KeyboardInterrupt):
        mig.migrate(path, now=NOW, out=lambda _l: None)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT pipeline_status FROM job_postings WHERE external_id='legacy'"
                         ).fetchone()[0] == "discarded"
        assert c.execute("SELECT COUNT(*) FROM job_screenings WHERE backend='deterministic'"
                         ).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 1
    assert set(_verdicts(path).values()) == {"pending"}

    monkeypatch.undo()
    assert mig.migrate(path, now=NOW, out=lambda _l: None) == 0
    assert _verdicts(path) == {"legacy": "discarded", "kept": "keep"}


def test_no_legacy_discard_still_backfills_unsettled_verdicts(tmp_path):
    """An install with zero legacy discards is not 'already migrated' while a finished
    screen discard or triage verdict sits on a pending posting."""
    path, conn = _db(tmp_path)
    _add(conn, "rejected", screen=("complete", True))
    _add(conn, "kept", screen=("complete", False), jev=("complete", "keep"))
    conn.close()
    lines = []
    assert mig.migrate(path, now=NOW, out=lines.append) == 0
    assert mig.ALREADY not in lines
    assert _verdicts(path) == {"rejected": "discarded", "kept": "keep"}
    with closing(db.connect(path)) as c:
        assert not db.needs_evaluate_once_migration(c)


def test_without_triage_a_passing_screen_backfills_keep(tmp_path):
    path, conn = _db(tmp_path, triage_roles="[]")
    _add(conn, "passed", screen=("complete", False))
    conn.close()
    assert mig.migrate(path, now=NOW, out=lambda _l: None) == 0
    assert _verdicts(path) == {"passed": "keep"}


def test_a_rerun_is_a_no_op_even_after_triage_is_unconfigured(tmp_path):
    """The migration commits a marker with its writes; a later rerun reads it and does
    not settle a pass left pending under triage as `keep` (SPEC: nothing does)."""
    path, conn = _db(tmp_path)
    _add(conn, "kept", screen=("complete", False), jev=("complete", "keep"))
    _add(conn, "waiting", at=RECENT, screen=("complete", False))
    conn.close()
    assert mig.migrate(path, now=NOW, out=lambda _l: None) == 0
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT value FROM app_settings WHERE key=?",
                         (mig.MARKER,)).fetchone()[0] == NOW
        c.execute("UPDATE candidate_profile SET target_roles='[]'")
    lines = []
    assert mig.migrate(path, now=NOW, out=lines.append) == 0
    assert lines == [mig.ALREADY]
    assert _verdicts(path) == {"kept": "keep", "waiting": "pending"}


def test_refuses_triage_rows_without_a_candidate_profile(tmp_path):
    """Without the profile row (migrate_profile not run) triage looks unused and every
    pending pass would become keep: refuse, write nothing."""
    path, conn = _db(tmp_path, profile=False)
    _add(conn, "kept", screen=("complete", False), jev=("complete", "keep"))
    _add(conn, "waiting", at=RECENT, screen=("complete", False))
    conn.close()
    lines = []
    assert mig.migrate(path, now=NOW, out=lines.append) == 2
    assert "migrate_profile" in lines[0]
    assert set(_verdicts(path).values()) == {"pending"}
    assert not list(Path(path).parent.glob("*.backup-*"))


def test_without_triage_a_premature_pass_aged_out_is_backfilled_keep(tmp_path):
    """A no-triage pass run before the migration ages old passing screens out; the
    backfill settles them `keep` as it would have, and leaves a discarded one alone."""
    path, conn = _db(tmp_path, triage_roles="[]")
    _add(conn, "passed", screen=("complete", False))
    _add(conn, "unscreened")
    conn.execute("UPDATE job_postings SET verdict='not_evaluated', verdict_at=?", (NOW,))
    conn.commit()
    conn.close()
    assert mig.migrate(path, now=NOW, out=lambda _l: None) == 0
    assert _verdicts(path) == {"passed": "keep", "unscreened": "not_evaluated"}


@pytest.mark.parametrize("detail,why", [
    ({**LEGACY, "assessment": {}}, "unexpected score_detail"),
    ({**LEGACY, "disqualified": False}, "unexpected score_detail"),
    (None, "unexpected score_detail"),
])
def test_refuses_an_unexpected_discard_and_writes_nothing(tmp_path, detail, why):
    path, conn = _db(tmp_path)
    _add(conn, "odd", status="discarded", detail=detail)
    conn.close()
    lines = []
    assert mig.migrate(path, now=NOW, out=lines.append) == 2
    assert why in lines[0]
    assert _verdicts(path) == {"odd": "pending"}
    assert not list(Path(path).parent.glob("*.backup-*"))


def test_refuses_a_discard_that_already_has_a_screen(tmp_path):
    path, conn = _db(tmp_path)
    _add(conn, "both", status="discarded", detail=LEGACY, screen=("complete", True))
    conn.close()
    lines = []
    assert mig.migrate(path, now=NOW, out=lines.append) == 2
    assert "already has a job_screenings row" in lines[0]


def test_refuses_before_the_schema_push(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE job_postings (id INTEGER PRIMARY KEY, pipeline_status TEXT)")
    lines = []
    assert mig.migrate(str(path), now=NOW, out=lines.append) == 2
    assert "prisma db push" in lines[0]


def test_main_reports_a_missing_db(tmp_path, capsys):
    assert mig.main(["migrate", "--db", str(tmp_path / "missing.db")]) == 2
    assert "refused" in capsys.readouterr().out
