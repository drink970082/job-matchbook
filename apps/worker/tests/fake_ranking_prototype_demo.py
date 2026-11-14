"""Run a private, fake-provider ranking mechanics demo against a temporary DB."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from mcp import Client
from ats_worker.mcp.read_repository import ReadOnlyATSRepository
from ats_worker.mcp.server import create_server
from ats_worker.ranking.prototype import RankingReader, RankingStore, canonical, fake_reply
from tests._helpers import bootstrap_db


_EXPECTED = {
    "sources.json": "996f198e4e799a75a648ae25ab3fe261f84bfea03170bf28c3978846e4074327",
    "profile-binding.json": "bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986",
    "domain-manifest.json": "c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c",
    "question-pack.json": "b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7",
}
_EXPECTED_CONTEXT = "e1741d3349ff8e0e3016e4abe135eb38c206dde98ad1d47e2471410308f6270f"
_TIERS = ("high", "medium", "low", None)
_NOW = "2026-11-13T18:54:19Z"


async def _exercise_mcp(db_path: str, sources: list[dict]) -> tuple[dict, dict, bool]:
    reader = RankingReader(db_path)
    server = create_server(ReadOnlyATSRepository(db_path), ranking_reader=reader)
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.call_tool("list_job_rankings", {"lane": "raw", "limit": 100})
        if listed.is_error:
            raise RuntimeError("in-process ranking list failed")
        page = listed.structured_content
        coverage = await client.call_tool("get_job_ranking_coverage", {})
        if coverage.is_error:
            raise RuntimeError("in-process ranking coverage failed")

        source_text = sources[0]["description"]
        chunks = []
        offset = 0
        while True:
            detail_result = await client.call_tool("get_job_ranking", {
                "job_id": sources[0]["job_id"],
                "description_offset": offset,
                "description_limit": 12_000,
            })
            if detail_result.is_error:
                raise RuntimeError("in-process ranking detail failed")
            detail = detail_result.structured_content
            chunks.append(detail["source_description_chunk"])
            if not detail["has_more"]:
                break
            offset = detail["next_offset"]
        roundtrip = (
            len(page["items"]) == len(sources)
            and "description" not in page["items"][0]
            and all(source["description"] not in json.dumps(page) for source in sources)
        )
        roundtrip = roundtrip and "profile_sha256" not in json.dumps(detail)
        roundtrip = roundtrip and "raw_native" not in json.dumps(detail)
        roundtrip = roundtrip and "".join(chunks) == source_text
        return page, coverage.structured_content, roundtrip


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(inputs: Path, name: str):
    raw = (inputs / name).read_bytes()
    if name in _EXPECTED and _sha(raw) != _EXPECTED[name]:
        raise ValueError("approved private prototype input hash mismatch")
    return json.loads(raw)


def run_demo(inputs: Path) -> dict:
    sources = _read(inputs, "sources.json")
    profile_binding = _read(inputs, "profile-binding.json")
    domain_manifest = _read(inputs, "domain-manifest.json")
    question_pack = _read(inputs, "question-pack.json")
    if len(sources) != 20 or profile_binding.get("domains") != domain_manifest:
        raise ValueError("approved private prototype input shape mismatch")
    context_binding = {
        "schema": "ranking-question-context-domain-v1",
        "question_pack": question_pack,
        "domain_manifest": domain_manifest,
    }
    if _sha(canonical(context_binding).encode("utf-8")) != _EXPECTED_CONTEXT:
        raise ValueError("approved question/domain input hash mismatch")
    policy = {
        "profile_sha256": _sha(canonical(profile_binding).encode("utf-8")),
        "question_context_domain_sha256": _EXPECTED_CONTEXT,
        "question_set": question_pack,
        "rubric_version": question_pack["version"],
        "projection_version": "ranking-projection-v1",
        "adapter_version": "fake-native-prototype-v1",
        "requested_model": "fake-jev-p3-v1",
        "resolved_model": "fake-jev-p3-v1",
    }

    with tempfile.TemporaryDirectory(prefix="jev-p3-fake-demo-") as temporary:
        db_path = bootstrap_db(Path(temporary) / "demo.db")
        calls = 0
        with sqlite3.connect(db_path) as connection:
            store = RankingStore(connection)
            for index, source in enumerate(sources):
                tier = _TIERS[index % len(_TIERS)]

                def provider(invocation, selected=tier):
                    nonlocal calls
                    calls += 1
                    return fake_reply(invocation, selected)

                store.assess(source, policy, provider=provider, now=_NOW)

            cache = store.assess(
                sources[0], policy,
                provider=lambda _: (_ for _ in ()).throw(AssertionError("cache miss")), now=_NOW,
            )

        page, coverage, mcp_roundtrip = asyncio.run(_exercise_mcp(db_path, sources))
        tiers = Counter(
            "unknown" if item["priority"] is None else item["priority"]
            for item in page["items"]
        )
        if not mcp_roundtrip:
            raise AssertionError("in-process MCP did not preserve source/detail privacy contract")
        return {
            "scope": "existing-inventory development data",
            "scenario": "fake-provider prototype mechanics only",
            "source_count": len(sources),
            "fake_provider_invocations": calls,
            "fake_priority_counts": {key: tiers[key] for key in ("high", "medium", "low", "unknown")},
            "cache_hit_verified": cache["cache_hit"],
            "coverage_freshness": coverage["freshness"],
            "coverage_latest_attempt": coverage["latest_attempt"],
            "mcp_roundtrip_verified": mcp_roundtrip,
            "production_db_writes": 0,
            "ranking_quality_evidence": False,
            "prototype": True,
            "fake_provider": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", required=True, type=Path,
                        help="private jev-ranking-p3-dev-v1 input directory")
    args = parser.parse_args()
    print(json.dumps(run_demo(args.inputs_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
