import subprocess
import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]


def test_fresh_preselection_import_avoids_legacy_and_private_file_reads():
    script = r'''
import sys
from pathlib import Path

forbidden = (
    "/resume/",
    "/config.yaml",
    "/ats_worker/score/",
    "/score/prompts/",
    "/personal_profile",
)

def audit(event, args):
    if event != "open" or not args:
        return
    path = args[0]
    if isinstance(path, (str, bytes, Path)):
        normalized = str(path).replace("\\", "/")
        if any(fragment in normalized for fragment in forbidden):
            raise AssertionError("forbidden preselection import read: " + normalized)

sys.addaudithook(audit)
import ats_worker.preselection.questions
import ats_worker.preselection.extraction
import ats_worker.preselection.shadow
assert not any(
    name == "ats_worker.score" or name.startswith("ats_worker.score.")
    for name in sys.modules
)
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKER_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
