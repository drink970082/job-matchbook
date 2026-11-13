from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from ats_worker.preselection.jev import (
    jev_question_set_from_value,
    native_jev_journal_payload,
)
from ats_worker.preselection.preference import PreferencePolicy, PreferenceTier
from ats_worker.preselection.preference_guard import (
    AtomicAvoidanceContract,
    GuardAvoidance,
    PreferenceGuardError,
    derive_preference_guard,
)
from ats_worker.preselection.shadow import AttemptRecord, ModelIdentity, RunBinding


WORKER_ROOT = Path(__file__).resolve().parents[1]


COMPOUND_QUESTIONS = {
    "version": "synthetic-compound-v1",
    "questions": [
        {
            "id": "duty_avoidance",
            "type": "choice",
            "instructions": "Synthetic avoidance.",
            "criteria": {"present": "Present.", "absent": "Absent.", "unclear": "Unclear."},
        },
        {
            "id": "quant_role",
            "type": "choice",
            "instructions": "Synthetic role.",
            "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."},
        },
        {
            "id": "python_role",
            "type": "choice",
            "instructions": "Synthetic role.",
            "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."},
        },
        {
            "id": "general_role",
            "type": "choice",
            "instructions": "Synthetic role.",
            "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."},
        },
        {
            "id": "engineering_primary",
            "type": "choice",
            "instructions": "Synthetic engineering.",
            "criteria": {"yes": "Yes.", "no": "No.", "unknown": "Unknown."},
        },
    ],
}

ATOMIC_IDS = (
    "avoid_frontend_mobile",
    "avoid_hardware_chip_embedded",
    "avoid_low_level_cpp",
    "avoid_operations",
    "avoid_sales_solutions",
    "avoid_analysis_only",
    "avoid_excluded_modeling",
)
ATOMIC_QUESTIONS = {
    "version": "synthetic-atomic-v9",
    "questions": [
        {
            "id": question_id,
            "type": "choice",
            "instructions": "Synthetic atomic duty.",
            "criteria": {"present": "Present.", "absent": "Absent.", "unknown": "Unknown."},
        }
        for question_id in ATOMIC_IDS
    ],
}

MODEL = ModelIdentity("openrouter", "typesafe/jev-1.13", "typesafe/jev-1.13-synthetic")
WORK_ID = "a" * 64


def _questions():
    return jev_question_set_from_value(COMPOUND_QUESTIONS)


def _policy(question_set=None):
    question_set = question_set or _questions()
    return PreferencePolicy(
        version="synthetic-preference-v1",
        question_set_sha256=question_set.sha256,
        first_target_role_ids=("quant_role", "python_role"),
        secondary_role_ids=("general_role",),
        supported_value="supported",
        not_supported_value="not_supported",
        unknown_value="unknown",
        avoidance_question_id="duty_avoidance",
        avoidance_present_value="present",
        avoidance_absent_value="absent",
        avoidance_unclear_value="unclear",
        engineering_question_id="engineering_primary",
        engineering_yes_value="yes",
        engineering_no_value="no",
        engineering_unknown_value="unknown",
    )


def _question_values(question_set, answers):
    raw_answers = {}
    for question in question_set.questions:
        choice = answers[question.id]
        values = list(dict(question.choice_criteria))
        raw_answers[question.id] = {
            "type": "choice",
            "choice": choice,
            "probabilities": {value: (1.0 if value == choice else 0.0) for value in values},
            "confidence": 1.0,
        }
    return raw_answers


def _payload(question_set, answers, *, numeric_shift=0.0):
    raw_answers = _question_values(question_set, answers)
    for answer in raw_answers.values():
        choice = answer["choice"]
        values = list(answer["probabilities"])
        if numeric_shift:
            answer["probabilities"] = {
                value: (0.7 + numeric_shift if value == choice else (0.3 - numeric_shift) / (len(values) - 1))
                for value in values
            }
            answer["confidence"] = 0.35 + numeric_shift
    response = {
        "id": "synthetic-response",
        "model": MODEL.resolved_model,
        "answers": raw_answers,
    }
    return native_jev_journal_payload(question_set, response)


