from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ats_worker.preselection.evaluation import (
    EvaluationValidationError,
    build_evaluation_report,
    evaluation_from_value,
    load_evaluation_text,
)
from ats_worker.preselection.shadow import AttemptJournal, AttemptRecord, ShadowIntegrityError


FIXTURE = Path(__file__).parent / "fixtures" / "preselection_evaluation.synthetic.json"
TOOLS = Path(__file__).parents[1] / "tools"
EPOCH = "2026-10-27T00:00:00+00:00"


def evaluation_value() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _charge(kind: str, amount: str | None) -> dict[str, str | None]:
    if kind == "unknown":
        return {
            "kind": "unknown",
            "amount": None,
            "currency": None,
            "billing_unit": None,
            "rate_date": None,
            "rate_source": None,
        }
    return {
        "kind": kind,
        "amount": amount,
        "currency": "SYNTHETIC-CREDIT",
        "billing_unit": "fake-call",
        "rate_date": "2026-10-27",
        "rate_source": "synthetic-fixture",
    }


def journal_for(value: dict | None = None) -> AttemptJournal:
    payload = value or evaluation_value()
    run = payload["run"]
    models = run["model_identities"]
    rows: list[AttemptRecord] = []

    def add(
        *,
        stage: str,
        variant: str,
        work_item: str,
        draw: int | None,
        request: str,
        status: str,
        model_key: str,
        retry_of: int | None = None,
        charge_kind: str = "actual",
        amount: str = "0.05",
        response_payload: dict | None = None,
    ) -> None:
        attempt_id = len(rows) + 1
        model = models[model_key]
        success = status == "succeeded"
        rows.append(
            AttemptRecord(
                attempt_id=attempt_id,
                stage=stage,
                variant=variant,
                request_identity=request,
                work_item_identity_sha256=work_item,
                draw_number=draw,
                attempt_number=2 if retry_of is not None else 1,
                retry_of=retry_of,
                status=status,
                provider=model["provider"],
                requested_model=model["requested_model"],
                resolved_model=model["resolved_model"],
                started_at=EPOCH,
                completed_at="2026-10-27T00:00:01+00:00",
                elapsed_ms=100,
                usage={
                    "input_tokens": 10 if success else None,
                    "output_tokens": 4 if success else None,
                    "cached_input_tokens": None,
                },
                charge=_charge(charge_kind, amount if charge_kind != "unknown" else None),
                reserved_charge=None,
                response_payload=response_payload or ({"synthetic": True} if success else None),
                error_code=None if success else "synthetic_failure",
                delivery="completed" if success else ("not_sent" if status == "retryable_failure" else "unknown"),
                circuit_breaker=False,
            )
        )

    # One shared extraction per work item. It is charged once to the extracted arm.
    for item in payload["items"]:
        work_item = item["work_item_identity_sha256"]
        request = hashlib.sha256(f"extract:{work_item}".encode()).hexdigest()
        add(
            stage="extract_jd",
            variant="extract",
            work_item=work_item,
            draw=None,
            request=request,
            status="succeeded",
            model_key="extract",
            amount="0.02",
        )

    for outcome in payload["assessments"]:
        variant = outcome["variant"]
        model_key = variant
        request = outcome["request_identity_sha256"]
        if variant == "direct" and outcome["draw_number"] == 1 and outcome["work_item_identity_sha256"].endswith("1"):
            add(
                stage="assess",
                variant=variant,
                work_item=outcome["work_item_identity_sha256"],
                draw=outcome["draw_number"],
                request=request,
                status="retryable_failure",
                model_key=model_key,
                charge_kind="estimate",
                amount="0.01",
            )
            retry_of = rows[-1].attempt_id
        else:
            retry_of = None
        add(
            stage="assess",
            variant=variant,
            work_item=outcome["work_item_identity_sha256"],
            draw=outcome["draw_number"],
            request=request,
            status="succeeded" if outcome["status"] == "completed" else "failed",
            model_key=model_key,
            retry_of=retry_of,
            charge_kind="actual" if outcome["status"] == "completed" else "unknown",
            amount="0.05",
            response_payload=(
                {
                    "answers": {
                        field: {"value": answer, "evidence": []}
                        for field, answer in outcome["answers"].items()
                    },
                    "explanation": "Synthetic answer fixture.",
                }
                if outcome["status"] == "completed"
                else None
            ),
        )

    journal = AttemptJournal(
        rows,
        run_started_at=EPOCH,
        limits_identity_sha256=run["attempt_limits_identity_sha256"],
    )
    return AttemptJournal.from_json(journal.to_json())


