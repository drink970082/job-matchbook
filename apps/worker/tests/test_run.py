"""TDD for the entrypoint: --once runs the three stages in order, env plumbing."""
from __future__ import annotations

import errno
import os

import pytest

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
from ats_worker import prompts
from ats_worker import run
from tests._helpers import bootstrap_db, make_posting


def _assessment(**over):
    """A minimally-valid fit assessment scorecard (passes score._normalize_score's
    enum checks) so a fake fit closure's card doesn't itself raise ScoreError."""
    base = {
        "seniority": {"verdict": "match", "note": ""},
        "domain": {"verdict": "match", "note": ""},
        "must_haves": {"met": [], "missing": []},
        "nice_to_haves": {"missing": []},
        "summary": "",
    }
    base.update(over)
    return base


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


def test_run_once_calls_five_stages_in_order(monkeypatch):
    order = []

    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda *a, **k: order.append("fetch") or 0)
    monkeypatch.setattr(run.pipeline, "run_expire",
                        lambda *a, **k: order.append("expire") or 0)
    monkeypatch.setattr(run.pipeline, "run_retry",
                        lambda *a, **k: order.append("retry") or 0)
    monkeypatch.setattr(run.pipeline, "run_score",
                        lambda *a, **k: order.append("score"))
    monkeypatch.setattr(run.pipeline, "run_notify",
                        lambda *a, **k: order.append("notify"))

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    # The watchlist now comes from the DB; stub the reads so this stage-order test
    # doesn't need a real connection (feeds are off, so run_feed isn't called).
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
    )

    run.run_once(
        cfg,
        db_path=":memory:",
        resumes={"resume": "resume"},
        env={
            "ANTHROPIC_API_KEY": "k",
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_CHAT_ID": "c",
            "OLLAMA_HOST": "h",
        },
    )
    assert order == ["fetch", "expire", "retry", "score", "notify"]


def test_run_once_fetch_only_stops_before_score(monkeypatch):
    # --fetch-only must run through retry then return BEFORE any screen/scorer call
    # (a quota-free board refresh) — so score/notify never run.
    order = []
    for stage, ret in (("run_fetch", 0), ("run_expire", 0), ("run_retry", 0),
                       ("run_score", None), ("run_notify", None)):
        monkeypatch.setattr(run.pipeline, stage,
                            lambda *a, _s=stage, **k: order.append(_s))

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])
    monkeypatch.setattr(run.db, "get_by_status", lambda conn, status: [])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    run.run_once(cfg, db_path=":memory:", resumes={"resume": "r"}, env=_ENV,
                 fetch_only=True)
    assert order == ["run_fetch", "run_expire", "run_retry"]  # no score, no notify


def test_run_once_score_only_skips_ingest(monkeypatch):
    # --score-only must skip the network ingest (fetch/feed/expire) and go straight
    # to retry -> score -> notify over the existing backlog.
    order = []
    for stage in ("run_fetch", "run_expire", "run_retry", "run_score", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage,
                            lambda *a, _s=stage, **k: order.append(_s) or 0)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    run.run_once(cfg, db_path=":memory:", resumes={"resume": "r"}, env=_ENV,
                 score_only=True)
    assert order == ["run_retry", "run_score", "run_notify"]  # no fetch/expire


def test_run_once_without_telegram_skips_notify(monkeypatch, capsys):
    # Telegram is optional: a user who only reviews the Discovered Jobs tab (matched
    # rows show there at 'scored', not just 'notified') runs the worker with no bot
    # creds. run_once must score then skip notify, not KeyError.
    order = []
    for stage in ("run_fetch", "run_expire", "run_retry", "run_score", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage,
                            lambda *a, _s=stage, **k: order.append(_s) or 0)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    run.run_once(cfg, db_path=":memory:", resumes={"resume": "r"},
                 env={"ANTHROPIC_API_KEY": "k", "OLLAMA_HOST": "h"})  # no telegram
    assert order == ["run_fetch", "run_expire", "run_retry", "run_score"]  # no notify
    assert "notify" in capsys.readouterr().out.lower()


# --- watchlist bootstrap + feed wiring ------------------------------------

_ENV = {"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"}


def _stub_stages(monkeypatch):
    for stage in ("run_fetch", "run_retry", "run_score", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)


