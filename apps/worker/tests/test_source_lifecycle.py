from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests

from ats_worker import db, pipeline
from ats_worker.source_lifecycle import assessment_freshness, assessment_input_hash
from tests._helpers import LONG_DESC, NOW, make_posting

LATER = "2026-06-04T09:00:00.000Z"


def _insert(conn, external_id, *, status="new", score_detail=None, source="smartrecruiters"):
    db.upsert_postings(conn, [make_posting(external_id, source=source)], now=NOW)
    conn.execute("UPDATE job_postings SET pipeline_status=?,score_detail=? WHERE external_id=?",
                 (status, json.dumps(score_detail) if score_detail is not None else None,
                  external_id))
    conn.commit()
    return conn.execute("SELECT * FROM job_postings WHERE external_id=?", (external_id,)).fetchone()


def _available(row, **changes):
    posting = {key: row[key] for key in (
        "source", "external_id", "company_name", "job_title", "location", "job_url",
        "description",
    )}
    posting.update(changes)
    return {"state": "available", "posting": posting, "error_category": None}


def test_ingest_versions_complete_content_and_duplicate_only_refreshes_seen(db_path):
    conn = db.connect(db_path)
    first = make_posting("sr-1", source="smartrecruiters")
    assert db.upsert_postings(conn, [first], now=NOW) == 1
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    original_hash = assessment_input_hash(first)
    assert row["source_state"] == "available"
    assert row["source_last_seen_at"] == NOW
    assert row["source_content_hash"] == original_hash
    assert row["source_content_revision"] == 1

    duplicate = {**first, "job_title": "Changed from listing path"}
    assert db.upsert_postings(conn, [duplicate], now=LATER) == 0
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["job_title"] == first["job_title"]
    assert row["source_content_hash"] == original_hash
    assert row["source_content_revision"] == 1
    assert row["source_last_seen_at"] == LATER


def test_candidate_selection_uses_fit_assessment_and_protected_link(db_path):
    conn = db.connect(db_path)
    states = ["new", "failed", "discarded", "expired", "scored", "notified", "applied"]
    rows = {}
    for i, state in enumerate(states):
        rows[state] = _insert(conn, state, status=state)
    fit = _insert(conn, "fit", score_detail={"assessment": {"domain": {"verdict": "match"}}})
    linked = _insert(conn, "linked")
    conn.execute("INSERT INTO applications(company_name,job_title,date_applied,status) "
                 "VALUES ('A','B','2026-01-01','Applied')")
    conn.execute("UPDATE job_postings SET application_id=1 WHERE id=?", (linked["id"],))
    conn.execute("INSERT INTO status_history(application_id,status,timestamp) "
                 "VALUES (1,'Applied','2026-01-01T00:00:00Z')")
    conn.execute("UPDATE job_postings SET score_detail='not json' WHERE external_id='failed'")
    conn.commit()

    candidates = db.get_unscored_refresh_candidates(conn, "smartrecruiters", 25)
    ids = {row["external_id"] for row in candidates}
    assert ids == {"new", "failed", "discarded", "expired", "linked"} - {"linked"}
    # A numeric score or malformed score_detail is not a fit assessment.
    conn.execute("UPDATE job_postings SET score=0 WHERE external_id='new'")
    conn.commit()
    assert "new" in {row["external_id"] for row in
                      db.get_unscored_refresh_candidates(conn, "smartrecruiters", 25)}
    assert fit["external_id"] == "fit"
    assert not db.save_source_observation(
        conn, linked["id"], expected_source="smartrecruiters", expected_external_id="linked",
        observation={"state": "closed"}, now=LATER,
    )
    assert conn.execute("SELECT status FROM applications WHERE id=1").fetchone()[0] == "Applied"
    assert conn.execute("SELECT COUNT(*) FROM status_history WHERE application_id=1").fetchone()[0] == 1


def test_unchanged_observation_refreshes_times_without_revision_change(db_path, capsys):
    conn = db.connect(db_path)
    _insert(conn, "same")
    _insert(conn, "future", status="future_lifecycle")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    result = pipeline.run_unscored_refresh(
        conn, source="smartrecruiters", limit=25, now=LATER,
        observation_fn=lambda *_: _available(row),
    )
    current = conn.execute("SELECT * FROM job_postings").fetchone()
    assert result == {"selected": 1, "found": 1, "changed": 0, "closed": 0,
                      "inconclusive": 0, "skipped": 1}
    assert current["source_last_seen_at"] == LATER
    assert current["source_last_checked_at"] == LATER
    assert current["source_content_revision"] == 1
    assert current["pipeline_status"] == "new"
    assert "[source-refresh]" in capsys.readouterr().out