def test_synthetic_report_counts_recall_failures_fields_and_draw_stability_without_ids():
    value = evaluation_value()
    report = build_evaluation_report(evaluation_from_value(value), journal_for(value))

    held_out_direct_draw_two = report["splits"]["held_out"]["arms"]["direct"]["draws"]["2"]
    assert held_out_direct_draw_two["outcome_status_counts"] == {
        "completed": 1,
        "unresolved": 0,
        "failed": 1,
        "missing": 0,
    }
    top_two = held_out_direct_draw_two["budgets"][1]
    assert top_two["positive_total"] == 1
    assert top_two["positive_selected"] == 0
    assert top_two["positive_misses"] == 1
    assert top_two["positive_recall"] == 0
    assert top_two["positive_recall_wilson_95"] == {"lower": 0.0, "upper": 0.793451}
    assert top_two["unselected_label_counts"]["positive"] == 1
    assert top_two["unselected_reason_counts"]["failed_assessment"] == 1
    assert held_out_direct_draw_two["field_metrics"]["work_alignment"]["unanswered_items"] == 1

    stability = report["splits"]["development"]["arms"]["direct"]["top_budget_stability"][0]
    assert stability["pool_draw_pairs"] == 1
    assert stability["mean_top_budget_jaccard"] == 0
    assert report["attempt_accounting"]["per_arm_including_extraction"]["extracted"]["attempts"] == 12
    assert report["attempt_accounting"]["per_arm_including_extraction"]["extracted"]["attempts_by_stage"] == {
        "assess": 8,
        "extract_jd": 4,
    }
    assert report["attempt_accounting"]["run"]["unknown_charge_attempts"] == 1
    assert report["attempt_accounting"]["run"]["retry_attempts"] == 1
    assert {row["kind"] for row in report["attempt_accounting"]["run"]["charge_totals"]} == {
        "actual",
        "estimate",
    }
    direct_item_costs = report["attempt_accounting"]["per_work_item_cost_distribution"]["direct"]
    assert direct_item_costs["work_items_with_unknown_charge"] == 1
    assert direct_item_costs["work_items_with_estimated_charge"] == 1
    assert {row["kind"] for row in direct_item_costs["reported_amounts_by_kind_and_rate"]} == {
        "actual",
        "estimate",
    }
    assert report["decision"]["status"] == "not_recorded"
    assert report["run"]["evaluation_manifest_sha256"] == hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    development_baselines = report["splits"]["development"]["baselines"]
    assert set(development_baselines) == {"recency", "role_coverage"}
    assert development_baselines["recency"]["budgets"][0]["positive_selected"] == 1
    assert development_baselines["role_coverage"]["budgets"][0]["positive_selected"] == 0
    assert "daily_brief" not in development_baselines
    serialized = json.dumps(report, sort_keys=True)
    assert value["items"][0]["work_item_identity_sha256"] not in serialized
    assert "synthetic-group-a" not in serialized
    assert report["run"]["attempt_journal_sha256"] == hashlib.sha256(
        journal_for(value).to_json().encode()
    ).hexdigest()


def test_cli_reads_only_explicit_synthetic_files_and_emits_aggregate_report(tmp_path):
    value = evaluation_value()
    journal_path = tmp_path / "attempts.json"
    journal_for(value).save(journal_path)
    input_path = tmp_path / "evaluation.json"
    input_path.write_text(json.dumps(value), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(TOOLS / "preselection_evaluation.py"), str(input_path), "--journal", str(journal_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["cohort"]["items"] == 4
    assert report["decision"]["status"] == "not_recorded"
    assert value["items"][0]["work_item_identity_sha256"] not in result.stdout


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["items"][1].update(group_id=value["items"][0]["group_id"], split="held_out"),
        lambda value: value["assessments"].append(deepcopy(value["assessments"][0])),
        lambda value: value["run"].update(variants=[[]]),
        lambda value: value["items"][0].update(role_families=[[]]),
        lambda value: value["items"][0].update(field_labels={"unknown_field": "x"}),
        lambda value: value["assessments"][0].update(priority_rank=999),
        lambda value: value["items"][0].update(label_source="human_unresolved"),
        lambda value: value["run"].update(run_id="\ud800"),
    ],
)
def test_malformed_or_leaking_inputs_fail_as_validation_errors(mutate):
    value = evaluation_value()
    mutate(value)
    with pytest.raises(EvaluationValidationError):
        evaluation_from_value(value)


