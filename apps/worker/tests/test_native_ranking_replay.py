"""Offline native20 replay boundary and provenance regression tests."""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from ats_worker.ranking.prototype import (
    RECORDED_NATIVE_ADAPTER,
    RECORDED_NATIVE_REQUESTED_MODEL,
    RECORDED_NATIVE_RESOLVED_MODEL,
    RankingReader,
    RankingStore,
    digest,
    fake_reply,
)
from tests.native_ranking_replay_demo import ReplayInputError, load_verified_native20, run_demo
from tests.test_ranking_prototype import policy, source


PRIVATE_INPUTS = os.environ.get("ATS_NATIVE20_PRIVATE_INPUTS")


def native_policy(**changes):
    native = {
        "adapter_version": RECORDED_NATIVE_ADAPTER,
        "requested_model": RECORDED_NATIVE_REQUESTED_MODEL,
        "resolved_model": RECORDED_NATIVE_RESOLVED_MODEL,
    }
    native.update(changes)
    return policy(**native)


def _private_inputs_or_skip() -> Path:
    if not PRIVATE_INPUTS:
        pytest.skip("ATS_NATIVE20_PRIVATE_INPUTS is not configured")
    path = Path(PRIVATE_INPUTS)
    if not path.is_dir():
        pytest.skip("private native20 artifacts are not present")
    return path


def _copy_replay_package(source_dir: Path, tmp_path: Path) -> Path:
    target_parent = tmp_path / "private"
    target = target_parent / "native20"
    target.mkdir(parents=True)
    for name in (
        "sources.json", "profile-binding.json", "question-pack.json",
        "domain-manifest.json", "pilot-offline-preparation.json",
        "native20-blind-proxy.json",
    ):
        shutil.copyfile(source_dir.parent / name, target_parent / name)
    for name in ("campaign-ledger.jsonl", "summary.json"):
        shutil.copyfile(source_dir / name, target / name)
    for path in source_dir.iterdir():
        if path.is_file() and path.name.startswith(("request-", "response-", "result-")):
            shutil.copyfile(path, target / path.name)
    return target


def test_native_replay_demo_uses_only_private_input_dir_and_reconciles_mcp():
    inputs = _private_inputs_or_skip()
    assert tuple(inspect.signature(run_demo).parameters) == ("inputs_dir", "campaign")
    assert inspect.signature(run_demo).parameters["campaign"].kind is inspect.Parameter.KEYWORD_ONLY
    result = run_demo(inputs)
    assert result["source_count"] == result["replayed_responses"] == 20
    assert result["live_provider_calls"] == result["network_calls"] == 0
    assert result["freshness"] == {"current": 20, "stale": 0, "absent": 0}
    assert result["succeeded"] == 20
    assert result["assessment_origin_counts"] == {"fake": 0, "recorded_native": 20}
    assert result["fake_provider"] is False
    assert result["priority_counts"] == {"low": 16, "medium": 4}
    assert result["needs_review"] == {"yes": 20, "no": 0}
    assert result["aggregate_native_values"] == {
        "domain": {
            "agentic_llm_applications": 2,
            "analysis_decision_support": 9,
            "general_software_engineering": 6,
            "mixed": 1,
            "ml_engineering": 2,
        },
        "preference": {"plausible": 4, "weak": 16},
        "relevance": {"absent": 2, "partial": 17, "supported": 1},
        "ambiguity": {"clear": 1, "review": 19},
    }
    assert result["mcp_coverage_verified"] is True
    assert result["mcp_counts"] == {"list_rows": 20, "detail_rows": 20, "description_chunks": 20}
    assert result["ranking_quality_evidence"] is False
    assert result["production_db_writes"] == 0


def test_ambiguity_arm_replay_reconciles_mcp_without_changing_priority():
    inputs = _private_inputs_or_skip().parent / "native20-ambiguity-v2"
    if not inputs.is_dir():
        pytest.skip("private ambiguity arm artifacts are not present")
    result = run_demo(inputs)
    assert result["campaign"] == "native20-ambiguity-v2"
    assert result["replayed_responses"] == result["succeeded"] == 20
    assert result["freshness"] == {"current": 20, "stale": 0, "absent": 0}
    assert result["assessment_origin_counts"] == {"fake": 0, "recorded_native": 20}
    assert result["priority_counts"] == {"low": 16, "medium": 4}
    assert result["needs_review"] == {"yes": 7, "no": 13}
    assert result["aggregate_native_values"]["ambiguity"] == {"clear": 16, "review": 4}
    assert result["mcp_counts"] == {"list_rows": 20, "detail_rows": 20, "description_chunks": 20}
    assert result["fake_provider"] is False
    assert result["prototype"] is True
    assert result["live_provider_calls"] == result["network_calls"] == result["production_db_writes"] == 0


def test_changed_native_response_body_is_rejected_before_replay(tmp_path):
    inputs = _copy_replay_package(_private_inputs_or_skip(), tmp_path)
    response = next(inputs.glob("response-*.body"))
    response.write_bytes(response.read_bytes() + b" ")
    with pytest.raises(ReplayInputError, match="response body hash mismatch"):
        load_verified_native20(inputs)


