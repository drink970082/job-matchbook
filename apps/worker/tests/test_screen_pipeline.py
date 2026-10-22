from __future__ import annotations

import json

from ats_worker import db, pipeline, score
from tests._helpers import NOW, bootstrap_db, make_posting


def _screen_result(*, disqualified=False):
    return {
        "screen": {"degree": {"pass": True, "note": ""}},
        "disqualified": disqualified,
        "disqualification_reason": "test" if disqualified else "",
    }


def _run(conn, screen_fn, *, now=NOW, candidate=None, limit=40, extract=object()):
    return pipeline.run_screen(
        conn, now=now, screen_fn=screen_fn, extract=extract, candidate=candidate,
        backend="codex", model="gpt-5.6-luna", effort="medium", limit=limit,
        screen_workers=1,
    )


def test_provider_preflight_matches_screening_gates():
    extract = object()
    assert score.screen_requires_provider(
        make_posting("needs"), extract=extract, candidate={"highest_degree": "bachelor"})
    assert not score.screen_requires_provider(
        make_posting("none"), extract=extract, candidate=None)
    assert not score.screen_requires_provider(
        make_posting("no-provider"), extract=None,
        candidate={"highest_degree": "bachelor"})
    assert not score.screen_requires_provider(
        make_posting("intern", job_title="Software Intern"), extract=extract,
        candidate={"highest_degree": "bachelor", "exclude_internships": True})


def test_screen_results_cache_and_leave_fit_lifecycle_unchanged(tmp_path):
    path = bootstrap_db(tmp_path / "screen.db")
    conn = db.connect(path)
    try:
        db.upsert_postings(conn, [make_posting("old"), make_posting("new")], now=NOW)
        conn.execute(
            "UPDATE job_postings SET score=61, score_detail='legacy bytes', attempts=2, "
            "notify_attempts=1 WHERE external_id='new'"
        )
        conn.commit()
        before = tuple(conn.execute(
            "SELECT pipeline_status, score, score_detail, attempts, notify_attempts, "
            "application_id FROM job_postings WHERE external_id='new'"
        ).fetchone())
        calls = []

        def screen_fn(posting):
            calls.append(posting["external_id"])
            return _screen_result()

        _run(conn, screen_fn, candidate={"highest_degree": "bachelor"}, limit=1)
        assert calls == ["new"]
        after = tuple(conn.execute(
            "SELECT pipeline_status, score, score_detail, attempts, notify_attempts, "
            "application_id FROM job_postings WHERE external_id='new'"
        ).fetchone())
        assert after == before
        saved = conn.execute(
            "SELECT state, result_json, backend, model, effort, evaluator_version "
            "FROM job_screenings JOIN job_postings "
            "ON job_postings.id=job_screenings.job_posting_id "
            "WHERE external_id='new'"
        ).fetchone()
        assert saved["state"] == "complete"
        assert json.loads(saved["result_json"]) == _screen_result()
        assert tuple(saved)[2:] == (
            "codex", "gpt-5.6-luna", "medium", pipeline.SCREEN_EVALUATOR_VERSION)

        # The older never-screened row is reached next; the successful row stays cached.
        _run(conn, screen_fn, candidate={"highest_degree": "bachelor"}, limit=1)
        _run(conn, screen_fn, candidate={"highest_degree": "bachelor"}, limit=1)
        assert calls == ["new", "old"]
    finally:
        conn.close()


def test_provider_cap_counts_failures_and_errors_retry_oldest_first(tmp_path):
    path = bootstrap_db(tmp_path / "screen-errors.db")
    conn = db.connect(path)
    try:
        db.upsert_postings(conn, [make_posting("one"), make_posting("two")], now=NOW)
        candidate = {"highest_degree": "bachelor"}
        attempted = []

        def fail(posting):
            attempted.append(posting["external_id"])
            return {"provider_error": True, "provider_error_category": "provider_error"}

        _run(conn, fail, candidate=candidate, limit=2)
        assert attempted == ["two", "one"]
        assert conn.execute(
            "SELECT COUNT(*) FROM job_screenings WHERE state='provider_error'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT DISTINCT error_message FROM job_screenings"
        ).fetchone()[0] == "Screen provider failed; retry is pending."

        attempted.clear()
        _run(conn, lambda p: attempted.append(p["external_id"]) or _screen_result(),
             now="2026-06-04T10:00:00.000Z", candidate=candidate, limit=1)
        # Both errors share the first attempt time, so the stable id tiebreak retries id 1.
        assert attempted == ["one"]
        states = dict(conn.execute(
            "SELECT p.external_id, s.state FROM job_screenings s "
            "JOIN job_postings p ON p.id=s.job_posting_id"
        ).fetchall())
        assert states == {"one": "complete", "two": "provider_error"}
    finally:
        conn.close()