def test_duplicate_json_members_are_rejected():
    with pytest.raises(EvaluationValidationError, match="duplicate JSON"):
        load_evaluation_text('{"schema": 1, "schema": 1}')


def test_human_labels_require_blinding_attestation_and_synthetic_labels_are_marked():
    value = evaluation_value()
    value["run"]["labeling_blinded"] = True
    for item in value["items"]:
        item["label_source"] = "human_unresolved" if item["label"] == "unresolved" else "human_adjudicated"
    dataset = evaluation_from_value(value)
    report = build_evaluation_report(dataset, journal_for(value))
    assert report["cohort"]["label_evidence_status"] == "human_labels_blinded_to_assessments"

    value["run"]["labeling_blinded"] = False
    with pytest.raises(EvaluationValidationError, match="attested as blind"):
        evaluation_from_value(value)

    synthetic = build_evaluation_report(
        evaluation_from_value(evaluation_value()), journal_for(evaluation_value())
    )
    assert synthetic["cohort"]["label_evidence_status"] == "synthetic_fixture_only"


def test_report_rejects_attempt_journal_model_and_outcome_mismatches():
    value = evaluation_value()
    dataset = evaluation_from_value(value)
    journal = journal_for(value)
    journal.records[0].requested_model = "different-model"
    with pytest.raises(EvaluationValidationError, match="provider/model identity"):
        build_evaluation_report(dataset, journal)

    journal = journal_for(value)
    dataset_value = evaluation_value()
    dataset_value["assessments"][0]["request_identity_sha256"] = "f" * 64
    with pytest.raises(EvaluationValidationError, match="does not match its journal"):
        build_evaluation_report(evaluation_from_value(dataset_value), journal)


def test_completed_outcome_cannot_be_claimed_for_a_failed_attempt():
    value = evaluation_value()
    failed = next(row for row in value["assessments"] if row["status"] == "failed")
    failed["status"] = "completed"
    failed["priority_rank"] = 2
    failed["answers"] = {
        "role_families": ["product"],
        "work_alignment": "low",
        "dimension_example": 1,
    }
    dataset = evaluation_from_value(value)
    with pytest.raises(EvaluationValidationError, match="final successful attempt"):
        build_evaluation_report(dataset, journal_for(evaluation_value()))


def test_completed_answers_must_match_the_successful_journal_response():
    value = evaluation_value()
    value["assessments"][0]["answers"]["work_alignment"] = "low"
    with pytest.raises(EvaluationValidationError, match="differ from the successful"):
        build_evaluation_report(evaluation_from_value(value), journal_for(evaluation_value()))


def test_attempt_journal_identity_and_budget_must_match_run():
    value = evaluation_value()
    dataset = evaluation_from_value(value)
    journal = journal_for(value)
    journal.limits_identity_sha256 = "0" * 64
    with pytest.raises(EvaluationValidationError, match="limits identity"):
        build_evaluation_report(dataset, journal)


def test_extracted_assessments_require_one_shared_successful_extraction():
    value = evaluation_value()
    dataset = evaluation_from_value(value)
    journal = journal_for(value)
    journal.records = [record for record in journal.records if record.stage != "extract_jd"]
    with pytest.raises(EvaluationValidationError, match="no successful shared JD extraction"):
        build_evaluation_report(dataset, journal)


