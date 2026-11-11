"""Hermetic tests for the isolated JEV campaign ledger and repeat reporter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ats_worker.preselection.convergence import (
    BudgetedTransport,
    CampaignBudgetExceeded,
    CampaignConfig,
    CampaignLedger,
    CampaignLedgerIntegrityError,
    ConvergenceError,
    ContradictionPolicy,
    Stage1Manifest,
    Stage1Observation,
    build_stage1_report,
)
from ats_worker.preselection.jev import jev_question_set_from_value, native_jev_journal_payload


QUESTIONS = {
    "version": "synthetic-convergence-v1",
    "questions": [
        {"id": "preference", "type": "choice", "instructions": "Synthetic preference.",
         "criteria": {"primary": "Primary.", "adjacent": "Adjacent.", "avoided": "Avoided."}},
        {"id": "quant_swe", "type": "choice", "instructions": "Synthetic family support.",
         "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."}},
        {"id": "python_quant", "type": "choice", "instructions": "Synthetic family support.",
         "criteria": {"supported": "Supported.", "not_supported": "Not supported.", "unknown": "Unknown."}},
    ],
}
MODEL = "typesafe/jev-1.13:synthetic-canonical"
PROFILE_SHA = "a" * 64


def _config(**overrides):
    values = {
        "campaign_id": "synthetic-stage-one",
        "historical_spend": "0.002003148",
        "historical_attempts": 10,
        "global_ceiling": "10",
        "ordinary_dispatch_ceiling": "9",
        "stage_ceiling": "0.50",
        "reserve_per_attempt": "0.15",
        "max_global_attempts": 5000,
        "max_stage_attempts": 40,
    }
    values.update(overrides)
    return CampaignConfig(**values)


def _charge(amount="0.0001", **overrides):
    values = {
        "kind": "actual",
        "amount": amount,
        "currency": "USD",
        "billing_unit": "request",
        "rate_date": "2026-11-10",
        "rate_source": "synthetic.provider.cost",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _reserve(ledger, request="request-1", draw=1, work_hash="b" * 64):
    return ledger.reserve_attempt(
        phase="stage1", run_id="synthetic-run", request_identity=request,
        work_item_identity_sha256=work_hash, draw_number=draw,
    )


def _authorization_hash():
    return hashlib.sha256(b"synthetic-operator-authorization").hexdigest()


def _extend(ledger, *, new_cap=100, expected_previous_event_sha256=None):
    snapshot = ledger.snapshot()
    return ledger.extend_stage_attempts(
        new_cap=new_cap,
        authorization_sha256=_authorization_hash(),
        expected_previous_event_sha256=(
            expected_previous_event_sha256 or snapshot.last_event_sha256
        ),
    )


class _Invocation:
    request_identity = "request-transport"
    work_item_identity_sha256 = "c" * 64
    draw_number = 1


class _ReplyTransport:
    def __init__(self, charge):
        self.charge = charge
        self.calls = 0

    def complete(self, invocation):
        self.calls += 1
        return SimpleNamespace(charge=self.charge)


class _FailingTransport:
    def complete(self, invocation):
        raise RuntimeError("synthetic unknown delivery")


def _response(question_set, response_id, answers):
    raw_answers = {}
    for question in question_set.questions:
        answer_value = answers[question.id]
        criteria = dict(question.choice_criteria)
        probabilities = {key: (1.0 if key == answer_value else 0.0) for key in criteria}
        raw_answers[question.id] = {
            "type": "choice", "choice": answer_value,
            "probabilities": probabilities, "confidence": 1.0,
        }
    response = {
        "id": response_id,
        "model": MODEL,
        "answers": raw_answers,
        "usage": {"input_tokens": 10, "output_tokens": 4, "cost": 0.0001},
    }
    return native_jev_journal_payload(question_set, response)


def _manifest(expected=(('synthetic-job-1', 1), ('synthetic-job-1', 2), ('synthetic-job-1', 3)), policy=True):
    question_set = jev_question_set_from_value(QUESTIONS)
    contradiction_policy = None
    if policy:
        contradiction_policy = ContradictionPolicy(
            preference_question_id="preference",
            primary_value="primary",
            adjacent_value="adjacent",
            avoided_value="avoided",
            first_target_role_ids=("quant_swe", "python_quant"),
            supported_value="supported",
        )
    return Stage1Manifest(
        campaign_id="synthetic-stage-one",
        profile_sha256=PROFILE_SHA,
        model_identity=MODEL,
        question_set=question_set,
        expected_draws=tuple(expected),
        contradiction_policy=contradiction_policy,
    )


def _observation(manifest, draw, preference, quant="not_supported", python="not_supported", *, job="synthetic-job-1"):
    return Stage1Observation(
        work_item_ref=job,
        draw_number=draw,
        profile_sha256=PROFILE_SHA,
        model_identity=MODEL,
        request_identity=hashlib.sha256(f"{job}:{draw}".encode()).hexdigest(),
        assessment_from_cache=False,
        native_payload=_response(
            manifest.question_set,
            f"synthetic-response-{job}-{draw}",
            {"preference": preference, "quant_swe": quant, "python_quant": python},
        ),
    )


def test_ledger_reserves_before_call_settles_idempotently_and_resumes(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config())
    initial = ledger.snapshot()
    assert initial.attempts == 10
    assert initial.stage_attempts == 0
    assert initial.settled_spend == "0.002003148"

    reservation = _reserve(ledger)
    assert path.read_text().endswith("\n")
    assert ledger.snapshot().pending_reservation_id == reservation.reservation_id
    with pytest.raises(CampaignBudgetExceeded, match="in-flight"):
        _reserve(ledger, request="request-2", draw=2)

    charge = _charge()
    settled = ledger.settle(reservation.reservation_id, charge)
    assert settled.attempts == 11
    assert settled.stage_attempts == 1
    assert settled.settled_spend == "0.002103148"
    assert settled.pending_reservation_id is None
    assert ledger.settle(reservation.reservation_id, charge) == settled

    restarted = CampaignLedger(path, _config())
    assert restarted.snapshot() == settled
    with pytest.raises(CampaignLedgerIntegrityError, match="different charge"):
        restarted.settle(reservation.reservation_id, _charge("0.0002"))


def test_unknown_and_interrupted_reservations_stop_after_restart(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config())
    reservation = _reserve(ledger)
    restarted = CampaignLedger(path, _config())
    with pytest.raises(CampaignBudgetExceeded, match="in-flight"):
        _reserve(restarted, request="second")
    unknown = restarted.settle(reservation.reservation_id, None)
    assert unknown.has_unknown_settlement
    assert restarted.settle(reservation.reservation_id, None) == unknown
    with pytest.raises(CampaignBudgetExceeded, match="unknown charge"):
        _reserve(CampaignLedger(path, _config()), request="third")


def test_over_reserve_charge_is_recorded_and_persistently_stops_new_attempts(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config())
    reservation = _reserve(ledger)
    settled = ledger.settle(reservation.reservation_id, _charge("0.150000001"))
    assert settled.settled_spend == "0.152003149"
    assert settled.has_over_reserve_charge
    restarted = CampaignLedger(path, _config())
    assert restarted.snapshot().has_over_reserve_charge
    with pytest.raises(CampaignBudgetExceeded, match="exceeded its reserve"):
        _reserve(restarted, request="must-not-dispatch", draw=2)


def test_budgeted_transport_settles_provider_failure_and_leaves_unclassified_errors_pending(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config())
    inner = _ReplyTransport(_charge())
    transport = BudgetedTransport(inner, ledger, run_id="synthetic-run")
    reply = transport.complete(_Invocation())
    assert reply.charge.amount == "0.0001"
    assert inner.calls == 1
    assert ledger.snapshot().stage_attempts == 1

    path2 = tmp_path / "interrupted.jsonl"
    interrupted_ledger = CampaignLedger(path2, _config())
    with pytest.raises(RuntimeError, match="unknown delivery"):
        BudgetedTransport(_FailingTransport(), interrupted_ledger, run_id="synthetic-run").complete(_Invocation())
    snapshot = CampaignLedger(path2, _config()).snapshot()
    assert snapshot.pending_reservation_id is not None
    with pytest.raises(CampaignBudgetExceeded, match="in-flight"):
        _reserve(CampaignLedger(path2, _config()), request="no-retry")

    class _ChargedFailure(Exception):
        def __init__(self):
            self.charge = _charge("0.0002")

    class _FailureTransport:
        def complete(self, invocation):
            raise _ChargedFailure()

    path3 = tmp_path / "provider-failure.jsonl"
    with pytest.raises(_ChargedFailure):
        BudgetedTransport(_FailureTransport(), CampaignLedger(path3, _config()), run_id="synthetic-run").complete(_Invocation())
    assert CampaignLedger(path3, _config()).snapshot().settled_spend == "0.002203148"


def test_campaign_attempt_and_spend_caps_are_checked_before_reserve(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config(max_stage_attempts=1))
    reservation = _reserve(ledger)
    ledger.settle(reservation.reservation_id, _charge("0.1"))
    with pytest.raises(CampaignBudgetExceeded, match="stage attempt cap"):
        _reserve(ledger, request="second", draw=2)

    spend_path = tmp_path / "spend-cap.jsonl"
    spend_ledger = CampaignLedger(spend_path, _config(stage_ceiling="0.20"))
    spend_reservation = _reserve(spend_ledger)
    spend_ledger.settle(spend_reservation.reservation_id, _charge("0.05"))
    with pytest.raises(CampaignBudgetExceeded, match="stage reserve ceiling"):
        _reserve(spend_ledger, request="second", draw=2)


def test_corrupted_truncated_or_reconfigured_ledger_fails_loud(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config())
    reservation = _reserve(ledger)
    ledger.settle(reservation.reservation_id, _charge())
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:-4])
    with pytest.raises(CampaignLedgerIntegrityError, match="truncated"):
        ledger.snapshot()

    fresh = tmp_path / "fresh.jsonl"
    ledger2 = CampaignLedger(fresh, _config())
    _reserve(ledger2)
    with pytest.raises(CampaignLedgerIntegrityError, match="configuration"):
        CampaignLedger(fresh, _config(stage_ceiling="0.49")).snapshot()


def test_competing_reservers_are_serialized_by_filesystem_lock(tmp_path):
    ledger = CampaignLedger(tmp_path / "campaign.jsonl", _config())

    def reserve(draw):
        try:
            return _reserve(ledger, request=f"request-{draw}", draw=draw)
        except CampaignBudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, (1, 2)))
    assert sum(result is not None for result in results) == 1
    assert ledger.snapshot().pending_reservation_id is not None


def test_three_draw_report_computes_stability_without_quality_claims():
    manifest = _manifest(policy=False)
    report = build_stage1_report(manifest, [
        _observation(manifest, 1, "primary"),
        _observation(manifest, 2, "primary"),
        _observation(manifest, 3, "primary"),
    ])
    assert report["planned_draws"] == 3
    assert report["completed_draws"] == 3
    assert report["missing_draws"] == []
    assert report["field_metrics"]["preference"]["observed"]["modal_agreement"] == 1.0
    assert report["field_metrics"]["preference"]["pairwise_agreement"] == 1.0
    assert report["quality_evaluation"] == "not_measured"
    assert report["labels_used"] is False
    assert report["scores_or_ranks_created"] is False
    assert report["contradictions"] == []


def test_three_draw_report_preserves_missing_draws_and_finds_explicit_contradictions():
    manifest = _manifest()
    report = build_stage1_report(manifest, [
        _observation(manifest, 1, "adjacent", quant="supported"),
        _observation(manifest, 2, "primary"),
    ])
    assert report["completed_draws"] == 2
    assert report["missing_draws"] == [{"work_item_ref": "synthetic-job-1", "draw_number": 3}]
    preference = report["field_metrics"]["preference"]
    assert preference["modal_agreement"] == 0.5
    assert preference["pairwise_agreement"] == 0.0
    assert {item["kind"] for item in report["contradictions"]} == {
        "first_target_supported_with_adjacent_preference",
        "primary_preference_without_first_target_support",
    }

    flips = build_stage1_report(manifest, [
        _observation(manifest, 1, "primary", quant="supported"),
        _observation(manifest, 2, "avoided", quant="supported"),
    ])
    assert any(item["kind"] == "primary_vs_avoided_repeat_flip" for item in flips["contradictions"])


@pytest.mark.parametrize("bad_observation", [
    "duplicate", "extra", "wrong-profile", "wrong-model", "tampered", "cache", "request-reuse"
])
def test_stage1_report_rejects_unbound_or_duplicate_observations(bad_observation):
    manifest = _manifest()
    valid = _observation(manifest, 1, "primary")
    if bad_observation == "duplicate":
        observations = [valid, valid]
    elif bad_observation == "extra":
        observations = [_observation(manifest, 4, "primary")]
    elif bad_observation == "wrong-profile":
        observations = [Stage1Observation(valid.work_item_ref, valid.draw_number, "d" * 64, MODEL,
                                          valid.request_identity, False, valid.native_payload)]
    elif bad_observation == "wrong-model":
        observations = [Stage1Observation(valid.work_item_ref, valid.draw_number, PROFILE_SHA, "other-model",
                                          valid.request_identity, False, valid.native_payload)]
    elif bad_observation == "cache":
        observations = [Stage1Observation(valid.work_item_ref, valid.draw_number, PROFILE_SHA, MODEL,
                                          valid.request_identity, True, valid.native_payload)]
    elif bad_observation == "request-reuse":
        other = _observation(manifest, 2, "primary")
        other = Stage1Observation(other.work_item_ref, other.draw_number, other.profile_sha256,
                                  other.model_identity, valid.request_identity, False, other.native_payload)
        observations = [valid, other]
    else:
        payload = dict(valid.native_payload)
        payload["question_set_sha256"] = "0" * 64
        observations = [Stage1Observation(valid.work_item_ref, valid.draw_number, PROFILE_SHA, MODEL,
                                          valid.request_identity, False, payload)]
    with pytest.raises(ConvergenceError):
        build_stage1_report(manifest, observations)


def test_policy_must_name_frozen_choice_fields_and_values():
    manifest = _manifest()
    bad = ContradictionPolicy("missing", "primary", "adjacent", "avoided", ("quant_swe",), "supported")
    with pytest.raises(ConvergenceError):
        Stage1Manifest(manifest.campaign_id, manifest.profile_sha256, MODEL,
                       manifest.question_set, manifest.expected_draws, bad).validate()


def test_stage_cap_extension_is_cas_bound_idempotent_and_preserves_accounting(tmp_path):
    path = tmp_path / "campaign.jsonl"
    ledger = CampaignLedger(path, _config())
    for draw in (1, 2):
        reservation = _reserve(ledger, request=f"before-extension-{draw}", draw=draw)
        ledger.settle(reservation.reservation_id, _charge("0.0002"))
    before = ledger.snapshot()
    original_config_hash = ledger.config.identity_sha256
    original_anchor = json.loads(path.read_text().splitlines()[0])["body"]
    assert before.stage_attempts == 2
    assert before.attempts == 12
    assert before.current_stage_attempt_cap == 40

    amended = _extend(ledger)

    assert amended.stage_attempts == before.stage_attempts
    assert amended.attempts == before.attempts
    assert amended.settled_spend == before.settled_spend
    assert amended.current_stage_attempt_cap == 100
    assert amended.last_event_sha256 != before.last_event_sha256
    assert ledger.config.identity_sha256 == original_config_hash
    assert json.loads(path.read_text().splitlines()[0])["body"] == original_anchor
    assert _extend(ledger, expected_previous_event_sha256=before.last_event_sha256) == amended

    with pytest.raises(CampaignLedgerIntegrityError, match="different cap amendment"):
        _extend(ledger, new_cap=101, expected_previous_event_sha256=before.last_event_sha256)

    resumed = CampaignLedger(path, _config())
    assert resumed.snapshot() == amended
    after = _reserve(resumed, request="after-extension", draw=3)
    assert resumed.snapshot().stage_attempts == 3
    assert resumed.snapshot().attempts == 13
    resumed.settle(after.reservation_id, _charge())


def test_stage_cap_extension_rejects_stale_cas_nonincrease_and_global_overflow(tmp_path):
    ledger = CampaignLedger(tmp_path / "stale.jsonl", _config())
    stale_hash = ledger.snapshot().last_event_sha256
    reservation = _reserve(ledger)
    ledger.settle(reservation.reservation_id, _charge())
    with pytest.raises(CampaignBudgetExceeded, match="stale"):
        _extend(ledger, expected_previous_event_sha256=stale_hash)

    with pytest.raises(ConvergenceError, match="strictly increase"):
        _extend(ledger, new_cap=40)
    with pytest.raises(ConvergenceError, match="integer"):
        ledger.extend_stage_attempts(
            new_cap=True,
            authorization_sha256=_authorization_hash(),
            expected_previous_event_sha256=ledger.snapshot().last_event_sha256,
        )
    with pytest.raises(ConvergenceError, match="authorization_sha256"):
        ledger.extend_stage_attempts(
            new_cap=100,
            authorization_sha256="bad",
            expected_previous_event_sha256=ledger.snapshot().last_event_sha256,
        )

    tight = CampaignLedger(tmp_path / "global.jsonl", _config(max_global_attempts=11))
    with pytest.raises(CampaignBudgetExceeded, match="global attempts remaining"):
        _extend(tight, new_cap=41)


def test_replay_rejects_a_second_cap_amendment_event(tmp_path):
    path = tmp_path / "duplicate-amendment.jsonl"
    ledger = CampaignLedger(path, _config())
    _extend(ledger)
    last_envelope = json.loads(path.read_text().splitlines()[-1])
    previous_hash = last_envelope["event_sha256"]
    body = {
        "kind": "extend_stage_attempts",
        "campaign_id": "synthetic-stage-one",
        "stage_id": "stage1",
        "previous_stage_attempt_cap": 100,
        "new_stage_attempt_cap": 110,
        "authorization_sha256": _authorization_hash(),
        "expected_previous_event_sha256": previous_hash,
        "previous_event_sha256": previous_hash,
    }
    event_hash = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    duplicate_event = json.dumps(
        {"body": body, "event_sha256": event_hash},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(duplicate_event + "\n")

    with pytest.raises(CampaignLedgerIntegrityError, match="duplicate cap amendments"):
        CampaignLedger(path, _config()).snapshot()


@pytest.mark.parametrize("stop_state", ["pending", "unknown", "over-reserve"])
def test_stage_cap_extension_rejects_pending_or_stopped_campaign(tmp_path, stop_state):
    ledger = CampaignLedger(tmp_path / f"{stop_state}.jsonl", _config())
    reservation = _reserve(ledger)
    if stop_state == "unknown":
        ledger.settle(reservation.reservation_id, None)
    elif stop_state == "over-reserve":
        ledger.settle(reservation.reservation_id, _charge("0.1501"))
    with pytest.raises(CampaignBudgetExceeded, match="pending or stopped"):
        _extend(ledger)
