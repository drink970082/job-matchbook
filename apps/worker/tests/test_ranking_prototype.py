"""Isolated P3 mechanics; fake tiers are not ranking-quality evidence."""
import json
import sqlite3
import pytest
from ats_worker.ranking.prototype import RankingStore, RankingReader, fake_reply


def source(job_id=1, **changes):
    return {"schema": "ranking-source-v1", "job_id": job_id, "company": "Example", "title": "Engineer", "location": "New York", "description": "Build compilers.", "source_url": "https://example.invalid/1", "publication_time": "2026-11-01", "captured_time": "2026-11-13T00:00:00Z", "source_revision": 1, **changes}


def policy(**changes):
    choices = {"domain": {"compiler": "Compiler work", "mixed": "Mixed", "unknown": "Unknown"}, "preference": {v: v for v in ("strong", "plausible", "weak", "unknown")}, "relevance": {v: v for v in ("supported", "partial", "absent", "unknown")}, "ambiguity": {v: v for v in ("clear", "review")}}
    return {"profile_sha256": "a" * 64, "question_context_domain_sha256": "b" * 64, "question_set": {"version": "ranking-v1", "questions": [{"id": k, "type": "choice", "instructions": "Synthetic question", "criteria": v} for k, v in choices.items()]}, "rubric_version": "ranking-v1", "projection_version": "ranking-projection-v1", "adapter_version": "fake-native-v1", "requested_model": "fake-jev-p3-v1", "resolved_model": "fake-jev-p3-v1", **changes}


def test_projection_cache_and_privacy(db_path):
    store, reader = RankingStore(sqlite3.connect(db_path)), RankingReader(db_path)
    calls = []
    for i, tier in enumerate(("high", "medium", "low", None), 1):
        def provider(inv, tier=tier):
            calls.append(inv["job_id"]); return fake_reply(inv, tier)
        store.assess(source(i), policy(), provider=provider, now="2026-11-13T01:00:00Z")
    store.assess(source(), policy(), provider=lambda _: pytest.fail("cache must not call"), now="2026-11-13T02:00:00Z")
    page = reader.list_rankings(lane="raw")
    assert [r["priority"] for r in page["items"]] == ["high", "medium", "low", None]
    assert reader.coverage()["freshness"] == {"current": 4, "stale": 0, "absent": 0}
    assert reader.list_rankings(priority="low")["items"][0]["job_id"] == 3
    assert reader.list_rankings(lane="unknown")["items"][0]["job_id"] == 4
    assert all(r["fake_provider"] and r["prototype"] for r in page["items"])
    assert "profile_sha256" not in json.dumps(page)
    assert len(calls) == 4


@pytest.mark.parametrize("bad", ["job", "boolean_job", "source", "binding", "model", "schema"])
def test_wrong_identity_or_schema_never_succeeds(db_path, bad):
    store = RankingStore(sqlite3.connect(db_path))
    def provider(inv):
        reply = fake_reply(inv, "high")
        if bad == "job": reply["job_id"] = 99
        if bad == "boolean_job": reply["job_id"] = True
        if bad == "source": reply["source_sha256"] = "f" * 64
        if bad == "binding": reply["binding_sha256"] = "f" * 64
        if bad == "model": reply["response"]["model"] = "wrong"
        if bad == "schema": reply["response"]["answers"]["domain"]["choice"] = "invalid"
        return reply
    store.assess(source(), policy(), provider=provider, now="2026-11-13T01:00:00Z")
    data = RankingReader(db_path).coverage()
    assert data["freshness"]["absent"] == 1
    assert data["latest_attempt"]["failed"] == 1
    assert RankingReader(db_path).get_ranking(1)["ranking"] is None


def test_provider_cannot_mutate_frozen_invocation_or_policy(db_path):
    store = RankingStore(sqlite3.connect(db_path))
    pol = policy()

    def mutate_invocation(inv):
        inv["job_id"] = 99
        inv["binding_sha256"] = "f" * 64
        return fake_reply(inv, "high")

    store.assess(source(), pol, provider=mutate_invocation, now="2026-11-13T01:00:00Z")
    assert RankingReader(db_path).get_ranking(1)["ranking"] is None

    store.assess(source(2), pol, provider=lambda inv: _mutate_policy_and_reply(inv, pol), now="2026-11-13T02:00:00Z")
    detail = RankingReader(db_path).get_ranking(2)
    assert detail["ranking"]["priority"] == "high"
    assert detail["latest_attempt"]["state"] == "succeeded"


def _mutate_policy_and_reply(invocation, pol):
    pol["resolved_model"] = "fake-mutated-after-dispatch"
    return fake_reply(invocation, "high")