def test_changed_content_stales_completed_screen_without_provider_rerun(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "changed")
    db.save_screening(conn, row["id"], state="complete",
                      result={"screen": {"degree": {"pass": True}}},
                      error_category=None, backend="test", model=None, effort=None,
                      evaluator_version="test-v1", now=NOW)
    before = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    observed = _available(before, job_title="Senior Software Engineer",
                           description=LONG_DESC + "Updated requirements.")
    called = []
    result = pipeline.run_unscored_refresh(
        conn, source="smartrecruiters", limit=25, now=LATER,
        observation_fn=lambda *_: called.append("source") or observed,
    )
    current = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    screening = conn.execute("SELECT * FROM job_screenings WHERE job_posting_id=?",
                             (row["id"],)).fetchone()
    assert result["changed"] == 1
    assert called == ["source"]
    assert current["job_title"] == "Senior Software Engineer"
    assert current["source_content_revision"] == 2
    assert screening["source_content_revision"] == 1
    assert assessment_freshness(assessed=True, captured_revision=1,
                                current_revision=2) == "stale"
    assert current["pipeline_status"] == "new"


def test_changed_content_attributes_legacy_unversioned_screen_to_prior_revision(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "legacy")
    db.save_screening(conn, row["id"], state="complete", result={"screen": {}},
                      error_category=None, backend="test", model=None, effort=None,
                      evaluator_version="test-v1", now=NOW)
    conn.execute("UPDATE job_screenings SET source_content_revision=NULL WHERE job_posting_id=?",
                 (row["id"],))
    conn.commit()
    before = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters",
        expected_external_id="legacy",
        observation=_available(before, job_title="Changed title"), now=LATER,
    )
    current = conn.execute("SELECT source_content_revision FROM job_postings WHERE id=?",
                           (row["id"],)).fetchone()[0]
    captured = conn.execute("SELECT source_content_revision FROM job_screenings "
                             "WHERE job_posting_id=?", (row["id"],)).fetchone()[0]
    assert (current, captured) == (2, 1)


def test_combined_screen_only_discard_captures_revision_and_is_refreshable(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "combined", status="new")
    detail = {"screen": {"degree": {"pass": False}}, "disqualified": True}
    db.save_score(conn, row["id"], score=0, score_detail=detail,
                  status="discarded", now=NOW)
    stored = json.loads(conn.execute("SELECT score_detail FROM job_postings WHERE id=?",
                                     (row["id"],)).fetchone()[0])
    assert stored["source_content_revision"] == 1
    assert db.get_unscored_refresh_candidates(conn, "smartrecruiters", 25)

    before = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters", expected_external_id="combined",
        observation=_available(before, description=LONG_DESC + "Changed."), now=LATER,
    )
    changed = conn.execute("SELECT score_detail,source_content_revision,pipeline_status "
                           "FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    stored = json.loads(changed["score_detail"])
    assert changed["source_content_revision"] == 2
    assert stored["source_content_revision"] == 1
    assert changed["pipeline_status"] == "discarded"


def test_closure_inconclusive_and_reopening_preserve_pipeline_and_content(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "cycle")
    original = dict(conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone())
    assert db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters", expected_external_id="cycle",
        observation={"state": "closed"}, now=LATER,
    )
    closed = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert closed["source_state"] == "closed"
    assert closed["source_last_check_outcome"] == "confirmed_closed"
    assert closed["source_last_seen_at"] == original["source_last_seen_at"]
    assert closed["description"] == original["description"]
    assert closed["pipeline_status"] == "new"

    retry = "2026-06-04T10:00:00.000Z"
    assert db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters", expected_external_id="cycle",
        observation={"state": "unknown", "error_category": "timeout"}, now=retry,
    )
    inconclusive = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert inconclusive["source_state"] == "closed"
    assert inconclusive["source_last_checked_at"] == LATER
    assert inconclusive["source_last_check_attempted_at"] == retry
    assert inconclusive["source_last_check_error_category"] == "timeout"

    reopened = _available(inconclusive)
    assert db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters", expected_external_id="cycle",
        observation=reopened, now="2026-06-04T11:00:00.000Z",
    )
    current = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert current["source_state"] == "available"
    assert current["source_last_check_outcome"] == "found"
    assert current["source_last_check_error_category"] is None
    assert current["pipeline_status"] == "new"


