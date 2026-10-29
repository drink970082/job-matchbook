"""Fresh-process contracts for the screen/legacy dependency boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def test_screen_only_pass_avoids_legacy_imports_prompts_and_resume_reads():
    script = dedent(r'''
        import importlib.abc
        import json
        import sqlite3
        import sys
        import tempfile
        from pathlib import Path

        blocked = ("ats_worker.score", "ats_worker.fit_profile", "ats_worker.prompts")
        class BlockLegacy(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
                    raise ImportError("forbidden legacy import: " + fullname)
                return None
        sys.meta_path.insert(0, BlockLegacy())

        real_read_text = Path.read_text
        prompt_reads = []
        def guarded_read_text(path, *args, **kwargs):
            if path.name in {"score.txt", "seniority.txt", "extract.txt", "personal_profile.txt"}:
                raise AssertionError("forbidden legacy/resume read: " + str(path))
            if path.name.startswith("resume") and path.suffix == ".txt":
                raise AssertionError("resume read in screen-only mode: " + str(path))
            if path.name == "screen.txt":
                prompt_reads.append(str(path))
            return real_read_text(path, *args, **kwargs)
        Path.read_text = guarded_read_text

        from ats_worker import run

        class ForbiddenStage:
            def __call__(self, *args, **kwargs):
                raise AssertionError("screen-only reached a legacy fit/notify stage")
        run.pipeline.run_retry = ForbiddenStage()
        run.pipeline.run_score = ForbiddenStage()
        run.pipeline.run_notify = ForbiddenStage()

        calls = []
        def fake_make_screener(backend, **kwargs):
            assert backend == "codex"
            def extract(prompt, schema):
                calls.append((prompt, schema))
                return {"screen": {"degree": {
                    "degree_levels": ["bachelor's"], "degree_required": False}}}
            return extract
        run.make_screener = fake_make_screener
        run.fetch_company = lambda *args, **kwargs: [{
            "source": "greenhouse", "external_id": "screen-isolation",
            "company_name": "Synthetic", "job_title": "Software Engineer",
            "location": "Remote", "job_url": "https://example.test/jobs/1",
            "description": "Build backend services in Python and Go. " * 12,
        }]

        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            cfg = root / "screen.yaml"
            db = root / "applications.db"
            resume_dir = root / "resume-inputs"
            resume_dir.mkdir()
            (resume_dir / "resume.txt").write_text("must not be read")
            cfg.write_text("companies:\n"
                           "  - { source: greenhouse, slug: synthetic, name: Synthetic }\n"
                           "candidate:\n"
                           "  highest_degree: bachelor's\n"
                           "fit_profile: malformed\n")
            schema = Path("tests/fixtures/schema.sql").read_text()
            connection = sqlite3.connect(db)
            connection.executescript(schema)
            connection.close()
            run.main(["--once", "--screen-only", "--screen-backend", "codex",
                      "--screen-limit", "2", "--config", str(cfg), "--db", str(db),
                      "--resume-dir", str(resume_dir)])

            connection = sqlite3.connect(db)
            posting = connection.execute(
                "SELECT pipeline_status, score, score_detail, attempts, notify_attempts "
                "FROM job_postings WHERE external_id='screen-isolation'").fetchone()
            screening = connection.execute(
                "SELECT state FROM job_screenings").fetchone()
            connection.close()
            assert posting == ("new", None, None, 0, 0), posting
            assert screening == ("complete",), screening
            assert len(calls) == 1, len(calls)
            assert prompt_reads and all(Path(p).name == "screen.txt" for p in prompt_reads)
            assert not any(name.startswith(blocked[0]) for name in sys.modules)
            assert not any(name == blocked[1] or name.startswith(blocked[1] + ".")
                           for name in sys.modules)
            assert not any(name == blocked[2] or name.startswith(blocked[2] + ".")
                           for name in sys.modules)
        print("SCREEN_ONLY_ISOLATION_PASS")
    ''')
    worker = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(worker)
    result = subprocess.run([sys.executable, "-c", script], cwd=worker, env=env,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SCREEN_ONLY_ISOLATION_PASS" in result.stdout


def test_explicit_legacy_run_still_validates_and_uses_legacy_fit_path():
    script = dedent(r'''
        import json
        import sqlite3
        import sys
        import tempfile
        from pathlib import Path

        from ats_worker import run

        fit_calls = []
        card = {
            "score": 88,
            "assessment": {
                "seniority": {"verdict": "match", "note": ""},
                "domain": {"verdict": "match", "note": ""},
                "must_haves": {"met": [], "missing": []},
                "nice_to_haves": {"missing": []},
                "summary": "synthetic fit result",
            },
            "insufficient_context": False,
        }
        def fake_scorer_factory(*args, **kwargs):
            def fit(postings, resumes):
                assert resumes == {"resume": "synthetic resume"}, resumes
                fit_calls.extend(posting["external_id"] for posting in postings)
                return [dict(card) for _ in postings]
            return fit
        run.make_codex_scorer = fake_scorer_factory
        run.make_screener = lambda *args, **kwargs: None
        run.capture_usage = lambda *args, **kwargs: True
        run.fetch_company = lambda *args, **kwargs: [{
            "source": "greenhouse", "external_id": "legacy-pass",
            "company_name": "Synthetic", "job_title": "Software Engineer",
            "location": "Remote", "job_url": "https://example.test/jobs/legacy",
            "description": "Build backend services. " * 80,
        }]

        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            config = root / "config.yaml"
            database = root / "applications.db"
            resume_dir = root / "resumes"
            resume_dir.mkdir()
            (resume_dir / "resume.txt").write_text("synthetic resume")
            config.write_text("companies:\n"
                              "  - { source: greenhouse, slug: synthetic, name: Synthetic }\n")
            connection = sqlite3.connect(database)
            connection.executescript(Path("tests/fixtures/schema.sql").read_text())
            connection.close()

            run.main(["--once", "--score-backend", "codex", "--screen-backend", "none",
                      "--config", str(config), "--db", str(database),
                      "--resume-dir", str(resume_dir), "--env", str(root / ".env")])

            connection = sqlite3.connect(database)
            posting = connection.execute(
                "SELECT pipeline_status, score FROM job_postings "
                "WHERE external_id='legacy-pass'").fetchone()
            connection.close()
            assert posting == ("scored", 88), posting
            assert fit_calls == ["legacy-pass"], fit_calls
            for name in ("ats_worker.score", "ats_worker.fit_profile", "ats_worker.prompts"):
                assert name in sys.modules, name
        print("LEGACY_FIT_COMPATIBILITY_PASS")
    ''')
    worker = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(worker)
    result = subprocess.run([sys.executable, "-c", script], cwd=worker, env=env,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LEGACY_FIT_COMPATIBILITY_PASS" in result.stdout


def test_compatibility_facade_and_exception_imports_defer_fit_resources_in_fresh_processes():
    script = dedent(r'''
        import sys
        from pathlib import Path

        action = sys.argv[1]
        prompt_reads = []
        real_read_text = Path.read_text
        def record_reads(path, *args, **kwargs):
            if path.name in {"score.txt", "screen.txt", "seniority.txt", "extract.txt"}:
                prompt_reads.append(path.name)
            return real_read_text(path, *args, **kwargs)
        Path.read_text = record_reads

        if action == "exception":
            from ats_worker.score.errors import ScoreError
            from ats_worker.model_errors import ModelResponseError
            assert ScoreError is ModelResponseError
        elif action == "facade":
            from ats_worker.score import ScoreError
            from ats_worker.model_errors import ModelResponseError
            assert ScoreError is ModelResponseError
        elif action == "screen":
            from ats_worker.score import SCREEN_SCHEMA, deterministic_screen, screen_posting
            from ats_worker.screening.engine import deterministic_screen as neutral_screen
            from ats_worker.screening.engine import screen_posting as neutral_posting
            from ats_worker.screening.prompts import SCREEN_SCHEMA as neutral_schema
            assert deterministic_screen is neutral_screen
            assert screen_posting is neutral_posting
            assert SCREEN_SCHEMA == neutral_schema
        elif action == "screen-module":
            from ats_worker import score
            from ats_worker.screening.engine import screen_posting as neutral_posting
            assert score.screen.screen_posting is neutral_posting
        elif action == "usage-module":
            import importlib
            from ats_worker import score
            assert score.usage is importlib.import_module("ats_worker.score.usage")
            assert "usage" in score.__all__
        elif action == "fit-factory":
            from ats_worker.score import make_codex_scorer
            assert callable(make_codex_scorer)
            assert "ats_worker.score.backends_codex" in sys.modules
            assert "score.txt" in prompt_reads
        else:
            raise AssertionError(action)

        fit_backends = {
            "ats_worker.score.backends_codex",
            "ats_worker.score.backends_claude",
            "ats_worker.score.backends_claude_cli",
        }
        if action == "fit-factory":
            assert fit_backends.intersection(sys.modules)
        else:
            assert not fit_backends.intersection(sys.modules), fit_backends.intersection(sys.modules)
            assert not {"score.txt", "seniority.txt", "extract.txt"}.intersection(prompt_reads), prompt_reads
            assert prompt_reads == (
                ["screen.txt"] if action in {"screen", "screen-module"} else []
            ), prompt_reads
        print("COMPATIBILITY_IMPORT_PASS:" + action)
    ''')
    worker = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(worker)
    for action in (
        "exception",
        "facade",
        "screen",
        "screen-module",
        "usage-module",
        "fit-factory",
    ):
        result = subprocess.run(
            [sys.executable, "-c", script, action],
            cwd=worker,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{action}: {result.stdout}{result.stderr}"
        assert f"COMPATIBILITY_IMPORT_PASS:{action}" in result.stdout