def test_run_once_seeds_watchlist_from_config_when_empty(monkeypatch, tmp_path):
    _stub_stages(monkeypatch)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "  - { source: lever, slug: b, name: B }\n"
    )
    run.run_once(cfg, db_path=str(dbfile), resumes={"resume": "r"}, env=_ENV)

    conn = dbmod.connect(str(dbfile))
    assert dbmod.get_watchlist(conn) == [
        {"source": "greenhouse", "slug": "a", "name": "A", "recipe": None},
        {"source": "lever", "slug": "b", "name": "B", "recipe": None},
    ]
    # a second pass does not duplicate (watchlist no longer empty)
    run.run_once(cfg, db_path=str(dbfile), resumes={"resume": "r"}, env=_ENV)
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
                 db_path=str(dbfile), resumes={"resume": "r"}, env=_ENV)
    assert "browser" not in seen["sources"] and "greenhouse" in seen["sources"]

    # enable_browser_sources: they pass through
    run.run_once(cfgmod.load_config("companies: []\nenable_browser_sources: true\n"),
                 db_path=str(dbfile), resumes={"resume": "r"}, env=_ENV)
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
    run.run_once(cfg_on, db_path=str(dbfile), resumes={"resume": "r"}, env=_ENV)
    assert calls == [("simplify", ["Software"])]

    calls.clear()
    cfg_off = cfgmod.load_config("companies: []\nfeeds:\n  simplify:\n    enabled: false\n")
    run.run_once(cfg_off, db_path=str(dbfile), resumes={"resume": "r"}, env=_ENV)
    assert calls == []


def test_run_once_screen_backend_none_makes_no_provider_call(monkeypatch, tmp_path):
    # A GPU-less user: the pass must complete with zero screen calls.
    _stub_stages(monkeypatch)
    seen = {}
    monkeypatch.setattr(run, "make_screener",
                        lambda backend, **kw: seen.setdefault("backend", backend))
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile),
                 resumes={"resume": "r"}, env=_ENV, screen_backend="none")
    assert seen["backend"] == "none"


def test_run_once_uses_screen_model_override(monkeypatch, tmp_path):
    # --screen-model/SCREEN_MODEL must reach the hosted adapter's build call.
    # make_screener itself already threads screen_model per-call (Task 5); the gap
    # this closes is run_once accepting and forwarding it at all.
    _stub_stages(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        run, "make_claude_api_extract",
        lambda key, model, **kw: seen.update(model=model) or (lambda p, s: {}))
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    run.run_once(cfgmod.load_config("companies: []\n"), db_path=str(dbfile),
                 resumes={"resume": "r"}, env=_ENV, screen_backend="claude-api",
                 screen_model="claude-sonnet-5")
    assert seen["model"] == "claude-sonnet-5"


# --- run_once builds the candidate + plumbs Ollama env (the real wiring) ---

def _run_once_capturing_screen(monkeypatch, tmp_path, cfg, env):
    """Drive the REAL run_score over one 'new' row, capturing the kwargs the wired
    screen_fn passes to screen_posting, plus the kwargs the REAL make_screener (not
    mocked here) passes on to make_ollama_extract — that is where OLLAMA_HOST now
    lands, since it is no longer a screen_posting kwarg (Task 2). fetch/notify are
    stubbed, and the fit scorer's BUILD is stubbed to a trivial hermetic callable —
    the fake screen always survives (not disqualified), so run_score's fit phase does
    run, and it must not shell out to a real codex/Claude backend."""
    captured = {}

    def fake_screen_posting(posting, **kwargs):
        captured["kwargs"] = kwargs
        captured["posting"] = posting
        return {"disqualified": False}

    def fake_make_ollama_extract(**kwargs):
        captured["extract_kwargs"] = kwargs
        return lambda prompt, schema: {}

    monkeypatch.setattr(run, "screen_posting", fake_screen_posting)
    monkeypatch.setattr(run, "make_ollama_extract", fake_make_ollama_extract)
    monkeypatch.setattr(
        run, "make_scorer",
        lambda backend, **kw: (lambda postings, resumes: [
            {"score": 70, "assessment": _assessment()} for _ in postings]),
    )
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_notify", lambda *a, **k: None)

    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    conn = dbmod.connect(str(dbfile))
    dbmod.upsert_postings(conn, [make_posting("1")], now="2026-01-01T00:00:00.000Z")
    conn.close()

    run.run_once(cfg, db_path=str(dbfile), resumes={"resume": "r"}, env=env)
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
    assert cand["highest_degree"] == "Master's"
    assert cand["locations"] == ["remote", "USA"]
    assert cand["exclude_internships"] is False        # defaults off; plumbed through
    assert kw["num_ctx"] == 4096                       # OLLAMA_NUM_CTX honored
    assert captured["extract_kwargs"]["ollama_host"] == "http://ol:11434"
    # (fit-scorer wiring — which backend/model builds fit_fn — is verified by the
    # score-model/backend tests below via make_scorer/make_claude_scorer/
    # make_codex_scorer; screen_posting has no score_fit kwarg to inspect here.)


