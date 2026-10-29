import json
from pathlib import Path
import subprocess
import sys

import pytest

from ats_worker.preselection.replay import (
    ReplayValidationError,
    _recency_order,
    _role_coverage_order,
    _stable_split,
    build_snapshot_manifest,
    build_replay_report,
    build_snapshot_replay_report,
    load_pool_text,
    load_snapshot_text,
    pool_from_value,
    snapshot_from_value,
)
from ats_worker.preselection.profile import profile_from_value, render_profile


FIXTURE = Path(__file__).parent / "fixtures/preselection_pool.synthetic.json"
SNAPSHOT_FIXTURE = Path(__file__).parent / "fixtures/preselection_snapshot.synthetic.json"
YOE_FIXTURE = Path(__file__).parent / "fixtures/preselection_yoe_boundaries.synthetic.json"


def _pool_value():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _snapshot_value():
    return json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))


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
        for result in split["baselines"]:
            role_metrics = result["role_family_metrics"]
            assert role_metrics
            assert all(key.startswith("role_") for key in role_metrics)
            assert all(
                set(metrics["label_counts"]) == {"positive", "negative", "unresolved"}
                for metrics in role_metrics.values()
            )
            assert all(
                metrics["label_coverage"]
                == pytest.approx(
                    (metrics["label_counts"]["positive"] + metrics["label_counts"]["negative"])
                    / metrics["pool_items"]
                )
                for metrics in role_metrics.values()
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


def test_daily_baseline_ties_use_stable_item_order_and_repeat_exactly():
    value = {
        "schema": 1,
        "pool_id": "daily-tie-order",
        "items": [
            {
                "id": f"tie-{day}-{rank}",
                "group_id": f"group-{day}-{rank}",
                "observed_at": f"2026-03-{day:02d}T12:00:00Z",
                "role_families": ["engineering"],
                "label": "positive",
            }
            for day in range(1, 5)
            for rank in ("c", "a", "b")
        ],
    }
    pool = pool_from_value(value)
    for day in range(1, 5):
        daily_items = [item for item in pool.items if item.utc_day == f"2026-03-{day:02d}"]
        assert _recency_order(daily_items)[0].id == f"tie-{day}-a"
        assert _role_coverage_order(daily_items)[0].id == f"tie-{day}-a"

    first = build_replay_report(pool, seed="daily-tie", heldout_fraction=0.5, budgets=(1,))
    second = build_replay_report(pool, seed="daily-tie", heldout_fraction=0.5, budgets=(1,))
    assert first == second
    for split in first["splits"].values():
        assert split["days"] == 2
        assert all(row["selected"] == 2 for row in split["baselines"])


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
        ({"seed": "\udcff", "heldout_fraction": 0.25, "budgets": (1,)}, "seed"),
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
    report = json.loads(result.stdout)
    assert report["item_count"] == 12
    assert report["evidence_status"] == "INCONCLUSIVE"
    assert report["acceptance_decision"] == "not_recorded"
    assert "legacy pool has no full source payloads" in report["evidence_limitations"]


def test_full_snapshot_cli_validates_complete_daily_pools_and_emits_aggregate_provenance():
    script = Path(__file__).parents[1] / "tools/preselection_replay.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(SNAPSHOT_FIXTURE),
            "--snapshot",
            "--seed",
            "synthetic-seed",
            "--heldout-fraction",
            "0.5",
            "--budget",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    encoded = json.dumps(report, sort_keys=True)

    assert report["evidence_status"] == "INPUTS_VALIDATED"
    assert report["acceptance_decision"] == "not_recorded"
    assert report["provider_calls"] == 0
    assert report["provenance"]["source_items"] == 8
    assert report["provenance"]["utc_days"] == 4
    assert set(report["provenance"]["versions"]) == {
        "frozen_input",
        "profile_schema",
        "profile_renderer",
        "source_pool_schema",
        "replay_algorithm",
    }
    for digest in (
        "profile_sha256",
        "rendered_context_sha256",
        "source_pool_sha256",
        "snapshot_manifest_sha256",
        "daily_membership_sha256",
    ):
        assert len(report["provenance"][digest]) == 64
    for split in report["splits"].values():
        assert split["days"] == 2
        assert all(row["budget_scope"] == "per_utc_day" for row in split["baselines"])
        assert all(row["selected"] == 2 for row in split["baselines"])
        assert all(row["positive_total"] == 2 for row in split["baselines"])
        assert all(row["positive_selected"] == 2 for row in split["baselines"])
        assert all(row["positive_recall"] == 1.0 for row in split["baselines"])
    for private_value in (
        "synthetic-positive-01",
        "synthetic-group-positive-01",
        "Fictional Company 01",
        "no real employer or vacancy",
        "production ownership stayed with the team",
    ):
        assert private_value not in encoded


def test_full_snapshot_allows_nullable_normalized_source_fields():
    value = _snapshot_value()
    for row in value["source_pool"]["items"]:
        row["source_payload"]["location"] = None
        row["source_payload"]["posted_at"] = None
    value["manifest"] = build_snapshot_manifest(
        value["profile"], value["rendered_context"], value["source_pool"]
    )

    snapshot = snapshot_from_value(value)
    assert len(snapshot.pool.items) == 8


def test_full_snapshot_requires_posted_at_even_if_the_manifest_is_recomputed():
    value = _snapshot_value()
    for row in value["source_pool"]["items"]:
        row["source_payload"].pop("posted_at")

    with pytest.raises(ReplayValidationError, match="missing required source fields"):
        build_snapshot_manifest(value["profile"], value["rendered_context"], value["source_pool"])


def test_snapshot_cli_never_emits_untrusted_role_labels(tmp_path):
    value = _snapshot_value()
    private_role = "PRIVATE_ROLE=alice@example.invalid"
    for row in value["source_pool"]["items"]:
        row["role_families"] = [private_role]
    value["manifest"] = build_snapshot_manifest(
        value["profile"], value["rendered_context"], value["source_pool"]
    )
    path = tmp_path / "synthetic-role-snapshot.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    script = Path(__file__).parents[1] / "tools/preselection_replay.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(path),
            "--snapshot",
            "--seed",
            "synthetic-seed",
            "--heldout-fraction",
            "0.5",
            "--budget",
            "1",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert private_role not in result.stdout
    assert set(report["splits"]["development"]["baselines"][0]["role_family_metrics"]) == {
        "role_1"
    }


def test_snapshot_cli_reports_malformed_unicode_as_a_bounded_input_error(tmp_path):
    value = _snapshot_value()
    value["source_pool"]["items"][0]["source_payload"]["extra"] = "\ud800"
    path = tmp_path / "synthetic-invalid-unicode.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    script = Path(__file__).parents[1] / "tools/preselection_replay.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(path),
            "--snapshot",
            "--seed",
            "synthetic-seed",
            "--heldout-fraction",
            "0.5",
            "--budget",
            "1",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "cannot replay frozen input" in result.stderr
    assert "UnicodeEncodeError" not in result.stderr


def test_snapshot_cli_reports_malformed_seed_unicode_as_a_bounded_input_error():
    script = Path(__file__).parents[1] / "tools/preselection_replay.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(SNAPSHOT_FIXTURE),
            "--snapshot",
            "--seed",
            "\udcff",
            "--heldout-fraction",
            "0.5",
            "--budget",
            "1",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "cannot replay frozen input: seed" in result.stderr
    assert "UnicodeEncodeError" not in result.stderr


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["source_pool"]["items"].pop(), "hashes do not match"),
        (
            lambda value: value["source_pool"]["items"].__setitem__(
                slice(None),
                [
                    item
                    for item in value["source_pool"]["items"]
                    if not item["observed_at"].startswith("2026-02-01")
                ],
            ),
            "hashes do not match",
        ),
        (
            lambda value: value["source_pool"]["items"][0]["source_payload"].update(
                description="changed fictional payload"
            ),
            "hashes do not match",
        ),
        (
            lambda value: value["source_pool"]["items"][1].update(
                id=value["source_pool"]["items"][0]["id"]
            ),
            "IDs must be unique",
        ),
        (
            lambda value: value["source_pool"]["items"][0]["source_payload"].pop("description"),
            "missing required source fields",
        ),
        (
            lambda value: value.update(rendered_context=value["rendered_context"] + "changed"),
            "does not match the candidate profile renderer",
        ),
        (
            lambda value: value["manifest"]["versions"].update(replay_algorithm="unknown"),
            "versions do not match",
        ),
        (
            lambda value: value["manifest"]["versions"].update(profile_schema=True),
            "versions do not match",
        ),
        (
            lambda value: value["manifest"]["daily_pools"][0]["item_ids"].reverse(),
            "daily membership does not match",
        ),
    ],
)
def test_snapshot_rejects_actual_input_or_manifest_tampering(mutate, message):
    value = _snapshot_value()
    mutate(value)
    with pytest.raises(ReplayValidationError, match=message):
        snapshot_from_value(value)


