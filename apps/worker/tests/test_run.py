"""TDD for the entrypoint: --once runs the three stages in order, env plumbing."""
from __future__ import annotations

import errno
import os

import pytest

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
from ats_worker import run
from ats_worker import screening as screening_mod
from tests._helpers import bootstrap_db, make_posting




def test_feed_session_is_per_thread():
    # The concurrent feed fetch needs ONE requests.Session per worker thread (Session
    # is not safe to share). Same thread reuses; different threads get distinct ones.
    import threading

    a1, a2 = run._feed_session(), run._feed_session()
    assert a1 is a2  # reused within a thread

    other: list = []
    t = threading.Thread(target=lambda: other.append(run._feed_session()))
    t.start(); t.join()
    assert other[0] is not a1  # a different thread gets its own


def test_load_env_reads_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "ANTHROPIC_API_KEY=sk-abc\n"
        "TELEGRAM_BOT_TOKEN=123:xyz\n"
        "# a comment\n"
        "\n"
        'TELEGRAM_CHAT_ID="555"\n'
        "OLLAMA_HOST=http://ollama:11434\n"
    )
    out = run.load_env(str(env))
    assert out["ANTHROPIC_API_KEY"] == "sk-abc"
    assert out["TELEGRAM_BOT_TOKEN"] == "123:xyz"
    assert out["TELEGRAM_CHAT_ID"] == "555"  # quotes stripped
    assert out["OLLAMA_HOST"] == "http://ollama:11434"


def test_load_env_on_a_directory_returns_empty_not_crash(tmp_path):
    # docker-compose bind-mounting a non-existent .env source creates an empty
    # DIRECTORY at the target; load_env must tolerate that (IsADirectoryError)
    # the same way it tolerates a missing file, not blow up the worker.
    d = tmp_path / "as_dir"
    d.mkdir()
    assert run.load_env(str(d)) == {}


def _stub_pass_record(monkeypatch):
    """For tests that run run_once over a FakeConn: the worker_runs writes are no-ops."""
    monkeypatch.setattr(run.db, "start_pass", lambda conn, **_: 1)
    monkeypatch.setattr(run.db, "update_pass_counts", lambda *_a, **_k: None)
    monkeypatch.setattr(run.db, "finish_pass", lambda *_a, **_k: None)


def test_run_once_fetch_only_stops_before_the_screen(monkeypatch):
    # --fetch-only must return BEFORE any screen call (a quota-free board refresh).
    order = []
    for stage, ret in (("run_fetch", 0), ("run_expire", 0), ("run_screen", None)):
        monkeypatch.setattr(run.pipeline, stage,
                            lambda *a, _s=stage, **k: order.append(_s))

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    _stub_pass_record(monkeypatch)
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_candidate_profile", lambda conn: None)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])
    monkeypatch.setattr(run.db, "get_by_status", lambda conn, status: [])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    run.run_once(cfg, db_path=":memory:", env=_ENV,
                 fetch_only=True)
    assert order == ["run_fetch", "run_expire"]  # no screen


def test_run_once_unscored_refresh_runs_as_an_isolated_source_only_mode(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(run.pipeline, "run_unscored_refresh",
                        lambda conn, **kwargs: calls.append(kwargs) or {})
    for stage in ("run_fetch", "run_expire", "run_screen"):
        monkeypatch.setattr(run.pipeline, stage,
                            lambda *a, _stage=stage, **k: pytest.fail(f"unexpected {_stage}"))
    cfg = cfgmod.load_config("companies: []\n")
    run.run_once(
        cfg, db_path=db_path, env={}, refresh_unscored=True,
        refresh_source="smartrecruiters", refresh_limit=3,
    )
    assert len(calls) == 1
    assert calls[0]["source"] == "smartrecruiters"
    assert calls[0]["limit"] == 3
    assert callable(calls[0]["observation_fn"])


def test_run_once_defaults_codex_to_luna_medium(monkeypatch, tmp_path):
    cfg = cfgmod.load_config("companies: []\n")
    dbfile = bootstrap_db(tmp_path / "screen-only-codex.db")
    captured = {}
    extract = lambda *_args: {"screen": {}}
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(run.pipeline, "run_expire", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(run, "make_screener", lambda *args, **kwargs: (
        captured.update(make_screener=(args, kwargs)) or extract))
    monkeypatch.setattr(run.pipeline, "run_screen", lambda *_args, **kwargs:
                        captured.update(run_screen=kwargs))

    monkeypatch.setattr(run, "capture_usage", lambda path, backend:
                        captured.update(usage=(path, backend)) or True)

    run.run_once(cfg, db_path=str(dbfile), env={}, screen_backend="codex")

    assert captured["make_screener"][1]["screen_model"] == "gpt-5.6-luna"
    assert captured["make_screener"][1]["screen_effort"] == "medium"
    assert captured["run_screen"]["model"] == "gpt-5.6-luna"
    assert captured["run_screen"]["effort"] == "medium"
    assert captured["run_screen"]["limit"] == 40
    assert captured["run_screen"]["screen_workers"] == 1
    assert captured["run_screen"]["clock"] is run._now
    assert captured["usage"] == (str(tmp_path / "quota.json"), "codex")


@pytest.mark.parametrize("backend,captures", [("claude-code", True), ("api", False),
                                                ("ollama", False)])
def test_run_once_captures_quota_only_for_subscription_backends(
        backend, captures, monkeypatch, tmp_path):
    dbfile = bootstrap_db(tmp_path / "q.db")
    seen = []
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *_a, **_k: 0)
    monkeypatch.setattr(run.pipeline, "run_expire", lambda *_a, **_k: 0)
    monkeypatch.setattr(run, "make_screener", lambda *_a, **_k: None)
    monkeypatch.setattr(run.pipeline, "run_screen", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "capture_usage", lambda path, b: seen.append((path, b)))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile), env={},
                 screen_backend=backend, screen_model="m")
    assert seen == ([(str(tmp_path / "quota.json"), backend)] if captures else [])


# --- watchlist bootstrap + feed wiring ------------------------------------

_ENV = {"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"}


def _stub_stages(monkeypatch):
    for stage in ("run_fetch", "run_screen"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)


def test_run_once_seeds_watchlist_from_config_when_empty(monkeypatch, tmp_path):
    _stub_stages(monkeypatch)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "  - { source: lever, slug: b, name: B }\n"
    )
    run.run_once(cfg, db_path=str(dbfile), env=_ENV)

    conn = dbmod.connect(str(dbfile))
    assert dbmod.get_watchlist(conn) == [
        {"source": "greenhouse", "slug": "a", "name": "A", "recipe": None},
        {"source": "lever", "slug": "b", "name": "B", "recipe": None},
    ]
    # a second pass does not duplicate (watchlist no longer empty)
    run.run_once(cfg, db_path=str(dbfile), env=_ENV)
    assert dbmod.count_watchlist(dbmod.connect(str(dbfile))) == 2