def _run_once_capturing_fit_model(monkeypatch, tmp_path, cfg, env, *, score_model,
                                  score_backend="claude"):
    """Like _run_once_capturing_screen, but leaves make_claude_scorer/
    make_codex_scorer for the caller to monkeypatch (to capture the model kwarg
    fit_fn's lazy build calls it with). screen_fn is stubbed to a hermetic
    always-survives fake so control reaches fit_fn regardless of candidate
    config (backend defaults to claude here: the default run backend is codex
    now)."""
    monkeypatch.setattr(run, "screen_posting", lambda posting, **kw: {"disqualified": False})
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_notify", lambda *a, **k: None)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    conn = dbmod.connect(str(dbfile))
    dbmod.upsert_postings(conn, [make_posting("1")], now="2026-01-01T00:00:00.000Z")
    conn.close()
    # score_backend=None -> omit it, so run_once's own default applies.
    extra = {} if score_backend is None else {"score_backend": score_backend}
    run.run_once(cfg, db_path=str(dbfile), resumes={"resume": "r"}, env=env,
                 anthropic_score_model=score_model, **extra)


def test_run_once_uses_score_model_override(monkeypatch, tmp_path):
    seen = {}

    def fake_make_claude_scorer(key, model, **kw):
        seen["model"] = model
        return lambda postings, resumes: [{"score": 70} for _ in postings]

    monkeypatch.setattr(run, "make_claude_scorer", fake_make_claude_scorer)
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    env = {"OLLAMA_HOST": "h", "ANTHROPIC_API_KEY": "k",
           "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    _run_once_capturing_fit_model(monkeypatch, tmp_path, cfg, env,
                                  score_model="claude-opus-4-8")
    assert seen["model"] == "claude-opus-4-8"


def test_make_scorer_picks_the_backend(monkeypatch):
    # One seam, two twins: codex (ChatGPT subscription) is the default; claude stays
    # reachable for a metered A/B. Codex must never need ANTHROPIC_API_KEY.
    monkeypatch.setattr(run, "make_codex_scorer",
                        lambda model, **kw: ("codex", model, kw.get("profile")))
    monkeypatch.setattr(run, "make_claude_scorer",
                        lambda key, model, **kw: ("claude", key, model))
    assert run.DEFAULT_SCORE_BACKEND == "codex"
    assert run.make_scorer("codex", env={}, profile="p") == (
        "codex", run.DEFAULT_CODEX_SCORE_MODEL, "p")
    assert run.make_scorer("claude", env={"ANTHROPIC_API_KEY": "k"}) == (
        "claude", "k", run.DEFAULT_ANTHROPIC_SCORE_MODEL)


def _run_once_capturing_run_score(monkeypatch, **kw):
    """Run one pass with every stage stubbed, returning run_score's kwargs."""
    seen: dict = {}
    for stage in ("run_fetch", "run_expire", "run_retry", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_score",
                        lambda conn, **k: seen.update(k))

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    run.run_once(cfg, db_path=":memory:", resumes={"resume": "r"}, env=_ENV, **kw)
    return seen