def test_changed_result_identity_is_rejected_before_replay(tmp_path):
    inputs = _copy_replay_package(_private_inputs_or_skip(), tmp_path)
    result_path = next(inputs.glob("result-*.json"))
    result = json.loads(result_path.read_text())
    result["job_id"] += 1
    result_path.write_text(json.dumps(result, separators=(",", ":")))
    with pytest.raises(ReplayInputError, match="derived result identity or value mismatch"):
        load_verified_native20(inputs)


def test_native_model_is_rejected_by_default_before_event_write(db_path):
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(ValueError, match="recorded native replay is enabled"):
            RankingStore(connection).capture(
                source(), native_policy(), now="2026-11-13T01:00:00Z",
            )
        assert connection.execute("SELECT COUNT(*) FROM job_ranking_events").fetchone()[0] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"requested_model": "typesafe/jev-1.12"},
        {"resolved_model": "typesafe/jev-1.13"},
        {"adapter_version": "fake-native-v1"},
    ],
)
def test_native_replay_requires_exact_model_and_adapter(db_path, change):
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(ValueError, match="recorded native replay is enabled"):
            RankingStore(connection, allow_native_replay=True).capture(
                source(), native_policy(**change), now="2026-11-13T01:00:00Z",
            )
        assert connection.execute("SELECT COUNT(*) FROM job_ranking_events").fetchone()[0] == 0


@pytest.mark.parametrize("allow_native_replay", [False, True])
def test_fake_origin_stays_fake_in_both_explicit_modes(db_path, allow_native_replay):
    with sqlite3.connect(db_path) as connection:
        RankingStore(connection, allow_native_replay=allow_native_replay).assess(
            source(), policy(), provider=lambda invocation: fake_reply(invocation, "high"),
            now="2026-11-13T01:00:00Z",
        )
    reader = RankingReader(db_path)
    listed = reader.list_rankings(lane="raw")
    detail = reader.get_ranking(1)
    coverage = reader.coverage()
    assert listed["items"][0]["assessment_origin"] == "fake"
    assert listed["items"][0]["fake_provider"] is True
    assert listed["fake_provider"] is True
    assert detail["assessment_origin"] == detail["source_assessment_origin"] == "fake"
    assert detail["source_snapshot"] == source()
    assert "assessment_origin" not in detail["source_snapshot"]
    assert detail["source_snapshot_sha256"] == digest(detail["source_snapshot"])
    assert detail["ranking"]["binding"]["source_sha256"] == detail["source_snapshot_sha256"]
    assert detail["fake_provider"] is True
    assert detail["ranking"]["assessment_origin"] == "fake"
    assert detail["ranking"]["completed_at_basis"] == "fake_assessment"
    assert coverage["assessment_origin_counts"] == {"fake": 1, "recorded_native": 0}
    assert coverage["fake_provider"] is True


def test_native_replay_completion_records_ingestion_time(db_path):
    captured = source()
    replay_time = "2026-11-14T03:00:00Z"
    with sqlite3.connect(db_path) as connection:
        RankingStore(connection, allow_native_replay=True).assess(
            captured, native_policy(), provider=lambda invocation: fake_reply(invocation, "high"),
            now=replay_time,
        )
    detail = RankingReader(db_path).get_ranking(captured["job_id"])
    assert detail["source_snapshot"] == captured
    assert detail["ranking"]["source_captured_time"] == captured["captured_time"]
    assert detail["ranking"]["completed_at"] == detail["latest_attempt"]["at"] == replay_time
    assert detail["ranking"]["completed_at"] != captured["captured_time"]
    assert detail["ranking"]["completed_at_basis"] == "replay_ingestion"


@pytest.mark.parametrize("bad_identity", ["job", "boolean_job", "source", "binding", "attempt", "model", "schema"])
def test_native_mode_keeps_all_p0_reply_identity_and_schema_guards(db_path, bad_identity):
    with sqlite3.connect(db_path) as connection:
        store = RankingStore(connection, allow_native_replay=True)

        def malformed(invocation):
            reply = fake_reply(invocation, "high")
            if bad_identity == "job":
                reply["job_id"] = 99
            elif bad_identity == "boolean_job":
                reply["job_id"] = True
            elif bad_identity == "source":
                reply["source_sha256"] = "f" * 64
            elif bad_identity == "binding":
                reply["binding_sha256"] = "f" * 64
            elif bad_identity == "attempt":
                reply["attempt_id"] = "wrong-attempt"
            elif bad_identity == "model":
                reply["response"]["model"] = "wrong-model"
            elif bad_identity == "schema":
                reply["response"]["answers"]["domain"]["choice"] = "invalid-choice"
            return reply

        store.assess(
            source(), native_policy(), provider=malformed,
            now="2026-11-13T01:00:00Z",
        )
    detail = RankingReader(db_path).get_ranking(1)
    assert detail["ranking"] is None
    assert detail["latest_attempt"]["state"] == "failed"
    assert detail["assessment_origin"] == "recorded_native"
    assert detail["source_assessment_origin"] == "recorded_native"
    assert detail["fake_provider"] is False