def test_run_once_gates_browser_sources(monkeypatch, tmp_path):
    _stub_stages(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda conn, companies, tf, *, now, **k:
                        seen.__setitem__("sources", [c["source"] for c in companies]) or 0)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    conn = dbmod.connect(str(dbfile))
    dbmod.import_watchlist(conn, [
        {"source": "greenhouse", "slug": "a", "name": "A", "recipe": None},
        {"source": "browser", "slug": "cs", "name": "CS", "recipe": {"url": "x", "item": "a"}},
    ], now="2026-01-01T00:00:00Z")
    conn.close()

    # default: browser rows filtered out of the fetch
    run.run_once(cfgmod.load_config("companies: []\n"),
                 db_path=str(dbfile), env=_ENV)
    assert "browser" not in seen["sources"] and "greenhouse" in seen["sources"]

    # enable_browser_sources: they pass through
    run.run_once(cfgmod.load_config("companies: []\nenable_browser_sources: true\n"),
                 db_path=str(dbfile), env=_ENV)
    assert "browser" in seen["sources"]


def test_run_once_runs_enabled_feed_and_skips_disabled(monkeypatch, tmp_path):
    _stub_stages(monkeypatch)
    calls = []
    monkeypatch.setattr(run.pipeline, "run_feed",
                        lambda conn, *, now, feed_fn, keep_categories, feed_name, **k:
                        calls.append((feed_name, keep_categories)) or 0)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))

    cfg_on = cfgmod.load_config(
        "companies: []\nfeeds:\n  simplify:\n    enabled: true\n    categories: [Software]\n"
    )
    run.run_once(cfg_on, db_path=str(dbfile), env=_ENV)
    assert calls == [("simplify", ["Software"])]

    calls.clear()
    cfg_off = cfgmod.load_config("companies: []\nfeeds:\n  simplify:\n    enabled: false\n")
    run.run_once(cfg_off, db_path=str(dbfile), env=_ENV)
    assert calls == []


def test_run_once_screen_backend_none_makes_no_provider_call(monkeypatch, tmp_path):
    # A GPU-less user: the pass must complete with zero screen calls.
    _stub_stages(monkeypatch)
    seen = {}
    monkeypatch.setattr(run, "make_screener",
                        lambda backend, **kw: seen.setdefault("backend", backend))
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile), env=_ENV, screen_backend="none")
    assert seen["backend"] == "none"


def test_run_once_uses_screen_model_override(monkeypatch, tmp_path):
    # --screen-model/SCREEN_MODEL must reach the hosted adapter's build call.
    # make_screener itself already threads screen_model per-call (Task 5); the gap
    # this closes is run_once accepting and forwarding it at all.
    _stub_stages(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        screening_mod, "make_api_extract",
        lambda **kw: seen.update(model=kw["model"]) or (lambda p, s: {}))
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile), env=_ENV, screen_backend="api",
                 screen_model="claude-sonnet-5")
    assert seen["model"] == "claude-sonnet-5"


# --- run_once builds the candidate + plumbs Ollama env (the real wiring) ---

def _run_once_capturing_screen(monkeypatch, tmp_path, cfg, env):
    """Run run_once with the screen stage feeding one posting to the wired screen_fn,
    capturing the kwargs it passes to screen_posting, plus the kwargs the REAL
    make_screener (not mocked here) passes on to make_ollama_extract — that is where
    OLLAMA_HOST lands, since it is not a screen_posting kwarg."""
    captured = {}

    def fake_screen_posting(posting, **kwargs):
        captured["kwargs"] = kwargs
        captured["posting"] = posting
        return {"disqualified": False}

    def fake_make_ollama_extract(**kwargs):
        captured["extract_kwargs"] = kwargs
        return lambda prompt, schema: {}

    monkeypatch.setattr(run, "screen_posting", fake_screen_posting)
    monkeypatch.setattr(screening_mod, "make_ollama_extract", fake_make_ollama_extract)
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_screen",
                        lambda conn, *, screen_fn, **k: screen_fn(make_posting("1")))

    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    conn = dbmod.connect(str(dbfile))
    dbmod.upsert_postings(conn, [make_posting("1")], now="2026-01-01T00:00:00.000Z")
    conn.close()

    run.run_once(cfg, db_path=str(dbfile), env=env)
    return captured