def test_run_once_stamps_the_active_fit_backend_and_model(monkeypatch):
    # The scorer's identity is known only at the wiring layer (run.py), so run_once
    # hands it to run_score for persistence — a row scored on codex/gpt-5.6-sol must
    # be distinguishable afterwards from one scored on claude/claude-sonnet-5.
    codex = _run_once_capturing_run_score(monkeypatch)["scorer_meta"]
    assert codex == {"backend": "codex", "model": run.DEFAULT_CODEX_SCORE_MODEL,
                     "scorer_version": prompts.SCORER_VERSION}

    claude = _run_once_capturing_run_score(
        monkeypatch, score_backend="claude",
        anthropic_score_model="claude-sonnet-5")["scorer_meta"]
    assert claude["backend"] == "claude"
    assert claude["model"] == "claude-sonnet-5"


def test_scorer_meta_model_tracks_the_backend_make_scorer_picks():
    # The two must not drift: whatever model make_scorer hands the backend is the
    # model the provenance stamp claims.
    assert run._scorer_meta("codex", codex_score_model="m")["model"] == "m"
    assert run._scorer_meta("claude", anthropic_score_model="m")["model"] == "m"


def test_run_once_no_notify_scores_without_alerting(monkeypatch, capsys):
    # An unattended bulk-scoring pass would otherwise fire a Telegram alert per match.
    # --no-notify scores silently; the matches still surface in the web Discovered tab,
    # and the rows stay 'scored' so a later pass CAN notify them (nothing is consumed).
    order = []
    for stage in ("run_fetch", "run_expire", "run_retry", "run_score", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage,
                            lambda *a, _s=stage, **k: order.append(_s) or 0)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")

    run.run_once(cfg, db_path=":memory:", resumes={"resume": "r"}, env=_ENV,
                 no_notify=True)
    assert "run_score" in order and "run_notify" not in order
    assert "notify" in capsys.readouterr().out.lower()   # says so, never silently


def test_run_once_rescreen_discarded_requeues_before_scoring(monkeypatch):
    # The flag is the only way back from 'discarded' (terminal). Off by default:
    # a normal pass must never resurrect discards behind the operator's back.
    calls: list = []
    # (requeued, skipped) -- skipped names the un-hydrated stub discards left behind
    monkeypatch.setattr(run.db, "requeue_discarded",
                        lambda conn, now: (calls.append(now), (3, 2))[1])

    _run_once_capturing_run_score(monkeypatch)
    assert calls == []

    _run_once_capturing_run_score(monkeypatch, rescreen_discarded=True)
    assert len(calls) == 1


def test_unknown_score_backend_fails_before_any_work(monkeypatch, capsys):
    # argparse enforces `choices` on a parsed value, never on an env-supplied default,
    # so SCORE_BACKEND=openai in a .env used to reach _scorer_meta deep inside the pass
    # -- AFTER the fetch and AFTER --rescreen-discarded had spent its one shot. main()
    # must reject it at parse time, before anything irreversible.
    # Via the ENV default specifically -- argparse's `choices` already rejects the
    # flag, which is exactly why the env path was the one that slipped through.
    monkeypatch.setenv("SCORE_BACKEND", "openai")
    with pytest.raises(SystemExit):
        run.main(["--once"])
    assert "unknown score backend" in capsys.readouterr().err


