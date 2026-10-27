import json
from pathlib import Path
import subprocess
import sys

import pytest

from ats_worker.preselection.replay import (
    ReplayValidationError,
    _role_coverage_order,
    _stable_split,
    build_replay_report,
    load_pool_text,
    pool_from_value,
)


FIXTURE = Path(__file__).parent / "fixtures/preselection_pool.synthetic.json"
YOE_FIXTURE = Path(__file__).parent / "fixtures/preselection_yoe_boundaries.synthetic.json"


def _pool_value():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_grouped_split_keeps_days_and_shared_templates_together_and_is_repeatable():
    pool = load_pool_text(FIXTURE.read_text(encoding="utf-8"))
    assignments, components = _stable_split(pool, "synthetic-seed", 0.25)

    assert assignments == _stable_split(pool, "synthetic-seed", 0.25)[0]
    assert assignments["synthetic-001"] == assignments["synthetic-003"]
    assert assignments["synthetic-007"] == assignments["synthetic-009"]
    assert set(assignments.values()) == {"development", "held_out"}
    assert sum(components.values()) == 5


def test_replay_reports_aggregate_baselines_label_coverage_and_no_row_identifiers():
    pool = load_pool_text(FIXTURE.read_text(encoding="utf-8"))
    report = build_replay_report(
        pool, seed="synthetic-seed", heldout_fraction=0.25, budgets=(1, 3)
    )
    encoded = json.dumps(report, sort_keys=True)

    assert report["item_count"] == 12
    assert report["provider_calls"] == 0
    assert report["inference_cost"] == "not_applicable_no_provider_calls"
    assert report["split"]["algorithm"] == "utc-day-and-group-connected-components-v1"
    assert "synthetic-001" not in encoded
    assert "shared-template" not in encoded
    assert "synthetic-pool-v1" not in encoded
    assert set(report["splits"]) == {"development", "held_out"}
    for split in report["splits"].values():
        assert split["label_coverage"] == pytest.approx(
            (split["label_counts"]["positive"] + split["label_counts"]["negative"])
            / split["items"]
        )
        assert {result["baseline"] for result in split["baselines"]} == {
            "recency",
            "role_coverage",
        }
        assert all(result["budget"] in {1, 3} for result in split["baselines"])
        assert all("engineering" in result["role_family_metrics"] for result in split["baselines"])
        engineering = split["role_family_metrics"]["engineering"]
        assert set(engineering["label_counts"]) == {"positive", "negative", "unresolved"}
        assert engineering["label_coverage"] == pytest.approx(
            (engineering["label_counts"]["positive"] + engineering["label_counts"]["negative"])
            / engineering["pool_items"]
        )


def test_role_coverage_baseline_prefers_uncovered_families_then_recency():
    pool = load_pool_text(FIXTURE.read_text(encoding="utf-8"))
    ordered = _role_coverage_order(list(pool.items))
    roles = set()
    first_two = []
    for item in ordered[:2]:
        roles.update(item.role_families)
        first_two.append(item)
    assert len(roles) >= len(ordered[0].role_families)
    assert first_two[0] != first_two[1]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(jd="fictional posting text"), "unknown field"),
        (lambda value: value["items"][0].pop("label"), "missing a required field"),
        (lambda value: value["items"][1].update(id=value["items"][0]["id"]), "IDs must be unique"),
        (lambda value: value["items"][0].update(observed_at="2026-01-01T09:00:00"), "timezone"),
        (
            lambda value: value["items"][0].update(label="maybe"),
            "positive, negative, or unresolved",
        ),
        (
            lambda value: value["items"][0].update(
                role_families=["engineering", "engineering"]
            ),
            "duplicates",
        ),
        (lambda value: value["items"][0].update(group_id=" bad "), "trimmed text"),
    ],
)
def test_frozen_pool_schema_rejects_missing_malformed_and_private_text_fields(mutate, message):
    value = _pool_value()
    mutate(value)
    with pytest.raises(ReplayValidationError, match=message):
        pool_from_value(value)


def test_frozen_pool_json_rejects_duplicate_members_and_empty_pool():
    with pytest.raises(ReplayValidationError, match="duplicate JSON"):
        load_pool_text('{"schema":1,"schema":1}')
    value = _pool_value()
    value["items"] = []
    with pytest.raises(ReplayValidationError, match="non-empty array"):
        pool_from_value(value)


def test_replay_parameters_and_insufficient_group_components_fail_visibly():
    pool = load_pool_text(FIXTURE.read_text(encoding="utf-8"))
    for kwargs, message in [
        ({"seed": "", "heldout_fraction": 0.25, "budgets": (1,)}, "seed"),
        ({"seed": "x", "heldout_fraction": 1.0, "budgets": (1,)}, "heldout_fraction"),
        ({"seed": "x", "heldout_fraction": 0.25, "budgets": ()}, "budgets"),
        ({"seed": "x", "heldout_fraction": 0.25, "budgets": (0,)}, "budgets"),
    ]:
        with pytest.raises(ReplayValidationError, match=message):
            build_replay_report(pool, **kwargs)
    one_component = pool_from_value(
        {
            "schema": 1,
            "pool_id": "single-component",
            "items": [
                {
                    "id": "a",
                    "group_id": "same",
                    "observed_at": "2026-01-01T00:00:00Z",
                    "role_families": [],
                    "label": "unresolved",
                },
                {
                    "id": "b",
                    "group_id": "same",
                    "observed_at": "2026-01-02T00:00:00Z",
                    "role_families": [],
                    "label": "positive",
                },
            ],
        }
    )
    with pytest.raises(ReplayValidationError, match="independent day/group components"):
        build_replay_report(one_component, seed="x", heldout_fraction=0.25, budgets=(1,))


def test_zero_positive_split_reports_recall_as_null():
    value = _pool_value()
    for item in value["items"]:
        item["label"] = "negative"
    pool = pool_from_value(value)
    report = build_replay_report(pool, seed="synthetic-seed", heldout_fraction=0.25, budgets=(1,))
    for split in report["splits"].values():
        assert all(result["positive_recall"] is None for result in split["baselines"])


def test_replay_cli_emits_only_report_and_no_source_identifiers():
    script = Path(__file__).parents[1] / "tools/preselection_replay.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(FIXTURE),
            "--seed",
            "synthetic-seed",
            "--heldout-fraction",
            "0.25",
            "--budget",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "synthetic-001" not in result.stdout
    assert json.loads(result.stdout)["item_count"] == 12


def test_synthetic_yoe_truth_table_covers_required_boundaries_without_policy_code():
    cases = json.loads(YOE_FIXTURE.read_text(encoding="utf-8"))
    by_id = {case["id"]: case["expected"] for case in cases}

    assert len(by_id) == len(cases)
    assert {
        "required-two-plus",
        "required-at-least-two",
        "required-range-two-four",
        "range-zero-two",
        "range-one-three",
        "up-to-two",
        "two-preferred",
        "unstated",
        "ambiguous-two",
        "lower-yoe-alternative",
        "skill-specific-professional",
        "degree-duration",
        "unrelated-years",
        "preferred-lower-does-not-cancel",
    } <= set(by_id)
    assert by_id["required-two-plus"] == "exclude"
    assert by_id["lower-yoe-alternative"] == "not_excluded"
    assert by_id["ambiguous-two"] == "unresolved"
    assert by_id["degree-duration"] == "not_excluded"
    assert by_id["preferred-lower-does-not-cancel"] == "exclude"