def _binding(question_set, *, run_id, profile_seed):
    return RunBinding(
        run_id,
        ("1" if profile_seed == "native" else "5") * 64,
        ("2" if profile_seed == "native" else "6") * 64,
        question_set.sha256,
        ("3" if profile_seed == "native" else "7") * 64,
        ("4" if profile_seed == "native" else "8") * 64,
    )


def _atomic_contract(question_set):
    return AtomicAvoidanceContract(
        version="atomic-avoidance-v9-synthetic",
        question_ids=ATOMIC_IDS,
        question_set_sha256=question_set.sha256,
    )


def _record(payload, binding, *, attempt_id, draw=1, work_id=WORK_ID, status="succeeded", model=MODEL):
    return AttemptRecord(
        attempt_id=attempt_id,
        stage="assess",
        variant="direct",
        request_identity=("b" if attempt_id == 1 else "c") * 64,
        work_item_identity_sha256=work_id,
        run_binding_sha256=binding.identity_sha256,
        draw_number=draw,
        attempt_number=1,
        retry_of=None,
        status=status,
        provider=model.provider,
        requested_model=model.requested_model,
        resolved_model=model.resolved_model,
        started_at="2026-11-12T00:00:00Z",
        completed_at="2026-11-12T00:00:01Z",
        elapsed_ms=1000,
        usage={"input_tokens": 10, "output_tokens": 10, "cached_input_tokens": 0},
        charge={"kind": "actual", "amount": "0", "currency": "USD", "billing_unit": "token", "rate_date": "2026-11-12", "rate_source": "synthetic"},
        reserved_charge=None,
        response_payload=payload,
        error_code=None,
        delivery="completed",
        circuit_breaker=False,
        retry_delay_seconds=None,
        retry_backoff_completed=False,
    )


def _pair(compound_signal, atomic_values, *, native_numeric_shift=0.0, atomic_numeric_shift=0.0):
    compound = _questions()
    atomic = jev_question_set_from_value(ATOMIC_QUESTIONS)
    native_answers = {
        "duty_avoidance": {"present": "present", "absent": "absent", "unknown": "unclear"}[compound_signal],
        "quant_role": "supported",
        "python_role": "not_supported",
        "general_role": "not_supported",
        "engineering_primary": "yes",
    }
    native_binding = _binding(compound, run_id="native-run", profile_seed="native")
    atomic_binding = _binding(atomic, run_id="atomic-run", profile_seed="atomic")
    native_payload = _payload(compound, native_answers, numeric_shift=native_numeric_shift)
    atomic_payload = _payload(
        atomic,
        dict(zip(ATOMIC_IDS, atomic_values, strict=True)),
        numeric_shift=atomic_numeric_shift,
    )
    native_record = _record(native_payload, native_binding, attempt_id=1)
    atomic_record = _record(atomic_payload, atomic_binding, attempt_id=2)
    return (
        native_record,
        atomic_record,
        native_binding,
        atomic_binding,
        compound,
        atomic,
        _policy(compound),
        _atomic_contract(atomic),
    )


def _derive(pair):
    return derive_preference_guard(
        native_record=pair[0],
        atomic_record=pair[1],
        native_run_binding=pair[2],
        atomic_run_binding=pair[3],
        native_question_set=pair[4],
        atomic_question_set=pair[5],
        atomic_contract=pair[7],
        compound_policy=pair[6],
        expected_model=MODEL,
        expected_work_item_identity_sha256=WORK_ID,
    )


@pytest.mark.parametrize(
    ("compound", "atomic", "expected_tier", "reason", "material"),
    [
        ("present", "present", PreferenceTier.AVOIDED, "signals-agree-present", False),
        ("present", "absent", PreferenceTier.UNRESOLVED, "material-avoidance-disagreement", True),
        ("present", "unknown", PreferenceTier.UNRESOLVED, "ordinary-uncertainty", False),
        ("absent", "present", PreferenceTier.UNRESOLVED, "material-avoidance-disagreement", True),
        ("absent", "absent", PreferenceTier.PRIMARY, "signals-agree-absent", False),
        ("absent", "unknown", PreferenceTier.UNRESOLVED, "ordinary-uncertainty", False),
        ("unknown", "present", PreferenceTier.UNRESOLVED, "ordinary-uncertainty", False),
        ("unknown", "absent", PreferenceTier.UNRESOLVED, "ordinary-uncertainty", False),
        ("unknown", "unknown", PreferenceTier.UNRESOLVED, "ordinary-uncertainty", False),
    ],
)
def test_guard_truth_table(compound, atomic, expected_tier, reason, material):
    values = [atomic] * len(ATOMIC_IDS)
    result = _derive(_pair(compound, values))

    assert result.tier is expected_tier
    assert result.reason == reason
    assert result.material_disagreement is material
    assert result.review_required is (expected_tier is PreferenceTier.UNRESOLVED)


