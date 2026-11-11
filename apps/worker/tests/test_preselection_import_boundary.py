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


def test_shadow_assessment_runs_with_legacy_imports_and_resources_blocked():
    script = r'''
import importlib.abc
import sys
from pathlib import Path

forbidden = (
    "ats_worker.score",
    "ats_worker.fit_profile",
    "ats_worker.prompts",
    "ats_worker.config",
    "ats_worker.registry",
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
    if path.name == ".env" or path.suffix.lower() in {".txt", ".yaml", ".yml"}:
        raise AssertionError("shadow assessment read a legacy resource: " + str(path))

sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd() / "tests"))

from test_preselection_shadow import (
    ASSESSOR,
    FakeClock,
    FakeTransport,
    assessment_payload,
    approved_profile,
    job,
    limits,
    questions,
    reply,
)
from ats_worker.preselection.shadow import AttemptJournal, run_shadow_assessment
import ats_worker.preselection.jev
import ats_worker.preselection.openrouter_jev
from ats_worker.preselection.convergence import CampaignLedger, build_stage1_report
from ats_worker.preselection.preference import PreferenceTier, derive_preference
from test_preselection_convergence import _charge, _config, _manifest, _observation, _reserve
from test_preselection_preference import (
    MODEL as PREFERENCE_MODEL,
    _payload as preference_payload,
    _policy as preference_policy,
    _questions as preference_questions,
)
from tempfile import TemporaryDirectory
import hashlib

clock = FakeClock()
transport = FakeTransport([reply(ASSESSOR, assessment_payload())], clock)
journal = AttemptJournal.empty()
result = run_shadow_assessment(
    job(),
    approved_profile(),
    questions(),
    "direct",
    ASSESSOR,
    transport,
    journal,
    limits(),
    clock,
    lambda current: None,
    enabled=True,
)
assert result.status == "completed"
assert result.assessment is not None
assert len(transport.calls) == 1
with TemporaryDirectory() as directory:
    ledger = CampaignLedger(Path(directory) / "campaign.jsonl", _config())
    reservation = _reserve(ledger)
    ledger.settle(reservation.reservation_id, _charge())
    before_extension = ledger.snapshot()
    amendment = ledger.extend_stage_attempts(
        new_cap=100,
        authorization_sha256=hashlib.sha256(b"synthetic authorization").hexdigest(),
        expected_previous_event_sha256=before_extension.last_event_sha256,
    )
    assert amendment.current_stage_attempt_cap == 100
    assert amendment.attempts == before_extension.attempts
    manifest = _manifest(policy=False)
    report = build_stage1_report(manifest, [_observation(manifest, 1, "primary")])
    assert report["completed_draws"] == 1
    assert report["quality_evaluation"] == "not_measured"
    question_set = preference_questions()
    decision = derive_preference(
        preference_payload(question_set, quant="supported"),
        question_set,
        PREFERENCE_MODEL,
        preference_policy(question_set),
    )
    assert decision.tier is PreferenceTier.PRIMARY
loaded = [
    name for name in sys.modules
    if any(name == item or name.startswith(item + ".") for item in forbidden)
]
assert not loaded, loaded
print("PRESELECTION_SHADOW_BOUNDARY_PASS")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKER_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRESELECTION_SHADOW_BOUNDARY_PASS" in result.stdout