def test_run_once_builds_candidate_and_honors_num_ctx(monkeypatch, tmp_path):
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "candidate:\n"
        "  highest_degree: \"Master's\"\n"
        "  locations: ['remote', 'USA']\n"
    )
    env = {"OLLAMA_NUM_CTX": "4096", "OLLAMA_HOST": "http://ol:11434",
           "ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    captured = _run_once_capturing_screen(monkeypatch, tmp_path, cfg, env)
    kw = captured["kwargs"]
    cand = kw["candidate"]
    assert cand["highest_degree"] == "master's"  # canonical DEGREES value, same rank
    assert cand["locations"] == ["remote", "USA"]
    assert cand["exclude_internships"] is False        # defaults off; plumbed through
    assert kw["num_ctx"] == 4096                       # OLLAMA_NUM_CTX honored
    assert captured["extract_kwargs"]["ollama_host"] == "http://ol:11434"






def test_make_screener_none_returns_no_extract():
    # SCREEN_BACKEND=none must produce NO callable at all — screen_posting then runs
    # the deterministic gates only and never attempts a provider call.
    assert run.make_screener("none", env={}, http=None) is None


def test_make_screener_ollama_builds_a_working_extract(monkeypatch):
    calls = []

    class FakeHttp:
        def post(self, url, json=None, timeout=None):
            calls.append(url)

            class R:
                status_code = 200

                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    return {"response": '{"screen": {}}'}
            return R()

    extract = run.make_screener("ollama", env={"OLLAMA_HOST": "http://x:11434"},
                                http=FakeHttp(), model="m")
    assert extract("prompt", {}) == {"screen": {}}
    assert calls == ["http://x:11434/api/generate"]


def test_make_screener_codex_wires_model(monkeypatch):
    # Same dispatch pattern as the HTTP backends: the seam only needs to pass the
    # right model through, so the real (subprocess-shelling) adapter is faked out.
    monkeypatch.setattr(screening_mod, "make_codex_extract", lambda model: ("codex", model))
    assert run.make_screener("codex", env={}, http=None) == (
        "codex", "gpt-5.6-luna")
    assert run.make_screener("codex", env={}, http=None,
                             screen_model="gpt-5.6-luna") == ("codex", "gpt-5.6-luna")


def test_make_screener_codex_wires_reasoning_effort(monkeypatch):
    monkeypatch.setattr(screening_mod, "make_codex_extract",
        lambda model, reasoning_effort=None: ("codex", model, reasoning_effort))
    assert run.make_screener("codex", env={}, http=None,
                             screen_model="gpt-5.6-luna",
                             screen_effort="medium") == (
        "codex", "gpt-5.6-luna", "medium")


def test_screen_only_is_an_accepted_alias_for_the_default_pass(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    captured = {}
    def load_screen_config(_path, **kwargs):
        captured["config_options"] = kwargs
        return object()
    monkeypatch.setattr(run.config_mod, "load_config", load_screen_config)
    monkeypatch.setattr(run, "run_once",
                        lambda _cfg, **kwargs: captured.update(kwargs))

    run.main([
        "--once", "--screen-only", "--screen-backend", "none",
        "--config", "unused.yaml", "--env", str(env_file),
        "--db", str(tmp_path / "applications.db"),
    ])

    assert captured["config_options"] == {}
    assert captured["fetch_only"] is False
    assert captured["screen_limit"] == 40


@pytest.mark.parametrize("mode_args", [
    ["--screen-only", "--fetch-only"],
    ["--rescreen-screened", "--fetch-only"],
    ["--screen-only", "--screen-limit", "0"],
    ["--fetch-only", "--screen-unlimited"],
    ["--screen-only", "--screen-unlimited", "--screen-limit", "1"],
])
def test_screen_only_invalid_combinations_fail_before_config_or_db(
        mode_args, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda _path: pytest.fail("config must not load"))
    with pytest.raises(SystemExit):
        run.main([*mode_args, "--once", "--config", "unused.yaml",
                  "--env", str(env_file), "--db", str(tmp_path / "db.sqlite")])


def test_rescreen_screened_requires_one_shot(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda _path: pytest.fail("config must not load"))
    with pytest.raises(SystemExit):
        run.main(["--screen-only", "--rescreen-screened", "--config", "unused.yaml",
                  "--env", str(env_file), "--db", str(tmp_path / "db.sqlite")])


@pytest.mark.parametrize("mode_args", [
    ["--refresh-unscored", "--refresh-source", "smartrecruiters"],
    ["--once", "--refresh-unscored"],
    ["--once", "--refresh-unscored", "--refresh-source", "smartrecruiters",
     "--refresh-limit", "26"],
    ["--once", "--refresh-unscored", "--refresh-source", "smartrecruiters",
     "--fetch-only"],
])
def test_unscored_refresh_invalid_combinations_fail_before_config_or_db(
        mode_args, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda _path: pytest.fail("config must not load"))
    with pytest.raises(SystemExit):
        run.main([*mode_args, "--config", "unused.yaml", "--env", str(env_file),
                  "--db", str(tmp_path / "db.sqlite")])


def test_make_screener_claude_code_wires_model(monkeypatch):
    # Same dispatch pattern. screen_model=None (the default) must pass through as
    # None rather than a hard-coded default — make_claude_code_extract's own
    # `model=None` picks the CLI's default model in that case.
    monkeypatch.setattr(screening_mod, "make_claude_code_extract", lambda model: ("claude-code", model))
    assert run.make_screener("claude-code", env={}, http=None) == ("claude-code", None)
    assert run.make_screener("claude-code", env={}, http=None,
                             screen_model="claude-opus-4-8") == (
        "claude-code", "claude-opus-4-8")


def test_make_screener_api_wires_base_url_key_and_model(monkeypatch):
    seen = {}
    monkeypatch.setattr(screening_mod, "make_api_extract",
                        lambda **kw: seen.update(kw) or "X")
    env = {"SCREEN_API_BASE_URL": "https://openrouter.ai/api/v1/", "SCREEN_API_KEY": "k"}
    assert run.make_screener("api", env=env, http="H", screen_model="vendor/m") == "X"
    assert seen == {"base_url": "https://openrouter.ai/api/v1", "api_key": "k",
                    "model": "vendor/m", "http": "H"}
    run.make_screener("api", env={}, screen_model="m")
    assert seen["base_url"] == "https://api.openai.com/v1" and seen["api_key"] is None


def test_make_screener_api_requires_a_model():
    with pytest.raises(ValueError, match="needs SCREEN_MODEL"):
        run.make_screener("api", env={"SCREEN_API_KEY": "k"})


def test_ollama_ignores_a_leftover_screen_model():
    assert run.screen_model_for("ollama", screen_model="gpt-5.6-luna",
                                ollama_model="custom:1b") == "custom:1b"
    assert run.screen_model_for("ollama", screen_model="gpt-5.6-luna") == "qwen3.5:4b"


def test_main_rejects_api_without_a_model_before_any_work(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("SCREEN_BACKEND=api\n")
    monkeypatch.setattr(run.os, "environ", dict(run.os.environ))
    for k in ("SCREEN_BACKEND", "SCREEN_MODEL"):
        run.os.environ.pop(k, None)
    monkeypatch.setattr(run, "run_once", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(SystemExit):
        run.main(["--once", "--env", str(env_file), "--db", str(tmp_path / "d.db")])
    assert "needs SCREEN_MODEL" in capsys.readouterr().err


@pytest.mark.parametrize("retired", ["openai-api", "claude-api"])
def test_main_rejects_retired_backends_before_any_work(retired, tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(f"SCREEN_BACKEND={retired}\n")
    monkeypatch.setattr(run.os, "environ", dict(run.os.environ))
    run.os.environ.pop("SCREEN_BACKEND", None)
    monkeypatch.setattr(run, "run_once", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(SystemExit):
        run.main(["--once", "--env", str(env_file), "--db", str(tmp_path / "d.db")])
    assert "SCREEN_BACKEND=api" in capsys.readouterr().err


def test_make_screener_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown screen backend"):
        run.make_screener("gpt9", env={}, http=None)


def test_default_screen_backend_is_free():
    # "Auto-detection must never select a paid backend" is satisfied BY CONSTRUCTION:
    # there is no auto-detection. The backend is always explicit and defaults to the
    # free local one, so no code path can reach a metered provider without the operator
    # naming it. This test pins that property against a future "helpfully" added probe.
    assert run.DEFAULT_SCREEN_BACKEND == "ollama"
    assert run.make_screener(run.DEFAULT_SCREEN_BACKEND, env={}, http=None,
                             model="m") is not None


def test_run_once_threads_fetch_filters(monkeypatch):
    captured = {}
    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda *a, **k: captured.update(k) or 0)
    for stage in ("run_expire", "run_screen"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    _stub_pass_record(monkeypatch)
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    stored: dict = {}
    monkeypatch.setattr(run.db, "write_candidate_profile",
                        lambda conn, values, *, actor, now: stored.update(values, actor=actor))
    monkeypatch.setattr(run.db, "get_candidate_profile", lambda conn: dict(stored) or None)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "max_age_days: 30\n"
        "title_exclude: [intern]\n"
        "candidate: { locations: [USA] }\n"
    )
    run.run_once(cfg, db_path=":memory:", env=_ENV)
    assert captured["max_age_days"] == 30
    assert captured["title_exclude"] == ["intern"]
    assert captured["candidate"]["locations"] == ["USA"]


def test_run_once_empty_candidate_skips_screening(monkeypatch, tmp_path):
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    env = {"OLLAMA_HOST": "h", "ANTHROPIC_API_KEY": "k",
           "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    kw = _run_once_capturing_screen(monkeypatch, tmp_path, cfg, env)["kwargs"]
    assert kw["candidate"] is None                     # is_empty() -> no SCREEN call
    assert kw["num_ctx"] == 8192                        # default when env omits it



# --- main() honors .env for argparse defaults -------------------------------

def test_main_merges_env_file_into_argparse_defaults(monkeypatch, tmp_path):
    # SCREEN_BACKEND / OLLAMA_MODEL / DB_PATH / SCREEN_MODEL set in .env must reach
    # run_once — regression guard for the bug where load_env's dict was never merged
    # into os.environ (so the os.environ-derived argparse defaults ignored .env).
    import os as _os
    monkeypatch.setattr(_os, "environ", dict(_os.environ))
    for k in ("SCREEN_BACKEND", "OLLAMA_MODEL", "DB_PATH", "SCREEN_MODEL"):
        _os.environ.pop(k, None)

    envfile = tmp_path / ".env"
    envfile.write_text(
        "SCREEN_BACKEND=api\n"
        "OLLAMA_MODEL=custom:1b\n"
        "DB_PATH=/tmp/from-env.db\n"
        "SCREEN_MODEL=claude-from-env\n"
        "ANTHROPIC_API_KEY=k\n"
    )

    captured = {}
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: captured.update(kw))
    # run.config_mod IS cfgmod (same module object, `from . import config as config_mod`),
    # so the stub must close over the real load_config captured before patching — routing
    # through `cfgmod.load_config` inside the replacement would call itself and recurse.
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))

    run.main(["--once", "--env", str(envfile)])

    assert captured["screen_backend"] == "api"
    assert captured["ollama_model"] == "custom:1b"
    assert captured["db_path"] == "/tmp/from-env.db"
    assert captured["screen_model"] == "claude-from-env"
    assert captured["env"]["ANTHROPIC_API_KEY"] == "k"   # dict still plumbed to run_once


def test_main_env_merge_excludes_secrets(monkeypatch, tmp_path):
    # Regression guard for the secret-scoping regression: main() must only promote
    # the argparse-read config keys from .env into os.environ, never secrets — a
    # leaked os.environ secret would be inherited by the codex CLI subprocess.
    import os as _os
    monkeypatch.setattr(_os, "environ", dict(_os.environ))
    for k in ("DB_PATH", "OLLAMA_MODEL", "SCREEN_BACKEND", "SCREEN_MODEL",
              "SCORE_BACKEND", "CODEX_SCORE_MODEL",
              "ANTHROPIC_SCORE_MODEL", "CODEX_BATCH_SIZE",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SCREEN_API_KEY",
              "OPENAI_API_KEY"):
        _os.environ.pop(k, None)

    envfile = tmp_path / ".env"
    envfile.write_text(
        "DB_PATH=/tmp/from-env.db\n"
        "OLLAMA_MODEL=custom:1b\n"
        "SCREEN_BACKEND=api\n"
        "SCREEN_MODEL=claude-opus-4-8\n"
        "SCORE_BACKEND=claude-api\n"
        "CODEX_SCORE_MODEL=gpt-from-env\n"
        "ANTHROPIC_SCORE_MODEL=claude-from-env\n"
        "CODEX_BATCH_SIZE=3\n"
        "TELEGRAM_BOT_TOKEN=secret-tok\n"
        "TELEGRAM_CHAT_ID=c\n"
        "SCREEN_API_KEY=secret-key\n"
        "OPENAI_API_KEY=secret-openai-key\n"
    )

    captured = {}
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: captured.update(kw))
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))

    run.main(["--once", "--env", str(envfile)])

    # The argparse-read config keys must be promoted into os.environ.
    assert _os.environ["DB_PATH"] == "/tmp/from-env.db"
    assert _os.environ["OLLAMA_MODEL"] == "custom:1b"
    assert _os.environ["SCREEN_BACKEND"] == "api"
    assert _os.environ["SCREEN_MODEL"] == "claude-opus-4-8"
    # Retired fit-scorer keys are no longer argparse defaults, so they stay out too.
    for retired in ("SCORE_BACKEND", "CODEX_SCORE_MODEL", "ANTHROPIC_SCORE_MODEL",
                    "CODEX_BATCH_SIZE"):
        assert retired not in _os.environ

    # Secrets must never be promoted into os.environ (would leak to codex subprocess).
    assert "TELEGRAM_BOT_TOKEN" not in _os.environ
    assert "TELEGRAM_CHAT_ID" not in _os.environ
    assert "SCREEN_API_KEY" not in _os.environ
    assert "OPENAI_API_KEY" not in _os.environ

    # ... but secrets must still reach run_once via the in-process env dict.
    assert captured["env"]["TELEGRAM_BOT_TOKEN"] == "secret-tok"
    assert captured["env"]["TELEGRAM_CHAT_ID"] == "c"
    assert captured["env"]["SCREEN_API_KEY"] == "secret-key"
    assert captured["env"]["OPENAI_API_KEY"] == "secret-openai-key"


