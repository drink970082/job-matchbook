"""TDD for the entrypoint: --once runs the four stages in order, env plumbing."""
from __future__ import annotations

from ats_worker import run


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

    schema = (
        __import__("pathlib").Path(__file__).parent / "fixtures" / "schema.sql"
    ).read_text()
    dbfile = tmp_path / "applications.db"
    import sqlite3
    boot = sqlite3.connect(dbfile)
    boot.executescript(schema)
    boot.execute(
        "INSERT INTO job_postings (source, external_id, company_name, job_title, "
        "job_url, description, score, pipeline_status, created_at) VALUES "
        "('greenhouse','77','Acme','Eng','http://x','jd',90,'scored','2026-01-01')"
    )
    boot.commit()
    boot.close()

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
