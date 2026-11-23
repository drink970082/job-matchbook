from __future__ import annotations

import json

from ats_worker import db, pipeline
from ats_worker.screening import engine as screen_engine
from tests._helpers import NOW, bootstrap_db, make_posting


def _screen_result(*, disqualified=False):
    return {
        "screen": {"degree": {"pass": True, "note": ""}},
        "disqualified": disqualified,
        "disqualification_reason": "test" if disqualified else "",
    }


def _run(conn, screen_fn, *, now=NOW, candidate=None, limit=40, extract=object(), clock=None):
    return pipeline.run_screen(
        conn, now=now, screen_fn=screen_fn, extract=extract, candidate=candidate,
        backend="codex", model="gpt-5.6-luna", effort="medium", limit=limit,
        screen_workers=1, clock=clock,
    )


def test_provider_preflight_matches_screening_gates():
    extract = object()
    assert screen_engine.screen_requires_provider(
        make_posting("needs"), extract=extract, candidate={"highest_degree": "bachelor"})
    assert not screen_engine.screen_requires_provider(
        make_posting("none"), extract=extract, candidate=None)
    assert not screen_engine.screen_requires_provider(
        make_posting("no-provider"), extract=None,
        candidate={"highest_degree": "bachelor"})
    assert not screen_engine.screen_requires_provider(
        make_posting("intern", job_title="Software Intern"), extract=extract,
        candidate={"highest_degree": "bachelor", "exclude_internships": True})


def test_screen_results_cache_and_leave_fit_lifecycle_unchanged(tmp_path):
    path = bootstrap_db(tmp_path / "screen.db")
    conn = db.connect(path)
    try:
        db.upsert_postings(conn, [make_posting("old"), make_posting("new")], now=NOW)
        conn.execute(
            "UPDATE job_postings SET score_detail='legacy bytes' WHERE external_id='new'"
        )
        conn.commit()
        before = tuple(conn.execute(
            "SELECT pipeline_status, score_detail, application_id FROM job_postings "
            "WHERE external_id='new'"
        ).fetchone())
        calls = []

        def screen_fn(posting):
            calls.append(posting["external_id"])
            return _screen_result()

        _run(conn, screen_fn, candidate={"highest_degree": "bachelor"}, limit=1)
        assert calls == ["new"]
        after = tuple(conn.execute(
            "SELECT pipeline_status, score_detail, application_id FROM job_postings "
            "WHERE external_id='new'"
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
        original_updated_at = conn.execute(
            "SELECT job_screenings.updated_at FROM job_screenings JOIN job_postings "
            "ON job_postings.id=job_screenings.job_posting_id WHERE external_id='new'"
        ).fetchone()[0]

        # The older never-screened row is reached next; the successful row stays cached.
        later_timestamp = "2026-06-04T10:00:00.000Z"
        clock_samples = []

        def later_clock():
            clock_samples.append(later_timestamp)
            return later_timestamp

        _run(conn, screen_fn, candidate={"highest_degree": "bachelor"}, limit=1,
             clock=later_clock)
        assert clock_samples == [later_timestamp]
        assert conn.execute(
            "SELECT job_screenings.updated_at FROM job_screenings JOIN job_postings "
            "ON job_postings.id=job_screenings.job_posting_id WHERE external_id='new'"
        ).fetchone()[0] == original_updated_at
        assert conn.execute(
            "SELECT job_screenings.updated_at FROM job_screenings JOIN job_postings "
            "ON job_postings.id=job_screenings.job_posting_id WHERE external_id='old'"
        ).fetchone()[0] == later_timestamp
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
            return screen_engine.screen_posting(posting, extract=extract, candidate=candidate)

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


def _verdicts(conn):
    return {r["external_id"]: r["verdict"] for r in conn.execute(
        "SELECT external_id, verdict FROM job_postings ORDER BY id")}


def test_a_finished_screen_writes_the_verdict_and_its_profile_version(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "verdict.db"))
    db.upsert_postings(conn, [make_posting("pass"), make_posting("fail")], now=NOW)

    def screen_fn(posting):
        return _screen_result(disqualified=posting["external_id"] == "fail")

    pipeline.run_screen(conn, now=NOW, screen_fn=screen_fn, extract=object(),
                        candidate={"highest_degree": "bachelor"}, backend="codex",
                        model="m", effort=None, profile_version=5, triage=False)
    # No triage stage configured: passing the requirements is the final keep.
    assert _verdicts(conn) == {"pass": "keep", "fail": "discarded"}
    assert {r[0] for r in conn.execute("SELECT profile_version FROM job_screenings")} == {5}
    assert {r[0] for r in conn.execute("SELECT verdict_at FROM job_postings")} == {NOW}


def test_a_passing_screen_stays_pending_when_triage_is_next(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "pending.db"))
    db.upsert_postings(conn, [make_posting("pass"), make_posting("fail")], now=NOW)

    def screen_fn(posting):
        return _screen_result(disqualified=posting["external_id"] == "fail")

    pipeline.run_screen(conn, now=NOW, screen_fn=screen_fn, extract=object(),
                        candidate={"highest_degree": "bachelor"}, backend="codex",
                        model="m", effort=None, triage=True)
    assert _verdicts(conn) == {"pass": "pending", "fail": "discarded"}