# --- one pass at a time (the host pass lock) ---------------------------------

def test_a_second_pass_is_refused_while_the_first_holds_the_lock(tmp_path):
    # The real race: a hand-run pass landing inside a scheduled one. The second
    # acquisition must fail IMMEDIATELY (no blocking, no queueing) and name the holder.
    # Two fds on one file conflict under flock even inside one process, so this needs
    # no subprocess.
    lock = tmp_path / "pass.lock"
    with run.pass_lock(lock):
        with pytest.raises(run.PassInProgress) as exc:
            with run.pass_lock(lock):
                pytest.fail("a second pass acquired a lock the first one holds")
    assert str(os.getpid()) in str(exc.value)      # says WHICH process holds it
    assert "quota" in str(exc.value)               # and why a duplicate pass matters

    with run.pass_lock(lock):                      # released on normal exit
        pass


def test_a_stale_lockfile_does_not_wedge_the_pipeline(tmp_path):
    # Host killed mid-pass: the file survives with a dead pid in it, but the kernel
    # dropped the flock with the process. The next pass must take it with no operator
    # deleting anything by hand.
    #
    # This has to be a REAL subprocess that is REALLY killed. Writing a dead pid into a
    # file nobody ever flocked would pass against a plain PID-file implementation too,
    # and kernel-release-on-death is the entire reason flock was chosen over one.
    import subprocess
    import sys
    lock = tmp_path / "pass.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,os,sys\n"
         "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
         "os.ftruncate(fd, 0); os.write(fd, f'{os.getpid()}\\n'.encode())\n"
         "print('held', flush=True)\n"
         "sys.stdin.read()\n",
         str(lock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(run.PassInProgress):     # genuinely held by another process
            with run.pass_lock(lock):
                pytest.fail("took a lock another process holds")
        holder.kill()                               # SIGKILL: no cleanup can run
        holder.wait(timeout=10)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)

    assert lock.exists()                            # nothing unlinked it
    assert lock.read_text().strip() == str(holder.pid)   # ... and it still names the dead pid
    with run.pass_lock(lock):                       # taken anyway, no manual cleanup
        assert lock.read_text().strip() == str(os.getpid())


