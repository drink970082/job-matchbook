"""Security and behavior tests for the bounded read-only MCP repository."""

from __future__ import annotations

import base64
import json
import sqlite3

import pytest

from ats_worker.mcp.read_repository import (
    DatabaseUnavailable,
    QueryInputError,
    ReadOnlyATSRepository,
    RecordNotFound,
)
from tests._helpers import bootstrap_db


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