def test_list_observation_reopens_source_without_relabeling_detail_check(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "list-reopen")
    assert db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters",
        expected_external_id="list-reopen", observation={"state": "closed"}, now=LATER,
    )
    closed = dict(conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone())

    seen_at = "2026-06-04T10:30:00.000Z"
    db.upsert_postings(conn, [closed], now=seen_at)
    listed = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert listed["source_state"] == "available"
    assert listed["source_last_seen_at"] == seen_at
    assert listed["source_last_checked_at"] == LATER
    assert listed["source_last_check_outcome"] == "confirmed_closed"

    retry = "2026-06-04T11:00:00.000Z"
    assert db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters",
        expected_external_id="list-reopen",
        observation={"state": "unknown", "error_category": "timeout"}, now=retry,
    )
    current = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert current["source_state"] == "available"
    assert current["source_last_seen_at"] == seen_at
    assert current["source_last_checked_at"] == LATER
    assert current["source_last_check_attempted_at"] == retry
    assert current["source_last_check_outcome"] == "inconclusive"


def test_mismatched_identity_is_inconclusive_and_changes_no_content(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "expected")
    before = dict(conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone())
    observation = _available(before, external_id="other", job_title="Wrong job")
    assert db.save_source_observation(
        conn, row["id"], expected_source="smartrecruiters", expected_external_id="expected",
        observation=observation, now=LATER,
    )
    after = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert after["source_last_check_outcome"] == "inconclusive"
    assert after["source_last_check_error_category"] == "identity_mismatch"
    assert after["source_state"] == "available"
    assert after["job_title"] == before["job_title"]
    assert after["source_content_revision"] == before["source_content_revision"]


@pytest.mark.parametrize(("exception", "category"), [
    (requests.Timeout("sensitive response body"), "timeout"),
    (requests.ConnectionError("sensitive response body"), "connection_error"),
    *[(requests.HTTPError(response=SimpleNamespace(status_code=status)), category)
      for status, category in ((403, "http_403"), (404, "http_404"), (410, "http_410"),
                               (429, "http_429"), (503, "http_5xx"))],
])
def test_http_and_transport_failures_are_safe_inconclusive_results(db_path, exception, category):
    conn = db.connect(db_path)
    row = _insert(conn, "error")
    before = dict(conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone())
    result = pipeline.run_unscored_refresh(
        conn, source="smartrecruiters", limit=25, now=LATER,
        observation_fn=lambda *_: (_ for _ in ()).throw(exception),
    )
    after = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert result["inconclusive"] == 1
    assert after["source_state"] == "available"
    assert after["source_last_checked_at"] is None
    assert after["source_last_check_outcome"] == "inconclusive"
    assert after["source_last_check_error_category"] == category
    assert after["description"] == before["description"]
    assert "sensitive response body" not in after["source_last_check_error_category"]


def test_incomplete_detail_response_preserves_existing_source_evidence(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "incomplete")
    before = dict(conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone())
    result = pipeline.run_unscored_refresh(
        conn, source="smartrecruiters", limit=25, now=LATER,
        observation_fn=lambda *_: {
            "state": "unknown", "error_category": "incomplete_content",
        },
    )
    after = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert result["inconclusive"] == 1
    assert after["source_state"] == before["source_state"]
    assert after["source_last_checked_at"] == before["source_last_checked_at"]
    assert after["source_content_hash"] == before["source_content_hash"]
    assert after["source_content_revision"] == before["source_content_revision"]
    assert after["description"] == before["description"]


def test_concurrent_application_or_status_change_skips_fetched_result(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "raced")

    def observe(*_):
        conn.execute("UPDATE job_postings SET pipeline_status='applied' WHERE id=?", (row["id"],))
        conn.commit()
        return _available(row, job_title="Must not write")

    result = pipeline.run_unscored_refresh(
        conn, source="smartrecruiters", limit=25, now=LATER, observation_fn=observe,
    )
    current = conn.execute("SELECT * FROM job_postings WHERE id=?", (row["id"],)).fetchone()
    assert result["skipped"] == 1
    assert current["pipeline_status"] == "applied"
    assert current["job_title"] == row["job_title"]
    assert current["source_last_check_attempted_at"] is None


def test_completed_assessments_capture_posting_revision(db_path):
    conn = db.connect(db_path)
    row = _insert(conn, "versioned")
    detail = {"assessment": {"domain": {"verdict": "match"}}}
    db.save_screening(conn, row["id"], state="complete", result={"screen": {}},
                      error_category=None, backend="test", model=None, effort=None,
                      evaluator_version="test-v1", now=NOW)
    captured = conn.execute("SELECT source_content_revision FROM job_screenings "
                            "WHERE job_posting_id=?", (row["id"],)).fetchone()[0]
    assert captured == 1

    scored_row = _insert(conn, "versioned-fit")
    db.save_score(conn, scored_row["id"], score=80, score_detail=detail, now=NOW)
    scored = json.loads(conn.execute("SELECT score_detail FROM job_postings WHERE id=?",
                                     (scored_row["id"],)).fetchone()[0])
    assert scored["source_content_revision"] == 1