def test_an_unopenable_lock_is_not_reported_as_contention(tmp_path):
    # A root-owned leftover from one sudo run, a 0600 file, a missing TMPDIR: each makes
    # os.open fail forever, and "never unlinked" means nothing self-heals. The one thing
    # it must NOT do is claim a pass is already running, which would send the operator
    # hunting a process that does not exist.
    lock = tmp_path / "missing-dir" / "pass.lock"
    with pytest.raises(RuntimeError) as exc:
        with run.pass_lock(lock):
            pytest.fail("opened a lock under a directory that does not exist")
    assert not isinstance(exc.value, run.PassInProgress)
    assert str(lock) in str(exc.value)              # names the path to fix
    assert "--db" in str(exc.value)


def test_an_unwritable_lock_still_guards_the_pass(tmp_path, capsys):
    # The expensive shape of the same failure: one accidental `sudo python -m
    # ats_worker.run` leaves a root-owned lock file that is never unlinked. flock needs
    # no write access, so refusing here would trade a WORKING guard for a daemon that
    # stays `active (running)`, reports a healthy schedule and never completes a pass —
    # the RuntimeError would be raised inside the APScheduler job, where the executor
    # catches and logs it. Degrade to a read-only hold instead.
    lock = tmp_path / "pass.lock"
    lock.write_text("999\n")
    lock.chmod(0o444)
    with run.pass_lock(lock):
        # still exclusive: a second pass is refused, which is the whole point
        with pytest.raises(run.PassInProgress):
            with run.pass_lock(lock):
                pytest.fail("two passes held an unwritable lock at once")
    out = capsys.readouterr().out
    assert "read-only" in out                    # the degradation is announced,
    assert "NOT recorded" in out                 # and so is the lost pid diagnostic


def test_an_unreadable_lock_fails_loud_instead_of_degrading(tmp_path, monkeypatch):
    # The read-only fallback exists for a lock we can still READ. One we cannot open at
    # all has nothing to degrade to, so it must fail loud like any other unopenable
    # lock — never silently proceed without a guard, and never claim contention.
    lock = tmp_path / "pass.lock"
    lock.write_text("1\n")
    real_open = os.open

    def denied(p, flags, *a, **kw):     # both modes refused, as for a 0600 file
        if str(p) == str(lock):         # owned by another user
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_open(p, flags, *a, **kw)

    monkeypatch.setattr(run.os, "open", denied)
    with pytest.raises(RuntimeError) as exc:
        with run.pass_lock(lock):
            pytest.fail("held a lock that could not be opened in either mode")
    assert not isinstance(exc.value, run.PassInProgress)
    assert str(lock) in str(exc.value)
    assert "--db" in str(exc.value)


def test_a_contender_never_names_a_dead_pid_as_the_holder(tmp_path):
    # The lock file is never unlinked, so its pid outlives the process that wrote it.
    # A read-only holder cannot overwrite it at all, and even a writable one has a
    # window between taking the flock and writing — so the bytes alone would make a
    # contender report a corpse as the running pass and send the operator hunting a
    # process that does not exist. That is the very "is this pid the same process"
    # guessing game flock exists to avoid.
    lock = tmp_path / "pass.lock"
    lock.write_text("999999\n")                  # a pid that is not running
    lock.chmod(0o444)                            # force the read-only hold
    with run.pass_lock(lock):
        with pytest.raises(run.PassInProgress) as exc:
            with run.pass_lock(lock):
                pytest.fail("two passes held the lock at once")
    assert "pid unknown" in str(exc.value)
    assert "999999" not in str(exc.value)


def test_a_contender_names_the_holder_when_the_pid_is_live(tmp_path):
    # The diagnostic still works in the normal case — the liveness check must not
    # turn every contention message into a useless "unknown".
    lock = tmp_path / "pass.lock"
    with run.pass_lock(lock):
        with pytest.raises(run.PassInProgress) as exc:
            with run.pass_lock(lock):
                pytest.fail("two passes held the lock at once")
    assert f"pid {os.getpid()}" in str(exc.value)


def test_a_filesystem_without_flock_is_not_reported_as_contention(monkeypatch, tmp_path):
    # NFS without lockd, some FUSE mounts: flock raises ENOLCK/ENOSYS rather than
    # EWOULDBLOCK. Reporting that as contention refuses EVERY pass forever while telling
    # the operator one is already running — a permanent silent outage.
    def no_locks(fd, op):
        raise OSError(errno.ENOLCK, "No locks available")
    monkeypatch.setattr(run.fcntl, "flock", no_locks)
    with pytest.raises(RuntimeError) as exc:
        with run.pass_lock(tmp_path / "pass.lock"):
            pytest.fail("took a lock on a filesystem that cannot lock")
    assert not isinstance(exc.value, run.PassInProgress)
    assert "not contention" in str(exc.value)