def test_snapshot_rejects_profile_change_even_when_context_is_rerendered():
    value = _snapshot_value()
    value["profile"]["background"][0]["text"] += " Revised."
    value["rendered_context"] = render_profile(profile_from_value(value["profile"]))

    with pytest.raises(ReplayValidationError, match="hashes do not match"):
        snapshot_from_value(value)


def test_unknown_labels_remain_in_pool_and_make_recall_inconclusive_without_denominator_shrink():
    value = _snapshot_value()
    unresolved_id = value["source_pool"]["items"][0]["id"]
    value["source_pool"]["items"][0]["label"] = "unresolved"
    value["manifest"] = build_snapshot_manifest(
        value["profile"], value["rendered_context"], value["source_pool"]
    )
    snapshot = load_snapshot_text(json.dumps(value))
    report = build_snapshot_replay_report(
        snapshot, seed="synthetic-seed", heldout_fraction=0.5, budgets=(1,)
    )
    assignments, _ = _stable_split(snapshot.pool, "synthetic-seed", 0.5)
    affected = report["splits"][assignments[unresolved_id]]

    assert report["evidence_status"] == "INCONCLUSIVE"
    assert report["acceptance_decision"] == "not_recorded"
    assert affected["items"] == 4
    assert affected["label_counts"]["unresolved"] == 1
    assert affected["label_coverage"] == 0.75
    assert all(row["positive_recall"] is None for row in affected["baselines"])
    assert all(
        metrics["positive_recall"] is None
        for row in affected["baselines"]
        for metrics in row["role_family_metrics"].values()
    )
    assert "PASS" not in json.dumps(report)


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
    assert by_id["lower-yoe-alternative"] == "do_not_exclude"
    assert by_id["degree-duration"] == "do_not_exclude"
    assert by_id["preferred-lower-does-not-cancel"] == "exclude"


def test_k_is_allocated_once_per_complete_utc_day_inside_each_split():
    value = {
        "schema": 1,
        "pool_id": "four-day-daily-allocation",
        "items": [
            {
                "id": f"day-{day}",
                "group_id": f"unique-group-{day}",
                "observed_at": f"2026-02-{day:02d}T12:00:00Z",
                "role_families": ["engineering"],
                "label": "positive",
            }
            for day in range(1, 5)
        ],
    }
    pool = pool_from_value(value)
    report = build_replay_report(pool, seed="x", heldout_fraction=0.5, budgets=(1,))

    for split in report["splits"].values():
        assert split["days"] == 2
        for result in split["baselines"]:
            assert result["budget_scope"] == "per_utc_day"
            assert result["selected"] == 2
            assert result["positive_total"] == 2
            assert result["positive_selected"] == 2
            assert result["positive_recall"] == 1.0
