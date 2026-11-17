"""Subscription quota telemetry (`ats_worker.usage`). No real network."""
from __future__ import annotations

import json
from datetime import datetime
import urllib.error
import pytest
from ats_worker import usage


class _FakeResp:
    """Minimal stand-in for urlopen's context-managed response."""

    status = 200

    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


CODEX_USAGE_BODY = {
    "plan_type": "plus",
    "rate_limit": {
        "primary_window": {"used_percent": 11, "limit_window_seconds": 604800,
                           "reset_at": 1785905532},
        "secondary_window": None,
    },
}


# The live 2026-07-29 shape: BOTH the flat named buckets and the richer `limits[]`
# array, with a model-scoped weekly row beside the pooled one.
CLAUDE_USAGE_BODY = {
    "five_hour": {"utilization": 2.0, "resets_at": "2026-07-29T19:59:59.561596+00:00"},
    "seven_day": {"utilization": 72.0, "resets_at": "2026-08-02T12:00:00.561620+00:00"},
    "seven_day_opus": None,
    "limits": [
        {"kind": "session", "group": "session", "percent": 2,
         "resets_at": "2026-07-29T19:59:59.561596+00:00", "scope": None},
        {"kind": "weekly_all", "group": "weekly", "percent": 72,
         "resets_at": "2026-08-02T12:00:00.561620+00:00", "scope": None},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 2,
         "resets_at": "2026-08-02T11:59:59.561861+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}}},
    ],
}


@pytest.fixture
def codex_login(tmp_path, monkeypatch):
    """A logged-in codex home (CODEX_HOME is codex's own override)."""
    home = tmp_path / "codex"
    home.mkdir()
    (home / "auth.json").write_text(json.dumps(
        {"tokens": {"access_token": "tok", "account_id": "acct"}}))
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


@pytest.fixture
def claude_login(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    home.mkdir()
    (home / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"accessToken": "tok"}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    return home


def test_fetch_codex_usage_normalizes_the_window(codex_login, monkeypatch):
    seen = {}

    def get_json(url, headers):
        seen["url"], seen["headers"] = url, headers
        return CODEX_USAGE_BODY

    monkeypatch.setattr(usage, "_get_json", get_json)
    snap = usage.fetch_codex_usage()
    assert snap == {"backend": "codex", "plan_type": "plus", "limits": [
        {"key": "primary", "used_percent": 11, "window_minutes": 10080,
         "resets_at": 1785905532}]}
    # limit_window_seconds -> minutes, so the web's windowLabel reads it as "weekly".
    assert snap["limits"][0]["window_minutes"] == 10080
    assert seen["url"] == usage.CODEX_USAGE_URL
    assert seen["headers"]["chatgpt-account-id"] == "acct"


def _http_error(code):
    return urllib.error.HTTPError("https://x/usage", code, "reason", {}, None)


@pytest.mark.parametrize("code,retryable", [
    (403, True),    # the measured failure — whatever produces it, another attempt may differ
    (429, True),
    (500, True),
    (401, False),   # not logged in is a VERDICT: retrying only delays the same answer
    (404, False),
])
def test_which_statuses_are_worth_retrying(code, retryable, monkeypatch):
    # Drives the real status -> retryable mapping through urlopen. The earlier version of
    # these tests monkeypatched `_get_json_once` and hand-wrote the flag, so they would
    # have passed against an implementation that retried 401 too — i.e. they pinned the
    # test's own opinion rather than the code's.
    def boom(req, timeout=None):
        raise _http_error(code)
    monkeypatch.setattr(usage.urllib.request, "urlopen", boom)
    assert usage._get_json_once("https://x/usage", {}) == (None, retryable)


def test_a_retryable_failure_is_retried_and_the_recovery_is_kept(monkeypatch):
    # MEASURED 2026-07-31: the 12:00 pass fit-scored 26 rows and the usage fetch returned
    # 403; hand-calling straight after gave 403 / 200 / 403 within forty seconds. Without
    # a retry the snapshot silently goes stale and every downstream quota decision reads
    # an old number.
    calls = []

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(403)
        return _FakeResp(json.dumps({"ok": True}))

    monkeypatch.setattr(usage.urllib.request, "urlopen", flaky)
    assert usage._get_json("https://x/usage", {}, sleep=lambda _s: None) == {"ok": True}
    assert len(calls) == 2


def test_a_verdict_status_is_not_retried(monkeypatch):
    calls = []

    def denied(req, timeout=None):
        calls.append(1)
        raise _http_error(401)

    monkeypatch.setattr(usage.urllib.request, "urlopen", denied)
    assert usage._get_json("https://x/usage", {}, sleep=lambda _s: None) is None
    assert len(calls) == 1


def test_the_attempt_bound_and_the_sleep_schedule_are_the_module_defaults(monkeypatch):
    # Pins the DEFAULTS, not an argument the test supplies: the previous version passed
    # attempts=3 explicitly, so raising _ATTEMPTS to 50 kept it green.
    calls, slept = [], []
    monkeypatch.setattr(usage.urllib.request,
                        "urlopen", lambda req, timeout=None: calls.append(1) or
                        (_ for _ in ()).throw(_http_error(403)))
    monkeypatch.setattr(usage.time, "sleep", slept.append)
    assert usage._get_json("https://x/usage", {}) is None
    assert len(calls) == usage._ATTEMPTS
    # one sleep BETWEEN attempts, never after the last, and growing past the only
    # interval at which the endpoint was ever observed to change state
    assert slept == list(usage._RETRY_SLEEPS)[:usage._ATTEMPTS - 1]
    assert slept == sorted(slept) and slept[-1] >= 20.0


def test_codex_usage_sends_a_non_default_user_agent(codex_login, monkeypatch):
    # chatgpt.com is behind Cloudflare, which 403s urllib's default Python-urllib/3.x.
    # Without an explicit UA the bar silently never updates (verified 2026-07-29).
    seen = {}
    monkeypatch.setattr(usage, "_get_json",
                        lambda url, headers: seen.update(headers) or CODEX_USAGE_BODY)
    usage.fetch_codex_usage()
    assert seen["User-Agent"] and not seen["User-Agent"].startswith("Python-urllib")


def test_fetch_codex_usage_none_when_not_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "absent"))
    monkeypatch.setattr(usage, "_get_json",
                        lambda *a, **k: pytest.fail("must not call out without auth"))
    assert usage.fetch_codex_usage() is None