def test_the_lock_is_keyed_on_the_db_not_on_the_temp_dir(tmp_path, monkeypatch):
    # THE MONEY CASE. A systemd unit with PrivateTmp=yes, or a cron job with a sanitized
    # env, resolves a different temp dir than an interactive shell that exports TMPDIR.
    # Keyed on the temp dir, both passes acquired and both fit-scored the same rows on
    # the paid backend. Keyed on the db, the second one is refused however TMPDIR moves.
    db = tmp_path / "applications.db"
    db.touch()
    with run.pass_lock(db_path=db):
        monkeypatch.setattr(run, "_LOCK_PATH", tmp_path / "some-other-tmp" / "pass.lock")
        with pytest.raises(run.PassInProgress):
            with run.pass_lock(db_path=str(db)):   # str vs Path, and a moved TMPDIR
                pytest.fail("two passes acquired the same db — quota spent twice")

    # ...and a relative path naming the same file is still the same lock.
    monkeypatch.chdir(tmp_path)
    with run.pass_lock(db_path=db):
        with pytest.raises(run.PassInProgress):
            with run.pass_lock(db_path="applications.db"):
                pytest.fail("a relative --db dodged the guard")

    # Two checkouts pointed at two DBs are genuinely independent and must NOT block.
    other = tmp_path / "other" / "applications.db"
    other.parent.mkdir()
    other.touch()
    with run.pass_lock(db_path=db):
        with run.pass_lock(db_path=other):
            pass

    assert run._lock_path_for(db) == tmp_path / "applications.db.pass.lock"


def test_the_lock_is_released_when_the_pass_raises(tmp_path):
    lock = tmp_path / "pass.lock"
    with pytest.raises(ValueError):
        with run.pass_lock(lock):
            raise ValueError("boom")
    with run.pass_lock(lock):
        pass


def test_main_once_refuses_to_start_inside_another_pass(monkeypatch, tmp_path):
    # End of the wiring: a refused pass runs NOTHING (no fetch, no paid score) and
    # exits non-zero with a readable message rather than waiting for the lock.
    calls: list = []
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: calls.append(kw))
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))

    # Hold the lock for the SAME db main() will resolve — that is what the lock is keyed
    # on, so a test naming a different db would contend with nothing and pass vacuously.
    db = str(tmp_path / "applications.db")
    with run.pass_lock(db_path=db):
        with pytest.raises(SystemExit) as exc:
            run.main(["--once", "--db", db, "--env", str(tmp_path / "none.env")])
    assert "already running" in str(exc.value)
    assert calls == []


def test_a_scheduled_pass_skips_the_slot_instead_of_dying(monkeypatch, tmp_path, caplog):
    # Daemon side of the refusal: a scheduled firing that finds the lock held must skip
    # THIS slot and leave the daemon scheduled. A hand run raises SystemExit instead, and
    # conflating the two would take the daemon down whenever an operator ran a pass by
    # hand — which wall-clock slots make MORE likely, not less, because a habitual 08:00
    # hand run now collides with the 08:00 slot every single day.
    fired: list = []

    def fake_scheduler(job, schedule_hours):
        # Fire the registered job once, the way a real slot would, then return instead
        # of blocking. Discarding the callable would leave nothing under test.
        fired.append(schedule_hours)
        job()

    monkeypatch.setattr(run, "_run_scheduler", fake_scheduler)
    calls: list = []
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: calls.append(kw))
    monkeypatch.setattr(run, "_profile_for_pass", lambda conn, cfg, now: None)
    monkeypatch.setattr(run.db, "connect", lambda path: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(run.db, "has_table", lambda conn, name: True)
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))

    db = str(tmp_path / "applications.db")
    with run.pass_lock(db_path=db):
        run.main(["--db", db, "--env", str(tmp_path / "none.env")])

    assert calls == []                                   # the pass did not run
    # WARNING on the logging stream, not stdout: "a pass did not run" is the same signal
    # APScheduler emits for a misfire or a max-instances skip, and an operator reading
    # journald needs the two interleaved rather than split across stdout and stderr.
    assert "skipping this pass" in caplog.text
    assert {r.levelname for r in caplog.records} == {"WARNING"}
    assert fired == [24]                                 # ... but the daemon lives on


def test_main_once_takes_the_lock_and_gives_it_back(monkeypatch, tmp_path):
    # The lock is held for one pass, not for the process lifetime — otherwise a
    # daemon would hold it across its whole run and block every hand-run pass.
    calls: list = []
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: calls.append(kw))
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))

    db = str(tmp_path / "applications.db")
    run.main(["--once", "--db", db, "--env", str(tmp_path / "none.env")])
    assert len(calls) == 1
    with run.pass_lock(db_path=db):                # free again
        pass


# --- wall-clock schedule ---------------------------------------------------

@pytest.mark.parametrize("hours,expected", [
    (1, "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23"),
    (2, "0,2,4,6,8,10,12,14,16,18,20,22"),
    (3, "0,3,6,9,12,15,18,21"),
    (4, "0,4,8,12,16,20"),
    (6, "0,6,12,18"),
    (8, "0,8,16"),
    (12, "0,12"),
])
def test_the_schedule_is_evenly_spaced_wall_clock_slots(hours, expected):
    # The behavior change this replaces: `add_job(once, "interval", hours=h)` fired at
    # LAUNCH TIME + h, so starting the worker at 09:47 put passes at 09:47/13:47/17:47 and
    # a restart silently re-phased the whole day. Slots are now absolute, so a restart
    # cannot move them and two hosts agree on when a pass happens.
    assert run.cron_hours(hours) == expected


def test_a_daily_schedule_is_one_midnight_slot_and_not_an_empty_list():
    # The off-by-one that would be invisible: `range(0, 24, 24)` is `[0]`, but a `<`-vs-
    # `<=` slip gives `[]`, which APScheduler accepts as a trigger that NEVER FIRES. The
    # daemon would start clean, print a schedule, and sit dead forever — and 24 was the
    # shipped default, so this is the path most installs take.
    assert run.cron_hours(24) == "0"
    assert run.cron_hours(24).split(",") == ["0"]


def _daemon_harness(monkeypatch, schedule_hours=4):
    """Wire `main` for a daemon run with no apscheduler and no pipeline.

    `started` and `passes` append into a shared `order` list as well, so a test can
    assert SEQUENCE and not just counts — the stub returns instead of blocking, which
    hides the one thing that matters about `--run-now` (see the ordering test).
    """
    order: list = []
    started: list = []
    passes: list = []

    def fake_scheduler(job, hours):
        started.append(hours)
        order.append("scheduler")

    def fake_run_once(cfg, **kw):
        passes.append(kw)
        order.append("pass")

    monkeypatch.setattr(run, "_run_scheduler", fake_scheduler)
    monkeypatch.setattr(run, "run_once", fake_run_once)
    # The startup preference seed; a no-op here (no real DB behind the daemon stub).
    monkeypatch.setattr(run.db, "connect", lambda path: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(run.db, "has_table", lambda conn, name: True)
    monkeypatch.setattr(run, "_profile_for_pass", lambda conn, cfg, now: None)
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config(
                            f"companies: []\nschedule_hours: {schedule_hours}\n"))
    return started, passes, order


