"""Security and behavior tests for the bounded read-only MCP repository."""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ats_worker.mcp.read_repository import (
    DatabaseUnavailable,
    QueryInputError,
    ReadOnlyATSRepository,
    RecordNotFound,
)
from tests._helpers import FIXTURES, bootstrap_db


def _job(conn, *, title="Engineer", company="Acme", status="new", description="JD",
         url="https://example.test/jobs/1", posted="2026-10-01"):
    cursor = conn.execute(
        "INSERT INTO job_postings(source,external_id,company_name,job_title,job_url,description,"
        "pipeline_status,created_at,posted_at) VALUES('custom',?,?,?,?,?,?,?,?)",
        (str(conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0] + 1), company,
         title, url, description, status, "2026-10-22T10:00:00Z", posted),
    )
    return cursor.lastrowid


def _application(conn, *, company="Acme", notes=None, status="Applied"):
    cursor = conn.execute(
        "INSERT INTO applications(company_name,job_title,application_url,date_applied,category,"
        "status,notes,last_updated) VALUES(?,?,?,?,?,?,?,?)",
        (company, "Engineer", "https://apply.test/form", "2026-10-20", "Engineering",
         status, notes, "2026-10-22"),
    )
    return cursor.lastrowid


def test_database_is_opened_read_only_and_query_only(db_path):
    repo = ReadOnlyATSRepository(db_path)
    with repo._connection() as conn:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO app_settings(key,value) VALUES('x','y')")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 0


def test_each_query_opens_a_live_connection_that_sees_committed_wal_writes(db_path):
    repo = ReadOnlyATSRepository(db_path)
    assert repo.list_jobs()["items"] == []
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA journal_mode=WAL")
    _job(writer)
    writer.commit()
    writer.close()
    assert len(repo.list_jobs()["items"]) == 1


def test_missing_or_incomplete_database_fails_safely_without_creating_file(tmp_path):
    missing = tmp_path / "private" / "missing.db"
    repo = ReadOnlyATSRepository(missing)
    with pytest.raises(DatabaseUnavailable) as exc:
        repo.get_ats_overview()
    assert "ATS_DB_PATH" in str(exc.value)
    assert str(tmp_path) not in str(exc.value)
    assert not missing.exists()

    incomplete = tmp_path / "incomplete.db"
    with sqlite3.connect(incomplete) as conn:
        conn.execute("CREATE TABLE applications(id INTEGER PRIMARY KEY)")
    with pytest.raises(DatabaseUnavailable, match="schema is incomplete"):
        ReadOnlyATSRepository(incomplete).get_ats_overview()


def test_overview_reconciles_counts_and_keeps_unknown_statuses(db_path):
    with sqlite3.connect(db_path) as conn:
        first = _job(conn, status="new")
        second = _job(conn, status="legacy-custom")
        _application(conn, status="Applied")
        _application(conn, status="future-status")
        conn.execute(
            "INSERT INTO job_screenings(job_posting_id,state,backend,evaluator_version,"
            "last_attempted_at,created_at) VALUES(?, 'complete','ollama','v1','now','now')",
            (first,),
        )
        conn.execute(
            "INSERT INTO job_screenings(job_posting_id,state,backend,evaluator_version,"
            "last_attempted_at,created_at) VALUES(?, 'future-state','ollama','v1','now','now')",
            (second,),
        )
    overview = ReadOnlyATSRepository(db_path).get_ats_overview()
    assert sum(row["count"] for row in overview["pipeline_status_counts"]) == 2
    assert overview["unknown_pipeline_statuses"] == ["legacy-custom"]
    assert overview["unknown_application_statuses"] == ["future-status"]
    assert overview["screen_state_counts_by_posting"] == [
        {"state": "complete", "count": 1}, {"state": "future-state", "count": 1}
    ]
    assert overview["screening_record_state_counts"] == [
        {"value": "complete", "count": 1, "known": True},
        {"value": "future-state", "count": 1, "known": False},
    ]
    assert overview["table_counts"]["job_postings"] == 2