def test_rescreen_discarded_requires_once(monkeypatch, tmp_path, capsys):
    # In daemon mode the flag would fire EVERY pass — resurrecting the same discards
    # every 6h and re-charging the paid fit scorer for each survivor, forever. It is
    # a one-shot operator action, so refuse the combination instead of leaking money.
    cfg = tmp_path / "config.yaml"
    cfg.write_text("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    with pytest.raises(SystemExit):
        run.main(["--rescreen-discarded", "--config", str(cfg),
                  "--env", str(tmp_path / "none.env")])
    assert "--once" in capsys.readouterr().err


def test_make_scorer_rejects_an_unknown_backend():
    # A typo'd --score-backend must fail loudly, not silently fall back to a paid API.
    with pytest.raises(ValueError, match="unknown score backend"):
        run.make_scorer("gpt", env={})


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
    monkeypatch.setattr(run, "make_codex_extract", lambda model: ("codex", model))
    assert run.make_screener("codex", env={}, http=None) == (
        "codex", run.DEFAULT_CODEX_SCREEN_MODEL)
    assert run.make_screener("codex", env={}, http=None,
                             screen_model="gpt-5.6-luna") == ("codex", "gpt-5.6-luna")


def test_make_screener_claude_code_wires_model(monkeypatch):
    # Same dispatch pattern. screen_model=None (the default) must pass through as
    # None rather than a hard-coded default — make_claude_code_extract's own
    # `model=None` picks the CLI's default model in that case.
    monkeypatch.setattr(run, "make_claude_code_extract", lambda model: ("claude-code", model))
    assert run.make_screener("claude-code", env={}, http=None) == ("claude-code", None)
    assert run.make_screener("claude-code", env={}, http=None,
                             screen_model="claude-opus-4-8") == (
        "claude-code", "claude-opus-4-8")


def test_make_screener_claude_api_wires_key_and_model(monkeypatch):
    # Same dispatch pattern as test_make_scorer_picks_the_backend: the seam only
    # needs to pass the right key/model through, so the real adapter is faked out.
    monkeypatch.setattr(run, "make_claude_api_extract",
                        lambda key, model: ("claude-api", key, model))
    assert run.make_screener("claude-api", env={"ANTHROPIC_API_KEY": "k"}) == (
        "claude-api", "k", run.DEFAULT_CLAUDE_SCREEN_MODEL)
    assert run.make_screener("claude-api", env={"ANTHROPIC_API_KEY": "k"},
                             screen_model="claude-opus-4-8") == (
        "claude-api", "k", "claude-opus-4-8")


def test_make_screener_openai_api_wires_key_and_model(monkeypatch):
    # Same dispatch pattern as test_make_screener_claude_api_wires_key_and_model.
    monkeypatch.setattr(run, "make_openai_api_extract",
                        lambda key, model, *, http=None: ("openai-api", key, model, http))
    assert run.make_screener("openai-api", env={"OPENAI_API_KEY": "k"}, http="H") == (
        "openai-api", "k", run.DEFAULT_OPENAI_SCREEN_MODEL, "H")
    assert run.make_screener("openai-api", env={"OPENAI_API_KEY": "k"},
                             screen_model="gpt-6") == (
        "openai-api", "k", "gpt-6", None)


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


def test_run_once_defaults_to_the_codex_scorer(monkeypatch, tmp_path):
    # The default pass builds the codex scorer and never reads ANTHROPIC_API_KEY —
    # env here deliberately omits it, so a regression to Claude raises KeyError.
    seen = {}

    def fake_make_codex_scorer(model, **kw):
        seen["model"] = model
        return lambda postings, resumes: [{"score": 70} for _ in postings]

    monkeypatch.setattr(run, "make_codex_scorer", fake_make_codex_scorer)
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    env = {"OLLAMA_HOST": "h", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    _run_once_capturing_fit_model(monkeypatch, tmp_path, cfg, env,
                                  score_model="unused", score_backend=None)
    assert seen["model"] == run.DEFAULT_CODEX_SCORE_MODEL


def test_run_once_threads_fetch_filters(monkeypatch):
    captured = {}
    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda *a, **k: captured.update(k) or 0)
    for stage in ("run_expire", "run_retry", "run_score", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(run.db, "connect", lambda path: FakeConn())
    monkeypatch.setattr(run.db, "count_watchlist", lambda conn: 1)
    monkeypatch.setattr(run.db, "get_watchlist",
                        lambda conn: [{"source": "greenhouse", "slug": "a", "name": "A"}])

    from ats_worker import config as cfgmod
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "max_age_days: 30\n"
        "title_exclude: [intern]\n"
        "candidate: { locations: [USA] }\n"
    )
    run.run_once(cfg, db_path=":memory:", resumes={"resume": "resume"}, env=_ENV)
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


# --- multi-resume loading ---------------------------------------------------

def test_load_resumes_labels_profile_and_order(tmp_path):
    (tmp_path / "resume_swe.txt").write_text("SWE", encoding="utf-8")
    (tmp_path / "resume_quant_dev.txt").write_text("QD", encoding="utf-8")
    (tmp_path / "personal_profile.txt").write_text("my goals", encoding="utf-8")
    resumes, profile = run.load_resumes(str(tmp_path))
    # labels strip the resume_ prefix; sorted by filename -> deterministic,
    # cache-stable prompt order (quant_dev before swe)
    assert resumes == {"quant_dev": "QD", "swe": "SWE"}
    assert list(resumes) == ["quant_dev", "swe"]
    assert profile == "my goals"


def test_load_resumes_bare_resume_txt_is_single_version(tmp_path):
    (tmp_path / "resume.txt").write_text("me", encoding="utf-8")
    resumes, profile = run.load_resumes(str(tmp_path))
    assert resumes == {"resume": "me"}
    assert profile == ""


def test_load_resumes_no_files_exits_with_hint(tmp_path):
    with pytest.raises(SystemExit) as e:
        run.load_resumes(str(tmp_path))
    assert "resume" in str(e.value).lower()


def test_load_resumes_duplicate_label_exits_naming_both(tmp_path):
    (tmp_path / "resume_swe.txt").write_text("a", encoding="utf-8")
    (tmp_path / "swe.txt").write_text("b", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        run.load_resumes(str(tmp_path))
    assert "resume_swe.txt" in str(e.value) and "swe.txt" in str(e.value)


def test_load_resumes_non_utf8_file_exits_not_traceback(tmp_path):
    (tmp_path / "resume.txt").write_bytes(b"\xff\xfe caf\xe9")  # not valid UTF-8
    with pytest.raises(SystemExit) as e:
        run.load_resumes(str(tmp_path))
    assert "resume.txt" in str(e.value)


def test_load_resumes_skips_dotfiles(tmp_path):
    (tmp_path / "resume.txt").write_text("me", encoding="utf-8")
    (tmp_path / "._resume.txt").write_bytes(b"\x00\x05\x16\x07 AppleDouble junk")
    resumes, _ = run.load_resumes(str(tmp_path))
    assert resumes == {"resume": "me"}


# --- main() honors .env for argparse defaults -------------------------------

def test_main_merges_env_file_into_argparse_defaults(monkeypatch, tmp_path):
    # SCORE_BACKEND / OLLAMA_MODEL / DB_PATH / CODEX_SCORE_MODEL set in .env must reach
    # run_once — regression guard for the bug where load_env's dict was never merged
    # into os.environ (so the os.environ-derived argparse defaults ignored .env).
    import os as _os
    monkeypatch.setattr(_os, "environ", dict(_os.environ))
    for k in ("SCORE_BACKEND", "OLLAMA_MODEL", "DB_PATH", "CODEX_SCORE_MODEL"):
        _os.environ.pop(k, None)

    envfile = tmp_path / ".env"
    envfile.write_text(
        "SCORE_BACKEND=claude\n"
        "OLLAMA_MODEL=custom:1b\n"
        "DB_PATH=/tmp/from-env.db\n"
        "CODEX_SCORE_MODEL=gpt-from-env\n"
        "ANTHROPIC_API_KEY=k\nTELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=c\n"
    )

    captured = {}
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: captured.update(kw))
    # run.config_mod IS cfgmod (same module object, `from . import config as config_mod`),
    # so the stub must close over the real load_config captured before patching — routing
    # through `cfgmod.load_config` inside the replacement would call itself and recurse.
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))
    monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))

    run.main(["--once", "--env", str(envfile)])

    assert captured["score_backend"] == "claude"
    assert captured["ollama_model"] == "custom:1b"
    assert captured["db_path"] == "/tmp/from-env.db"
    assert captured["codex_score_model"] == "gpt-from-env"
    assert captured["env"]["TELEGRAM_BOT_TOKEN"] == "t"   # dict still plumbed to run_once


