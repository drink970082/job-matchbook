"""Replay the frozen native20 responses through the isolated P3 prototype.

The CLI accepts a private artifact directory and an optional fixed campaign. The script
verifies its fixed input manifest, hash-chained campaign ledger, exact requests,
responses and derived result files before opening a temporary fixture database.
It makes no provider or network calls and prints aggregate counts only.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

from ats_worker.ranking.native import jev_question_set_from_value, validate_jev_response
from ats_worker.ranking.prototype import (
    RECORDED_NATIVE_ADAPTER,
    RECORDED_NATIVE_REQUESTED_MODEL,
    RECORDED_NATIVE_RESOLVED_MODEL,
    RankingReader,
    RankingStore,
    canonical,
    digest,
)


CAMPAIGN_NATIVE20 = "native20"
CAMPAIGN_AMBIGUITY_V2 = "native20-ambiguity-v2"
BASE_P0_HASHES = {
    "sources.json": "996f198e4e799a75a648ae25ab3fe261f84bfea03170bf28c3978846e4074327",
    "profile-binding.json": "bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986",
    "domain-manifest.json": "c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c",
}
CAMPAIGN_PROOFS = {
    CAMPAIGN_NATIVE20: {
        "input_hashes": {
            **BASE_P0_HASHES,
            "question-pack.json": "b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7",
            "pilot-offline-preparation.json": "367beef9b9da05f22db9d3fdd3705bcb66ac2558f78af2851ff202e4f87669af",
        },
        "proxy_hashes": {
            "native20-blind-proxy.json": "a056e1a9f1416f5ce24e202199100c2d72327665d4760efdf6b2f18b3b981e33",
        },
        "ledger_sha256": "2a66b07130e2e5d7d47ff409c0f0259acfd05cf3806fe31d83c338e28ab25d05",
        "summary_sha256": "3ff35d30cf161070c314b31b19410111d3f497ed71cbcd28ca281ea8e57f4845",
        "result_manifest_sha256": "2d4587fc735bf04a22f787f994ffb02381139fd7e2e3c43c69dc3bc2d17e9a79",
        "settled_usd": "0.003670296",
        "carry_attempts": 1744,
        "carry_usd": "0.568324876",
        "parent_ledger_sha256": None,
    },
    CAMPAIGN_AMBIGUITY_V2: {
        "input_hashes": {
            **BASE_P0_HASHES,
            "question-pack.json": "0bcbb9eebb28a98959baed4e1fc6776b278c82cc88511100ab86a431d539c978",
            "pilot-offline-preparation.json": "5d7365cba218776700f0c90bc63c6effff6be3d68699a63595a3986249afe430",
            "arm-manifest.json": "97a7149e8438232bb700b873bf1cd85f63da15c0a7b081ce09ba9b3e17dd33b5",
        },
        "proxy_hashes": {
            "native20-blind-proxy.json": "a056e1a9f1416f5ce24e202199100c2d72327665d4760efdf6b2f18b3b981e33",
            "native20-rubric-proxy.json": "6ac37f58e152dd2e5e614b6f56c4cd23e9aefa00eb7b910c0d601a9d2504cec7",
        },
        "ledger_sha256": "51a68b6006471d19a9f2341ec937ff4223b1df2409cc59f97b3053c31f5f56d6",
        "summary_sha256": "1c3f31637edb75781df512ecc28e773d04ffb31c44ef814bbe5e2ed72c8c9a8d",
        "result_manifest_sha256": "2908d9f846dc991c0c86fc11f1d1ca79367f3aafa31628e502e405b6a31af205",
        "settled_usd": "0.003771096",
        "carry_attempts": 1764,
        "carry_usd": "0.571995172",
        "parent_ledger_sha256": "2a66b07130e2e5d7d47ff409c0f0259acfd05cf3806fe31d83c338e28ab25d05",
        "parent_question_pack_sha256": "b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7",
    },
}
NATIVE_PARSER_SHA256 = "51a0860d959ac792003cc209d85df34979d7e12bd1b4b95f905d889ceaff0acd"
EXPECTED_JOBS = 20
PRIVATE_RANKING_IDENTITIES = {
    "raw_native", "raw_response", "raw_response_sha256", "response_sha256",
    "request_sha256", "request_body_sha256", "response_body_sha256",
}


class ReplayInputError(ValueError):
    """A required private replay artifact is missing or inconsistent."""


def _fail(reason: str) -> None:
    raise ReplayInputError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _no_duplicate_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("nonfinite JSON number")


def _read_regular(path: Path, *, max_bytes: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            _fail("required artifact is not a regular file")
        raw = path.read_bytes()
    except ReplayInputError:
        raise
    except OSError:
        _fail("required artifact cannot be read")
    if len(raw) > max_bytes:
        _fail("artifact exceeds its fixed size bound")
    return raw


def _parse(raw: bytes) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_no_duplicate_members,
            parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        _fail("artifact contains invalid JSON")


def _read_json(path: Path, *, max_bytes: int) -> tuple[bytes, Any]:
    raw = _read_regular(path, max_bytes=max_bytes)
    return raw, _parse(raw)


def _same(actual: Any, expected: Any, reason: str) -> None:
    if actual != expected:
        _fail(reason)


def _strict_decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        _fail("invalid recorded charge")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        _fail("invalid recorded charge")
    if not amount.is_finite() or amount < 0:
        _fail("invalid recorded charge")
    return amount


def _event_chain(ledger_raw: bytes, summary: dict[str, Any], *, expected_ledger_sha256: str) -> list[dict[str, Any]]:
    if _sha(ledger_raw) != expected_ledger_sha256:
        _fail("campaign ledger hash mismatch")
    events = []
    previous = None
    try:
        lines = ledger_raw.splitlines()
        for raw_line in lines:
            event = _parse(raw_line)
            if not isinstance(event, dict) or set(event) != {"body", "event_sha256"}:
                _fail("invalid campaign event shape")
            body = event["body"]
            if not isinstance(body, dict) or body.get("previous_event_sha256") != previous:
                _fail("campaign event chain mismatch")
            event_hash = _sha(canonical(body).encode("utf-8"))
            if event["event_sha256"] != event_hash:
                _fail("campaign event hash mismatch")
            previous = event_hash
            events.append(body)
    except ReplayInputError:
        raise
    except Exception:
        _fail("invalid campaign event chain")
    if len(events) != 1 + EXPECTED_JOBS * 3:
        _fail("campaign event count mismatch")
    if not events or events[0].get("kind") != "carry":
        _fail("campaign carry event missing")
    if previous != summary.get("ledger_final_event_sha256"):
        _fail("campaign final event differs from summary")
    return events


def _canonical_request(source: dict[str, Any], profile: dict[str, Any], questions) -> bytes:
    wire_state = {
        "company": source["company"],
        "title": source["title"],
        "location": source["location"],
        "job_description": source["description"],
        "candidate_context": canonical(profile),
    }
    try:
        return canonical({
            "model": RECORDED_NATIVE_REQUESTED_MODEL,
            "state": wire_state,
            "questions": questions.wire_map(),
        }).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("cannot reproduce frozen request")


def _campaign_paths(inputs_dir: str | Path, campaign: str) -> tuple[Path, Path, Path]:
    if campaign not in CAMPAIGN_PROOFS:
        _fail("unsupported replay campaign")
    supplied = Path(inputs_dir)
    if supplied.is_symlink() or not supplied.is_dir():
        _fail("private replay input directory is invalid")
    if supplied.name in CAMPAIGN_PROOFS:
        package_root = supplied.parent
        campaign_dir = supplied if supplied.name == campaign else package_root / campaign
    else:
        package_root = supplied
        campaign_dir = package_root / campaign
    if campaign_dir.is_symlink() or not campaign_dir.is_dir():
        _fail("selected campaign directory is missing")
    frozen_dir = package_root if campaign == CAMPAIGN_NATIVE20 else campaign_dir
    return package_root, campaign_dir, frozen_dir


def _validated_values(response: Any, questions) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        assessment = validate_jev_response(
            response, questions, expected_model=RECORDED_NATIVE_RESOLVED_MODEL,
        )
    except Exception:
        _fail("recorded response fails the frozen native contract")
    values = {answer.question_id: answer.value for answer in assessment.answers}
    return values, response


def _verify_ambiguity_arm(
    package_root: Path,
    frozen: dict[str, Any],
    prep: dict[str, Any],
    proof_spec: dict[str, Any],
    proxy_hashes: dict[str, str],
):
    manifest = frozen["arm-manifest.json"]
    if not isinstance(manifest, dict):
        _fail("ambiguity arm manifest is invalid")
    _same(manifest.get("schema"), "native20-ambiguity-v2-freeze-v1", "ambiguity arm manifest schema mismatch")
    expected_files = {name: digest for name, digest in proof_spec["input_hashes"].items() if name != "arm-manifest.json"}
    _same(manifest.get("files"), expected_files, "ambiguity arm frozen input list mismatch")
    _same(manifest.get("proxies"), proxy_hashes, "ambiguity arm proxy seals mismatch")
    _same(manifest.get("parent_ledger_sha256"), proof_spec["parent_ledger_sha256"], "ambiguity arm parent ledger mismatch")
    _same(manifest.get("carry_attempts"), 1764, "ambiguity arm carry attempts mismatch")
    _same(manifest.get("carry_usd"), "0.571995172", "ambiguity arm carry amount mismatch")
    _same(manifest.get("limits"), {
        "attempts": 20, "request_bytes": 32768, "retries": 0,
        "seconds": 1200, "usd": "0.50",
    }, "ambiguity arm limits mismatch")
    _same(manifest.get("request_count"), EXPECTED_JOBS, "ambiguity arm request count mismatch")
    _same(manifest.get("request_bytes_min"), 16_387, "ambiguity arm minimum request size mismatch")
    _same(manifest.get("request_bytes_max"), 22_847, "ambiguity arm maximum request size mismatch")
    _same(manifest.get("provider_calls"), 0, "ambiguity arm freeze made provider calls")

    _same(prep.get("schema"), "native20-ambiguity-v2-offline-preparation-v1", "ambiguity arm preparation schema mismatch")
    _same(prep.get("parent_ledger_sha256"), proof_spec["parent_ledger_sha256"], "ambiguity arm preparation parent ledger mismatch")
    _same(prep.get("parent_question_pack_sha256"), proof_spec["parent_question_pack_sha256"], "ambiguity arm parent question pack mismatch")
    _same(prep.get("cumulative_attempts"), 1764, "ambiguity arm preparation attempts mismatch")
    _same(prep.get("cumulative_usd"), "0.571995172", "ambiguity arm preparation cost mismatch")
    _same(prep.get("pending"), 0, "ambiguity arm has pending prior charges")
    _same(prep.get("unknown"), 0, "ambiguity arm has unknown prior charges")
    _same(prep.get("overreserve"), 0, "ambiguity arm has overreserved prior charges")
    _same(prep.get("provider_calls"), 0, "ambiguity arm preparation made provider calls")

    parent_pack_raw = _read_regular(package_root / "question-pack.json", max_bytes=100_000)
    _same(_sha(parent_pack_raw), proof_spec["parent_question_pack_sha256"], "ambiguity arm parent question pack hash mismatch")
    parent_pack = _parse(parent_pack_raw)
    try:
        parent_questions = jev_question_set_from_value(parent_pack)
        selected_questions = jev_question_set_from_value(frozen["question-pack.json"])
    except Exception:
        _fail("ambiguity arm question pack is invalid")
    parent_ambiguity = next(question for question in parent_pack["questions"] if question["id"] == "ambiguity")
    selected_ambiguity = next(question for question in frozen["question-pack.json"]["questions"] if question["id"] == "ambiguity")
    _same(manifest.get("question_change"), {
        "before": parent_ambiguity,
        "after": selected_ambiguity,
    }, "ambiguity arm question change differs from its manifest")
    _same(
        [question for question in parent_pack["questions"] if question["id"] != "ambiguity"],
        [question for question in frozen["question-pack.json"]["questions"] if question["id"] != "ambiguity"],
        "ambiguity arm changed another question",
    )
    _same(parent_pack["version"], "ranking-v1", "baseline question pack version mismatch")
    _same(frozen["question-pack.json"]["version"], "ranking-v1-ambiguity-clarified-v1", "ambiguity arm question pack version mismatch")

    parent_ledger = _read_regular(package_root / CAMPAIGN_NATIVE20 / "campaign-ledger.jsonl", max_bytes=2_000_000)
    _same(_sha(parent_ledger), proof_spec["parent_ledger_sha256"], "ambiguity arm baseline ledger hash mismatch")
    parent_summary_raw, parent_summary = _read_json(package_root / CAMPAIGN_NATIVE20 / "summary.json", max_bytes=100_000)
    _same(_sha(parent_summary_raw), CAMPAIGN_PROOFS[CAMPAIGN_NATIVE20]["summary_sha256"], "ambiguity arm baseline summary hash mismatch")
    _same(parent_summary.get("ledger_sha256"), proof_spec["parent_ledger_sha256"], "ambiguity arm baseline summary ledger mismatch")
    closed_parent = [item for item in prep.get("closed_ledgers", []) if isinstance(item, dict) and item.get("sha256") == proof_spec["parent_ledger_sha256"]]
    if len(closed_parent) != 1 or closed_parent[0].get("last_event_sha256") != parent_summary.get("ledger_final_event_sha256"):
        _fail("ambiguity arm does not close over the baseline ledger")
    return parent_questions


def load_verified_native20(
    inputs_dir: str | Path, *, campaign: str | None = None,
) -> dict[str, Any]:
    """Verify one fixed native campaign before responses enter the store."""
    if campaign is None:
        campaign = Path(inputs_dir).name
        if campaign not in CAMPAIGN_PROOFS:
            campaign = CAMPAIGN_NATIVE20
    proof_spec = CAMPAIGN_PROOFS.get(campaign)
    if proof_spec is None:
        _fail("unsupported replay campaign")
    package_root, campaign_dir, frozen_dir = _campaign_paths(inputs_dir, campaign)
    frozen: dict[str, Any] = {}
    for name, expected_hash in proof_spec["input_hashes"].items():
        raw, value = _read_json(frozen_dir / name, max_bytes=8_000_000)
        if _sha(raw) != expected_hash:
            _fail("frozen P0 input hash mismatch")
        frozen[name] = value
    proxy_hashes = {}
    for name, expected_hash in proof_spec["proxy_hashes"].items():
        raw = _read_regular(package_root / name, max_bytes=8_000_000)
        if _sha(raw) != expected_hash:
            _fail("frozen proxy seal hash mismatch")
        proxy_hashes[name] = expected_hash

    if not isinstance(frozen["sources.json"], list) or len(frozen["sources.json"]) != EXPECTED_JOBS:
        _fail("frozen source count mismatch")
    if not isinstance(frozen["profile-binding.json"], dict):
        _fail("frozen profile binding is invalid")
    if not isinstance(frozen["domain-manifest.json"], dict):
        _fail("frozen domain manifest is invalid")
    if not isinstance(frozen["question-pack.json"], dict):
        _fail("frozen question pack is invalid")

    try:
        questions = jev_question_set_from_value(frozen["question-pack.json"])
    except Exception:
        _fail("frozen question pack is invalid")

    prep = frozen["pilot-offline-preparation.json"]
    if not isinstance(prep, dict) or not isinstance(prep.get("requests"), list) or len(prep["requests"]) != EXPECTED_JOBS:
        _fail("offline preparation proof is invalid")

    summary_raw, summary = _read_json(campaign_dir / "summary.json", max_bytes=100_000)
    if _sha(summary_raw) != proof_spec["summary_sha256"]:
        _fail("campaign summary hash mismatch")
    if not isinstance(summary, dict):
        _fail("native20 summary is invalid")
    ledger_raw = _read_regular(campaign_dir / "campaign-ledger.jsonl", max_bytes=2_000_000)
    if _sha(ledger_raw) != summary.get("ledger_sha256"):
        _fail("campaign ledger differs from summary")
    events = _event_chain(ledger_raw, summary, expected_ledger_sha256=proof_spec["ledger_sha256"])

    parser_path = Path(__file__).resolve().parents[1] / "ats_worker" / "ranking" / "native.py"
    if _sha(_read_regular(parser_path, max_bytes=300_000)) != NATIVE_PARSER_SHA256:
        _fail("native response parser differs from frozen pilot")

    # The carry event proves which approved context and local preparation were used.
    carry = events[0]
    _same(carry.get("kind"), "carry", "campaign carry event mismatch")
    frozen_bindings = {k: v for k, v in proof_spec["input_hashes"].items() if k in {
        "sources.json", "profile-binding.json", "question-pack.json", "domain-manifest.json",
    }}
    _same(carry.get("frozen_inputs"), frozen_bindings, "campaign P0 input bindings mismatch")
    _same(carry.get("offline_preparation_sha256"), proof_spec["input_hashes"]["pilot-offline-preparation.json"], "campaign preparation binding mismatch")
    _same(carry.get("blind_proxy_seal_sha256"), proof_spec["proxy_hashes"]["native20-blind-proxy.json"], "campaign blind seal binding mismatch")
    _same(carry.get("native_parser_sha256"), NATIVE_PARSER_SHA256, "campaign parser binding mismatch")
    _same(carry.get("closed_ledgers"), prep.get("closed_ledgers"), "campaign prior-ledger proof mismatch")
    _same(carry.get("historical_attempts"), proof_spec["carry_attempts"], "campaign carry attempts mismatch")
    _same(carry.get("historical_spend_usd"), proof_spec["carry_usd"], "campaign carry spend mismatch")
    _same(carry.get("limits"), {"attempts": 20, "usd": "0.50", "seconds": 1200, "request_bytes": 32768}, "campaign limits mismatch")
    parent_questions = None
    if campaign == CAMPAIGN_AMBIGUITY_V2:
        _same(carry.get("arm_manifest_sha256"), proof_spec["input_hashes"]["arm-manifest.json"], "campaign arm manifest binding mismatch")
        _same(carry.get("parent_ledger_sha256"), proof_spec["parent_ledger_sha256"], "campaign parent ledger binding mismatch")
        _same(carry.get("rubric_proxy_seal_sha256"), proxy_hashes["native20-rubric-proxy.json"], "campaign rubric proxy binding mismatch")
        parent_questions = _verify_ambiguity_arm(package_root, frozen, prep, proof_spec, proxy_hashes)

    expected_summary = {
        "status": "completed", "attempts": EXPECTED_JOBS, "settled": EXPECTED_JOBS,
        "unknown": 0, "validity": EXPECTED_JOBS,
        "settled_usd": proof_spec["settled_usd"], "pending_reserved_usd": "0E-10",
        "resolved_model": RECORDED_NATIVE_RESOLVED_MODEL,
    }
    for key, expected in expected_summary.items():
        _same(summary.get(key), expected, "native20 completion summary mismatch")

    by_kind: dict[str, dict[str, dict[str, Any]]] = {
        "reserve": {}, "response_received": {}, "settle": {},
    }
    for index, event in enumerate(events[1:]):
        expected_kind = ("reserve", "response_received", "settle")[(index % 3)]
        if event.get("kind") != expected_kind:
            _fail("campaign events are not in their recorded request order")
        reservation_id = event.get("reservation_id")
        if not isinstance(reservation_id, str) or reservation_id in by_kind[expected_kind]:
            _fail("campaign reservation identity is invalid")
        by_kind[expected_kind][reservation_id] = event

    sources = frozen["sources.json"]
    proofs = prep["requests"]
    records = []
    result_hash_manifest = []
    for source, prepared in zip(sources, proofs, strict=True):
        if not isinstance(source, dict) or not isinstance(prepared, dict):
            _fail("frozen source or request proof is invalid")
        job_id = source.get("job_id")
        if type(job_id) is not int or job_id <= 0:
            _fail("frozen source identity is invalid")
        key = str(job_id)
        source_sha = digest(source)
        request_raw_expected = _canonical_request(source, frozen["profile-binding.json"], questions)
        request_sha = _sha(request_raw_expected)
        proof = {
            "disposition": "within_local_bound",
            "job_id": job_id,
            "source_sha256": source_sha,
            "request_sha256": request_sha,
            "request_bytes": len(request_raw_expected),
        }
        if campaign == CAMPAIGN_AMBIGUITY_V2:
            parent_request_raw = _canonical_request(source, frozen["profile-binding.json"], parent_questions)
            parent_request_sha = _sha(parent_request_raw)
            _same(prepared.get("parent_request_sha256"), parent_request_sha, "arm parent request differs from baseline context")
            baseline_request = _read_regular(package_root / CAMPAIGN_NATIVE20 / f"request-{job_id}.json", max_bytes=32_768)
            if baseline_request != parent_request_raw:
                _fail("arm parent request differs from frozen baseline request")
            proof["parent_request_sha256"] = parent_request_sha
            frozen_request = _read_regular(campaign_dir / f"frozen-request-{job_id}.json", max_bytes=32_768)
            if frozen_request != request_raw_expected:
                _fail("arm frozen request differs from selected question pack")
        if set(prepared) != set(proof):
            _fail("offline request proof has unexpected fields")
        for name, expected in proof.items():
            _same(prepared.get(name), expected, "offline request proof differs from frozen inputs")

        request_raw = _read_regular(campaign_dir / f"request-{job_id}.json", max_bytes=32_768)
        if request_raw != request_raw_expected:
            _fail("recorded request differs from the exact P0 context")
        reserve = by_kind["reserve"].get(key)
        received = by_kind["response_received"].get(key)
        settled = by_kind["settle"].get(key)
        if reserve is None or received is None or settled is None:
            _fail("campaign events do not cover every frozen source")
        _same(reserve.get("binding"), proof, "campaign source or request identity mismatch")
        _same(reserve.get("profile_sha256"), proof_spec["input_hashes"]["profile-binding.json"], "campaign profile binding mismatch")
        _same(reserve.get("questions_sha256"), proof_spec["input_hashes"]["question-pack.json"], "campaign question binding mismatch")
        _same(reserve.get("domain_manifest_sha256"), proof_spec["input_hashes"]["domain-manifest.json"], "campaign domain binding mismatch")
        if received.get("status_code") != 200:
            _fail("recorded response was not successful")

        response_raw = _read_regular(campaign_dir / f"response-{job_id}.body", max_bytes=128_000)
        response_sha = _sha(response_raw)
        _same(received.get("response_sha256"), response_sha, "response body hash mismatch")
        _same(received.get("response_bytes"), len(response_raw), "response body size mismatch")
        _same(settled.get("response_sha256"), response_sha, "settlement response hash mismatch")
        _same(settled.get("status"), "settled", "response settlement status mismatch")

        response = _parse(response_raw)
        values, response = _validated_values(response, questions)
        result_raw, result = _read_json(campaign_dir / f"result-{job_id}.json", max_bytes=100_000)
        result_hash_manifest.append({"job_id": job_id, "sha256": _sha(result_raw)})
        if not isinstance(result, dict):
            _fail("derived result is invalid")
        expected_result = {
            "job_id": job_id,
            "binding": proof,
            "request_sha256": request_sha,
            "raw_response_sha256": response_sha,
            "model": RECORDED_NATIVE_RESOLVED_MODEL,
            "profile_sha256": proof_spec["input_hashes"]["profile-binding.json"],
            "question_pack_sha256": proof_spec["input_hashes"]["question-pack.json"],
            "domain_manifest_sha256": proof_spec["input_hashes"]["domain-manifest.json"],
            "native_values": values,
            "usage": settled.get("usage"),
            "cost_usd": settled.get("amount"),
        }
        for name, expected in expected_result.items():
            _same(result.get(name), expected, "derived result identity or value mismatch")
        _same(result.get("usage"), response.get("usage"), "response usage differs from derived result")
        amount = _strict_decimal(result.get("cost_usd"))
        _same(_strict_decimal(result.get("usage", {}).get("cost")), amount, "result usage and charge disagree")
        _same(_strict_decimal(settled.get("amount")), amount, "ledger settlement and result charge disagree")
        records.append({"source": source, "response": response, "values": values, "amount": amount})

    expected_ids = [str(source["job_id"]) for source in sources]
    for kind, events_by_id in by_kind.items():
        if set(events_by_id) != set(expected_ids):
            _fail("campaign event source coverage mismatch")
    expected_files = {
        f"{kind}-{source['job_id']}{suffix}"
        for source in sources
        for kind, suffix in (("request", ".json"), ("response", ".body"), ("result", ".json"))
    }
    if campaign == CAMPAIGN_AMBIGUITY_V2:
        expected_files |= {f"frozen-request-{source['job_id']}.json" for source in sources}
    actual_files = {
        path.name for path in campaign_dir.iterdir()
        if re.fullmatch(r"(?:frozen-request|request|response|result)-\d+\.(?:json|body)", path.name)
    }
    if actual_files != expected_files:
        _fail("campaign request, response or result file set changed")
    if _sha(canonical(result_hash_manifest).encode("utf-8")) != proof_spec["result_manifest_sha256"]:
        _fail("campaign derived result manifest mismatch")

    expected_aggregate = {
        question.id: dict(Counter(record["values"][question.id] for record in records))
        for question in questions.questions
    }
    _same(summary.get("aggregate_native_values"), expected_aggregate, "native20 aggregate differs from responses")
    total_cost = sum((record["amount"] for record in records), Decimal(0))
    _same(total_cost, _strict_decimal(summary.get("settled_usd")), "summary and individual charges disagree")

    native_parser_context = {
        "profile_sha256": proof_spec["input_hashes"]["profile-binding.json"],
        "question_context_domain_sha256": proof_spec["input_hashes"]["domain-manifest.json"],
        "question_set": frozen["question-pack.json"],
        "rubric_version": frozen["question-pack.json"]["version"],
        "projection_version": "ranking-projection-v1",
        "adapter_version": RECORDED_NATIVE_ADAPTER,
        "requested_model": RECORDED_NATIVE_REQUESTED_MODEL,
        "resolved_model": RECORDED_NATIVE_RESOLVED_MODEL,
    }
    # Keep the already hash-checked bytes available only in-process; never include them
    # in the result returned to the demo caller.
    return {
        "campaign": campaign, "records": records, "policy": native_parser_context,
        "expected_aggregate": expected_aggregate,
    }


def _offline_provider(records_by_job: dict[int, dict[str, Any]]):
    replayed = 0

    def provide(invocation: dict[str, Any]) -> dict[str, Any]:
        nonlocal replayed
        record = records_by_job.get(invocation.get("job_id"))
        if record is None:
            raise ValueError("no verified response for source")
        source = record["source"]
        if invocation.get("source_sha256") != digest(source):
            raise ValueError("invocation source differs from verified response")
        if invocation.get("question_set") != record["question_set"]:
            raise ValueError("invocation question set differs from verified response")
        if invocation.get("resolved_model") != RECORDED_NATIVE_RESOLVED_MODEL:
            raise ValueError("invocation model differs from verified response")
        replayed += 1
        return {
            key: invocation[key]
            for key in ("job_id", "source_sha256", "binding_sha256", "attempt_id")
        } | {"response": record["response"]}

    provide.replayed_count = lambda: replayed
    return provide


async def _verify_mcp(path: str, expected: dict[str, Any]) -> dict[str, Any]:
    from mcp.client import Client
    from ats_worker.mcp.read_repository import ReadOnlyATSRepository
    from ats_worker.mcp.server import create_server

    ordinary = create_server(ReadOnlyATSRepository(path))
    server = create_server(ReadOnlyATSRepository(path), ranking_reader=RankingReader(path))
    async with Client(ordinary, raise_exceptions=True) as ordinary_client:
        standard_names = {tool.name for tool in (await ordinary_client.list_tools()).tools}
    async with Client(server, raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        if len(standard_names) != 10 or names != standard_names | {
            "list_job_rankings", "get_job_ranking", "get_job_ranking_coverage",
        }:
            _fail("optional MCP tool set changed")
        listed = (await client.call_tool("list_job_rankings", {"lane": "raw", "limit": 100})).structured_content
        items = listed["items"]
        if len(items) != EXPECTED_JOBS or listed["next_cursor"] is not None:
            _fail("MCP list does not cover all replayed sources")
        if listed["assessment_origin"] != "recorded_native" or listed["fake_provider"] is not False:
            _fail("MCP list origin does not identify recorded native results")
        if any(item["assessment_origin"] != "recorded_native" or item["fake_provider"] is not False for item in items):
            _fail("MCP list contains inaccurate provider provenance")
        if any(item["freshness"] != "current" for item in items):
            _fail("MCP list contains a non-current replay")

        native_counts: dict[str, Counter] = {key: Counter() for key in expected["expected_aggregate"]}
        chunk_count = 0
        detail_count = 0
        expected_by_id = {record["source"]["job_id"]: record for record in expected["records"]}
        for item in items:
            job_id = item["job_id"]
            record = expected_by_id.get(job_id)
            if record is None:
                _fail("MCP list contains an unknown source")
            first = (await client.call_tool("get_job_ranking", {
                "job_id": job_id, "description_offset": 0, "description_limit": 16_000,
            })).structured_content
            detail_count += 1
            if (first["assessment_origin"] != "recorded_native"
                    or first["source_assessment_origin"] != "recorded_native"
                    or first["fake_provider"] is not False
                    or first["freshness"] != "current"):
                _fail("MCP detail provenance or freshness is invalid")
            if "assessment_origin" in first["source_snapshot"]:
                _fail("MCP source snapshot contains non-source provenance fields")
            if first["source_snapshot"].get("description") is not None:
                _fail("MCP detail returned an unchunked source description")
            ranking = first["ranking"]
            if ranking is None or ranking.get("assessment_origin") != "recorded_native" or ranking.get("fake_provider") is not False:
                _fail("MCP detail ranking origin is invalid")
            if (ranking.get("completed_at_basis") != "replay_ingestion"
                    or ranking.get("completed_at") == record["source"]["captured_time"]):
                _fail("MCP replay completion time does not identify replay ingestion")
            if PRIVATE_RANKING_IDENTITIES.intersection(ranking):
                _fail("MCP detail contains a private body identity")
            for question_id, value in ranking["native_values"].items():
                native_counts[question_id][value] += 1

            source_text = [first["source_description_chunk"]]
            chunk_count += 1
            offset = first["next_offset"]
            while first["has_more"]:
                first = (await client.call_tool("get_job_ranking", {
                    "job_id": job_id, "description_offset": offset, "description_limit": 16_000,
                })).structured_content
                source_text.append(first["source_description_chunk"])
                chunk_count += 1
                offset = first["next_offset"]
            if "".join(source_text) != record["source"]["description"]:
                _fail("MCP source chunks do not reconstruct the captured description")

        _same(
            {question: dict(counts) for question, counts in native_counts.items()},
            expected["expected_aggregate"],
            "MCP native values differ from verified response aggregate",
        )
        coverage = (await client.call_tool("get_job_ranking_coverage", {})).structured_content
        if coverage["freshness"] != {"current": EXPECTED_JOBS, "stale": 0, "absent": 0}:
            _fail("MCP coverage freshness does not reconcile")
        if coverage["assessment_origin_counts"] != {"fake": 0, "recorded_native": EXPECTED_JOBS}:
            _fail("MCP coverage provenance does not reconcile")
        if coverage["fake_provider"] is not False or coverage["assessment_origin"] != "recorded_native":
            _fail("MCP coverage provider provenance is invalid")
        return {"list_rows": len(items), "detail_rows": detail_count, "description_chunks": chunk_count}


def run_demo(inputs_dir: str | Path, *, campaign: str | None = None) -> dict[str, Any]:
    """Run the validated replay in a fixture database and return aggregate counts only."""
    verified = load_verified_native20(inputs_dir, campaign=campaign)
    with tempfile.TemporaryDirectory(prefix="native-ranking-replay-") as temporary:
        from tests._helpers import bootstrap_db

        database = Path(temporary) / "applications.db"
        bootstrap_db(database)
        if database.resolve().parent != Path(temporary).resolve():
            _fail("temporary database escaped its fixture directory")
        records_by_job = {}
        for record in verified["records"]:
            job_id = record["source"]["job_id"]
            records_by_job[job_id] = {**record, "question_set": verified["policy"]["question_set"]}
        provider = _offline_provider(records_by_job)
        with sqlite3.connect(database) as connection:
            store = RankingStore(connection, allow_native_replay=True)
            for record in verified["records"]:
                store.assess(
                    record["source"], verified["policy"], provider=provider,
                    now=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                )

        reader = RankingReader(database)
        coverage = reader.coverage()
        if coverage["freshness"] != {"current": EXPECTED_JOBS, "stale": 0, "absent": 0}:
            _fail("replay database freshness does not reconcile")
        if coverage["latest_attempt"]["succeeded"] != EXPECTED_JOBS:
            _fail("replay database success count does not reconcile")
        if coverage["assessment_origin_counts"] != {"fake": 0, "recorded_native": EXPECTED_JOBS}:
            _fail("replay database provenance does not reconcile")
        if provider.replayed_count() != EXPECTED_JOBS:
            _fail("not every verified response was replayed exactly once")

        rows = reader.list_rankings(lane="raw", limit=100)["items"]
        priority_counts = Counter(row["priority"] or "unknown" for row in rows)
        review_count = sum(row["needs_review"] for row in rows)
        projected = {question: Counter() for question in verified["expected_aggregate"]}
        for record in verified["records"]:
            detail = reader.get_ranking(record["source"]["job_id"])
            if detail["fake_provider"] is not False or detail["assessment_origin"] != "recorded_native":
                _fail("replayed record origin is invalid")
            for question_id, value in detail["ranking"]["native_values"].items():
                projected[question_id][value] += 1
        _same(
            {question: dict(counts) for question, counts in projected.items()},
            verified["expected_aggregate"],
            "prototype replay changed native values",
        )

        mcp = asyncio.run(_verify_mcp(str(database), verified))
        return {
            "campaign": verified["campaign"],
            "source_count": EXPECTED_JOBS,
            "replayed_responses": provider.replayed_count(),
            "live_provider_calls": 0,
            "network_calls": 0,
            "freshness": dict(coverage["freshness"]),
            "succeeded": coverage["latest_attempt"]["succeeded"],
            "assessment_origin_counts": coverage["assessment_origin_counts"],
            "priority_counts": dict(priority_counts),
            "needs_review": {"yes": review_count, "no": EXPECTED_JOBS - review_count},
            "aggregate_native_values": verified["expected_aggregate"],
            "mcp_coverage_verified": True,
            "mcp_counts": mcp,
            "fake_provider": False,
            "prototype": True,
            "ranking_quality_evidence": False,
            "production_db_writes": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_inputs_dir", type=Path)
    parser.add_argument("--campaign", choices=tuple(CAMPAIGN_PROOFS))
    args = parser.parse_args()
    print(json.dumps(run_demo(args.private_inputs_dir, campaign=args.campaign), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
