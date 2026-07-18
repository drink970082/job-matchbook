"""TDD for the entrypoint: --once runs the three stages in order, env plumbing."""
from __future__ import annotations

import pytest

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
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


def test_run_once_calls_three_stages_in_order(monkeypatch):
    order = []

    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda *a, **k: order.append("fetch") or 0)
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
    assert order == ["fetch", "score", "notify"]


# --- watchlist bootstrap + feed wiring ------------------------------------

_ENV = {"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"}


def _stub_stages(monkeypatch):
    for stage in ("run_fetch", "run_score", "run_notify"):
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


# --- run_once builds the candidate + plumbs Ollama env (the real wiring) ---

def _run_once_capturing_screen(monkeypatch, tmp_path, cfg, env):
    """Drive the REAL run_score over one 'new' row, capturing the kwargs the wired
    screen_fn passes to screen_posting. fetch/notify are stubbed, and the fit
    scorer's BUILD is stubbed to a trivial hermetic callable — the fake screen
    always survives (not disqualified), so run_score's fit phase does run, and
    it must not shell out to a real codex/Claude backend."""
    captured = {}

    def fake_screen_posting(posting, **kwargs):
        captured["kwargs"] = kwargs
        captured["posting"] = posting
        return {"disqualified": False}

    monkeypatch.setattr(run, "screen_posting", fake_screen_posting)
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
    kw = _run_once_capturing_screen(monkeypatch, tmp_path, cfg, env)["kwargs"]
    cand = kw["candidate"]
    assert cand["highest_degree"] == "Master's"
    assert cand["locations"] == ["remote", "USA"]
    assert cand["exclude_internships"] is False        # defaults off; plumbed through
    assert kw["num_ctx"] == 4096                       # OLLAMA_NUM_CTX honored
    assert kw["ollama_host"] == "http://ol:11434"
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


def test_make_scorer_rejects_an_unknown_backend():
    # A typo'd --score-backend must fail loudly, not silently fall back to a paid API.
    with pytest.raises(ValueError, match="unknown score backend"):
        run.make_scorer("gpt", env={})


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