def test_main_env_merge_excludes_secrets(monkeypatch, tmp_path):
    # Regression guard for the secret-scoping regression: main() must only promote
    # the eight argparse-read config keys from .env into os.environ, never secrets —
    # a leaked os.environ secret would be inherited by the codex CLI subprocess
    # (subprocess.run with no env= in score/backends_codex.py).
    import os as _os
    monkeypatch.setattr(_os, "environ", dict(_os.environ))
    for k in ("DB_PATH", "OLLAMA_MODEL", "SCREEN_BACKEND", "SCREEN_MODEL",
              "SCORE_BACKEND", "CODEX_SCORE_MODEL",
              "ANTHROPIC_SCORE_MODEL", "CODEX_BATCH_SIZE",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY",
              "OPENAI_API_KEY"):
        _os.environ.pop(k, None)

    envfile = tmp_path / ".env"
    envfile.write_text(
        "DB_PATH=/tmp/from-env.db\n"
        "OLLAMA_MODEL=custom:1b\n"
        "SCREEN_BACKEND=claude-api\n"
        "SCREEN_MODEL=claude-opus-4-8\n"
        "SCORE_BACKEND=claude\n"
        "CODEX_SCORE_MODEL=gpt-from-env\n"
        "ANTHROPIC_SCORE_MODEL=claude-from-env\n"
        "CODEX_BATCH_SIZE=3\n"
        "TELEGRAM_BOT_TOKEN=secret-tok\n"
        "TELEGRAM_CHAT_ID=c\n"
        "ANTHROPIC_API_KEY=secret-key\n"
        "OPENAI_API_KEY=secret-openai-key\n"
    )

    captured = {}
    monkeypatch.setattr(run, "run_once", lambda cfg, **kw: captured.update(kw))
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))
    monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))

    run.main(["--once", "--env", str(envfile)])

    # The eight argparse-read config keys must be promoted into os.environ.
    assert _os.environ["DB_PATH"] == "/tmp/from-env.db"
    assert _os.environ["OLLAMA_MODEL"] == "custom:1b"
    assert _os.environ["SCREEN_BACKEND"] == "claude-api"
    assert _os.environ["SCREEN_MODEL"] == "claude-opus-4-8"
    assert _os.environ["SCORE_BACKEND"] == "claude"
    assert _os.environ["CODEX_SCORE_MODEL"] == "gpt-from-env"
    assert _os.environ["ANTHROPIC_SCORE_MODEL"] == "claude-from-env"
    assert _os.environ["CODEX_BATCH_SIZE"] == "3"

    # Secrets must never be promoted into os.environ (would leak to codex subprocess).
    assert "TELEGRAM_BOT_TOKEN" not in _os.environ
    assert "TELEGRAM_CHAT_ID" not in _os.environ
    assert "ANTHROPIC_API_KEY" not in _os.environ
    assert "OPENAI_API_KEY" not in _os.environ

    # ... but secrets must still reach run_once via the in-process env dict.
    assert captured["env"]["TELEGRAM_BOT_TOKEN"] == "secret-tok"
    assert captured["env"]["TELEGRAM_CHAT_ID"] == "c"
    assert captured["env"]["ANTHROPIC_API_KEY"] == "secret-key"
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
    assert "TMPDIR" in str(exc.value)


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