def test_the_screen_runs_only_inside_the_window_and_only_on_pending_rows(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "window.db"))
    # NOW is 2026-06-04: the 7-day window starts 2026-05-28.
    db.upsert_postings(conn, [make_posting("edge", posted_at="2026-05-28"),
                              make_posting("old", posted_at="2026-05-27"),
                              make_posting("dated-by-ingest", posted_at=None),
                              make_posting("settled")], now=NOW)
    conn.execute("UPDATE job_postings SET posted_at=NULL, created_at='2026-05-01T00:00:00.000Z' "
                 "WHERE external_id='dated-by-ingest'")
    conn.execute("UPDATE job_postings SET verdict='keep' WHERE external_id='settled'")
    conn.commit()
    calls = []

    def screen_fn(posting):
        calls.append(posting["external_id"])
        return _screen_result()

    _run(conn, screen_fn, candidate={"highest_degree": "bachelor"})
    assert calls == ["edge"]


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


def test_screen_saves_sample_clock_after_each_result_on_the_db_thread(db_path):
    import threading

    conn = db.connect(db_path)
    try:
        db.upsert_postings(conn, [make_posting("first"), make_posting("second")], now=NOW)
        current_time = ["2026-06-04T08:00:00.000Z"]
        finished = []
        sampled = []
        db_thread = threading.get_ident()

        def screen(posting):
            if posting["external_id"] == "second":
                current_time[0] = "2026-06-04T08:30:00.000Z"
            else:
                current_time[0] = "2026-06-04T09:05:00.000Z"
            finished.append(posting["external_id"])
            return _screen_result()

        def clock():
            sampled.append((current_time[0], tuple(finished), threading.get_ident()))
            return current_time[0]

        _run(conn, screen, candidate={"highest_degree": "bachelor"}, clock=clock)
        rows = conn.execute(
            "SELECT p.external_id,s.last_attempted_at,s.completed_at,s.created_at,s.updated_at "
            "FROM job_screenings s JOIN job_postings p ON p.id=s.job_posting_id"
        ).fetchall()
        persisted = {row[0]: tuple(row[1:]) for row in rows}
        assert persisted["second"] == ("2026-06-04T08:30:00.000Z",) * 4
        assert persisted["first"] == ("2026-06-04T09:05:00.000Z",) * 4
        assert sampled == [
            ("2026-06-04T08:30:00.000Z", ("second",), db_thread),
            ("2026-06-04T09:05:00.000Z", ("second", "first"), db_thread),
        ]
    finally:
        conn.close()


def test_unlimited_screen_exceeds_default_cap_and_still_caches_success(db_path):
    conn = db.connect(db_path)
    try:
        db.upsert_postings(conn, [make_posting(str(i)) for i in range(45)], now=NOW)
        calls = []
        def screen(posting):
            calls.append(posting["id"])
            return _screen_result()
        first = _run(conn, screen, candidate={"highest_degree": "bachelor"}, limit=None)
        assert first["attempted"] == 45 and first["saved"] == 45
        second = _run(conn, screen, candidate={"highest_degree": "bachelor"}, limit=None)
        assert second["attempted"] == 0 and len(calls) == 45
    finally:
        conn.close()


def test_unlimited_screen_retains_dead_provider_breaker(db_path):
    conn = db.connect(db_path)
    try:
        db.upsert_postings(conn, [make_posting(str(i)) for i in range(45)], now=NOW)
        calls = []
        def fail(posting):
            calls.append(posting["id"])
            return {"provider_error": True}
        result = _run(conn, fail, candidate={"highest_degree": "bachelor"}, limit=None)
        assert 0 < result["attempted"] < 45
        assert len(calls) == result["errors"] == result["attempted"]
        assert conn.execute("SELECT COUNT(*) FROM job_screenings WHERE state='complete'").fetchone()[0] == 0
    finally:
        conn.close()