def test_starting_the_daemon_runs_no_pass_at_launch(monkeypatch, tmp_path):
    # The eager `once()` before `scheduler.start()` is GONE. It made every restart cost an
    # immediate full pass — at 6 passes/day a daemon bounced three times ran nine — and it
    # was also masking APScheduler's one-second default misfire grace, because a restarted
    # daemon always ran promptly whether or not it had missed a slot.
    started, passes, order = _daemon_harness(monkeypatch)
    run.main(["--env", str(tmp_path / "none.env")])
    assert passes == []            # nothing ran...
    assert started == [4]          # ...and the scheduler is up on the configured cadence


def test_run_now_runs_exactly_one_pass_before_the_scheduler_takes_over(monkeypatch, tmp_path):
    # The opt-in restoration of the old behavior. Exactly one, and BEFORE the scheduler
    # blocks — a second pass here would double the startup cost of the paid fit scorer,
    # and running it after `_run_scheduler` would never happen at all, since that call
    # blocks for the life of the daemon.
    started, passes, order = _daemon_harness(monkeypatch)
    run.main(["--run-now", "--env", str(tmp_path / "none.env")])
    assert len(passes) == 1
    assert started == [4]


def test_run_now_and_once_together_are_a_parser_error(monkeypatch, tmp_path):
    # They are two different programs: --once runs a pass and EXITS, --run-now runs a pass
    # and then stays on the schedule forever. Silently picking one would either strand an
    # operator's foreground shell or exit a daemon they meant to leave running.
    _daemon_harness(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        run.main(["--run-now", "--once", "--env", str(tmp_path / "none.env")])
    assert exc.value.code == 2


def test_run_now_runs_its_pass_BEFORE_the_scheduler_starts(monkeypatch, tmp_path):
    # Sequence, not count — and the count-only assertion above cannot see this. In
    # production `_run_scheduler` BLOCKS for the daemon's lifetime, so if the two calls
    # were the other way round `--run-now` would never run a pass at all, and every test
    # that stubs the scheduler with a returning lambda would still pass.
    started, passes, order = _daemon_harness(monkeypatch)
    run.main(["--run-now", "--env", str(tmp_path / "none.env")])
    assert order == ["pass", "scheduler"]


def test_a_contended_run_now_logs_and_still_starts_the_scheduler(monkeypatch, tmp_path,
                                                                 caplog):
    # `--run-now` is documented as "run one pass immediately, THEN keep the wall-clock
    # schedule". A hand pass holding the lock must therefore cost the startup pass, not
    # the daemon: exiting here would mean a worker that refuses to come up for as long as
    # an operator's `--once` is running — and wall-clock slots make that collision MORE
    # likely, since hand runs cluster on the hour. Only a foreground `--once` exits.
    started, passes, order = _daemon_harness(monkeypatch)
    db = str(tmp_path / "applications.db")
    with run.pass_lock(db_path=db):
        run.main(["--run-now", "--db", db, "--env", str(tmp_path / "none.env")])
    assert passes == []                 # the startup pass was refused...
    assert started == [4]               # ...and the daemon came up anyway
    assert "skipping this pass" in caplog.text


# --- the scheduler wiring itself -------------------------------------------
# `_run_scheduler` is `# pragma: no cover` because CI installs requirements-dev.txt only,
# which excludes apscheduler. That is an install choice, not a hard constraint: apscheduler
# IS a declared runtime dependency, so where it is importable these run and close the gap
# that pragma leaves. Without them, replacing the CronTrigger with the old interval trigger
# — reverting the entire feature — keeps the suite green.

def test_the_daemon_registers_a_cron_trigger_on_the_configured_wall_clock_slots(monkeypatch):
    # The wiring assertion. `cron_hours` being right proves nothing if nothing calls it,
    # and an `interval` trigger would still schedule *something* on the right cadence
    # while silently reintroducing launch-relative drift.
    pytest.importorskip("apscheduler")
    captured = {}

    class FakeScheduler:
        def add_job(self, job, trigger, **kw):
            captured["trigger"] = trigger
            captured["kw"] = kw

        def start(self):
            captured["started"] = True

    import apscheduler.schedulers.blocking as blocking
    monkeypatch.setattr(blocking, "BlockingScheduler", FakeScheduler)

    run._run_scheduler(lambda: None, 4)

    trigger = captured["trigger"]
    assert type(trigger).__name__ == "CronTrigger"
    assert str(trigger) == "cron[hour='0,4,8,12,16,20', minute='0']"
    assert captured["started"] is True


def test_the_daemon_sets_the_misfire_grace_that_apscheduler_defaults_to_one_second(monkeypatch):
    # The only non-default of the three. APScheduler drops a missed slot after ONE SECOND
    # otherwise, and the deleted eager pass used to hide that by always running at startup.
    pytest.importorskip("apscheduler")
    captured = {}

    class FakeScheduler:
        def add_job(self, job, trigger, **kw): captured.update(kw)
        def start(self): pass

    import apscheduler.schedulers.blocking as blocking
    monkeypatch.setattr(blocking, "BlockingScheduler", FakeScheduler)

    run._run_scheduler(lambda: None, 1)
    assert captured["misfire_grace_time"] == 1800      # half of a 1h cadence
    run._run_scheduler(lambda: None, 4)
    assert captured["misfire_grace_time"] == 3600      # the cap bites from h=2 up
    run._run_scheduler(lambda: None, 24)
    assert captured["misfire_grace_time"] == 3600      # not 12 hours


def test_the_daemon_installs_a_timestamped_logging_handler(monkeypatch):
    # Without this the scheduler's misfire warnings and job tracebacks fall to
    # logging.lastResort: message and level only, no timestamp and no logger name, which
    # is exactly what makes a journald log unreadable next to the pipeline's own output.
    pytest.importorskip("apscheduler")
    import logging as _logging

    class FakeScheduler:
        def add_job(self, job, trigger, **kw): pass
        def start(self): pass

    import apscheduler.schedulers.blocking as blocking
    monkeypatch.setattr(blocking, "BlockingScheduler", FakeScheduler)

    root = _logging.getLogger()
    saved = root.handlers[:]
    try:
        root.handlers = []
        run._run_scheduler(lambda: None, 4)
        assert root.handlers, "the daemon installed no handler"
        assert "%(asctime)s" in root.handlers[0].formatter._fmt
    finally:
        root.handlers = saved


@pytest.mark.parametrize('modes', [
    {'fetch_only': True, 'refresh_unscored': True},
    {'screen_limit': 0},
    {'refresh_unscored': True, 'rescreen_screened': True,
     'refresh_source': 'smartrecruiters'},
])
def test_run_once_invalid_modes_fail_before_opening_database(tmp_path, monkeypatch, modes):
    def unexpected_connect(*args, **kwargs):
        pytest.fail('invalid modes must fail before opening or seeding the database')

    monkeypatch.setattr(run.db, 'connect', unexpected_connect)
    cfg = cfgmod.Config(companies=[cfgmod.Company('greenhouse', 'acme', 'Acme')])
    with pytest.raises(ValueError):
        run.run_once(cfg, db_path=str(tmp_path / 'must-not-exist.db'),
                     env={}, **modes)
    assert not (tmp_path / 'must-not-exist.db').exists()


@pytest.mark.parametrize("environment_limit", ["1", "40", "0", "invalid"])
def test_screen_unlimited_cli_overrides_environment_limit(tmp_path, monkeypatch, environment_limit):
    monkeypatch.setenv("SCREEN_LIMIT", environment_limit)
    env_file = tmp_path / ".env"
    env_file.write_text("")
    captured = {}
    def load_screen_config(_path, **kwargs):
        captured["config_options"] = kwargs
        return object()
    monkeypatch.setattr(run.config_mod, "load_config", load_screen_config)
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: captured.update(kw))
    run.main(["--once", "--screen-unlimited", "--env", str(env_file),
              "--db", str(tmp_path / "db.sqlite")])
    assert captured["screen_limit"] is None
    assert captured["config_options"] == {}