def test_the_default_lock_path_is_not_under_the_shared_db_dir():
    # db/ is bind-mounted into the web container; the lock is a property of this host's
    # processes, not of the data. The autouse fixture redirects _LOCK_PATH for the rest
    # of the suite, so without this nothing would notice it moving.
    from tests.conftest import SHIPPED_LOCK_PATH
    assert SHIPPED_LOCK_PATH == run.Path(run.tempfile.gettempdir()) / "ats-worker-pass.lock"
    assert "db" not in SHIPPED_LOCK_PATH.parts


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
    monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))

    with run.pass_lock():                          # conftest points _LOCK_PATH at tmp
        with pytest.raises(SystemExit) as exc:
            run.main(["--once", "--env", str(tmp_path / "none.env")])
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
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config("companies: []\n"))
    monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))

    with run.pass_lock():
        run.main(["--env", str(tmp_path / "none.env")])

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
    monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))

    run.main(["--once", "--env", str(tmp_path / "none.env")])
    assert len(calls) == 1
    with run.pass_lock():                          # free again
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
    real_load_config = cfgmod.load_config
    monkeypatch.setattr(run.config_mod, "load_config",
                        lambda path: real_load_config(
                            f"companies: []\nschedule_hours: {schedule_hours}\n"))
    monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))
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


def test_run_now_does_not_open_the_rescreen_discarded_backdoor(monkeypatch, tmp_path):
    # `--rescreen-discarded` is one-shot because `once()` closes over the flag: allowing it
    # alongside --run-now would leave it set on every LATER scheduled firing too, and
    # resurrect the entire discard pile — thousands of rows — into the paid scorer daily.
    # It stays bound to --once, which exits before a second firing can exist.
    _daemon_harness(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        run.main(["--run-now", "--rescreen-discarded",
                  "--env", str(tmp_path / "none.env")])
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
    with run.pass_lock():
        run.main(["--run-now", "--env", str(tmp_path / "none.env")])
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
