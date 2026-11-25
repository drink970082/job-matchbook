"""The onboard-board CLI adds through the web write API, never the database (#235).

This loads the *real* script (not a copy) via importlib, since it lives outside the
`ats_worker` package, and runs it against a stub web on loopback. What the web itself
does with the request (slug guard, duplicate, recipe schema, audit row with actor `mcp`)
is pinned on the web side (`api-v1.int.test.ts`).
"""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / ".claude/skills/onboard-board/scripts/add_watched.py"

_spec = importlib.util.spec_from_file_location("add_watched", SCRIPT)
add_watched = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_watched)

ACME = ["--source", "greenhouse", "--slug", "acme", "--name", "Acme"]


def lists_one(*_a):
    return True


def never(*_a):
    raise AssertionError("the board must not be fetched")


@pytest.fixture
def web(monkeypatch, tmp_path):
    """A stub web: `calls` records (path, auth, body), `answers` queues (status, payload)."""
    stub = SimpleNamespace(calls=[], answers=[])

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            stub.calls.append((self.path, self.headers["Authorization"], body))
            status, payload = stub.answers.pop(0) if stub.answers else (200, {"data": body})
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("HOME", str(tmp_path))           # no real ~/.config/ats-mcp/api-key
    monkeypatch.setenv("ATS_API_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ATS_API_KEY", "k")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    yield stub
    server.shutdown()
    server.server_close()


def test_dry_runs_then_verifies_then_adds_with_the_write_key(web, capsys):
    seen = []

    def listed(*args):
        seen.append((args, len(web.calls)))
        return True

    add_watched.main(ACME, has_listings=listed)
    board = {"source": "greenhouse", "slug": "acme", "name": "Acme"}
    assert web.calls == [("/api/v1/watchlist", "Bearer k", {**board, "dry_run": True}),
                         ("/api/v1/watchlist", "Bearer k", board)]
    assert seen == [(("greenhouse", "acme", "Acme"), 1)]        # between the two calls
    assert capsys.readouterr().out.startswith("added: greenhouse/acme (Acme)")


@pytest.mark.parametrize("has_listings, reason", [
    (lambda *_a: False, "board lists no postings"),
    (lambda *_a: 1 / 0, "could not verify the board"),
])
def test_a_board_that_does_not_verify_is_not_added(web, has_listings, reason):
    with pytest.raises(SystemExit, match=reason):
        add_watched.main(ACME, has_listings=has_listings)
    assert [c[2].get("dry_run") for c in web.calls] == [True]


def test_a_web_rejection_is_reported_before_any_fetch(web):
    web.answers.append((400, {"error": "slug contains invalid characters"}))
    with pytest.raises(SystemExit, match="slug contains invalid characters"):
        add_watched.main(["--source", "workday", "--slug", "x@evil:80/../y", "--name", "Evil"], has_listings=never)
    assert len(web.calls) == 1


def test_a_recipe_board_is_sent_with_its_recipe_and_not_fetched(web, tmp_path, capsys):
    recipe = tmp_path / "recipe.json"
    recipe.write_text('{"url": "https://a.example.com/j", "item": "li", "fields": {"title": "h2", "external_id": "a"}}')
    row = {"source": "browser", "slug": "acme", "name": "Acme"}
    web.answers += [(200, {"data": row}), (200, {"data": {**row, "warning": "Browser sources were off"}})]
    add_watched.main(["--source", "browser", "--slug", "acme", "--name", "Acme", "--recipe", str(recipe)],
                     has_listings=never)
    assert [c[2]["recipe"] for c in web.calls] == [recipe.read_text()] * 2
    assert "warning: Browser sources were off" in capsys.readouterr().out


def test_the_key_file_is_used_when_the_env_has_none(web, monkeypatch, tmp_path):
    monkeypatch.delenv("ATS_API_KEY")
    key = tmp_path / ".config/ats-mcp/api-key"
    key.parent.mkdir(parents=True)
    key.write_text("from-file\n")
    add_watched.main(ACME, has_listings=lists_one)
    assert {c[1] for c in web.calls} == {"Bearer from-file"}


@pytest.mark.parametrize("env, sent", [("from-env", "from-env"), ("  ", "from-file")])
def test_the_env_key_wins_over_the_file_unless_blank(web, monkeypatch, tmp_path, env, sent):
    monkeypatch.setenv("ATS_API_KEY", env)
    key = tmp_path / ".config/ats-mcp/api-key"
    key.parent.mkdir(parents=True)
    key.write_text("from-file")
    add_watched.main(ACME, has_listings=lists_one)
    assert {c[1] for c in web.calls} == {f"Bearer {sent}"}


@pytest.mark.parametrize("key", ["two\nlines", "k\u00e9y\u2026"])
def test_a_malformed_key_is_named_and_never_sent_or_printed(web, monkeypatch, key):
    monkeypatch.setenv("ATS_API_KEY", key)
    with pytest.raises(SystemExit, match="one line of ASCII") as exc:
        add_watched.main(ACME, has_listings=never)
    assert web.calls == [] and key not in str(exc.value)


def test_a_rejected_second_call_is_not_reported_as_added(web, capsys):
    web.answers += [(200, {"data": {"source": "greenhouse", "slug": "acme", "name": "Acme"}}),
                    (400, {"error": "greenhouse/acme is already on the watchlist"})]
    with pytest.raises(SystemExit, match="already on the watchlist"):
        add_watched.main(ACME, has_listings=lists_one)
    assert capsys.readouterr().out == ""


def test_a_server_that_is_not_the_ats_web_is_named(web):
    web.answers.append((200, ["hello"]))
    with pytest.raises(SystemExit, match="not the ATS web app"):
        add_watched.main(ACME, has_listings=never)


def test_a_missing_recipe_file_is_an_error_not_a_traceback(web, tmp_path):
    with pytest.raises(SystemExit, match="cannot read"):
        add_watched.main([*ACME, "--recipe", str(tmp_path / "nope.json")], has_listings=never)
    assert web.calls == []


def test_the_default_check_is_the_adapters_list_check():
    from ats_worker.fetch import board_has_listings
    assert add_watched.main.__defaults__ == (None, board_has_listings)


def test_no_key_fails_with_the_reason_and_sends_nothing(web, monkeypatch):
    monkeypatch.delenv("ATS_API_KEY")
    with pytest.raises(SystemExit, match="no write key"):
        add_watched.main(ACME, has_listings=never)
    assert web.calls == []


def test_an_unreachable_web_fails_with_the_reason(web, monkeypatch):
    monkeypatch.setenv("ATS_API_URL", "http://127.0.0.1:1")
    with pytest.raises(SystemExit, match="ATS web is unreachable"):
        add_watched.main(ACME, has_listings=never)


@pytest.mark.parametrize("status, reason", [
    (503, "write API is disabled"), (401, "rejected this server's key"), (403, "needs a read_write key"),
])
def test_a_refused_key_fails_with_the_reason(web, status, reason):
    web.answers.append((status, {"error": "x"}))
    with pytest.raises(SystemExit, match=reason):
        add_watched.main(ACME, has_listings=never)
