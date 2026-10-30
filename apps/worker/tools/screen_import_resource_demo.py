#!/usr/bin/env python3
"""Compare active worker import/resource use before and after screen isolation.

Example:
    python3 apps/worker/tools/screen_import_resource_demo.py \
        --before a9e5972 --after HEAD

The demo extracts tracked worker files from each revision into temporary folders,
imports the runtime wiring in a fresh process, and reports imported score modules
and prompt files read. It never loads operator configuration or private inputs.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


_PROBE = r'''
import json
import sys
from pathlib import Path

reads = []
real_read_text = Path.read_text
def record_reads(path, *args, **kwargs):
    if path.name in {
        "score.txt", "screen.txt", "seniority.txt", "extract.txt",
        "personal_profile.txt",
    } or (path.name.startswith("resume") and path.suffix == ".txt"):
        reads.append(path.name)
    return real_read_text(path, *args, **kwargs)
Path.read_text = record_reads

import ats_worker.run

score_modules = sorted(
    name for name in sys.modules
    if name == "ats_worker.score" or name.startswith("ats_worker.score.")
)
print(json.dumps({"score_modules": score_modules, "resource_reads": reads}))
'''


def _probe_revision(repo: Path, revision: str) -> dict:
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", revision, "apps/worker"],
        check=True,
        capture_output=True,
    )
    with tempfile.TemporaryDirectory(prefix="screen-import-demo-") as raw_dir:
        root = Path(raw_dir)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            bundle.extractall(root)
        worker = root / "apps" / "worker"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(worker)
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            cwd=worker,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"probe failed for {revision}: {result.stdout}{result.stderr}")
        return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="baseline git revision")
    parser.add_argument("--after", default="HEAD", help="isolated revision (default: HEAD)")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]
    before = _probe_revision(repo, args.before)
    after = _probe_revision(repo, args.after)
    legacy_prompts = {"score.txt", "seniority.txt", "extract.txt"}
    if after["score_modules"]:
        raise SystemExit(f"screen-isolated revision imported score modules: {after['score_modules']}")
    if legacy_prompts.intersection(after["resource_reads"]):
        raise SystemExit(f"screen-isolated revision read legacy prompts: {after['resource_reads']}")
    if after["resource_reads"].count("screen.txt") != 1:
        raise SystemExit(f"expected one screen prompt read, got {after['resource_reads']}")

    print(json.dumps({"before": before, "after": after}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