def test_missing_outcome_stays_in_recall_denominator_and_is_reported():
    value = evaluation_value()
    value["assessments"] = [
        row
        for row in value["assessments"]
        if not (
            row["work_item_identity_sha256"].endswith("3")
            and row["variant"] == "direct"
            and row["draw_number"] == 1
        )
    ]
    report = build_evaluation_report(evaluation_from_value(value), journal_for(value))
    draw = report["splits"]["held_out"]["arms"]["direct"]["draws"]["1"]
    assert draw["outcome_status_counts"]["missing"] == 1
    assert draw["budgets"][1]["positive_total"] == 1
    assert draw["budgets"][1]["positive_misses"] == 1


def test_repeated_draw_subset_is_not_mislabeled_as_population_recall():
    value = evaluation_value()
    subset_item = value["items"][3]["work_item_identity_sha256"]
    value["items"][3]["draw_numbers"] = [1]
    value["assessments"] = [
        row
        for row in value["assessments"]
        if not (row["work_item_identity_sha256"] == subset_item and row["draw_number"] == 2)
    ]
    report = build_evaluation_report(evaluation_from_value(value), journal_for(value))
    draw = report["splits"]["held_out"]["arms"]["direct"]["draws"]["2"]
    assert draw["expected_assessments"] == 1
    assert draw["assessment_scope"] == "predeclared_repeated_subset"
    assert draw["population_recall_reportable"] is False
    assert draw["outcome_status_counts"]["missing"] == 0


def test_rank_ties_and_daily_pool_split_leakage_are_rejected():
    value = evaluation_value()
    matching = [
        row
        for row in value["assessments"]
        if row["variant"] == "direct" and row["draw_number"] == 1
    ]
    matching[1]["priority_rank"] = matching[0]["priority_rank"]
    with pytest.raises(EvaluationValidationError, match="tie breaks"):
        evaluation_from_value(value)

    value = evaluation_value()
    value["items"][0]["pool_id_sha256"] = value["items"][2]["pool_id_sha256"]
    with pytest.raises(EvaluationValidationError, match="daily pool cannot cross"):
        evaluation_from_value(value)


@pytest.mark.parametrize(
    ("field", "message"),
    [("recency", "recency baseline order"), ("role_coverage", "role-coverage baseline order")],
)
def test_deterministic_baseline_order_is_recomputed_from_frozen_features(field, message):
    value = evaluation_value()
    value["baseline_orders"][0][field].reverse()
    with pytest.raises(EvaluationValidationError, match=message):
        evaluation_from_value(value)


def test_observation_timestamps_must_include_a_timezone_and_outcomes_must_be_planned():
    value = evaluation_value()
    value["items"][0]["observed_at"] = "2026-10-23T11:00:00"
    with pytest.raises(EvaluationValidationError, match="must include a timezone"):
        evaluation_from_value(value)

    value = evaluation_value()
    value["items"][3]["draw_numbers"] = [1]
    with pytest.raises(EvaluationValidationError, match="not planned for this work item"):
        evaluation_from_value(value)


def test_daily_brief_baseline_requires_all_pools_and_keeps_its_cost_external():
    value = evaluation_value()
    for order in value["baseline_orders"]:
        order["daily_brief"] = order["recency"][:1]
    report = build_evaluation_report(evaluation_from_value(value), journal_for(value))
    daily_brief = report["splits"]["development"]["baselines"]["daily_brief"]
    assert daily_brief["budgets"][0]["selected_items"] == 1
    assert "reconcile actual ChatGPT workflow resource use separately" in daily_brief["cost_accounting"]

    value = evaluation_value()
    value["baseline_orders"][0]["daily_brief"] = []
    with pytest.raises(EvaluationValidationError, match="every daily pool or none"):
        evaluation_from_value(value)


def test_cli_rejects_invalid_journal_and_never_invokes_an_external_provider(tmp_path):
    input_path = tmp_path / "evaluation.json"
    input_path.write_text(json.dumps(evaluation_value()), encoding="utf-8")
    journal_path = tmp_path / "journal.json"
    journal_path.write_text("{}", encoding="utf-8")
    journal_path.chmod(0o600)
    result = subprocess.run(
        [sys.executable, str(TOOLS / "preselection_evaluation.py"), str(input_path), "--journal", str(journal_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "cannot build" in result.stderr


def test_invalid_shadow_journal_shape_is_rejected_before_metric_build():
    with pytest.raises(ShadowIntegrityError):
        AttemptJournal.from_json("{}")