def test_job_search_escapes_like_wildcards_and_keyset_pages(db_path):
    with sqlite3.connect(db_path) as conn:
        percent = _job(conn, title="100% Remote")
        _job(conn, title="1000 Remote")
        _job(conn, title="Role_One")
        _job(conn, title="Role!One")
    repo = ReadOnlyATSRepository(db_path)
    assert [row["id"] for row in repo.list_jobs(search="%")["items"]] == [percent]
    assert repo.list_jobs(search="_")["items"][0]["job_title"] == "Role_One"
    assert repo.list_jobs(search="!")["items"][0]["job_title"] == "Role!One"

    first = repo.list_jobs(limit=2)
    second = repo.list_jobs(limit=2, cursor=first["next_cursor"])
    assert first["has_more"] and not second["has_more"]
    assert [r["id"] for r in first["items"] + second["items"]] == [4, 3, 2, 1]
    assert "not a snapshot" in first["ordering"]
    with pytest.raises(QueryInputError, match="does not match"):
        repo.list_jobs(source="other", cursor=first["next_cursor"])
    with pytest.raises(QueryInputError, match="malformed"):
        repo.list_jobs(cursor="../bad")


def test_orphaned_optional_application_link_is_returned_as_stored(db_path):
    with sqlite3.connect(db_path) as conn:
        job_id = _job(conn)
        conn.execute("UPDATE job_postings SET application_id=999 WHERE id=?", (job_id,))
    job = ReadOnlyATSRepository(db_path).get_job(job_id)
    assert job["application_id"] == 999
    assert job["pipeline_status"] == "new"