def test_deterministic_rows_finish_after_provider_cap(tmp_path):
    path = bootstrap_db(tmp_path / "screen-deterministic.db")
    conn = db.connect(path)
    try:
        # Insert the deterministic row first so the provider row is the newer queue head.
        db.upsert_postings(conn, [
            make_posting("intern", job_title="Intern Software Engineer"),
            make_posting("provider"),
        ], now=NOW)
        candidate = {"highest_degree": "bachelor", "exclude_internships": True}
        provider_calls = []

        def extract(_prompt, _schema):
            provider_calls.append(True)
            return {"screen": {}}

        def screen_fn(posting):
            return score.screen_posting(posting, extract=extract, candidate=candidate)

        _run(conn, screen_fn, candidate=candidate, limit=1, extract=extract)
        assert len(provider_calls) == 1
        intern = conn.execute(
            "SELECT s.state, s.result_json FROM job_screenings s "
            "JOIN job_postings p ON p.id=s.job_posting_id WHERE p.external_id='intern'"
        ).fetchone()
        assert intern["state"] == "complete"
        assert json.loads(intern["result_json"])["disqualified"] is True
        assert conn.execute(
            "SELECT COUNT(*) FROM job_screenings WHERE state='complete'"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_rescreen_clears_only_successes_for_still_new_rows(tmp_path):
    path = bootstrap_db(tmp_path / "screen-reset.db")
    conn = db.connect(path)
    try:
        db.upsert_postings(conn, [make_posting("new"), make_posting("discarded")], now=NOW)
        rows = conn.execute("SELECT id, external_id FROM job_postings").fetchall()
        for row in rows:
            db.save_screening(
                conn, row["id"], state="complete", result=_screen_result(),
                error_category=None, backend="codex", model="gpt-5.6-luna",
                effort="medium", evaluator_version="screen-v1", now=NOW)
        conn.execute("UPDATE job_postings SET pipeline_status='discarded' "
                     "WHERE external_id='discarded'")
        conn.commit()
        assert db.clear_completed_screenings(conn) == 1
        remaining = conn.execute(
            "SELECT p.external_id FROM job_screenings s "
            "JOIN job_postings p ON p.id=s.job_posting_id"
        ).fetchall()
        assert [row[0] for row in remaining] == ["discarded"]
    finally:
        conn.close()


def test_screen_result_is_not_saved_if_lifecycle_changes_during_provider_call(tmp_path):
    path = bootstrap_db(tmp_path / "screen-race.db")
    conn = db.connect(path)
    try:
        db.upsert_postings(conn, [make_posting("raced")], now=NOW)

        def screen_fn(_posting):
            other = db.connect(path)
            try:
                other.execute("UPDATE job_postings SET pipeline_status='discarded'")
                other.commit()
            finally:
                other.close()
            return _screen_result()

        tally = _run(conn, screen_fn, candidate={"highest_degree": "bachelor"})
        assert tally["changed"] == 1
        assert conn.execute("SELECT COUNT(*) FROM job_screenings").fetchone()[0] == 0
    finally:
        conn.close()


def test_provider_exception_text_is_not_persisted(tmp_path):
    path = bootstrap_db(tmp_path / "screen-safe-error.db")
    conn = db.connect(path)
    try:
        db.upsert_postings(conn, [make_posting("bad")], now=NOW)

        def fail(_posting):
            raise RuntimeError("secret JD and token=do-not-store")

        _run(conn, fail, candidate={"highest_degree": "bachelor"})
        stored = tuple(conn.execute(
            "SELECT error_category, error_message, result_json FROM job_screenings"
        ).fetchone())
        assert stored == ("screen_error", "Screen provider failed; retry is pending.", None)
    finally:
        conn.close()


def test_screen_provider_cap_preserves_existing_deprioritized_queue(db_path):
    conn = db.connect(db_path)
    try:
        db.upsert_postings(conn, [make_posting('older-priority'),
                                  make_posting('newer-demoted')], now=NOW)
        conn.execute("UPDATE job_postings SET deprioritized_at=? WHERE external_id=?",
                     (NOW, 'newer-demoted'))
        conn.commit()
        attempted = []

        def screen(posting):
            attempted.append(posting['external_id'])
            return _screen_result()

        _run(conn, screen, candidate={'highest_degree': 'bachelor'}, limit=1)
        assert attempted == ['older-priority']
        _run(conn, screen, candidate={'highest_degree': 'bachelor'}, limit=1)
        assert attempted == ['older-priority', 'newer-demoted']
    finally:
        conn.close()