@pytest.mark.parametrize("revision", [True, 0, -1, {}, "", " padded "])
def test_invalid_source_revision_rejected_before_persistence(db_path, revision):
    store = RankingStore(sqlite3.connect(db_path))
    with pytest.raises(ValueError, match="source revision"):
        store.capture(source(source_revision=revision), policy(), now="2026-11-13T01:00:00Z")


@pytest.mark.parametrize("captured", ["2026-11-13T00:00:00", "2026-11-13T01:00:00+01:00", "bad"])
def test_captured_time_must_be_explicit_utc(db_path, captured):
    with pytest.raises(ValueError, match="captured time|UTC"):
        RankingStore(sqlite3.connect(db_path)).capture(
            source(captured_time=captured), policy(), now="2026-11-13T01:00:00Z",
        )


def test_unfiltered_rank_order_uses_tier_then_utc_instant_then_job_id(db_path):
    store = RankingStore(sqlite3.connect(db_path))
    for ident, published, domain in (
        (1, "2026-11-13T01:00:00+01:00", "compiler"),
        (2, "2026-11-13T00:30:00Z", "analytics"),
        (3, "2026-11-13", "analytics"),
    ):
        pol = policy()
        pol["question_set"]["questions"][0]["criteria"]["analytics"] = "Analysis duties"

        def provider(inv, domain=domain, tier="medium" if ident == 2 else "high"):
            reply = fake_reply(inv, tier)
            answer = reply["response"]["answers"]["domain"]
            answer["choice"] = domain
            answer["probabilities"] = {key: int(key == domain) for key in answer["probabilities"]}
            return reply

        store.assess(source(ident, publication_time=published), pol, provider=provider, now="2026-11-13T01:00:00Z")
    rows = RankingReader(db_path).list_rankings(lane="raw")["items"]
    assert [(row["domain"], row["job_id"], row["priority"]) for row in rows] == [
        ("compiler", 1, "high"), ("analytics", 3, "high"), ("analytics", 2, "medium"),
    ]


@pytest.mark.parametrize("change", ["source", "location", "profile", "question", "model"])
def test_changed_binding_failed_refresh_preserves_stale(db_path, change):
    store = RankingStore(sqlite3.connect(db_path))
    store.assess(source(), policy(), provider=lambda inv: fake_reply(inv, "high"), now="2026-11-13T01:00:00Z")
    job, pol = source(), policy()
    if change == "source": job["description"] += " Changed duties."
    if change == "location": job["location"] = "London"
    if change == "profile": pol["profile_sha256"] = "c" * 64
    if change == "question": pol["question_context_domain_sha256"] = "c" * 64
    if change == "model": pol["resolved_model"] = "fake-jev-p3-v2"
    store.assess(job, pol, provider=lambda _: (_ for _ in ()).throw(TimeoutError()), now="2026-11-13T02:00:00Z")
    reader = RankingReader(db_path); detail = reader.get_ranking(1)
    assert detail["freshness"] == "stale" and detail["ranking"]["priority"] == "high"
    assert detail["latest_attempt"]["state"] == "failed"
    assert reader.list_rankings()["items"] == []
    assert reader.list_rankings(lane="raw")["items"][0]["freshness"] == "stale"


def test_snapshot_cursor_pins_attempts_sources_and_new_results(db_path):
    store = RankingStore(sqlite3.connect(db_path))
    for i in range(1, 4):
        store.assess(source(i), policy(), provider=lambda inv: fake_reply(inv, "high"), now="2026-11-13T01:00:00Z")
    reader = RankingReader(db_path); first = reader.list_rankings(limit=1)
    store.assess(source(2, description="Changed"), policy(), provider=lambda _: (_ for _ in ()).throw(TimeoutError()), now="2026-11-13T02:00:00Z")
    store.assess(source(4), policy(), provider=lambda inv: fake_reply(inv, "high"), now="2026-11-13T02:00:00Z")
    second = reader.list_rankings(limit=1, cursor=first["next_cursor"])
    third = reader.list_rankings(limit=1, cursor=second["next_cursor"])
    assert [first["items"][0]["job_id"], second["items"][0]["job_id"], third["items"][0]["job_id"]] == [1, 2, 3]
    assert second["items"][0]["freshness"] == "current"
    assert reader.coverage(watermark=first["watermark"])["freshness"]["current"] == 3
    assert reader.coverage()["freshness"] == {"current": 3, "stale": 1, "absent": 0}
    with pytest.raises(ValueError): reader.list_rankings(priority="low", cursor=first["next_cursor"])
    with pytest.raises(ValueError): reader.list_rankings(cursor="broken")
