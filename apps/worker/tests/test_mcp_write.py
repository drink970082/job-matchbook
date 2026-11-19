"""MCP write tools: they call the web write API (mocked here) and never write SQLite."""

from __future__ import annotations

import sqlite3

import pytest
import requests

from ats_worker.mcp.write_client import ATSWriteClient, WriteAPIError, write_client_from_env
from tests._helpers import bootstrap_db

mcp_sdk = pytest.importorskip("mcp", reason="install requirements-mcp.txt for protocol tests")
from mcp import Client  # noqa: E402

from ats_worker.mcp.read_repository import ReadOnlyATSRepository  # noqa: E402
from ats_worker.mcp.server import create_server  # noqa: E402

WRITE_TOOLS = {"record_application", "mark_job_applied", "update_application_status",
               "update_application_notes"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeResponse:
    def __init__(self, status: int, payload=None, raw: bool = False):
        self.status_code = status
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._raw:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, json=None, timeout=None, headers=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _client(*responses):
    session = FakeSession(*responses)
    return ATSWriteClient("http://web.test/", "k", session=session), session


# --- the HTTP client --------------------------------------------------------

def test_client_sends_bearer_and_returns_data():
    client, session = _client(FakeResponse(200, {"data": {"id": 7}}))
    assert client.call("POST", "/api/v1/applications", {"a": 1}) == {"id": 7}
    assert session.calls[0]["url"] == "http://web.test/api/v1/applications"
    assert session.calls[0]["headers"] == {"Authorization": "Bearer k"}
    assert session.calls[0]["json"] == {"a": 1}


@pytest.mark.parametrize("resp, message", [
    (FakeResponse(400, {"error": "Invalid status"}), "Invalid status"),
    (FakeResponse(400, None, raw=True), "HTTP 400"),
    (FakeResponse(500, ["x"]), "HTTP 500"),
    (FakeResponse(401, {"error": "x"}), "rejected this server's key"),
    (FakeResponse(403, {"error": "x"}), "rejected this server's key"),
    (FakeResponse(503, {"error": "x"}), "disabled"),
    (requests.ConnectionError("refused"), "unreachable at http://web.test"),
])
def test_client_maps_failures_to_safe_messages(resp, message):
    client, _ = _client(resp)
    with pytest.raises(WriteAPIError, match=message):
        client.call("POST", "/x")


def test_from_env_needs_a_key_and_defaults_to_loopback():
    assert write_client_from_env({}) is None
    assert write_client_from_env({"ATS_API_KEY": "  "}) is None
    assert write_client_from_env({"ATS_API_KEY": "k"})._base == "http://127.0.0.1:3000"
    assert write_client_from_env({"ATS_API_KEY": "k", "ATS_API_URL": "http://h:1"})._base == "http://h:1"


# --- the tools over the protocol ---------------------------------------------

def _seed_app(path, notes):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO applications(company_name,job_title,date_applied,status,notes) "
            "VALUES('Acme','Engineer','2026-11-01','Applied',?)", (notes,))


@pytest.mark.anyio
async def test_no_writer_means_no_write_tools(tmp_path):
    server = create_server(ReadOnlyATSRepository(bootstrap_db(tmp_path / "m.db")))
    async with Client(server, raise_exceptions=True) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names and not names & WRITE_TOOLS


@pytest.mark.anyio
async def test_write_tools_call_the_api_and_are_not_read_only(tmp_path):
    path = bootstrap_db(tmp_path / "m.db")
    writer, session = _client(
        FakeResponse(200, {"data": {"id": 1}}),
        FakeResponse(200, {"data": {"id": 2}}),
        FakeResponse(200, {"data": None}),
    )
    server = create_server(ReadOnlyATSRepository(path), writer)
    async with Client(server, raise_exceptions=True) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert WRITE_TOOLS <= set(tools)
        for name in WRITE_TOOLS:
            ann = tools[name].model_dump(by_alias=True)["annotations"]
            assert ann["readOnlyHint"] is False and ann["destructiveHint"] is False

        rec = await client.call_tool("record_application", {
            "company_name": "Acme", "job_title": "Engineer", "date_applied": "2026-11-18"})
        assert rec.structured_content == {"application": {"id": 1}}
        await client.call_tool("mark_job_applied", {"job_id": 5, "category": "SWE"})
        await client.call_tool("update_application_status", {"application_id": 1, "status": "Offer"})

    assert [(c["method"], c["url"].removeprefix("http://web.test")) for c in session.calls] == [
        ("POST", "/api/v1/applications"),
        ("POST", "/api/v1/jobs/5/applied"),
        ("POST", "/api/v1/applications/1/status"),
    ]
    assert session.calls[0]["json"] == {"company_name": "Acme", "job_title": "Engineer",
                                        "date_applied": "2026-11-18", "status": "Applied"}
    assert session.calls[1]["json"] == {"category": "SWE"}
    assert session.calls[2]["json"] == {"status": "Offer"}