def test_both_absent_preserves_compound_unresolved_projection():
    pair = list(_pair("absent", ["absent"] * 7))
    answers = {
        "duty_avoidance": "absent",
        "quant_role": "unknown",
        "python_role": "not_supported",
        "general_role": "not_supported",
        "engineering_primary": "yes",
    }
    pair[0].response_payload = _payload(pair[4], answers)

    result = _derive(tuple(pair))

    assert result.tier is PreferenceTier.UNRESOLVED
    assert result.tier is result.base_decision.tier
    assert result.reason == "signals-agree-absent"
    assert result.review_required is True


def test_atomic_present_dominates_unknown_and_requires_complete_vector():
    values = ["unknown"] * 7
    values[3] = "present"
    result = _derive(_pair("absent", values))

    assert result.atomic_avoidance is GuardAvoidance.PRESENT
    assert result.material_disagreement is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda pair: setattr(pair[0], "status", "failed"),
        lambda pair: setattr(pair[1], "variant", "extracted"),
        lambda pair: setattr(pair[0], "work_item_identity_sha256", "d" * 64),
        lambda pair: setattr(pair[1], "draw_number", 2),
        lambda pair: setattr(pair[0], "run_binding_sha256", "e" * 64),
        lambda pair: setattr(pair[1], "resolved_model", "other/model"),
        lambda pair: pair[0].response_payload.__setitem__("response_sha256", "0" * 64),
    ],
)
def test_guard_rejects_failed_unbound_or_mismatched_evidence(mutation):
    pair = list(_pair("absent", ["absent"] * 7))
    mutation(pair)

    with pytest.raises(PreferenceGuardError):
        _derive(tuple(pair))


def test_guard_rejects_incomplete_atomic_vector():
    pair = list(_pair("absent", ["absent"] * 7))
    incomplete_response = deepcopy(pair[1].response_payload["response"])
    incomplete_response["answers"].pop(ATOMIC_IDS[-1])
    pair[1].response_payload = native_jev_journal_payload(pair[5], incomplete_response)

    with pytest.raises(PreferenceGuardError):
        _derive(tuple(pair))


def test_guard_rejects_malformed_atomic_contract_and_run_binding():
    pair = list(_pair("absent", ["absent"] * 7))
    pair[7] = replace(pair[7], question_ids=pair[7].question_ids[:-1] + (pair[7].question_ids[0],))

    with pytest.raises(PreferenceGuardError):
        _derive(tuple(pair))

    pair = list(_pair("absent", ["absent"] * 7))
    pair[7] = replace(pair[7], question_set_sha256="f" * 64)
    with pytest.raises(PreferenceGuardError):
        _derive(tuple(pair))

    pair = list(_pair("absent", ["absent"] * 7))
    pair[3] = replace(pair[3], profile_sha256="f" * 64)
    with pytest.raises(PreferenceGuardError):
        _derive(tuple(pair))


def test_numeric_probability_and_confidence_changes_do_not_change_arbitration():
    baseline = _derive(_pair("absent", ["absent"] * 7))
    changed = _derive(
        _pair("absent", ["absent"] * 7, native_numeric_shift=-0.1, atomic_numeric_shift=-0.1)
    )

    assert (changed.tier, changed.reason, changed.material_disagreement) == (
        baseline.tier,
        baseline.reason,
        baseline.material_disagreement,
    )
    assert changed.native_response_sha256 != baseline.native_response_sha256
    assert changed.atomic_response_sha256 != baseline.atomic_response_sha256
    assert changed.policy_sha256 == baseline.policy_sha256
    assert changed.policy_sha256 != changed.base_decision.policy_sha256
    assert changed.guard_version == baseline.guard_version


