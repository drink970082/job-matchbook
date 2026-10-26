"""Protocol-level MCP tests; CI installs the optional SDK v2 dependency."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

mcp_sdk = pytest.importorskip("mcp", reason="install requirements-mcp.txt for protocol tests")
from mcp import Client, StdioServerParameters  # noqa: E402

from ats_worker.mcp.read_repository import ReadOnlyATSRepository  # noqa: E402
from ats_worker.mcp.server import create_server  # noqa: E402
from tests._helpers import bootstrap_db  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _seed_job(path: str) -> None:
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO job_postings(source,external_id,company_name,job_title,job_url,description,"
            "pipeline_status,created_at) VALUES('greenhouse','1','Acme','Engineer',"
            "'https://example.test/jobs/1','A private description','new','2026-10-22')"
        )


def _seed_application(path: str) -> None:
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO applications(company_name,job_title,application_url,date_applied,"
            "category,status,notes,last_updated) VALUES('Acme','Engineer','https://example.test/apply',"
            "'2026-10-22','Engineering','Applied','Synthetic private note','2026-10-22')"
        )


@pytest.mark.anyio
async def test_in_memory_protocol_lists_read_only_tools_and_returns_structured_data(tmp_path):
    path = bootstrap_db(tmp_path / "mcp.db")
    _seed_job(path)
    _seed_application(path)
    import sqlite3

    with sqlite3.connect(path) as conn:
        application_before = conn.execute("SELECT * FROM applications").fetchall()
    server = create_server(ReadOnlyATSRepository(path))
    async with Client(server, raise_exceptions=True) as client:
        listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        assert names == {
            "get_ats_overview", "list_jobs", "get_job", "get_job_description",
            "list_applications", "get_application", "get_application_notes",
            "list_application_history", "list_ats_records", "get_ats_record",
        }
        for tool in listing.tools:
            annotations = tool.model_dump(by_alias=True)["annotations"]
            assert annotations["readOnlyHint"] is True
            assert annotations["openWorldHint"] is False

        result = await client.call_tool("list_jobs", {"search": "Engineer"})
        assert result.is_error is not True
        assert result.structured_content["items"][0]["job_title"] == "Engineer"
        assert "description" not in result.structured_content["items"][0]
        overview = await client.call_tool("get_ats_overview", {})
        assert overview.structured_content["table_counts"]["applications"] == 1

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM applications").fetchall() == application_before


@pytest.mark.anyio
async def test_protocol_errors_are_actionable_without_exposing_database_paths(tmp_path):
    path = bootstrap_db(tmp_path / "mcp.db")
    async with Client(create_server(ReadOnlyATSRepository(path)), raise_exceptions=True) as client:
        missing = await client.call_tool("get_job", {"job_id": 99})
        assert missing.is_error is True
        assert "job was not found" in missing.content[0].text
        assert str(tmp_path) not in missing.content[0].text

        invalid = await client.call_tool("list_ats_records", {"entity": "sqlite_master"})
        assert invalid.is_error is True
        assert "entity" in invalid.content[0].text


@pytest.mark.anyio
async def test_stdio_subprocess_uses_protocol_and_only_reads_its_configured_database(tmp_path):
    path = bootstrap_db(tmp_path / "mcp-stdio.db")
    _seed_job(path)
    worker_root = Path(__file__).resolve().parents[1]
    process = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ats_worker.mcp"],
        env={"ATS_DB_PATH": path, "PYTHONPATH": os.fspath(worker_root)},
    )
    async with Client(process) as client:
        result = await client.call_tool("get_ats_overview", {})
        assert result.structured_content["table_counts"]["job_postings"] == 1


@pytest.mark.anyio
async def test_stdio_research_path_pages_gets_chunks_and_reports_safe_error(tmp_path):
    path = bootstrap_db(tmp_path / "mcp-research.db")
    import sqlite3

    body = "Synthetic full job description with literal 100%_! marker. " * 4
    with sqlite3.connect(path) as conn:
        job_ids = []
        for index in range(3):
            cursor = conn.execute(
                "INSERT INTO job_postings(source,external_id,company_name,job_title,job_url,description,"
                "pipeline_status,created_at,posted_at) VALUES('synthetic',?,?,?,?,?,'new',?,?)",
                (str(index), "Synthetic Co", f"Role {index}",
                 f"https://example.test/job/{index}", body,
                 "2026-10-22T10:00:00Z", "2010-01-01"),
            )
            job_ids.append(cursor.lastrowid)
        conn.execute(
            "INSERT INTO job_screenings(job_posting_id,state,result_json,backend,model,effort,"
            "evaluator_version,last_attempted_at,completed_at,created_at,updated_at) "
            "VALUES(?,'complete',?,'codex','synthetic-model','medium','screen-v1',"
            "'2026-10-22T10:30:00Z','2026-10-22T10:30:00Z','2026-10-22T10:30:00Z',"
            "'2026-10-22T10:30:00Z')",
            (job_ids[0], '{"screen":{"degree":{"pass":true}},"disqualified":false}'),
        )
    worker_root = Path(__file__).resolve().parents[1]
    process = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ats_worker.mcp"],
        env={"ATS_DB_PATH": path, "PYTHONPATH": os.fspath(worker_root)},
    )
    async with Client(process) as client:
        literal_search = await client.call_tool("list_jobs", {
            "search": "100%_!", "search_scope": "all_text", "limit": 10,
        })
        assert len(literal_search.structured_content["items"]) == 3
        assert all("description" not in row for row in literal_search.structured_content["items"])

        outcomes = await client.call_tool("list_jobs", {
            "screen_outcome": "no_disqualifier_found",
            "screening_updated_from": "2026-10-22T10:30:00+00:00",
            "screening_updated_to": "2026-10-22T10:30:01Z",
        })
        assert [row["id"] for row in outcomes.structured_content["items"]] == [job_ids[0]]
        assert outcomes.structured_content["items"][0]["screen_summary"]["is_advisory"] is True

        candidates = await client.call_tool("list_jobs", {
            "triage_status": "candidate", "limit": 10,
        })
        assert [row["id"] for row in candidates.structured_content["items"]] == [job_ids[0]]
        assert candidates.structured_content["items"][0]["triage_summary"]["status"] == "candidate"
        assert candidates.structured_content["items"][0]["screen_summary"]["outcome"] == "no_disqualifier_found"
        overview = await client.call_tool("get_ats_overview", {})
        triage_counts = overview.structured_content["job_triage_counts"]
        assert triage_counts["scope"] == "all job_postings"
        assert sum(row["count"] for row in triage_counts["counts"]) == len(job_ids)

        first = await client.call_tool("list_jobs", {"limit": 1})
        first_page = first.structured_content
        assert len(first_page["items"]) == 1 and first_page["has_more"] is True
        first_job_id = first_page["items"][0]["id"]
        second = await client.call_tool(
            "list_jobs", {"limit": 1, "cursor": first_page["next_cursor"]},
        )
        assert len(second.structured_content["items"]) == 1
        assert second.structured_content["items"][0]["id"] < first_job_id

        detail = await client.call_tool("get_job", {"job_id": first_job_id})
        assert detail.structured_content["description_is_null"] is False
        collected = []
        offset = 0
        while True:
            chunk = await client.call_tool(
                "get_job_description", {"job_id": first_job_id, "offset": offset, "limit": 11},
            )
            value = chunk.structured_content
            collected.append(value["text"])
            if not value["has_more"]:
                break
            offset = value["next_offset"]
        assert "".join(collected) == body

        missing = await client.call_tool("get_job", {"job_id": 999})
        assert missing.is_error is True
        assert "job was not found" in missing.content[0].text
        assert str(tmp_path) not in missing.content[0].text

        invalid = await client.call_tool("list_jobs", {
            "screening_updated_from": "2026-10-22T10:00:00",
        })
        assert invalid.is_error is True
        assert "offset-aware RFC3339" in invalid.content[0].text