def test_fetch_claude_usage_prefers_the_limits_array_and_keeps_the_model_scope(
        claude_login, monkeypatch):
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: CLAUDE_USAGE_BODY)
    snap = usage.fetch_claude_usage()
    assert snap["backend"] == "claude"
    # The scoped weekly row must stay distinguishable from the pooled one — both are
    # "weekly", and 72% beside 2% under one label reads as a contradiction.
    assert [(l["key"], l["used_percent"], l["window_minutes"]) for l in snap["limits"]] == [
        ("session", 2, 300),
        ("weekly_all", 72, 10080),
        ("weekly_scoped (Fable)", 2, 10080),
    ]


def test_claude_usage_falls_back_to_the_flat_buckets(claude_login, monkeypatch):
    # An account on the other side of the limits[] migration must still render.
    body = {k: v for k, v in CLAUDE_USAGE_BODY.items() if k != "limits"}
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: body)
    snap = usage.fetch_claude_usage()
    assert [(l["key"], l["used_percent"]) for l in snap["limits"]] == [
        ("five_hour", 2.0), ("seven_day", 72.0)]      # the null seven_day_opus is skipped


def test_claude_usage_parses_iso_resets_into_epoch_seconds(claude_login, monkeypatch):
    # Codex sends an int, Claude an ISO string; the web reads one epoch field.
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: CLAUDE_USAGE_BODY)
    resets = usage.fetch_claude_usage()["limits"][0]["resets_at"]
    assert isinstance(resets, int)
    assert resets == int(datetime.fromisoformat(
        "2026-07-29T19:59:59.561596+00:00").timestamp())


def test_epoch_tolerates_a_z_suffix_and_junk():
    assert usage._epoch(1785905532) == 1785905532
    assert usage._epoch("2026-07-29T19:59:59Z") == usage._epoch("2026-07-29T19:59:59+00:00")
    assert usage._epoch("not-a-date") is None
    assert usage._epoch(None) is None


def test_capture_usage_writes_atomically_and_leaves_no_tmp(codex_login, tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: CODEX_USAGE_BODY)
    path = str(tmp_path / "scorer_usage.json")
    assert usage.capture_usage(path, "codex") is True
    assert json.loads((tmp_path / "scorer_usage.json").read_text())["backend"] == "codex"
    assert not list(tmp_path.glob("scorer_usage.json*.tmp"))


