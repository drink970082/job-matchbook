import json
from pathlib import Path

import pytest

from ats_worker.preselection.profile import (
    ProfileValidationError,
    load_profile_text,
    measure_context,
    profile_from_value,
    render_profile,
)


FIXTURE = Path(__file__).parent / "fixtures/preselection_profile.synthetic.json"


def test_profile_renders_all_blocks_exactly_in_declared_order_and_hashes_stably():
    profile = load_profile_text(FIXTURE.read_text(encoding="utf-8"))
    rendered = render_profile(profile)

    assert rendered == (
        "AS OF 2026-01-02\n"
        "BACKGROUND\n"
        "Built a service in a fictional internship; production ownership stayed with the team.\n"
        "Used data analysis in an academic project; professional depth is not established.\n"
        "SEARCH\n"
        "Interested in engineering and product work; family priority is unresolved.\n"
        "Treat unstated authorization and missing requirements as unknown.\n"
    )
    fixture_text = FIXTURE.read_text(encoding="utf-8")
    assert profile.identity_sha256 == profile_from_value(json.loads(fixture_text)).identity_sha256
    reordered = json.loads(FIXTURE.read_text(encoding="utf-8"))
    reordered["background"].reverse()
    assert profile.identity_sha256 != profile_from_value(reordered).identity_sha256
    assert "professional depth is not established" in rendered
    assert "priority is unresolved" in rendered


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(extra="forbidden"), "unknown field"),
        (lambda value: value.update(schema=True), "integer 1"),
        (lambda value: value.update(version=""), "version"),
        (lambda value: value.update(as_of="2026-02-30"), "calendar date"),
        (lambda value: value.update(status=[]), "status"),
        (lambda value: value.update(background={}), "array"),
        (lambda value: value["background"][0].update(source="archive"), "unknown field"),
        (lambda value: value["background"][0].update(text="two\nparagraphs"), "one paragraph"),
        (lambda value: value["background"][0].update(text=" padded "), "trimmed text"),
    ],
)
def test_profile_rejects_invalid_or_unallowlisted_values(change, message):
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    change(value)
    with pytest.raises(ProfileValidationError, match=message):
        profile_from_value(value)


def test_profile_rejects_duplicate_ids_across_both_sections_and_duplicate_json_members():
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["preferences"][0]["id"] = value["background"][0]["id"]
    with pytest.raises(ProfileValidationError, match="IDs must be unique"):
        profile_from_value(value)
    with pytest.raises(ProfileValidationError, match="duplicate JSON"):
        load_profile_text('{"schema":1,"schema":1}')


def test_context_budget_is_measurement_only_and_never_truncates():
    profile = load_profile_text(FIXTURE.read_text(encoding="utf-8"))
    rendered = render_profile(profile)
    seen: list[str] = []

    measured = measure_context(rendered, lambda value: seen.append(value) or 25, soft_limit=10)

    assert seen == [rendered]
    assert measured == {"token_count": 25, "soft_limit": 10, "over_budget": True}
    assert render_profile(profile) == rendered
    assert measure_context(rendered, lambda _: 10, soft_limit=10)["over_budget"] is False


@pytest.mark.parametrize(
    "counter,limit",
    [(lambda _: True, 1), (lambda _: -1, 1), (lambda _: 1, 0)],
)
def test_context_measurement_rejects_invalid_counter_contract(counter, limit):
    with pytest.raises((TypeError, ValueError)):
        measure_context("unchanged", counter, soft_limit=limit)
