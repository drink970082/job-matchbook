"""TDD for the entrypoint: --once runs the four stages in order, env plumbing."""
from __future__ import annotations

import json

from ats_worker import config as cfgmod
from ats_worker import db as dbmod
from ats_worker import run
from tests._helpers import bootstrap_db, make_posting, seed_scored


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


def test_resume_out_dir_is_unique_per_posting_under_base():
    posting = {"source": "greenhouse", "external_id": "4012345"}
    out = run.resume_out_dir("/resumes", posting)
    # Lives under the shared base dir (so the Next route can serve it) and is
    # unique per (source, external_id) so concurrent tailors never collide.
    assert out == "/resumes/greenhouse_4012345"
    other = run.resume_out_dir("/resumes", {"source": "lever", "external_id": "4012345"})
    assert other != out


def test_run_once_tailor_writes_pdf_under_resume_dir(monkeypatch, tmp_path):
    """The wired tailor_fn must compile into the shared resume dir, so the
    stored resume_path is something the web app's /api/resume route can read."""
    captured = {}

    def fake_tailor_resume(master, jd, missing, *, claude, compile_pdf, count_pages,
                           max_rounds, out_dir):
        captured["out_dir"] = out_dir
        return {"tex": "x", "pdf_path": f"{out_dir}/resume.pdf", "pages": 1, "ok": True}

    monkeypatch.setattr(run, "tailor_resume", fake_tailor_resume)
    monkeypatch.setattr(run, "make_claude", lambda *a, **k: (lambda p: "tex"))
    # Run only the tailor stage against a real temp db with one high-scored row.
    from ats_worker import db as dbmod

    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_score", lambda *a, **k: None)
    monkeypatch.setattr(run.pipeline, "run_notify", lambda *a, **k: None)

    real_run_tailor = run.pipeline.run_tailor

    dbfile = tmp_path / "applications.db"
    bootstrap_db(dbfile)
    conn = dbmod.connect(str(dbfile))
    seed_scored(conn, {"77": 90}, detail={})  # one greenhouse/77 row, scored >= threshold
    conn.close()

    run.run_once(
        cfgmod_minimal(), db_path=str(dbfile), resume_text="r", master_tex="m",
        env={"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
             "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"},
        resume_dir=str(tmp_path / "resumes"),
    )

    assert captured["out_dir"] == str(tmp_path / "resumes" / "greenhouse_77")
    conn = dbmod.connect(str(dbfile))
    row = conn.execute("SELECT resume_path, pipeline_status FROM job_postings").fetchone()
    assert row["pipeline_status"] == "tailored"
    assert row["resume_path"].startswith(str(tmp_path / "resumes" / "greenhouse_77"))


def cfgmod_minimal():
    from ats_worker import config as cfgmod
    return cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\nthreshold: 75\n"
    )


def test_run_once_calls_four_stages_in_order(monkeypatch):
    order = []

    monkeypatch.setattr(run.pipeline, "run_fetch",
                        lambda *a, **k: order.append("fetch") or 0)
    monkeypatch.setattr(run.pipeline, "run_score",
                        lambda *a, **k: order.append("score"))
    monkeypatch.setattr(run.pipeline, "run_tailor",
                        lambda *a, **k: order.append("tailor"))
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
        resume_text="resume",
        master_tex="master",
        env={
            "ANTHROPIC_API_KEY": "k",
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_CHAT_ID": "c",
            "OLLAMA_HOST": "h",
        },
    )
    assert order == ["fetch", "score", "tailor", "notify"]


# --- watchlist bootstrap + feed wiring ------------------------------------

_ENV = {"ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_CHAT_ID": "c", "OLLAMA_HOST": "h"}


def _stub_stages(monkeypatch):
    for stage in ("run_fetch", "run_score", "run_tailor", "run_notify"):
        monkeypatch.setattr(run.pipeline, stage, lambda *a, **k: 0)


def test_run_once_seeds_watchlist_from_config_when_empty(monkeypatch, tmp_path):
    _stub_stages(monkeypatch)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "  - { source: lever, slug: b, name: B }\n"
    )
    run.run_once(cfg, db_path=str(dbfile), resume_text="r", master_tex="m", env=_ENV)

    conn = dbmod.connect(str(dbfile))
    assert dbmod.get_watchlist(conn) == [
        {"source": "greenhouse", "slug": "a", "name": "A"},
        {"source": "lever", "slug": "b", "name": "B"},
    ]
    # a second pass does not duplicate (watchlist no longer empty)
    run.run_once(cfg, db_path=str(dbfile), resume_text="r", master_tex="m", env=_ENV)
    assert dbmod.count_watchlist(dbmod.connect(str(dbfile))) == 2


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
    run.run_once(cfg_on, db_path=str(dbfile), resume_text="r", master_tex="m", env=_ENV)
    assert calls == [("simplify", ["Software"])]

    calls.clear()
    cfg_off = cfgmod.load_config("companies: []\nfeeds:\n  simplify:\n    enabled: false\n")
    run.run_once(cfg_off, db_path=str(dbfile), resume_text="r", master_tex="m", env=_ENV)
    assert calls == []