def test_guard_policy_identity_changes_with_atomic_contract_version_or_question_hash():
    pair = _pair("absent", ["absent"] * 7)
    baseline = _derive(pair)

    versioned_pair = list(pair)
    versioned_pair[7] = replace(pair[7], version="atomic-avoidance-v10-synthetic")
    versioned = _derive(tuple(versioned_pair))
    assert versioned.policy_sha256 != baseline.policy_sha256

    atomic_value = pair[5].as_dict()
    atomic_value["version"] = "synthetic-atomic-v10"
    updated_questions = jev_question_set_from_value(atomic_value)
    updated_binding = replace(pair[3], question_set_sha256=updated_questions.sha256)
    updated_payload = native_jev_journal_payload(updated_questions, pair[1].response_payload["response"])
    updated_record = replace(
        pair[1],
        run_binding_sha256=updated_binding.identity_sha256,
        response_payload=updated_payload,
    )
    pinned_pair = list(pair)
    pinned_pair[1] = updated_record
    pinned_pair[3] = updated_binding
    pinned_pair[5] = updated_questions
    pinned_pair[7] = replace(pair[7], question_set_sha256=updated_questions.sha256)
    pinned = _derive(tuple(pinned_pair))
    assert pinned.policy_sha256 != baseline.policy_sha256


def test_guard_preserves_raw_payloads_and_all_provenance():
    pair = _pair("absent", ["absent"] * 7)
    native_before = deepcopy(pair[0].response_payload)
    atomic_before = deepcopy(pair[1].response_payload)

    result = _derive(pair)

    assert result.native_response_payload == native_before
    assert result.atomic_response_payload == atomic_before
    assert result.source_work_item_identity_sha256 == WORK_ID
    assert result.draw_number == 1
    assert result.native_run_binding_sha256 == pair[2].identity_sha256
    assert result.atomic_run_binding_sha256 == pair[3].identity_sha256
    assert result.native_question_set_sha256 == pair[4].sha256
    assert result.atomic_question_set_sha256 == pair[5].sha256
    assert result.native_response_sha256 == native_before["response_sha256"]
    assert result.atomic_response_sha256 == atomic_before["response_sha256"]
    assert pair[0].response_payload == native_before
    assert pair[1].response_payload == atomic_before


def test_atomic_contract_is_versioned_and_pins_seven_ids_and_question_hash():
    pair = _pair("absent", ["absent"] * 7)
    contract = pair[7]

    assert contract.version == "atomic-avoidance-v9-synthetic"
    assert len(contract.question_ids) == 7
    assert len(set(contract.question_ids)) == 7
    assert contract.question_set_sha256 == pair[5].sha256


def test_guard_executes_with_legacy_imports_and_private_resources_blocked():
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
        raise AssertionError("guard read a private or legacy resource: " + str(path))

sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd() / "tests"))
from test_preselection_preference_guard import _derive, _pair
result = _derive(_pair("absent", ["absent"] * 7))
assert result.tier.value == "primary"
loaded = [name for name in sys.modules if any(name == item or name.startswith(item + ".") for item in forbidden)]
assert not loaded, loaded
print("PREFERENCE_GUARD_BLOCKED_LEGACY_EXECUTION_PASS")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKER_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREFERENCE_GUARD_BLOCKED_LEGACY_EXECUTION_PASS" in result.stdout


def test_guard_module_import_does_not_load_shadow_or_legacy_runtime_modules():
    script = r'''
import importlib.abc
import sys

forbidden = (
    "ats_worker.preselection.shadow",
    "ats_worker.score",
    "ats_worker.fit_profile",
    "ats_worker.prompts",
    "ats_worker.config",
    "ats_worker.registry",
    "ats_worker.run",
)

class BlockModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in forbidden):
            raise ImportError("forbidden import: " + fullname)
        return None

sys.meta_path.insert(0, BlockModules())
import ats_worker.preselection.preference_guard
loaded = [name for name in sys.modules if any(name == item or name.startswith(item + ".") for item in forbidden)]
assert not loaded, loaded
print("PREFERENCE_GUARD_IMPORT_BOUNDARY_PASS")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=WORKER_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREFERENCE_GUARD_IMPORT_BOUNDARY_PASS" in result.stdout