def test_capture_usage_stamps_as_of_so_a_stale_reading_is_legible(codex_login, tmp_path,
                                                                  monkeypatch):
    # The instrument the quota decisions read. Without this field a stale snapshot and a
    # fresh one look identical to anything but `ls -la` — which is how one --score-limit
    # decision came out ~17 points optimistic.
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: CODEX_USAGE_BODY)
    path = tmp_path / "scorer_usage.json"
    assert usage.capture_usage(str(path), "codex") is True
    stamped = json.loads(path.read_text())["as_of"]
    assert datetime.fromisoformat(stamped).tzinfo is not None   # local time, offset-aware


def test_capture_usage_keeps_the_last_good_snapshot_when_the_fetch_fails(
        codex_login, tmp_path, monkeypatch):
    # A transient 429 / expired token must dim the bar's freshness, not blank it.
    path = tmp_path / "scorer_usage.json"
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: CODEX_USAGE_BODY)
    usage.capture_usage(str(path), "codex")
    monkeypatch.setattr(usage, "_get_json", lambda url, headers: None)
    assert usage.capture_usage(str(path), "codex") is False
    assert json.loads(path.read_text())["backend"] == "codex"   # previous reading intact


def test_capture_usage_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "absent"))
    assert usage.capture_usage("/nonexistent-dir/deep/none.json", "codex") is False
    assert usage.capture_usage(str(tmp_path / "u.json"), "gemini") is False   # unknown backend


def test_get_json_names_the_http_status_when_the_provider_raises(capsys):
    import urllib.error

    def raising(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usage.urllib.request, "urlopen", raising)
        assert usage._get_json("https://x/usage", {}, attempts=1) is None
    out = capsys.readouterr().out
    assert "429" in out and "https://x/usage" in out


def test_get_json_names_the_exception_when_the_connection_fails(capsys):
    import urllib.error

    def raising(req, timeout=None):
        raise urllib.error.URLError("name resolution failed")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usage.urllib.request, "urlopen", raising)
        assert usage._get_json("https://x/usage", {}, attempts=1) is None
    assert "URLError" in capsys.readouterr().out


def test_an_unanticipated_failure_cannot_colour_the_pass_and_still_says_why(
        codex_login, tmp_path, capsys):
    # The no-raise guarantee lives in capture_usage, not in _get_json -- that catch is
    # narrow on purpose. But narrow is only defensible if the blanket catch SPEAKS:
    # otherwise an exception type the fetchers do not anticipate produces silence, which
    # is worse than one more 403. (The codex_login fixture is load-bearing: without it
    # _codex_auth returns None and urlopen is never reached, so the test would pass
    # while asserting nothing.)
    def raising(req, timeout=None):
        raise RuntimeError("something nobody anticipated")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usage.urllib.request, "urlopen", raising)
        assert usage.capture_usage(str(tmp_path / "u.json"), "codex") is False
    assert "RuntimeError" in capsys.readouterr().out


def test_a_200_with_no_usable_window_says_so_instead_of_going_quiet(codex_login, capsys):
    # The prime-suspect shape MINUS the status code: the endpoint answers 200 and the
    # window carries a null used_percent. Nothing named this before, so the instrument
    # could have missed the very failure it was built for.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usage, "_get_json",
                   lambda url, headers: {"rate_limit": {"primary_window":
                                                        {"used_percent": None}}})
        assert usage.fetch_codex_usage() is None
    assert "no usable window" in capsys.readouterr().out


def test_a_200_that_is_not_the_expected_shape_says_so(codex_login, capsys):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usage, "_get_json", lambda url, headers: {"unexpected": 1})
        assert usage.fetch_codex_usage() is None
    assert "no rate_limit object" in capsys.readouterr().out


def test_a_truncated_body_is_caught_and_named(capsys):
    # IncompleteRead/BadStatusLine subclass neither OSError nor ValueError, so before
    # this they escaped _get_json entirely and capture_usage swallowed them in silence.
    import http.client

    def raising(req, timeout=None):
        raise http.client.IncompleteRead(b"partial")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usage.urllib.request, "urlopen", raising)
        assert usage._get_json("https://x/usage", {}, attempts=1) is None
    assert "IncompleteRead" in capsys.readouterr().out


def test_a_200_whose_body_is_not_an_object_says_so(codex_login, capsys):
    # The last silent path the pre-merge review found empirically: valid JSON that is
    # not a dict parsed fine, so _get_json said nothing and the shape check returned
    # None with zero output -- making SPEC's "every route names itself" literally untrue.
    for body in ([], "nonsense", 3):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(usage, "_get_json", lambda url, headers, b=body: b)
            assert usage.fetch_codex_usage() is None
        assert "not an object" in capsys.readouterr().out