# --- run_once builds the candidate + plumbs Ollama env (the real wiring) ---

def _run_once_capturing_score(monkeypatch, tmp_path, cfg, env):
    """Drive the REAL run_score over one 'new' row, capturing the kwargs the wired
    score_fn passes to score_posting. fetch/tailor/notify are stubbed so no network
    or Claude/Telegram is touched."""
    captured = {}

    def fake_score_posting(posting, resume_text, **kwargs):
        captured["kwargs"] = kwargs
        captured["posting"] = posting
        return {"score": 70}

    monkeypatch.setattr(run, "score_posting", fake_score_posting)
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_tailor", lambda *a, **k: None)
    monkeypatch.setattr(run.pipeline, "run_notify", lambda *a, **k: None)

    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    conn = dbmod.connect(str(dbfile))
    dbmod.upsert_postings(conn, [make_posting("1")], now="2026-01-01T00:00:00.000Z")
    conn.close()

    run.run_once(cfg, db_path=str(dbfile), resume_text="r", master_tex="m", env=env)
    return captured


def test_run_once_builds_candidate_and_honors_num_ctx(monkeypatch, tmp_path):
    cfg = cfgmod.load_config(
        "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
        "candidate:\n"
        "  years_experience: 2\n"
        "  highest_degree: \"Master's\"\n"
        "  locations: ['remote', 'USA']\n"
        "  dealbreakers: ['no internships']\n"
    )
    env = {"OLLAMA_NUM_CTX": "4096", "OLLAMA_HOST": "http://ol:11434",
           "ANTHROPIC_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    kw = _run_once_capturing_score(monkeypatch, tmp_path, cfg, env)["kwargs"]
    cand = kw["candidate"]
    assert cand["years_experience"] == 2
    assert cand["highest_degree"] == "Master's"
    assert cand["locations"] == ["remote", "USA"]
    assert cand["dealbreakers"] == ["no internships"]
    assert cand["exclude_internships"] is False        # defaults off; plumbed through
    assert kw["num_ctx"] == 4096                       # OLLAMA_NUM_CTX honored
    assert kw["ollama_host"] == "http://ol:11434"
    assert callable(kw["score_fit"])                   # Claude scorer injected


def _run_once_capturing_score_with_model(monkeypatch, tmp_path, cfg, env, *, score_model):
    """Like _run_once_capturing_score, but passes anthropic_score_model through."""
    def fake_score_posting(posting, resume_text, **kwargs):
        return {"score": 70}
    monkeypatch.setattr(run, "score_posting", fake_score_posting)
    monkeypatch.setattr(run.pipeline, "run_fetch", lambda *a, **k: 0)
    monkeypatch.setattr(run.pipeline, "run_tailor", lambda *a, **k: None)
    monkeypatch.setattr(run.pipeline, "run_notify", lambda *a, **k: None)
    dbfile = tmp_path / "applications.db"
    bootstrap_db(str(dbfile))
    conn = dbmod.connect(str(dbfile))
    dbmod.upsert_postings(conn, [make_posting("1")], now="2026-01-01T00:00:00.000Z")
    conn.close()
    run.run_once(cfg, db_path=str(dbfile), resume_text="r", master_tex="m", env=env,
                 anthropic_score_model=score_model)


def test_run_once_uses_score_model_override(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(run, "make_claude_scorer",
                        lambda key, model: seen.setdefault("model", model) or
                        (lambda posting, resume_text: {"score": 70}))
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    env = {"OLLAMA_HOST": "h", "ANTHROPIC_API_KEY": "k",
           "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    _run_once_capturing_score_with_model(monkeypatch, tmp_path, cfg, env,
                                         score_model="claude-opus-4-8")
    assert seen["model"] == "claude-opus-4-8"


def test_run_once_empty_candidate_skips_screening(monkeypatch, tmp_path):
    cfg = cfgmod.load_config("companies:\n  - { source: greenhouse, slug: a, name: A }\n")
    env = {"OLLAMA_HOST": "h", "ANTHROPIC_API_KEY": "k",
           "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
    kw = _run_once_capturing_score(monkeypatch, tmp_path, cfg, env)["kwargs"]
    assert kw["candidate"] is None                     # is_empty() -> no SCREEN call
    assert kw["num_ctx"] == 8192                        # default when env omits it


def test_missing_keywords_parsing():
    assert run._missing_keywords(
        {"score_detail": json.dumps({"missing_keywords": ["aws", "k8s"]})}
    ) == ["aws", "k8s"]
    assert run._missing_keywords({"score_detail": None}) == []
    assert run._missing_keywords({"score_detail": "not json {{{"}) == []
    assert run._missing_keywords({}) == []