@pytest.mark.anyio
async def test_status_outside_the_vocabulary_is_rejected_before_any_call(tmp_path):
    writer, session = _client()
    server = create_server(ReadOnlyATSRepository(bootstrap_db(tmp_path / "m.db")), writer)
    async with Client(server, raise_exceptions=True) as client:
        res = await client.call_tool("update_application_status", {"application_id": 1, "status": "Offerr"})
    assert res.is_error is True
    assert session.calls == []


@pytest.mark.anyio
async def test_api_error_surfaces_as_tool_error(tmp_path):
    writer, _ = _client(FakeResponse(400, {"error": "Application not found"}))
    server = create_server(ReadOnlyATSRepository(bootstrap_db(tmp_path / "m.db")), writer)
    async with Client(server, raise_exceptions=True) as client:
        res = await client.call_tool("update_application_status", {"application_id": 9, "status": "Offer"})
    assert res.is_error is True
    assert "Application not found" in res.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("existing, expected", [
    (None, "called back"),
    ("   ", "called back"),
    ("first note\n", "first note\n\ncalled back"),
])
async def test_notes_are_appended_never_replaced(tmp_path, existing, expected):
    path = bootstrap_db(tmp_path / "m.db")
    _seed_app(path, existing)
    with sqlite3.connect(path) as conn:
        before = conn.execute("SELECT * FROM applications").fetchall()
    writer, session = _client(FakeResponse(200, {"data": None}))
    server = create_server(ReadOnlyATSRepository(path), writer)
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("update_application_notes", {"application_id": 1, "text": "called back"})
    assert session.calls[0]["method"] == "PATCH"
    assert session.calls[0]["json"] == {"notes": expected}
    with sqlite3.connect(path) as conn:  # MCP itself never wrote the DB
        assert conn.execute("SELECT * FROM applications").fetchall() == before


@pytest.mark.anyio
async def test_notes_longer_than_one_chunk_are_read_whole(tmp_path):
    path = bootstrap_db(tmp_path / "m.db")
    long = "x" * 40_000
    _seed_app(path, long)
    writer, session = _client(FakeResponse(200, {"data": None}))
    server = create_server(ReadOnlyATSRepository(path), writer)
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("update_application_notes", {"application_id": 1, "text": "y"})
    assert session.calls[0]["json"] == {"notes": long + "\n\ny"}


@pytest.mark.anyio
async def test_notes_on_a_missing_application_never_calls_the_api(tmp_path):
    writer, session = _client()
    server = create_server(ReadOnlyATSRepository(bootstrap_db(tmp_path / "m.db")), writer)
    async with Client(server, raise_exceptions=True) as client:
        res = await client.call_tool("update_application_notes", {"application_id": 9, "text": "y"})
    assert res.is_error is True
    assert session.calls == []


def test_reads_report_who_wrote(tmp_path):
    path = bootstrap_db(tmp_path / "m.db")
    _seed_app(path, None)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE applications SET actor='mcp'")
        conn.execute("INSERT INTO status_history(application_id,status,timestamp,actor) "
                     "VALUES(1,'Offer','2026-11-18T12:00:00.000Z','mcp')")
    repo = ReadOnlyATSRepository(path)
    assert repo.list_applications()["items"][0]["actor"] == "mcp"
    assert repo.get_application(1)["actor"] == "mcp"
    assert repo.list_application_history(1)["items"][0]["actor"] == "mcp"