def test_cursor_is_bounded_and_does_not_store_filter_text(db_path):
    long_source, long_status, long_screen, long_search = "s" * 200, "p" * 200, "x" * 200, "t" * 200
    with sqlite3.connect(db_path) as conn:
        app_id = _application(conn)
        first = _job(conn, title=long_search, status=long_status)
        second = _job(conn, title=long_search, status=long_status)
        conn.execute("UPDATE job_postings SET source=?, application_id=? WHERE id IN (?,?)",
                     (long_source, app_id, first, second))
        conn.execute(
            "INSERT INTO job_screenings(job_posting_id,state,backend,evaluator_version,"
            "last_attempted_at,created_at) VALUES(?,?,'ollama','v1','now','now')",
            (first, long_screen),
        )
        conn.execute(
            "INSERT INTO job_screenings(job_posting_id,state,backend,evaluator_version,"
            "last_attempted_at,created_at) VALUES(?,?,'ollama','v1','now','now')",
            (second, long_screen),
        )
    page = ReadOnlyATSRepository(db_path).list_jobs(
        search=long_search, source=long_source, pipeline_status=long_status,
        screen_state=long_screen, created_from="2026-10-22", created_to="2026-10-22",
        posted_from="2026-10-01", posted_to="2026-10-31", application_id=app_id, limit=1,
    )
    assert page["has_more"] and len(page["next_cursor"]) < 200
    cursor = page["next_cursor"]
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert long_search not in payload["scope"]
    for field in ("key", "extra"):
        forged = dict(payload)
        forged[field] = 2**63
        encoded = base64.urlsafe_b64encode(
            json.dumps(forged, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        with pytest.raises(QueryInputError, match="malformed"):
            ReadOnlyATSRepository(db_path).list_jobs(
                search=long_search, source=long_source, pipeline_status=long_status,
                screen_state=long_screen, created_from="2026-10-22", created_to="2026-10-22",
                posted_from="2026-10-01", posted_to="2026-10-31", application_id=app_id,
                limit=1, cursor=encoded,
            )


def test_job_filters_and_get_job_withhold_description_but_offer_exact_chunks(db_path):
    body = "Sensitive job description\n" * 3
    with sqlite3.connect(db_path) as conn:
        matching = _job(conn, title="Principal Engineer", status="new", description=body,
                        url="https://jobs.test/apply?token=private&page=2", posted="2026-10-02")
        timestamped = _job(conn, title="Timestamped", posted="2026-10-02T23:59:59Z")
        _job(conn, title="Other", status="failed", posted="2026-09-01")
    repo = ReadOnlyATSRepository(db_path)
    page = repo.list_jobs(
        search="Principal", pipeline_status="new", screen_state="not_screened",
        created_from="2026-10-22", posted_from="2026-10-01", posted_to="2026-10-31",
    )
    assert [row["id"] for row in page["items"]] == [matching]
    end_of_day = repo.list_jobs(posted_from="2026-10-02", posted_to="2026-10-02")
    assert {row["id"] for row in end_of_day["items"]} == {matching, timestamped}
    assert "private" not in page["items"][0]["job_url"]
    assert page["items"][0]["description_chars"] == len(body)
    full = repo.get_job(matching)
    assert "description" not in full
    assert full["description_chars"] == len(body)
    assert "private" not in full["job_url"]
    assert full["screening"] is None
    chunks = [repo.get_job_description(matching, offset=offset, limit=7)["text"]
              for offset in range(0, len(body), 7)]
    assert "".join(chunks) == body
    assert repo.get_job_description(matching, offset=len(body), limit=7)["has_more"] is False


def test_application_links_notes_null_empty_and_application_history_cursor(db_path):
    with sqlite3.connect(db_path) as conn:
        app_null = _application(conn, company="NullCo", notes=None)
        app_empty = _application(conn, company="EmptyCo", notes="")
        conn.execute("UPDATE applications SET application_url='' WHERE id=?", (app_empty,))
        conn.execute("INSERT INTO status_history(application_id,status,timestamp) VALUES(?,?,?)",
                     (app_null, "Applied", "2026-10-22T10:00:00Z"))
        conn.execute("INSERT INTO status_history(application_id,status,timestamp) VALUES(?,?,?)",
                     (app_null, "Interview", "2026-10-22T10:00:00Z"))
        conn.execute("INSERT INTO status_history(application_id,status,timestamp) VALUES(?,?,?)",
                     (app_null, "Offer", "2026-10-23T10:00:00Z"))
        job_id = _job(conn)
        conn.execute("UPDATE job_postings SET application_id=? WHERE id=?", (app_null, job_id))
    repo = ReadOnlyATSRepository(db_path)
    listed = repo.list_applications(search="Null", status="Applied", category="Engineering",
                                    applied_from="2026-10-01", applied_to="2026-10-31")
    assert listed["items"][0]["linked_job_count"] == 1
    full = repo.get_application(app_null)
    assert full["linked_job_ids"] == [job_id]
    assert full["notes_is_null"] is True
    assert repo.get_application_notes(app_null)["text"] is None
    empty = repo.get_application(app_empty)
    assert empty["application_url"] == ""
    assert empty["notes_is_null"] is False and empty["notes_chars"] == 0
    assert repo.get_application_notes(app_empty)["text"] == ""

    first = repo.list_application_history(app_null, limit=2)
    second = repo.list_application_history(app_null, limit=2, cursor=first["next_cursor"])
    assert [r["status"] for r in first["items"] + second["items"]] == [
        "Applied", "Interview", "Offer"
    ]


def test_text_chunks_distinguish_empty_and_validate_bounds(db_path):
    with sqlite3.connect(db_path) as conn:
        null_id = _job(conn, description="JD")
        empty_id = _job(conn, description="")
        app_id = _application(conn, notes="hello")
    repo = ReadOnlyATSRepository(db_path)
    first = repo.get_job_description(null_id, limit=1)
    assert first["text"] == "J" and first["next_offset"] == 1 and first["has_more"]
    assert repo.get_job_description(null_id, offset=1, limit=1)["text"] == "D"
    assert repo.get_job_description(empty_id)["text"] == ""
    assert repo.get_application_notes(app_id, offset=2, limit=2)["text"] == "ll"
    with pytest.raises(QueryInputError, match="past the end"):
        repo.get_application_notes(app_id, offset=6)
    with pytest.raises(QueryInputError, match="limit must be between"):
        repo.get_job_description(null_id, limit=0)


def test_all_ats_entities_are_allowlisted_and_json_is_reported(db_path):
    recipe = {
        "headers": {"Authorization": "Bearer top-secret", "X-Custom": "private-value"},
        "nested": {"headers": [["Cookie", "session-secret"], ["X-Trace", "trace"]]},
        "url": "https://board.test/jobs?access_token=url-secret&page=2",
    }
    with sqlite3.connect(db_path) as conn:
        job_id = _job(conn)
        app_id = _application(conn, notes="note")
        conn.execute(
            "INSERT INTO job_screenings(job_posting_id,state,result_json,backend,evaluator_version,"
            "last_attempted_at,created_at) VALUES(?, 'complete','{\"ok\":true}','ollama','v1','now','now')",
            (job_id,),
        )
        conn.execute("INSERT INTO status_history(application_id,status,timestamp) VALUES(?,?,?)",
                     (app_id, "Applied", "2026-10-22T10:00:00Z"))
        conn.execute("INSERT INTO watched_companies(source,slug,name,recipe,created_at) VALUES(?,?,?,?,?)",
                     ("custom", "acme", "Acme", json.dumps(recipe), "now"))
        conn.execute("INSERT INTO feed_unresolved(feed,url,company_name,job_title,host,reason,created_at) "
                     "VALUES('feed','https://board.test/apply?api_key=feed-secret','Acme','Engineer',"
                     "'board.test','unsupported_host','now')")
        conn.execute("INSERT INTO promotion_dismissed(source,slug,created_at) VALUES('custom','old','now')")
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('categories','[\"Engineering\"]','now')")
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('private-key','secret-setting','now')")
    repo = ReadOnlyATSRepository(db_path)
    entities = (
        "applications", "job_postings", "job_screenings", "status_history",
        "watched_companies", "feed_unresolved", "promotion_dismissed", "app_settings",
    )
    assert all(repo.list_ats_records(entity)["items"] for entity in entities)
    assert repo.get_ats_record("job_screenings", "1")["result_json_parsed"] == {"ok": True}
    company = repo.get_ats_record("watched_companies", "1")
    redacted = json.dumps(company)
    for secret in ("top-secret", "private-value", "session-secret", "url-secret"):
        assert secret not in redacted
    assert "Authorization" in redacted and "X-Custom" in redacted
    assert "[REDACTED]" in redacted
    feed = repo.get_ats_record("feed_unresolved", "1")
    assert "feed-secret" not in json.dumps(feed)
    categories = repo.get_ats_record("app_settings", "categories")
    assert categories["value_parsed"] == ["Engineering"]
    private = repo.get_ats_record("app_settings", "private-key")
    assert "secret-setting" not in json.dumps(private)
    assert "withheld" in private["value"]


def test_malformed_recipe_is_withheld_without_leaking_raw_value(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO watched_companies(source,slug,name,recipe,created_at) "
                     "VALUES('custom','broken','Broken','{\"headers\": [secret', 'now')")
    record = ReadOnlyATSRepository(db_path).get_ats_record("watched_companies", "1")
    assert record["recipe_parse_status"] == "malformed_withheld"
    assert "secret" not in json.dumps(record)


def test_valid_json_that_is_not_a_recipe_object_is_withheld(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO watched_companies(source,slug,name,recipe,created_at) "
                     "VALUES('custom','scalar','Scalar','\"api_key=private\"', 'now')")
    record = ReadOnlyATSRepository(db_path).get_ats_record("watched_companies", "1")
    assert record["recipe_parse_status"] == "malformed_withheld"
    assert "private" not in json.dumps(record)


@pytest.mark.parametrize("entity", [[], {}, None, "sqlite_master", "applications; DROP TABLE applications"])
def test_entity_input_cannot_select_arbitrary_sql(entity, db_path):
    repo = ReadOnlyATSRepository(db_path)
    with pytest.raises(QueryInputError, match="entity must name"):
        repo.list_ats_records(entity)
    with pytest.raises(QueryInputError, match="entity must name"):
        repo.get_ats_record(entity, "1")


def test_invalid_filters_keys_and_missing_rows_are_actionable(db_path):
    repo = ReadOnlyATSRepository(db_path)
    with pytest.raises(QueryInputError, match="real calendar date"):
        repo.list_jobs(created_from="2026-02-30")
    with pytest.raises(QueryInputError, match="must not be after"):
        repo.list_jobs(posted_from="2026-10-03", posted_to="2026-10-02")
    with pytest.raises(QueryInputError, match="between"):
        repo.list_applications(limit=True)
    with pytest.raises(QueryInputError, match="positive integer"):
        repo.get_job(0)
    with pytest.raises(QueryInputError, match="positive integer"):
        repo.get_ats_record("job_postings", "0")
    with pytest.raises(RecordNotFound, match="job was not found"):
        repo.get_job(999)
    with pytest.raises(RecordNotFound, match="record was not found"):
        repo.get_job_description(999)


@pytest.mark.parametrize('query_key', ['key', 'sig', 'jwt', 'access_token', 'api%5Fkey'])
def test_malformed_url_query_secrets_are_redacted_in_all_recipe_reads(db_path, query_key):
    recipe = {'url': f'https://[bad?{query_key}=synthetic-secret&page=2#{query_key}'}
    with sqlite3.connect(db_path) as conn:
        conn.execute('INSERT INTO watched_companies(source,slug,name,recipe,created_at) '
                     'VALUES(?,?,?,?,?)', ('custom', 'acme', 'Acme', json.dumps(recipe), 'now'))
    repo = ReadOnlyATSRepository(db_path)
    detail = repo.get_ats_record('watched_companies', '1')
    listing = repo.list_ats_records('watched_companies')
    for result in (detail, listing):
        assert 'synthetic-secret' not in json.dumps(result)
        assert 'page=2' in json.dumps(result)
    assert '[REDACTED]' in detail['recipe_parsed']['url'] or '%5BREDACTED%5D' in detail['recipe_parsed']['url']


def _insert_screen(conn, job_id, *, state, result_json, updated_at,
                   backend="codex", model="synthetic-model", effort="medium"):
    conn.execute(
        "INSERT INTO job_screenings(job_posting_id,state,result_json,backend,model,effort,"
        "evaluator_version,last_attempted_at,completed_at,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,'screen-v1',?,?,?,?)",
        (job_id, state, result_json, backend, model, effort,
         updated_at or "2026-10-22T10:20:30.000Z",
         updated_at if state == "complete" else None,
         "2026-10-22T10:20:30.000Z", updated_at),
    )


def test_standalone_screen_outcomes_share_synthetic_contract_fixture(db_path):
    contract = json.loads((FIXTURES / "standalone_screen_contract.json").read_text())
    job_ids = {}
    with sqlite3.connect(db_path) as conn:
        for case in contract["cases"]:
            job_id = _job(conn, title=case["name"])
            job_ids[case["name"]] = job_id
            if case["name"] == "not_screened":
                conn.execute(
                    "UPDATE job_postings SET score_detail=? WHERE id=?",
                    (contract["legacy_evidence"]["score_detail_raw"], job_id),
                )
            if case["state"] is not None:
                _insert_screen(
                    conn, job_id, state=case["state"],
                    result_json=case["result_json_raw"],
                    updated_at="2026-10-22T10:20:30.000Z",
                )

    repo = ReadOnlyATSRepository(db_path)
    page = repo.list_jobs(limit=100)
    by_title = {item["job_title"]: item for item in page["items"]}
    for case in contract["cases"]:
        item = by_title[case["name"]]
        assert item["screen_summary"]["outcome"] == case["expected_outcome"]
        assert item["screen_summary"]["is_advisory"] is True
        assert item["screen_summary"]["origin"] == (
            "none" if case["state"] is None else "job_screenings"
        )
        matches = repo.list_jobs(screen_outcome=case["expected_outcome"], limit=100)
        assert item["id"] in {result["id"] for result in matches["items"]}

    legacy = by_title["not_screened"]
    assert legacy["screen_summary"]["outcome"] == contract["legacy_evidence"][
        "expected_standalone_outcome"
    ]
    assert legacy["screen_summary"]["assessment_time"] is None
    assert legacy["screen_summary"]["origin"] == "none"
    assert legacy["legacy_screen_evidence"] == {
        "available": True,
        "origin": contract["legacy_evidence"]["expected_origin"],
        "read_tool": "get_job",
    }
    assert "result_json" not in legacy

    legacy_detail = repo.get_job(job_ids["not_screened"])
    assert legacy_detail["screen_summary"]["outcome"] == "not_screened"
    assert legacy_detail["screen_summary"]["assessment_time"] is None
    assert legacy_detail["legacy_screen_evidence"]["available"] is True
    standalone_detail = repo.get_job(job_ids["successful_checked_result"])
    assert standalone_detail["screen_summary"] == {
        "outcome": "no_disqualifier_found",
        "is_advisory": True,
        "reason": "No failing typed check was stored; unchecked requirements remain unknown.",
        "assessment_time": "2026-10-22T10:20:30.000Z",
        "backend": "codex",
        "model": "synthetic-model",
        "effort": "medium",
        "evaluator_version": "screen-v1",
        "origin": "job_screenings",
    }


def test_screen_summaries_bound_and_redact_untrusted_reasons(db_path):
    secret_url = "https://example.test/role?token=synthetic-secret"
    reason = secret_url + " " + "x" * 500
    result = json.dumps({
        "screen": {"degree": {"pass": False}},
        "disqualified": True,
        "disqualification_reason": reason,
    })
    with sqlite3.connect(db_path) as conn:
        job_id = _job(conn)
        _insert_screen(conn, job_id, state="complete", result_json=result,
                       updated_at="2026-10-22T10:20:30Z")
    item = ReadOnlyATSRepository(db_path).list_jobs()["items"][0]
    summary = item["screen_summary"]
    assert summary["outcome"] == "disqualified"
    assert len(summary["reason"]) <= 300
    assert "synthetic-secret" not in summary["reason"]
    assert summary["assessment_time"] == "2026-10-22T10:20:30Z"
    assert summary["backend"] == "codex"
    assert summary["model"] == "synthetic-model"
    assert summary["effort"] == "medium"


def test_all_text_search_is_opt_in_literal_and_keeps_descriptions_chunk_only(db_path):
    with sqlite3.connect(db_path) as conn:
        body_id = _job(conn, title="Metadata only", description="contains 100%_! synthetic phrase")
        _job(conn, title="Metadata wildcard", description="contains 1000A! synthetic phrase")
        _job(conn, title="Null distinction", description="")
    repo = ReadOnlyATSRepository(db_path)
    assert repo.list_jobs(search="synthetic phrase")["items"] == []
    for literal in ("%", "_", "!"):
        matched = repo.list_jobs(search=literal, search_scope="all_text")
        assert any(item["id"] == body_id for item in matched["items"])
        assert all("description" not in item for item in matched["items"])
    assert {item["id"] for item in repo.list_jobs(search="100%_!", search_scope="all_text")["items"]} == {body_id}
    assert repo.list_jobs(search="phrase", search_scope="all_text")["items"][0]["description_chars"] == len(
        "contains 100%_! synthetic phrase"
    )
    assert any(item["description_chars"] == 0 and not item["description_is_null"]
               for item in repo.list_jobs(search_scope="all_text")["items"])


def test_screening_windows_use_utc_instants_and_id_ceiling(db_path):
    with sqlite3.connect(db_path) as conn:
        ids = [_job(conn, title=f"same-time-{i}", posted="2010-01-01") for i in range(5)]
        for job_id in ids:
            _insert_screen(conn, job_id, state="complete",
                           result_json='{"screen":{"degree":{"pass":true}},"disqualified":false}',
                           updated_at="2026-10-22T12:00:00.123456Z")
        provider_error = _job(conn, title="old-posting-provider-error", posted="2010-01-01")
        _insert_screen(conn, provider_error, state="provider_error", result_json=None,
                       updated_at="2026-10-22T12:00:00.123456Z")
    repo = ReadOnlyATSRepository(db_path)
    first = repo.list_jobs(
        screening_updated_from="2026-10-22T14:00:00.123456+02:00", limit=2,
    )
    second = repo.list_jobs(
        screening_updated_from="2026-10-22T14:00:00.123456+02:00", limit=2,
        cursor=first["next_cursor"],
    )
    third = repo.list_jobs(
        screening_updated_from="2026-10-22T14:00:00.123456+02:00", limit=2,
        cursor=second["next_cursor"],
    )
    found = [item["id"] for page in (first, second, third) for item in page["items"]]
    assert found == list(reversed([*ids, provider_error]))
    assert len(found) == len(set(found))
    assert repo.list_jobs(
        screening_updated_to="2026-10-22T12:00:00.123456Z", limit=100,
    )["items"] == []
    assert len(repo.list_jobs(
        screening_updated_from="2026-10-22T12:00:00.123456Z",
        screening_updated_to="2026-10-22T12:00:00.123457Z", limit=100,
    )["items"]) == 6
    assert repo.list_jobs(screen_outcome="provider_error", screening_updated_from=
                          "2026-10-22T12:00:00.123456Z")["items"][0]["id"] == provider_error
    with pytest.raises(QueryInputError, match="offset"):
        repo.list_jobs(screening_updated_from="2026-10-22T12:00:00")
    over_limit_fraction = "2026-10-22T12:00:00." + ("1" * 20) + "Z"
    assert len(over_limit_fraction) > 40
    with pytest.raises(QueryInputError, match="too long"):
        repo.list_jobs(screening_updated_from=over_limit_fraction)
    with pytest.raises(QueryInputError, match="must not be after"):
        repo.list_jobs(screening_updated_from="2026-10-23T00:00:00Z",
                       screening_updated_to="2026-10-22T00:00:00Z")
    with pytest.raises(QueryInputError, match="does not match"):
        repo.list_jobs(screening_updated_from="2026-10-22T12:00:00Z",
                       cursor=first["next_cursor"])
    with pytest.raises(QueryInputError, match="does not match"):
        repo.list_jobs(screening_updated_from="2026-10-22T14:00:00.123456+02:00",
                       screen_outcome="provider_error", cursor=first["next_cursor"])
    with pytest.raises(QueryInputError, match="does not match"):
        repo.list_jobs(screening_updated_from="2026-10-22T14:00:00.123456+02:00",
                       search="synthetic", search_scope="all_text", cursor=first["next_cursor"])


def test_screening_windows_preserve_fractional_precision_beyond_microseconds(db_path):
    assessment_time = "2026-10-22T12:00:00.12345678901234Z"
    with sqlite3.connect(db_path) as conn:
        job_id = _job(conn, title="high precision assessment", posted="2010-01-01")
        _insert_screen(
            conn, job_id, state="provider_error", result_json=None,
            updated_at=assessment_time,
        )
    repo = ReadOnlyATSRepository(db_path)
    equivalent_offset = "2026-10-22T14:00:00.12345678901234+02:00"
    matched = repo.list_jobs(screening_updated_from=equivalent_offset)
    assert [row["id"] for row in matched["items"]] == [job_id]
    one_fraction_later = "2026-10-22T14:00:00.12345678901235+02:00"
    assert repo.list_jobs(screening_updated_from=one_fraction_later)["items"] == []


def test_assessment_time_unknowns_and_eligible_screen_counts_are_explicit(db_path):
    contract = json.loads((FIXTURES / "standalone_screen_contract.json").read_text())
    time_cases = {case["name"]: case for case in contract["assessment_time_cases"]}
    with sqlite3.connect(db_path) as conn:
        fresh = _job(conn, title="fresh")
        retry = _job(conn, title="retry")
        space_form = _job(conn, title="offset-bearing space timestamp")
        naive = _job(conn, title="naive legacy timestamp")
        completed = _job(conn, title="complete")
        _job(conn, title="discarded", status="discarded")
        _job(conn, title="scored", status="scored")
        _insert_screen(conn, retry, state="provider_error", result_json=None,
                       updated_at="legacy-unparseable")
        _insert_screen(conn, space_form, state="provider_error", result_json=None,
                       updated_at=time_cases["offset_bearing_space_form"]["stored_updated_at"])
        _insert_screen(conn, naive, state="provider_error", result_json=None,
                       updated_at=time_cases["naive_legacy_updated_at"]["stored_updated_at"])
        _insert_screen(conn, completed, state="complete", result_json="{broken",
                       updated_at=None)
    repo = ReadOnlyATSRepository(db_path)
    from_today = repo.list_jobs(screening_updated_from="2026-10-22T00:00:00Z")
    assert [item["id"] for item in from_today["items"]] == [space_form]
    overview = repo.get_ats_overview()
    backlog = overview["eligible_screen_backlog"]
    assert backlog["scope"] == "pipeline_status=new"
    assert backlog["fresh"] == 1
    assert backlog["retry_eligible"] == 3
    assert backlog["total"] == 4
    assert overview["unknown_screening_updated_at_count"] == 3
    counts = {row["outcome"]: row["count"]
              for row in overview["standalone_screen_outcome_counts"]["counts"]}
    assert counts == {
        "not_screened": 3,
        "provider_error": 3,
        "disqualified": 0,
        "no_disqualifier_found": 0,
        "unknown": 1,
    }
    assert overview["standalone_screen_outcome_counts"]["scope"] == "all job_postings"
    assert overview["response_generated_at"].endswith("Z")
    by_title = {row["job_title"]: row for row in repo.list_jobs(limit=100)["items"]}
    assert by_title["retry"]["screen_summary"]["assessment_time"] is None
    assert by_title["complete"]["screen_summary"]["assessment_time"] is None
    for name, job_id in (("offset_bearing_space_form", space_form),
                         ("naive_legacy_updated_at", naive)):
        time_case = time_cases[name]
        title = ("offset-bearing space timestamp" if name == "offset_bearing_space_form"
                 else "naive legacy timestamp")
        summary_time = by_title[title]["screen_summary"]["assessment_time"]
        assert (summary_time is not None) is time_case["expected_known"]
        assert summary_time == time_case["expected_summary_time"]
        window_rows = repo.list_jobs(
            screening_updated_from="2026-10-22T00:00:00Z",
            screen_outcome="provider_error",
            limit=100,
        )["items"]
        assert (job_id in {item["id"] for item in window_rows}) is time_case["expected_known"]
    assert fresh != retry


def test_assessment_time_contract_cases_use_strict_timestamp_semantics(db_path):
    contract = json.loads((FIXTURES / "standalone_screen_contract.json").read_text())
    with sqlite3.connect(db_path) as conn:
        for case in contract["assessment_time_cases"]:
            job_id = _job(conn, title=case["name"])
            _insert_screen(
                conn,
                job_id,
                state="provider_error",
                result_json=None,
                updated_at=case["stored_updated_at"],
            )

    repo = ReadOnlyATSRepository(db_path)
    by_title = {item["job_title"]: item for item in repo.list_jobs(limit=100)["items"]}
    for case in contract["assessment_time_cases"]:
        summary_time = by_title[case["name"]]["screen_summary"]["assessment_time"]
        assert summary_time == case["expected_summary_time"]
        assert (summary_time is not None) is case["expected_known"]


def test_job_cursor_ceiling_and_live_pages_make_no_snapshot_claim(db_path):
    with sqlite3.connect(db_path) as conn:
        ids = [_job(conn, title=f"row-{i}") for i in range(4)]
    repo = ReadOnlyATSRepository(db_path)
    first = repo.list_jobs(limit=1)
    assert first["items"][0]["id"] == ids[-1]
    with sqlite3.connect(db_path) as conn:
        inserted = _job(conn, title="inserted-after-first-page")
        conn.execute("DELETE FROM job_postings WHERE id=?", (ids[1],))
    second = repo.list_jobs(limit=1, cursor=first["next_cursor"])
    third = repo.list_jobs(limit=1, cursor=second["next_cursor"])
    remaining = [item["id"] for page in (second, third) for item in page["items"]]
    assert inserted not in remaining
    assert ids[1] not in remaining
    assert remaining == [ids[-2], ids[0]]
    assert first["ordering"].startswith("live keyset page")
    assert first["traversal"]["snapshot"] is False
    assert first["traversal"]["id_ceiling"] == ids[-1]


def test_screening_change_behind_cursor_is_found_by_reconciliation(db_path):
    with sqlite3.connect(db_path) as conn:
        existing = [_job(conn, title=f"existing-error-{index}") for index in range(3)]
        changed_later = _job(conn, title="assessment changes after cursor")
        for job_id in existing:
            _insert_screen(conn, job_id, state="provider_error", result_json=None,
                           updated_at="2026-10-22T10:20:30Z")
    repo = ReadOnlyATSRepository(db_path)
    first = repo.list_jobs(screen_outcome="provider_error", limit=1)
    second = repo.list_jobs(
        screen_outcome="provider_error", limit=1, cursor=first["next_cursor"],
    )
    assert [first["items"][0]["id"], second["items"][0]["id"]] == [existing[2], existing[1]]
    assert second["next_cursor"] is not None

    with sqlite3.connect(db_path) as conn:
        _insert_screen(conn, changed_later, state="provider_error", result_json=None,
                       updated_at="2026-10-22T10:30:00Z")
    third = repo.list_jobs(
        screen_outcome="provider_error", limit=1, cursor=second["next_cursor"],
    )
    traversed_ids = [first["items"][0]["id"], second["items"][0]["id"],
                     *[item["id"] for item in third["items"]]]
    assert changed_later not in traversed_ids
    reconciled = repo.list_jobs(screen_outcome="provider_error", limit=100)
    assert changed_later in {item["id"] for item in reconciled["items"]}
    assert first["traversal"]["snapshot"] is False


def test_overview_clock_is_injected_and_normalized_to_utc(db_path):
    fixed = datetime(2026, 10, 22, 14, 30, 0, 123000,
                     tzinfo=timezone(timedelta(hours=2)))
    overview = ReadOnlyATSRepository(db_path, clock=lambda: fixed).get_ats_overview()
    assert overview["response_generated_at"] == "2026-10-22T12:30:00.123Z"


def test_large_generated_all_text_search_filters_before_limit_and_bounds_payload(db_path):
    body_size = 2_048
    rows = []
    for index in range(3_000):
        marker = "rare synthetic marker" if index == 17 else "ordinary synthetic body"
        body = (marker + " " + ("x" * body_size))
        rows.append((f"generated-{index}", "Synthetic Co", f"Role {index}", body))
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO job_postings(source,external_id,company_name,job_title,job_url,description,"
            "pipeline_status,created_at) VALUES('synthetic',?,?,?, 'https://example.test/job',?,'new',"
            "'2026-10-22T00:00:00Z')",
            rows,
        )
    result = ReadOnlyATSRepository(db_path).list_jobs(
        search="rare synthetic marker", search_scope="all_text", limit=1,
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["external_id"] == "generated-17"
    assert result["has_more"] is False
    payload = json.dumps(result, separators=(",", ":"))
    assert len(payload) < 8_000
    assert "ordinary synthetic body" not in payload
    assert "description" not in result["items"][0]