# --- candidate profile (#224): the DB row wins, config.yaml seeds it once -----------

_CANDIDATE_YAML = ("companies: []\ntitle_exclude: [sales]\nmax_age_days: 30\n"
                   "candidate:\n  work_authorization: needs visa sponsorship\n"
                   "  locations: [remote]\n  exclude_internships: true\n")


def _capture_fetch(monkeypatch) -> dict:
    _stub_stages(monkeypatch)
    seen: dict = {}

    def run_fetch(conn, companies, title_filter, *, candidate=None, **k):
        seen.update(k, title_filter=title_filter, candidate=candidate)
        return 0
    monkeypatch.setattr(run.pipeline, "run_fetch", run_fetch)
    return seen


def _set(dbfile, sql):
    conn = dbmod.connect(str(dbfile))
    conn.execute(sql)
    conn.commit()
    conn.close()


def test_run_once_seeds_the_profile_once_then_reads_the_db(monkeypatch, tmp_path, capsys):
    seen = _capture_fetch(monkeypatch)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config(_CANDIDATE_YAML), db_path=str(dbfile), env=_ENV)
    assert seen["candidate"]["work_authorization"] == "needs visa sponsorship"
    assert (seen["title_exclude"], seen["max_age_days"]) == (["sales"], 30)
    stored = dbmod.get_candidate_profile(dbmod.connect(str(dbfile)))
    assert (stored["actor"], stored["version"], stored["locations"]) == ("config", 1, '["remote"]')
    assert stored["confirmed_at"] is None
    assert "seeded the candidate profile" in capsys.readouterr().out

    # The operator changes the stored row (as the web API does); later config edits are
    # reported and ignored, scope and requirements alike.
    _set(dbfile, "UPDATE candidate_profile SET work_authorization='citizen', "
                 "locations='[\"Boston\"]', title_exclude='[\"staff\"]', max_age_days=0, "
                 "version=2, actor='mcp'")
    edited = _CANDIDATE_YAML.replace("[remote]", "[Austin]").replace("[sales]", "[intern]")
    run.run_once(cfgmod.load_config(edited), db_path=str(dbfile), env=_ENV)
    assert seen["candidate"]["work_authorization"] == "citizen"
    assert seen["candidate"]["locations"] == ["Boston"]
    assert (seen["title_exclude"], seen["max_age_days"]) == (["staff"], 0)
    out = capsys.readouterr().out
    assert "title_exclude, max_age_days, candidate ignored" in out and "seeded" not in out


def test_fresh_install_without_config_is_configured_by_the_row_alone(monkeypatch, tmp_path):
    seen = _capture_fetch(monkeypatch)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile), env=_ENV)
    assert seen["candidate"] is None and seen["title_filter"] == []
    assert dbmod.get_candidate_profile(dbmod.connect(str(dbfile))) is None

    # Configured only through the form / set_candidate_profile: the row drives the scope
    # and the screen, with the degree derived from the education rows.
    _set(dbfile, "INSERT INTO candidate_profile (id, title_include, education, actor, "
                 "updated_at) VALUES (1, '[\"engineer\"]', '[{\"degree\":\"bachelor''s\",\"field\":\"CS\"},"
                 "{\"degree\":\"phd\",\"field\":\"Math\"}]', 'web', '2026-11-20T00:00:00Z')")
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile), env=_ENV)
    assert seen["title_filter"] == ["engineer"]
    assert seen["candidate"]["highest_degree"] == "phd"


def test_run_once_rejects_an_off_vocabulary_stored_value(monkeypatch, tmp_path):
    _capture_fetch(monkeypatch)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    _set(dbfile, "INSERT INTO candidate_profile (id, work_authorization, actor, updated_at) "
                 "VALUES (1, 'F-1 OPT', 'mcp', '2026-11-18T00:00:00Z')")
    with pytest.raises(cfgmod.ConfigError, match="work_authorization"):
        run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile), env=_ENV)


def test_daemon_startup_seeds_the_profile_before_the_first_slot(monkeypatch, tmp_path):
    # Until a row exists MCP reports the profile missing, and a set_candidate_profile in
    # that window would pre-empt the config seed; so the daemon seeds at launch.
    real_load_config = cfgmod.load_config
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    monkeypatch.setattr(run, "_run_scheduler", lambda job, hours: None)
    monkeypatch.setattr(run.config_mod, "load_config", lambda path: real_load_config(_CANDIDATE_YAML))
    run.main(["--db", str(dbfile), "--env", str(tmp_path / "none.env")])
    assert dbmod.get_candidate_profile(dbmod.connect(str(dbfile)))["actor"] == "config"
