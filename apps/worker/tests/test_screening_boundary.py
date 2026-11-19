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
        import builtins
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
        def reject_candidate_text_read(path, mode):
            if "r" in mode and path.suffix == ".txt" and path.name != "screen.txt":
                raise AssertionError("screen-only read non-screen text resource: " + str(path))

        real_open = builtins.open
        def guarded_open(file, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            try:
                reject_candidate_text_read(Path(file), mode)
            except TypeError:
                pass
            return real_open(file, *args, **kwargs)
        builtins.open = guarded_open

        real_path_open = Path.open
        def guarded_path_open(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            reject_candidate_text_read(path, mode)
            return real_path_open(path, *args, **kwargs)
        Path.open = guarded_path_open

        def guarded_read_text(path, *args, **kwargs):
            if path.name == "screen.txt":
                prompt_reads.append(str(path))
            return real_read_text(path, *args, **kwargs)
        Path.read_text = guarded_read_text

        from ats_worker import run


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
                           "  highest_degree: bachelor's\n")
            schema = Path("tests/fixtures/schema.sql").read_text()
            connection = sqlite3.connect(db)
            connection.executescript(schema)
            connection.close()
            run.main(["--once", "--screen-only", "--screen-backend", "codex",
                      "--screen-limit", "2", "--config", str(cfg), "--db", str(db)])

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

