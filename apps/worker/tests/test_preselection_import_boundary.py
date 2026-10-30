from __future__ import annotations

import subprocess
import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]


def test_profile_replay_and_cli_import_without_legacy_modules_or_text_reads():
    script = r'''
import importlib.abc
import sys
from pathlib import Path

forbidden = (
    "ats_worker.score",
    "ats_worker.fit_profile",
    "ats_worker.prompts",
    "ats_worker.run",
)

class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in forbidden):
            raise ImportError("forbidden legacy import: " + fullname)
        return None

sys.meta_path.insert(0, BlockLegacy())

def audit(event, args):
    if event != "open" or not args:
        return
    try:
        path = Path(args[0])
    except TypeError:
        return
    if path.suffix == ".txt":
        raise AssertionError("provider-free import read a text resource: " + str(path))

sys.addaudithook(audit)
import ats_worker.preselection.profile
import ats_worker.preselection.replay

sys.path.insert(0, str(Path.cwd() / "tools"))
import preselection_profile
import preselection_replay

loaded = [
    name for name in sys.modules
    if any(name == item or name.startswith(item + ".") for item in forbidden)
]
assert not loaded, loaded
print("PRESELECTION_IMPORT_BOUNDARY_PASS")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKER_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRESELECTION_IMPORT_BOUNDARY_PASS" in result.stdout
